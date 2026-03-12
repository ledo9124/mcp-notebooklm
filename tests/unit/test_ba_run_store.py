"""Unit tests for BA run-store and fixture scaffolding helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from notebooklm_mcp.ba.fixtures import (
    FixtureScenario,
    ensure_fixture_skeleton,
    load_fixture_manifest,
)
from notebooklm_mcp.ba.metrics import (
    MetricBasis,
    MetricMeasurement,
    MetricsCaptureSource,
    RunMetricsSnapshot,
)
from notebooklm_mcp.ba.models import (
    RunAuditDocument,
    RunEventRecord,
    RunEventType,
    RunStateSnapshot,
    RunStatus,
    RunStep,
    RunStepRecord,
    RunStepStatus,
    WorkflowMode,
)
from notebooklm_mcp.ba.run_store import BARunStore


def test_run_store_create_initializes_expected_layout(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-001",
    )

    metadata = store.create(mode_requested=WorkflowMode.FE_FIRST)

    assert store.feature_paths.root == tmp_path / "docs/features/customer-create"
    assert store.feature_paths.screens_dir.exists()
    assert store.run_paths.root.exists()
    assert store.run_paths.snapshots_dir.exists()
    assert store.run_paths.prompts_dir.exists()
    assert store.feature_paths.run_audit_json.exists()
    assert metadata.run_artifacts.run_metadata_json == (
        "docs/features/customer-create/runs/run-001/run-metadata.json"
    )
    assert metadata.feature_bundle.metrics_summary_markdown == (
        "docs/features/customer-create/06-metrics-summary.md"
    )
    assert metadata.run_artifacts.metrics_json == (
        "docs/features/customer-create/runs/run-001/metrics.json"
    )


def test_run_store_persists_and_loads_typed_metadata_and_state(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-002",
    )
    store.create(mode_requested=WorkflowMode.BALANCED)

    metadata = store.load_metadata()
    assert metadata.mode_requested is WorkflowMode.BALANCED

    initial_audit = store.load_run_audit()
    assert len(initial_audit.entries) == 1
    assert initial_audit.entries[0].snapshot.status is RunStatus.PENDING

    store.save_run_state(
        RunStateSnapshot(
            run_id="run-002",
            feature_key="customer-create",
            status=RunStatus.RUNNING,
            current_step=RunStep.REGISTER_SOURCES,
            steps=[
                RunStepRecord(
                    step=RunStep.REGISTER_SOURCES,
                    status=RunStepStatus.RUNNING,
                    metadata={"source_keys": ["ba-pdf"]},
                )
            ],
            events=[
                RunEventRecord(
                    event_type=RunEventType.STARTED,
                    step=RunStep.REGISTER_SOURCES,
                    message="Source registration started",
                    details={"source_keys": ["ba-pdf"]},
                )
            ],
        )
    )
    loaded_state = store.load_run_state()
    assert loaded_state.status is RunStatus.RUNNING
    assert loaded_state.steps[0].metadata == {"source_keys": ["ba-pdf"]}

    audit = store.load_run_audit()
    assert len(audit.entries) == 2
    assert audit.entries[-1].snapshot.events[0].details == {"source_keys": ["ba-pdf"]}


def test_run_store_create_backfills_run_audit_from_existing_state(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-003",
    )
    store.create(mode_requested=WorkflowMode.AUTO)
    store.feature_paths.run_audit_json.unlink()

    store.save_run_state(
        RunStateSnapshot(
            run_id="run-003",
            feature_key="customer-create",
            status=RunStatus.DEGRADED,
            current_step=RunStep.ASSESS_SOURCE_QUALITY,
            steps=[
                RunStepRecord(
                    step=RunStep.ASSESS_SOURCE_QUALITY,
                    status=RunStepStatus.DEGRADED,
                    halt_reason="OCR quality too low",
                )
            ],
            warnings=["OCR quality too low"],
        ),
        record_audit=False,
    )

    store.create(mode_requested=WorkflowMode.AUTO)

    audit = store.load_run_audit()
    assert len(audit.entries) == 1
    assert audit.entries[0].snapshot.status is RunStatus.DEGRADED
    assert audit.entries[0].snapshot.current_step is RunStep.ASSESS_SOURCE_QUALITY


def test_run_store_create_backfills_run_audit_when_existing_file_is_empty(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-003b",
    )
    store.create(mode_requested=WorkflowMode.AUTO)
    store.save_run_audit(RunAuditDocument(feature_key="customer-create"))

    store.save_run_state(
        RunStateSnapshot(
            run_id="run-003b",
            feature_key="customer-create",
            status=RunStatus.RUNNING,
            current_step=RunStep.REGISTER_SOURCES,
            steps=[
                RunStepRecord(
                    step=RunStep.REGISTER_SOURCES,
                    status=RunStepStatus.RUNNING,
                )
            ],
        ),
        record_audit=False,
    )

    store.create(mode_requested=WorkflowMode.AUTO)

    audit = store.load_run_audit()
    assert len(audit.entries) == 1
    assert audit.entries[0].snapshot.status is RunStatus.RUNNING
    assert audit.entries[0].snapshot.current_step is RunStep.REGISTER_SOURCES


def test_run_store_create_does_not_duplicate_existing_audit_entries(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-003c",
    )
    store.create(mode_requested=WorkflowMode.AUTO)

    first_audit = store.load_run_audit()
    store.create(mode_requested=WorkflowMode.AUTO)
    second_audit = store.load_run_audit()

    assert len(first_audit.entries) == 1
    assert len(second_audit.entries) == 1
    assert second_audit.entries[0].snapshot.status is RunStatus.PENDING


def test_append_run_audit_entry_honors_explicit_timestamp(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-003d",
    )
    store.create(mode_requested=WorkflowMode.AUTO)

    audit = store.append_run_audit_entry(
        RunStateSnapshot(
            run_id="run-003d",
            feature_key="customer-create",
            status=RunStatus.COMPLETED,
            current_step=RunStep.RENDER_BUNDLE,
        ),
        recorded_at="2026-03-12T10:00:00+00:00",
    )

    assert audit.entries[-1].recorded_at == "2026-03-12T10:00:00+00:00"
    assert audit.entries[-1].snapshot.status is RunStatus.COMPLETED
    assert store.load_run_audit().entries[-1].snapshot.current_step is RunStep.RENDER_BUNDLE


def test_run_store_rejects_mismatched_run_state_identity(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-003e",
    )
    store.create(mode_requested=WorkflowMode.AUTO)

    with pytest.raises(ValueError, match="feature_key"):
        store.save_run_state(
            RunStateSnapshot(
                run_id="run-003e",
                feature_key="orders",
                status=RunStatus.RUNNING,
            )
        )

    with pytest.raises(ValueError, match="run_id"):
        store.append_run_audit_entry(
            RunStateSnapshot(
                run_id="run-other",
                feature_key="customer-create",
                status=RunStatus.RUNNING,
            )
        )

    assert len(store.load_run_audit().entries) == 1


def test_run_store_persists_rerun_artifacts_for_impacted_screens_and_changelog(
    tmp_path: Path,
) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-004",
    )
    store.create(mode_requested=WorkflowMode.AUTO)

    impacted_path = store.save_impacted_screens_json(
        '{\n  "changed_sources": ["requirements"],\n  "impacted_screens": ["customer-form"]\n}\n'
    )
    changelog_path = store.save_changelog_markdown(
        "# Changelog\n\n- requirements -> customer-form rerun planned.\n"
    )

    assert impacted_path == store.run_paths.impacted_screens_json
    assert changelog_path == store.feature_paths.changelog_markdown
    assert store.load_impacted_screens_json().startswith("{\n")
    assert "customer-form" in store.load_impacted_screens_json()
    assert store.load_changelog_markdown().startswith("# Changelog\n")
    assert "rerun planned" in store.load_changelog_markdown()


def test_run_store_persists_metrics_snapshot_history_and_summary(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-004b",
    )
    store.create(mode_requested=WorkflowMode.FE_FIRST)

    snapshot = RunMetricsSnapshot(
        feature_key="customer-create",
        run_id="run-004b",
        source=MetricsCaptureSource.RUN_PIPELINE,
        run_status=RunStatus.COMPLETED,
        screen_count=1,
        average_manual_edits_per_screen=MetricMeasurement(
            value=0.0,
            unit="validation-reruns/screen",
            basis=MetricBasis.PROXY,
            summary="No standalone validation reruns have been recorded yet.",
        ),
        false_blocker_rate=MetricMeasurement(
            unit="percent",
            basis=MetricBasis.NOT_AVAILABLE,
            summary="No blocker history has been recorded yet.",
        ),
        rerun_scope_reduction_percentage=MetricMeasurement(
            unit="percent",
            basis=MetricBasis.NOT_APPLICABLE,
            summary="No incremental rerun decision has been recorded yet.",
        ),
        time_to_first_fe_spec_seconds=MetricMeasurement(
            value=12.5,
            unit="seconds",
            basis=MetricBasis.EXACT,
            summary="Measured from run creation to render completion.",
        ),
        ungrounded_facts_caught_by_qa=MetricMeasurement(
            value=1,
            unit="findings",
            basis=MetricBasis.EXACT,
            summary="One grounding-related QA finding was recorded.",
        ),
        fe_first_without_later_contract_breakage_percentage=MetricMeasurement(
            unit="percent",
            basis=MetricBasis.NOT_APPLICABLE,
            summary="No screens are currently being delivered in FE-first provisional mode.",
        ),
    )

    metrics_path = store.save_metrics_snapshot(snapshot)
    history = store.append_metrics_snapshot(snapshot)
    summary_path = store.save_metrics_summary_markdown("# Operational Metrics\n")

    assert metrics_path == store.run_paths.metrics_json
    assert summary_path == store.feature_paths.metrics_summary_markdown
    assert store.load_metrics_snapshot().time_to_first_fe_spec_seconds.value == 12.5
    assert len(history.entries) == 1
    assert store.load_metrics_history().entries[0].source is MetricsCaptureSource.RUN_PIPELINE
    assert store.load_metrics_summary_markdown().startswith("# Operational Metrics\n")


def test_fixture_skeleton_creates_expected_scenarios_and_manifests(tmp_path: Path) -> None:
    layouts = ensure_fixture_skeleton(workspace_root=tmp_path)

    assert set(layouts) == set(FixtureScenario)
    assert layouts[FixtureScenario.CLEAN_FEATURE].sources_dir.exists()
    assert layouts[FixtureScenario.NOTE_CLARIFICATION].notes_dir.exists()
    assert layouts[FixtureScenario.RERUN_DIFF].before_dir is not None
    assert layouts[FixtureScenario.RERUN_DIFF].after_dir is not None
    assert layouts[FixtureScenario.RERUN_DIFF].before_dir.exists()
    assert layouts[FixtureScenario.RERUN_DIFF].after_dir.exists()

    manifest = load_fixture_manifest(layouts[FixtureScenario.GARBLED_PDF].manifest_json)
    assert manifest.scenario is FixtureScenario.GARBLED_PDF
