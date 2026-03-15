"""Version-tracked SQLite migrations for local NotebookLM state."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Callable, Iterable

from .schema import (
    INITIAL_SCHEMA_VERSION,
    LATEST_SCHEMA_VERSION,
    apply_schema_v1,
    apply_schema_v2,
    apply_schema_v3,
    apply_schema_v4,
    apply_schema_v5,
    apply_schema_v6,
    apply_schema_v7,
    apply_schema_v8,
    apply_schema_v9,
    apply_schema_v10,
    apply_schema_v11,
)


MigrationFn = Callable[[sqlite3.Connection], None]
MIGRATIONS_TABLE = "schema_migrations"


@dataclass(frozen=True)
class Migration:
    """One schema migration step."""

    version: int
    name: str
    apply: MigrationFn


DEFAULT_MIGRATIONS = (
    Migration(
        version=INITIAL_SCHEMA_VERSION,
        name="schema_v1",
        apply=apply_schema_v1,
    ),
    Migration(
        version=2,
        name="approval_requests_v2",
        apply=apply_schema_v2,
    ),
    Migration(
        version=3,
        name="mvp_indexes_v3",
        apply=apply_schema_v3,
    ),
    Migration(
        version=4,
        name="inbox_tables_v4",
        apply=apply_schema_v4,
    ),
    Migration(
        version=5,
        name="radar_tables_v5",
        apply=apply_schema_v5,
    ),
    Migration(
        version=6,
        name="leases_v6",
        apply=apply_schema_v6,
    ),
    Migration(
        version=7,
        name="post_mvp_run_tables_v7",
        apply=apply_schema_v7,
    ),
    Migration(
        version=8,
        name="history_fts_v8",
        apply=apply_schema_v8,
    ),
    Migration(
        version=9,
        name="workspace_tables_v9",
        apply=apply_schema_v9,
    ),
    Migration(
        version=10,
        name="workspace_index_fts_v10",
        apply=apply_schema_v10,
    ),
    Migration(
        version=LATEST_SCHEMA_VERSION,
        name="approval_policy_columns_v11",
        apply=apply_schema_v11,
    ),
)


def ensure_migrations_table(connection: sqlite3.Connection) -> None:
    """Create the migration ledger table if it does not already exist."""
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def get_current_version(connection: sqlite3.Connection) -> int:
    """Return the latest applied schema version, or 0 when nothing has run yet."""
    ensure_migrations_table(connection)
    row = connection.execute(
        f"SELECT COALESCE(MAX(version), 0) AS version FROM {MIGRATIONS_TABLE}"
    ).fetchone()
    return int(row["version"])


def _validate_migrations(migrations: Iterable[Migration]) -> list[Migration]:
    """Require unique, strictly increasing migration versions."""
    ordered = list(migrations)
    versions = [migration.version for migration in ordered]
    if versions != sorted(versions):
        raise ValueError("Migration versions must be sorted in ascending order")
    if len(set(versions)) != len(versions):
        raise ValueError("Migration versions must be unique")
    return ordered


def run_migrations(connection: sqlite3.Connection, migrations: Iterable[Migration]) -> list[int]:
    """Apply any pending migrations and record the versions that ran."""
    ensure_migrations_table(connection)
    ordered = _validate_migrations(migrations)
    applied_versions = {
        row["version"]
        for row in connection.execute(f"SELECT version FROM {MIGRATIONS_TABLE}").fetchall()
    }

    ran: list[int] = []
    for migration in ordered:
        if migration.version in applied_versions:
            continue

        with connection:
            migration.apply(connection)
            connection.execute(
                f"INSERT INTO {MIGRATIONS_TABLE}(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
        ran.append(migration.version)
        applied_versions.add(migration.version)

    return ran


def run_default_migrations(connection: sqlite3.Connection) -> list[int]:
    """Apply the built-in local cache migrations to an open connection."""
    return run_migrations(connection, DEFAULT_MIGRATIONS)


__all__ = [
    "DEFAULT_MIGRATIONS",
    "MIGRATIONS_TABLE",
    "Migration",
    "ensure_migrations_table",
    "get_current_version",
    "run_default_migrations",
    "run_migrations",
]
