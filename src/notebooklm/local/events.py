"""Helpers for working with the local run_events append-only log."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import secrets
import sqlite3
from typing import Any


CANONICAL_EVENT_KINDS = (
    "route.resolved",
    "cache.hit",
    "cache.miss",
    "sync.started",
    "sync.finished",
    "auth.refreshed",
    "transport.retry",
    "artifact.polled",
    "research.started",
    "research.polled",
    "research.completed",
    "research.imported",
    "source.deleted",
    "notebook.deleted",
    "approval.requested",
    "approval.resolved",
    "doctor.run.started",
    "doctor.check.completed",
    "doctor.repair.completed",
    "workspace.resolve.completed",
    "workspace.query.completed",
    "watch.run.completed",
    "change.detected",
    "delta.briefing.created",
    "inbox.item.created",
    "inbox.item.applied",
)
CANONICAL_EVENT_KIND_SET = frozenset(CANONICAL_EVENT_KINDS)
_CROCKFORD_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@dataclass(frozen=True)
class RunEvent:
    """Structured view of one run_events row."""

    event_id: str
    trace_id: str
    run_id: str | None
    kind: str
    ts: str
    payload: Any | None


def _normalize_timestamp(ts: datetime | None = None) -> datetime:
    """Return a UTC timestamp suitable for event storage."""
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _encode_crockford_base32(value: int, length: int) -> str:
    chars = ["0"] * length
    for index in range(length - 1, -1, -1):
        chars[index] = _CROCKFORD_BASE32[value & 31]
        value >>= 5
    return "".join(chars)


def generate_event_id(ts: datetime | None = None) -> str:
    """Generate an `evt_<ulid>` identifier using a stdlib-only ULID encoder."""
    timestamp = _normalize_timestamp(ts)
    timestamp_ms = int(timestamp.timestamp() * 1000)
    ulid_value = (timestamp_ms << 80) | secrets.randbits(80)
    return f"evt_{_encode_crockford_base32(ulid_value, 26)}"


def append_run_event(
    connection: sqlite3.Connection,
    trace_id: str,
    kind: str,
    *,
    run_id: str | None = None,
    payload: Any | None = None,
    event_id: str | None = None,
    ts: datetime | None = None,
) -> RunEvent:
    """Append one event to the local run_events log."""
    if kind not in CANONICAL_EVENT_KIND_SET:
        raise ValueError(f"Unknown run event kind: {kind}")

    timestamp = _normalize_timestamp(ts)
    persisted_ts = timestamp.isoformat()
    persisted_event_id = event_id or generate_event_id(timestamp)
    payload_json = (
        None
        if payload is None
        else json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )

    with connection:
        connection.execute(
            """
            INSERT INTO run_events(event_id, trace_id, run_id, kind, ts, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (persisted_event_id, trace_id, run_id, kind, persisted_ts, payload_json),
        )

    return RunEvent(
        event_id=persisted_event_id,
        trace_id=trace_id,
        run_id=run_id,
        kind=kind,
        ts=persisted_ts,
        payload=payload,
    )


def list_run_events(connection: sqlite3.Connection, trace_id: str) -> list[RunEvent]:
    """Fetch all events for one trace, ordered by timestamp then event_id."""
    rows = connection.execute(
        """
        SELECT event_id, trace_id, run_id, kind, ts, payload_json
        FROM run_events
        WHERE trace_id = ?
        ORDER BY ts ASC, event_id ASC
        """,
        (trace_id,),
    ).fetchall()

    return _rows_to_events(rows)


def tail_run_events(
    connection: sqlite3.Connection,
    *,
    limit: int = 20,
    after_ts: str | None = None,
    after_event_id: str | None = None,
) -> list[RunEvent]:
    """Fetch the most recent events, optionally only returning rows after a cursor."""
    sql = """
        SELECT event_id, trace_id, run_id, kind, ts, payload_json
        FROM run_events
    """
    params: list[object] = []

    if after_ts is not None and after_event_id is not None:
        sql += """
            WHERE ts > ?
               OR (ts = ? AND event_id > ?)
        """
        params.extend([after_ts, after_ts, after_event_id])

    sql += """
        ORDER BY ts DESC, event_id DESC
        LIMIT ?
    """
    params.append(limit)
    rows = connection.execute(sql, params).fetchall()
    return _rows_to_events(reversed(rows))


def count_run_events_before(
    connection: sqlite3.Connection,
    *,
    older_than: datetime,
) -> int:
    """Count persisted events older than the retention cutoff."""
    cutoff_ts = _normalize_timestamp(older_than).isoformat()
    row = connection.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM run_events
        WHERE ts < ?
        """,
        (cutoff_ts,),
    ).fetchone()
    return int(row["row_count"])


def prune_run_events_before(
    connection: sqlite3.Connection,
    *,
    older_than: datetime,
) -> int:
    """Delete persisted events older than the retention cutoff."""
    cutoff_ts = _normalize_timestamp(older_than).isoformat()
    with connection:
        cursor = connection.execute(
            """
            DELETE FROM run_events
            WHERE ts < ?
            """,
            (cutoff_ts,),
        )
    if cursor.rowcount == -1:
        return 0
    return max(0, cursor.rowcount)


def _rows_to_events(rows) -> list[RunEvent]:
    return [
        RunEvent(
            event_id=row["event_id"],
            trace_id=row["trace_id"],
            run_id=row["run_id"],
            kind=row["kind"],
            ts=row["ts"],
            payload=None
            if row["payload_json"] is None
            else json.loads(row["payload_json"]),
        )
        for row in rows
    ]


__all__ = [
    "CANONICAL_EVENT_KINDS",
    "CANONICAL_EVENT_KIND_SET",
    "RunEvent",
    "append_run_event",
    "count_run_events_before",
    "generate_event_id",
    "list_run_events",
    "prune_run_events_before",
    "tail_run_events",
]
