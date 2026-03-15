"""Contract tests for the execution-history tables in the local cache schema."""

from __future__ import annotations

import sqlite3

from notebooklm.local.schema import apply_schema_v1


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    with connection:
        apply_schema_v1(connection)
    return connection


def _table_info(connection: sqlite3.Connection, table_name: str) -> dict[str, sqlite3.Row]:
    return {
        row["name"]: row
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _foreign_keys(connection: sqlite3.Connection, table_name: str) -> dict[str, sqlite3.Row]:
    return {
        row["from"]: row
        for row in connection.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    }


def test_query_runs_table_matches_b024a_contract():
    connection = _connect()

    columns = _table_info(connection, "query_runs")
    foreign_keys = _foreign_keys(connection, "query_runs")
    table_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'query_runs'"
    ).fetchone()["sql"]

    assert list(columns) == [
        "id",
        "trace_id",
        "profile_id",
        "notebook_id",
        "intent",
        "mode",
        "prompt_text",
        "prompt_hash",
        "settings_hash",
        "notebook_fingerprint",
        "cache_policy",
        "route_reason",
        "source_of_truth",
        "started_at",
        "ended_at",
        "status",
        "reused_from",
    ]
    assert columns["id"]["pk"] == 1
    assert columns["trace_id"]["notnull"] == 1
    assert columns["profile_id"]["notnull"] == 1
    assert columns["prompt_hash"]["notnull"] == 1
    assert columns["status"]["notnull"] == 1
    assert columns["reused_from"]["notnull"] == 0
    assert "CHECK (id LIKE 'qr_%')" in table_sql
    assert "'pending', 'running', 'completed', 'failed', 'cancelled'" in table_sql
    assert foreign_keys["profile_id"]["table"] == "profiles"
    assert foreign_keys["notebook_id"]["table"] == "notebooks"
    assert foreign_keys["reused_from"]["table"] == "query_runs"


def test_query_results_table_matches_b024b_contract():
    connection = _connect()

    columns = _table_info(connection, "query_results")
    foreign_keys = _foreign_keys(connection, "query_results")

    assert list(columns) == [
        "query_run_id",
        "result_type",
        "answer_text",
        "citations_json",
        "artifact_id",
        "result_json",
        "created_at",
    ]
    assert columns["query_run_id"]["pk"] == 1
    assert columns["result_type"]["notnull"] == 1
    assert columns["created_at"]["notnull"] == 1
    assert foreign_keys["query_run_id"]["table"] == "query_runs"
    assert foreign_keys["artifact_id"]["table"] == "artifacts"


def test_sync_runs_table_matches_b024c_contract():
    connection = _connect()

    columns = _table_info(connection, "sync_runs")
    foreign_keys = _foreign_keys(connection, "sync_runs")
    table_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'sync_runs'"
    ).fetchone()["sql"]

    assert list(columns) == [
        "id",
        "trace_id",
        "profile_id",
        "scope",
        "target_id",
        "trigger",
        "started_at",
        "ended_at",
        "status",
        "stats_json",
        "error_text",
    ]
    assert columns["id"]["pk"] == 1
    assert columns["trace_id"]["notnull"] == 1
    assert columns["profile_id"]["notnull"] == 1
    assert columns["scope"]["notnull"] == 1
    assert columns["trigger"]["notnull"] == 1
    assert columns["status"]["notnull"] == 1
    assert "CHECK (id LIKE 'sr_%')" in table_sql
    assert "'pending', 'running', 'completed', 'failed', 'cancelled'" in table_sql
    assert foreign_keys["profile_id"]["table"] == "profiles"
