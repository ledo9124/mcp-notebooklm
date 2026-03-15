"""Tests for the retained source CLI surface."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from notebooklm.contracts import RiskTier
from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import ApprovalRequestRepository, NotebookRecord, SourceRecord
from notebooklm.notebooklm_cli import cli
from notebooklm.sync import NotebookDetailState, NotebookIndexState
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


def _prepare_local_cache_home(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)
    (home / "storage_state.json").write_text("{}", encoding="utf-8")
    (home / "browser_profile").mkdir(exist_ok=True)
    connection = connect_db()
    connection.close()


def _insert_detail_sync_seed(connection, notebook_id: str) -> None:
    connection.execute(
        """
        INSERT INTO notebooks (
            notebook_id,
            profile_id,
            title,
            normalized_title,
            detail_synced_at,
            remote_fingerprint
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            notebook_id,
            "default",
            "Notebook",
            "notebook",
            "2026-03-15T04:00:00+00:00",
            "fp_before",
        ),
    )
    connection.execute(
        """
        INSERT INTO sync_runs (
            id,
            trace_id,
            profile_id,
            scope,
            target_id,
            trigger,
            started_at,
            ended_at,
            status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "sr_detail",
            "trc_detail",
            "default",
            "notebook_detail",
            notebook_id,
            "manual",
            "2026-03-15T04:00:00+00:00",
            "2026-03-15T04:00:01+00:00",
            "completed",
        ),
    )


def _insert_source_delete_seed(connection, notebook_id: str, source_id: str) -> None:
    connection.execute(
        """
        INSERT INTO sources (
            source_id,
            notebook_id,
            profile_id,
            source_type,
            title,
            status,
            synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            notebook_id,
            "default",
            "web_page",
            "Cached Source",
            "ready",
            "2026-03-15T04:00:00+00:00",
        ),
        )


def _assert_envelope(data: dict, *, ok: bool, intent: str, mode: str) -> dict:
    assert data["ok"] is ok
    assert data["route"]["intent"] == intent
    assert data["route"]["mode"] == mode
    assert data["trace_id"]
    assert data["run_id"]
    return data["result"]


def _insert_source_guide_seed(
    connection,
    notebook_id: str,
    source_id: str,
    *,
    freshness_state: str = "stale",
    content_preview: str | None = "Old preview",
) -> None:
    connection.execute(
        """
        INSERT INTO sources (
            source_id,
            notebook_id,
            profile_id,
            source_type,
            title,
            origin_uri,
            status,
            freshness_state,
            content_preview,
            synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            notebook_id,
            "default",
            "web_page",
            "Source One",
            "https://example.com",
            "ready",
            freshness_state,
            content_preview,
            "2026-03-15T04:00:00+00:00",
        ),
    )


def _notebook_record(
    notebook_id: str = "nb_123",
    title: str = "Test Notebook",
    *,
    source_count: int = 0,
    index_synced_at: str = "2026-03-15T03:00:00+00:00",
    detail_synced_at: str = "2026-03-15T04:00:00+00:00",
) -> NotebookRecord:
    return NotebookRecord(
        notebook_id=notebook_id,
        profile_id="default",
        title=title,
        normalized_title=title.casefold(),
        source_count=source_count,
        index_synced_at=index_synced_at,
        detail_synced_at=detail_synced_at,
    )


def _source_record(
    source_id: str,
    title: str,
    *,
    notebook_id: str = "nb_123",
    source_type: str = "web_page",
    status: str = "ready",
    freshness_state: str | None = None,
    origin_uri: str | None = None,
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        notebook_id=notebook_id,
        profile_id="default",
        source_type=source_type,
        status=status,
        title=title,
        origin_uri=origin_uri,
        freshness_state=freshness_state,
        synced_at="2026-03-15T04:00:00+00:00",
    )


class TestSourceList:
    def test_source_list_reads_local_detail_cache_and_filters(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.source.connect_db") as mock_connect_db,
                patch("notebooklm.cli.source.sync_notebook_index", new_callable=AsyncMock) as mock_sync_index,
                patch("notebooklm.cli.source.sync_notebook_detail", new_callable=AsyncMock) as mock_sync_detail,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value.__enter__.return_value = MagicMock()
                mock_connect_db.return_value.__exit__.return_value = None
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[_notebook_record()],
                    used_cache=True,
                    synced_at="2026-03-15T03:00:00+00:00",
                )
                mock_sync_detail.return_value = NotebookDetailState(
                    notebook=_notebook_record(source_count=2),
                    sources=[
                        _source_record(
                            "src_1",
                            "Source One",
                            source_type="web_page",
                            status="ready",
                            freshness_state="fresh",
                        ),
                        _source_record(
                            "src_2",
                            "Source Two",
                            source_type="pdf",
                            status="error",
                            freshness_state="stale",
                        ),
                    ],
                    artifacts=[],
                    used_cache=True,
                    synced_at="2026-03-15T04:00:00+00:00",
                )
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["source", "list", "-n", "Test Notebook", "--status", "ready"],
                )

        assert result.exit_code == 0
        assert "Source One" in result.output
        assert "Source Two" not in result.output
        assert "local_cache" in result.output
        mock_client.sources.list.assert_not_called()
        assert mock_sync_index.await_args.kwargs["force_refresh"] is False
        assert mock_sync_detail.await_args.kwargs["force_refresh"] is False

    def test_source_list_json_output_includes_filters_and_provenance(self, runner, mock_auth):
        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.source.connect_db") as mock_connect_db,
                patch("notebooklm.cli.source.sync_notebook_index", new_callable=AsyncMock) as mock_sync_index,
                patch("notebooklm.cli.source.sync_notebook_detail", new_callable=AsyncMock) as mock_sync_detail,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value.__enter__.return_value = MagicMock()
                mock_connect_db.return_value.__exit__.return_value = None
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[_notebook_record()],
                    used_cache=False,
                    synced_at="2026-03-15T03:30:00+00:00",
                    sync_run_id="sr_index",
                )
                mock_sync_detail.return_value = NotebookDetailState(
                    notebook=_notebook_record(source_count=2, index_synced_at="2026-03-15T03:30:00+00:00"),
                    sources=[
                        _source_record(
                            "src_1",
                            "Source One",
                            source_type="web_page",
                            status="ready",
                            origin_uri="https://example.com/one",
                        ),
                        _source_record(
                            "src_2",
                            "Source Two",
                            source_type="pdf",
                            status="processing",
                            freshness_state="stale",
                            origin_uri="https://example.com/two",
                        ),
                    ],
                    artifacts=[],
                    used_cache=False,
                    synced_at="2026-03-15T04:00:00+00:00",
                    sync_run_id="sr_detail",
                )
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["source", "list", "-n", "nb_123", "--type", "pdf", "--refresh", "--json"],
                )

        assert result.exit_code == 0
        data = json.loads(result.output)
        payload = _assert_envelope(
            data,
            ok=True,
            intent="LOCAL_METADATA",
            mode="source_list",
        )
        assert data["route"]["source_of_truth"] == "mixed"
        assert data["route"]["cache_mode"] == "refresh"
        assert data["freshness"]["used_cached_result"] is False
        assert payload["notebook"]["id"] == "nb_123"
        assert payload["filters"]["type"] == "pdf"
        assert payload["freshness"]["used_cache"] is False
        assert payload["provenance"]["detail_source"] == "remote_sync"
        assert payload["count"] == 1
        assert payload["total_count"] == 2
        assert payload["sources"][0]["id"] == "src_2"
        assert mock_sync_index.await_args.kwargs["force_refresh"] is True
        assert mock_sync_detail.await_args.kwargs["force_refresh"] is True

    def test_source_list_uses_current_context_without_index_lookup(
        self,
        runner,
        mock_auth,
        mock_context_file,
    ):
        mock_context_file.write_text(json.dumps({"notebook_id": "nb_ctx"}), encoding="utf-8")

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.source.connect_db") as mock_connect_db,
                patch("notebooklm.cli.source.sync_notebook_index", new_callable=AsyncMock) as mock_sync_index,
                patch("notebooklm.cli.source.sync_notebook_detail", new_callable=AsyncMock) as mock_sync_detail,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value.__enter__.return_value = MagicMock()
                mock_connect_db.return_value.__exit__.return_value = None
                mock_sync_detail.return_value = NotebookDetailState(
                    notebook=_notebook_record(notebook_id="nb_ctx", title="Context Notebook", source_count=1),
                    sources=[_source_record("src_ctx", "Context Source", notebook_id="nb_ctx")],
                    artifacts=[],
                    used_cache=True,
                    synced_at="2026-03-15T04:00:00+00:00",
                )
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["source", "list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        payload = _assert_envelope(
            data,
            ok=True,
            intent="LOCAL_METADATA",
            mode="source_list",
        )
        assert data["route"]["source_of_truth"] == "local_cache"
        assert payload["notebook"]["id"] == "nb_ctx"
        assert payload["provenance"]["resolution_source"] == "current_context"
        mock_sync_index.assert_not_awaited()


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
        payload = _assert_envelope(
            data,
            ok=True,
            intent="LOCAL_MUTATION",
            mode="source_add",
        )
        assert data["route"]["source_of_truth"] == "remote_http"
        assert data["cache_updates"]["tables_touched"] == ["notebooks", "sync_runs"]
        assert payload["source"]["id"] == "src_new"

    def test_source_add_invalidates_notebook_detail_cache(
        self, runner, mock_auth, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_detail_sync_seed(connection, "nb_123")

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
        with connect_db() as connection:
            notebook = connection.execute(
                "SELECT detail_synced_at, remote_fingerprint FROM notebooks WHERE notebook_id = ?",
                ("nb_123",),
            ).fetchone()
            sync_run = connection.execute(
                "SELECT status, error_text FROM sync_runs WHERE id = ?",
                ("sr_detail",),
            ).fetchone()

        assert notebook["detail_synced_at"] is None
        assert notebook["remote_fingerprint"] is None
        assert sync_run["status"] == "cancelled"
        assert sync_run["error_text"] == "source.add"


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
    @pytest.mark.parametrize("command", ["list", "guide", "add", "add-research", "delete", "wait"])
    def test_kept_source_commands_exist(self, runner, command):
        result = runner.invoke(cli, ["source", command, "--help"])
        assert result.exit_code == 0

    @pytest.mark.parametrize(
        "command",
        ["get", "rename", "refresh", "add-drive", "fulltext", "stale"],
    )
    def test_removed_source_commands_are_unavailable(self, runner, command):
        result = runner.invoke(cli, ["source", command, "--help"])
        assert result.exit_code == 2
        assert "No such command" in result.output


class TestSourceGuide:
    def test_source_guide_json_output_updates_cached_preview_and_provenance(
        self,
        runner,
        mock_auth,
        mock_fetch_tokens,
        monkeypatch,
        tmp_path,
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_detail_sync_seed(connection, "nb_123")
            _insert_source_guide_seed(connection, "nb_123", "src_1")

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[
                    Source(
                        id="src_1",
                        title="Source One",
                        url="https://example.com",
                        _type_code=5,
                        status=2,
                    )
                ]
            )
            mock_client.sources.get_guide = AsyncMock(
                return_value={
                    "summary": "Guide summary",
                    "keywords": ["alpha", "beta"],
                }
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.source.sync_notebook_index", new_callable=AsyncMock) as mock_sync:
                mock_sync.return_value = NotebookIndexState(
                    notebooks=[_notebook_record(notebook_id="nb_123", title="Test Notebook")],
                    used_cache=True,
                    synced_at="2026-03-15T03:00:00+00:00",
                    sync_run_id="sr_index",
                )
                result = runner.invoke(cli, ["source", "guide", "src_1", "-n", "Test Notebook", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_envelope(
            payload,
            ok=True,
            intent="REMOTE_METADATA",
            mode="source_guide",
        )
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["cache_updates"]["tables_touched"] == ["sources"]
        assert result_payload["source"]["id"] == "src_1"
        assert result_payload["source"]["title"] == "Source One"
        assert result_payload["guide"] == {
            "summary": "Guide summary",
            "keywords": ["alpha", "beta"],
        }
        assert result_payload["freshness"]["source_metadata_synced_at"] == "2026-03-15T04:00:00+00:00"
        assert result_payload["freshness"]["source_metadata_freshness_state"] == "stale"
        assert result_payload["provenance"]["guide_source"] == "remote"
        assert result_payload["provenance"]["resolution_source"] == "local_cache"
        assert result_payload["provenance"]["content_preview_cached"] is True
        assert result_payload["provenance"]["cache_updated"] is True
        assert result_payload["freshness"]["guide_fetched_at"]
        assert mock_client.sources.get_guide.await_count == 1

        with connect_db() as connection:
            row = connection.execute(
                "SELECT content_preview FROM sources WHERE source_id = ?",
                ("src_1",),
            ).fetchone()

        assert row["content_preview"] == "Guide summary"

    def test_source_guide_uses_current_context_without_index_lookup(
        self,
        runner,
        mock_auth,
        mock_fetch_tokens,
        mock_context_file,
    ):
        mock_context_file.write_text(json.dumps({"notebook_id": "nb_ctx"}), encoding="utf-8")

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.list = AsyncMock(
                return_value=[
                    Source(
                        id="src_ctx",
                        title="Context Source",
                        url=None,
                        _type_code=3,
                        status=1,
                    )
                ]
            )
            mock_client.sources.get_guide = AsyncMock(
                return_value={
                    "summary": "",
                    "keywords": [],
                }
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.source.sync_notebook_index", new_callable=AsyncMock) as mock_sync:
                result = runner.invoke(cli, ["source", "guide", "src_ctx", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_envelope(
            payload,
            ok=True,
            intent="REMOTE_METADATA",
            mode="source_guide",
        )
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["cache_updates"]["tables_touched"] == []
        assert result_payload["source"]["id"] == "src_ctx"
        assert result_payload["source"]["notebook_id"] == "nb_ctx"
        assert result_payload["guide"] == {"summary": "", "keywords": []}
        assert result_payload["freshness"]["source_metadata_freshness_state"] == "unknown"
        assert result_payload["provenance"]["resolution_source"] == "current_context"
        assert result_payload["provenance"]["content_preview_cached"] is False
        assert result_payload["provenance"]["cache_updated"] is False
        mock_sync.assert_not_awaited()


class TestSourceDelete:
    def test_source_delete_dry_run_previews_target(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_detail_sync_seed(connection, "nb_123")
            _insert_source_delete_seed(connection, "nb_123", "src_1")

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            result = runner.invoke(
                cli,
                ["source", "delete", "src_1", "-n", "nb_123", "--dry-run", "--json"],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_envelope(
            payload,
            ok=True,
            intent="LOCAL_MUTATION",
            mode="source_delete",
        )
        assert payload["route"]["source_of_truth"] == "remote_http"
        assert payload["cache_updates"]["tables_touched"] == []
        assert result_payload["dry_run"] is True
        assert result_payload["deleted"] is False
        assert result_payload["source"]["id"] == "src_1"
        callback = cli.commands["source"].commands["delete"].callback
        assert getattr(callback, "__risk_tier__") is RiskTier.T3_DESTRUCTIVE
        assert getattr(callback, "__approval_gated__") is True
        assert getattr(callback, "__destructive__") is True
        mock_client.sources.delete.assert_not_awaited()

    def test_source_delete_requires_approval_in_json_mode(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_detail_sync_seed(connection, "nb_123")
            _insert_source_delete_seed(connection, "nb_123", "src_1")

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            result = runner.invoke(cli, ["source", "delete", "src_1", "-n", "nb_123", "--json"])

        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["route"]["mode"] == "source_delete"
        assert payload["route"]["notebook_id"] == "nb_123"
        assert payload["route"]["profile_id"] == "default"
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["result"]["code"] == "APPROVAL_REQUIRED"
        assert payload["result"]["next_step_kind"] == "approval_token"
        assert payload["result"]["approval_request_created"] is True
        assert payload["result"]["approval_token"].startswith("appr_")
        assert payload["result"]["resume_token"].startswith("resume_")
        assert payload["result"]["entity_type"] == "source_delete"
        mock_client.sources.delete.assert_not_awaited()

        with connect_db() as connection:
            approvals = ApprovalRequestRepository(connection).list_for_entity("source_delete", "src_1")

        assert len(approvals) == 1
        assert approvals[0].id == payload["result"]["approval_token"]

    def test_source_delete_uses_notebook_policy_over_profile_auto_policy(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_detail_sync_seed(connection, "nb_123")
            _insert_source_delete_seed(connection, "nb_123", "src_1")
            connection.execute(
                """
                UPDATE profiles
                SET approval_policy_json = ?
                WHERE profile_id = ?
                """,
                ('{"name":"profile-auto","default":"auto"}', "default"),
            )
            connection.execute(
                """
                UPDATE notebooks
                SET approval_policy_json = ?
                WHERE notebook_id = ?
                """,
                ('{"name":"notebook-manual","default":"manual"}', "nb_123"),
            )

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            result = runner.invoke(cli, ["source", "delete", "src_1", "-n", "nb_123", "--json"])

        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["result"]["code"] == "APPROVAL_REQUIRED"
        assert payload["result"]["approval_request"]["policy_name"] == "notebook-manual"
        mock_client.sources.delete.assert_not_awaited()

        with connect_db() as connection:
            approvals = ApprovalRequestRepository(connection).list_for_entity("source_delete", "src_1")

        assert len(approvals) == 1
        assert approvals[0].policy_name == "notebook-manual"

    def test_source_delete_accepts_approval_token_and_tombstones_cache(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_detail_sync_seed(connection, "nb_123")
            _insert_source_delete_seed(connection, "nb_123", "src_1")

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            first = runner.invoke(cli, ["source", "delete", "src_1", "-n", "nb_123", "--json"])

        approval_token = json.loads(first.output)["result"]["approval_token"]

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            result = runner.invoke(
                cli,
                [
                    "source",
                    "delete",
                    "src_1",
                    "-n",
                    "nb_123",
                    "--approval-token",
                    approval_token,
                    "--json",
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_envelope(
            payload,
            ok=True,
            intent="LOCAL_MUTATION",
            mode="source_delete",
        )
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["cache_updates"]["tables_touched"] == [
            "sources",
            "notebooks",
            "sync_runs",
            "run_events",
            "approval_requests",
        ]
        assert result_payload["deleted"] is True
        assert result_payload["approval_requests_resolved"] == 1
        mock_client.sources.delete.assert_awaited_once_with("nb_123", "src_1")

        with connect_db() as connection:
            source = connection.execute(
                "SELECT tombstoned_at FROM sources WHERE source_id = ?",
                ("src_1",),
            ).fetchone()
            notebook = connection.execute(
                "SELECT detail_synced_at, remote_fingerprint FROM notebooks WHERE notebook_id = ?",
                ("nb_123",),
            ).fetchone()
            sync_run = connection.execute(
                "SELECT status, error_text FROM sync_runs WHERE id = ?",
                ("sr_detail",),
            ).fetchone()
            approval = ApprovalRequestRepository(connection).get(approval_token)
            trace_row = connection.execute(
                "SELECT trace_id FROM run_events ORDER BY ts ASC, event_id ASC LIMIT 1"
            ).fetchone()
            events = list_run_events(connection, trace_row["trace_id"])

        assert source["tombstoned_at"] is not None
        assert notebook["detail_synced_at"] is None
        assert notebook["remote_fingerprint"] is None
        assert sync_run["status"] == "cancelled"
        assert sync_run["error_text"] == "source.delete"
        assert approval is not None
        assert approval.status == "approved"
        assert [event.kind for event in events] == ["source.deleted"]
        assert events[0].run_id is None
        assert events[0].payload == {
            "approval_requests_resolved": 1,
            "notebook_id": "nb_123",
            "source_id": "src_1",
            "title": "Source One",
        }

    def test_source_delete_allows_yes_without_creating_approval_request(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_detail_sync_seed(connection, "nb_123")
            _insert_source_delete_seed(connection, "nb_123", "src_1")

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.sources.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            result = runner.invoke(
                cli,
                ["source", "delete", "src_1", "-n", "nb_123", "--yes", "--json"],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_envelope(
            payload,
            ok=True,
            intent="LOCAL_MUTATION",
            mode="source_delete",
        )
        assert payload["cache_updates"]["tables_touched"] == [
            "sources",
            "notebooks",
            "sync_runs",
            "run_events",
        ]
        assert result_payload["deleted"] is True
        assert result_payload["approval_requests_resolved"] == 0
        mock_client.sources.delete.assert_awaited_once_with("nb_123", "src_1")

        with connect_db() as connection:
            approvals = ApprovalRequestRepository(connection).list_for_entity("source_delete", "src_1")

        assert approvals == []


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
        payload = _assert_envelope(
            data,
            ok=True,
            intent="REMOTE_METADATA",
            mode="source_wait",
        )
        assert payload["source_id"] == "src_123"
        assert payload["status"] == "ready"

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
        payload = _assert_envelope(
            data,
            ok=False,
            intent="REMOTE_METADATA",
            mode="source_wait",
        )
        assert payload["status"] == "not_found"
        assert payload["source_id"] == "src_123"

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
        payload = _assert_envelope(
            data,
            ok=False,
            intent="REMOTE_METADATA",
            mode="source_wait",
        )
        assert payload["status"] == "error"
        assert payload["source_id"] == "src_123"
        assert payload["status_code"] == 3

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
        payload = _assert_envelope(
            data,
            ok=False,
            intent="REMOTE_METADATA",
            mode="source_wait",
        )
        assert payload["status"] == "timeout"
        assert payload["source_id"] == "src_123"
        assert payload["timeout_seconds"] == 30
        assert payload["last_status_code"] == 1
