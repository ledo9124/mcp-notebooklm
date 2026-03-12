"""Operational metrics boundary for BA workflow usefulness reporting."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any

from pydantic import Field, model_validator

from .models import (
    BAModel,
    ReadinessSummary,
    RunStateSnapshot,
    RunStatus,
    RunStep,
    ScreenCatalogDocument,
    SourceManifestDocument,
    ValidationReport,
    ValidationStatus,
)
from .reruns import RerunDecision, RerunPlan
from .schema_version import SchemaFamily, current_schema_version

MODULE_PURPOSE = (
    "Own local-first operational metrics snapshots, history, and reporting helpers "
    "for BA pipeline usefulness."
)

OWNS = (
    "Typed metrics snapshots/history for BA runs",
    "Proxy calculations for workflow usefulness metrics the repo can observe locally",
    "Human-readable evaluation summaries derived from persisted BA artifacts",
)

MUST_NOT_OWN = (
    "NotebookLM transport or API calls",
    "Filesystem persistence mechanics",
    "Rendered bundle validation logic itself",
    "MCP tool registration",
)

GROUNDING_FINDING_CODES = frozenset(
    {
        "confirmed-fact-missing-evidence",
        "manifest-missing-notebook-source-id",
        "manifest-missing-snapshot",
        "manifest-missing-parse-quality",
        "missing-snapshot-metadata",
        "missing-snapshot-fulltext",
        "missing-source-manifest-coverage",
        "terminology-missing-source",
    }
)

CONTRACT_BREAKAGE_FINDING_CODES = frozenset(
    {
        "missing-provisional-contract",
        "missing-mock-data",
        "invalid-contract-yaml",
        "invalid-mock-data-json",
        "contract-mock-misalignment",
    }
)

FALSE_BLOCKER_STAGES = frozenset(
    {
        RunStep.INGEST_AND_WAIT.value,
        RunStep.ASSESS_SOURCE_QUALITY.value,
        RunStep.EVALUATE_READINESS.value,
        RunStep.VALIDATE_BUNDLE.value,
    }
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MetricBasis(str, Enum):
    EXACT = "EXACT"
    PROXY = "PROXY"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MetricsCaptureSource(str, Enum):
    RUN_PIPELINE = "RUN_PIPELINE"
    VALIDATE_BUNDLE = "VALIDATE_BUNDLE"
    RERUN_IMPACTED = "RERUN_IMPACTED"


class MetricMeasurement(BAModel):
    value: float | int | None = None
    unit: str = Field(min_length=1)
    basis: MetricBasis
    numerator: float | int | None = None
    denominator: float | int | None = None
    summary: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class RunMetricsSnapshot(BAModel):
    schema_version: str = Field(
        default_factory=lambda: current_schema_version(SchemaFamily.METRICS_REPORT)
    )
    feature_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    generated_at: str = Field(default_factory=_utc_now_iso)
    source: MetricsCaptureSource
    run_status: RunStatus
    current_step: RunStep | None = None
    blocking_stage: str | None = None
    screen_count: int = Field(ge=0, default=0)
    registered_source_count: int | None = Field(default=None, ge=0)
    source_snapshot_fingerprint: str | None = None
    validation_status: ValidationStatus | None = None
    qa_finding_count: int = Field(ge=0, default=0)
    qa_warning_count: int = Field(ge=0, default=0)
    qa_findings_by_code: dict[str, int] = Field(default_factory=dict)
    qa_findings_by_severity: dict[str, int] = Field(default_factory=dict)
    latest_rerun_decision: RerunDecision | None = None
    latest_rerun_impacted_screen_count: int | None = Field(default=None, ge=0)
    latest_rerun_changed_source_count: int | None = Field(default=None, ge=0)
    average_manual_edits_per_screen: MetricMeasurement
    false_blocker_rate: MetricMeasurement
    rerun_scope_reduction_percentage: MetricMeasurement
    time_to_first_fe_spec_seconds: MetricMeasurement
    ungrounded_facts_caught_by_qa: MetricMeasurement
    fe_first_without_later_contract_breakage_percentage: MetricMeasurement
    notes: list[str] = Field(default_factory=list)


class RunMetricsHistoryDocument(BAModel):
    schema_version: str = Field(
        default_factory=lambda: current_schema_version(SchemaFamily.METRICS_REPORT)
    )
    feature_key: str = Field(min_length=1)
    entries: list[RunMetricsSnapshot] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_feature_scope(self) -> "RunMetricsHistoryDocument":
        for entry in self.entries:
            if entry.feature_key != self.feature_key:
                raise ValueError("metrics history entries must match document feature_key")
        return self


def build_metrics_snapshot(
    *,
    feature_key: str,
    run_id: str,
    source: MetricsCaptureSource,
    state: RunStateSnapshot,
    run_created_at: str | None,
    source_manifest: SourceManifestDocument | None = None,
    screen_catalog: ScreenCatalogDocument | None = None,
    readiness: ReadinessSummary | None = None,
    validation_report: ValidationReport | None = None,
    rerun_plan: RerunPlan | None = None,
    history_entries: Sequence[RunMetricsSnapshot] = (),
    notes: Sequence[str] = (),
) -> RunMetricsSnapshot:
    findings = list(validation_report.findings) if validation_report is not None else []
    snapshot = RunMetricsSnapshot(
        feature_key=feature_key,
        run_id=run_id,
        source=source,
        run_status=state.status,
        current_step=state.current_step,
        blocking_stage=_blocking_stage(state),
        screen_count=_screen_count(readiness=readiness, screen_catalog=screen_catalog),
        registered_source_count=len(source_manifest.rows) if source_manifest is not None else None,
        source_snapshot_fingerprint=_source_snapshot_fingerprint(source_manifest),
        validation_status=validation_report.status if validation_report is not None else None,
        qa_finding_count=len(findings),
        qa_warning_count=len(validation_report.warnings) if validation_report is not None else 0,
        qa_findings_by_code=_count_by_code(findings),
        qa_findings_by_severity=_count_by_severity(findings),
        latest_rerun_decision=rerun_plan.decision if rerun_plan is not None else None,
        latest_rerun_impacted_screen_count=(
            len(rerun_plan.impacted_screens) if rerun_plan is not None else None
        ),
        latest_rerun_changed_source_count=(
            len(rerun_plan.changed_sources) if rerun_plan is not None else None
        ),
        average_manual_edits_per_screen=_not_available_metric(
            unit="validation-reruns/screen",
            summary="Screen counts are required before manual-edit proxies can be computed.",
        ),
        false_blocker_rate=_not_available_metric(
            unit="percent",
            summary="No blocker history has been recorded yet.",
        ),
        rerun_scope_reduction_percentage=_not_applicable_metric(
            unit="percent",
            summary="No incremental rerun decision has been recorded yet.",
        ),
        time_to_first_fe_spec_seconds=_not_available_metric(
            unit="seconds",
            summary="Render completion has not been recorded yet.",
        ),
        ungrounded_facts_caught_by_qa=_not_available_metric(
            unit="findings",
            summary="Validation findings are required before grounding catches can be counted.",
        ),
        fe_first_without_later_contract_breakage_percentage=_not_available_metric(
            unit="percent",
            summary="Readiness and validation context are required before FE-first stability can be scored.",
        ),
        notes=_dedupe_texts(notes),
    )
    combined_history = [*history_entries, snapshot]
    return snapshot.model_copy(
        update={
            "average_manual_edits_per_screen": _average_manual_edits_metric(
                snapshot.screen_count,
                combined_history,
            ),
            "false_blocker_rate": _false_blocker_rate_metric(combined_history),
            "rerun_scope_reduction_percentage": _rerun_scope_reduction_metric(
                screen_count=snapshot.screen_count,
                rerun_plan=rerun_plan,
            ),
            "time_to_first_fe_spec_seconds": _time_to_first_fe_spec_metric(
                state=state,
                run_created_at=run_created_at,
            ),
            "ungrounded_facts_caught_by_qa": _ungrounded_facts_metric(validation_report),
            "fe_first_without_later_contract_breakage_percentage": _fe_first_contract_stability_metric(
                readiness=readiness,
                validation_report=validation_report,
            ),
        }
    )


def render_metrics_summary_markdown(
    snapshot: RunMetricsSnapshot,
    *,
    history: RunMetricsHistoryDocument | None = None,
) -> str:
    lines = [
        "# Operational Metrics",
        "",
        f"- Feature key: `{snapshot.feature_key}`",
        f"- Run id: `{snapshot.run_id}`",
        f"- Generated at: `{snapshot.generated_at}`",
        f"- Captured from: `{snapshot.source.value}`",
        f"- Run status: `{snapshot.run_status.value}`",
        f"- Current step: `{snapshot.current_step.value if snapshot.current_step is not None else 'none'}`",
        f"- Screen count: {snapshot.screen_count}",
        f"- Registered source count: {snapshot.registered_source_count if snapshot.registered_source_count is not None else 'n/a'}",
        f"- Validation status: `{snapshot.validation_status.value if snapshot.validation_status is not None else 'n/a'}`",
        f"- Metrics history entries: {len(history.entries) if history is not None else 1}",
        "",
        "## Metrics",
        "",
    ]

    for label, measurement in (
        ("Average manual edits per screen", snapshot.average_manual_edits_per_screen),
        ("False blocker rate", snapshot.false_blocker_rate),
        ("Rerun scope reduction percentage", snapshot.rerun_scope_reduction_percentage),
        ("Time to first FE spec", snapshot.time_to_first_fe_spec_seconds),
        ("Ungrounded facts caught by QA", snapshot.ungrounded_facts_caught_by_qa),
        (
            "FE-first without later contract breakage percentage",
            snapshot.fe_first_without_later_contract_breakage_percentage,
        ),
    ):
        lines.append(
            f"- {label}: {_format_measurement_value(measurement)} (`{measurement.basis.value}`)"
        )
        lines.append(f"  {measurement.summary}")

    lines.extend(
        [
            "",
            "## QA Breakdown",
            "",
            f"- Findings: {snapshot.qa_finding_count}",
            f"- Warnings: {snapshot.qa_warning_count}",
        ]
    )
    if snapshot.qa_findings_by_code:
        lines.append("- Findings by code:")
        for code, count in snapshot.qa_findings_by_code.items():
            lines.append(f"  - `{code}`: {count}")
    else:
        lines.append("- Findings by code: none recorded.")

    if snapshot.qa_findings_by_severity:
        lines.append("- Findings by severity:")
        for severity, count in snapshot.qa_findings_by_severity.items():
            lines.append(f"  - `{severity}`: {count}")

    if snapshot.latest_rerun_decision is not None:
        lines.extend(
            [
                "",
                "## Latest Rerun Context",
                "",
                f"- Decision: `{snapshot.latest_rerun_decision.value}`",
                f"- Changed sources: {snapshot.latest_rerun_changed_source_count or 0}",
                f"- Impacted screens: {snapshot.latest_rerun_impacted_screen_count or 0}",
            ]
        )

    if snapshot.notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in snapshot.notes)

    if history is not None and history.entries:
        lines.extend(["", "## Recent History", ""])
        for entry in history.entries[-5:]:
            validation_value = entry.validation_status.value if entry.validation_status is not None else "n/a"
            lines.append(
                "- `{created}` source=`{source}` status=`{status}` validation=`{validation}`".format(
                    created=entry.generated_at,
                    source=entry.source.value,
                    status=entry.run_status.value,
                    validation=validation_value,
                )
            )

    return "\n".join(lines).rstrip() + "\n"


def _screen_count(
    *,
    readiness: ReadinessSummary | None,
    screen_catalog: ScreenCatalogDocument | None,
) -> int:
    if readiness is not None:
        return len(readiness.screens)
    if screen_catalog is not None:
        return len(screen_catalog.screens)
    return 0


def _blocking_stage(state: RunStateSnapshot) -> str | None:
    if state.current_step is not None:
        return state.current_step.value
    for record in reversed(state.steps):
        if record.status.value in {"DEGRADED", "HALTED", "FAILED"}:
            return record.step.value
    if state.status in {RunStatus.DEGRADED, RunStatus.HALTED, RunStatus.FAILED}:
        for record in reversed(state.steps):
            if record.completed_at is not None:
                return record.step.value
    return None


def _source_snapshot_fingerprint(source_manifest: SourceManifestDocument | None) -> str | None:
    if source_manifest is None or not source_manifest.rows:
        return None
    payload = [
        {
            "source_key": row.source_key,
            "snapshot_id": row.snapshot_id,
            "notebook_source_id": row.notebook_source_id,
            "status": row.status.value,
        }
        for row in sorted(source_manifest.rows, key=lambda item: item.source_key)
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _count_by_code(findings: Sequence[Any]) -> dict[str, int]:
    counter = Counter(finding.code for finding in findings)
    return dict(sorted(counter.items()))


def _count_by_severity(findings: Sequence[Any]) -> dict[str, int]:
    counter = Counter(finding.severity.value for finding in findings)
    return dict(sorted(counter.items()))


def _average_manual_edits_metric(
    screen_count: int,
    history_entries: Sequence[RunMetricsSnapshot],
) -> MetricMeasurement:
    if screen_count <= 0:
        return _not_available_metric(
            unit="validation-reruns/screen",
            summary="Screen counts are required before manual-edit proxies can be computed.",
        )
    validation_refreshes = sum(
        1 for entry in history_entries if entry.source is MetricsCaptureSource.VALIDATE_BUNDLE
    )
    value = round(validation_refreshes / screen_count, 3)
    return MetricMeasurement(
        value=value,
        unit="validation-reruns/screen",
        basis=MetricBasis.PROXY,
        numerator=validation_refreshes,
        denominator=screen_count,
        summary=(
            "Uses standalone `ba.validate_bundle` refreshes as the local-first proxy "
            "for manual touch cycles per screen."
        ),
    )


def _false_blocker_rate_metric(
    history_entries: Sequence[RunMetricsSnapshot],
) -> MetricMeasurement:
    blocker_entries: list[tuple[int, RunMetricsSnapshot]] = []
    for index, entry in enumerate(history_entries):
        if entry.run_status not in {RunStatus.DEGRADED, RunStatus.HALTED}:
            continue
        if entry.blocking_stage not in FALSE_BLOCKER_STAGES:
            continue
        if not entry.source_snapshot_fingerprint:
            continue
        blocker_entries.append((index, entry))

    if not blocker_entries:
        return _not_available_metric(
            unit="percent",
            summary=(
                "No degraded or halted checkpoints with stable source fingerprints have "
                "been recorded yet."
            ),
        )

    cleared_without_source_change = 0
    for index, blocker in blocker_entries:
        later_success = next(
            (
                candidate
                for candidate in history_entries[index + 1 :]
                if candidate.run_status is RunStatus.COMPLETED
                and candidate.source_snapshot_fingerprint == blocker.source_snapshot_fingerprint
            ),
            None,
        )
        if later_success is not None:
            cleared_without_source_change += 1

    denominator = len(blocker_entries)
    value = round((cleared_without_source_change / denominator) * 100, 2)
    return MetricMeasurement(
        value=value,
        unit="percent",
        basis=MetricBasis.PROXY,
        numerator=cleared_without_source_change,
        denominator=denominator,
        summary=(
            "Treats degraded or halted checkpoints later cleared by a completed run with the "
            "same source snapshot fingerprint as false-blocker candidates."
        ),
    )


def _rerun_scope_reduction_metric(
    *,
    screen_count: int,
    rerun_plan: RerunPlan | None,
) -> MetricMeasurement:
    if rerun_plan is None:
        return _not_applicable_metric(
            unit="percent",
            summary="No incremental rerun decision has been recorded yet.",
        )
    if screen_count <= 0:
        return _not_available_metric(
            unit="percent",
            summary="A screen count is required before rerun scope reduction can be measured.",
        )

    if rerun_plan.decision is RerunDecision.NO_CHANGES:
        saved_screens = screen_count
    elif rerun_plan.decision is RerunDecision.FULL_FEATURE:
        saved_screens = 0
    else:
        impacted = min(len(rerun_plan.impacted_screens), screen_count)
        saved_screens = max(screen_count - impacted, 0)

    value = round((saved_screens / screen_count) * 100, 2)
    return MetricMeasurement(
        value=value,
        unit="percent",
        basis=MetricBasis.EXACT,
        numerator=saved_screens,
        denominator=screen_count,
        summary=(
            "Compares the latest rerun decision against the current screen count to show "
            "how much full-feature rerendering was avoided."
        ),
        details={"decision": rerun_plan.decision.value},
    )


def _time_to_first_fe_spec_metric(
    *,
    state: RunStateSnapshot,
    run_created_at: str | None,
) -> MetricMeasurement:
    if not run_created_at:
        return _not_available_metric(
            unit="seconds",
            summary="Run creation time is unavailable, so FE-spec latency cannot be computed.",
        )
    render_completed_at = _step_completed_at(state, RunStep.RENDER_BUNDLE)
    if render_completed_at is None:
        return _not_available_metric(
            unit="seconds",
            summary="The bundle has not reached `RENDER_BUNDLE`, so no FE spec has been emitted yet.",
        )
    value = _duration_seconds(run_created_at, render_completed_at)
    if value is None:
        return _not_available_metric(
            unit="seconds",
            summary="Stored timestamps could not be parsed for FE-spec latency.",
        )
    return MetricMeasurement(
        value=round(value, 3),
        unit="seconds",
        basis=MetricBasis.EXACT,
        summary="Measures the elapsed wall-clock time from run creation to `RENDER_BUNDLE` completion.",
    )


def _ungrounded_facts_metric(
    validation_report: ValidationReport | None,
) -> MetricMeasurement:
    if validation_report is None:
        return _not_available_metric(
            unit="findings",
            summary="Validation findings are required before grounding catches can be counted.",
        )
    count = sum(
        1 for finding in validation_report.findings if finding.code in GROUNDING_FINDING_CODES
    )
    return MetricMeasurement(
        value=count,
        unit="findings",
        basis=MetricBasis.EXACT,
        summary=(
            "Counts validation findings that catch missing evidence, missing source coverage, "
            "or broken source-grounding links."
        ),
        details={"codes": sorted(GROUNDING_FINDING_CODES)},
    )


def _fe_first_contract_stability_metric(
    *,
    readiness: ReadinessSummary | None,
    validation_report: ValidationReport | None,
) -> MetricMeasurement:
    if readiness is None:
        return _not_available_metric(
            unit="percent",
            summary="Readiness output is required before FE-first delivery coverage can be scored.",
        )
    fe_first_screen_ids = sorted(
        screen.screen_id
        for screen in readiness.screens
        if screen.fe_ready and not screen.be_ready
    )
    if not fe_first_screen_ids:
        return _not_applicable_metric(
            unit="percent",
            summary="No screens are currently being delivered in FE-first provisional mode.",
        )
    if validation_report is None:
        return _not_available_metric(
            unit="percent",
            summary=(
                "A validation report is required before FE-first screens can be checked for "
                "later contract breakage."
            ),
        )

    broken_screen_ids = {
        finding.screen_id
        for finding in validation_report.findings
        if finding.screen_id is not None and finding.code in CONTRACT_BREAKAGE_FINDING_CODES
    }
    stable_screen_count = sum(1 for screen_id in fe_first_screen_ids if screen_id not in broken_screen_ids)
    denominator = len(fe_first_screen_ids)
    value = round((stable_screen_count / denominator) * 100, 2)
    return MetricMeasurement(
        value=value,
        unit="percent",
        basis=MetricBasis.EXACT,
        numerator=stable_screen_count,
        denominator=denominator,
        summary=(
            "Measures how many FE-first provisional screens remain free of later contract "
            "or mock-data breakage findings."
        ),
    )


def _step_completed_at(state: RunStateSnapshot, step: RunStep) -> str | None:
    for record in state.steps:
        if record.step is step:
            return record.completed_at
    return None


def _duration_seconds(start: str, end: str) -> float | None:
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        return None
    return max((end_dt - start_dt).total_seconds(), 0.0)


def _not_available_metric(*, unit: str, summary: str) -> MetricMeasurement:
    return MetricMeasurement(unit=unit, basis=MetricBasis.NOT_AVAILABLE, summary=summary)


def _not_applicable_metric(*, unit: str, summary: str) -> MetricMeasurement:
    return MetricMeasurement(unit=unit, basis=MetricBasis.NOT_APPLICABLE, summary=summary)


def _format_measurement_value(measurement: MetricMeasurement) -> str:
    if measurement.value is None:
        return "n/a"
    if measurement.unit == "percent":
        return f"{float(measurement.value):.2f}%"
    if measurement.unit == "seconds":
        return f"{float(measurement.value):.3f}s"
    return str(measurement.value)


def _dedupe_texts(values: Sequence[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if not value:
            continue
        seen.setdefault(value, None)
    return list(seen)


__all__ = [
    "CONTRACT_BREAKAGE_FINDING_CODES",
    "FALSE_BLOCKER_STAGES",
    "GROUNDING_FINDING_CODES",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "MetricBasis",
    "MetricMeasurement",
    "MetricsCaptureSource",
    "OWNS",
    "RunMetricsHistoryDocument",
    "RunMetricsSnapshot",
    "build_metrics_snapshot",
    "render_metrics_summary_markdown",
]
