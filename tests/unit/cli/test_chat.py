"""Tests for the retained chat CLI surface."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from notebooklm.cli.helpers import set_current_conversation
from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import (
    NotebookRecord,
    NotebookRepository,
    QueryResultRepository,
    QueryRunRepository,
)
from notebooklm.notebooklm_cli import cli
from notebooklm.rpc import QUERY_URL
from notebooklm.types import AskResult

from .conftest import create_mock_client, patch_client_for_module


def make_ask_result(answer="The answer is 42.") -> AskResult:
    return AskResult(
        answer=answer,
        conversation_id="a1b2c3d4-0000-0000-0000-000000000001",
        turn_number=1,
        is_follow_up=False,
        references=[],
        raw_response="",
    )


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_auth():
    with patch("notebooklm.cli.helpers.load_auth_from_storage") as mock:
        mock.return_value = {
            "SID": "test",
            "HSID": "test",
            "SSID": "test",
            "APISID": "test",
            "SAPISID": "test",
        }
        yield mock


class TestAskCommand:
    def test_ask_outputs_answer(self, runner, mock_auth):
        with patch_client_for_module("chat") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(return_value=make_ask_result())
            mock_client.chat.get_conversation_id = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["ask", "What is 42?", "-n", "nb_123"])

            assert result.exit_code == 0, result.output
            assert "The answer is 42." in result.output

    def test_ask_json_output(self, runner, mock_auth):
        with patch_client_for_module("chat") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(return_value=make_ask_result())
            mock_client.chat.get_conversation_id = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["ask", "What is 42?", "--json", "-n", "nb_123"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["route"]["intent"] == "QUERY"
        assert data["route"]["mode"] == "answer"
        assert data["run_id"].startswith("qr_")
        assert data["route"]["notebook_id"] == "nb_123"
        assert data["route"]["profile_id"] == "default"
        assert data["route"]["source_of_truth"] == "remote_http"
        assert data["route"]["cache_mode"] == "smart"
        assert data["route"]["transport"] == {
            "kind": "httpx",
            "endpoint": QUERY_URL,
            "rpcid": None,
        }
        assert data["freshness"] is None
        assert data["result"]["answer"] == "The answer is 42."
        assert data["result"]["conversation_id"] == "a1b2c3d4-0000-0000-0000-000000000001"
        assert data["result"]["turn_number"] == 1
        assert "raw_response" not in data["result"]
        assert data["cache_updates"]["tables_touched"] == [
            "query_runs",
            "query_results",
            "run_events",
        ]
        assert data["diagnostics"]["retries"] == 0
        assert data["diagnostics"]["auth_refreshed"] is False
        assert isinstance(data["diagnostics"]["elapsed_ms"], int)

    def test_ask_records_query_history_and_events(self, runner, mock_auth):
        with patch_client_for_module("chat") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(return_value=make_ask_result())
            mock_client.chat.get_conversation_id = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["ask", "What is 42?", "-n", "nb_123"])

        assert result.exit_code == 0, result.output

        with connect_db() as connection:
            query_runs = QueryRunRepository(connection).list_for_notebook("nb_123")
            assert len(query_runs) == 1
            query_run = query_runs[0]
            query_result = QueryResultRepository(connection).get(query_run.id)
            events = list_run_events(connection, query_run.trace_id)

        assert query_run.id.startswith("qr_")
        assert query_run.intent == "ask"
        assert query_run.mode == "answer"
        assert query_run.prompt_text == "What is 42?"
        assert query_run.cache_policy == "smart"
        assert query_run.route_reason == "Structured ask command uses the remote query transport."
        assert query_run.source_of_truth == "remote_http"
        assert query_run.status == "completed"
        assert query_run.started_at is not None
        assert query_run.ended_at is not None

        assert query_result is not None
        assert query_result.query_run_id == query_run.id
        assert query_result.result_type == "answer"
        assert query_result.answer_text == "The answer is 42."
        assert json.loads(query_result.citations_json) == []
        assert json.loads(query_result.result_json)["answer"] == "The answer is 42."

        assert [event.kind for event in events] == ["route.resolved", "cache.miss"]
        assert all(event.run_id == query_run.id for event in events)
        assert events[0].payload["command"] == "ask"
        assert events[0].payload["mode"] == "answer"
        assert events[1].payload["entity"] == "query_results"

    def test_ask_reuses_exact_cached_result_when_fingerprint_matches(self, runner, mock_auth):
        with connect_db() as connection:
            NotebookRepository(connection).upsert(
                NotebookRecord(
                    notebook_id="nb_123",
                    profile_id="default",
                    title="Notebook",
                    normalized_title="notebook",
                    remote_fingerprint="fp_notebook",
                )
            )

        with patch_client_for_module("chat") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(return_value=make_ask_result(answer="Cached answer"))
            mock_client.chat.get_conversation_id = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                first = runner.invoke(cli, ["ask", "What is 42?", "-n", "nb_123"])

        assert first.exit_code == 0, first.output
        set_current_conversation(None)

        with patch_client_for_module("chat") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(side_effect=AssertionError("should reuse local result"))
            mock_client.chat.get_conversation_id = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                second = runner.invoke(cli, ["ask", "What is 42?", "--json", "-n", "nb_123"])

        assert second.exit_code == 0, second.output
        payload = json.loads(second.output)
        assert payload["route"]["source_of_truth"] == "local_cache"
        assert payload["route"]["transport"] == {
            "kind": "local",
            "endpoint": None,
            "rpcid": None,
        }
        assert payload["freshness"]["used_cached_result"] is True
        assert payload["result"]["answer"] == "Cached answer"
        assert payload["cache_updates"]["tables_touched"] == [
            "query_runs",
            "query_results",
            "run_events",
        ]
        mock_client.chat.ask.assert_not_awaited()

        with connect_db() as connection:
            query_runs = QueryRunRepository(connection).list_for_notebook("nb_123")
            reused_runs = [run for run in query_runs if run.reused_from is not None]
            assert len(reused_runs) == 1
            reused_run = reused_runs[0]
            original_run = next(run for run in query_runs if run.id == reused_run.reused_from)
            events = list_run_events(connection, reused_run.trace_id)
            reused_result = QueryResultRepository(connection).get(reused_run.id)

        assert reused_run.source_of_truth == "local_cache"
        assert reused_run.status == "completed"
        assert reused_run.reused_from == original_run.id
        assert reused_result is not None
        assert reused_result.answer_text == "Cached answer"
        assert [event.kind for event in events] == ["route.resolved", "cache.hit"]

    def test_ask_resolves_exact_cached_notebook_title_without_remote_lookup(
        self, runner, mock_auth
    ):
        with connect_db() as connection:
            NotebookRepository(connection).upsert(
                NotebookRecord(
                    notebook_id="nb_pricing",
                    profile_id="default",
                    title="Pricing",
                    normalized_title="pricing",
                )
            )

        with patch_client_for_module("chat") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(return_value=make_ask_result())
            mock_client.chat.get_conversation_id = AsyncMock(return_value=None)
            mock_client.notebooks.list = AsyncMock(
                side_effect=AssertionError("ask title resolution should stay local-first")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["ask", "What changed?", "-n", "Pricing"])

        assert result.exit_code == 0, result.output
        mock_client.chat.ask.assert_awaited_once_with(
            "nb_pricing",
            "What changed?",
            source_ids=None,
            conversation_id=None,
        )

    def test_ask_fails_when_cached_title_resolution_is_ambiguous(self, runner, mock_auth):
        with connect_db() as connection:
            repository = NotebookRepository(connection)
            repository.upsert(
                NotebookRecord(
                    notebook_id="nb_pricing",
                    profile_id="default",
                    title="Pricing",
                    normalized_title="pricing",
                )
            )
            repository.upsert(
                NotebookRecord(
                    notebook_id="nb_pricing_review",
                    profile_id="default",
                    title="Pricing Review",
                    normalized_title="pricing review",
                )
            )

        with patch_client_for_module("chat") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(return_value=make_ask_result())
            mock_client.chat.get_conversation_id = AsyncMock(return_value=None)
            mock_client.notebooks.list = AsyncMock(
                side_effect=AssertionError("ambiguous title should fail before remote resolution")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["ask", "What changed?", "-n", "pri"])

        assert result.exit_code == 1, result.output
        assert "Ambiguous notebook 'pri' matches 2 cached notebooks" in result.output
        mock_client.chat.ask.assert_not_awaited()

    @pytest.mark.parametrize("command", ["configure"])
    def test_removed_chat_commands_are_unavailable(self, runner, command):
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 2
        assert "No such command" in result.output


class TestAskServerResumed:
    def test_ask_shows_resumed_when_no_local_conv_but_server_has_one(
        self, runner, mock_auth, tmp_path
    ):
        """When context has no conv ID but server returns one, output should say 'Resumed'."""
        context_file = tmp_path / "context.json"
        context_file.write_text('{"notebook_id": "nb_123"}')

        # is_follow_up=True because ask() was called with a conversation_id from server
        ask_result = AskResult(
            answer="The answer.",
            conversation_id="conv-server-abc",
            turn_number=1,
            is_follow_up=True,
            references=[],
            raw_response="",
        )

        with patch_client_for_module("chat") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(return_value=ask_result)
            mock_client.chat.get_conversation_id = AsyncMock(return_value="conv-server-abc")
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
                patch("notebooklm.cli.helpers.get_context_path", return_value=context_file),
            ):
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["ask", "-n", "nb_123", "question"])

        assert result.exit_code == 0, result.output
        assert "Resumed conversation:" in result.output
        assert "(turn 1)" not in result.output

    def test_ask_shows_turn_number_for_local_follow_up(self, runner, mock_auth, tmp_path):
        """When context has a local conv ID, follow-up should show turn number."""
        context_file = tmp_path / "context.json"
        context_file.write_text('{"notebook_id": "nb_123", "conversation_id": "conv-local-abc"}')

        ask_result = AskResult(
            answer="The answer.",
            conversation_id="conv-local-abc",
            turn_number=2,
            is_follow_up=True,
            references=[],
            raw_response="",
        )

        with patch_client_for_module("chat") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(return_value=ask_result)
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
                patch("notebooklm.cli.helpers.get_context_path", return_value=context_file),
            ):
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["ask", "-n", "nb_123", "follow-up question"])

        assert result.exit_code == 0, result.output
        assert "Conversation: conv-local-abc (turn 2)" in result.output
        assert "Resumed" not in result.output
