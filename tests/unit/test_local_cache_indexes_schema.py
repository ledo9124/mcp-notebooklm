"""Contract tests for the remaining composite MVP cache indexes."""

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


def _index_columns(connection: sqlite3.Connection, index_name: str) -> list[str]:
    return [
        row["name"] for row in connection.execute(f"PRAGMA index_info({index_name})").fetchall()
    ]


def test_sources_composite_indexes_match_b026b_contract():
    connection = _connect()

    index_names = {
        row["name"] for row in connection.execute("PRAGMA index_list(sources)").fetchall()
    }

    assert "idx_sources_notebook_status" in index_names
    assert "idx_sources_profile_source_type" in index_names
    assert _index_columns(connection, "idx_sources_notebook_status") == [
        "notebook_id",
        "status",
    ]
    assert _index_columns(connection, "idx_sources_profile_source_type") == [
        "profile_id",
        "source_type",
    ]


def test_artifacts_composite_index_matches_b026c_contract():
    connection = _connect()

    index_names = {
        row["name"] for row in connection.execute("PRAGMA index_list(artifacts)").fetchall()
    }

    assert "idx_artifacts_notebook_status" in index_names
    assert _index_columns(connection, "idx_artifacts_notebook_status") == [
        "notebook_id",
        "status",
    ]


def test_query_runs_composite_index_matches_b026d_contract():
    connection = _connect()

    index_names = {
        row["name"] for row in connection.execute("PRAGMA index_list(query_runs)").fetchall()
    }

    assert "idx_query_runs_prompt_fingerprint_intent" in index_names
    assert _index_columns(connection, "idx_query_runs_prompt_fingerprint_intent") == [
        "prompt_hash",
        "notebook_fingerprint",
        "intent",
    ]


def test_sync_runs_composite_index_matches_b026e_contract():
    connection = _connect()

    index_names = {
        row["name"] for row in connection.execute("PRAGMA index_list(sync_runs)").fetchall()
    }

    assert "idx_sync_runs_profile_scope_started_at" in index_names
    assert _index_columns(connection, "idx_sync_runs_profile_scope_started_at") == [
        "profile_id",
        "scope",
        "started_at",
    ]
