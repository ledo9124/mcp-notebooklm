"""Capability adapter over ``NotebookLMClient`` for BA workflows.

Later BA modules should depend on :class:`BACapabilityAdapter` rather than
reaching into ``NotebookLMClient`` sub-clients directly. This module owns:

- capability support/degradation declarations
- normalization of inconsistent SDK shapes that matter to BA workflow code
- one obvious seam for future BA orchestration, rendering, and validation code
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlparse

from notebooklm.exceptions import (
    NotebookLMError,
    SourceNotFoundError,
    SourceProcessingError,
    SourceTimeoutError,
    ValidationError,
)
from pydantic import ValidationError as PydanticValidationError
from notebooklm.rpc.types import ExportType, ReportFormat
from notebooklm.types import (
    Artifact,
    AskResult,
    ChatReference,
    ChatSettings,
    GenerationStatus,
    Note,
    Source,
    SourceFulltext,
)
from .models import (
    HaltRecommendation,
    SourceContentKind,
    SourceLifecycleStatus,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceRegistrationInput,
    SourceRegistrationResult,
    SourceRegistrationWarning,
    SourceRegistrationWarningCode,
    SourceType,
)

MODULE_PURPOSE = (
    "Translate NotebookLMClient primitives into normalized BA capabilities and payloads."
)

OWNS = (
    "NotebookLM capability normalization",
    "Source/note/research/artifact parity shims",
    "Thin BA-facing accessors over NotebookLMClient",
)

MUST_NOT_OWN = (
    "MCP tool registration",
    "Filesystem run persistence",
    "Prompt templates",
    "Final bundle rendering",
)

ADAPTER_USAGE_RULES = (
    "Later BA modules should depend on BACapabilityAdapter instead of calling NotebookLMClient sub-clients directly.",
    "Keep unsupported/degraded capability handling centralized in this module.",
    "Normalize inconsistent SDK return shapes here before downstream BA code depends on them.",
)


class BACapabilityState(str, Enum):
    """Availability state for a BA-relevant upstream capability."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"


class BACapabilityName(str, Enum):
    """Named BA-relevant capabilities exposed through the adapter."""

    SOURCE_INGEST = "source_ingest"
    SOURCE_SNAPSHOT = "source_snapshot"
    NOTE_CRUD = "note_crud"
    NOTE_TO_SOURCE_BRIDGE = "note_to_source_bridge"
    NOTE_EXPORT = "note_export"
    NOTEBOOK_CHAT_SETTINGS = "notebook_chat_settings"
    GLOBAL_OUTPUT_LANGUAGE = "global_output_language"
    RESEARCH = "research"
    REPORT_ARTIFACTS = "report_artifacts"
    DATA_TABLE_ARTIFACTS = "data_table_artifacts"
    MIND_MAP_ARTIFACTS = "mind_map_artifacts"


class BASourceReadinessState(str, Enum):
    """Normalized readiness state for source-ingest workflows."""

    READY = "ready"
    PROCESSING = "processing"
    FAILED = "failed"
    DEGRADED = "degraded"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class BACapabilitySupport:
    """Centralized support declaration for one BA-relevant capability."""

    name: BACapabilityName
    state: BACapabilityState
    summary: str
    details: str = ""

    @property
    def is_usable(self) -> bool:
        """Return ``True`` when the capability is callable by BA code."""
        return self.state is not BACapabilityState.UNSUPPORTED


@dataclass(frozen=True, slots=True)
class BACitation:
    """Normalized citation payload for BA ask flows."""

    source_id: str
    title: str | None = None
    url: str | None = None
    quote: str | None = None
    location: str | None = None


@dataclass(frozen=True, slots=True)
class BAStructuredAskResult:
    """BA-friendly wrapper over ``AskResult`` with normalized citations."""

    answer: str
    conversation_id: str
    turn_number: int
    is_follow_up: bool
    citations: tuple[BACitation, ...] = ()


@dataclass(frozen=True, slots=True)
class BASourceSnapshot:
    """Full-fidelity source snapshot for deterministic BA workflows."""

    notebook_id: str
    source_id: str
    title: str
    source_type: str
    status: int
    is_ready: bool
    url: str | None
    content: str
    char_count: int
    guide_summary: str
    guide_keywords: tuple[str, ...]
    is_fresh: bool


@dataclass(frozen=True, slots=True)
class BASourceOperationResult:
    """Normalized source ingest/readiness result for later BA persistence."""

    source_key: str | None
    notebook_id: str
    notebook_source_id: str | None
    title: str
    readiness_state: BASourceReadinessState
    source_type: str | None = None
    status: int | None = None
    degraded_reason: str | None = None
    support: BACapabilitySupport | None = None


class BAReadyTimeoutPolicy(str, Enum):
    """Policy for handling source-readiness timeouts."""

    FAIL = "FAIL"
    DEGRADE = "DEGRADE"


@dataclass(frozen=True, slots=True)
class BAIngestWaitResult:
    """Normalized result for a manifest-driven ingest-and-wait pass."""

    notebook_id: str
    manifest: SourceManifestDocument
    source_results: tuple[BASourceOperationResult, ...]
    selected_source_keys: tuple[str, ...] = ()
    poll_budget_seconds: float = 120.0
    ready_timeout_policy: BAReadyTimeoutPolicy = BAReadyTimeoutPolicy.DEGRADE
    elapsed_seconds: float = 0.0
    recommendation: HaltRecommendation = HaltRecommendation.PROCEED
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BAObjectRef:
    """Reference to a notebook object created or returned by the adapter."""

    notebook_id: str
    object_id: str | None
    kind: Literal["note", "source"]
    title: str
    support: BACapabilitySupport | None = None


@dataclass(frozen=True, slots=True)
class BAResearchSource:
    """Normalized research source candidate."""

    title: str
    url: str = ""


@dataclass(frozen=True, slots=True)
class BAResearchSession:
    """Normalized research session handle."""

    notebook_id: str
    task_id: str
    report_id: str | None
    query: str
    mode: str


@dataclass(frozen=True, slots=True)
class BAResearchPollResult:
    """Normalized research poll payload."""

    task_id: str | None
    status: str
    query: str = ""
    summary: str = ""
    sources: tuple[BAResearchSource, ...] = ()


@dataclass(frozen=True, slots=True)
class BAArtifactTask:
    """Normalized artifact-generation task status."""

    notebook_id: str
    artifact_kind: str
    task_id: str
    status: str
    error: str | None = None
    error_code: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_generation_status(
        cls,
        notebook_id: str,
        artifact_kind: str,
        status: GenerationStatus,
    ) -> "BAArtifactTask":
        """Build a BA task wrapper from the SDK generation status."""
        return cls(
            notebook_id=notebook_id,
            artifact_kind=artifact_kind,
            task_id=status.task_id,
            status=status.status,
            error=status.error,
            error_code=status.error_code,
            metadata=status.metadata,
        )


@dataclass(frozen=True, slots=True)
class BAMindMapResult:
    """Mind-map generation result with explicit degraded support metadata."""

    notebook_id: str
    note_id: str | None
    mind_map: Any
    support: BACapabilitySupport


class BAAdapterError(NotebookLMError):
    """Base exception for BA adapter failures."""


class UnsupportedBACapabilityError(BAAdapterError):
    """Raised when a BA workflow asks for an unsupported capability."""

    def __init__(self, support: BACapabilitySupport):
        self.support = support
        message = (
            f"BA capability '{support.name.value}' is {support.state.value}: {support.summary}"
        )
        if support.details:
            message = f"{message} {support.details}"
        super().__init__(message)


_CAPABILITY_SUPPORT: dict[BACapabilityName, BACapabilitySupport] = {
    BACapabilityName.SOURCE_INGEST: BACapabilitySupport(
        name=BACapabilityName.SOURCE_INGEST,
        state=BACapabilityState.AVAILABLE,
        summary="URL, text, file, and Drive source ingest are available through the SDK.",
        details="The adapter should use SDK source methods directly instead of the narrower MCP source tool set.",
    ),
    BACapabilityName.SOURCE_SNAPSHOT: BACapabilitySupport(
        name=BACapabilityName.SOURCE_SNAPSHOT,
        state=BACapabilityState.AVAILABLE,
        summary="Full-fidelity source snapshots are available through the SDK.",
        details=(
            "Snapshotting should use get_fulltext/get_guide/check_freshness directly instead "
            "of preview-capped MCP content helpers."
        ),
    ),
    BACapabilityName.NOTE_CRUD: BACapabilitySupport(
        name=BACapabilityName.NOTE_CRUD,
        state=BACapabilityState.AVAILABLE,
        summary="Notebook notes support CRUD operations through the SDK.",
    ),
    BACapabilityName.NOTE_TO_SOURCE_BRIDGE: BACapabilitySupport(
        name=BACapabilityName.NOTE_TO_SOURCE_BRIDGE,
        state=BACapabilityState.DEGRADED,
        summary="The public SDK does not expose a real note-to-source conversion method.",
        details=(
            "The adapter can only synthesize a text source via sources.add_text(), which is not "
            "the same as converting an existing NotebookLM note."
        ),
    ),
    BACapabilityName.NOTE_EXPORT: BACapabilitySupport(
        name=BACapabilityName.NOTE_EXPORT,
        state=BACapabilityState.UNSUPPORTED,
        summary="The public SDK does not currently implement note export.",
        details="Docstrings mention export/conversion, but there is no callable note export API surface yet.",
    ),
    BACapabilityName.NOTEBOOK_CHAT_SETTINGS: BACapabilitySupport(
        name=BACapabilityName.NOTEBOOK_CHAT_SETTINGS,
        state=BACapabilityState.AVAILABLE,
        summary="Notebook-scoped chat settings are available and typed.",
    ),
    BACapabilityName.GLOBAL_OUTPUT_LANGUAGE: BACapabilitySupport(
        name=BACapabilityName.GLOBAL_OUTPUT_LANGUAGE,
        state=BACapabilityState.AVAILABLE,
        summary="Account-global output language is available through the SDK settings API.",
    ),
    BACapabilityName.RESEARCH: BACapabilitySupport(
        name=BACapabilityName.RESEARCH,
        state=BACapabilityState.AVAILABLE,
        summary="Raw research start/poll/import controls are available through the SDK.",
    ),
    BACapabilityName.REPORT_ARTIFACTS: BACapabilitySupport(
        name=BACapabilityName.REPORT_ARTIFACTS,
        state=BACapabilityState.AVAILABLE,
        summary="Report generation, wait, download, and export are available through the SDK.",
    ),
    BACapabilityName.DATA_TABLE_ARTIFACTS: BACapabilitySupport(
        name=BACapabilityName.DATA_TABLE_ARTIFACTS,
        state=BACapabilityState.AVAILABLE,
        summary="Data-table generation, wait, download, and export are available through the SDK.",
    ),
    BACapabilityName.MIND_MAP_ARTIFACTS: BACapabilitySupport(
        name=BACapabilityName.MIND_MAP_ARTIFACTS,
        state=BACapabilityState.DEGRADED,
        summary="Mind maps are available, but they are persisted through the notes subsystem.",
        details=(
            "Mind-map generation returns a payload plus note_id instead of a normal generation task, "
            "so downstream BA code should treat it as a note-backed artifact seam."
        ),
    ),
}

ADAPTER_CAPABILITIES = tuple(_CAPABILITY_SUPPORT.values())

_UNSET = object()


def _coerce_capability_name(capability: BACapabilityName | str) -> BACapabilityName:
    """Normalize a capability identifier to ``BACapabilityName``."""
    if isinstance(capability, BACapabilityName):
        return capability
    try:
        return BACapabilityName(capability)
    except ValueError as exc:
        raise ValidationError(f"Unknown BA capability: {capability!r}") from exc


def _coerce_report_format(report_format: ReportFormat | str) -> ReportFormat:
    """Normalize report format strings to the SDK enum."""
    if isinstance(report_format, ReportFormat):
        return report_format
    try:
        return ReportFormat(report_format)
    except ValueError as exc:
        raise ValidationError(
            f"Invalid report_format {report_format!r}. "
            f"Use one of: {', '.join(item.value for item in ReportFormat)}"
        ) from exc


def _coerce_export_type(export_type: ExportType | str) -> ExportType:
    """Normalize export destination values to the SDK enum."""
    if isinstance(export_type, ExportType):
        return export_type
    normalized = export_type.strip().lower()
    mapping = {
        "docs": ExportType.DOCS,
        "sheets": ExportType.SHEETS,
    }
    if normalized in mapping:
        return mapping[normalized]
    raise ValidationError("Invalid export_type. Use ExportType, 'docs', or 'sheets'.")


def _optional_list(values: Sequence[str] | None) -> list[str] | None:
    """Convert optional sequences to concrete lists for SDK calls."""
    if values is None:
        return None
    return list(values)


def _citation_location(reference: ChatReference) -> str | None:
    """Return a human-readable citation location string."""
    if reference.start_char is None and reference.end_char is None:
        return None
    if reference.start_char is not None and reference.end_char is not None:
        return f"{reference.start_char}-{reference.end_char}"
    if reference.start_char is not None:
        return str(reference.start_char)
    return str(reference.end_char)


def _source_readiness_state(source: Source) -> BASourceReadinessState:
    """Map SDK source status to a BA-friendly readiness state."""
    if source.is_ready:
        return BASourceReadinessState.READY
    if source.is_error:
        return BASourceReadinessState.FAILED
    return BASourceReadinessState.PROCESSING


def _is_http_url(value: str) -> bool:
    """Return ``True`` for HTTP(S) URLs."""
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_file_path(value: str, workspace_root: Path) -> bool:
    """Best-effort path detection for pre-ingest source registration."""
    candidate = Path(value)
    resolved = candidate if candidate.is_absolute() else workspace_root / candidate
    return (
        candidate.is_absolute()
        or resolved.exists()
        or "/" in value
        or "\\" in value
        or bool(candidate.suffix)
    )


def _infer_source_content_kind(value: str, workspace_root: Path) -> SourceContentKind:
    """Infer source content kind when the caller does not provide one."""
    if _is_http_url(value):
        return SourceContentKind.URL
    if "\n" in value or "\r" in value:
        return SourceContentKind.INLINE_TEXT
    if _looks_like_file_path(value, workspace_root):
        return SourceContentKind.FILE_PATH
    return SourceContentKind.INLINE_TEXT


def _default_source_title(
    source_key: str,
    source_ref: str,
    content_kind: SourceContentKind,
    explicit_title: str | None,
) -> str | None:
    """Derive a stable display title when the caller does not provide one."""
    if explicit_title:
        return explicit_title.strip()
    if content_kind is SourceContentKind.FILE_PATH:
        return Path(source_ref).name or source_key
    if content_kind is SourceContentKind.URL:
        parsed = urlparse(source_ref)
        last_segment = Path(parsed.path).name
        return last_segment or source_key
    if content_kind is SourceContentKind.INLINE_TEXT:
        return source_key.replace("-", " ").replace("_", " ").title() or source_key
    return None


def _coerce_timeout_policy(
    ready_timeout_policy: BAReadyTimeoutPolicy | str,
) -> BAReadyTimeoutPolicy:
    if isinstance(ready_timeout_policy, BAReadyTimeoutPolicy):
        return ready_timeout_policy
    return BAReadyTimeoutPolicy(str(ready_timeout_policy).upper())


def _lifecycle_status_from_readiness(
    readiness_state: BASourceReadinessState,
) -> SourceLifecycleStatus:
    if readiness_state is BASourceReadinessState.READY:
        return SourceLifecycleStatus.READY
    if readiness_state is BASourceReadinessState.PROCESSING:
        return SourceLifecycleStatus.INGESTING
    if readiness_state is BASourceReadinessState.DEGRADED:
        return SourceLifecycleStatus.DEGRADED
    return SourceLifecycleStatus.FAILED


def _ingest_recommendation(
    source_results: Sequence[BASourceOperationResult],
    ready_timeout_policy: BAReadyTimeoutPolicy,
) -> HaltRecommendation:
    if any(
        result.readiness_state in {BASourceReadinessState.FAILED, BASourceReadinessState.MISSING}
        for result in source_results
    ):
        return HaltRecommendation.HALT
    if any(
        result.readiness_state in {BASourceReadinessState.DEGRADED, BASourceReadinessState.PROCESSING}
        for result in source_results
    ):
        if ready_timeout_policy is BAReadyTimeoutPolicy.FAIL:
            return HaltRecommendation.HALT
        return HaltRecommendation.DEGRADE
    return HaltRecommendation.PROCEED


class BACapabilityAdapter:
    """Central BA-facing seam over a connected ``NotebookLMClient`` instance."""

    def __init__(self, client: Any):
        self._client = client

    @property
    def client(self) -> Any:
        """Expose the wrapped client for rare debugging/introspection cases."""
        return self._client

    def describe_capabilities(self) -> dict[str, BACapabilitySupport]:
        """Return the adapter's centralized capability support catalog."""
        return {name.value: support for name, support in _CAPABILITY_SUPPORT.items()}

    def get_capability(self, capability: BACapabilityName | str) -> BACapabilitySupport:
        """Return support metadata for a named capability."""
        return _CAPABILITY_SUPPORT[_coerce_capability_name(capability)]

    def require_capability(
        self,
        capability: BACapabilityName | str,
        *,
        allow_degraded: bool = True,
    ) -> BACapabilitySupport:
        """Return support metadata or raise when the capability is not safe to use."""
        support = self.get_capability(capability)
        if support.state is BACapabilityState.UNSUPPORTED:
            raise UnsupportedBACapabilityError(support)
        if support.state is BACapabilityState.DEGRADED and not allow_degraded:
            raise UnsupportedBACapabilityError(support)
        return support

    async def list_sources(self, notebook_id: str) -> list[Source]:
        """List notebook sources through the centralized ingest/snapshot seam."""
        self.require_capability(BACapabilityName.SOURCE_INGEST)
        return await self._client.sources.list(notebook_id)

    async def get_source(self, notebook_id: str, source_id: str) -> Source | None:
        """Get source metadata through the centralized ingest/snapshot seam."""
        self.require_capability(BACapabilityName.SOURCE_INGEST)
        return await self._client.sources.get(notebook_id, source_id)

    async def ingest_url(
        self,
        notebook_id: str,
        url: str,
        *,
        wait: bool = False,
        wait_timeout: float = 120.0,
    ) -> Source:
        """Add a URL source."""
        self.require_capability(BACapabilityName.SOURCE_INGEST)
        return await self._client.sources.add_url(
            notebook_id,
            url,
            wait=wait,
            wait_timeout=wait_timeout,
        )

    async def ingest_text(
        self,
        notebook_id: str,
        title: str,
        content: str,
        *,
        wait: bool = False,
        wait_timeout: float = 120.0,
    ) -> Source:
        """Add a pasted-text source."""
        self.require_capability(BACapabilityName.SOURCE_INGEST)
        return await self._client.sources.add_text(
            notebook_id,
            title,
            content,
            wait=wait,
            wait_timeout=wait_timeout,
        )

    async def ingest_file(
        self,
        notebook_id: str,
        file_path: str | Path,
        *,
        mime_type: str | None = None,
        wait: bool = False,
        wait_timeout: float = 120.0,
    ) -> Source:
        """Add a file source."""
        self.require_capability(BACapabilityName.SOURCE_INGEST)
        return await self._client.sources.add_file(
            notebook_id,
            file_path,
            mime_type=mime_type,
            wait=wait,
            wait_timeout=wait_timeout,
        )

    async def ingest_drive(
        self,
        notebook_id: str,
        file_id: str,
        title: str,
        *,
        mime_type: str = "application/vnd.google-apps.document",
        wait: bool = False,
        wait_timeout: float = 120.0,
    ) -> Source:
        """Add a Google Drive source."""
        self.require_capability(BACapabilityName.SOURCE_INGEST)
        return await self._client.sources.add_drive(
            notebook_id,
            file_id,
            title,
            mime_type=mime_type,
            wait=wait,
            wait_timeout=wait_timeout,
        )

    async def wait_for_source(
        self,
        notebook_id: str,
        source_id: str,
        *,
        timeout: float = 120.0,
    ) -> Source:
        """Wait for a source to reach READY status."""
        self.require_capability(BACapabilityName.SOURCE_INGEST)
        return await self._client.sources.wait_until_ready(
            notebook_id,
            source_id,
            timeout=timeout,
        )

    async def collect_source_snapshot(
        self,
        notebook_id: str,
        source_id: str,
    ) -> BASourceSnapshot:
        """Collect a full BA snapshot for one source."""
        self.require_capability(BACapabilityName.SOURCE_SNAPSHOT)
        source = await self._client.sources.get(notebook_id, source_id)
        if source is None:
            raise SourceNotFoundError(source_id)

        fulltext, guide, is_fresh = await asyncio.gather(
            self._client.sources.get_fulltext(notebook_id, source_id),
            self._client.sources.get_guide(notebook_id, source_id),
            self._client.sources.check_freshness(notebook_id, source_id),
        )

        summary = guide.get("summary", "") if isinstance(guide, dict) else ""
        keywords_raw = guide.get("keywords", []) if isinstance(guide, dict) else []
        keywords = tuple(str(keyword) for keyword in keywords_raw if isinstance(keyword, str))

        title = fulltext.title or source.title or source_id
        url = fulltext.url or source.url
        return BASourceSnapshot(
            notebook_id=notebook_id,
            source_id=source_id,
            title=title,
            source_type=source.kind.value,
            status=source.status,
            is_ready=source.is_ready,
            url=url,
            content=fulltext.content,
            char_count=fulltext.char_count,
            guide_summary=str(summary or ""),
            guide_keywords=keywords,
            is_fresh=is_fresh,
        )

    async def collect_source_snapshots(
        self,
        notebook_id: str,
        source_ids: Sequence[str],
    ) -> list[BASourceSnapshot]:
        """Collect full BA snapshots for multiple sources."""
        self.require_capability(BACapabilityName.SOURCE_SNAPSHOT)
        tasks = [self.collect_source_snapshot(notebook_id, source_id) for source_id in source_ids]
        return list(await asyncio.gather(*tasks))

    def normalize_source_result(
        self,
        notebook_id: str,
        source: Source | None,
        *,
        source_key: str | None = None,
        readiness_state: BASourceReadinessState | None = None,
        degraded_reason: str | None = None,
        support: BACapabilitySupport | None = None,
    ) -> BASourceOperationResult:
        """Normalize a source object into a BA-friendly ingest/readiness envelope."""
        resolved_support = support or self.get_capability(BACapabilityName.SOURCE_INGEST)
        if source is None:
            return BASourceOperationResult(
                source_key=source_key,
                notebook_id=notebook_id,
                notebook_source_id=None,
                title=source_key or "",
                readiness_state=readiness_state or BASourceReadinessState.MISSING,
                degraded_reason=degraded_reason,
                support=resolved_support,
            )

        return BASourceOperationResult(
            source_key=source_key,
            notebook_id=notebook_id,
            notebook_source_id=source.id,
            title=source.title or source_key or source.id,
            readiness_state=readiness_state or _source_readiness_state(source),
            source_type=source.kind.value,
            status=source.status,
            degraded_reason=degraded_reason,
            support=resolved_support,
        )

    def register_sources(
        self,
        *,
        feature_key: str,
        run_id: str,
        source_entries: Sequence[SourceRegistrationInput | dict[str, Any]],
        update_only: bool = False,
        workspace_root: Path | str = Path("."),
    ) -> SourceRegistrationResult:
        """Normalize user source intent into a typed pre-ingest manifest."""
        workspace = Path(workspace_root).resolve()
        warnings: list[SourceRegistrationWarning] = []
        rows: list[SourceManifestRow] = []
        seen_source_keys: set[str] = set()

        for raw_entry in source_entries:
            source_key_hint = None
            if isinstance(raw_entry, dict):
                source_key_hint = raw_entry.get("source_key")

            try:
                entry = SourceRegistrationInput.model_validate(raw_entry)
            except PydanticValidationError as exc:
                warnings.append(
                    SourceRegistrationWarning(
                        code=SourceRegistrationWarningCode.INVALID_SOURCE_ENTRY,
                        message=f"Invalid source entry: {exc.errors()[0]['msg']}",
                        source_key=str(source_key_hint) if source_key_hint else None,
                    )
                )
                continue

            if entry.source_key in seen_source_keys:
                warnings.append(
                    SourceRegistrationWarning(
                        code=SourceRegistrationWarningCode.DUPLICATE_SOURCE_KEY,
                        message=(
                            f"Duplicate source_key '{entry.source_key}' was ignored; "
                            "source keys must stay stable and unique within a run."
                        ),
                        source_key=entry.source_key,
                    )
                )
                continue
            seen_source_keys.add(entry.source_key)

            normalized_ref = entry.path_or_url_or_text.strip()
            content_kind = entry.content_kind or _infer_source_content_kind(normalized_ref, workspace)

            if content_kind is SourceContentKind.URL:
                if not _is_http_url(normalized_ref):
                    warnings.append(
                        SourceRegistrationWarning(
                            code=SourceRegistrationWarningCode.INVALID_SOURCE_ENTRY,
                            message="URL sources must start with http:// or https://.",
                            source_key=entry.source_key,
                        )
                    )
                    continue
            elif content_kind is SourceContentKind.FILE_PATH:
                candidate = Path(normalized_ref)
                resolved = candidate if candidate.is_absolute() else workspace / candidate
                if not resolved.exists():
                    warnings.append(
                        SourceRegistrationWarning(
                            code=SourceRegistrationWarningCode.INVALID_SOURCE_ENTRY,
                            message=f"File source does not exist: {normalized_ref}",
                            source_key=entry.source_key,
                        )
                    )
                    continue
                normalized_ref = candidate.as_posix()
            elif not normalized_ref:
                warnings.append(
                    SourceRegistrationWarning(
                        code=SourceRegistrationWarningCode.INVALID_SOURCE_ENTRY,
                        message="Inline text sources must not be empty.",
                        source_key=entry.source_key,
                    )
                )
                continue

            rows.append(
                SourceManifestRow(
                    source_key=entry.source_key,
                    source_type=entry.source_type,
                    priority=entry.priority,
                    content_kind=content_kind,
                    source_ref=normalized_ref,
                    title=_default_source_title(
                        entry.source_key,
                        normalized_ref,
                        content_kind,
                        entry.title,
                    ),
                    notes=list(entry.notes),
                )
            )

        missing_critical_source_types: list[SourceType] = []
        if not update_only and not any(
            row.source_type is SourceType.PRIMARY_REQUIREMENT for row in rows
        ):
            missing_critical_source_types.append(SourceType.PRIMARY_REQUIREMENT)
            warnings.append(
                SourceRegistrationWarning(
                    code=SourceRegistrationWarningCode.MISSING_CRITICAL_SOURCE_TYPE,
                    message=(
                        "At least one PRIMARY_REQUIREMENT source is required before ingestion "
                        "unless the run is explicitly marked update-only."
                    ),
                )
            )

        manifest = SourceManifestDocument(
            run_id=run_id,
            feature_key=feature_key,
            rows=rows,
            warnings=[warning.message for warning in warnings],
        )
        return SourceRegistrationResult(
            manifest=manifest,
            warnings=warnings,
            missing_critical_source_types=missing_critical_source_types,
            update_only=update_only,
        )

    async def ingest_url_result(
        self,
        notebook_id: str,
        source_key: str,
        url: str,
        *,
        wait: bool = False,
        wait_timeout: float = 120.0,
    ) -> BASourceOperationResult:
        """Add a URL source and preserve ``source_key -> notebook_source_id`` linkage."""
        source = await self.ingest_url(
            notebook_id,
            url,
            wait=wait,
            wait_timeout=wait_timeout,
        )
        return self.normalize_source_result(notebook_id, source, source_key=source_key)

    async def ingest_text_result(
        self,
        notebook_id: str,
        source_key: str,
        title: str,
        content: str,
        *,
        wait: bool = False,
        wait_timeout: float = 120.0,
    ) -> BASourceOperationResult:
        """Add a text source and preserve ``source_key -> notebook_source_id`` linkage."""
        source = await self.ingest_text(
            notebook_id,
            title,
            content,
            wait=wait,
            wait_timeout=wait_timeout,
        )
        return self.normalize_source_result(notebook_id, source, source_key=source_key)

    async def ingest_file_result(
        self,
        notebook_id: str,
        source_key: str,
        file_path: str | Path,
        *,
        mime_type: str | None = None,
        wait: bool = False,
        wait_timeout: float = 120.0,
    ) -> BASourceOperationResult:
        """Add a file source and preserve ``source_key -> notebook_source_id`` linkage."""
        source = await self.ingest_file(
            notebook_id,
            file_path,
            mime_type=mime_type,
            wait=wait,
            wait_timeout=wait_timeout,
        )
        return self.normalize_source_result(notebook_id, source, source_key=source_key)

    async def ingest_drive_result(
        self,
        notebook_id: str,
        source_key: str,
        file_id: str,
        title: str,
        *,
        mime_type: str = "application/vnd.google-apps.document",
        wait: bool = False,
        wait_timeout: float = 120.0,
    ) -> BASourceOperationResult:
        """Add a Drive source and preserve ``source_key -> notebook_source_id`` linkage."""
        source = await self.ingest_drive(
            notebook_id,
            file_id,
            title,
            mime_type=mime_type,
            wait=wait,
            wait_timeout=wait_timeout,
        )
        return self.normalize_source_result(notebook_id, source, source_key=source_key)

    async def wait_for_source_result(
        self,
        notebook_id: str,
        source_key: str,
        source_id: str,
        *,
        timeout: float = 120.0,
    ) -> BASourceOperationResult:
        """Wait for source readiness and downgrade timeouts into typed result payloads."""
        support = self.get_capability(BACapabilityName.SOURCE_INGEST)
        try:
            source = await self.wait_for_source(
                notebook_id,
                source_id,
                timeout=timeout,
            )
            return self.normalize_source_result(
                notebook_id,
                source,
                source_key=source_key,
                support=support,
            )
        except SourceTimeoutError as exc:
            source = await self.get_source(notebook_id, source_id)
            return self.normalize_source_result(
                notebook_id,
                source,
                source_key=source_key,
                readiness_state=BASourceReadinessState.DEGRADED,
                degraded_reason=str(exc),
                support=support,
            )
        except SourceProcessingError as exc:
            source = await self.get_source(notebook_id, source_id)
            return self.normalize_source_result(
                notebook_id,
                source,
                source_key=source_key,
                readiness_state=BASourceReadinessState.FAILED,
                degraded_reason=str(exc),
                support=support,
            )
        except SourceNotFoundError as exc:
            return self.normalize_source_result(
                notebook_id,
                None,
                source_key=source_key,
                readiness_state=BASourceReadinessState.MISSING,
                degraded_reason=str(exc),
                support=support,
            )

    async def ingest_and_wait(
        self,
        notebook_id: str,
        manifest: SourceManifestDocument,
        *,
        source_keys: Sequence[str] | None = None,
        workspace_root: Path | str = Path("."),
        poll_budget_seconds: float = 120.0,
        ready_timeout_policy: BAReadyTimeoutPolicy | str = BAReadyTimeoutPolicy.DEGRADE,
    ) -> BAIngestWaitResult:
        """Ingest selected manifest rows and wait until they are ready or degraded."""
        timeout_policy = _coerce_timeout_policy(ready_timeout_policy)
        workspace = Path(workspace_root).resolve()
        warnings: list[str] = []
        selection_items: list[SourceManifestRow | BASourceOperationResult] = []

        if source_keys is None:
            selection_items.extend(
                row for row in manifest.rows if row.notebook_source_id is None
            )
            selected_source_keys = tuple(
                row.source_key for row in selection_items if isinstance(row, SourceManifestRow)
            )
        else:
            rows_by_key = {row.source_key: row for row in manifest.rows}
            seen_source_keys: set[str] = set()
            ordered_source_keys: list[str] = []
            for source_key in source_keys:
                if source_key in seen_source_keys:
                    continue
                seen_source_keys.add(source_key)
                ordered_source_keys.append(source_key)
                row = rows_by_key.get(source_key)
                if row is None:
                    warnings.append(f"source_key '{source_key}' was not present in the manifest.")
                    selection_items.append(
                        self.normalize_source_result(
                            notebook_id,
                            None,
                            source_key=source_key,
                            readiness_state=BASourceReadinessState.MISSING,
                            degraded_reason="Source key was not present in the manifest.",
                        )
                    )
                    continue
                selection_items.append(row)
            selected_source_keys = tuple(ordered_source_keys)

        started = monotonic()
        resolved_results: list[BASourceOperationResult | None] = [None] * len(selection_items)
        pending_waits: list[tuple[int, Any]] = []

        for index, item in enumerate(selection_items):
            if isinstance(item, BASourceOperationResult):
                resolved_results[index] = item
                continue

            row = item
            if row.notebook_source_id:
                pending_waits.append(
                    (
                        index,
                        self.wait_for_source_result(
                            notebook_id,
                            row.source_key,
                            row.notebook_source_id,
                            timeout=poll_budget_seconds,
                        ),
                    )
                )
                continue

            ingest_result = await self._ingest_manifest_row(
                notebook_id,
                row,
                workspace_root=workspace,
            )
            if (
                ingest_result.notebook_source_id
                and ingest_result.readiness_state is not BASourceReadinessState.READY
            ):
                pending_waits.append(
                    (
                        index,
                        self.wait_for_source_result(
                            notebook_id,
                            row.source_key,
                            ingest_result.notebook_source_id,
                            timeout=poll_budget_seconds,
                        ),
                    )
                )
                continue
            resolved_results[index] = ingest_result

        if pending_waits:
            wait_results = await asyncio.gather(*(coro for _, coro in pending_waits))
            for (index, _), wait_result in zip(pending_waits, wait_results, strict=True):
                resolved_results[index] = wait_result

        source_results = tuple(result for result in resolved_results if result is not None)
        result_map = {
            result.source_key: result for result in source_results if result.source_key is not None
        }
        result_warnings = [
            f"{result.source_key or result.title}: {result.degraded_reason}"
            for result in source_results
            if result.degraded_reason
        ]
        updated_rows = [
            row.model_copy(
                update={
                    "notebook_source_id": (
                        result_map[row.source_key].notebook_source_id or row.notebook_source_id
                    )
                    if row.source_key in result_map
                    else row.notebook_source_id,
                    "status": _lifecycle_status_from_readiness(
                        result_map[row.source_key].readiness_state
                    )
                    if row.source_key in result_map
                    else row.status,
                }
            )
            for row in manifest.rows
        ]
        updated_manifest = manifest.model_copy(
            update={
                "rows": updated_rows,
                "warnings": [*manifest.warnings, *warnings, *result_warnings],
            }
        )

        return BAIngestWaitResult(
            notebook_id=notebook_id,
            manifest=updated_manifest,
            source_results=source_results,
            selected_source_keys=selected_source_keys,
            poll_budget_seconds=poll_budget_seconds,
            ready_timeout_policy=timeout_policy,
            elapsed_seconds=monotonic() - started,
            recommendation=_ingest_recommendation(source_results, timeout_policy),
            warnings=tuple(warnings),
        )

    async def _ingest_manifest_row(
        self,
        notebook_id: str,
        row: SourceManifestRow,
        *,
        workspace_root: Path,
    ) -> BASourceOperationResult:
        support = self.get_capability(BACapabilityName.SOURCE_INGEST)
        try:
            if row.content_kind is SourceContentKind.URL:
                return await self.ingest_url_result(
                    notebook_id,
                    row.source_key,
                    row.source_ref,
                    wait=False,
                )
            if row.content_kind is SourceContentKind.FILE_PATH:
                candidate = Path(row.source_ref)
                file_path = candidate if candidate.is_absolute() else workspace_root / candidate
                return await self.ingest_file_result(
                    notebook_id,
                    row.source_key,
                    file_path,
                    wait=False,
                )
            if row.content_kind is SourceContentKind.INLINE_TEXT:
                return await self.ingest_text_result(
                    notebook_id,
                    row.source_key,
                    row.title or row.source_key,
                    row.source_ref,
                    wait=False,
                )
        except (NotebookLMError, OSError, ValueError) as exc:
            return self.normalize_source_result(
                notebook_id,
                None,
                source_key=row.source_key,
                readiness_state=BASourceReadinessState.FAILED,
                degraded_reason=str(exc),
                support=support,
            )

        return self.normalize_source_result(
            notebook_id,
            None,
            source_key=row.source_key,
            readiness_state=BASourceReadinessState.FAILED,
            degraded_reason=f"Unsupported content kind for BA ingest: {row.content_kind}",
            support=support,
        )

    async def ask_with_structured_citations(
        self,
        notebook_id: str,
        question: str,
        *,
        source_ids: Sequence[str] | None = None,
        conversation_id: str | None = None,
    ) -> BAStructuredAskResult:
        """Ask a question and normalize citations into BA-friendly objects."""
        ask_result: AskResult = await self._client.chat.ask(
            notebook_id,
            question,
            source_ids=_optional_list(source_ids),
            conversation_id=conversation_id,
        )

        referenced_ids = {reference.source_id for reference in ask_result.references if reference.source_id}
        source_metadata: dict[str, Source] = {}
        if referenced_ids:
            sources = await self._client.sources.list(notebook_id)
            source_metadata = {source.id: source for source in sources if source.id in referenced_ids}

        citations = tuple(
            BACitation(
                source_id=reference.source_id,
                title=source_metadata.get(reference.source_id).title
                if reference.source_id in source_metadata
                else None,
                url=source_metadata.get(reference.source_id).url
                if reference.source_id in source_metadata
                else None,
                quote=reference.cited_text,
                location=_citation_location(reference),
            )
            for reference in ask_result.references
        )

        return BAStructuredAskResult(
            answer=ask_result.answer,
            conversation_id=ask_result.conversation_id,
            turn_number=ask_result.turn_number,
            is_follow_up=ask_result.is_follow_up,
            citations=citations,
        )

    async def get_conversation_id(self, notebook_id: str) -> str | None:
        """Return the most recent conversation id for a notebook."""
        return await self._client.chat.get_conversation_id(notebook_id)

    async def get_conversation_history(
        self,
        notebook_id: str,
        *,
        limit: int = 100,
        conversation_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """Return normalized Q/A history."""
        return await self._client.chat.get_history(
            notebook_id,
            limit=limit,
            conversation_id=conversation_id,
        )

    async def list_notes(self, notebook_id: str) -> list[Note]:
        """List notebook notes."""
        self.require_capability(BACapabilityName.NOTE_CRUD)
        return await self._client.notes.list(notebook_id)

    async def get_note(self, notebook_id: str, note_id: str) -> Note | None:
        """Get a notebook note."""
        self.require_capability(BACapabilityName.NOTE_CRUD)
        return await self._client.notes.get(notebook_id, note_id)

    async def create_note(self, notebook_id: str, title: str, content: str) -> Note:
        """Create a notebook note."""
        self.require_capability(BACapabilityName.NOTE_CRUD)
        return await self._client.notes.create(notebook_id, title, content)

    async def update_note(
        self,
        notebook_id: str,
        note_id: str,
        *,
        title: str,
        content: str,
    ) -> None:
        """Update a notebook note."""
        self.require_capability(BACapabilityName.NOTE_CRUD)
        await self._client.notes.update(notebook_id, note_id, content, title)

    async def delete_note(self, notebook_id: str, note_id: str) -> bool:
        """Delete a notebook note."""
        self.require_capability(BACapabilityName.NOTE_CRUD)
        return await self._client.notes.delete(notebook_id, note_id)

    async def create_text_source_from_note_content(
        self,
        notebook_id: str,
        *,
        title: str,
        content: str,
        wait: bool = False,
        wait_timeout: float = 120.0,
    ) -> BAObjectRef:
        """Create a text source from synthesized note content.

        This is intentionally explicit about the degraded semantics. The SDK does
        not expose a true note-conversion method today, so the adapter uses
        ``sources.add_text()`` and marks the returned support state accordingly.
        """
        support = self.require_capability(BACapabilityName.NOTE_TO_SOURCE_BRIDGE)
        source = await self._client.sources.add_text(
            notebook_id,
            title,
            content,
            wait=wait,
            wait_timeout=wait_timeout,
        )
        return BAObjectRef(
            notebook_id=notebook_id,
            object_id=source.id or None,
            kind="source",
            title=source.title or title,
            support=support,
        )

    async def export_note(
        self,
        notebook_id: str,
        note_id: str,
        *,
        title: str = "Export",
    ) -> None:
        """Raise explicitly until note export exists in the public SDK."""
        del notebook_id, note_id, title
        self.require_capability(BACapabilityName.NOTE_EXPORT, allow_degraded=False)

    async def get_notebook_chat_settings(
        self,
        notebook_id: str,
        *,
        strict: bool = True,
    ) -> ChatSettings:
        """Read notebook-scoped chat settings."""
        self.require_capability(BACapabilityName.NOTEBOOK_CHAT_SETTINGS)
        return await self._client.chat.get_settings(notebook_id, strict=strict)

    async def set_notebook_chat_settings(
        self,
        notebook_id: str,
        settings: ChatSettings,
    ) -> None:
        """Set notebook-scoped chat settings absolutely."""
        self.require_capability(BACapabilityName.NOTEBOOK_CHAT_SETTINGS)
        await self._client.chat.set_settings(notebook_id, settings)

    async def update_notebook_chat_settings(
        self,
        notebook_id: str,
        *,
        goal: Any = _UNSET,
        response_length: Any = _UNSET,
        custom_prompt: Any = _UNSET,
        strict: bool = True,
    ) -> ChatSettings:
        """Patch notebook-scoped chat settings without leaking raw SDK sentinels."""
        self.require_capability(BACapabilityName.NOTEBOOK_CHAT_SETTINGS)
        kwargs: dict[str, Any] = {"strict": strict}
        if goal is not _UNSET:
            kwargs["goal"] = goal
        if response_length is not _UNSET:
            kwargs["response_length"] = response_length
        if custom_prompt is not _UNSET:
            kwargs["custom_prompt"] = custom_prompt
        return await self._client.chat.update_settings(notebook_id, **kwargs)

    async def reset_notebook_chat_settings(self, notebook_id: str) -> None:
        """Reset notebook-scoped chat settings to defaults."""
        self.require_capability(BACapabilityName.NOTEBOOK_CHAT_SETTINGS)
        await self._client.chat.reset_settings(notebook_id)

    async def get_output_language(self) -> str | None:
        """Read the account-global output language."""
        self.require_capability(BACapabilityName.GLOBAL_OUTPUT_LANGUAGE)
        return await self._client.settings.get_output_language()

    async def set_output_language(self, language: str) -> str | None:
        """Set the account-global output language."""
        self.require_capability(BACapabilityName.GLOBAL_OUTPUT_LANGUAGE)
        return await self._client.settings.set_output_language(language)

    async def start_research(
        self,
        notebook_id: str,
        query: str,
        *,
        source: str = "web",
        mode: str = "fast",
    ) -> BAResearchSession | None:
        """Start a research session and normalize the handle."""
        self.require_capability(BACapabilityName.RESEARCH)
        result = await self._client.research.start(
            notebook_id,
            query,
            source=source,
            mode=mode,
        )
        if result is None:
            return None
        task_id = result.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return None
        report_id = result.get("report_id")
        return BAResearchSession(
            notebook_id=notebook_id,
            task_id=task_id,
            report_id=str(report_id) if report_id else None,
            query=str(result.get("query", query)),
            mode=str(result.get("mode", mode)),
        )

    async def poll_research(self, notebook_id: str) -> BAResearchPollResult:
        """Poll a research session and normalize the result."""
        self.require_capability(BACapabilityName.RESEARCH)
        result = await self._client.research.poll(notebook_id)
        sources_raw = result.get("sources", []) if isinstance(result, dict) else []
        sources = tuple(
            BAResearchSource(
                title=str(source_data.get("title", "")),
                url=str(source_data.get("url", "")),
            )
            for source_data in sources_raw
            if isinstance(source_data, dict)
        )
        task_id = result.get("task_id") if isinstance(result, dict) else None
        return BAResearchPollResult(
            task_id=str(task_id) if task_id else None,
            status=str(result.get("status", "unknown")) if isinstance(result, dict) else "unknown",
            query=str(result.get("query", "")) if isinstance(result, dict) else "",
            summary=str(result.get("summary", "")) if isinstance(result, dict) else "",
            sources=sources,
        )

    async def import_research_sources(
        self,
        notebook_id: str,
        task_id: str,
        sources: Sequence[BAResearchSource | dict[str, str]],
    ) -> tuple[BAObjectRef, ...]:
        """Import research sources and normalize the returned source handles."""
        self.require_capability(BACapabilityName.RESEARCH)
        request_payload: list[dict[str, str]] = []
        for source in sources:
            if isinstance(source, BAResearchSource):
                request_payload.append({"title": source.title, "url": source.url})
            else:
                request_payload.append(
                    {
                        "title": str(source.get("title", "")),
                        "url": str(source.get("url", "")),
                    }
                )

        imported = await self._client.research.import_sources(notebook_id, task_id, request_payload)
        return tuple(
            BAObjectRef(
                notebook_id=notebook_id,
                object_id=str(source_data.get("id", "")) or None,
                kind="source",
                title=str(source_data.get("title", "")),
            )
            for source_data in imported
            if isinstance(source_data, dict)
        )

    async def list_artifacts(self, notebook_id: str, artifact_type: Any = None) -> list[Artifact]:
        """List notebook artifacts through the BA adapter seam."""
        return await self._client.artifacts.list(notebook_id, artifact_type=artifact_type)

    async def get_artifact(self, notebook_id: str, artifact_id: str) -> Artifact | None:
        """Get one notebook artifact through the BA adapter seam."""
        return await self._client.artifacts.get(notebook_id, artifact_id)

    async def generate_report(
        self,
        notebook_id: str,
        *,
        report_format: ReportFormat | str = ReportFormat.BRIEFING_DOC,
        source_ids: Sequence[str] | None = None,
        language: str = "en",
        custom_prompt: str | None = None,
        extra_instructions: str | None = None,
    ) -> BAArtifactTask:
        """Generate a report and normalize the task handle."""
        self.require_capability(BACapabilityName.REPORT_ARTIFACTS)
        status = await self._client.artifacts.generate_report(
            notebook_id,
            report_format=_coerce_report_format(report_format),
            source_ids=_optional_list(source_ids),
            language=language,
            custom_prompt=custom_prompt,
            extra_instructions=extra_instructions,
        )
        return BAArtifactTask.from_generation_status(notebook_id, "report", status)

    async def generate_data_table(
        self,
        notebook_id: str,
        *,
        source_ids: Sequence[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
    ) -> BAArtifactTask:
        """Generate a data table and normalize the task handle."""
        self.require_capability(BACapabilityName.DATA_TABLE_ARTIFACTS)
        status = await self._client.artifacts.generate_data_table(
            notebook_id,
            source_ids=_optional_list(source_ids),
            language=language,
            instructions=instructions,
        )
        return BAArtifactTask.from_generation_status(notebook_id, "data_table", status)

    async def generate_mind_map(
        self,
        notebook_id: str,
        *,
        source_ids: Sequence[str] | None = None,
    ) -> BAMindMapResult:
        """Generate a note-backed mind map with explicit degraded support metadata."""
        support = self.require_capability(BACapabilityName.MIND_MAP_ARTIFACTS)
        payload = await self._client.artifacts.generate_mind_map(
            notebook_id,
            source_ids=_optional_list(source_ids),
        )
        note_id = payload.get("note_id") if isinstance(payload, dict) else None
        mind_map = payload.get("mind_map") if isinstance(payload, dict) else None
        return BAMindMapResult(
            notebook_id=notebook_id,
            note_id=str(note_id) if note_id else None,
            mind_map=mind_map,
            support=support,
        )

    async def wait_for_artifact(
        self,
        notebook_id: str,
        task_id: str,
        *,
        artifact_kind: str = "artifact",
        initial_interval: float = 2.0,
        max_interval: float = 10.0,
        timeout: float = 300.0,
    ) -> BAArtifactTask:
        """Wait for an artifact task to complete and normalize the result."""
        status = await self._client.artifacts.wait_for_completion(
            notebook_id,
            task_id,
            initial_interval=initial_interval,
            max_interval=max_interval,
            timeout=timeout,
        )
        return BAArtifactTask.from_generation_status(notebook_id, artifact_kind, status)

    async def download_report(
        self,
        notebook_id: str,
        output_path: str | Path,
        *,
        artifact_id: str | None = None,
    ) -> str:
        """Download a report artifact."""
        self.require_capability(BACapabilityName.REPORT_ARTIFACTS)
        return await self._client.artifacts.download_report(
            notebook_id,
            str(output_path),
            artifact_id=artifact_id,
        )

    async def download_data_table(
        self,
        notebook_id: str,
        output_path: str | Path,
        *,
        artifact_id: str | None = None,
    ) -> str:
        """Download a data-table artifact."""
        self.require_capability(BACapabilityName.DATA_TABLE_ARTIFACTS)
        return await self._client.artifacts.download_data_table(
            notebook_id,
            str(output_path),
            artifact_id=artifact_id,
        )

    async def download_mind_map(
        self,
        notebook_id: str,
        output_path: str | Path,
        *,
        artifact_id: str | None = None,
    ) -> str:
        """Download a mind-map artifact."""
        self.require_capability(BACapabilityName.MIND_MAP_ARTIFACTS)
        return await self._client.artifacts.download_mind_map(
            notebook_id,
            str(output_path),
            artifact_id=artifact_id,
        )

    async def export_report(
        self,
        notebook_id: str,
        artifact_id: str,
        *,
        title: str = "Export",
        export_type: ExportType | str = ExportType.DOCS,
    ) -> Any:
        """Export a report artifact."""
        self.require_capability(BACapabilityName.REPORT_ARTIFACTS)
        return await self._client.artifacts.export_report(
            notebook_id,
            artifact_id,
            title=title,
            export_type=_coerce_export_type(export_type),
        )

    async def export_data_table(
        self,
        notebook_id: str,
        artifact_id: str,
        *,
        title: str = "Export",
    ) -> Any:
        """Export a data-table artifact."""
        self.require_capability(BACapabilityName.DATA_TABLE_ARTIFACTS)
        return await self._client.artifacts.export_data_table(
            notebook_id,
            artifact_id,
            title=title,
        )


__all__ = [
    "ADAPTER_CAPABILITIES",
    "ADAPTER_USAGE_RULES",
    "BAAdapterError",
    "BAArtifactTask",
    "BACapabilityAdapter",
    "BACapabilityName",
    "BACapabilityState",
    "BACapabilitySupport",
    "BACitation",
    "BAIngestWaitResult",
    "BAMindMapResult",
    "BAObjectRef",
    "BAReadyTimeoutPolicy",
    "BAResearchPollResult",
    "BAResearchSession",
    "BAResearchSource",
    "SourceRegistrationResult",
    "BASourceOperationResult",
    "BASourceReadinessState",
    "BASourceSnapshot",
    "BAStructuredAskResult",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "UnsupportedBACapabilityError",
]
