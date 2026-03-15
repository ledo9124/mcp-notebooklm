"""Local cache diagnostics and maintenance helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from notebooklm.paths import get_home_dir

from .db import DB_FILENAME, configure_connection
from .events import count_run_events_before, prune_run_events_before
from .schema import MVP_TABLES

_TOMBSTONE_TABLES = {
    "sources": "source_id",
    "notebooks": "notebook_id",
}
_EVENT_LOG_TABLE = "run_events"
_SYNC_TIMESTAMP_QUERIES = (
    ("notebooks", "SELECT index_synced_at AS sync_ts FROM notebooks WHERE index_synced_at IS NOT NULL"),
    ("notebooks", "SELECT detail_synced_at AS sync_ts FROM notebooks WHERE detail_synced_at IS NOT NULL"),
    ("sources", "SELECT synced_at AS sync_ts FROM sources WHERE synced_at IS NOT NULL"),
    ("sync_runs", "SELECT started_at AS sync_ts FROM sync_runs WHERE started_at IS NOT NULL"),
    ("sync_runs", "SELECT ended_at AS sync_ts FROM sync_runs WHERE ended_at IS NOT NULL"),
)


@dataclass(frozen=True)
class CacheStatus:
    """Materialized cache diagnostics for the local SQLite store."""

    db_path: str
    exists: bool
    table_counts: dict[str, int] = field(default_factory=dict)
    db_size_bytes: int = 0
    wal_size_bytes: int = 0
    oldest_sync_timestamp: str | None = None
    newest_sync_timestamp: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation."""
        return {
            "db_path": self.db_path,
            "exists": self.exists,
            "table_counts": dict(self.table_counts),
            "db_size_bytes": self.db_size_bytes,
            "wal_size_bytes": self.wal_size_bytes,
            "oldest_sync_timestamp": self.oldest_sync_timestamp,
            "newest_sync_timestamp": self.newest_sync_timestamp,
        }


@dataclass(frozen=True)
class CachePruneResult:
    """Summary of a local cache prune run."""

    db_path: str
    exists: bool
    older_than_days: int
    dry_run: bool
    candidate_counts: dict[str, int] = field(default_factory=dict)
    deleted_counts: dict[str, int] = field(default_factory=dict)
    total_candidates: int = 0
    total_deleted: int = 0
    vacuumed: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation."""
        return {
            "db_path": self.db_path,
            "exists": self.exists,
            "older_than_days": self.older_than_days,
            "dry_run": self.dry_run,
            "candidate_counts": dict(self.candidate_counts),
            "deleted_counts": dict(self.deleted_counts),
            "total_candidates": self.total_candidates,
            "total_deleted": self.total_deleted,
            "vacuumed": self.vacuumed,
        }


def resolve_cache_db_path(path: str | Path | None = None) -> Path:
    """Resolve the SQLite cache path without creating NOTEBOOKLM_HOME for reads."""
    if path is not None:
        return Path(path).expanduser().resolve()
    return get_home_dir() / DB_FILENAME


def load_cache_status(path: str | Path | None = None) -> CacheStatus:
    """Collect row counts, file sizes, and sync freshness details for the cache."""
    db_path = resolve_cache_db_path(path)
    table_counts = {table: 0 for table in MVP_TABLES}
    wal_path = _wal_path(db_path)

    if not db_path.exists():
        return CacheStatus(
            db_path=str(db_path),
            exists=False,
            table_counts=table_counts,
            db_size_bytes=0,
            wal_size_bytes=_file_size(wal_path),
        )

    with _open_existing_connection(db_path) as connection:
        existing_tables = _existing_tables(connection)
        for table in MVP_TABLES:
            if table not in existing_tables:
                continue
            row = connection.execute(f"SELECT COUNT(*) AS row_count FROM {table}").fetchone()
            table_counts[table] = int(row["row_count"])
        oldest_sync_timestamp, newest_sync_timestamp = _sync_bounds(connection, existing_tables)

    return CacheStatus(
        db_path=str(db_path),
        exists=True,
        table_counts=table_counts,
        db_size_bytes=_file_size(db_path),
        wal_size_bytes=_file_size(wal_path),
        oldest_sync_timestamp=oldest_sync_timestamp,
        newest_sync_timestamp=newest_sync_timestamp,
    )


def prune_cache(
    path: str | Path | None = None,
    *,
    older_than_days: int = 30,
    dry_run: bool = False,
) -> CachePruneResult:
    """Delete old cache rows, rotate aged run events, and compact when needed."""
    db_path = resolve_cache_db_path(path)
    candidate_counts = {table: 0 for table in (*_TOMBSTONE_TABLES, _EVENT_LOG_TABLE)}
    deleted_counts = {table: 0 for table in (*_TOMBSTONE_TABLES, _EVENT_LOG_TABLE)}

    if not db_path.exists():
        return CachePruneResult(
            db_path=str(db_path),
            exists=False,
            older_than_days=older_than_days,
            dry_run=dry_run,
            candidate_counts=candidate_counts,
            deleted_counts=deleted_counts,
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    vacuumed = False

    with _open_existing_connection(db_path) as connection:
        existing_tables = _existing_tables(connection)
        prunable_rows = _collect_prunable_rows(connection, existing_tables, cutoff)
        for table, rows in prunable_rows.items():
            candidate_counts[table] = len(rows)
        if _EVENT_LOG_TABLE in existing_tables:
            candidate_counts[_EVENT_LOG_TABLE] = count_run_events_before(
                connection,
                older_than=cutoff,
            )

        if not dry_run:
            for table in ("sources", "notebooks"):
                if table not in existing_tables:
                    continue
                row_ids = [row_id for row_id in prunable_rows[table]]
                if not row_ids:
                    continue
                id_column = _TOMBSTONE_TABLES[table]
                with connection:
                    connection.executemany(
                        f"DELETE FROM {table} WHERE {id_column} = ?",
                        [(row_id,) for row_id in row_ids],
                    )
                deleted_counts[table] = len(row_ids)
            if _EVENT_LOG_TABLE in existing_tables:
                deleted_counts[_EVENT_LOG_TABLE] = prune_run_events_before(
                    connection,
                    older_than=cutoff,
                )
            total_deleted = sum(deleted_counts.values())
            if total_deleted > 0:
                connection.commit()
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
                vacuumed = True

    return CachePruneResult(
        db_path=str(db_path),
        exists=True,
        older_than_days=older_than_days,
        dry_run=dry_run,
        candidate_counts=candidate_counts,
        deleted_counts=deleted_counts,
        total_candidates=sum(candidate_counts.values()),
        total_deleted=sum(deleted_counts.values()),
        vacuumed=vacuumed,
    )


def _open_existing_connection(db_path: Path) -> sqlite3.Connection:
    """Open an existing SQLite database with the standard local-cache pragmas."""
    return configure_connection(sqlite3.connect(db_path))


def _existing_tables(connection: sqlite3.Connection) -> set[str]:
    """Return the set of tables present in the target database."""
    return {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _sync_bounds(
    connection: sqlite3.Connection,
    existing_tables: set[str],
) -> tuple[str | None, str | None]:
    """Return the oldest/newest known sync timestamps across cache tables."""
    if not {"notebooks", "sources", "sync_runs"} & existing_tables:
        return None, None

    timestamps: list[datetime] = []
    for table_name, query in _SYNC_TIMESTAMP_QUERIES:
        if table_name not in existing_tables:
            continue
        for row in connection.execute(query).fetchall():
            parsed = _parse_timestamp(row["sync_ts"])
            if parsed is not None:
                timestamps.append(parsed)

    if not timestamps:
        return None, None

    return min(timestamps).isoformat(), max(timestamps).isoformat()


def _collect_prunable_rows(
    connection: sqlite3.Connection,
    existing_tables: set[str],
    cutoff: datetime,
) -> dict[str, list[str]]:
    """Find tombstoned row ids older than the cutoff for each prunable table."""
    prunable_rows = {table: [] for table in _TOMBSTONE_TABLES}
    for table, id_column in _TOMBSTONE_TABLES.items():
        if table not in existing_tables:
            continue
        rows = connection.execute(
            f"""
            SELECT {id_column} AS row_id, tombstoned_at
            FROM {table}
            WHERE tombstoned_at IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            tombstoned_at = _parse_timestamp(row["tombstoned_at"])
            if tombstoned_at is not None and tombstoned_at <= cutoff:
                prunable_rows[table].append(str(row["row_id"]))
    return prunable_rows


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse a stored ISO-8601 timestamp into a comparable UTC datetime."""
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _file_size(path: Path) -> int:
    """Return a file size in bytes, or zero when the file is absent."""
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _wal_path(db_path: Path) -> Path:
    """Return the SQLite WAL sidecar path for the given DB."""
    return db_path.with_name(f"{db_path.name}-wal")


__all__ = [
    "CachePruneResult",
    "CacheStatus",
    "load_cache_status",
    "prune_cache",
    "resolve_cache_db_path",
]
