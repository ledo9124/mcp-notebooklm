"""Parent-level integration contract for local SQLite bootstrap."""

from __future__ import annotations

from notebooklm.local.db import connect_db
from notebooklm.local.migrations import MIGRATIONS_TABLE, get_current_version
from notebooklm.local.schema import (
    APP_STATE_SINGLETON_KEY,
    HISTORY_TABLES,
    INBOX_TABLES,
    INITIAL_SCHEMA_VERSION,
    LEASE_TABLES,
    LATEST_SCHEMA_VERSION,
    MVP_TABLES,
    POST_MVP_RUN_TABLES,
    RADAR_TABLES,
    WORKSPACE_TABLES,
)

EXPECTED_DEFAULT_LEDGER = [
    (INITIAL_SCHEMA_VERSION, "schema_v1"),
    (2, "approval_requests_v2"),
    (3, "mvp_indexes_v3"),
    (4, "inbox_tables_v4"),
    (5, "radar_tables_v5"),
    (6, "leases_v6"),
    (7, "post_mvp_run_tables_v7"),
    (8, "history_fts_v8"),
    (9, "workspace_tables_v9"),
    (10, "workspace_index_fts_v10"),
    (LATEST_SCHEMA_VERSION, "approval_policy_columns_v11"),
]


def test_connect_db_bootstraps_schema_and_wal_mode(tmp_path):
    """Opening the DB should apply the built-in schema and keep WAL enabled."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        migration_rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        app_state = connection.execute(
            "SELECT singleton_key, schema_version FROM app_state"
        ).fetchone()

    assert journal_mode.lower() == "wal"
    assert set(MVP_TABLES).issubset(tables)
    assert set(HISTORY_TABLES).issubset(tables)
    assert set(INBOX_TABLES).issubset(tables)
    assert set(RADAR_TABLES).issubset(tables)
    assert set(LEASE_TABLES).issubset(tables)
    assert set(WORKSPACE_TABLES).issubset(tables)
    assert set(POST_MVP_RUN_TABLES).issubset(tables)
    assert [(row["version"], row["name"]) for row in migration_rows] == EXPECTED_DEFAULT_LEDGER
    assert app_state["singleton_key"] == APP_STATE_SINGLETON_KEY
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION


def test_connect_db_reopen_keeps_schema_version_idempotent(tmp_path):
    """Reopening an existing DB should not replay the built-in migration ledger."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        first_rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()

    with connect_db(db_path) as connection:
        second_rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        current_version = get_current_version(connection)

    assert [(row["version"], row["name"]) for row in first_rows] == EXPECTED_DEFAULT_LEDGER
    assert [(row["version"], row["name"]) for row in second_rows] == EXPECTED_DEFAULT_LEDGER
    assert current_version == LATEST_SCHEMA_VERSION
