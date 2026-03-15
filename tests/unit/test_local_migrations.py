"""Unit tests for the local SQLite migration runner."""

from __future__ import annotations

import pytest

from notebooklm.local.db import connect_db
from notebooklm.local.migrations import (
    DEFAULT_MIGRATIONS,
    MIGRATIONS_TABLE,
    Migration,
    get_current_version,
    run_migrations,
)
from notebooklm.local.schema import (
    HISTORY_TABLES,
    INDEX_NAMES,
    INBOX_TABLES,
    LEASE_TABLES,
    LATEST_SCHEMA_VERSION,
    POST_MVP_RUN_TABLES,
    RADAR_TABLES,
    WORKSPACE_TABLES,
)

EXPECTED_DEFAULT_LEDGER = [
    (1, "schema_v1"),
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


def test_run_migrations_applies_pending_versions_in_order(tmp_path):
    """Pending migrations should execute in-order and record their versions."""
    db_path = tmp_path / "cache.db"

    migrations = [
        Migration(
            version=1,
            name="create_one",
            apply=lambda connection: connection.execute(
                "CREATE TABLE one (id INTEGER PRIMARY KEY)"
            ),
        ),
        Migration(
            version=2,
            name="create_two",
            apply=lambda connection: connection.execute(
                "CREATE TABLE two (id INTEGER PRIMARY KEY)"
            ),
        ),
    ]

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, migrations) == [1, 2]
        assert get_current_version(connection) == 2

        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert MIGRATIONS_TABLE in tables
    assert "one" in tables
    assert "two" in tables


def test_run_migrations_is_idempotent_when_versions_already_applied(tmp_path):
    """A second run should not replay migrations that are already recorded."""
    db_path = tmp_path / "cache.db"
    migrations = [
        Migration(
            version=1,
            name="create_items",
            apply=lambda connection: connection.execute(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)"
            ),
        )
    ]

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, migrations) == [1]
        assert run_migrations(connection, migrations) == []

        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()

    assert [(row["version"], row["name"]) for row in rows] == [(1, "create_items")]


def test_run_migrations_rejects_out_of_order_or_duplicate_versions(tmp_path):
    """Migration plans should fail fast if version ordering is ambiguous."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        with pytest.raises(ValueError, match="sorted"):
            run_migrations(
                connection,
                [
                    Migration(2, "later", lambda conn: None),
                    Migration(1, "earlier", lambda conn: None),
                ],
            )

        with pytest.raises(ValueError, match="unique"):
            run_migrations(
                connection,
                [
                    Migration(1, "first", lambda conn: None),
                    Migration(1, "duplicate", lambda conn: None),
                ],
            )


def test_default_migrations_upgrade_existing_v1_database(tmp_path):
    """Reopening a v1 DB should backfill later built-in migrations."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, DEFAULT_MIGRATIONS[:1]) == [1]

    with connect_db(db_path) as connection:
        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        app_state = connection.execute(
            "SELECT schema_version FROM app_state WHERE singleton_key = 1"
        ).fetchone()

    assert [(row["version"], row["name"]) for row in rows] == EXPECTED_DEFAULT_LEDGER
    assert "approval_requests" in tables
    assert set(HISTORY_TABLES).issubset(tables)
    assert set(INBOX_TABLES).issubset(tables)
    assert set(RADAR_TABLES).issubset(tables)
    assert set(LEASE_TABLES).issubset(tables)
    assert set(WORKSPACE_TABLES).issubset(tables)
    assert set(POST_MVP_RUN_TABLES).issubset(tables)
    assert set(INDEX_NAMES).issubset(indexes)
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION


def test_default_migrations_backfill_inbox_tables_for_existing_v3_database(tmp_path):
    """A v3 database should receive the inbox tables when v4 migrations run."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, DEFAULT_MIGRATIONS[:3]) == [1, 2, 3]
        connection.execute("PRAGMA foreign_keys=OFF")
        with connection:
            connection.execute("DROP TABLE inbox_items")
            connection.execute("DROP TABLE inbox_clusters")
            connection.execute(
                """
                UPDATE app_state
                SET schema_version = 3
                WHERE singleton_key = 1
                """
            )
        connection.execute("PRAGMA foreign_keys=ON")

    with connect_db(db_path) as connection:
        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        app_state = connection.execute(
            "SELECT schema_version FROM app_state WHERE singleton_key = 1"
        ).fetchone()

    assert [(row["version"], row["name"]) for row in rows] == EXPECTED_DEFAULT_LEDGER
    assert set(HISTORY_TABLES).issubset(tables)
    assert set(INBOX_TABLES).issubset(tables)
    assert set(RADAR_TABLES).issubset(tables)
    assert set(LEASE_TABLES).issubset(tables)
    assert set(WORKSPACE_TABLES).issubset(tables)
    assert set(POST_MVP_RUN_TABLES).issubset(tables)
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION


def test_default_migrations_backfill_radar_tables_for_existing_v4_database(tmp_path):
    """A v4 database should receive the change-radar tables when v5 migrations run."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, DEFAULT_MIGRATIONS[:4]) == [1, 2, 3, 4]
        connection.execute("PRAGMA foreign_keys=OFF")
        with connection:
            connection.execute("DROP TABLE delta_briefings")
            connection.execute("DROP TABLE change_events")
            connection.execute("DROP TABLE watch_runs")
            connection.execute("DROP TABLE source_revisions")
            connection.execute("DROP TABLE watches")
            connection.execute(
                """
                UPDATE app_state
                SET schema_version = 4
                WHERE singleton_key = 1
                """
            )
        connection.execute("PRAGMA foreign_keys=ON")

    with connect_db(db_path) as connection:
        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        app_state = connection.execute(
            "SELECT schema_version FROM app_state WHERE singleton_key = 1"
        ).fetchone()

    assert [(row["version"], row["name"]) for row in rows] == EXPECTED_DEFAULT_LEDGER
    assert set(HISTORY_TABLES).issubset(tables)
    assert set(RADAR_TABLES).issubset(tables)
    assert set(LEASE_TABLES).issubset(tables)
    assert set(WORKSPACE_TABLES).issubset(tables)
    assert set(POST_MVP_RUN_TABLES).issubset(tables)
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION


def test_default_migrations_backfill_leases_table_for_existing_v5_database(tmp_path):
    """A v5 database should receive the shared lease table when v6 migrations run."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, DEFAULT_MIGRATIONS[:5]) == [1, 2, 3, 4, 5]
        with connection:
            connection.execute("DROP TABLE leases")
            connection.execute(
                """
                UPDATE app_state
                SET schema_version = 5
                WHERE singleton_key = 1
                """
            )

    with connect_db(db_path) as connection:
        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        app_state = connection.execute(
            "SELECT schema_version FROM app_state WHERE singleton_key = 1"
        ).fetchone()

    assert [(row["version"], row["name"]) for row in rows] == EXPECTED_DEFAULT_LEDGER
    assert set(HISTORY_TABLES).issubset(tables)
    assert set(LEASE_TABLES).issubset(tables)
    assert set(WORKSPACE_TABLES).issubset(tables)
    assert set(POST_MVP_RUN_TABLES).issubset(tables)
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION


def test_default_migrations_backfill_post_mvp_run_tables_for_existing_v6_database(tmp_path):
    """A v6 database should receive workspace/doctor run tables when v7 runs."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, DEFAULT_MIGRATIONS[:6]) == [1, 2, 3, 4, 5, 6]
        with connection:
            connection.execute("DROP TABLE doctor_runs")
            connection.execute("DROP TABLE workspace_runs")
            connection.execute(
                """
                UPDATE app_state
                SET schema_version = 6
                WHERE singleton_key = 1
                """
            )

    with connect_db(db_path) as connection:
        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        app_state = connection.execute(
            "SELECT schema_version FROM app_state WHERE singleton_key = 1"
        ).fetchone()

    assert [(row["version"], row["name"]) for row in rows] == EXPECTED_DEFAULT_LEDGER
    assert set(POST_MVP_RUN_TABLES).issubset(tables)
    assert set(HISTORY_TABLES).issubset(tables)
    assert set(WORKSPACE_TABLES).issubset(tables)
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION


def test_default_migrations_backfill_history_fts_for_existing_v7_database(tmp_path):
    """A v7 database should receive the history FTS table when v8 runs."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, DEFAULT_MIGRATIONS[:7]) == [1, 2, 3, 4, 5, 6, 7]
        with connection:
            connection.execute("DROP TABLE history_fts")
            connection.execute(
                """
                UPDATE app_state
                SET schema_version = 7
                WHERE singleton_key = 1
                """
            )

    with connect_db(db_path) as connection:
        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        app_state = connection.execute(
            "SELECT schema_version FROM app_state WHERE singleton_key = 1"
        ).fetchone()
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
                "profile_a",
                "find renewal terms",
                "Renewal is covered in section 9.",
                "Vendor Contracts",
                "MSA Renewal Addendum",
            ),
        )
        matches = connection.execute(
            "SELECT run_id FROM history_fts WHERE history_fts MATCH ?",
            ("renewal",),
        ).fetchall()

    assert [(row["version"], row["name"]) for row in rows] == EXPECTED_DEFAULT_LEDGER
    assert set(HISTORY_TABLES).issubset(tables)
    assert set(WORKSPACE_TABLES).issubset(tables)
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION
    assert [row["run_id"] for row in matches] == ["qr_history_1"]


def test_default_migrations_backfill_workspace_tables_for_existing_v8_database(tmp_path):
    """A v8 database should receive the workspace tables and FTS when v9/v10 run."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, DEFAULT_MIGRATIONS[:8]) == [1, 2, 3, 4, 5, 6, 7, 8]
        with connection:
            connection.execute("DROP TABLE workspace_index_entries")
            connection.execute("DROP TABLE workspace_rules")
            connection.execute("DROP TABLE workspace_members")
            connection.execute("DROP TABLE workspaces")
            connection.execute(
                """
                UPDATE app_state
                SET schema_version = 8
                WHERE singleton_key = 1
                """
            )

    with connect_db(db_path) as connection:
        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        app_state = connection.execute(
            "SELECT schema_version FROM app_state WHERE singleton_key = 1"
        ).fetchone()

    assert [(row["version"], row["name"]) for row in rows] == EXPECTED_DEFAULT_LEDGER
    assert set(WORKSPACE_TABLES).issubset(tables)
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION


def test_default_migrations_backfill_workspace_index_fts_for_existing_v9_database(tmp_path):
    """A v9 database should receive the workspace FTS table when v10 runs."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, DEFAULT_MIGRATIONS[:9]) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        with connection:
            connection.execute("DROP TABLE workspace_index_fts")
            connection.execute(
                """
                UPDATE app_state
                SET schema_version = 9
                WHERE singleton_key = 1
                """
            )

    with connect_db(db_path) as connection:
        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        app_state = connection.execute(
            "SELECT schema_version FROM app_state WHERE singleton_key = 1"
        ).fetchone()
        connection.execute(
            """
            INSERT INTO workspace_index_fts (
                entry_id,
                workspace_id,
                profile_id,
                notebook_id,
                notebook_title,
                notebook_summary,
                title_aliases_text,
                source_titles_text,
                source_snippets_text,
                tags_text,
                recent_query_text,
                content_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "wsi_v10_1",
                "ws_market",
                "profile_a",
                "nb_pricing",
                "Pricing Notebook",
                "Quarterly renewal plan",
                "pricing notebook",
                "Renewal Deck",
                "Discount ladder notes",
                "pricing renewal",
                "How did renewals change last quarter?",
                "Pricing Notebook Quarterly renewal plan Renewal Deck Discount ladder notes",
            ),
        )
        matches = connection.execute(
            "SELECT notebook_id FROM workspace_index_fts WHERE workspace_index_fts MATCH ?",
            ("renewal",),
        ).fetchall()

    assert [(row["version"], row["name"]) for row in rows] == EXPECTED_DEFAULT_LEDGER
    assert set(WORKSPACE_TABLES).issubset(tables)
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION
    assert [row["notebook_id"] for row in matches] == ["nb_pricing"]


def test_default_migrations_backfill_approval_policy_columns_for_existing_v10_database(tmp_path):
    """A v10 database should receive profile/notebook approval-policy columns when v11 runs."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path, apply_migrations=False) as connection:
        assert run_migrations(connection, DEFAULT_MIGRATIONS[:10]) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        connection.execute("PRAGMA foreign_keys=OFF")
        with connection:
            connection.execute("DROP TABLE notebooks")
            connection.execute("DROP TABLE profiles")
            connection.execute(
                """
                CREATE TABLE profiles (
                    profile_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    account_email TEXT,
                    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
                    storage_state_path TEXT NOT NULL,
                    browser_profile_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE notebooks (
                    notebook_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL
                        REFERENCES profiles(profile_id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    is_owner INTEGER NOT NULL DEFAULT 0 CHECK (is_owner IN (0, 1)),
                    share_visibility TEXT,
                    created_at_remote TEXT,
                    source_count INTEGER NOT NULL DEFAULT 0,
                    artifact_count INTEGER NOT NULL DEFAULT 0,
                    note_count INTEGER NOT NULL DEFAULT 0,
                    summary_preview TEXT,
                    index_synced_at TEXT,
                    detail_synced_at TEXT,
                    remote_fingerprint TEXT,
                    tombstoned_at TEXT,
                    raw_json TEXT
                )
                """
            )
            connection.execute(
                """
                UPDATE app_state
                SET schema_version = 10
                WHERE singleton_key = 1
                """
            )
        connection.execute("PRAGMA foreign_keys=ON")

    with connect_db(db_path) as connection:
        rows = connection.execute(
            f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
        ).fetchall()
        profile_columns = connection.execute("PRAGMA table_info(profiles)").fetchall()
        notebook_columns = connection.execute("PRAGMA table_info(notebooks)").fetchall()
        app_state = connection.execute(
            "SELECT schema_version FROM app_state WHERE singleton_key = 1"
        ).fetchone()

    assert [(row["version"], row["name"]) for row in rows] == EXPECTED_DEFAULT_LEDGER
    assert "approval_policy_json" in [row["name"] for row in profile_columns]
    assert "approval_policy_json" in [row["name"] for row in notebook_columns]
    assert app_state["schema_version"] == LATEST_SCHEMA_VERSION
