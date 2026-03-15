"""Unit tests for workspace run persistence helpers."""

from __future__ import annotations

import json

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import WorkspaceRecord, WorkspaceRepository, WorkspaceRunRepository
from notebooklm.profiles.manager import ProfileManager
from notebooklm.workspaces import (
    WorkspaceCandidateRecord,
    WorkspaceNotebookAnswer,
    complete_workspace_run,
    plan_workspace_query,
    start_workspace_run,
    synthesize_workspace_answer,
)


def _seed_profile(connection) -> None:
    manager = ProfileManager(connection)
    if manager.get_profile("default") is not None:
        return
    manager.create_profile(
        profile_id="default",
        display_name="Default",
        account_email="default@example.com",
        storage_state_path="/tmp/default/storage_state.json",
        browser_profile_path="/tmp/default/browser_profile",
        is_default=True,
    )


def _candidate(notebook_id: str, *, member_priority: int, fts_rank: float) -> WorkspaceCandidateRecord:
    return WorkspaceCandidateRecord(
        entry_id=f"wsi_{notebook_id}",
        workspace_id="ws_market",
        profile_id="default",
        notebook_id=notebook_id,
        notebook_title=notebook_id.replace("_", " ").title(),
        notebook_summary=f"Summary for {notebook_id}",
        member_priority=member_priority,
        tags=("pricing",),
        recent_query_text=None,
        fts_rank=fts_rank,
        selection_reason="fts",
    )


def test_workspace_run_helpers_persist_plan_and_result(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(connection)
        workspace = WorkspaceRecord(
            id="ws_market",
            profile_id="default",
            name="Market Intel",
            slug="market-intel",
            kind="static",
            created_at="2026-03-15T05:00:00Z",
            updated_at="2026-03-15T05:00:00Z",
        )
        WorkspaceRepository(connection).upsert(workspace)

        plan = plan_workspace_query(
            query="pricing pressure",
            candidates=[
                _candidate("nb_pricing", member_priority=9, fts_rank=-2.5),
                _candidate("nb_competitor", member_priority=5, fts_rank=-0.8),
            ],
        )
        started = start_workspace_run(
            connection,
            workspace=workspace,
            trace_id="trc_workspace_1",
            query_text="pricing pressure",
            plan=plan,
            started_at="2026-03-15T05:40:00Z",
        )
        result = synthesize_workspace_answer(
            "pricing pressure",
            [
                WorkspaceNotebookAnswer(
                    notebook_id="nb_pricing",
                    notebook_title="Pricing",
                    answer_text="Discount guardrails are under pressure.",
                ),
                WorkspaceNotebookAnswer(
                    notebook_id="nb_competitor",
                    notebook_title="Competitor",
                    answer_text="Competitors are pushing lower entry pricing.",
                ),
            ],
        )
        completed = complete_workspace_run(
            connection,
            run_id=started.id,
            result=result,
            ended_at="2026-03-15T05:40:05Z",
        )
        fetched = WorkspaceRunRepository(connection).get(started.id)

    assert started.id.startswith("wr_")
    assert started.status == "running"
    assert json.loads(started.selected_notebooks_json or "[]") == ["nb_pricing"]
    assert json.loads(started.plan_json or "{}")["mode"] == "single_notebook"

    assert completed.status == "completed"
    assert completed.ended_at == "2026-03-15T05:40:05Z"
    assert fetched == completed
    assert json.loads(completed.result_json or "{}")["provenance"][0]["notebook_id"] == "nb_pricing"


def test_complete_workspace_run_raises_for_unknown_run(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(connection)
        result = synthesize_workspace_answer(
            "pricing pressure",
            [
                WorkspaceNotebookAnswer(
                    notebook_id="nb_pricing",
                    notebook_title="Pricing",
                    answer_text="Discount guardrails are under pressure.",
                )
            ],
        )
        try:
            complete_workspace_run(connection, run_id="wr_missing", result=result)
        except KeyError as exc:
            error = str(exc)
        else:
            raise AssertionError("Expected missing workspace run to raise KeyError")

    assert "Workspace run not found" in error
