"""CLI tests for `notebooklm history`."""

from __future__ import annotations

import json

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import (
    NotebookRecord,
    NotebookRepository,
    QueryResultRecord,
    QueryResultRepository,
    QueryRunRecord,
    QueryRunRepository,
)
from notebooklm.notebooklm_cli import cli
from notebooklm.profiles.manager import ProfileManager


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


def _seed_history_rows() -> None:
    with connect_db() as connection:
        _seed_profile(connection)
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id="nb_history",
                profile_id="default",
                title="History Notebook",
                normalized_title="history notebook",
            )
        )
        QueryRunRepository(connection).upsert(
            QueryRunRecord(
                id="qr_history_1",
                trace_id="trc_history_1",
                profile_id="default",
                notebook_id="nb_history",
                intent="ask",
                mode="answer",
                prompt_text="find the renewal clause",
                prompt_hash="hash-history-1",
                cache_policy="smart",
                route_reason="remote query",
                source_of_truth="remote_http",
                started_at="2026-03-15T03:00:00Z",
                ended_at="2026-03-15T03:00:02Z",
                status="completed",
            )
        )
        QueryResultRepository(connection).upsert(
            QueryResultRecord(
                query_run_id="qr_history_1",
                result_type="answer",
                answer_text="The renewal clause appears in section 4.",
                citations_json='["citation-1"]',
                result_json='{"summary": "renewal clause"}',
                created_at="2026-03-15T03:00:02Z",
            )
        )
        with connection:
            connection.execute(
                """
                INSERT INTO history_fts (
                    run_id,
                    trace_id,
                    profile_id,
                    prompt_text,
                    answer_text,
                    notebook_title,
                    source_titles
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "qr_history_1",
                    "trc_history_1",
                    "default",
                    "find the renewal clause",
                    "The renewal clause appears in section 4.",
                    "History Notebook",
                    "Master Service Agreement Renewal Addendum",
                ),
            )


def test_history_search_json_returns_local_fts_hits(runner):
    _seed_history_rows()

    result = runner.invoke(cli, ["history", "search", "renewal", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_METADATA"
    assert payload["route"]["mode"] == "history_search"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["profile_id"] == "default"
    assert payload["result"]["query"] == "renewal"
    assert payload["result"]["count"] == 1
    assert payload["result"]["hits"][0]["run_id"] == "qr_history_1"
    assert payload["result"]["hits"][0]["notebook_title"] == "History Notebook"


def test_history_show_json_returns_full_run_detail(runner):
    _seed_history_rows()

    result = runner.invoke(cli, ["history", "show", "qr_history_1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_METADATA"
    assert payload["route"]["mode"] == "history_show"
    assert payload["route"]["profile_id"] == "default"
    assert payload["result"]["run"]["id"] == "qr_history_1"
    assert payload["result"]["run"]["route_reason"] == "remote query"
    assert payload["result"]["result"]["answer_text"] == "The renewal clause appears in section 4."
    assert payload["result"]["result"]["citations"] == ["citation-1"]
    assert payload["result"]["timing"]["duration_ms"] == 2000
    assert (
        payload["result"]["history_index"]["source_titles"]
        == "Master Service Agreement Renewal Addendum"
    )


def test_history_group_help_lists_search_and_show(runner):
    result = runner.invoke(cli, ["history", "--help"])

    assert result.exit_code == 0, result.output
    assert "search" in result.output
    assert "show" in result.output
