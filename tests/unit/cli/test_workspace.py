"""CLI tests for `notebooklm workspace` commands."""

from __future__ import annotations

import importlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

from notebooklm.cli.workspace import workspace
from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import (
    InboxItemRepository,
    NotebookRecord,
    NotebookRepository,
    QueryResultRecord,
    QueryResultRepository,
    QueryRunRecord,
    QueryRunRepository,
    SourceRecord,
    SourceRepository,
    WorkspaceIndexEntryRepository,
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


def _seed_workspace_rows(*, include_competitor: bool = False) -> None:
    with connect_db() as connection:
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
        QueryRunRepository(connection).upsert(
            QueryRunRecord(
                id="qr_pricing_1",
                trace_id="trc_pricing_1",
                profile_id="default",
                notebook_id="nb_pricing",
                intent="ask",
                mode="answer",
                prompt_text="What changed in renewal obligations?",
                prompt_hash="hash_pricing_1",
                cache_policy="smart",
                route_reason="remote query",
                source_of_truth="remote_http",
                started_at="2026-03-15T05:02:00Z",
                ended_at="2026-03-15T05:02:02Z",
                status="completed",
            )
        )
        QueryResultRepository(connection).upsert(
            QueryResultRecord(
                query_run_id="qr_pricing_1",
                result_type="answer",
                answer_text="Renewal obligations tightened in the latest quarter.",
                citations_json='["citation-1"]',
                result_json='{"summary":"renewal obligations tightened"}',
                created_at="2026-03-15T05:02:02Z",
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


def _build_index() -> None:
    with connect_db() as connection:
        workspace_row = WorkspaceRepository(connection).get("ws_market")
        assert workspace_row is not None
        build_workspace_index(connection, workspace=workspace_row)


def _ask_result(answer: str, conversation_id: str) -> AskResult:
    return AskResult(
        answer=answer,
        conversation_id=conversation_id,
        turn_number=1,
        is_follow_up=False,
    )


def _mock_workspace_client():
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.chat = MagicMock()
    client.chat.ask = AsyncMock()
    return client


def test_workspace_list_json_lists_cached_workspaces(runner):
    _seed_workspace_rows()

    result = runner.invoke(workspace, ["list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_METADATA"
    assert payload["route"]["mode"] == "workspace_list"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["profile_id"] == "default"
    assert payload["result"]["count"] == 1
    assert payload["result"]["workspaces"][0]["id"] == "ws_market"
    assert payload["result"]["workspaces"][0]["slug"] == "market-intel"
    assert payload["result"]["workspaces"][0]["member_count"] == 1
    assert payload["result"]["workspaces"][0]["indexed_count"] == 0


def test_workspace_create_json_persists_static_workspace_and_empty_index(runner):
    with connect_db() as connection:
        _seed_profile(connection)

    result = runner.invoke(
        workspace,
        [
            "create",
            "Legal Review",
            "--description",
            "Contracts and policy notes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "workspace_create"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["workspace"]["name"] == "Legal Review"
    assert payload["result"]["workspace"]["slug"] == "legal-review"
    assert payload["result"]["workspace"]["kind"] == "static"
    assert payload["result"]["workspace"]["description"] == "Contracts and policy notes"
    assert payload["result"]["workspace"]["member_count"] == 0
    assert payload["result"]["workspace"]["indexed_count"] == 0

    with connect_db() as connection:
        workspace_row = WorkspaceRepository(connection).get_by_slug("default", "legal-review")
        assert workspace_row is not None
        assert workspace_row.description == "Contracts and policy notes"
        assert WorkspaceIndexEntryRepository(connection).list_for_workspace(workspace_row.id) == []


def test_workspace_index_json_rebuilds_workspace_corpus(runner):
    _seed_workspace_rows()

    result = runner.invoke(workspace, ["index", "market-intel", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "workspace_index"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["workspace"]["id"] == "ws_market"
    assert payload["result"]["workspace"]["slug"] == "market-intel"
    assert payload["result"]["indexed_count"] == 1
    assert payload["result"]["entries"][0]["notebook_id"] == "nb_pricing"
    assert payload["result"]["entries"][0]["notebook_title"] == "Pricing Notebook"

    with connect_db() as connection:
        entries = WorkspaceIndexEntryRepository(connection).list_for_workspace("ws_market")

    assert len(entries) == 1
    assert entries[0].source_titles_text == "Renewal Deck"


def test_workspace_add_json_resolves_local_notebook_and_rebuilds_index(runner):
    _seed_workspace_rows(include_competitor=True)

    result = runner.invoke(
        workspace,
        ["add", "market-intel", "--notebook", "competitor", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "workspace_add"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["member"]["notebook_id"] == "nb_competitor"
    assert payload["result"]["member"]["notebook_title"] == "Competitor Notebook"
    assert payload["result"]["resolved_notebook_source"] == "local_cache"
    assert payload["result"]["workspace"]["id"] == "ws_market"
    assert payload["result"]["workspace"]["member_count"] == 2
    assert payload["result"]["workspace"]["indexed_count"] == 2

    with connect_db() as connection:
        members = WorkspaceMemberRepository(connection).list_for_workspace("ws_market")
        entries = WorkspaceIndexEntryRepository(connection).list_for_workspace("ws_market")

    assert [member.notebook_id for member in members] == ["nb_pricing", "nb_competitor"]
    assert sorted(entry.notebook_id for entry in entries) == ["nb_competitor", "nb_pricing"]


def test_workspace_remove_json_deletes_member_and_rebuilds_index(runner):
    _seed_workspace_rows(include_competitor=True)
    _build_index()

    result = runner.invoke(
        workspace,
        ["remove", "market-intel", "--notebook", "competitor", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "workspace_remove"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["member"]["notebook_id"] == "nb_competitor"
    assert payload["result"]["member"]["notebook_title"] == "Competitor Notebook"
    assert payload["result"]["resolved_notebook_source"] == "local_cache"
    assert payload["result"]["workspace"]["member_count"] == 1
    assert payload["result"]["workspace"]["indexed_count"] == 1

    with connect_db() as connection:
        members = WorkspaceMemberRepository(connection).list_for_workspace("ws_market")
        entries = WorkspaceIndexEntryRepository(connection).list_for_workspace("ws_market")

    assert [member.notebook_id for member in members] == ["nb_pricing"]
    assert [entry.notebook_id for entry in entries] == ["nb_pricing"]


def test_workspace_show_json_includes_members_and_index_entries(runner):
    _seed_workspace_rows(include_competitor=True)
    _build_index()

    result = runner.invoke(workspace, ["show", "market-intel", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_METADATA"
    assert payload["route"]["mode"] == "workspace_show"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["workspace"]["id"] == "ws_market"
    assert payload["result"]["workspace"]["slug"] == "market-intel"
    assert payload["result"]["workspace"]["member_count"] == 2
    assert payload["result"]["workspace"]["indexed_count"] == 2
    assert [member["notebook_id"] for member in payload["result"]["members"]] == [
        "nb_pricing",
        "nb_competitor",
    ]
    assert payload["result"]["members"][0]["notebook_title"] == "Pricing Notebook"
    assert sorted(entry["notebook_id"] for entry in payload["result"]["entries"]) == [
        "nb_competitor",
        "nb_pricing",
    ]


def test_workspace_ask_json_executes_live_single_notebook_plan_and_records_run(
    runner,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_workspace_rows()
    _build_index()

    workspace_module = importlib.import_module("notebooklm.cli.workspace")
    mock_client = _mock_workspace_client()
    mock_client.chat.ask.return_value = _ask_result(
        "Renewal obligations tightened in the latest quarter.",
        "conv_workspace_pricing",
    )

    with patch.object(workspace_module, "NotebookLMClient") as mock_client_cls:
        mock_client_cls.return_value = mock_client
        result = runner.invoke(
            workspace,
            ["ask", "market-intel", "What changed in renewal obligations?", "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "WORKSPACE_QUERY"
    assert payload["route"]["mode"] == "workspace_ask"
    assert payload["route"]["source_of_truth"] == "mixed"
    assert payload["route"]["cache_mode"] == "network"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["workspace"]["id"] == "ws_market"
    assert payload["result"]["plan"]["mode"] == "single_notebook"
    assert payload["result"]["plan"]["selected_notebooks"][0]["id"] == "nb_pricing"
    assert payload["result"]["answer"] == "Renewal obligations tightened in the latest quarter."
    assert payload["result"]["provenance"][0]["notebook_id"] == "nb_pricing"
    assert payload["result"]["workspace_run"]["status"] == "completed"
    mock_client.chat.ask.assert_awaited_once_with(
        "nb_pricing",
        "What changed in renewal obligations?",
    )

    with connect_db() as connection:
        runs = WorkspaceRunRepository(connection).list_for_workspace("ws_market")
        events = list_run_events(connection, payload["trace_id"])

    assert len(runs) == 1
    assert runs[0].status == "completed"
    assert runs[0].mode == "ask"
    assert json.loads(runs[0].selected_notebooks_json or "[]") == ["nb_pricing"]
    assert [event.kind for event in events] == [
        "workspace.resolve.completed",
        "workspace.query.completed",
    ]
    assert events[0].run_id == runs[0].id
    assert events[0].payload["workspace_id"] == "ws_market"
    assert events[0].payload["plan_mode"] == "single_notebook"
    assert events[0].payload["selected_notebook_ids"] == ["nb_pricing"]
    assert events[1].payload["mode"] == "ask"
    assert events[1].payload["status"] == "completed"
    assert events[1].payload["answer_count"] == 1
    assert events[1].payload["failure_count"] == 0


def test_workspace_ask_renders_fanout_answer_and_provenance(
    runner,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_workspace_rows(include_competitor=True)
    _build_index()

    workspace_module = importlib.import_module("notebooklm.cli.workspace")
    mock_client = _mock_workspace_client()

    async def _ask(notebook_id: str, question: str):
        assert question == "mystery market signal"
        if notebook_id == "nb_pricing":
            return _ask_result(
                "Pricing notes point to discount pressure.",
                "conv_workspace_pricing",
            )
        return _ask_result(
            "Competitor notes point to buyer confusion.",
            "conv_workspace_competitor",
        )

    mock_client.chat.ask.side_effect = _ask

    with patch.object(workspace_module, "NotebookLMClient") as mock_client_cls:
        mock_client_cls.return_value = mock_client
        result = runner.invoke(workspace, ["ask", "market-intel", "mystery market signal"])

    assert result.exit_code == 0, result.output
    assert "Workspace synthesis:" in result.output
    assert "Pricing Notebook" in result.output
    assert "Competitor Notebook" in result.output
    assert "Workspace run:" in result.output
    assert mock_client.chat.ask.await_count == 2

    with connect_db() as connection:
        runs = WorkspaceRunRepository(connection).list_for_workspace("ws_market")

    assert len(runs) == 1
    assert runs[0].status == "completed"
    assert json.loads(runs[0].selected_notebooks_json or "[]") == [
        "nb_pricing",
        "nb_competitor",
    ]


def test_workspace_compare_json_surfaces_differences_between_notebooks(
    runner,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_workspace_rows(include_competitor=True)
    _build_index()

    workspace_module = importlib.import_module("notebooklm.cli.workspace")
    mock_client = _mock_workspace_client()

    async def _ask(notebook_id: str, question: str):
        assert question == "mystery market signal"
        if notebook_id == "nb_pricing":
            return _ask_result(
                "Pricing notes point to discount pressure.",
                "conv_workspace_pricing",
            )
        return _ask_result(
            "Competitor notes point to buyer confusion.",
            "conv_workspace_competitor",
        )

    mock_client.chat.ask.side_effect = _ask

    with patch.object(workspace_module, "NotebookLMClient") as mock_client_cls:
        mock_client_cls.return_value = mock_client
        result = runner.invoke(
            workspace,
            ["compare", "market-intel", "mystery market signal", "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "WORKSPACE_COMPARE"
    assert payload["route"]["mode"] == "workspace_compare"
    assert payload["route"]["source_of_truth"] == "mixed"
    assert payload["route"]["cache_mode"] == "network"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["workspace"]["id"] == "ws_market"
    assert payload["result"]["workspace_run"]["status"] == "completed"
    assert payload["result"]["workspace_run"]["mode"] == "compare"
    assert payload["result"]["comparison"]["single_notebook_fallback"] is False
    assert len(payload["result"]["comparison"]["differences"]) == 2
    assert "differences and contradictions remain visible" in payload["result"]["comparison"]["summary"]
    assert payload["result"]["comparison"]["differences"][0]["notebook_id"] == "nb_pricing"
    assert payload["result"]["comparison"]["differences"][1]["notebook_id"] == "nb_competitor"

    with connect_db() as connection:
        runs = WorkspaceRunRepository(connection).list_for_workspace("ws_market")
        events = list_run_events(connection, payload["trace_id"])

    assert len(runs) == 1
    assert runs[0].status == "completed"
    assert runs[0].mode == "compare"
    assert json.loads(runs[0].selected_notebooks_json or "[]") == [
        "nb_pricing",
        "nb_competitor",
    ]
    assert [event.kind for event in events] == [
        "workspace.resolve.completed",
        "workspace.query.completed",
    ]
    assert events[0].run_id == runs[0].id
    assert events[0].payload["workspace_id"] == "ws_market"
    assert events[0].payload["plan_mode"] == "fan_out"
    assert events[0].payload["selected_notebook_ids"] == [
        "nb_pricing",
        "nb_competitor",
    ]
    assert events[1].payload["mode"] == "compare"
    assert events[1].payload["status"] == "completed"
    assert events[1].payload["answer_count"] == 2
    assert events[1].payload["failure_count"] == 0


def test_workspace_compare_renders_contradictions_and_gap_fill_proposals(
    runner,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_workspace_rows(include_competitor=True)
    _build_index()

    workspace_module = importlib.import_module("notebooklm.cli.workspace")
    mock_client = _mock_workspace_client()

    async def _ask(notebook_id: str, question: str):
        assert question == "mystery market signal"
        if notebook_id == "nb_pricing":
            return _ask_result(
                "Enterprise buyers prioritize price discipline.",
                "conv_workspace_pricing",
            )
        return _ask_result(
            "Enterprise buyers prioritize support confidence.",
            "conv_workspace_competitor",
        )

    mock_client.chat.ask.side_effect = _ask

    with patch.object(workspace_module, "NotebookLMClient") as mock_client_cls:
        mock_client_cls.return_value = mock_client
        result = runner.invoke(
            workspace,
            ["compare", "market-intel", "mystery market signal"],
        )

    assert result.exit_code == 0, result.output
    assert "Contradictions" in result.output
    assert "Gap-Fill Proposals" in result.output
    assert "enterprise buyers" in result.output
    assert "Gap fill: clarify enterprise buyers" in result.output
    assert "pending" in result.output

    with connect_db() as connection:
        items = InboxItemRepository(connection).list_for_profile("default")

    assert len(items) == 1
    assert items[0].origin == "agent_proposal"
    assert items[0].kind == "report"
    assert items[0].workspace_id == "ws_market"


def test_workspace_group_help_lists_all_workspace_commands(runner):
    result = runner.invoke(workspace, ["--help"])

    assert result.exit_code == 0, result.output
    assert "list" in result.output
    assert "create" in result.output
    assert "add" in result.output
    assert "remove" in result.output
    assert "show" in result.output
    assert "ask" in result.output
    assert "compare" in result.output
    assert "index" in result.output
