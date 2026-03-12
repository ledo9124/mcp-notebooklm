"""Unit tests for shared BA MCP tool contract helpers."""

from __future__ import annotations

import json
from pathlib import Path

from notebooklm_mcp._result import to_json_compatible
from notebooklm_mcp.ba.models import RunStateSnapshot, RunStatus, WorkflowMode
from notebooklm_mcp.ba.run_store import BARunStore
from notebooklm_mcp.ba.tool_contracts import (
    NotebookLifecycle,
    PLANNED_BA_TOOL_NAMES,
    build_start_run_result,
    make_ba_tool_result,
)


def test_to_json_compatible_serializes_pydantic_models() -> None:
    payload = to_json_compatible(
        RunStateSnapshot(
            run_id="run-1",
            feature_key="customer-create",
            status=RunStatus.RUNNING,
        )
    )

    assert payload["run_id"] == "run-1"
    assert payload["feature_key"] == "customer-create"
    assert payload["status"] == "RUNNING"


def test_planned_ba_tool_names_cover_initial_public_surface() -> None:
    assert {
        "ba.start_run",
        "ba.register_sources",
        "ba.ingest_and_wait",
        "ba.build_source_manifest",
        "ba.status",
        "ba.run_pipeline",
    } <= set(PLANNED_BA_TOOL_NAMES)


def test_build_start_run_result_maps_persisted_store_metadata(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-1",
    )
    metadata = store.create(mode_requested=WorkflowMode.FE_FIRST)

    result = build_start_run_result(
        store=store,
        metadata=metadata,
        notebook_lifecycle=NotebookLifecycle.REUSE_FEATURE_NOTEBOOK,
    )

    assert result.run_id == "run-1"
    assert result.mode_requested is WorkflowMode.FE_FIRST
    assert result.notebook_lifecycle is NotebookLifecycle.REUSE_FEATURE_NOTEBOOK
    assert result.run_metadata_path.endswith("run-metadata.json")
    assert result.resolved_output_dir.endswith("docs/features/customer-create")


def test_make_ba_tool_result_keeps_text_and_structured_outputs_aligned() -> None:
    result = make_ba_tool_result(
        tool_name="ba.start_run",
        feature_key="customer-create",
        run_id="run-1",
        data={"resolved_output_dir": "/tmp/work"},
    )

    assert result["structuredContent"]["tool"] == "ba.start_run"
    text = result["content"][0]["text"]
    assert json.loads(text) == result["structuredContent"]
