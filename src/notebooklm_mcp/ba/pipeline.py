"""Internal orchestration for end-to-end BA pipeline execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, TypeAlias, TypeVar

from pydantic import Field

from .._errors import sanitize_error_message
from .adapter import BAIngestWaitResult, BASourceSnapshot
from .contracts import (
    build_provisional_contract_artifacts,
    render_contract_yaml,
    render_mock_data_json,
)
from .extraction import (
    CanonicalScreenExtractionResult,
    ScreenCatalogExtractionResult,
    TerminologyExtractionResult,
)
from .gaps import build_gap_review_document
from .matrices import ScreenMatrixBundle, build_screen_matrix_bundle
from .models import (
    BAModel,
    HaltRecommendation,
    ReadinessDecision,
    ReadinessSummary,
    RunStateSnapshot,
    RunStep,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    SourceManifestDocument,
    SourceQualityAssessment,
    SourceSnapshotRecord,
    TerminologyDocument,
    ValidationReport,
    ValidationStatus,
    WorkflowMode,
)
from .readiness import evaluate_readiness
from .rendering import (
    ScreenBundleArtifact,
    build_source_manifest_document,
    render_action_rule_matrix_csv,
    render_api_matrix_csv,
    render_be_spec_markdown,
    render_fe_spec_markdown,
    render_field_matrix_csv,
    render_question_backlog_markdown,
    render_readiness_summary_markdown,
    render_source_manifest_markdown,
    render_terminology_markdown,
    write_bundle_layout,
)
from .run_store import BARunStore, RunMetadata, SourceRegistrationInput, SourceRegistrationResult
from .state_machine import BARunStateMachine, RunStateTransitionError
from .tool_contracts import RUN_PIPELINE_DRY_RUN_STOP_STEP
from .validation import assess_source_quality

MODULE_PURPOSE = "Own the BA pipeline orchestration layer over existing subsystem seams."

OWNS = (
    "Step-by-step BA pipeline sequencing and stop conditions",
    "Run-state updates around the existing BA deterministic helpers",
    "Dry-run stop-after-readiness behavior for ba.run_pipeline",
)

MUST_NOT_OWN = (
    "NotebookLM transport access",
    "Prompt text or structured extraction rules",
    "FastMCP registration or tool result envelopes",
    "Low-level filesystem layout rules beyond BARunStore",
)

AwaitableOrValue: TypeAlias = Awaitable[Any] | Any
ProgressCallback: TypeAlias = Callable[[RunStateSnapshot], AwaitableOrValue]
IngestAndWaitCallable: TypeAlias = Callable[
    [BARunStore, SourceManifestDocument],
    AwaitableOrValue,
]
SnapshotSourcesCallable: TypeAlias = Callable[
    [BARunStore, SourceManifestDocument, BAIngestWaitResult],
    AwaitableOrValue,
]
ExtractTerminologyCallable: TypeAlias = Callable[
    [BARunStore, SourceManifestDocument, Sequence[SourceSnapshotRecord]],
    AwaitableOrValue,
]
ExtractScreenCatalogCallable: TypeAlias = Callable[
    [BARunStore, SourceManifestDocument, TerminologyDocument, Sequence[SourceSnapshotRecord]],
    AwaitableOrValue,
]
ExtractCanonicalCallable: TypeAlias = Callable[
    [
        BARunStore,
        ScreenCatalogEntry,
        SourceManifestDocument,
        TerminologyDocument,
        Sequence[SourceSnapshotRecord],
        WorkflowMode,
    ],
    AwaitableOrValue,
]
ValidateBundleCallable: TypeAlias = Callable[
    [
        BARunStore,
        SourceManifestDocument,
        ScreenCatalogDocument,
        ReadinessSummary,
        Sequence[ScreenBundleArtifact],
    ],
    AwaitableOrValue,
]

_READY_TO_CONTINUE = {
    ReadinessDecision.READY_FOR_FE_AND_BE,
    ReadinessDecision.READY_FOR_FE_WITH_PROVISIONAL_CONTRACT,
}

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BAPipelineServices:
    """Injected stage services for the notebook-backed pipeline steps."""

    ingest_and_wait: IngestAndWaitCallable
    snapshot_sources: SnapshotSourcesCallable
    extract_terminology: ExtractTerminologyCallable
    extract_screen_catalog: ExtractScreenCatalogCallable
    extract_canonical: ExtractCanonicalCallable
    validate_bundle: ValidateBundleCallable | None = None


class BAPipelineResult(BAModel):
    """Structured result for a full BA pipeline execution attempt."""

    feature_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    resolved_output_dir: str = Field(min_length=1)
    metadata: RunMetadata
    mode_requested: WorkflowMode
    dry_run: bool = False
    state: RunStateSnapshot
    source_registration: SourceRegistrationResult
    source_manifest: SourceManifestDocument | None = None
    quality_assessments: list[SourceQualityAssessment] = Field(default_factory=list)
    terminology: TerminologyDocument | None = None
    screen_catalog: ScreenCatalogDocument | None = None
    readiness: ReadinessSummary | None = None
    validation_report: ValidationReport | None = None
    bundle_files: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    stop_step: RunStep | None = None
    stop_reason: str | None = None


async def run_pipeline(
    *,
    store: BARunStore,
    services: BAPipelineServices,
    mode_requested: WorkflowMode,
    source_inputs: Sequence[SourceRegistrationInput] = (),
    notebook_lifecycle: str = "REUSE_FEATURE_NOTEBOOK",
    assumption_profile: Mapping[str, Any] | None = None,
    update_only: bool = False,
    dry_run: bool = False,
    progress: ProgressCallback | None = None,
) -> BAPipelineResult:
    """Execute the ordered BA workflow through the current subsystem seams."""

    runner = _PipelineExecution(
        store=store,
        services=services,
        mode_requested=mode_requested,
        source_inputs=tuple(source_inputs),
        notebook_lifecycle=notebook_lifecycle,
        assumption_profile=dict(assumption_profile or {}),
        update_only=update_only,
        dry_run=dry_run,
        progress=progress,
    )
    return await runner.run()


class _PipelineExecution:
    def __init__(
        self,
        *,
        store: BARunStore,
        services: BAPipelineServices,
        mode_requested: WorkflowMode,
        source_inputs: tuple[SourceRegistrationInput, ...],
        notebook_lifecycle: str,
        assumption_profile: dict[str, Any],
        update_only: bool,
        dry_run: bool,
        progress: ProgressCallback | None,
    ) -> None:
        self.store = store
        self.services = services
        self.mode_requested = mode_requested
        self.source_inputs = source_inputs
        self.notebook_lifecycle = notebook_lifecycle
        self.assumption_profile = assumption_profile
        self.update_only = update_only
        self.dry_run = dry_run
        self.progress = progress

        self.metadata: RunMetadata | None = None
        self.machine: BARunStateMachine | None = None
        self.registration: SourceRegistrationResult | None = None
        self.ingest_result: BAIngestWaitResult | None = None
        self.source_manifest: SourceManifestDocument | None = None
        self.snapshots: list[SourceSnapshotRecord] = []
        self.quality_assessments: list[SourceQualityAssessment] = []
        self.terminology: TerminologyDocument | None = None
        self.screen_catalog: ScreenCatalogDocument | None = None
        self.canonical_screens_by_id: dict[str, Any] = {}
        self.reviews_by_id: dict[str, Any] = {}
        self.matrices_by_id: dict[str, ScreenMatrixBundle] = {}
        self.contract_payloads_by_id: dict[str, tuple[str, str]] = {}
        self.rendered_screen_artifacts: list[ScreenBundleArtifact] = []
        self.readiness: ReadinessSummary | None = None
        self.validation_report: ValidationReport | None = None
        self.bundle_files: dict[str, str] = {}
        self.warnings: list[str] = []

    async def run(self) -> BAPipelineResult:
        self.metadata = self.store.create(mode_requested=self.mode_requested)
        self.machine = BARunStateMachine.from_store(self.store)

        if self.machine.can_resume():
            return self._result(
                stop_step=self.machine.state.current_step,
                stop_reason="resuming a paused BA pipeline is not implemented yet",
            )
        if self.machine.is_terminal():
            return self._result()

        self._assert_resume_scope_is_supported()

        await self._ensure_start_run()
        await self._ensure_sources_registered()

        if self.registration is None:
            msg = "source registration was not established before pipeline execution"
            raise RuntimeError(msg)

        if self.registration.missing_critical_sources:
            reason = "missing critical sources: " + ", ".join(
                source_type.value for source_type in self.registration.missing_critical_sources
            )
            return await self._degrade(
                RunStep.REGISTER_SOURCES,
                reason=reason,
                metadata={
                    "missing_critical_source_types": [
                        source_type.value for source_type in self.registration.missing_critical_sources
                    ],
                    "update_only": self.update_only,
                },
            )

        self.source_manifest = self.registration.manifest
        if not self.source_manifest.rows:
            return await self._degrade(
                RunStep.REGISTER_SOURCES,
                reason="no usable sources were registered",
                metadata={"update_only": self.update_only},
            )

        if early := await self._ingest_and_wait():
            return early
        if early := await self._snapshot_sources():
            return early
        if early := await self._assess_source_quality():
            return early
        await self._build_source_manifest()
        if early := await self._normalize_terminology():
            return early
        if early := await self._build_screen_catalog():
            return early
        if early := await self._extract_canonical():
            return early
        await self._review_gaps()
        await self._generate_matrices()
        if early := await self._evaluate_readiness():
            return early
        await self._generate_contracts()
        await self._render_bundle()
        if early := await self._validate_bundle():
            return early

        state = self.machine.complete_run(
            message="BA pipeline completed",
            metadata={
                "dry_run": self.dry_run,
                "screen_count": len(self.canonical_screens_by_id),
                "bundle_file_count": len(self.bundle_files),
            },
        )
        await self._emit(state)
        return self._result()

    def _assert_resume_scope_is_supported(self) -> None:
        assert self.machine is not None
        unsupported_steps = {
            record.step
            for record in self.machine.state.steps
            if record.status.value == "COMPLETED"
            and record.step not in {RunStep.START_RUN, RunStep.REGISTER_SOURCES}
        }
        if unsupported_steps:
            steps = ", ".join(step.value for step in sorted(unsupported_steps, key=lambda item: item.value))
            msg = f"pipeline resume beyond source registration is not implemented yet: {steps}"
            raise RunStateTransitionError(msg)

    async def _ensure_start_run(self) -> None:
        assert self.machine is not None
        if _is_completed(self.machine.state, RunStep.START_RUN):
            return

        started = self.machine.start_run(
            metadata={
                "mode_requested": self.mode_requested.value,
                "notebook_lifecycle": self.notebook_lifecycle,
                "assumption_profile": self.assumption_profile,
            },
            note="Run root initialized",
        )
        await self._emit(started)
        completed = self.machine.complete_step(
            RunStep.START_RUN,
            message="START_RUN completed",
            metadata={
                "mode_requested": self.mode_requested.value,
                "notebook_lifecycle": self.notebook_lifecycle,
                "assumption_profile": self.assumption_profile,
            },
        )
        await self._emit(completed)

    async def _ensure_sources_registered(self) -> None:
        assert self.machine is not None
        if _is_completed(self.machine.state, RunStep.REGISTER_SOURCES):
            self.registration = self.store.load_source_registration()
            self._extend_warnings(self.registration.warnings)
            return

        if not self.source_inputs:
            msg = "source_inputs are required when REGISTER_SOURCES has not already completed"
            raise ValueError(msg)

        started = self.machine.start_step(
            RunStep.REGISTER_SOURCES,
            metadata={
                "requested_source_count": len(self.source_inputs),
                "update_only": self.update_only,
            },
        )
        await self._emit(started)

        try:
            self.registration = self.store.register_sources(
                list(self.source_inputs),
                update_only=self.update_only,
            )
        except Exception as exc:
            await self._fail_step(RunStep.REGISTER_SOURCES, exc)
            raise

        self._extend_warnings(self.registration.warnings)
        completed = self.machine.complete_step(
            RunStep.REGISTER_SOURCES,
            message="REGISTER_SOURCES completed",
            metadata={
                "registered_source_count": len(self.registration.registered_sources),
                "warning_count": len(self.registration.warnings),
                "missing_critical_source_count": len(self.registration.missing_critical_sources),
                "update_only": self.update_only,
            },
        )
        await self._emit(completed)

    async def _ingest_and_wait(self) -> BAPipelineResult | None:
        assert self.machine is not None
        assert self.source_manifest is not None

        started = self.machine.start_step(
            RunStep.INGEST_AND_WAIT,
            metadata={"source_count": len(self.source_manifest.rows)},
        )
        await self._emit(started)

        try:
            ingest_result = await _maybe_await(
                self.services.ingest_and_wait(self.store, self.source_manifest)
            )
        except Exception as exc:
            await self._fail_step(RunStep.INGEST_AND_WAIT, exc)
            raise

        if not isinstance(ingest_result, BAIngestWaitResult):
            msg = f"ingest_and_wait must return BAIngestWaitResult, got {type(ingest_result)!r}"
            raise TypeError(msg)

        self._extend_warnings(ingest_result.warnings)
        self.ingest_result = ingest_result
        self.source_manifest = ingest_result.manifest

        if ingest_result.recommendation is HaltRecommendation.HALT:
            return await self._halt(
                RunStep.INGEST_AND_WAIT,
                reason=_ingest_stop_reason(ingest_result),
                metadata={
                    "recommendation": ingest_result.recommendation.value,
                    "selected_source_count": len(ingest_result.selected_source_keys),
                },
            )
        if ingest_result.recommendation in {
            HaltRecommendation.DEGRADE,
            HaltRecommendation.CLARIFICATION_FIRST,
        }:
            return await self._degrade(
                RunStep.INGEST_AND_WAIT,
                reason=_ingest_stop_reason(ingest_result),
                metadata={
                    "recommendation": ingest_result.recommendation.value,
                    "selected_source_count": len(ingest_result.selected_source_keys),
                },
            )

        completed = self.machine.complete_step(
            RunStep.INGEST_AND_WAIT,
            message="INGEST_AND_WAIT completed",
            metadata={
                "recommendation": ingest_result.recommendation.value,
                "selected_source_count": len(ingest_result.selected_source_keys),
                "warning_count": len(ingest_result.warnings),
            },
        )
        await self._emit(completed)
        return None

    async def _snapshot_sources(self) -> BAPipelineResult | None:
        assert self.machine is not None
        assert self.source_manifest is not None

        started = self.machine.start_step(
            RunStep.SNAPSHOT_SOURCES,
            metadata={"source_count": len(self.source_manifest.rows)},
        )
        await self._emit(started)

        if self.ingest_result is None:
            msg = "ingest_result was not captured before SNAPSHOT_SOURCES"
            raise RuntimeError(msg)

        try:
            snapshot_results = await _maybe_await(
                self.services.snapshot_sources(
                    self.store,
                    self.source_manifest,
                    self.ingest_result,
                )
            )
        except Exception as exc:
            await self._fail_step(RunStep.SNAPSHOT_SOURCES, exc)
            raise

        self.snapshots = [
            _normalize_snapshot_result(self.store, snapshot)
            for snapshot in tuple(snapshot_results)
        ]
        if not self.snapshots:
            return await self._degrade(
                RunStep.SNAPSHOT_SOURCES,
                reason="no source snapshots were captured",
                metadata={"source_count": len(self.source_manifest.rows)},
            )

        self.source_manifest = self.store.attach_snapshot_records(self.source_manifest, self.snapshots)
        completed = self.machine.complete_step(
            RunStep.SNAPSHOT_SOURCES,
            message="SNAPSHOT_SOURCES completed",
            metadata={"snapshot_count": len(self.snapshots)},
        )
        await self._emit(completed)
        return None

    async def _assess_source_quality(self) -> BAPipelineResult | None:
        assert self.machine is not None
        assert self.source_manifest is not None

        started = self.machine.start_step(
            RunStep.ASSESS_SOURCE_QUALITY,
            metadata={"snapshot_count": len(self.snapshots)},
        )
        await self._emit(started)

        self.quality_assessments = []
        rows_by_source_key = {row.source_key: row for row in self.source_manifest.rows}
        for snapshot in self.snapshots:
            row = rows_by_source_key.get(snapshot.source_key)
            if row is None:
                continue
            content = self.store.load_source_snapshot_text(snapshot.source_key, snapshot.snapshot_id)
            assessment = assess_source_quality(row, snapshot, content)
            self.store.save_source_quality_assessment(snapshot.source_key, snapshot.snapshot_id, assessment)
            self.quality_assessments.append(assessment)
            if assessment.recommendation is not HaltRecommendation.PROCEED:
                self._extend_warnings(
                    [
                        (
                            f"{assessment.source_key}: parse quality "
                            f"{assessment.parse_quality.value} -> {assessment.recommendation.value}"
                        )
                    ]
                )

        halted = next(
            (
                assessment
                for assessment in self.quality_assessments
                if assessment.recommendation is HaltRecommendation.HALT
            ),
            None,
        )
        if halted is not None:
            return await self._halt(
                RunStep.ASSESS_SOURCE_QUALITY,
                reason=(
                    f"{halted.source_key} failed source-quality checks "
                    f"({halted.parse_quality.value})"
                ),
                metadata={
                    "source_key": halted.source_key,
                    "parse_quality": halted.parse_quality.value,
                    "recommendation": halted.recommendation.value,
                },
            )

        completed = self.machine.complete_step(
            RunStep.ASSESS_SOURCE_QUALITY,
            message="ASSESS_SOURCE_QUALITY completed",
            metadata={
                "assessment_count": len(self.quality_assessments),
                "warning_count": len(self.warnings),
            },
        )
        await self._emit(completed)
        return None

    async def _build_source_manifest(self) -> None:
        assert self.machine is not None
        assert self.source_manifest is not None

        started = self.machine.start_step(
            RunStep.BUILD_SOURCE_MANIFEST,
            metadata={
                "snapshot_count": len(self.snapshots),
                "quality_assessment_count": len(self.quality_assessments),
            },
        )
        await self._emit(started)

        manifest = self.source_manifest.model_copy(
            update={"warnings": _dedupe_preserving_order((*self.source_manifest.warnings, *self.warnings))}
        )
        self.source_manifest = build_source_manifest_document(
            manifest,
            snapshots=self.snapshots,
            quality_assessments=self.quality_assessments,
        )
        markdown = render_source_manifest_markdown(self.source_manifest)
        self.store.save_source_manifest_artifacts(self.source_manifest, markdown=markdown)

        completed = self.machine.complete_step(
            RunStep.BUILD_SOURCE_MANIFEST,
            message="BUILD_SOURCE_MANIFEST completed",
            metadata={
                "source_count": len(self.source_manifest.rows),
                "warning_count": len(self.source_manifest.warnings),
            },
        )
        await self._emit(completed)

    async def _normalize_terminology(self) -> BAPipelineResult | None:
        assert self.machine is not None
        assert self.source_manifest is not None

        started = self.machine.start_step(
            RunStep.NORMALIZE_TERMINOLOGY,
            metadata={"source_count": len(self.source_manifest.rows)},
        )
        await self._emit(started)

        try:
            extraction = await _maybe_await(
                self.services.extract_terminology(self.store, self.source_manifest, self.snapshots)
            )
        except Exception as exc:
            await self._fail_step(RunStep.NORMALIZE_TERMINOLOGY, exc)
            raise

        if not isinstance(extraction, TerminologyExtractionResult):
            msg = (
                "extract_terminology must return TerminologyExtractionResult, "
                f"got {type(extraction)!r}"
            )
            raise TypeError(msg)

        self.terminology = extraction.document
        self._extend_warnings(extraction.warnings)
        self.store.save_terminology_artifacts(
            extraction.document,
            markdown=render_terminology_markdown(extraction.document),
        )

        completed = self.machine.complete_step(
            RunStep.NORMALIZE_TERMINOLOGY,
            message="NORMALIZE_TERMINOLOGY completed",
            metadata={
                "term_count": len(extraction.document.entries),
                "warning_count": len(extraction.warnings),
            },
        )
        await self._emit(completed)
        return None

    async def _build_screen_catalog(self) -> BAPipelineResult | None:
        assert self.machine is not None
        assert self.source_manifest is not None
        assert self.terminology is not None

        started = self.machine.start_step(RunStep.BUILD_SCREEN_CATALOG)
        await self._emit(started)

        try:
            extraction = await _maybe_await(
                self.services.extract_screen_catalog(
                    self.store,
                    self.source_manifest,
                    self.terminology,
                    self.snapshots,
                )
            )
        except Exception as exc:
            await self._fail_step(RunStep.BUILD_SCREEN_CATALOG, exc)
            raise

        if not isinstance(extraction, ScreenCatalogExtractionResult):
            msg = (
                "extract_screen_catalog must return ScreenCatalogExtractionResult, "
                f"got {type(extraction)!r}"
            )
            raise TypeError(msg)

        self.screen_catalog = extraction.document
        self._extend_warnings(extraction.warnings)
        self.store.save_screen_catalog(extraction.document)

        if not extraction.document.screens:
            return await self._degrade(
                RunStep.BUILD_SCREEN_CATALOG,
                reason="no screens were cataloged from the available sources",
                metadata={"warning_count": len(extraction.warnings)},
            )

        completed = self.machine.complete_step(
            RunStep.BUILD_SCREEN_CATALOG,
            message="BUILD_SCREEN_CATALOG completed",
            metadata={
                "screen_count": len(extraction.document.screens),
                "warning_count": len(extraction.warnings),
            },
        )
        await self._emit(completed)
        return None

    async def _extract_canonical(self) -> BAPipelineResult | None:
        assert self.machine is not None
        assert self.source_manifest is not None
        assert self.terminology is not None
        assert self.screen_catalog is not None

        started = self.machine.start_step(
            RunStep.EXTRACT_CANONICAL,
            metadata={"screen_count": len(self.screen_catalog.screens)},
        )
        await self._emit(started)

        self.canonical_screens_by_id = {}
        for entry in self.screen_catalog.screens:
            try:
                extraction = await _maybe_await(
                    self.services.extract_canonical(
                        self.store,
                        entry,
                        self.source_manifest,
                        self.terminology,
                        self.snapshots,
                        self.mode_requested,
                    )
                )
            except Exception as exc:
                await self._fail_step(RunStep.EXTRACT_CANONICAL, exc)
                raise

            if not isinstance(extraction, CanonicalScreenExtractionResult):
                msg = (
                    "extract_canonical must return CanonicalScreenExtractionResult, "
                    f"got {type(extraction)!r}"
                )
                raise TypeError(msg)

            self._extend_warnings(extraction.warnings)
            self.canonical_screens_by_id[entry.screen_id] = extraction.screen
            self.store.save_canonical_screen(extraction.screen)

        if not self.canonical_screens_by_id:
            return await self._degrade(
                RunStep.EXTRACT_CANONICAL,
                reason="no canonical screens were extracted",
                metadata={"screen_count": len(self.screen_catalog.screens)},
            )

        completed = self.machine.complete_step(
            RunStep.EXTRACT_CANONICAL,
            message="EXTRACT_CANONICAL completed",
            metadata={
                "screen_count": len(self.canonical_screens_by_id),
                "warning_count": len(self.warnings),
            },
        )
        await self._emit(completed)
        return None

    async def _review_gaps(self) -> None:
        assert self.machine is not None

        started = self.machine.start_step(
            RunStep.REVIEW_GAPS,
            metadata={"screen_count": len(self.canonical_screens_by_id)},
        )
        await self._emit(started)

        self.reviews_by_id = {
            screen_id: build_gap_review_document(screen)
            for screen_id, screen in self.canonical_screens_by_id.items()
        }

        completed = self.machine.complete_step(
            RunStep.REVIEW_GAPS,
            message="REVIEW_GAPS completed",
            metadata={
                "screen_count": len(self.reviews_by_id),
                "question_count": sum(
                    len(review.questions_for_ba)
                    + len(review.questions_for_tech_lead)
                    + len(review.questions_for_design)
                    + len(review.unassigned_questions)
                    for review in self.reviews_by_id.values()
                ),
            },
        )
        await self._emit(completed)

    async def _generate_matrices(self) -> None:
        assert self.machine is not None

        started = self.machine.start_step(
            RunStep.GENERATE_MATRICES,
            metadata={"screen_count": len(self.canonical_screens_by_id)},
        )
        await self._emit(started)

        self.matrices_by_id = {}
        for screen_id, screen in self.canonical_screens_by_id.items():
            bundle = build_screen_matrix_bundle(screen)
            self.matrices_by_id[screen_id] = bundle
            self.store.save_screen_matrix_artifacts(
                screen_id,
                field_csv=render_field_matrix_csv(bundle.field_rows),
                action_rule_csv=render_action_rule_matrix_csv(bundle.action_rule_rows),
                api_csv=render_api_matrix_csv(bundle.api_rows),
            )

        completed = self.machine.complete_step(
            RunStep.GENERATE_MATRICES,
            message="GENERATE_MATRICES completed",
            metadata={"screen_count": len(self.matrices_by_id)},
        )
        await self._emit(completed)

    async def _evaluate_readiness(self) -> BAPipelineResult | None:
        assert self.machine is not None

        started = self.machine.start_step(
            RunStep.EVALUATE_READINESS,
            metadata={"screen_count": len(self.canonical_screens_by_id)},
        )
        await self._emit(started)

        self.readiness = evaluate_readiness(
            list(self.canonical_screens_by_id.values()),
            feature_mode=self.mode_requested,
        )
        self._extend_warnings(self.readiness.warnings)
        self.store.write_text(
            self.store.feature_paths.readiness_summary_markdown,
            render_readiness_summary_markdown(self.readiness),
        )

        readiness_metadata = {
            "decision": self.readiness.decision.value,
            "screen_count": len(self.readiness.screens),
            "blocker_count": len(self.readiness.blockers),
            "warning_count": len(self.readiness.warnings),
        }

        if not self.dry_run and self.readiness.decision not in _READY_TO_CONTINUE:
            return await self._degrade(
                RunStep.EVALUATE_READINESS,
                reason=_readiness_stop_reason(self.readiness),
                metadata=readiness_metadata,
            )

        completed = self.machine.complete_step(
            RunStep.EVALUATE_READINESS,
            message="EVALUATE_READINESS completed",
            metadata=readiness_metadata,
        )
        await self._emit(completed)

        if self.dry_run:
            self._extend_warnings(
                ["dry_run=true: pipeline stopped after readiness assessment."]
            )
            done = self.machine.complete_run(
                message="BA dry run completed after readiness assessment",
                metadata={
                    "dry_run": True,
                    "stopped_after": RUN_PIPELINE_DRY_RUN_STOP_STEP.value,
                },
            )
            await self._emit(done)
            return self._result(
                stop_step=RUN_PIPELINE_DRY_RUN_STOP_STEP,
                stop_reason="dry_run",
            )
        return None

    async def _generate_contracts(self) -> None:
        assert self.machine is not None
        assert self.screen_catalog is not None
        assert self.readiness is not None

        started = self.machine.start_step(
            RunStep.GENERATE_CONTRACTS,
            metadata={"screen_count": len(self.screen_catalog.screens)},
        )
        await self._emit(started)

        readiness_by_screen = {item.screen_id: item for item in self.readiness.screens}
        self.contract_payloads_by_id = {}
        for entry in self.screen_catalog.screens:
            screen = self.canonical_screens_by_id[entry.screen_id]
            bundle = self.matrices_by_id[entry.screen_id]
            screen_readiness = readiness_by_screen[entry.screen_id]
            contract_artifacts = build_provisional_contract_artifacts(
                screen,
                matrices=bundle,
                readiness=screen_readiness,
            )
            if contract_artifacts is None:
                continue
            contract_yaml = render_contract_yaml(contract_artifacts.openapi_document)
            mock_data_json = render_mock_data_json(contract_artifacts.mock_data)
            self.store.save_contract_yaml(entry.screen_id, contract_yaml)
            self.store.save_mock_data_json(entry.screen_id, mock_data_json)
            self.contract_payloads_by_id[entry.screen_id] = (contract_yaml, mock_data_json)

        completed = self.machine.complete_step(
            RunStep.GENERATE_CONTRACTS,
            message="GENERATE_CONTRACTS completed",
            metadata={"contract_count": len(self.contract_payloads_by_id)},
        )
        await self._emit(completed)

    async def _render_bundle(self) -> None:
        assert self.machine is not None
        assert self.source_manifest is not None
        assert self.terminology is not None
        assert self.screen_catalog is not None
        assert self.readiness is not None

        started = self.machine.start_step(
            RunStep.RENDER_BUNDLE,
            metadata={"screen_count": len(self.screen_catalog.screens)},
        )
        await self._emit(started)

        readiness_by_screen = {item.screen_id: item for item in self.readiness.screens}
        screen_artifacts: list[ScreenBundleArtifact] = []
        for entry in self.screen_catalog.screens:
            screen = self.canonical_screens_by_id[entry.screen_id]
            review = self.reviews_by_id[entry.screen_id]
            matrices = self.matrices_by_id[entry.screen_id]
            screen_readiness = readiness_by_screen[entry.screen_id]
            fe_markdown = render_fe_spec_markdown(
                entry,
                screen,
                matrices=matrices,
                review=review,
                readiness=screen_readiness,
            )
            be_markdown = render_be_spec_markdown(
                entry,
                screen,
                matrices=matrices,
                review=review,
                readiness=screen_readiness,
            )
            questions_markdown = render_question_backlog_markdown(review)
            self.store.save_fe_spec_markdown(entry.screen_id, fe_markdown)
            self.store.save_be_spec_markdown(entry.screen_id, be_markdown)
            self.store.save_questions_markdown(entry.screen_id, questions_markdown)

            contract_yaml, mock_data_json = self.contract_payloads_by_id.get(entry.screen_id, (None, None))
            screen_artifacts.append(
                ScreenBundleArtifact(
                    screen_id=entry.screen_id,
                    canonical_json=screen.model_dump_json(indent=2),
                    fe_markdown=fe_markdown,
                    be_markdown=be_markdown,
                    questions_markdown=questions_markdown,
                    field_matrix_csv=render_field_matrix_csv(matrices.field_rows),
                    action_rule_matrix_csv=render_action_rule_matrix_csv(matrices.action_rule_rows),
                    api_matrix_csv=render_api_matrix_csv(matrices.api_rows),
                    contract_yaml=contract_yaml,
                    mock_data_json=mock_data_json,
                )
            )

        self.rendered_screen_artifacts = list(screen_artifacts)
        self.bundle_files = write_bundle_layout(
            self.store,
            source_manifest=self.source_manifest,
            screen_catalog=self.screen_catalog,
            readiness=self.readiness,
            screen_artifacts=screen_artifacts,
            terminology=self.terminology,
            run_audit=self.store.load_run_audit(),
        )

        completed = self.machine.complete_step(
            RunStep.RENDER_BUNDLE,
            message="RENDER_BUNDLE completed",
            metadata={
                "screen_count": len(screen_artifacts),
                "bundle_file_count": len(self.bundle_files),
            },
        )
        await self._emit(completed)

    def _refresh_bundle_layout(self, *, include_qa_reports: bool) -> None:
        if (
            self.source_manifest is None
            or self.screen_catalog is None
            or self.readiness is None
            or self.terminology is None
        ):
            return

        screen_artifacts = list(self.rendered_screen_artifacts)
        if include_qa_reports:
            refreshed_artifacts: list[ScreenBundleArtifact] = []
            for artifact in screen_artifacts:
                qa_report_json = artifact.qa_report_json
                try:
                    qa_report_json = self.store.load_qa_report_json(artifact.screen_id)
                except Exception:
                    pass
                refreshed_artifacts.append(
                    artifact.model_copy(update={"qa_report_json": qa_report_json})
                )
            screen_artifacts = refreshed_artifacts
            self.rendered_screen_artifacts = refreshed_artifacts

        self.bundle_files = write_bundle_layout(
            self.store,
            source_manifest=self.source_manifest,
            screen_catalog=self.screen_catalog,
            readiness=self.readiness,
            screen_artifacts=screen_artifacts,
            terminology=self.terminology,
            run_audit=self.store.load_run_audit(),
        )

    async def _validate_bundle(self) -> BAPipelineResult | None:
        assert self.machine is not None
        assert self.source_manifest is not None
        assert self.screen_catalog is not None
        assert self.readiness is not None

        started = self.machine.start_step(
            RunStep.VALIDATE_BUNDLE,
            metadata={"bundle_file_count": len(self.bundle_files)},
        )
        await self._emit(started)
        self._refresh_bundle_layout(include_qa_reports=False)

        if self.services.validate_bundle is None:
            self.validation_report = ValidationReport(
                run_id=self.store.run_id,
                feature_key=self.store.feature_key,
                status=ValidationStatus.WARN,
                warnings=[
                    "Bundle validation hooks are not implemented yet; qa-report generation was skipped."
                ],
            )
        else:
            try:
                self.validation_report = await _maybe_await(
                    self.services.validate_bundle(
                        self.store,
                        self.source_manifest,
                        self.screen_catalog,
                        self.readiness,
                        self.rendered_screen_artifacts,
                    )
                )
            except Exception as exc:
                await self._fail_step(RunStep.VALIDATE_BUNDLE, exc)
                raise

            if not isinstance(self.validation_report, ValidationReport):
                msg = (
                    "validate_bundle must return ValidationReport, "
                    f"got {type(self.validation_report)!r}"
                )
                raise TypeError(msg)

        self._extend_warnings(self.validation_report.warnings)
        if self.validation_report.status is ValidationStatus.FAIL:
            return await self._halt(
                RunStep.VALIDATE_BUNDLE,
                reason="bundle validation reported failing findings",
                metadata={
                    "status": self.validation_report.status.value,
                    "finding_count": len(self.validation_report.findings),
                },
            )

        completed = self.machine.complete_step(
            RunStep.VALIDATE_BUNDLE,
            message="VALIDATE_BUNDLE completed",
            metadata={
                "status": self.validation_report.status.value,
                "finding_count": len(self.validation_report.findings),
                "warning_count": len(self.validation_report.warnings),
                "validation_skipped": self.services.validate_bundle is None,
                },
            )
        await self._emit(completed)
        self._refresh_bundle_layout(include_qa_reports=True)
        return None

    async def _degrade(
        self,
        step: RunStep,
        *,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> BAPipelineResult:
        assert self.machine is not None
        state = self.machine.mark_degraded(
            reason,
            step=step,
            message=f"{step.value} degraded",
            metadata=metadata,
        )
        await self._emit(state)
        return self._result(stop_step=step, stop_reason=reason)

    async def _halt(
        self,
        step: RunStep,
        *,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> BAPipelineResult:
        assert self.machine is not None
        state = self.machine.halt(
            reason,
            step=step,
            message=f"{step.value} halted",
            metadata=metadata,
        )
        await self._emit(state)
        return self._result(stop_step=step, stop_reason=reason)

    async def _fail_step(self, step: RunStep, exc: Exception) -> None:
        assert self.machine is not None
        try:
            state = self.machine.fail(
                sanitize_error_message(str(exc)),
                step=step,
                message=f"{step.value} failed",
                metadata={"exception_type": type(exc).__name__},
            )
        except RunStateTransitionError:
            return
        await self._emit(state)

    async def _emit(self, state: RunStateSnapshot) -> None:
        if self.progress is None:
            return
        await _maybe_await(self.progress(state))

    def _extend_warnings(self, warnings: Sequence[str]) -> None:
        self.warnings = _dedupe_preserving_order((*self.warnings, *warnings))

    def _result(
        self,
        *,
        stop_step: RunStep | None = None,
        stop_reason: str | None = None,
    ) -> BAPipelineResult:
        assert self.metadata is not None
        assert self.machine is not None
        registration = self.registration
        if registration is None:
            registration = SourceRegistrationResult(
                feature_key=self.store.feature_key,
                run_id=self.store.run_id,
                manifest=SourceManifestDocument(
                    feature_key=self.store.feature_key,
                    run_id=self.store.run_id,
                ),
            )
        source_manifest = self.source_manifest or registration.manifest
        return BAPipelineResult(
            feature_key=self.store.feature_key,
            run_id=self.store.run_id,
            resolved_output_dir=self.store.feature_paths.root.as_posix(),
            metadata=self.metadata,
            mode_requested=self.mode_requested,
            dry_run=self.dry_run,
            state=self.machine.state,
            source_registration=registration,
            source_manifest=source_manifest,
            quality_assessments=list(self.quality_assessments),
            terminology=self.terminology,
            screen_catalog=self.screen_catalog,
            readiness=self.readiness,
            validation_report=self.validation_report,
            bundle_files=dict(self.bundle_files),
            warnings=_dedupe_preserving_order((*self.machine.state.warnings, *self.warnings)),
            stop_step=stop_step,
            stop_reason=stop_reason,
        )

async def _maybe_await(value: Awaitable[T] | T) -> T:
    if isawaitable(value):
        return await value
    return value


def _normalize_snapshot_result(
    store: BARunStore,
    snapshot: (
        BASourceSnapshot
        | SourceSnapshotRecord
        | tuple[str, BASourceSnapshot | SourceSnapshotRecord]
    ),
) -> SourceSnapshotRecord:
    source_key: str | None = None
    payload: BASourceSnapshot | SourceSnapshotRecord = snapshot
    if isinstance(snapshot, tuple):
        if len(snapshot) != 2:
            msg = "snapshot_sources tuple items must be (source_key, snapshot)"
            raise TypeError(msg)
        source_key, payload = snapshot

    snapshot = payload
    if isinstance(snapshot, SourceSnapshotRecord):
        if source_key is not None and snapshot.source_key != source_key:
            msg = (
                "snapshot_sources returned mismatched source_key pair: "
                f"{source_key!r} != {snapshot.source_key!r}"
            )
            raise ValueError(msg)
        return snapshot
    if not isinstance(snapshot, BASourceSnapshot):
        msg = (
            "snapshot_sources must return BASourceSnapshot or SourceSnapshotRecord items, "
            f"got {type(snapshot)!r}"
        )
        raise TypeError(msg)
    if not source_key:
        msg = "BASourceSnapshot items must be paired with a source_key"
        raise TypeError(msg)
    return store.persist_source_snapshot(
        source_key=source_key,
        notebook_source_id=snapshot.source_id,
        title=snapshot.title,
        source_type=snapshot.source_type,
        content=snapshot.content,
        char_count=snapshot.char_count,
        guide_summary=snapshot.guide_summary,
        guide_keywords=snapshot.guide_keywords,
        is_fresh=snapshot.is_fresh,
    )


def _is_completed(state: RunStateSnapshot, step: RunStep) -> bool:
    return any(record.step is step and record.status.value == "COMPLETED" for record in state.steps)


def _dedupe_preserving_order(values: Sequence[str]) -> list[str]:
    deduped: dict[str, str] = {}
    for value in values:
        deduped.setdefault(value, value)
    return list(deduped.values())


def _ingest_stop_reason(result: BAIngestWaitResult) -> str:
    degraded_reasons = [
        item.degraded_reason
        for item in result.source_results
        if item.degraded_reason
    ]
    if degraded_reasons:
        return degraded_reasons[0]
    if result.warnings:
        return result.warnings[0]
    return f"ingest_and_wait returned {result.recommendation.value}"


def _readiness_stop_reason(summary: ReadinessSummary) -> str:
    if summary.warnings:
        return summary.warnings[0]
    return (
        "feature readiness did not allow bundle generation: "
        f"{summary.decision.value}"
    )


__all__ = [
    "BAPipelineResult",
    "BAPipelineServices",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "run_pipeline",
]
