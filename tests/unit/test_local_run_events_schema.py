"""Contract tests for the run_events table in the local cache schema."""

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


def test_run_events_table_matches_b025a_contract():
    connection = _connect()

    columns = _table_info(connection, "run_events")
    table_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'run_events'"
    ).fetchone()["sql"]

    assert list(columns) == [
        "event_id",
        "trace_id",
        "run_id",
        "kind",
        "ts",
        "payload_json",
    ]
    assert columns["event_id"]["pk"] == 1
    assert columns["trace_id"]["notnull"] == 1
    assert columns["kind"]["notnull"] == 1
    assert columns["ts"]["notnull"] == 1
    assert columns["run_id"]["notnull"] == 0
    assert columns["payload_json"]["notnull"] == 0
    assert "CHECK (event_id LIKE 'evt_%')" in table_sql


def test_run_events_trace_id_index_matches_b025d_contract():
    connection = _connect()

    indexes = {
        row["name"]: row
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }

    assert "idx_run_events_trace_id" in indexes
    assert "run_events (trace_id)" in indexes["idx_run_events_trace_id"]["sql"]
