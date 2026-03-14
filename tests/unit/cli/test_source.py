"""Tests for the retained source CLI surface."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from notebooklm.notebooklm_cli import cli
from notebooklm.types import Source, SourceNotFoundError, SourceProcessingError, SourceTimeoutError

from .conftest import create_mock_client, patch_client_for_module


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


class TestSourceList:
    def test_source_list(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_1", title="Source One")]
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "list", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "Source One" in result.output or "src_1" in result.output

    def test_source_list_json_output(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[
                    Source(id="src_1", title="Test Source", url="https://example.com"),
                ]
            )
            mock_client.notebooks.get = AsyncMock(return_value=MagicMock(title="Test Notebook"))
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "list", "-n", "nb_123", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 1
        assert data["sources"][0]["id"] == "src_1"


class TestSourceAdd:
    def test_source_add_url(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.add_url = AsyncMock(
                return_value=Source(id="src_new", title="Example", url="https://example.com")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "add", "https://example.com", "-n", "nb_123"])

        assert result.exit_code == 0
        mock_client.sources.add_url.assert_awaited_once_with("nb_123", "https://example.com")

    def test_source_add_youtube_url(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.add_url = AsyncMock(
                return_value=Source(
                    id="src_yt",
                    title="YouTube Video",
                    url="https://youtube.com/watch?v=abc123",
                )
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["source", "add", "https://youtube.com/watch?v=abc123", "-n", "nb_123"],
                )

        assert result.exit_code == 0
        mock_client.sources.add_url.assert_awaited_once()

    def test_source_add_text(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.add_text = AsyncMock(
                return_value=Source(id="src_text", title="My Text Source")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["source", "add", "Some text content", "--type", "text", "-n", "nb_123"],
                )

        assert result.exit_code == 0
        mock_client.sources.add_text.assert_awaited_once_with(
            "nb_123", "Untitled", "Some text content"
        )

    def test_source_add_text_with_title(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.add_text = AsyncMock(
                return_value=Source(id="src_text", title="Custom Title")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    [
                        "source",
                        "add",
                        "My notes",
                        "--type",
                        "text",
                        "--title",
                        "Custom Title",
                        "-n",
                        "nb_123",
                    ],
                )

        assert result.exit_code == 0
        mock_client.sources.add_text.assert_awaited_once_with(
            "nb_123", "Custom Title", "My notes"
        )

    def test_source_add_file(self, runner, mock_auth, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.add_file = AsyncMock(
                return_value=Source(id="src_file", title="test.pdf")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["source", "add", str(test_file), "--type", "file", "-n", "nb_123"],
                )

        assert result.exit_code == 0
        mock_client.sources.add_file.assert_awaited_once_with("nb_123", str(test_file), None)

    def test_source_add_json_output(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.add_url = AsyncMock(
                return_value=Source(id="src_new", title="Example", url="https://example.com")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["source", "add", "https://example.com", "-n", "nb_123", "--json"],
                )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["source"]["id"] == "src_new"


class TestSourceAddAutoDetect:
    def test_source_add_autodetect_file(self, runner, mock_auth, tmp_path):
        test_file = tmp_path / "paper.pdf"
        test_file.write_bytes(b"pdf")

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.add_file = AsyncMock(
                return_value=Source(id="src_file", title="paper.pdf")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "add", str(test_file), "-n", "nb_123"])

        assert result.exit_code == 0
        mock_client.sources.add_file.assert_awaited_once_with("nb_123", str(test_file), None)

    def test_source_add_autodetect_plain_text(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.add_text = AsyncMock(
                return_value=Source(id="src_text", title="Pasted Text")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "add", "plain text body", "-n", "nb_123"])

        assert result.exit_code == 0
        mock_client.sources.add_text.assert_awaited_once_with(
            "nb_123", "Pasted Text", "plain text body"
        )

    def test_source_add_autodetect_text_with_custom_title(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.add_text = AsyncMock(
                return_value=Source(id="src_text", title="Research")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["source", "add", "plain text body", "--title", "Research", "-n", "nb_123"],
                )

        assert result.exit_code == 0
        mock_client.sources.add_text.assert_awaited_once_with(
            "nb_123", "Research", "plain text body"
        )


class TestSourceCommands:
    @pytest.mark.parametrize("command", ["list", "add", "add-research", "wait"])
    def test_kept_source_commands_exist(self, runner, command):
        result = runner.invoke(cli, ["source", command, "--help"])
        assert result.exit_code == 0

    @pytest.mark.parametrize(
        "command",
        ["get", "delete", "rename", "refresh", "add-drive", "fulltext", "guide", "stale"],
    )
    def test_removed_source_commands_are_unavailable(self, runner, command):
        result = runner.invoke(cli, ["source", command, "--help"])
        assert result.exit_code == 2
        assert "No such command" in result.output


class TestSourceWait:
    def test_source_wait_success(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_123", title="Test Source")]
            )
            mock_client.sources.wait_until_ready = AsyncMock(
                return_value=Source(id="src_123", title="Test Source", status=2)
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "wait", "src_123", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "ready" in result.output.lower()

    def test_source_wait_success_with_title(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_123", title="My Source Title")]
            )
            mock_client.sources.wait_until_ready = AsyncMock(
                return_value=Source(id="src_123", title="My Source Title", status=2)
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "wait", "src_123", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "My Source Title" in result.output

    def test_source_wait_success_json(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_123", title="Test Source")]
            )
            mock_client.sources.wait_until_ready = AsyncMock(
                return_value=Source(id="src_123", title="Test Source", status=2)
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli, ["source", "wait", "src_123", "-n", "nb_123", "--json"]
                )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["source_id"] == "src_123"
        assert data["status"] == "ready"

    def test_source_wait_not_found(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_123", title="Test Source")]
            )
            mock_client.sources.wait_until_ready = AsyncMock(
                side_effect=SourceNotFoundError("src_123")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "wait", "src_123", "-n", "nb_123"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_source_wait_not_found_json(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_123", title="Test Source")]
            )
            mock_client.sources.wait_until_ready = AsyncMock(
                side_effect=SourceNotFoundError("src_123")
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli, ["source", "wait", "src_123", "-n", "nb_123", "--json"]
                )

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "not_found"
        assert data["source_id"] == "src_123"

    def test_source_wait_processing_error(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_123", title="Test Source")]
            )
            mock_client.sources.wait_until_ready = AsyncMock(
                side_effect=SourceProcessingError("src_123", status=3)
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "wait", "src_123", "-n", "nb_123"])

        assert result.exit_code == 1
        assert "processing failed" in result.output.lower()

    def test_source_wait_processing_error_json(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_123", title="Test Source")]
            )
            mock_client.sources.wait_until_ready = AsyncMock(
                side_effect=SourceProcessingError("src_123", status=3)
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli, ["source", "wait", "src_123", "-n", "nb_123", "--json"]
                )

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["source_id"] == "src_123"
        assert data["status_code"] == 3

    def test_source_wait_timeout(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_123", title="Test Source")]
            )
            mock_client.sources.wait_until_ready = AsyncMock(
                side_effect=SourceTimeoutError("src_123", timeout=30.0, last_status=1)
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "wait", "src_123", "-n", "nb_123"])

        assert result.exit_code == 2
        assert "timeout" in result.output.lower()

    def test_source_wait_timeout_json(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[Source(id="src_123", title="Test Source")]
            )
            mock_client.sources.wait_until_ready = AsyncMock(
                side_effect=SourceTimeoutError("src_123", timeout=30.0, last_status=1)
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli, ["source", "wait", "src_123", "-n", "nb_123", "--json"]
                )

        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["status"] == "timeout"
        assert data["source_id"] == "src_123"
        assert data["timeout_seconds"] == 30
        assert data["last_status_code"] == 1
