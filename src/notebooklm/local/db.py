"""SQLite connection helpers for local NotebookLM state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from notebooklm.paths import get_home_dir

from .migrations import run_default_migrations
from notebooklm.profiles.legacy import bootstrap_legacy_profile


DB_FILENAME = "cache.db"
DEFAULT_BUSY_TIMEOUT_MS = 5_000


def get_db_path(path: str | Path | None = None) -> Path:
    """Resolve the local SQLite database path."""
    if path is not None:
        return Path(path).expanduser().resolve()
    return get_home_dir(create=True) / DB_FILENAME


def configure_connection(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Apply the baseline SQLite pragmas for the local cache database."""
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def connect_db(
    path: str | Path | None = None, *, apply_migrations: bool = True
) -> sqlite3.Connection:
    """Open the local cache DB, optionally applying the built-in migrations."""
    db_path = get_db_path(path)
    should_bootstrap_legacy = db_path == get_db_path()
    db_previously_existed = db_path.exists()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = configure_connection(sqlite3.connect(db_path))
    if apply_migrations:
        run_default_migrations(connection)
        if should_bootstrap_legacy and not db_previously_existed:
            bootstrap_legacy_profile(connection)
    return connection


__all__ = [
    "DB_FILENAME",
    "DEFAULT_BUSY_TIMEOUT_MS",
    "configure_connection",
    "connect_db",
    "get_db_path",
]
