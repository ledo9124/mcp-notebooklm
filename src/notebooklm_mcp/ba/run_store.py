"""Run-store boundary for BA workflow persistence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .metrics import RunMetricsHistoryDocument, RunMetricsSnapshot
from .models import (
    BAModel,
    CanonicalScreen,
    RunAuditDocument,
    RunAuditEntry,
    RunStateSnapshot,
    RunStatus,
    ScreenCatalogDocument,
    SourceContentKind,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceSnapshotRecord,
    SourceType,
    TerminologyDocument,
    WorkflowMode,
)

MODULE_PURPOSE = "Own local persistence for BA runs, snapshots, manifests, and rerun metadata."

OWNS = (
    "Run directory layout",
    "Read/write helpers for stored BA run artifacts",
    "Stable persistence APIs for extraction, rendering, validation, and reruns",
)

MUST_NOT_OWN = (
    "NotebookLM SDK access",
    "Prompt composition",
    "MCP tool registration",
    "Cross-module business rules unrelated to persistence",
)

DEFAULT_FEATURES_ROOT = Path("docs/features")

_RUN_DIR_NAME = "runs"
_SCREENS_DIR_NAME = "screens"

_OVERVIEW_MD = "00-overview.md"
_SOURCE_MANIFEST_MD = "01-source-manifest.md"
_SOURCE_MANIFEST_JSON = "01-source-manifest.json"
_SCREEN_CATALOG_JSON = "02-screen-catalog.json"
_READINESS_SUMMARY_MD = "03-readiness-summary.md"
_TERMINOLOGY_MD = "04-terminology.md"
_TERMINOLOGY_JSON = "04-terminology.json"
_RUN_AUDIT_JSON = "05-run-audit.json"
_METRICS_SUMMARY_MD = "06-metrics-summary.md"
_METRICS_HISTORY_JSON = "06-metrics-history.json"
_CHANGELOG_MD = "changelog.md"

_RUN_METADATA_JSON = "run-metadata.json"
_RUN_STATE_JSON = "run-state.json"
_SOURCE_REGISTRATION_JSON = "source-registration.json"
_IMPACTED_SCREENS_JSON = "impacted-screens.json"
_METRICS_JSON = "metrics.json"
_SNAPSHOT_METADATA_JSON = "snapshot.json"
_SNAPSHOT_FULLTEXT_TXT = "fulltext.txt"
_SNAPSHOT_GUIDE_JSON = "guide.json"
_SNAPSHOT_QUALITY_JSON = "quality.json"

_PROMPTS_DIR = "prompts"
_RAW_RESPONSES_DIR = "raw_responses"
_SNAPSHOTS_DIR = "snapshots"
_NORMALIZED_EVIDENCE_DIR = "normalized_evidence"
_KEY_SANITIZE_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ScreenBundlePaths:
    root: Path
    canonical_json: Path
    fe_markdown: Path
    be_markdown: Path
    questions_markdown: Path
    field_matrix_csv: Path
    action_rule_matrix_csv: Path
    api_matrix_csv: Path
    contract_yaml: Path
    mock_data_json: Path
    qa_report_json: Path


@dataclass(frozen=True)
class FeatureBundlePaths:
    root: Path
    overview_markdown: Path
    source_manifest_markdown: Path
    source_manifest_json: Path
    screen_catalog_json: Path
    readiness_summary_markdown: Path
    terminology_markdown: Path
    terminology_json: Path
    run_audit_json: Path
    metrics_summary_markdown: Path
    metrics_history_json: Path
    changelog_markdown: Path
    screens_dir: Path
    runs_dir: Path


@dataclass(frozen=True)
class RunArtifactPaths:
    root: Path
    snapshots_dir: Path
    prompts_dir: Path
    raw_responses_dir: Path
    normalized_evidence_dir: Path
    source_registration_json: Path
    impacted_screens_json: Path
    metrics_json: Path
    run_metadata_json: Path
    run_state_json: Path


@dataclass(frozen=True)
class SourceSnapshotPaths:
    root: Path
    metadata_json: Path
    fulltext_txt: Path
    guide_json: Path
    quality_json: Path


class FeatureArtifactPointers(BAModel):
    overview_markdown: str
    source_manifest_markdown: str
    source_manifest_json: str
    screen_catalog_json: str
    readiness_summary_markdown: str
    terminology_markdown: str
    terminology_json: str
    run_audit_json: str
    metrics_summary_markdown: str | None = None
    metrics_history_json: str | None = None
    changelog_markdown: str


class RunArtifactPointers(BAModel):
    snapshots_dir: str
    prompts_dir: str
    raw_responses_dir: str
    normalized_evidence_dir: str
    source_registration_json: str
    impacted_screens_json: str
    metrics_json: str | None = None
    run_metadata_json: str
    run_state_json: str


class RunMetadata(BAModel):
    feature_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    created_at: str
    mode_requested: WorkflowMode | None = None
    feature_bundle: FeatureArtifactPointers
    run_artifacts: RunArtifactPointers


class SourceRegistrationInput(BAModel):
    path_or_url_or_text: str = Field(min_length=1)
    source_type: SourceType
    priority: SourcePriority = SourcePriority.NORMAL
    source_key: str | None = None
    notes: list[str] = Field(default_factory=list)
    title: str | None = None
    content_kind: SourceContentKind | None = None


class RegisteredSourceInput(BAModel):
    source_key: str = Field(min_length=1)
    path_or_url_or_text: str = Field(min_length=1)
    source_type: SourceType
    priority: SourcePriority
    notes: list[str] = Field(default_factory=list)
    content_kind: SourceContentKind
    source_ref: str = Field(min_length=1)
    title: str | None = None


class SourceRegistrationResult(BAModel):
    feature_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    registered_sources: list[RegisteredSourceInput] = Field(default_factory=list)
    manifest: SourceManifestDocument
    warnings: list[str] = Field(default_factory=list)
    missing_critical_sources: list[SourceType] = Field(default_factory=list)


ModelT = TypeVar("ModelT", bound=BaseModel)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_file_path(value: str) -> bool:
    candidate = Path(value)
    return candidate.is_absolute() or "/" in value or "\\" in value or bool(candidate.suffix)


def _infer_source_content_kind(value: str) -> SourceContentKind:
    if _is_http_url(value):
        return SourceContentKind.URL
    if "\n" in value or "\r" in value:
        return SourceContentKind.INLINE_TEXT
    if _looks_like_file_path(value):
        return SourceContentKind.FILE_PATH
    return SourceContentKind.INLINE_TEXT


def _default_source_title(
    source_key: str,
    source_ref: str,
    content_kind: SourceContentKind,
    explicit_title: str | None,
) -> str | None:
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


class BARunStore:
    """Filesystem-backed layout and typed metadata helpers for BA runs."""

    def __init__(
        self,
        *,
        feature_key: str,
        run_id: str,
        workspace_root: Path | str = Path("."),
    ) -> None:
        self.feature_key = feature_key
        self.run_id = run_id
        self.workspace_root = Path(workspace_root).resolve()

    @property
    def feature_paths(self) -> FeatureBundlePaths:
        root = self.workspace_root / DEFAULT_FEATURES_ROOT / self.feature_key
        return FeatureBundlePaths(
            root=root,
            overview_markdown=root / _OVERVIEW_MD,
            source_manifest_markdown=root / _SOURCE_MANIFEST_MD,
            source_manifest_json=root / _SOURCE_MANIFEST_JSON,
            screen_catalog_json=root / _SCREEN_CATALOG_JSON,
            readiness_summary_markdown=root / _READINESS_SUMMARY_MD,
            terminology_markdown=root / _TERMINOLOGY_MD,
            terminology_json=root / _TERMINOLOGY_JSON,
            run_audit_json=root / _RUN_AUDIT_JSON,
            metrics_summary_markdown=root / _METRICS_SUMMARY_MD,
            metrics_history_json=root / _METRICS_HISTORY_JSON,
            changelog_markdown=root / _CHANGELOG_MD,
            screens_dir=root / _SCREENS_DIR_NAME,
            runs_dir=root / _RUN_DIR_NAME,
        )

    @property
    def run_paths(self) -> RunArtifactPaths:
        root = self.feature_paths.runs_dir / self.run_id
        return RunArtifactPaths(
            root=root,
            snapshots_dir=root / _SNAPSHOTS_DIR,
            prompts_dir=root / _PROMPTS_DIR,
            raw_responses_dir=root / _RAW_RESPONSES_DIR,
            normalized_evidence_dir=root / _NORMALIZED_EVIDENCE_DIR,
            source_registration_json=root / _SOURCE_REGISTRATION_JSON,
            impacted_screens_json=root / _IMPACTED_SCREENS_JSON,
            metrics_json=root / _METRICS_JSON,
            run_metadata_json=root / _RUN_METADATA_JSON,
            run_state_json=root / _RUN_STATE_JSON,
        )

    def screen_paths(self, screen_id: str) -> ScreenBundlePaths:
        root = self.feature_paths.screens_dir / screen_id
        return ScreenBundlePaths(
            root=root,
            canonical_json=root / "canonical.json",
            fe_markdown=root / "fe.md",
            be_markdown=root / "be.md",
            questions_markdown=root / "questions.md",
            field_matrix_csv=root / "field-matrix.csv",
            action_rule_matrix_csv=root / "action-rule-matrix.csv",
            api_matrix_csv=root / "api-matrix.csv",
            contract_yaml=root / "contract.provisional.yaml",
            mock_data_json=root / "mock-data.json",
            qa_report_json=root / "qa-report.json",
        )

    def snapshot_paths(self, source_key: str, snapshot_id: str) -> SourceSnapshotPaths:
        normalized_source_key = self._normalize_source_key(source_key)
        root = self.run_paths.snapshots_dir / normalized_source_key / snapshot_id
        return SourceSnapshotPaths(
            root=root,
            metadata_json=root / _SNAPSHOT_METADATA_JSON,
            fulltext_txt=root / _SNAPSHOT_FULLTEXT_TXT,
            guide_json=root / _SNAPSHOT_GUIDE_JSON,
            quality_json=root / _SNAPSHOT_QUALITY_JSON,
        )

    def ensure_layout(self) -> None:
        feature_paths = self.feature_paths
        run_paths = self.run_paths

        feature_paths.root.mkdir(parents=True, exist_ok=True)
        feature_paths.screens_dir.mkdir(parents=True, exist_ok=True)
        feature_paths.runs_dir.mkdir(parents=True, exist_ok=True)
        run_paths.root.mkdir(parents=True, exist_ok=True)
        run_paths.snapshots_dir.mkdir(parents=True, exist_ok=True)
        run_paths.prompts_dir.mkdir(parents=True, exist_ok=True)
        run_paths.raw_responses_dir.mkdir(parents=True, exist_ok=True)
        run_paths.normalized_evidence_dir.mkdir(parents=True, exist_ok=True)

    def create(self, *, mode_requested: WorkflowMode | None = None) -> RunMetadata:
        self.ensure_layout()
        metadata = RunMetadata(
            feature_key=self.feature_key,
            run_id=self.run_id,
            created_at=_utc_now_iso(),
            mode_requested=mode_requested,
            feature_bundle=self._feature_pointers(),
            run_artifacts=self._run_pointers(),
        )
        self.write_model_json(self.run_paths.run_metadata_json, metadata)

        if not self.run_paths.run_state_json.exists():
            self.save_run_state(
                RunStateSnapshot(
                    run_id=self.run_id,
                    feature_key=self.feature_key,
                    status=RunStatus.PENDING,
                )
            )
        elif not self.load_run_audit().entries:
            self.append_run_audit_entry(self.load_run_state())
        return metadata

    def load_metadata(self) -> RunMetadata:
        return self.read_model_json(self.run_paths.run_metadata_json, RunMetadata)

    def register_sources(
        self,
        inputs: list[SourceRegistrationInput],
        *,
        update_only: bool = False,
    ) -> SourceRegistrationResult:
        self.ensure_layout()

        warnings: list[str] = []
        registered_sources: list[RegisteredSourceInput] = []
        manifest_rows: list[SourceManifestRow] = []
        seen_keys: set[str] = set()

        for index, source_input in enumerate(inputs, start=1):
            try:
                normalized = self._normalize_source_input(source_input)
            except ValueError as exc:
                warnings.append(f"source[{index}]: {exc}")
                continue

            if normalized.source_key in seen_keys:
                warnings.append(
                    f"source[{index}]: duplicate source_key '{normalized.source_key}' skipped"
                )
                continue

            seen_keys.add(normalized.source_key)
            registered_sources.append(normalized)
            manifest_rows.append(
                SourceManifestRow(
                    source_key=normalized.source_key,
                    source_type=normalized.source_type,
                    priority=normalized.priority,
                    content_kind=normalized.content_kind,
                    source_ref=normalized.source_ref,
                    title=normalized.title,
                    notes=normalized.notes,
                )
            )

        missing_critical_sources: list[SourceType] = []
        has_primary_requirement = any(
            row.source_type is SourceType.PRIMARY_REQUIREMENT for row in manifest_rows
        )
        if not update_only and not has_primary_requirement:
            missing_critical_sources.append(SourceType.PRIMARY_REQUIREMENT)
            warnings.append(
                "missing critical source: at least one PRIMARY_REQUIREMENT source is required"
            )

        result = SourceRegistrationResult(
            feature_key=self.feature_key,
            run_id=self.run_id,
            registered_sources=registered_sources,
            manifest=SourceManifestDocument(
                run_id=self.run_id,
                feature_key=self.feature_key,
                rows=manifest_rows,
                warnings=warnings,
            ),
            warnings=warnings,
            missing_critical_sources=missing_critical_sources,
        )
        self.write_model_json(self.run_paths.source_registration_json, result)
        return result

    def load_source_registration(self) -> SourceRegistrationResult:
        return self.read_model_json(
            self.run_paths.source_registration_json,
            SourceRegistrationResult,
        )

    def save_source_manifest_artifacts(
        self,
        manifest: SourceManifestDocument,
        *,
        markdown: str,
    ) -> None:
        self.write_model_json(self.feature_paths.source_manifest_json, manifest)
        self.write_text(self.feature_paths.source_manifest_markdown, markdown)

    def load_source_manifest(self) -> SourceManifestDocument:
        return self.read_model_json(
            self.feature_paths.source_manifest_json,
            SourceManifestDocument,
        )

    def load_source_manifest_markdown(self) -> str:
        return self.feature_paths.source_manifest_markdown.read_text(encoding="utf-8")

    def save_screen_catalog(self, catalog: ScreenCatalogDocument) -> Path:
        return self.write_model_json(self.feature_paths.screen_catalog_json, catalog)

    def load_screen_catalog(self) -> ScreenCatalogDocument:
        return self.read_model_json(
            self.feature_paths.screen_catalog_json,
            ScreenCatalogDocument,
        )

    def save_terminology_artifacts(
        self,
        terminology: TerminologyDocument,
        *,
        markdown: str,
    ) -> None:
        self.write_model_json(self.feature_paths.terminology_json, terminology)
        self.write_text(self.feature_paths.terminology_markdown, markdown)

    def load_terminology(self) -> TerminologyDocument:
        return self.read_model_json(
            self.feature_paths.terminology_json,
            TerminologyDocument,
        )

    def load_terminology_markdown(self) -> str:
        return self.feature_paths.terminology_markdown.read_text(encoding="utf-8")

    def save_changelog_markdown(self, markdown: str) -> Path:
        return self.write_text(self.feature_paths.changelog_markdown, markdown)

    def load_changelog_markdown(self) -> str:
        return self.feature_paths.changelog_markdown.read_text(encoding="utf-8")

    def save_canonical_screen(self, screen: CanonicalScreen) -> Path:
        return self.write_model_json(self.screen_paths(screen.screen_id).canonical_json, screen)

    def load_canonical_screen(self, screen_id: str) -> CanonicalScreen:
        return self.read_model_json(
            self.screen_paths(screen_id).canonical_json,
            CanonicalScreen,
        )

    def save_screen_matrix_artifacts(
        self,
        screen_id: str,
        *,
        field_csv: str,
        action_rule_csv: str,
        api_csv: str,
    ) -> None:
        paths = self.screen_paths(screen_id)
        self.write_text(paths.field_matrix_csv, field_csv)
        self.write_text(paths.action_rule_matrix_csv, action_rule_csv)
        self.write_text(paths.api_matrix_csv, api_csv)

    def load_field_matrix_csv(self, screen_id: str) -> str:
        return self.screen_paths(screen_id).field_matrix_csv.read_text(encoding="utf-8")

    def load_action_rule_matrix_csv(self, screen_id: str) -> str:
        return self.screen_paths(screen_id).action_rule_matrix_csv.read_text(encoding="utf-8")

    def load_api_matrix_csv(self, screen_id: str) -> str:
        return self.screen_paths(screen_id).api_matrix_csv.read_text(encoding="utf-8")

    def save_fe_spec_markdown(self, screen_id: str, markdown: str) -> Path:
        return self.write_text(self.screen_paths(screen_id).fe_markdown, markdown)

    def load_fe_spec_markdown(self, screen_id: str) -> str:
        return self.screen_paths(screen_id).fe_markdown.read_text(encoding="utf-8")

    def save_be_spec_markdown(self, screen_id: str, markdown: str) -> Path:
        return self.write_text(self.screen_paths(screen_id).be_markdown, markdown)

    def load_be_spec_markdown(self, screen_id: str) -> str:
        return self.screen_paths(screen_id).be_markdown.read_text(encoding="utf-8")

    def save_questions_markdown(self, screen_id: str, markdown: str) -> Path:
        return self.write_text(self.screen_paths(screen_id).questions_markdown, markdown)

    def load_questions_markdown(self, screen_id: str) -> str:
        return self.screen_paths(screen_id).questions_markdown.read_text(encoding="utf-8")

    def save_contract_yaml(self, screen_id: str, contract_yaml: str) -> Path:
        return self.write_text(self.screen_paths(screen_id).contract_yaml, contract_yaml)

    def load_contract_yaml(self, screen_id: str) -> str:
        return self.screen_paths(screen_id).contract_yaml.read_text(encoding="utf-8")

    def save_mock_data_json(self, screen_id: str, mock_data_json: str) -> Path:
        return self.write_text(self.screen_paths(screen_id).mock_data_json, mock_data_json)

    def load_mock_data_json(self, screen_id: str) -> str:
        return self.screen_paths(screen_id).mock_data_json.read_text(encoding="utf-8")

    def save_qa_report_json(self, screen_id: str, qa_report_json: str) -> Path:
        return self.write_text(self.screen_paths(screen_id).qa_report_json, qa_report_json)

    def load_qa_report_json(self, screen_id: str) -> str:
        return self.screen_paths(screen_id).qa_report_json.read_text(encoding="utf-8")

    def persist_source_snapshot(
        self,
        *,
        source_key: str,
        notebook_source_id: str,
        title: str,
        source_type: str,
        content: str,
        char_count: int,
        guide_summary: str = "",
        guide_keywords: Sequence[str] = (),
        is_fresh: bool | None = None,
    ) -> SourceSnapshotRecord:
        self.ensure_layout()

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        snapshot_id = f"{self._normalize_source_key(source_key)}-{content_hash[:12]}"
        paths = self.snapshot_paths(source_key, snapshot_id)
        paths.root.mkdir(parents=True, exist_ok=True)
        paths.fulltext_txt.write_text(content, encoding="utf-8")

        guide_path: str | None = None
        if guide_summary or guide_keywords:
            paths.guide_json.write_text(
                json.dumps(
                    {
                        "summary": guide_summary,
                        "keywords": list(guide_keywords),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            guide_path = self._relative(paths.guide_json)

        record = SourceSnapshotRecord(
            source_key=source_key,
            snapshot_id=snapshot_id,
            content_hash=content_hash,
            fulltext_path=self._relative(paths.fulltext_txt),
            guide_path=guide_path,
            freshness=self._freshness_label(is_fresh),
            notebook_source_id=notebook_source_id,
            title=title,
            source_type=source_type,
            char_count=char_count,
        )
        self.write_model_json(paths.metadata_json, record)
        return record

    def load_source_snapshot(self, source_key: str, snapshot_id: str) -> SourceSnapshotRecord:
        return self.read_model_json(
            self.snapshot_paths(source_key, snapshot_id).metadata_json,
            SourceSnapshotRecord,
        )

    def load_source_snapshot_text(self, source_key: str, snapshot_id: str) -> str:
        return self.snapshot_paths(source_key, snapshot_id).fulltext_txt.read_text(encoding="utf-8")

    def attach_snapshot_records(
        self,
        manifest: SourceManifestDocument,
        records: Sequence[SourceSnapshotRecord],
    ) -> SourceManifestDocument:
        records_by_source_key = {record.source_key: record for record in records}
        rows = [
            row.model_copy(
                update={
                    "snapshot_id": records_by_source_key[row.source_key].snapshot_id,
                    "freshness": records_by_source_key[row.source_key].freshness,
                }
            )
            if row.source_key in records_by_source_key
            else row
            for row in manifest.rows
        ]
        return manifest.model_copy(update={"rows": rows})

    def save_source_quality_assessment(
        self,
        source_key: str,
        snapshot_id: str,
        assessment: BAModel,
    ) -> Path:
        return self.write_model_json(
            self.snapshot_paths(source_key, snapshot_id).quality_json,
            assessment,
        )

    def load_source_quality_assessment(
        self,
        source_key: str,
        snapshot_id: str,
        model_type: type[ModelT],
    ) -> ModelT:
        return self.read_model_json(
            self.snapshot_paths(source_key, snapshot_id).quality_json,
            model_type,
        )

    def save_run_state(self, state: RunStateSnapshot, *, record_audit: bool = True) -> Path:
        self._validate_run_state_identity(state)
        path = self.write_model_json(self.run_paths.run_state_json, state)
        if record_audit:
            self.append_run_audit_entry(state)
        return path

    def load_run_state(self) -> RunStateSnapshot:
        return self.read_model_json(self.run_paths.run_state_json, RunStateSnapshot)

    def save_run_audit(self, audit: RunAuditDocument) -> Path:
        if audit.feature_key != self.feature_key:
            raise ValueError("run audit feature_key must match store feature_key")
        return self.write_model_json(self.feature_paths.run_audit_json, audit)

    def load_run_audit(self) -> RunAuditDocument:
        if not self.feature_paths.run_audit_json.exists():
            return RunAuditDocument(feature_key=self.feature_key)
        return self.read_model_json(self.feature_paths.run_audit_json, RunAuditDocument)

    def save_impacted_screens_json(self, content: str) -> Path:
        return self.write_text(self.run_paths.impacted_screens_json, content)

    def load_impacted_screens_json(self) -> str:
        return self.run_paths.impacted_screens_json.read_text(encoding="utf-8")

    def save_metrics_snapshot(self, snapshot: RunMetricsSnapshot) -> Path:
        if snapshot.feature_key != self.feature_key:
            raise ValueError("metrics snapshot feature_key must match store feature_key")
        if snapshot.run_id != self.run_id:
            raise ValueError("metrics snapshot run_id must match store run_id")
        return self.write_model_json(self.run_paths.metrics_json, snapshot)

    def load_metrics_snapshot(self) -> RunMetricsSnapshot:
        return self.read_model_json(self.run_paths.metrics_json, RunMetricsSnapshot)

    def save_metrics_history(self, history: RunMetricsHistoryDocument) -> Path:
        if history.feature_key != self.feature_key:
            raise ValueError("metrics history feature_key must match store feature_key")
        return self.write_model_json(self.feature_paths.metrics_history_json, history)

    def load_metrics_history(self) -> RunMetricsHistoryDocument:
        if not self.feature_paths.metrics_history_json.exists():
            return RunMetricsHistoryDocument(feature_key=self.feature_key)
        return self.read_model_json(self.feature_paths.metrics_history_json, RunMetricsHistoryDocument)

    def append_metrics_snapshot(
        self,
        snapshot: RunMetricsSnapshot,
    ) -> RunMetricsHistoryDocument:
        history = self.load_metrics_history()
        history.entries.append(snapshot)
        self.save_metrics_history(history)
        return history

    def save_metrics_summary_markdown(self, markdown: str) -> Path:
        return self.write_text(self.feature_paths.metrics_summary_markdown, markdown)

    def load_metrics_summary_markdown(self) -> str:
        return self.feature_paths.metrics_summary_markdown.read_text(encoding="utf-8")

    def append_run_audit_entry(
        self,
        state: RunStateSnapshot,
        *,
        recorded_at: str | None = None,
    ) -> RunAuditDocument:
        self._validate_run_state_identity(state)
        audit = self.load_run_audit()
        audit.entries.append(
            RunAuditEntry(
                recorded_at=recorded_at or _utc_now_iso(),
                snapshot=state,
            )
        )
        self.save_run_audit(audit)
        return audit

    def write_model_json(self, path: Path, payload: BaseModel) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        return path

    def write_text(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_model_json(self, path: Path, model_type: type[ModelT]) -> ModelT:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))

    def _feature_pointers(self) -> FeatureArtifactPointers:
        paths = self.feature_paths
        return FeatureArtifactPointers(
            overview_markdown=self._relative(paths.overview_markdown),
            source_manifest_markdown=self._relative(paths.source_manifest_markdown),
            source_manifest_json=self._relative(paths.source_manifest_json),
            screen_catalog_json=self._relative(paths.screen_catalog_json),
            readiness_summary_markdown=self._relative(paths.readiness_summary_markdown),
            terminology_markdown=self._relative(paths.terminology_markdown),
            terminology_json=self._relative(paths.terminology_json),
            run_audit_json=self._relative(paths.run_audit_json),
            metrics_summary_markdown=self._relative(paths.metrics_summary_markdown),
            metrics_history_json=self._relative(paths.metrics_history_json),
            changelog_markdown=self._relative(paths.changelog_markdown),
        )

    def _run_pointers(self) -> RunArtifactPointers:
        paths = self.run_paths
        return RunArtifactPointers(
            snapshots_dir=self._relative(paths.snapshots_dir),
            prompts_dir=self._relative(paths.prompts_dir),
            raw_responses_dir=self._relative(paths.raw_responses_dir),
            normalized_evidence_dir=self._relative(paths.normalized_evidence_dir),
            source_registration_json=self._relative(paths.source_registration_json),
            impacted_screens_json=self._relative(paths.impacted_screens_json),
            metrics_json=self._relative(paths.metrics_json),
            run_metadata_json=self._relative(paths.run_metadata_json),
            run_state_json=self._relative(paths.run_state_json),
        )

    def _normalize_source_input(self, source_input: SourceRegistrationInput) -> RegisteredSourceInput:
        locator = source_input.path_or_url_or_text.strip()
        if not locator:
            raise ValueError("path_or_url_or_text must not be empty")

        source_key = (
            self._normalize_source_key(source_input.source_key)
            if source_input.source_key
            else self._generate_source_key(locator, source_input.source_type)
        )
        content_kind = source_input.content_kind or _infer_source_content_kind(locator)
        source_ref = Path(locator).as_posix() if content_kind is SourceContentKind.FILE_PATH else locator
        return RegisteredSourceInput(
            source_key=source_key,
            path_or_url_or_text=locator,
            source_type=source_input.source_type,
            priority=source_input.priority,
            notes=source_input.notes,
            content_kind=content_kind,
            source_ref=source_ref,
            title=_default_source_title(
                source_key,
                source_ref,
                content_kind,
                source_input.title,
            ),
        )

    def _generate_source_key(self, locator: str, source_type: SourceType) -> str:
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "locator": locator,
                    "source_type": source_type.value,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()[:10]
        try:
            hint = self._normalize_source_key(self._source_key_hint(locator))
        except ValueError:
            hint = "source"
        return f"{hint}-{fingerprint}"

    def _source_key_hint(self, locator: str) -> str:
        parsed = urlparse(locator)
        if parsed.scheme and parsed.netloc:
            candidate = Path(parsed.path).stem or parsed.netloc
        else:
            candidate = Path(locator).stem or locator[:24]
        return candidate[:24]

    def _normalize_source_key(self, raw_key: str | None) -> str:
        if raw_key is None:
            return ""
        normalized = _KEY_SANITIZE_RE.sub("-", raw_key.strip().lower()).strip("-")
        if not normalized:
            raise ValueError("source_key must contain at least one alphanumeric character")
        return normalized

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.workspace_root).as_posix()

    def _freshness_label(self, is_fresh: bool | None) -> str:
        if is_fresh is True:
            return "fresh"
        if is_fresh is False:
            return "stale"
        return "unknown"

    def _validate_run_state_identity(self, state: RunStateSnapshot) -> None:
        if state.feature_key != self.feature_key:
            raise ValueError("run state feature_key must match store feature_key")
        if state.run_id != self.run_id:
            raise ValueError("run state run_id must match store run_id")


__all__ = [
    "BARunStore",
    "DEFAULT_FEATURES_ROOT",
    "FeatureArtifactPointers",
    "FeatureBundlePaths",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "RunArtifactPaths",
    "RunArtifactPointers",
    "RunMetadata",
    "ScreenBundlePaths",
    "RegisteredSourceInput",
    "SourceRegistrationInput",
    "SourceRegistrationResult",
    "SourceSnapshotPaths",
]
