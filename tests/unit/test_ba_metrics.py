"""Unit tests for BA operational metrics helpers."""

from __future__ import annotations

from notebooklm_mcp.ba.metrics import (
    MetricBasis,
    MetricsCaptureSource,
    build_metrics_snapshot,
    render_metrics_summary_markdown,
)
from notebooklm_mcp.ba.models import (
    ReadinessDecision,
    ReadinessSummary,
    RunStateSnapshot,
    RunStatus,
    RunStep,
    RunStepRecord,
    RunStepStatus,
    ScreenReadiness,
    SourceContentKind,
    SourceLifecycleStatus,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceType,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    WorkflowMode,
)
from notebooklm_mcp.ba.reruns import ImpactedScreen, RerunDecision, RerunPlan


def _manifest(*, feature_key: str, run_id: str, count: int = 1) -> SourceManifestDocument:
    return SourceManifestDocument(
        feature_key=feature_key,
        run_id=run_id,
        rows=[
            SourceManifestRow(
                source_key=f"source-{index}",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.INLINE_TEXT,
                source_ref=f"Inline source {index}",
                notebook_source_id=f"nb-src-{index}",
                snapshot_id=f"snap-{index}",
                status=SourceLifecycleStatus.READY,
            )
            for index in range(1, count + 1)
        ],
    )


def _readiness(
    *,
    feature_key: str,
    run_id: str,
    screens: list[tuple[str, bool, bool]],
    decision: ReadinessDecision,
) -> ReadinessSummary:
    return ReadinessSummary(
        feature_key=feature_key,
        run_id=run_id,
        feature_mode=WorkflowMode.FE_FIRST,
        decision=decision,
        screens=[
            ScreenReadiness(
                screen_id=screen_id,
                resolved_mode=WorkflowMode.FE_FIRST,
                fe_ready=fe_ready,
                be_ready=be_ready,
            )
            for screen_id, fe_ready, be_ready in screens
        ],
    )


def _state(
    *,
    feature_key: str,
    run_id: str,
    status: RunStatus,
    step: RunStep | None = None,
    render_completed_at: str | None = None,
) -> RunStateSnapshot:
    steps = []
    if step is not None:
        steps.append(
            RunStepRecord(
                step=step,
                status=(
                    RunStepStatus.COMPLETED
                    if status is RunStatus.COMPLETED
                    else RunStepStatus.HALTED
                ),
                started_at="2026-03-12T10:00:05+00:00",
                completed_at="2026-03-12T10:00:20+00:00",
                halt_reason="needs clarification" if status is not RunStatus.COMPLETED else None,
            )
        )
    if render_completed_at is not None:
        steps.append(
            RunStepRecord(
                step=RunStep.RENDER_BUNDLE,
                status=RunStepStatus.COMPLETED,
                started_at="2026-03-12T10:00:20+00:00",
                completed_at=render_completed_at,
            )
        )
    if status is RunStatus.COMPLETED:
        steps.append(
            RunStepRecord(
                step=RunStep.VALIDATE_BUNDLE,
                status=RunStepStatus.COMPLETED,
                started_at="2026-03-12T10:00:31+00:00",
                completed_at="2026-03-12T10:00:35+00:00",
            )
        )
    return RunStateSnapshot(
        feature_key=feature_key,
        run_id=run_id,
        status=status,
        current_step=step if status is not RunStatus.COMPLETED else None,
        steps=steps,
        halt_reason="needs clarification" if status is not RunStatus.COMPLETED else None,
    )


def test_build_metrics_snapshot_measures_latency_and_grounding_catches() -> None:
    report = ValidationReport(
        feature_key="customer-create",
        run_id="run-100",
        status=ValidationStatus.WARN,
        findings=[
            ValidationFinding(
                code="confirmed-fact-missing-evidence",
                severity=ValidationSeverity.WARNING,
                message="Fact is missing evidence.",
                screen_id="customer-form",
            )
        ],
    )
    snapshot = build_metrics_snapshot(
        feature_key="customer-create",
        run_id="run-100",
        source=MetricsCaptureSource.RUN_PIPELINE,
        state=_state(
            feature_key="customer-create",
            run_id="run-100",
            status=RunStatus.COMPLETED,
            render_completed_at="2026-03-12T10:00:30+00:00",
        ),
        run_created_at="2026-03-12T10:00:00+00:00",
        source_manifest=_manifest(feature_key="customer-create", run_id="run-100"),
        readiness=_readiness(
            feature_key="customer-create",
            run_id="run-100",
            screens=[("customer-form", True, True)],
            decision=ReadinessDecision.READY_FOR_FE_AND_BE,
        ),
        validation_report=report,
    )

    assert snapshot.time_to_first_fe_spec_seconds.basis is MetricBasis.EXACT
    assert snapshot.time_to_first_fe_spec_seconds.value == 30.0
    assert snapshot.ungrounded_facts_caught_by_qa.value == 1
    assert snapshot.average_manual_edits_per_screen.value == 0.0
    assert snapshot.false_blocker_rate.basis is MetricBasis.NOT_AVAILABLE
    assert snapshot.rerun_scope_reduction_percentage.basis is MetricBasis.NOT_APPLICABLE

    summary = render_metrics_summary_markdown(snapshot)
    assert "# Operational Metrics" in summary
    assert "Ungrounded facts caught by QA" in summary


def test_build_metrics_snapshot_uses_history_for_manual_edit_and_false_blocker_proxies() -> None:
    manifest = _manifest(feature_key="customer-create", run_id="run-101", count=2)
    blocker_snapshot = build_metrics_snapshot(
        feature_key="customer-create",
        run_id="run-101",
        source=MetricsCaptureSource.RUN_PIPELINE,
        state=_state(
            feature_key="customer-create",
            run_id="run-101",
            status=RunStatus.HALTED,
            step=RunStep.ASSESS_SOURCE_QUALITY,
        ),
        run_created_at="2026-03-12T10:00:00+00:00",
        source_manifest=manifest,
    )

    current_snapshot = build_metrics_snapshot(
        feature_key="customer-create",
        run_id="run-101",
        source=MetricsCaptureSource.VALIDATE_BUNDLE,
        state=_state(
            feature_key="customer-create",
            run_id="run-101",
            status=RunStatus.COMPLETED,
            render_completed_at="2026-03-12T10:00:30+00:00",
        ),
        run_created_at="2026-03-12T10:00:00+00:00",
        source_manifest=manifest,
        readiness=_readiness(
            feature_key="customer-create",
            run_id="run-101",
            screens=[("customer-form", True, True), ("customer-summary", True, True)],
            decision=ReadinessDecision.READY_FOR_FE_AND_BE,
        ),
        validation_report=ValidationReport(
            feature_key="customer-create",
            run_id="run-101",
            status=ValidationStatus.PASS,
        ),
        history_entries=[blocker_snapshot],
    )

    assert current_snapshot.average_manual_edits_per_screen.basis is MetricBasis.PROXY
    assert current_snapshot.average_manual_edits_per_screen.value == 0.5
    assert current_snapshot.false_blocker_rate.basis is MetricBasis.PROXY
    assert current_snapshot.false_blocker_rate.value == 100.0


def test_build_metrics_snapshot_computes_rerun_reduction_and_fe_first_stability() -> None:
    snapshot = build_metrics_snapshot(
        feature_key="customer-create",
        run_id="run-102",
        source=MetricsCaptureSource.RERUN_IMPACTED,
        state=_state(
            feature_key="customer-create",
            run_id="run-102",
            status=RunStatus.COMPLETED,
            render_completed_at="2026-03-12T10:00:30+00:00",
        ),
        run_created_at="2026-03-12T10:00:00+00:00",
        source_manifest=_manifest(feature_key="customer-create", run_id="run-102"),
        readiness=_readiness(
            feature_key="customer-create",
            run_id="run-102",
            screens=[
                ("screen-a", True, False),
                ("screen-b", True, False),
                ("screen-c", True, True),
                ("screen-d", True, True),
            ],
            decision=ReadinessDecision.READY_FOR_FE_WITH_PROVISIONAL_CONTRACT,
        ),
        validation_report=ValidationReport(
            feature_key="customer-create",
            run_id="run-102",
            status=ValidationStatus.WARN,
            findings=[
                ValidationFinding(
                    code="contract-mock-misalignment",
                    severity=ValidationSeverity.ERROR,
                    message="Contract and mock payload drifted.",
                    screen_id="screen-b",
                )
            ],
        ),
        rerun_plan=RerunPlan(
            feature_key="customer-create",
            run_id="run-102",
            decision=RerunDecision.SELECTIVE,
            impacted_screens=[
                ImpactedScreen(
                    screen_id="screen-a",
                    source_keys=["source-1"],
                    reasons=["requirements changed"],
                )
            ],
        ),
    )

    assert snapshot.rerun_scope_reduction_percentage.basis is MetricBasis.EXACT
    assert snapshot.rerun_scope_reduction_percentage.value == 75.0
    assert snapshot.fe_first_without_later_contract_breakage_percentage.basis is MetricBasis.EXACT
    assert snapshot.fe_first_without_later_contract_breakage_percentage.value == 50.0
