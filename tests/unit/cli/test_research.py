"""Tests for research CLI commands."""

import json
from unittest.mock import AsyncMock

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import (
    QueryRunRecord,
    QueryRunRepository,
    WorkspaceMemberRecord,
    WorkspaceMemberRepository,
    WorkspaceRecord,
    WorkspaceRepository,
    WorkspaceRunRecord,
    WorkspaceRunRepository,
)
from notebooklm.notebooklm_cli import cli
from notebooklm.rpc import BATCHEXECUTE_URL, RPCMethod

from .conftest import create_mock_client, patch_client_for_module


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
        ON CONFLICT(notebook_id) DO UPDATE SET
            detail_synced_at = excluded.detail_synced_at,
            remote_fingerprint = excluded.remote_fingerprint
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


def _insert_notebook_seed(connection, notebook_id: str) -> None:
    connection.execute(
        """
        INSERT INTO notebooks (
            notebook_id,
            profile_id,
            title,
            normalized_title
        ) VALUES (?, ?, ?, ?)
        """,
        (
            notebook_id,
            "default",
            "Notebook",
            "notebook",
        ),
    )


def _insert_research_run_seed(connection, research_id: str, notebook_id: str) -> None:
    _insert_notebook_seed(connection, notebook_id)
    connection.execute(
        """
        INSERT INTO research_runs (
            research_id,
            notebook_id,
            profile_id,
            mode,
            query_text,
            status,
            discovered_count,
            imported_count,
            started_at,
            updated_at,
            raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            research_id,
            notebook_id,
            "default",
            "fast",
            "AI research",
            "in_progress",
            0,
            0,
            "2026-03-15T04:00:00+00:00",
            "2026-03-15T04:00:00+00:00",
            json.dumps({"research_id": research_id, "query": "AI research"}),
        ),
    )


def _insert_source_seed(
    connection,
    *,
    notebook_id: str,
    source_id: str,
    origin_uri: str,
    title: str = "Existing Source",
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
            synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            notebook_id,
            "default",
            "web_page",
            title,
            origin_uri,
            "ready",
            "2026-03-15T04:00:00+00:00",
        ),
    )


def _insert_inbox_item_seed(
    connection,
    *,
    item_id: str,
    notebook_id: str,
    title: str,
    canonical_uri: str,
    state: str = "pending",
    priority: int = 3,
    novelty_score: float = 0.6,
    relevance_score: float = 0.7,
    trust_score: float = 0.75,
    rationale: dict | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO inbox_items (
            id,
            profile_id,
            notebook_id,
            workspace_id,
            origin,
            kind,
            state,
            priority,
            novelty_score,
            relevance_score,
            trust_score,
            approval_required,
            title,
            canonical_uri,
            snippet,
            rationale_json,
            created_at,
            decision_at,
            cluster_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            "default",
            notebook_id,
            None,
            "deep_research",
            "source",
            state,
            priority,
            novelty_score,
            relevance_score,
            trust_score,
            1,
            title,
            canonical_uri,
            "Existing staged research candidate.",
            json.dumps(
                rationale
                or {
                    "candidate": {"title": title, "url": canonical_uri},
                    "research_id": "seed_research",
                },
                sort_keys=True,
            ),
            "2026-03-15T04:00:00+00:00",
            None,
            None,
        ),
    )


def _insert_contextual_history_seed(connection, notebook_id: str) -> None:
    WorkspaceRepository(connection).upsert(
        WorkspaceRecord(
            id="ws_research",
            profile_id="default",
            name="Research Context",
            slug="research-context",
            kind="static",
            created_at="2026-03-15T04:05:00+00:00",
            updated_at="2026-03-15T04:05:00+00:00",
        )
    )
    WorkspaceMemberRepository(connection).upsert(
        WorkspaceMemberRecord(
            id="wsm_research_nb",
            workspace_id="ws_research",
            notebook_id=notebook_id,
            priority=8,
            added_at="2026-03-15T04:05:00+00:00",
        )
    )
    WorkspaceRunRepository(connection).upsert(
        WorkspaceRunRecord(
            id="wr_research_1",
            trace_id="trc_wr_research_1",
            profile_id="default",
            started_at="2026-03-15T04:06:00+00:00",
            ended_at="2026-03-15T04:06:03+00:00",
            status="completed",
            workspace_id="ws_research",
            mode="compare",
            query_text="AI research",
            selected_notebooks_json=json.dumps([notebook_id]),
            plan_json='{"mode":"compare"}',
            result_json='{"status":"completed"}',
        )
    )
    QueryRunRepository(connection).upsert(
        QueryRunRecord(
            id="qr_research_1",
            trace_id="trc_qr_research_1",
            profile_id="default",
            notebook_id=notebook_id,
            intent="ask",
            mode="answer",
            prompt_text="AI research",
            prompt_hash="hash_research_1",
            cache_policy="smart",
            route_reason="remote query",
            source_of_truth="remote_http",
            started_at="2026-03-15T04:07:00+00:00",
            ended_at="2026-03-15T04:07:02+00:00",
            status="completed",
        )
    )


# =============================================================================
# RESEARCH START TESTS
# =============================================================================


class TestResearchStart:
    def test_start_persists_research_run_and_event(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.start = AsyncMock(
                return_value={
                    "task_id": "task_123",
                    "query": "AI research",
                    "mode": "deep",
                    "report_id": "report_123",
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(
                cli,
                ["research", "start", "AI research", "-n", "nb_123", "--mode", "deep"],
            )

        assert result.exit_code == 0
        assert "Research started" in result.output
        assert "task_123" in result.output

        with connect_db() as connection:
            row = connection.execute(
                """
                SELECT research_id, notebook_id, mode, query_text, status, discovered_count
                FROM research_runs
                WHERE research_id = ?
                """,
                ("task_123",),
            ).fetchone()
            events = connection.execute(
                "SELECT kind, run_id FROM run_events ORDER BY ts ASC, event_id ASC"
            ).fetchall()

        assert row["research_id"] == "task_123"
        assert row["notebook_id"] == "nb_123"
        assert row["mode"] == "deep"
        assert row["query_text"] == "AI research"
        assert row["status"] == "in_progress"
        assert row["discovered_count"] == 0
        assert any(event["kind"] == "research.started" and event["run_id"] == "task_123" for event in events)

    def test_start_json_output(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.start = AsyncMock(
                return_value={
                    "task_id": "task_123",
                    "query": "AI research",
                    "mode": "fast",
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(
                cli,
                ["research", "start", "AI research", "-n", "nb_123", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["trace_id"].startswith("trc_")
        assert payload["run_id"] == "task_123"
        assert payload["route"]["intent"] == "RESEARCH"
        assert payload["route"]["mode"] == "fast"
        assert payload["route"]["notebook_id"] == "nb_123"
        assert payload["route"]["profile_id"] == "default"
        assert payload["route"]["source_of_truth"] == "remote_http"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["route"]["transport"] == {
            "kind": "httpx",
            "endpoint": BATCHEXECUTE_URL,
            "rpcid": RPCMethod.START_FAST_RESEARCH.value,
        }
        assert payload["result"]["research_id"] == "task_123"
        assert payload["result"]["status"] == "in_progress"
        assert payload["result"]["search_source"] == "web"
        assert payload["cache_updates"]["tables_touched"] == ["research_runs", "run_events"]
        assert payload["diagnostics"]["elapsed_ms"] >= 0

# =============================================================================
# RESEARCH STATUS TESTS
# =============================================================================


class TestResearchStatus:
    def test_status_no_research(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(return_value={"status": "no_research"})
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "status", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "No research running" in result.output

    def test_status_in_progress(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={"status": "in_progress", "query": "AI research"}
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "status", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "Research in progress" in result.output
        assert "AI research" in result.output

    def test_status_completed(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "query": "AI research",
                    "sources": [
                        {"title": "Source 1", "url": "http://example.com/1"},
                        {"title": "Source 2", "url": "http://example.com/2"},
                    ],
                    "summary": "This is a summary of the research results.",
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "status", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "Research completed" in result.output
        assert "Found 2 sources" in result.output
        assert "Source 1" in result.output

    def test_status_completed_with_many_sources(self, runner, mock_auth, mock_fetch_tokens):
        """Test that more than 10 sources shows truncation message."""
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            sources = [
                {"title": f"Source {i}", "url": f"http://example.com/{i}"} for i in range(15)
            ]
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "query": "AI research",
                    "sources": sources,
                    "summary": "",
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "status", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "Found 15 sources" in result.output
        assert "and 5 more" in result.output

    def test_status_unknown(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(return_value={"status": "unknown_status"})
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "status", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "Status: unknown_status" in result.output

    def test_status_json_output(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "task_id": "task_123",
                    "status": "completed",
                    "query": "AI research",
                    "sources": [{"title": "Source 1", "url": "http://example.com"}],
                    "summary": "Summary",
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "status", "-n", "nb_123", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["run_id"] == "task_123"
        assert payload["route"]["intent"] == "RESEARCH"
        assert payload["route"]["mode"] == "research_status"
        assert payload["route"]["notebook_id"] == "nb_123"
        assert payload["route"]["profile_id"] == "default"
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["route"]["transport"] == {
            "kind": "httpx",
            "endpoint": BATCHEXECUTE_URL,
            "rpcid": RPCMethod.POLL_RESEARCH.value,
        }
        assert payload["result"]["status"] == "completed"
        assert len(payload["result"]["sources"]) == 1
        assert payload["cache_updates"]["tables_touched"] == ["research_runs", "run_events"]


# =============================================================================
# RESEARCH WAIT TESTS
# =============================================================================


class TestResearchWait:
    def test_wait_completes(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_123",
                    "query": "AI research",
                    "sources": [{"title": "Source 1", "url": "http://example.com"}],
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "wait", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "Research completed" in result.output
        assert "Found 1 sources" in result.output

    def test_wait_no_research(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(return_value={"status": "no_research"})
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "wait", "-n", "nb_123"])

        assert result.exit_code == 1
        assert "No research running" in result.output

    def test_wait_timeout(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={"status": "in_progress", "query": "AI research"}
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(
                cli, ["research", "wait", "-n", "nb_123", "--timeout", "1", "--interval", "1"]
            )

        assert result.exit_code == 1
        assert "Timed out" in result.output

    def test_wait_with_import_all(self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_123",
                    "query": "AI research",
                    "sources": [{"title": "Source 1", "url": "http://example.com"}],
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "wait", "-n", "nb_123", "--import-all"])

        assert result.exit_code == 0
        assert "Staged 1 source(s) in inbox" in result.output
        assert "inbox approve <item-id>" in result.output

        with connect_db() as connection:
            item = connection.execute(
                """
                SELECT origin, kind, state, canonical_uri
                FROM inbox_items
                """
            ).fetchone()

        assert item["origin"] == "fast_research"
        assert item["kind"] == "source"
        assert item["state"] == "pending"
        assert item["canonical_uri"] == "http://example.com"

    def test_wait_json_output_completed(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_123",
                    "query": "AI research",
                    "sources": [{"title": "Source 1", "url": "http://example.com"}],
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "wait", "-n", "nb_123", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["run_id"] == "task_123"
        assert payload["route"]["intent"] == "RESEARCH"
        assert payload["route"]["mode"] == "research_status"
        assert payload["route"]["notebook_id"] == "nb_123"
        assert payload["route"]["profile_id"] == "default"
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["route"]["transport"] == {
            "kind": "httpx",
            "endpoint": BATCHEXECUTE_URL,
            "rpcid": RPCMethod.POLL_RESEARCH.value,
        }
        assert payload["result"]["status"] == "completed"
        assert payload["result"]["sources_found"] == 1
        assert payload["cache_updates"]["tables_touched"] == ["research_runs", "run_events"]

    def test_wait_json_output_with_import(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_123",
                    "query": "AI research",
                    "sources": [{"title": "Source 1", "url": "http://example.com"}],
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(
                cli, ["research", "wait", "-n", "nb_123", "--json", "--import-all"]
            )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["mode"] == "research_status"
        assert payload["result"]["status"] == "completed"
        assert payload["result"]["staged"] == 1
        assert payload["result"]["existing_inbox_count"] == 0
        assert len(payload["result"]["inbox_item_ids"]) == 1
        assert payload["cache_updates"]["tables_touched"] == [
            "research_runs",
            "run_events",
            "inbox_items",
            "inbox_clusters",
        ]

    def test_wait_json_no_research(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(return_value={"status": "no_research"})
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "wait", "-n", "nb_123", "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["route"]["mode"] == "research_status"
        assert payload["result"]["status"] == "no_research"
        assert "error" in payload["result"]
        assert payload["cache_updates"]["tables_touched"] == ["run_events"]

    def test_wait_json_timeout(self, runner, mock_auth, mock_fetch_tokens):
        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={"status": "in_progress", "task_id": "task_123", "query": "AI research"}
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(
                cli,
                ["research", "wait", "-n", "nb_123", "--json", "--timeout", "1", "--interval", "1"],
            )

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["route"]["mode"] == "research_status"
        assert payload["result"]["status"] == "timeout"
        assert payload["cache_updates"]["tables_touched"] == ["research_runs", "run_events"]

    def test_wait_with_research_id_updates_local_run_and_events(
        self, runner, mock_auth, mock_fetch_tokens
    ):
        with connect_db() as connection:
            _insert_research_run_seed(connection, "task_123", "nb_123")

        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_123",
                    "query": "AI research",
                    "sources": [
                        {"title": "Source 1", "url": "http://example.com"},
                        {"title": "Source 2", "url": "http://example.com/2"},
                    ],
                    "summary": "Summary",
                }
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "wait", "task_123"])

        assert result.exit_code == 0
        assert "Research completed" in result.output
        assert "task_123" in result.output

        with connect_db() as connection:
            row = connection.execute(
                """
                SELECT status, discovered_count, imported_count
                FROM research_runs
                WHERE research_id = ?
                """,
                ("task_123",),
            ).fetchone()
            events = connection.execute(
                "SELECT kind, run_id FROM run_events ORDER BY ts ASC, event_id ASC"
            ).fetchall()

        assert row["status"] == "completed"
        assert row["discovered_count"] == 2
        assert row["imported_count"] == 0
        assert any(event["kind"] == "research.polled" and event["run_id"] == "task_123" for event in events)
        assert any(
            event["kind"] == "research.completed" and event["run_id"] == "task_123"
            for event in events
        )


# =============================================================================
# RESEARCH IMPORT TESTS
# =============================================================================


class TestResearchImport:
    def test_import_dry_run_builds_candidate_summary(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_research_run_seed(connection, "task_123", "nb_123")
            _insert_source_seed(
                connection,
                notebook_id="nb_123",
                source_id="src_existing",
                origin_uri="http://example.com/existing",
            )

        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_123",
                    "query": "AI research",
                    "sources": [
                        {"title": "Existing", "url": "http://example.com/existing"},
                        {"title": "Fresh", "url": "http://example.com/fresh"},
                        {"title": "Fresh copy", "url": "http://example.com/fresh"},
                        {"title": "Title Only", "url": ""},
                    ],
                }
            )
            mock_client.research.import_sources = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "import", "task_123", "--dry-run", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["run_id"] == "task_123"
        assert payload["route"]["intent"] == "RESEARCH"
        assert payload["route"]["mode"] == "research_import"
        assert payload["route"]["notebook_id"] == "nb_123"
        assert payload["route"]["profile_id"] == "default"
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["route"]["transport"] == {
            "kind": "httpx",
            "endpoint": BATCHEXECUTE_URL,
            "rpcid": RPCMethod.IMPORT_RESEARCH.value,
        }
        assert payload["result"]["status"] == "preview"
        assert payload["result"]["would_import"] == 1
        assert payload["result"]["candidate_summary"] == {
            "total_candidates": 4,
            "importable_count": 1,
            "skipped_missing_url": 1,
            "skipped_duplicate_candidate": 1,
            "skipped_existing_source": 1,
            "already_imported_count": 0,
        }
        assert [candidate["decision"] for candidate in payload["result"]["candidates"]] == [
            "skip",
            "import",
            "skip",
            "skip",
        ]
        assert payload["cache_updates"]["tables_touched"] == ["research_runs", "run_events"]
        mock_client.research.import_sources.assert_not_called()

    def test_import_json_stages_inbox_items_and_persists_local_state(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_research_run_seed(connection, "task_123", "nb_123")
            _insert_detail_sync_seed(connection, "nb_123")

        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_123",
                    "query": "AI research",
                    "sources": [{"title": "Source 1", "url": "http://example.com"}],
                }
            )
            mock_client.research.import_sources = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "import", "task_123", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["run_id"] == "task_123"
        assert payload["route"]["intent"] == "RESEARCH"
        assert payload["route"]["mode"] == "research_import"
        assert payload["route"]["notebook_id"] == "nb_123"
        assert payload["route"]["profile_id"] == "default"
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["route"]["transport"] == {
            "kind": "httpx",
            "endpoint": BATCHEXECUTE_URL,
            "rpcid": RPCMethod.IMPORT_RESEARCH.value,
        }
        assert payload["result"]["status"] == "staged"
        assert payload["result"]["staged"] == 1
        assert payload["result"]["existing_inbox_count"] == 0
        assert payload["result"]["message"] == "Staged 1 research source(s) in inbox."
        assert payload["result"]["inbox_items"][0]["origin"] == "fast_research"
        assert payload["result"]["inbox_items"][0]["kind"] == "source"
        assert payload["result"]["inbox_items"][0]["state"] == "pending"
        assert payload["result"]["inbox_items"][0]["approval_required"] is True
        assert payload["result"]["inbox_items"][0]["canonical_uri"] == "http://example.com"
        assert payload["cache_updates"]["tables_touched"] == [
            "research_runs",
            "run_events",
            "inbox_items",
            "inbox_clusters",
        ]
        mock_client.research.import_sources.assert_not_called()

        with connect_db() as connection:
            item = connection.execute(
                """
                SELECT origin, kind, state, approval_required, canonical_uri, cluster_id
                FROM inbox_items
                """,
            ).fetchone()
            cluster = connection.execute(
                """
                SELECT canonical_uri, representative_item_id
                FROM inbox_clusters
                """
            ).fetchone()
            notebook = connection.execute(
                "SELECT detail_synced_at, remote_fingerprint FROM notebooks WHERE notebook_id = ?",
                ("nb_123",),
            ).fetchone()
            sync_run = connection.execute(
                "SELECT status, error_text FROM sync_runs WHERE id = ?",
                ("sr_detail",),
            ).fetchone()
            research = connection.execute(
                """
                SELECT imported_count, raw_json
                FROM research_runs
                WHERE research_id = ?
                """,
                ("task_123",),
            ).fetchone()
            events = connection.execute(
                "SELECT kind FROM run_events ORDER BY ts ASC, event_id ASC"
            ).fetchall()

        assert item["origin"] == "fast_research"
        assert item["kind"] == "source"
        assert item["state"] == "pending"
        assert item["approval_required"] == 1
        assert item["canonical_uri"] == "http://example.com"
        assert item["cluster_id"].startswith("icl_")
        assert cluster["canonical_uri"] == "http://example.com"
        assert cluster["representative_item_id"] == payload["result"]["inbox_item_ids"][0]
        assert notebook["detail_synced_at"] == "2026-03-15T04:00:00+00:00"
        assert notebook["remote_fingerprint"] == "fp_before"
        assert sync_run["status"] == "completed"
        assert sync_run["error_text"] is None
        assert research["imported_count"] == 0
        assert json.loads(research["raw_json"])["staged"] == 1
        assert any(event["kind"] == "inbox.item.created" for event in events)
        assert not any(event["kind"] == "approval.requested" for event in events)
        assert not any(event["kind"] == "research.imported" for event in events)

    def test_import_json_includes_cluster_explanations_in_staged_items(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_research_run_seed(connection, "task_123", "nb_123")

        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_123",
                    "query": "AI research",
                    "sources": [
                        {
                            "title": "Source 1",
                            "url": "http://example.com",
                            "content_hash": "sha256:abc123",
                            "report_citation_provenance": "report:rpt-123:citation:4",
                        }
                    ],
                }
            )
            mock_client.research.import_sources = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "import", "task_123", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        item = payload["result"]["inbox_items"][0]
        cluster = payload["result"]["inbox_clusters"][0]

        assert len(payload["result"]["inbox_clusters"]) == 1
        assert cluster["representative_item_id"] == item["id"]
        assert cluster["member_item_ids"] == [item["id"]]
        assert cluster["recommended_action"]["kind"] == "approve_import_source"
        assert item["rationale"]["candidate"]["content_hash"] == "sha256:abc123"
        assert (
            item["rationale"]["candidate"]["report_citation_provenance"]
            == "report:rpt-123:citation:4"
        )
        assert item["rationale"]["scores"] == {
            "relevance": item["relevance_score"],
            "novelty": item["novelty_score"],
            "trust": item["trust_score"],
        }
        assert item["rationale"]["cluster"]["cluster_id"] == item["cluster_id"]
        assert item["rationale"]["cluster"]["is_representative"] is True
        assert item["rationale"]["cluster"]["recommended_action"]["kind"] == "approve_import_source"

    def test_import_json_clusters_new_results_with_existing_active_inbox_items(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_research_run_seed(connection, "task_456", "nb_123")
            _insert_inbox_item_seed(
                connection,
                item_id="inb_existing",
                notebook_id="nb_123",
                title="Roadmap 2026 launch notes",
                canonical_uri="http://example.com/research/roadmap-2026-launch",
                priority=4,
                novelty_score=0.68,
                relevance_score=0.86,
                trust_score=0.82,
            )

        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_456",
                    "query": "AI research",
                    "sources": [
                        {
                            "title": "Roadmap 2026 launch update",
                            "url": "http://example.com/posts/roadmap-2026-launch-update",
                        }
                    ],
                }
            )
            mock_client.research.import_sources = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "import", "task_456", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        cluster = payload["result"]["inbox_clusters"][0]
        staged_item = payload["result"]["inbox_items"][0]

        assert payload["result"]["staged"] == 1
        assert len(payload["result"]["inbox_clusters"]) == 1
        assert cluster["representative_item_id"] == "inb_existing"
        assert sorted(cluster["member_item_ids"]) == sorted(["inb_existing", staged_item["id"]])
        assert cluster["signals"] == ["domain_slug_similarity"]
        assert cluster["recommended_action"] == {"kind": "approve_top_n", "target_count": 2}
        assert staged_item["rationale"]["cluster"]["representative_item_id"] == "inb_existing"
        assert staged_item["rationale"]["cluster"]["is_representative"] is False
        assert staged_item["rationale"]["cluster"]["match_signals"] == ["domain_slug_similarity"]

        with connect_db() as connection:
            items = connection.execute(
                """
                SELECT id, cluster_id, rationale_json
                FROM inbox_items
                WHERE notebook_id = ?
                ORDER BY id ASC
                """,
                ("nb_123",),
            ).fetchall()
            persisted_cluster = connection.execute(
                """
                SELECT representative_item_id
                FROM inbox_clusters
                WHERE id = ?
                """,
                (cluster["id"],),
            ).fetchone()

        assert {row["cluster_id"] for row in items} == {cluster["id"]}
        assert persisted_cluster["representative_item_id"] == "inb_existing"
        existing_rationale = json.loads(items[0]["rationale_json"])
        assert existing_rationale["cluster"]["member_item_ids"] == cluster["member_item_ids"]

    def test_import_json_surfaces_scoring_context_from_local_history(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_research_run_seed(connection, "task_context", "nb_123")
            _insert_contextual_history_seed(connection, "nb_123")
            _insert_inbox_item_seed(
                connection,
                item_id="inb_prior_approved",
                notebook_id="nb_123",
                title="Previously approved source",
                canonical_uri="http://example.com",
                state="approved",
            )

        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_context",
                    "query": "AI research",
                    "sources": [{"title": "Source 1", "url": "http://example.com"}],
                }
            )
            mock_client.research.import_sources = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["research", "import", "task_context", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        item = payload["result"]["inbox_items"][0]

        assert item["rationale"]["scoring_context"] == {
            "workspace_match_count": 1,
            "query_history_match_count": 1,
            "prior_approved_count": 1,
            "prior_rejected_count": 0,
        }
        assert item["rationale"]["scores"] == {
            "relevance": item["relevance_score"],
            "novelty": item["novelty_score"],
            "trust": item["trust_score"],
        }

    def test_import_json_reuses_existing_staged_inbox_items(
        self, runner, mock_auth, mock_fetch_tokens, monkeypatch, tmp_path
    ):
        _prepare_local_cache_home(monkeypatch, tmp_path)
        with connect_db() as connection:
            _insert_research_run_seed(connection, "task_123", "nb_123")

        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(
                return_value={
                    "status": "completed",
                    "task_id": "task_123",
                    "query": "AI research",
                    "sources": [{"title": "Source 1", "url": "http://example.com"}],
                }
            )
            mock_client.research.import_sources = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client

            first = runner.invoke(cli, ["research", "import", "task_123", "--json"])

        assert first.exit_code == 0

        with patch_client_for_module("research") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.research.poll = AsyncMock(side_effect=AssertionError("unexpected poll"))
            mock_client.research.import_sources = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client
            result = runner.invoke(
                cli,
                ["research", "import", "task_123", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["run_id"] == "task_123"
        assert payload["route"]["intent"] == "RESEARCH"
        assert payload["route"]["mode"] == "research_import"
        assert payload["route"]["notebook_id"] == "nb_123"
        assert payload["route"]["profile_id"] == "default"
        assert payload["route"]["source_of_truth"] == "local_cache"
        assert payload["route"]["cache_mode"] == "offline"
        assert payload["route"]["transport"]["kind"] == "local"
        assert payload["result"]["status"] == "staged"
        assert payload["result"]["staged"] == 0
        assert payload["result"]["existing_inbox_count"] == 1
        assert payload["result"]["message"] == "Research sources are already staged in inbox."
        assert payload["cache_updates"]["tables_touched"] == [
            "research_runs",
            "run_events",
            "inbox_items",
            "inbox_clusters",
        ]
        mock_client.research.import_sources.assert_not_called()

        with connect_db() as connection:
            research = connection.execute(
                """
                SELECT imported_count, raw_json
                FROM research_runs
                WHERE research_id = ?
                """,
                ("task_123",),
            ).fetchone()
            inbox_count = connection.execute("SELECT COUNT(*) AS count FROM inbox_items").fetchone()
            events = connection.execute(
                "SELECT kind FROM run_events ORDER BY ts ASC, event_id ASC"
            ).fetchall()

        assert research["imported_count"] == 0
        raw_payload = json.loads(research["raw_json"])
        assert raw_payload["staged"] == 0
        assert raw_payload["existing_inbox_count"] == 1
        assert inbox_count["count"] == 1
        assert sum(1 for event in events if event["kind"] == "inbox.item.created") == 1


# =============================================================================
# COMMAND EXISTENCE TESTS
# =============================================================================


class TestResearchCommandsExist:
    def test_research_group_exists(self, runner):
        result = runner.invoke(cli, ["research", "--help"])
        assert result.exit_code == 0
        assert "Research management commands" in result.output
        assert "import" in result.output
        assert "source add-research" in result.output
        assert "research import <research-id> --dry-run" in result.output

    def test_research_status_command_exists(self, runner):
        result = runner.invoke(cli, ["research", "status", "--help"])
        assert result.exit_code == 0
        assert "Check research status" in result.output

    def test_research_wait_command_exists(self, runner):
        result = runner.invoke(cli, ["research", "wait", "--help"])
        assert result.exit_code == 0
        assert "Wait for research to complete" in result.output

    def test_research_start_command_exists(self, runner):
        result = runner.invoke(cli, ["research", "start", "--help"])
        assert result.exit_code == 0
        assert "Start a research run" in result.output

    def test_research_import_command_exists(self, runner):
        result = runner.invoke(cli, ["research", "import", "--help"])
        assert result.exit_code == 0
        assert "Preview or stage sources from a completed research run" in result.output
