"""Unit tests for workspace ask fan-out execution helpers."""

from __future__ import annotations

import asyncio
import json

import pytest

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import WorkspaceRecord, WorkspaceRepository, WorkspaceRunRepository
from notebooklm.profiles.manager import ProfileManager
from notebooklm.workspaces import (
    WorkspaceCandidateRecord,
    execute_workspace_query,
    plan_workspace_query,
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


def _workspace() -> WorkspaceRecord:
    return WorkspaceRecord(
        id="ws_market",
        profile_id="default",
        name="Market Intel",
        slug="market-intel",
        kind="static",
        created_at="2026-03-15T05:00:00Z",
        updated_at="2026-03-15T05:00:00Z",
    )


def _candidate(
    notebook_id: str,
    *,
    member_priority: int,
    fts_rank: float | None,
    selection_reason: str = "fts",
) -> WorkspaceCandidateRecord:
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
        selection_reason=selection_reason,
    )


@pytest.mark.asyncio
async def test_execute_workspace_query_runs_single_notebook_plan_and_persists_run(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(connection)
        workspace = _workspace()
        WorkspaceRepository(connection).upsert(workspace)
        plan = plan_workspace_query(
            query="renewal risk",
            candidates=[_candidate("nb_pricing", member_priority=9, fts_rank=-2.4)],
        )

        async def ask_notebook(candidate, question):
            return f"{candidate.notebook_title} answered {question}"

        result = await execute_workspace_query(
            connection,
            workspace=workspace,
            question="renewal risk",
            plan=plan,
            trace_id="trc_workspace_single",
            ask_notebook=ask_notebook,
        )
        fetched = WorkspaceRunRepository(connection).get(result.run.id)

    assert result.run.status == "completed"
    assert [answer.notebook_id for answer in result.answers] == ["nb_pricing"]
    assert result.failures == ()
    assert result.synthesis.answer == "Nb Pricing answered renewal risk"
    assert fetched == result.run
    assert json.loads(result.run.result_json or "{}")["provenance"][0]["notebook_id"] == "nb_pricing"


@pytest.mark.asyncio
async def test_execute_workspace_query_fans_out_concurrently_but_preserves_plan_order(tmp_path):
    db_path = tmp_path / "cache.db"
    completed: list[str] = []

    with connect_db(db_path) as connection:
        _seed_profile(connection)
        workspace = _workspace()
        WorkspaceRepository(connection).upsert(workspace)
        plan = plan_workspace_query(
            query="pricing pressure",
            candidates=[
                _candidate("nb_pricing", member_priority=9, fts_rank=-1.2),
                _candidate("nb_competitor", member_priority=5, fts_rank=-0.9),
                _candidate("nb_support", member_priority=2, fts_rank=-0.8),
            ],
        )

        async def ask_notebook(candidate, question):
            if candidate.notebook_id == "nb_pricing":
                await asyncio.sleep(0.02)
            else:
                await asyncio.sleep(0.0)
            completed.append(candidate.notebook_id)
            return f"{candidate.notebook_title} answered {question}"

        result = await execute_workspace_query(
            connection,
            workspace=workspace,
            question="pricing pressure",
            plan=plan,
            trace_id="trc_workspace_fanout",
            ask_notebook=ask_notebook,
        )

    assert result.run.status == "completed"
    assert completed[0] != "nb_pricing"
    assert [answer.notebook_id for answer in result.answers] == [
        "nb_pricing",
        "nb_competitor",
        "nb_support",
    ]
    assert result.failures == ()
    assert result.synthesis.answer.startswith("Workspace synthesis:")


@pytest.mark.asyncio
async def test_execute_workspace_query_skips_trailing_fts_candidates_when_plan_tightens_fanout(tmp_path):
    db_path = tmp_path / "cache.db"
    asked: list[str] = []

    with connect_db(db_path) as connection:
        _seed_profile(connection)
        workspace = _workspace()
        WorkspaceRepository(connection).upsert(workspace)
        plan = plan_workspace_query(
            query="pricing pressure",
            candidates=[
                _candidate("nb_pricing", member_priority=9, fts_rank=-1.2),
                _candidate("nb_competitor", member_priority=5, fts_rank=-0.9),
                _candidate("nb_support", member_priority=2, fts_rank=0.4),
            ],
        )

        async def ask_notebook(candidate, question):
            asked.append(candidate.notebook_id)
            return f"{candidate.notebook_title} answered {question}"

        result = await execute_workspace_query(
            connection,
            workspace=workspace,
            question="pricing pressure",
            plan=plan,
            trace_id="trc_workspace_trimmed",
            ask_notebook=ask_notebook,
        )

    assert result.run.status == "completed"
    assert plan.selected_notebook_ids == ("nb_pricing", "nb_competitor")
    assert asked == ["nb_pricing", "nb_competitor"]
    assert [answer.notebook_id for answer in result.answers] == [
        "nb_pricing",
        "nb_competitor",
    ]
    assert result.failures == ()


@pytest.mark.asyncio
async def test_execute_workspace_query_marks_run_failed_when_any_notebook_ask_fails(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(connection)
        workspace = _workspace()
        WorkspaceRepository(connection).upsert(workspace)
        plan = plan_workspace_query(
            query="pricing pressure",
            candidates=[
                _candidate("nb_pricing", member_priority=9, fts_rank=-1.2),
                _candidate("nb_support", member_priority=2, fts_rank=-0.8),
            ],
        )

        async def ask_notebook(candidate, question):
            if candidate.notebook_id == "nb_support":
                raise RuntimeError(f"Notebook ask failed for {question}")
            return f"{candidate.notebook_title} answered {question}"

        result = await execute_workspace_query(
            connection,
            workspace=workspace,
            question="pricing pressure",
            plan=plan,
            trace_id="trc_workspace_failed",
            ask_notebook=ask_notebook,
        )
        fetched = WorkspaceRunRepository(connection).get(result.run.id)

    assert result.run.status == "failed"
    assert [answer.notebook_id for answer in result.answers] == ["nb_pricing"]
    assert len(result.failures) == 1
    assert result.failures[0].notebook_id == "nb_support"
    assert result.failures[0].error_type == "RuntimeError"
    assert fetched == result.run
    assert json.loads(result.run.result_json or "{}")["provenance"][0]["notebook_id"] == "nb_pricing"
