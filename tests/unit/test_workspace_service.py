"""Unit tests for shared workspace query service helpers."""

from __future__ import annotations

import json

import pytest

from notebooklm.contracts import Intent
from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import (
    InboxItemRepository,
    NotebookRecord,
    NotebookRepository,
    SourceRecord,
    SourceRepository,
    WorkspaceMemberRecord,
    WorkspaceMemberRepository,
    WorkspaceRecord,
    WorkspaceRepository,
    WorkspaceRunRepository,
)
from notebooklm.profiles.manager import ProfileManager
from notebooklm.workspaces import (
    build_workspace_index,
    build_workspace_query_envelope,
    invoke_workspace_query,
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


def _seed_workspace(connection, *, include_competitor: bool = False) -> None:
    _seed_profile(connection)
    WorkspaceRepository(connection).upsert(
        WorkspaceRecord(
            id="ws_market",
            profile_id="default",
            name="Market Intel",
            slug="market-intel",
            kind="static",
            created_at="2026-03-15T05:00:00Z",
            updated_at="2026-03-15T05:00:00Z",
        )
    )
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id="nb_pricing",
            profile_id="default",
            title="Pricing Notebook",
            normalized_title="pricing notebook",
            summary_preview="Quarterly renewal plan and discount strategy",
        )
    )
    WorkspaceMemberRepository(connection).upsert(
        WorkspaceMemberRecord(
            id="wsm_pricing",
            workspace_id="ws_market",
            notebook_id="nb_pricing",
            priority=5,
            tags_json='["pricing","renewal"]',
            added_at="2026-03-15T05:01:00Z",
        )
    )
    SourceRepository(connection).upsert(
        SourceRecord(
            source_id="src_renewal",
            notebook_id="nb_pricing",
            profile_id="default",
            source_type="web_page",
            status="ready",
            title="Renewal Deck",
            content_preview="Discount ladder notes and renewal obligations",
        )
    )
    if not include_competitor:
        return

    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id="nb_competitor",
            profile_id="default",
            title="Competitor Notebook",
            normalized_title="competitor notebook",
            summary_preview="Competitor pricing pressure and buyer confusion",
        )
    )
    WorkspaceMemberRepository(connection).upsert(
        WorkspaceMemberRecord(
            id="wsm_competitor",
            workspace_id="ws_market",
            notebook_id="nb_competitor",
            priority=4,
            tags_json='["competitor","pricing"]',
            added_at="2026-03-15T05:01:30Z",
        )
    )
    SourceRepository(connection).upsert(
        SourceRecord(
            source_id="src_competitor",
            notebook_id="nb_competitor",
            profile_id="default",
            source_type="web_page",
            status="ready",
            title="Competitor Pricing Sheet",
            content_preview="Enterprise buyers are confused by competitor packaging.",
        )
    )


@pytest.mark.asyncio
async def test_invoke_workspace_query_records_runs_events_and_envelope(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_workspace(connection)
        workspace_row = WorkspaceRepository(connection).get("ws_market")
        assert workspace_row is not None
        build_workspace_index(connection, workspace=workspace_row)

    async def ask_notebook(candidate, question):
        return f"{candidate.notebook_title} answered {question}"

    with connect_db(db_path) as connection:
        invocation = await invoke_workspace_query(
            connection,
            profile_id=None,
            name_or_slug="Market Intel",
            question="renewal risk",
            trace_id="trc_workspace_service",
            ask_notebook=ask_notebook,
            mode="ask",
        )
        payload = build_workspace_query_envelope(
            trace_id="trc_workspace_service",
            elapsed_ms=17,
            invocation=invocation,
            intent=Intent.WORKSPACE_QUERY,
            route_mode="workspace_ask",
            transport_kind="local",
        )
        runs = WorkspaceRunRepository(connection).list_for_workspace("ws_market")
        events = list_run_events(connection, "trc_workspace_service")

    assert invocation.workspace.id == "ws_market"
    assert invocation.execution.run.status == "completed"
    assert payload["route"]["intent"] == "WORKSPACE_QUERY"
    assert payload["route"]["mode"] == "workspace_ask"
    assert payload["result"]["workspace"]["slug"] == "market-intel"
    assert payload["result"]["answer"] == "Pricing Notebook answered renewal risk"
    assert payload["result"]["provenance"][0]["notebook_id"] == "nb_pricing"
    assert len(runs) == 1
    assert json.loads(runs[0].selected_notebooks_json or "[]") == ["nb_pricing"]
    assert [event.kind for event in events] == [
        "workspace.resolve.completed",
        "workspace.query.completed",
    ]


@pytest.mark.asyncio
async def test_build_workspace_query_envelope_compare_uses_shared_difference_summary(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_workspace(connection, include_competitor=True)
        workspace_row = WorkspaceRepository(connection).get("ws_market")
        assert workspace_row is not None
        build_workspace_index(connection, workspace=workspace_row)

    async def ask_notebook(candidate, question):
        if candidate.notebook_id == "nb_pricing":
            return "Pricing notes point to discount pressure."
        return "Competitor notes point to buyer confusion."

    with connect_db(db_path) as connection:
        invocation = await invoke_workspace_query(
            connection,
            profile_id=None,
            name_or_slug="market-intel",
            question="mystery market signal",
            trace_id="trc_workspace_compare_service",
            ask_notebook=ask_notebook,
            mode="compare",
        )
        payload = build_workspace_query_envelope(
            trace_id="trc_workspace_compare_service",
            elapsed_ms=23,
            invocation=invocation,
            intent=Intent.WORKSPACE_COMPARE,
            route_mode="workspace_compare",
            transport_kind="local",
        )

    assert payload["route"]["intent"] == "WORKSPACE_COMPARE"
    assert payload["result"]["comparison"]["single_notebook_fallback"] is False
    assert len(payload["result"]["comparison"]["differences"]) == 2
    assert "differences and contradictions remain visible" in payload["result"]["comparison"]["summary"]


@pytest.mark.asyncio
async def test_invoke_workspace_compare_stages_gap_fill_proposals_for_contradictions(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_workspace(connection, include_competitor=True)
        workspace_row = WorkspaceRepository(connection).get("ws_market")
        assert workspace_row is not None
        build_workspace_index(connection, workspace=workspace_row)

    async def ask_notebook(candidate, question):
        assert question == "mystery market signal"
        if candidate.notebook_id == "nb_pricing":
            return "Enterprise buyers prioritize price discipline."
        return "Enterprise buyers prioritize support confidence."

    with connect_db(db_path) as connection:
        invocation = await invoke_workspace_query(
            connection,
            profile_id=None,
            name_or_slug="market-intel",
            question="mystery market signal",
            trace_id="trc_workspace_gap_fill",
            ask_notebook=ask_notebook,
            mode="compare",
        )
        payload = build_workspace_query_envelope(
            trace_id="trc_workspace_gap_fill",
            elapsed_ms=29,
            invocation=invocation,
            intent=Intent.WORKSPACE_COMPARE,
            route_mode="workspace_compare",
            transport_kind="local",
        )
        items = InboxItemRepository(connection).list_for_profile("default")
        events = list_run_events(connection, "trc_workspace_gap_fill")

    assert payload["result"]["comparison"]["single_notebook_fallback"] is False
    assert len(payload["result"]["comparison"]["contradictions"]) == 1
    assert "staged gap-fill proposals" in payload["result"]["comparison"]["summary"]
    gap_fill = payload["result"]["comparison"]["gap_fill_proposals"]
    assert gap_fill["staged"] == 1
    assert gap_fill["existing_inbox_count"] == 0
    assert len(gap_fill["inbox_items"]) == 1
    assert items[0].origin == "agent_proposal"
    assert items[0].kind == "report"
    assert items[0].workspace_id == "ws_market"
    assert items[0].notebook_id is None
    assert items[0].approval_required is False
    assert [event.kind for event in events] == [
        "workspace.resolve.completed",
        "workspace.query.completed",
        "inbox.item.created",
    ]
    assert events[1].payload["contradiction_count"] == 1
    assert events[1].payload["gap_fill_staged"] == 1
    assert events[2].payload["item_id"] == items[0].id
