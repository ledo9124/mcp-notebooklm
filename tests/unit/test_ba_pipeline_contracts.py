"""Unit tests for BA run-pipeline sequencing helpers."""

from __future__ import annotations

from notebooklm_mcp.ba.models import RunStep
from notebooklm_mcp.ba.tool_contracts import (
    PLANNED_BA_TOOL_NAMES,
    RUN_PIPELINE_DRY_RUN_STOP_STEP,
    RUN_PIPELINE_STEP_SEQUENCE,
    RUN_STEP_TOOL_NAME_MAP,
    run_pipeline_steps,
    run_pipeline_tool_names,
    tool_name_for_run_step,
)


def test_run_pipeline_sequence_matches_plan_order() -> None:
    assert RUN_PIPELINE_STEP_SEQUENCE == (
        RunStep.START_RUN,
        RunStep.REGISTER_SOURCES,
        RunStep.INGEST_AND_WAIT,
        RunStep.SNAPSHOT_SOURCES,
        RunStep.ASSESS_SOURCE_QUALITY,
        RunStep.BUILD_SOURCE_MANIFEST,
        RunStep.NORMALIZE_TERMINOLOGY,
        RunStep.BUILD_SCREEN_CATALOG,
        RunStep.EXTRACT_CANONICAL,
        RunStep.REVIEW_GAPS,
        RunStep.GENERATE_MATRICES,
        RunStep.EVALUATE_READINESS,
        RunStep.GENERATE_CONTRACTS,
        RunStep.RENDER_BUNDLE,
        RunStep.VALIDATE_BUNDLE,
    )


def test_run_pipeline_dry_run_stops_after_readiness_assessment() -> None:
    dry_run_steps = run_pipeline_steps(dry_run=True)

    assert RUN_PIPELINE_DRY_RUN_STOP_STEP is RunStep.EVALUATE_READINESS
    assert dry_run_steps == RUN_PIPELINE_STEP_SEQUENCE[:12]
    assert dry_run_steps[-1] is RunStep.EVALUATE_READINESS
    assert RunStep.GENERATE_CONTRACTS not in dry_run_steps
    assert RunStep.VALIDATE_BUNDLE not in dry_run_steps


def test_run_pipeline_tool_names_align_with_public_surface() -> None:
    assert run_pipeline_tool_names() == tuple(
        RUN_STEP_TOOL_NAME_MAP[step] for step in RUN_PIPELINE_STEP_SEQUENCE
    )
    assert set(run_pipeline_tool_names()) <= set(PLANNED_BA_TOOL_NAMES)
    assert run_pipeline_tool_names(dry_run=True)[-1] == "ba.evaluate_readiness"
    assert "ba.generate_contracts" not in run_pipeline_tool_names(dry_run=True)


def test_tool_name_for_run_step_covers_every_pipeline_step() -> None:
    assert {tool_name_for_run_step(step) for step in RUN_PIPELINE_STEP_SEQUENCE} == set(
        RUN_STEP_TOOL_NAME_MAP.values()
    )
    assert tool_name_for_run_step(RunStep.START_RUN) == "ba.start_run"
    assert tool_name_for_run_step(RunStep.VALIDATE_BUNDLE) == "ba.validate_bundle"
