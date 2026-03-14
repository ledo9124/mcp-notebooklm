"""Tests for the retained chat CLI surface."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from notebooklm.notebooklm_cli import cli
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
        assert data["answer"] == "The answer is 42."
        assert data["conversation_id"] == "a1b2c3d4-0000-0000-0000-000000000001"
        assert data["turn_number"] == 1

    @pytest.mark.parametrize("command", ["configure", "history"])
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
