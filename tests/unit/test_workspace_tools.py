"""Unit tests for host-callable workspace tool wrappers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm import WorkspaceTool, WorkspaceToolDefinition, build_workspace_tool
from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import (
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
from notebooklm.types import AskResult
from notebooklm.workspaces import build_workspace_index


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


def _seed_workspace(connection) -> None:
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


def test_build_workspace_tool_exposes_agent_host_metadata():
    tool = build_workspace_tool("Market Intel", mode="compare")

    assert isinstance(tool, WorkspaceTool)
    assert isinstance(tool.definition, WorkspaceToolDefinition)
    assert tool.name == "compare_workspace_market_intel"
    assert tool.definition.workspace_slug == "market-intel"
    assert tool.definition.input_schema["required"] == ["question"]
    assert "contradictions stay visible" in tool.description
    assert "may stage local inbox proposals" in tool.description


@pytest.mark.asyncio
async def test_workspace_tool_invokes_shared_service_and_returns_canonical_envelope(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_workspace(connection)
        workspace_row = WorkspaceRepository(connection).get("ws_market")
        assert workspace_row is not None
        build_workspace_index(connection, workspace=workspace_row)

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.chat = MagicMock()
    client.chat.ask = AsyncMock(
        return_value=AskResult(
            answer="Renewal obligations tightened in the latest quarter.",
            conversation_id="conv_workspace_pricing",
            turn_number=1,
            is_follow_up=False,
        )
    )

    async def client_factory(_storage_path):
        return client

    tool = build_workspace_tool(
        "market-intel",
        db_path=db_path,
        client_factory=client_factory,
    )
    payload = await tool.invoke("What changed in renewal obligations?")

    assert payload["ok"] is True
    assert payload["route"]["intent"] == "WORKSPACE_QUERY"
    assert payload["route"]["mode"] == "workspace_ask"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["workspace"]["id"] == "ws_market"
    assert payload["result"]["answer"] == "Renewal obligations tightened in the latest quarter."
    assert payload["result"]["provenance"][0]["notebook_id"] == "nb_pricing"
    client.chat.ask.assert_awaited_once_with(
        "nb_pricing",
        "What changed in renewal obligations?",
    )

    with connect_db(db_path) as connection:
        runs = WorkspaceRunRepository(connection).list_for_workspace("ws_market")
        events = list_run_events(connection, payload["trace_id"])

    assert len(runs) == 1
    assert runs[0].mode == "ask"
    assert [event.kind for event in events] == [
        "workspace.resolve.completed",
        "workspace.query.completed",
    ]
