"""Tests for notebook CLI commands (now top-level commands)."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import (
    ApprovalRequestRepository,
    ArtifactRecord,
    NotebookRecord,
    SourceRecord,
)
from notebooklm.notebooklm_cli import cli
from notebooklm.sync import NotebookDetailState, NotebookIndexState
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


def _prepare_local_cache_home(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)
    (home / "storage_state.json").write_text("{}", encoding="utf-8")
    (home / "browser_profile").mkdir(exist_ok=True)
    connection = connect_db()
    connection.close()


def _insert_sync_run(
    connection,
    *,
    run_id: str,
    scope: str,
    status: str = "completed",
    target_id: str | None = None,
) -> None:
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
            run_id,
            f"trc_{run_id}",
            "default",
            scope,
            target_id,
            "manual",
            "2026-03-15T04:00:00+00:00",
            "2026-03-15T04:00:01+00:00",
            status,
        ),
    )


def _insert_notebook_delete_seed(connection, notebook_id: str, title: str) -> None:
    connection.execute(
        """
        INSERT INTO notebooks (
            notebook_id,
            profile_id,
            title,
            normalized_title,
            index_synced_at,
            detail_synced_at,
            remote_fingerprint
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            notebook_id,
            "default",
            title,
            title.lower(),
            "2026-03-15T04:00:00+00:00",
            "2026-03-15T04:00:00+00:00",
            "fp_before",
        ),
    )
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
            "src_1",
            notebook_id,
            "default",
            "web_page",
            "Source One",
            "ready",
            "2026-03-15T04:00:00+00:00",
        ),
    )
    connection.execute(
        """
        UPDATE app_state
        SET current_notebook_id = ?, current_conversation_id = ?
        WHERE singleton_key = 1
        """,
        (notebook_id, "conv_123"),
    )


def _make_notebook_record(
    *,
    notebook_id: str = "nb_pricing",
    title: str = "Pricing",
    source_count: int = 1,
    artifact_count: int = 1,
    is_owner: bool = True,
    index_synced_at: str = "2026-03-15T03:00:00+00:00",
    detail_synced_at: str = "2026-03-15T03:00:30+00:00",
    remote_fingerprint: str = "fp_pricing",
) -> NotebookRecord:
    return NotebookRecord(
        notebook_id=notebook_id,
        profile_id="default",
        title=title,
        normalized_title=title.lower(),
        is_owner=is_owner,
        created_at_remote="2024-01-01T00:00:00",
        source_count=source_count,
        artifact_count=artifact_count,
        index_synced_at=index_synced_at,
        detail_synced_at=detail_synced_at,
        remote_fingerprint=remote_fingerprint,
    )


def _make_notebook_detail_state(
    notebook: NotebookRecord,
    *,
    used_cache: bool,
    sync_run_id: str = "sr_detail",
) -> NotebookDetailState:
    return NotebookDetailState(
        notebook=notebook,
        sources=[
            SourceRecord(
                source_id="src_1",
                notebook_id=notebook.notebook_id,
                profile_id="default",
                source_type="web_page",
                status="ready",
                title="Source One",
                origin_uri="https://example.com/source-one",
                freshness_state="fresh",
                synced_at="2026-03-15T03:00:20+00:00",
            )
        ],
        artifacts=[
            ArtifactRecord(
                artifact_id="art_1",
                notebook_id=notebook.notebook_id,
                profile_id="default",
                artifact_type="briefing-doc",
                status="completed",
                requested_at="2026-03-15T03:00:15+00:00",
                title="Briefing Doc",
            )
        ],
        used_cache=used_cache,
        synced_at=notebook.detail_synced_at,
        sync_run_id=sync_run_id,
    )


def _assert_envelope(data: dict, *, ok: bool, intent: str, mode: str) -> dict:
    assert data["ok"] is ok
    assert data["trace_id"].startswith("trc_")
    assert data["run_id"].startswith("run_")
    assert data["route"]["intent"] == intent
    assert data["route"]["mode"] == mode
    assert "diagnostics" in data
    return data["result"]


# =============================================================================
# NOTEBOOK LIST TESTS
# =============================================================================


class TestNotebookList:
    def test_notebook_list_empty(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.notebook.connect_db") as mock_connect_db,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_index",
                    new_callable=AsyncMock,
                ) as mock_sync,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value = MagicMock(close=MagicMock())
                mock_sync.return_value = NotebookIndexState(
                    notebooks=[],
                    used_cache=True,
                    synced_at="2026-03-15T03:00:00+00:00",
                )
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["list"])

            assert result.exit_code == 0
            assert "Deprecated compatibility command." in result.output
            assert "notebooklm notebook list" in result.output
            assert "Notebooks" in result.output

    def test_notebook_list_with_notebooks(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.notebook.connect_db") as mock_connect_db,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_index",
                    new_callable=AsyncMock,
                ) as mock_sync,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value = MagicMock(close=MagicMock())
                mock_sync.return_value = NotebookIndexState(
                    notebooks=[
                        NotebookRecord(
                            notebook_id="nb_1",
                            profile_id="default",
                            title="First Notebook",
                            normalized_title="first notebook",
                            is_owner=True,
                            created_at_remote="2024-01-01T00:00:00",
                            index_synced_at="2026-03-15T03:00:00+00:00",
                        ),
                        NotebookRecord(
                            notebook_id="nb_2",
                            profile_id="default",
                            title="Second Notebook",
                            normalized_title="second notebook",
                            is_owner=False,
                            created_at_remote="2024-01-02T00:00:00",
                            index_synced_at="2026-03-15T03:00:00+00:00",
                        ),
                    ],
                    used_cache=False,
                    synced_at="2026-03-15T03:00:00+00:00",
                    sync_run_id="sr_01",
                )
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["list"])

            assert result.exit_code == 0
            assert "First Notebook" in result.output
            assert "Second Notebook" in result.output

    def test_notebook_list_json_output(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.notebook.connect_db") as mock_connect_db,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_index",
                    new_callable=AsyncMock,
                ) as mock_sync,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value = MagicMock(close=MagicMock())
                mock_sync.return_value = NotebookIndexState(
                    notebooks=[
                        NotebookRecord(
                            notebook_id="nb_1",
                            profile_id="default",
                            title="Test Notebook",
                            normalized_title="test notebook",
                            is_owner=True,
                            created_at_remote="2024-01-01T00:00:00",
                            index_synced_at="2026-03-15T03:00:00+00:00",
                        ),
                    ],
                    used_cache=True,
                    synced_at="2026-03-15T03:00:00+00:00",
                )
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["list", "--json"])

        assert result.exit_code == 0
        assert "Deprecated compatibility command." not in result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["route"]["intent"] == "LOCAL_METADATA"
        assert data["route"]["mode"] == "notebook_list"
        assert data["route"]["source_of_truth"] == "local_cache"
        assert data["route"]["cache_mode"] == "smart"
        assert data["route"]["transport"]["kind"] == "local"
        assert data["freshness"]["used_cached_result"] is True
        assert data["result"]["count"] == 1
        assert data["result"]["notebooks"][0]["id"] == "nb_1"

    def test_grouped_notebook_list_alias(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.notebook.connect_db") as mock_connect_db,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_index",
                    new_callable=AsyncMock,
                ) as mock_sync,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value = MagicMock(close=MagicMock())
                mock_sync.return_value = NotebookIndexState(
                    notebooks=[
                        NotebookRecord(
                            notebook_id="nb_1",
                            profile_id="default",
                            title="Grouped Notebook",
                            normalized_title="grouped notebook",
                            is_owner=True,
                            created_at_remote="2024-01-01T00:00:00",
                            index_synced_at="2026-03-15T03:00:00+00:00",
                        ),
                    ],
                    used_cache=True,
                    synced_at="2026-03-15T03:00:00+00:00",
                )
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["notebook", "list"])

            assert result.exit_code == 0
            assert "Deprecated compatibility command." not in result.output
            assert "Grouped Notebook" in result.output

    def test_grouped_notebook_list_refresh_forces_sync(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.notebook.connect_db") as mock_connect_db,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_index",
                    new_callable=AsyncMock,
                ) as mock_sync,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                mock_connect_db.return_value = MagicMock(close=MagicMock())
                mock_sync.return_value = NotebookIndexState(
                    notebooks=[],
                    used_cache=False,
                    synced_at="2026-03-15T03:00:00+00:00",
                )
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["notebook", "list", "--refresh"])

            assert result.exit_code == 0
            assert mock_sync.await_args.kwargs["force_refresh"] is True


class TestNotebookGroupUse:
    def test_notebook_use_accepts_exact_title(self, runner, mock_auth, mock_context_file):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.list = AsyncMock(
                return_value=[
                    Notebook(
                        id="nb_123",
                        title="Test Notebook",
                        created_at=datetime(2024, 1, 15),
                        is_owner=False,
                    )
                ]
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = (
                    "csrf",
                    "session",
                    "boq_labs-tailwind-frontend_20260315.01_p0",
                )
                result = runner.invoke(cli, ["notebook", "use", "Test Notebook"])

        assert result.exit_code == 0
        assert "nb_123" in result.output
        assert "Shared" in result.output

        context = json.loads(mock_context_file.read_text(encoding="utf-8"))
        assert context["notebook_id"] == "nb_123"
        assert context["title"] == "Test Notebook"
        assert context["is_owner"] is False

    def test_notebook_use_json_output_uses_canonical_envelope(
        self, runner, mock_auth, mock_context_file
    ):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.list = AsyncMock(
                return_value=[
                    Notebook(
                        id="nb_123",
                        title="Test Notebook",
                        created_at=datetime(2024, 1, 15),
                        is_owner=False,
                    )
                ]
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["notebook", "use", "Test Notebook", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["intent"] == "LOCAL_METADATA"
        assert payload["route"]["mode"] == "notebook_use"
        assert payload["route"]["notebook_id"] == "nb_123"
        assert payload["route"]["source_of_truth"] == "remote_http"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["route"]["transport"]["kind"] == "httpx"
        assert payload["freshness"]["used_cached_result"] is False
        assert payload["result"]["notebook"]["id"] == "nb_123"
        assert payload["result"]["notebook"]["created_at"] == "2024-01-15T00:00:00"
        assert payload["result"]["provenance"]["resolution_source"] == "remote_lookup"

        context = json.loads(mock_context_file.read_text(encoding="utf-8"))
        assert context["notebook_id"] == "nb_123"
        assert context["title"] == "Test Notebook"


class TestNotebookGroupShow:
    def test_notebook_show_prefers_cached_title_resolution(self, runner, mock_auth):
        cached_notebook = _make_notebook_record()

        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.notebook.connect_db") as mock_connect_db,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_index",
                    new_callable=AsyncMock,
                ) as mock_sync_index,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_detail",
                    new_callable=AsyncMock,
                ) as mock_sync_detail,
                patch(
                    "notebooklm.cli.notebook._resolve_notebook_selector",
                    new_callable=AsyncMock,
                ) as mock_resolve_selector,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                connection = MagicMock()
                mock_connect_db.return_value.__enter__.return_value = connection
                mock_connect_db.return_value.__exit__.return_value = False
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[cached_notebook],
                    used_cache=True,
                    synced_at="2026-03-15T03:00:00+00:00",
                    sync_run_id="sr_index",
                )
                mock_sync_detail.return_value = _make_notebook_detail_state(
                    cached_notebook,
                    used_cache=True,
                )
                mock_fetch.return_value = ("csrf", "session")

                result = runner.invoke(cli, ["notebook", "show", "Pricing"])

        assert result.exit_code == 0, result.output
        assert "Notebook Detail" in result.output
        assert "Pricing" in result.output
        assert "local_cache" in result.output
        assert mock_sync_detail.await_args.args[2] == "nb_pricing"
        mock_resolve_selector.assert_not_awaited()

    def test_notebook_show_json_reports_freshness_and_provenance(self, runner, mock_auth):
        cached_notebook = _make_notebook_record()
        detail_notebook = _make_notebook_record(
            source_count=2,
            artifact_count=1,
            detail_synced_at="2026-03-15T03:01:00+00:00",
            remote_fingerprint="fp_after_sync",
        )

        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.notebook.connect_db") as mock_connect_db,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_index",
                    new_callable=AsyncMock,
                ) as mock_sync_index,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_detail",
                    new_callable=AsyncMock,
                ) as mock_sync_detail,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                connection = MagicMock()
                mock_connect_db.return_value.__enter__.return_value = connection
                mock_connect_db.return_value.__exit__.return_value = False
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[cached_notebook],
                    used_cache=True,
                    synced_at="2026-03-15T03:00:00+00:00",
                    sync_run_id="sr_index",
                )
                mock_sync_detail.return_value = _make_notebook_detail_state(
                    detail_notebook,
                    used_cache=False,
                )
                mock_fetch.return_value = ("csrf", "session")

                result = runner.invoke(cli, ["notebook", "show", "Pricing", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["intent"] == "LOCAL_METADATA"
        assert payload["route"]["mode"] == "notebook_show"
        assert payload["route"]["notebook_id"] == "nb_pricing"
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["route"]["cache_mode"] == "smart"
        assert payload["route"]["transport"]["kind"] == "httpx"
        assert payload["freshness"]["used_cached_result"] is False
        assert payload["result"]["notebook"]["id"] == "nb_pricing"
        assert payload["result"]["notebook"]["remote_fingerprint"] == "fp_after_sync"
        assert payload["result"]["freshness"]["used_cache"] is False
        assert payload["result"]["freshness"]["detail_synced_at"] == "2026-03-15T03:01:00+00:00"
        assert payload["result"]["provenance"]["resolution_source"] == "local_cache"
        assert payload["result"]["provenance"]["detail_source"] == "remote_sync"
        assert payload["result"]["provenance"]["sync_run_id"] == "sr_detail"
        assert payload["result"]["sources"][0]["freshness_state"] == "fresh"
        assert payload["result"]["artifacts"][0]["artifact_type"] == "briefing-doc"

    def test_notebook_show_rejects_ambiguous_cached_matches(self, runner, mock_auth):
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.notebook.connect_db") as mock_connect_db,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_index",
                    new_callable=AsyncMock,
                ) as mock_sync_index,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_detail",
                    new_callable=AsyncMock,
                ) as mock_sync_detail,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                connection = MagicMock()
                mock_connect_db.return_value.__enter__.return_value = connection
                mock_connect_db.return_value.__exit__.return_value = False
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[
                        _make_notebook_record(notebook_id="nb_1", title="Pricing"),
                        _make_notebook_record(notebook_id="nb_2", title="Pricing Review"),
                    ],
                    used_cache=True,
                    synced_at="2026-03-15T03:00:00+00:00",
                )
                mock_fetch.return_value = ("csrf", "session")

                result = runner.invoke(cli, ["notebook", "show", "pri"])

        assert result.exit_code == 1, result.output
        assert "Ambiguous notebook 'pri' matches 2 cached notebooks" in result.output
        mock_sync_detail.assert_not_awaited()

    def test_notebook_show_refresh_forces_detail_sync(self, runner, mock_auth):
        cached_notebook = _make_notebook_record()

        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with (
                patch("notebooklm.cli.notebook.connect_db") as mock_connect_db,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_index",
                    new_callable=AsyncMock,
                ) as mock_sync_index,
                patch(
                    "notebooklm.cli.notebook.sync_notebook_detail",
                    new_callable=AsyncMock,
                ) as mock_sync_detail,
                patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
            ):
                connection = MagicMock()
                mock_connect_db.return_value.__enter__.return_value = connection
                mock_connect_db.return_value.__exit__.return_value = False
                mock_sync_index.return_value = NotebookIndexState(
                    notebooks=[cached_notebook],
                    used_cache=True,
                    synced_at="2026-03-15T03:00:00+00:00",
                )
                mock_sync_detail.return_value = _make_notebook_detail_state(
                    cached_notebook,
                    used_cache=False,
                )
                mock_fetch.return_value = ("csrf", "session")

                result = runner.invoke(cli, ["notebook", "show", "nb_pricing", "--refresh", "--json"])

        assert result.exit_code == 0, result.output
        assert mock_sync_detail.await_args.kwargs["force_refresh"] is True


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
        payload = json.loads(result.output)
        result_payload = _assert_envelope(
            payload,
            ok=True,
            intent="LOCAL_MUTATION",
            mode="notebook_create",
        )
        assert payload["route"]["source_of_truth"] == "remote_http"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["route"]["transport"]["kind"] == "httpx"
        assert payload["freshness"]["used_cached_result"] is False
        assert payload["cache_updates"]["tables_touched"] == ["notebooks", "sync_runs"]
        assert result_payload["notebook"]["id"] == "new_nb_id"
        assert result_payload["notebook"]["created_at"] == "2024-01-01T00:00:00"

    def test_notebook_create_invalidates_notebook_index_cache(
        self, runner, mock_auth, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            connection.execute(
                """
                INSERT INTO notebooks (
                    notebook_id,
                    profile_id,
                    title,
                    normalized_title,
                    index_synced_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "nb_existing",
                    "default",
                    "Existing Notebook",
                    "existing notebook",
                    "2026-03-15T04:00:00+00:00",
                ),
            )
            _insert_sync_run(connection, run_id="sr_index", scope="notebook_index")

        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.create = AsyncMock(
                return_value=Notebook(
                    id="new_nb_id",
                    title="Test Notebook",
                    created_at=datetime(2024, 1, 1),
                )
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["create", "Test Notebook"])

        assert result.exit_code == 0
        with connect_db() as connection:
            notebook = connection.execute(
                "SELECT index_synced_at FROM notebooks WHERE notebook_id = ?",
                ("nb_existing",),
            ).fetchone()
            sync_run = connection.execute(
                "SELECT status, error_text FROM sync_runs WHERE id = ?",
                ("sr_index",),
            ).fetchone()

        assert notebook["index_synced_at"] is None
        assert sync_run["status"] == "cancelled"
        assert sync_run["error_text"] == "notebook.create"


class TestNotebookDelete:
    def test_notebook_delete_dry_run_accepts_exact_title(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_notebook_delete_seed(connection, "nb_123", "Test Notebook")

        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            result = runner.invoke(cli, ["delete", "Test Notebook", "--dry-run", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_envelope(
            payload,
            ok=True,
            intent="LOCAL_MUTATION",
            mode="notebook_delete",
        )
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["cache_updates"]["tables_touched"] == []
        assert result_payload["dry_run"] is True
        assert result_payload["deleted"] is False
        assert result_payload["notebook"]["id"] == "nb_123"
        assert result_payload["notebook"]["title"] == "Test Notebook"
        assert result_payload["notebook"]["cached_source_count"] == 1
        mock_client.notebooks.delete.assert_not_awaited()

    def test_notebook_delete_requires_approval_in_json_mode(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_notebook_delete_seed(connection, "nb_123", "Test Notebook")

        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            result = runner.invoke(cli, ["delete", "nb_123", "--json"])

        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["route"]["mode"] == "notebook_delete"
        assert payload["route"]["notebook_id"] == "nb_123"
        assert payload["route"]["profile_id"] == "default"
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["result"]["code"] == "APPROVAL_REQUIRED"
        assert payload["result"]["next_step_kind"] == "approval_token"
        assert payload["result"]["approval_token"].startswith("appr_")
        assert payload["result"]["entity_type"] == "notebook_delete"
        mock_client.notebooks.delete.assert_not_awaited()

    def test_notebook_delete_allows_profile_auto_policy_without_approval_token(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_notebook_delete_seed(connection, "nb_123", "Test Notebook")
            connection.execute(
                """
                UPDATE profiles
                SET approval_policy_json = ?
                WHERE profile_id = ?
                """,
                ('{"name":"profile-auto","default":"auto"}', "default"),
            )

        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            result = runner.invoke(cli, ["delete", "nb_123", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_envelope(
            payload,
            ok=True,
            intent="LOCAL_MUTATION",
            mode="notebook_delete",
        )
        assert result_payload["deleted"] is True
        assert result_payload["approval_requests_resolved"] == 0
        assert "approval_requests" not in payload["cache_updates"]["tables_touched"]
        mock_client.notebooks.delete.assert_awaited_once_with("nb_123")

        with connect_db() as connection:
            approvals = ApprovalRequestRepository(connection).list_for_entity("notebook_delete", "nb_123")

        assert approvals == []

    def test_notebook_delete_accepts_approval_token_and_tombstones_cache(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_notebook_delete_seed(connection, "nb_123", "Test Notebook")
            _insert_sync_run(connection, run_id="sr_index", scope="notebook_index")
            _insert_sync_run(connection, run_id="sr_detail", scope="notebook_detail", target_id="nb_123")

        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            first = runner.invoke(cli, ["delete", "nb_123", "--json"])

        approval_token = json.loads(first.output)["result"]["approval_token"]

        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.delete = AsyncMock(return_value=True)
            mock_client_cls.return_value = mock_client
            result = runner.invoke(
                cli,
                ["delete", "nb_123", "--approval-token", approval_token, "--json"],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        result_payload = _assert_envelope(
            payload,
            ok=True,
            intent="LOCAL_MUTATION",
            mode="notebook_delete",
        )
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["cache_updates"]["tables_touched"] == [
            "notebooks",
            "sources",
            "sync_runs",
            "run_events",
            "approval_requests",
        ]
        assert result_payload["deleted"] is True
        assert result_payload["approval_requests_resolved"] == 1
        mock_client.notebooks.delete.assert_awaited_once_with("nb_123")

        with connect_db() as connection:
            notebook = connection.execute(
                """
                SELECT tombstoned_at, index_synced_at, detail_synced_at, remote_fingerprint
                FROM notebooks
                WHERE notebook_id = ?
                """,
                ("nb_123",),
            ).fetchone()
            source = connection.execute(
                "SELECT tombstoned_at FROM sources WHERE source_id = ?",
                ("src_1",),
            ).fetchone()
            app_state = connection.execute(
                """
                SELECT current_notebook_id, current_conversation_id
                FROM app_state
                WHERE singleton_key = 1
                """
            ).fetchone()
            index_sync = connection.execute(
                "SELECT status, error_text FROM sync_runs WHERE id = ?",
                ("sr_index",),
            ).fetchone()
            detail_sync = connection.execute(
                "SELECT status, error_text FROM sync_runs WHERE id = ?",
                ("sr_detail",),
            ).fetchone()
            approval = ApprovalRequestRepository(connection).get(approval_token)
            trace_row = connection.execute(
                "SELECT trace_id FROM run_events ORDER BY ts ASC, event_id ASC LIMIT 1"
            ).fetchone()
            events = list_run_events(connection, trace_row["trace_id"])

        assert notebook["tombstoned_at"] is not None
        assert notebook["index_synced_at"] is None
        assert notebook["detail_synced_at"] is None
        assert notebook["remote_fingerprint"] is None
        assert source["tombstoned_at"] is not None
        assert app_state["current_notebook_id"] is None
        assert app_state["current_conversation_id"] is None
        assert index_sync["status"] == "cancelled"
        assert index_sync["error_text"] == "notebook.delete"
        assert detail_sync["status"] == "cancelled"
        assert detail_sync["error_text"] == "notebook.delete"
        assert approval is not None
        assert approval.status == "approved"
        assert [event.kind for event in events] == ["notebook.deleted"]
        assert events[0].run_id is None
        assert events[0].payload == {
            "approval_requests_resolved": 1,
            "cached_source_count": 1,
            "notebook_id": "nb_123",
            "title": "Test Notebook",
        }


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
            assert "Deprecated compatibility command." in result.output
            assert "notebooklm overview" in result.output
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
        assert "Found 1 sources" in result.output
        assert "Imported 1 sources" not in result.output
        mock_client.research.import_sources.assert_not_awaited()

    def test_source_add_research_with_import_invalidates_notebook_detail_cache(
        self, runner, mock_auth, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
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
                    "nb_123",
                    "default",
                    "Notebook",
                    "notebook",
                    "2026-03-15T04:00:00+00:00",
                    "fp_before",
                ),
            )
            _insert_sync_run(
                connection,
                run_id="sr_detail",
                scope="notebook_detail",
                target_id="nb_123",
            )

        with patch_client_for_module("source") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.start = AsyncMock(return_value={"task_id": "task_123"})
            mock_client.research.poll = AsyncMock(
                return_value={"status": "completed", "sources": [{"id": "src_1", "url": "http://x"}]}
            )
            mock_client.research.import_sources = AsyncMock(return_value=[{"id": "src_1"}])
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli, ["source", "add-research", "AI research", "-n", "nb_123", "--import-all"]
                )

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
            approvals = ApprovalRequestRepository(connection).list_pending()
            inbox_items = connection.execute(
                """
                SELECT id, state, canonical_uri
                FROM inbox_items
                ORDER BY id
                """
            ).fetchall()

        assert notebook["detail_synced_at"] == "2026-03-15T04:00:00+00:00"
        assert notebook["remote_fingerprint"] == "fp_before"
        assert sync_run["status"] == "completed"
        assert sync_run["error_text"] is None
        assert approvals == []
        assert len(inbox_items) == 1
        assert inbox_items[0]["state"] == "pending"
        assert inbox_items[0]["canonical_uri"] == "http://x"
        mock_client.research.import_sources.assert_not_awaited()


# =============================================================================
# COMMAND EXISTENCE TESTS
# =============================================================================


class TestNotebookCommandsExist:
    def test_grouped_use_command_supports_json(self, runner):
        result = runner.invoke(cli, ["notebook", "use", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output

    def test_grouped_show_command_exists(self, runner):
        result = runner.invoke(cli, ["notebook", "show", "--help"])
        assert result.exit_code == 0
        assert "Show one notebook" in result.output

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

    def test_delete_command_exists(self, runner):
        result = runner.invoke(cli, ["delete", "--help"])
        assert result.exit_code == 0
        assert "Delete a notebook" in result.output

    def test_ask_command_exists(self, runner):
        result = runner.invoke(cli, ["ask", "--help"])
        assert result.exit_code == 0
        assert "QUESTION" in result.output

    @pytest.mark.parametrize("command", ["configure"])
    def test_removed_chat_commands_are_unavailable(self, runner, command):
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 2
        assert "No such command" in result.output

    def test_history_command_exists(self, runner):
        result = runner.invoke(cli, ["history", "--help"])
        assert result.exit_code == 0
        assert "search" in result.output
        assert "show" in result.output

    def test_top_level_help_shows_notebook_commands(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Verify notebook commands are at top level
        assert "list" in result.output
        assert "create" in result.output
        assert "delete" in result.output
        assert "summary" in result.output
        assert "ask" in result.output
        assert "history" in result.output
        assert "configure" not in result.output
        # Verify there's no "notebook" command in the Commands section
        # (it should only appear as part of "NotebookLM" in the description)
        commands_section = (
            result.output.split("Commands:")[1] if "Commands:" in result.output else ""
        )
        assert "  notebook " not in commands_section.lower()
