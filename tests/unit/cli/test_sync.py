"""Tests for explicit sync CLI commands."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import ArtifactRecord, NotebookRecord, SourceRecord
from notebooklm.notebooklm_cli import cli
from notebooklm.sync import NotebookDetailState, NotebookIndexState

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


def _prepare_local_cache_home(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)
    (home / "storage_state.json").write_text("{}", encoding="utf-8")
    (home / "browser_profile").mkdir(exist_ok=True)
    connection = connect_db()
    connection.close()


def _notebook_record(
    notebook_id: str = "nb_123",
    title: str = "Test Notebook",
    *,
    source_count: int = 1,
    artifact_count: int = 1,
    index_synced_at: str = "2026-03-15T03:00:00+00:00",
    detail_synced_at: str = "2026-03-15T03:05:00+00:00",
) -> NotebookRecord:
    return NotebookRecord(
        notebook_id=notebook_id,
        profile_id="default",
        title=title,
        normalized_title=title.casefold(),
        source_count=source_count,
        artifact_count=artifact_count,
        index_synced_at=index_synced_at,
        detail_synced_at=detail_synced_at,
    )


def _detail_state(
    notebook: NotebookRecord,
    *,
    used_cache: bool = False,
    sync_run_id: str = "sr_detail",
) -> NotebookDetailState:
    return NotebookDetailState(
        notebook=notebook,
        sources=[
            SourceRecord(
                source_id=f"src_{notebook.notebook_id}",
                notebook_id=notebook.notebook_id,
                profile_id="default",
                source_type="web_page",
                status="ready",
                title=f"{notebook.title} Source",
                freshness_state="fresh",
                synced_at=notebook.detail_synced_at,
            )
        ],
        artifacts=[
            ArtifactRecord(
                artifact_id=f"art_{notebook.notebook_id}",
                notebook_id=notebook.notebook_id,
                profile_id="default",
                artifact_type="audio",
                status="completed",
                requested_at=notebook.detail_synced_at,
                title=f"{notebook.title} Audio",
            )
        ],
        used_cache=used_cache,
        synced_at=notebook.detail_synced_at,
        sync_run_id=sync_run_id,
    )


def _assert_sync_envelope(payload: dict, *, notebook_id: str | None) -> dict:
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "REMOTE_METADATA"
    assert payload["route"]["mode"] == "sync_notebooks"
    assert payload["route"]["notebook_id"] == notebook_id
    assert payload["route"]["profile_id"] == "default"
    assert payload["route"]["source_of_truth"] == "mixed"
    assert payload["route"]["cache_mode"] == "refresh"
    assert payload["route"]["transport"]["kind"] == "httpx"
    assert payload["cache_updates"]["tables_touched"] == [
        "artifacts",
        "notebooks",
        "sources",
        "sync_runs",
    ]
    assert payload["diagnostics"]["retries"] == 0
    assert payload["diagnostics"]["auth_refreshed"] is False
    assert isinstance(payload["diagnostics"]["elapsed_ms"], int)
    assert payload["diagnostics"]["elapsed_ms"] >= 0
    return payload["result"]


class TestSyncNotebooks:
    def test_sync_notebooks_all_refreshes_index_and_each_detail(self, runner, mock_auth):
        alpha = _notebook_record(notebook_id="nb_alpha", title="Alpha", source_count=2, artifact_count=1)
        beta = _notebook_record(notebook_id="nb_beta", title="Beta", source_count=1, artifact_count=0)

        with patch_client_for_module("sync") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.sync.connect_db") as mock_connect_db,
                patch("notebooklm.cli.sync.sync_notebook_index", new_callable=AsyncMock) as mock_sync_index,
                patch("notebooklm.cli.sync.sync_notebook_detail", new_callable=AsyncMock) as mock_sync_detail,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value.__enter__.return_value = MagicMock()
                mock_connect_db.return_value.__exit__.return_value = None
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[alpha, beta],
                    used_cache=False,
                    synced_at="2026-03-15T03:00:00+00:00",
                    sync_run_id="sr_index",
                )
                mock_sync_detail.side_effect = [
                    _detail_state(alpha, sync_run_id="sr_alpha"),
                    _detail_state(beta, sync_run_id="sr_beta"),
                ]
                mock_fetch.return_value = ("csrf", "session")

                result = runner.invoke(cli, ["sync", "notebooks", "--all"])

        assert result.exit_code == 0, result.output
        assert "Notebook Sync" in result.output
        assert "Alpha" in result.output
        assert "Beta" in result.output
        assert mock_sync_index.await_args.kwargs["force_refresh"] is True
        assert mock_sync_index.await_args.kwargs["trigger"] == "manual"
        assert [call.args[2] for call in mock_sync_detail.await_args_list] == ["nb_alpha", "nb_beta"]
        assert all(call.kwargs["force_refresh"] is True for call in mock_sync_detail.await_args_list)

    def test_sync_notebooks_json_reports_scoped_stats_and_run_ids(self, runner, mock_auth):
        cached = _notebook_record(notebook_id="nb_alpha", title="Alpha", source_count=2, artifact_count=1)

        with patch_client_for_module("sync") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.sync.connect_db") as mock_connect_db,
                patch("notebooklm.cli.sync.sync_notebook_index", new_callable=AsyncMock) as mock_sync_index,
                patch("notebooklm.cli.sync.sync_notebook_detail", new_callable=AsyncMock) as mock_sync_detail,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value.__enter__.return_value = MagicMock()
                mock_connect_db.return_value.__exit__.return_value = None
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[cached],
                    used_cache=False,
                    synced_at="2026-03-15T03:00:00+00:00",
                    sync_run_id="sr_index",
                )
                mock_sync_detail.return_value = _detail_state(cached, sync_run_id="sr_alpha")
                mock_fetch.return_value = ("csrf", "session")

                result = runner.invoke(cli, ["sync", "notebooks", "--all", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_sync_envelope(payload, notebook_id=None)
        assert result_payload["scope"] == "all"
        assert result_payload["index"]["source"] == "remote_sync"
        assert result_payload["index"]["sync_run_id"] == "sr_index"
        assert result_payload["stats"] == {
            "notebook_count": 1,
            "source_count": 2,
            "artifact_count": 1,
            "remote_sync_count": 1,
            "cache_reuse_count": 0,
        }
        assert result_payload["notebooks"][0]["id"] == "nb_alpha"
        assert result_payload["notebooks"][0]["detail_source"] == "remote_sync"
        assert result_payload["notebooks"][0]["sync_run_id"] == "sr_alpha"

    def test_sync_notebooks_uses_current_context_when_selector_is_omitted(
        self,
        runner,
        mock_auth,
        mock_context_file,
    ):
        mock_context_file.write_text(json.dumps({"notebook_id": "nb_ctx"}), encoding="utf-8")
        cached = _notebook_record(notebook_id="nb_ctx", title="Context Notebook")

        with patch_client_for_module("sync") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.sync.connect_db") as mock_connect_db,
                patch("notebooklm.cli.sync.sync_notebook_index", new_callable=AsyncMock) as mock_sync_index,
                patch("notebooklm.cli.sync.sync_notebook_detail", new_callable=AsyncMock) as mock_sync_detail,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value.__enter__.return_value = MagicMock()
                mock_connect_db.return_value.__exit__.return_value = None
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[cached],
                    used_cache=False,
                    synced_at="2026-03-15T03:00:00+00:00",
                    sync_run_id="sr_index",
                )
                mock_sync_detail.return_value = _detail_state(cached, sync_run_id="sr_ctx")
                mock_fetch.return_value = ("csrf", "session")

                result = runner.invoke(cli, ["sync", "notebooks", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_sync_envelope(payload, notebook_id="nb_ctx")
        assert result_payload["requested_notebook"] is None
        assert result_payload["current_notebook_id"] == "nb_ctx"
        assert result_payload["notebooks"][0]["resolution_source"] == "current_context"
        mock_sync_detail.assert_awaited_once()
        assert mock_sync_detail.await_args.args[2] == "nb_ctx"

    def test_sync_notebooks_prefers_cached_selector_resolution_before_remote_lookup(
        self,
        runner,
        mock_auth,
    ):
        cached = _notebook_record(notebook_id="nb_123", title="Pricing Notebook")

        with patch_client_for_module("sync") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.sync.connect_db") as mock_connect_db,
                patch("notebooklm.cli.sync.sync_notebook_index", new_callable=AsyncMock) as mock_sync_index,
                patch("notebooklm.cli.sync.sync_notebook_detail", new_callable=AsyncMock) as mock_sync_detail,
                patch(
                    "notebooklm.cli.sync._resolve_notebook_selector",
                    new_callable=AsyncMock,
                ) as mock_remote_resolve,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value.__enter__.return_value = MagicMock()
                mock_connect_db.return_value.__exit__.return_value = None
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[cached],
                    used_cache=False,
                    synced_at="2026-03-15T03:00:00+00:00",
                    sync_run_id="sr_index",
                )
                mock_sync_detail.return_value = _detail_state(cached, sync_run_id="sr_cached")
                mock_fetch.return_value = ("csrf", "session")

                result = runner.invoke(
                    cli,
                    ["sync", "notebooks", "--notebook", "Pricing Notebook", "--json"],
                )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_sync_envelope(payload, notebook_id="nb_123")
        assert result_payload["notebooks"][0]["id"] == "nb_123"
        assert result_payload["notebooks"][0]["resolution_source"] == "local_cache"
        mock_remote_resolve.assert_not_awaited()

    def test_sync_notebooks_requires_scope_or_current_context(
        self,
        runner,
        mock_auth,
        mock_context_file,
    ):
        mock_context_file.write_text("{}", encoding="utf-8")

        with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = ("csrf", "session")
            result = runner.invoke(cli, ["sync", "notebooks"])

        assert result.exit_code == 1
        assert "No notebook specified" in result.output

    def test_sync_notebooks_rejects_all_and_notebook_together(self, runner, mock_auth):
        with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = ("csrf", "session")
            result = runner.invoke(cli, ["sync", "notebooks", "--all", "--notebook", "nb_123"])

        assert result.exit_code == 1
        assert "Use either --all or --notebook" in result.output
