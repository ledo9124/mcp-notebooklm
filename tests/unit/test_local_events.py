"""Unit tests for the local run_events helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3

import pytest

from notebooklm.local.events import (
    CANONICAL_EVENT_KINDS,
    append_run_event,
    count_run_events_before,
    generate_event_id,
    list_run_events,
    prune_run_events_before,
    tail_run_events,
)
from notebooklm.local.schema import apply_schema_v1


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    with connection:
        apply_schema_v1(connection)
    return connection


def test_canonical_event_kinds_are_deduplicated_and_normalized():
    assert "approval.requested" in CANONICAL_EVENT_KINDS
    assert "approval.resolved" in CANONICAL_EVENT_KINDS
    assert "transport.retry" in CANONICAL_EVENT_KINDS
    assert "research.started" in CANONICAL_EVENT_KINDS
    assert "research.polled" in CANONICAL_EVENT_KINDS
    assert "research.completed" in CANONICAL_EVENT_KINDS
    assert "source.deleted" in CANONICAL_EVENT_KINDS
    assert "notebook.deleted" in CANONICAL_EVENT_KINDS
    assert "approval.granted" not in CANONICAL_EVENT_KINDS
    assert len(CANONICAL_EVENT_KINDS) == len(set(CANONICAL_EVENT_KINDS))


def test_generate_event_id_uses_evt_prefix_and_ulid_shape():
    event_id = generate_event_id(datetime(2026, 3, 15, tzinfo=timezone.utc))

    assert re.fullmatch(r"evt_[0-9A-HJKMNP-TV-Z]{26}", event_id)


def test_append_run_event_persists_and_queries_by_trace_id():
    connection = _connect()

    first = append_run_event(
        connection,
        "trc_alpha",
        "route.resolved",
        run_id="qr_01",
        payload={"mode": "ask"},
        ts=datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc),
    )
    second = append_run_event(
        connection,
        "trc_alpha",
        "cache.miss",
        payload={"entity": "notebooks"},
        ts=datetime(2026, 3, 15, 3, 1, tzinfo=timezone.utc),
    )
    append_run_event(
        connection,
        "trc_other",
        "sync.started",
        ts=datetime(2026, 3, 15, 3, 2, tzinfo=timezone.utc),
    )

    events = list_run_events(connection, "trc_alpha")

    assert [event.event_id for event in events] == [first.event_id, second.event_id]
    assert events[0].run_id == "qr_01"
    assert events[0].payload == {"mode": "ask"}
    assert events[1].payload == {"entity": "notebooks"}


def test_append_run_event_rejects_unknown_kind():
    connection = _connect()

    with pytest.raises(ValueError, match="Unknown run event kind"):
        append_run_event(connection, "trc_bad", "not-a-real-kind")


def test_tail_run_events_returns_recent_rows_and_supports_incremental_cursor():
    connection = _connect()

    first = append_run_event(
        connection,
        "trc_alpha",
        "route.resolved",
        ts=datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc),
    )
    second = append_run_event(
        connection,
        "trc_beta",
        "cache.hit",
        ts=datetime(2026, 3, 15, 3, 1, tzinfo=timezone.utc),
    )
    third = append_run_event(
        connection,
        "trc_gamma",
        "sync.started",
        ts=datetime(2026, 3, 15, 3, 2, tzinfo=timezone.utc),
    )

    recent = tail_run_events(connection, limit=2)
    incremental = tail_run_events(
        connection,
        limit=5,
        after_ts=second.ts,
        after_event_id=second.event_id,
    )

    assert [event.event_id for event in recent] == [second.event_id, third.event_id]
    assert [event.event_id for event in incremental] == [third.event_id]
    assert recent[0].trace_id == "trc_beta"
    assert incremental[0].kind == "sync.started"


def test_count_and_prune_run_events_before_cutoff():
    connection = _connect()
    cutoff = datetime(2026, 3, 15, 3, 1, tzinfo=timezone.utc)

    old_event = append_run_event(
        connection,
        "trc_old",
        "route.resolved",
        ts=datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc),
    )
    recent_event = append_run_event(
        connection,
        "trc_recent",
        "cache.hit",
        ts=datetime(2026, 3, 15, 3, 2, tzinfo=timezone.utc),
    )

    assert count_run_events_before(connection, older_than=cutoff) == 1
    assert prune_run_events_before(connection, older_than=cutoff) == 1
    assert count_run_events_before(connection, older_than=cutoff) == 0
    assert [event.event_id for event in tail_run_events(connection, limit=10)] == [recent_event.event_id]
    assert [event.event_id for event in list_run_events(connection, "trc_old")] == []
    assert [event.event_id for event in list_run_events(connection, "trc_recent")] == [
        recent_event.event_id
    ]
    assert old_event.event_id != recent_event.event_id
