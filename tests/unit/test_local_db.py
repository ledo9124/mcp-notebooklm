"""Unit tests for the local SQLite bootstrap helpers."""

from __future__ import annotations

import sqlite3

from notebooklm.local.db import DEFAULT_BUSY_TIMEOUT_MS, connect_db, get_db_path


def test_get_db_path_uses_notebooklm_home(monkeypatch, tmp_path):
    """Default DB placement should follow NOTEBOOKLM_HOME."""
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(tmp_path / "state"))

    assert get_db_path() == (tmp_path / "state" / "cache.db").resolve()


def test_connect_db_creates_file_and_enables_wal(tmp_path):
    """The connection factory should create the DB file with the expected pragmas."""
    db_path = tmp_path / "cache" / "cache.db"

    with connect_db(db_path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert db_path.exists()
    assert journal_mode.lower() == "wal"
    assert synchronous == 1  # NORMAL
    assert foreign_keys == 1
    assert busy_timeout == DEFAULT_BUSY_TIMEOUT_MS


def test_connect_db_reopens_existing_database_without_resetting_contents(tmp_path):
    """Reopening the same DB should preserve existing rows and keep WAL active."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES ('kept')")
        connection.commit()

    with connect_db(db_path) as connection:
        row = connection.execute("SELECT value FROM sample").fetchone()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert isinstance(row, sqlite3.Row)
    assert row["value"] == "kept"
    assert journal_mode.lower() == "wal"
