"""Tests for notebook CLI commands (now top-level commands)."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from notebooklm.notebooklm_cli import cli
from notebooklm.types import AskResult, Notebook

from .conftest import create_mock_client, patch_client_for_module, patch_main_cli_client


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


# =============================================================================
# NOTEBOOK LIST TESTS
# =============================================================================


class TestNotebookList:
    def test_notebook_list_empty(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.list = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["list"])

            assert result.exit_code == 0
            assert "Notebooks" in result.output

    def test_notebook_list_with_notebooks(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.list = AsyncMock(
                return_value=[
                    Notebook(
                        id="nb_1",
                        title="First Notebook",
                        created_at=datetime(2024, 1, 1),
                        is_owner=True,
                    ),
                    Notebook(
                        id="nb_2",
                        title="Second Notebook",
                        created_at=datetime(2024, 1, 2),
                        is_owner=False,
                    ),
                ]
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["list"])

            assert result.exit_code == 0
            assert "First Notebook" in result.output
            assert "Second Notebook" in result.output

    def test_notebook_list_json_output(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.list = AsyncMock(
                return_value=[
                    Notebook(
                        id="nb_1",
                        title="Test Notebook",
                        created_at=datetime(2024, 1, 1),
                        is_owner=True,
                    ),
                ]
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["list", "--json"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "notebooks" in data
            assert data["count"] == 1
            assert data["notebooks"][0]["id"] == "nb_1"


# =============================================================================
# NOTEBOOK CREATE TESTS
# =============================================================================


class TestNotebookCreate:
    def test_notebook_create(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.create = AsyncMock(
                return_value=Notebook(
                    id="new_nb_id", title="Test Notebook", created_at=datetime(2024, 1, 1)
                )
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["create", "Test Notebook"])

            assert result.exit_code == 0
            assert "Created notebook" in result.output

    def test_notebook_create_json_output(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.create = AsyncMock(
                return_value=Notebook(
                    id="new_nb_id", title="Test Notebook", created_at=datetime(2024, 1, 1)
                )
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["create", "Test Notebook", "--json"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["notebook"]["id"] == "new_nb_id"


# =============================================================================
# NOTEBOOK SUMMARY TESTS
# =============================================================================


class TestNotebookSummary:
    def test_notebook_summary(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            # Mock list for partial ID resolution
            mock_client.notebooks.list = AsyncMock(
                return_value=[
                    Notebook(
                        id="nb_123",
                        title="Test Notebook",
                        created_at=datetime(2024, 1, 1),
                        is_owner=True,
                    ),
                ]
            )
            mock_desc = MagicMock()
            mock_desc.summary = "This notebook contains research about AI."
            mock_desc.suggested_topics = []
            mock_client.notebooks.get_description = AsyncMock(return_value=mock_desc)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["summary", "-n", "nb_123"])

            assert result.exit_code == 0
            assert "Summary" in result.output
            assert "research about AI" in result.output

    def test_notebook_summary_with_topics(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            # Mock list for partial ID resolution
            mock_client.notebooks.list = AsyncMock(
                return_value=[
                    Notebook(
                        id="nb_123",
                        title="Test Notebook",
                        created_at=datetime(2024, 1, 1),
                        is_owner=True,
                    ),
                ]
            )
            mock_desc = MagicMock()
            mock_desc.summary = "This is a summary."
            mock_topic = MagicMock()
            mock_topic.question = "What is machine learning?"
            mock_desc.suggested_topics = [mock_topic]
            mock_client.notebooks.get_description = AsyncMock(return_value=mock_desc)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["summary", "-n", "nb_123", "--topics"])

            assert result.exit_code == 0
            assert "Suggested Topics" in result.output
            assert "machine learning" in result.output

    def test_notebook_summary_not_available(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            # Mock list for partial ID resolution
            mock_client.notebooks.list = AsyncMock(
                return_value=[
                    Notebook(
                        id="nb_123",
                        title="Test Notebook",
                        created_at=datetime(2024, 1, 1),
                        is_owner=True,
                    ),
                ]
            )
            mock_client.notebooks.get_description = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["summary", "-n", "nb_123"])

            assert result.exit_code == 0
            assert "No summary available" in result.output


class TestNotebookAsk:
    def test_notebook_ask(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(
                return_value=AskResult(
                    answer="This is the answer to your question.",
                    conversation_id="conv_123",
                    is_follow_up=False,
                    turn_number=1,
                )
            )
            mock_client.chat.get_conversation_id = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with (
                patch(
                    "notebooklm.cli.helpers.get_context_path",
                    return_value=Path("/nonexistent/context.json"),
                ),
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["ask", "-n", "nb_123", "What is this?"])

            assert result.exit_code == 0
            assert "This is the answer" in result.output

    def test_notebook_ask_continue_conversation(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.chat.ask = AsyncMock(
                return_value=AskResult(
                    answer="Follow-up answer",
                    conversation_id="conv_123",
                    is_follow_up=True,
                    turn_number=2,
                )
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["ask", "-n", "nb_123", "-c", "conv_123", "Follow-up"])

            assert result.exit_code == 0
            assert "Follow-up answer" in result.output


# =============================================================================
# SOURCE ADD-RESEARCH TESTS (moved from insights to source)
# =============================================================================


class TestSourceAddResearch:
    def test_source_add_research_success(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.start = AsyncMock(return_value={"task_id": "task_123"})
            mock_client.research.poll = AsyncMock(
                return_value={"status": "completed", "sources": [{"title": "Source 1"}]}
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli, ["source", "add-research", "AI research", "-n", "nb_123"]
                )

            assert result.exit_code == 0
            assert "Found 1 sources" in result.output

    def test_source_add_research_failed_to_start(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.start = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli, ["source", "add-research", "AI research", "-n", "nb_123"]
                )

            assert result.exit_code == 1
            assert "Research failed to start" in result.output

    def test_source_add_research_with_import(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.start = AsyncMock(return_value={"task_id": "task_123"})
            mock_client.research.poll = AsyncMock(
                return_value={"status": "completed", "sources": [{"id": "src_1"}]}
            )
            mock_client.research.import_sources = AsyncMock(return_value=[{"id": "src_1"}])
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli, ["source", "add-research", "AI research", "-n", "nb_123", "--import-all"]
                )

            assert result.exit_code == 0
            assert "Imported 1 sources" in result.output


# =============================================================================
# COMMAND EXISTENCE TESTS
# =============================================================================


class TestNotebookCommandsExist:
    def test_list_command_exists(self, runner):
        result = runner.invoke(cli, ["list", "--help"])
        assert result.exit_code == 0
        assert "List all notebooks" in result.output

    def test_create_command_exists(self, runner):
        result = runner.invoke(cli, ["create", "--help"])
        assert result.exit_code == 0
        assert "TITLE" in result.output

    def test_summary_command_exists(self, runner):
        result = runner.invoke(cli, ["summary", "--help"])
        assert result.exit_code == 0
        assert "Get notebook summary" in result.output

    def test_ask_command_exists(self, runner):
        result = runner.invoke(cli, ["ask", "--help"])
        assert result.exit_code == 0
        assert "QUESTION" in result.output

    @pytest.mark.parametrize("command", ["configure", "history"])
    def test_removed_chat_commands_are_unavailable(self, runner, command):
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 2
        assert "No such command" in result.output

    def test_top_level_help_shows_notebook_commands(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Verify notebook commands are at top level
        assert "list" in result.output
        assert "create" in result.output
        assert "summary" in result.output
        assert "ask" in result.output
        assert "configure" not in result.output
        assert "history" not in result.output
        # Verify there's no "notebook" command in the Commands section
        # (it should only appear as part of "NotebookLM" in the description)
        commands_section = (
            result.output.split("Commands:")[1] if "Commands:" in result.output else ""
        )
        assert "  notebook " not in commands_section.lower()
