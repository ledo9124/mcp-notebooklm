"""Unit tests for BA MCP tool contract helpers."""

from __future__ import annotations

from pathlib import Path

from notebooklm_mcp.ba.models import WorkflowMode
from notebooklm_mcp.ba.run_store import BARunStore
from notebooklm_mcp.ba.tool_contracts import (
    BAStartRunRequest,
    NotebookLifecycle,
    PLANNED_BA_TOOL_NAMES,
    build_start_run_result,
    make_ba_tool_result,
)


def test_planned_ba_tool_names_are_unique_and_plan_aligned() -> None:
    assert len(PLANNED_BA_TOOL_NAMES) == len(set(PLANNED_BA_TOOL_NAMES))
    assert all(name.startswith("ba.") for name in PLANNED_BA_TOOL_NAMES)
    assert {
        "ba.start_run",
        "ba.run_pipeline",
        "ba.status",
        "ba.rerun_impacted",
    } <= set(PLANNED_BA_TOOL_NAMES)


def test_start_run_request_defaults_match_plan() -> None:
    request = BAStartRunRequest(
        feature_key="customer-create",
        output_dir="/tmp/workspace",
    )

    assert request.mode is WorkflowMode.AUTO
    assert request.notebook_lifecycle is NotebookLifecycle.REUSE_FEATURE_NOTEBOOK
    assert request.assumption_profile == {}


def test_build_start_run_result_uses_persisted_run_store_paths(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-101",
    )
    metadata = store.create(mode_requested=WorkflowMode.FE_FIRST)

    result = build_start_run_result(
        store=store,
        metadata=metadata,
        notebook_lifecycle=NotebookLifecycle.EPHEMERAL_RUN_NOTEBOOK,
    )

    assert result.run_id == "run-101"
    assert result.resolved_output_dir == (tmp_path / "docs/features/customer-create").as_posix()
    assert result.mode_requested is WorkflowMode.FE_FIRST
    assert result.notebook_lifecycle is NotebookLifecycle.EPHEMERAL_RUN_NOTEBOOK
    assert result.run_metadata_path == (
        tmp_path / "docs/features/customer-create/runs/run-101/run-metadata.json"
    ).as_posix()


def test_make_ba_tool_result_wraps_standard_success_envelope(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-102",
    )
    metadata = store.create(mode_requested=WorkflowMode.BALANCED)
    payload = build_start_run_result(
        store=store,
        metadata=metadata,
        notebook_lifecycle=NotebookLifecycle.REUSE_FEATURE_NOTEBOOK,
    )

    result = make_ba_tool_result(
        tool_name="ba.start_run",
        feature_key="customer-create",
        run_id="run-102",
        data=payload,
        warnings=["mode assumptions persisted locally"],
    )

    structured = result["structuredContent"]
    assert structured["ok"] is True
    assert structured["tool"] == "ba.start_run"
    assert structured["feature_key"] == "customer-create"
    assert structured["run_id"] == "run-102"
    assert structured["warnings"] == ["mode assumptions persisted locally"]
    assert structured["data"]["mode_requested"] == "BALANCED"
    assert structured["data"]["run_metadata_path"].endswith("run-metadata.json")
