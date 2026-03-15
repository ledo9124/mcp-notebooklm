"""Source metadata sync helpers backed by the local SQLite cache."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import sqlite3

from notebooklm.local.repositories import SourceRecord, SourceRepository
from notebooklm.rpc.types import source_status_to_str
from notebooklm.types import Source, SourceType

DEFAULT_READY_SOURCE_FRESHNESS_SECONDS = 600
DEFAULT_PENDING_SOURCE_FRESHNESS_SECONDS = 15
SOURCE_READY_FRESHNESS_ENV = "NOTEBOOKLM_SOURCE_READY_FRESHNESS_SECONDS"
SOURCE_PENDING_FRESHNESS_ENV = "NOTEBOOKLM_SOURCE_PENDING_FRESHNESS_SECONDS"


@dataclass(frozen=True)
class SourceSyncResult:
    """Result metadata for one source reconciliation pass."""

    sources: list[SourceRecord]
    tombstoned_count: int


def list_active_cached_sources(
    connection: sqlite3.Connection,
    notebook_id: str,
    *,
    now: datetime | None = None,
    ready_freshness_seconds: int | None = None,
    pending_freshness_seconds: int | None = None,
) -> list[SourceRecord]:
    """Return non-tombstoned cached sources for one notebook."""

    resolved_now = _normalize_timestamp(now)
    resolved_ready_freshness = (
        ready_freshness_seconds
        if ready_freshness_seconds is not None
        else get_ready_source_freshness_seconds()
    )
    resolved_pending_freshness = (
        pending_freshness_seconds
        if pending_freshness_seconds is not None
        else get_pending_source_freshness_seconds()
    )
    repository = SourceRepository(connection)
    active_records: list[SourceRecord] = []
    for record in repository.list_for_notebook(notebook_id):
        if record.tombstoned_at is not None:
            continue
        freshness_state = _resolve_source_freshness_state(
            record,
            now=resolved_now,
            ready_freshness_seconds=resolved_ready_freshness,
            pending_freshness_seconds=resolved_pending_freshness,
        )
        if freshness_state != record.freshness_state:
            record = replace(record, freshness_state=freshness_state)
            repository.upsert(record)
        active_records.append(record)
    return sorted(active_records, key=lambda record: record.source_id)


def get_ready_source_freshness_seconds() -> int:
    return int(
        os.environ.get(
            SOURCE_READY_FRESHNESS_ENV,
            str(DEFAULT_READY_SOURCE_FRESHNESS_SECONDS),
        )
    )


def get_pending_source_freshness_seconds() -> int:
    return int(
        os.environ.get(
            SOURCE_PENDING_FRESHNESS_ENV,
            str(DEFAULT_PENDING_SOURCE_FRESHNESS_SECONDS),
        )
    )


def _normalize_timestamp(ts: datetime | None = None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _normalize_timestamp(parsed)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint_raw_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _timestamp_from_epoch_parts(value: object) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    try:
        return datetime.fromtimestamp(value[0]).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _resolve_source_freshness_state(
    record: SourceRecord,
    *,
    now: datetime,
    ready_freshness_seconds: int,
    pending_freshness_seconds: int,
) -> str:
    synced_at = _parse_timestamp(record.synced_at)
    if synced_at is None:
        return "unknown"

    freshness_window = ready_freshness_seconds
    if record.status in {"processing", "preparing"}:
        freshness_window = pending_freshness_seconds

    if now - synced_at <= timedelta(seconds=freshness_window):
        return "fresh"
    return "stale"


def _source_id_from_raw(raw_source: object) -> str:
    if not isinstance(raw_source, list) or not raw_source:
        raise ValueError(f"Invalid source entry in GET_NOTEBOOK response: {raw_source!r}")
    first = raw_source[0]
    if isinstance(first, list):
        if not first:
            raise ValueError(
                f"Invalid source identifier in GET_NOTEBOOK response: {raw_source!r}"
            )
        return str(first[0])
    return str(first)


def _source_record_from_raw(
    raw_source: object,
    *,
    notebook_id: str,
    profile_id: str,
    synced_at: str,
    existing: SourceRecord | None,
) -> SourceRecord:
    if not isinstance(raw_source, list) or not raw_source:
        raise ValueError(f"Invalid source entry in GET_NOTEBOOK response: {raw_source!r}")

    source_id = _source_id_from_raw(raw_source)
    title = raw_source[1] if len(raw_source) > 1 and isinstance(raw_source[1], str) else None

    metadata = raw_source[2] if len(raw_source) > 2 and isinstance(raw_source[2], list) else []
    url = None
    if len(metadata) > 7 and isinstance(metadata[7], list) and metadata[7]:
        first_url = metadata[7][0]
        if isinstance(first_url, str):
            url = first_url

    created_at = _timestamp_from_epoch_parts(metadata[2] if len(metadata) > 2 else None)
    updated_at = None
    if len(metadata) > 3 and isinstance(metadata[3], list) and len(metadata[3]) > 1:
        updated_at = _timestamp_from_epoch_parts(metadata[3][1])

    type_code = metadata[4] if len(metadata) > 4 and isinstance(metadata[4], int) else None
    status_code = None
    if len(raw_source) > 3 and isinstance(raw_source[3], list) and len(raw_source[3]) > 1:
        status_code = raw_source[3][1]

    parsed_source = Source(
        id=str(source_id),
        title=title,
        url=url,
        _type_code=type_code,
        created_at=datetime.fromisoformat(created_at) if created_at else None,
        status=status_code if isinstance(status_code, int) else 0,
    )

    drive_syncable = existing.drive_syncable if existing is not None else None
    if parsed_source.kind in {
        SourceType.GOOGLE_DOCS,
        SourceType.GOOGLE_SLIDES,
        SourceType.GOOGLE_SPREADSHEET,
        SourceType.GOOGLE_DRIVE_AUDIO,
        SourceType.GOOGLE_DRIVE_VIDEO,
    }:
        drive_syncable = True

    raw_json = _canonical_json(raw_source)
    return SourceRecord(
        source_id=str(source_id),
        notebook_id=notebook_id,
        profile_id=profile_id,
        source_type=parsed_source.kind.value,
        status=source_status_to_str(status_code) if isinstance(status_code, int) else "unknown",
        title=title,
        origin_uri=url,
        freshness_state=existing.freshness_state if existing is not None else None,
        drive_syncable=drive_syncable,
        content_preview=existing.content_preview if existing is not None else None,
        added_at_remote=created_at,
        updated_at_remote=updated_at,
        synced_at=synced_at,
        remote_fingerprint=_fingerprint_raw_payload(raw_source),
        tombstoned_at=None,
        raw_json=raw_json,
    )


def reconcile_sources(
    connection: sqlite3.Connection,
    *,
    notebook_id: str,
    profile_id: str,
    synced_at: str,
    raw_sources: list[object],
    now: datetime | None = None,
    ready_freshness_seconds: int | None = None,
    pending_freshness_seconds: int | None = None,
) -> SourceSyncResult:
    """Upsert source rows from notebook detail and tombstone missing ones."""

    resolved_now = (
        _normalize_timestamp(now)
        if now is not None
        else (_parse_timestamp(synced_at) or _normalize_timestamp())
    )
    repository = SourceRepository(connection)
    existing_sources = {
        record.source_id: record for record in repository.list_for_notebook(notebook_id)
    }
    remote_source_ids: set[str] = set()
    for raw_source in raw_sources:
        source_id = _source_id_from_raw(raw_source)
        source_record = _source_record_from_raw(
            raw_source,
            notebook_id=notebook_id,
            profile_id=profile_id,
            synced_at=synced_at,
            existing=existing_sources.get(source_id),
        )
        repository.upsert(source_record)
        remote_source_ids.add(source_record.source_id)

    tombstoned_count = 0
    for existing in existing_sources.values():
        if existing.source_id in remote_source_ids or existing.tombstoned_at is not None:
            continue
        repository.upsert(
            replace(
                existing,
                synced_at=synced_at,
                tombstoned_at=synced_at,
            )
        )
        tombstoned_count += 1

    return SourceSyncResult(
        sources=list_active_cached_sources(
            connection,
            notebook_id,
            now=resolved_now,
            ready_freshness_seconds=ready_freshness_seconds,
            pending_freshness_seconds=pending_freshness_seconds,
        ),
        tombstoned_count=tombstoned_count,
    )


__all__ = [
    "DEFAULT_PENDING_SOURCE_FRESHNESS_SECONDS",
    "DEFAULT_READY_SOURCE_FRESHNESS_SECONDS",
    "SourceSyncResult",
    "SOURCE_PENDING_FRESHNESS_ENV",
    "SOURCE_READY_FRESHNESS_ENV",
    "get_pending_source_freshness_seconds",
    "get_ready_source_freshness_seconds",
    "list_active_cached_sources",
    "reconcile_sources",
]
