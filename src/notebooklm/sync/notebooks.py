"""Notebook index sync helpers backed by the local SQLite cache."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from notebooklm.auth import load_auth_from_storage
from notebooklm.local.fingerprints import compute_notebook_fingerprint
from notebooklm.local.repositories import (
    ArtifactRecord,
    ArtifactRepository,
    NotebookRecord,
    NotebookRepository,
    SourceRecord,
    SyncRunRecord,
    SyncRunRepository,
)
from notebooklm.observability import current_trace, generate_trace_id
from notebooklm.profiles.manager import ProfileManager
from notebooklm.rpc.types import artifact_status_to_str
from notebooklm.types import Artifact, Notebook

from .sources import list_active_cached_sources, reconcile_sources


DEFAULT_NOTEBOOK_INDEX_FRESHNESS_SECONDS = 300
NOTEBOOK_INDEX_FRESHNESS_ENV = "NOTEBOOKLM_NOTEBOOK_INDEX_FRESHNESS_SECONDS"
NOTEBOOK_INDEX_SCOPE = "notebook_index"
NOTEBOOK_INDEX_TRIGGER = "notebook_list"
DEFAULT_NOTEBOOK_DETAIL_FRESHNESS_SECONDS = 120
NOTEBOOK_DETAIL_FRESHNESS_ENV = "NOTEBOOKLM_NOTEBOOK_DETAIL_FRESHNESS_SECONDS"
NOTEBOOK_DETAIL_SCOPE = "notebook_detail"
NOTEBOOK_DETAIL_TRIGGER = "notebook_show"


@dataclass(frozen=True)
class NotebookIndexState:
    """Result metadata for one notebook-index resolution."""

    notebooks: list[NotebookRecord]
    used_cache: bool
    synced_at: str | None
    sync_run_id: str | None = None


@dataclass(frozen=True)
class NotebookDetailState:
    """Result metadata for one notebook-detail resolution."""

    notebook: NotebookRecord
    sources: list[SourceRecord]
    artifacts: list[ArtifactRecord]
    used_cache: bool
    synced_at: str | None
    sync_run_id: str | None = None


def _normalize_timestamp(ts: datetime | None = None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _timestamp_text(ts: datetime | None = None) -> str:
    return _normalize_timestamp(ts).isoformat()


def _normalize_title(title: str) -> str:
    return " ".join(title.split()).casefold()


def _cookie_fingerprint(cookies: dict[str, str]) -> str:
    material = "\n".join(f"{name}={cookies[name]}" for name in sorted(cookies))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _current_auth_fingerprint(storage_path: str | Path | None) -> str | None:
    if storage_path is None and "NOTEBOOKLM_AUTH_JSON" not in os.environ:
        return None
    try:
        return _cookie_fingerprint(load_auth_from_storage(Path(storage_path) if storage_path else None))
    except (FileNotFoundError, ValueError):
        return None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_stats_json(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sync_run_id(ts: datetime | None = None) -> str:
    return f"sr_{generate_trace_id(ts).split('_', 1)[1]}"


def get_notebook_index_freshness_seconds() -> int:
    """Return the cache freshness window for notebook-index sync."""
    raw_value = os.environ.get(NOTEBOOK_INDEX_FRESHNESS_ENV)
    if raw_value is None:
        return DEFAULT_NOTEBOOK_INDEX_FRESHNESS_SECONDS

    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_NOTEBOOK_INDEX_FRESHNESS_SECONDS

    return value if value > 0 else DEFAULT_NOTEBOOK_INDEX_FRESHNESS_SECONDS


def get_notebook_detail_freshness_seconds() -> int:
    """Return the cache freshness window for notebook-detail sync."""
    raw_value = os.environ.get(NOTEBOOK_DETAIL_FRESHNESS_ENV)
    if raw_value is None:
        return DEFAULT_NOTEBOOK_DETAIL_FRESHNESS_SECONDS

    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_NOTEBOOK_DETAIL_FRESHNESS_SECONDS

    return value if value > 0 else DEFAULT_NOTEBOOK_DETAIL_FRESHNESS_SECONDS


def _resolve_profile_id(
    connection: sqlite3.Connection,
    *,
    storage_path: str | Path | None = None,
) -> str:
    manager = ProfileManager(connection)

    if storage_path is not None:
        resolved_storage_path = Path(storage_path).expanduser().resolve()
        for profile in manager.list_profiles():
            if profile.storage_state_path == resolved_storage_path:
                return profile.profile_id

    active_profile = manager.get_active_profile()
    if active_profile is not None:
        return active_profile.profile_id

    profiles = manager.list_profiles()
    if len(profiles) == 1:
        return profiles[0].profile_id

    raise LookupError("No active profile is available for notebook index sync")


def _list_active_cached_notebooks(
    connection: sqlite3.Connection,
    profile_id: str,
) -> list[NotebookRecord]:
    repository = NotebookRepository(connection)
    records = [
        record
        for record in repository.list_for_profile(profile_id)
        if record.tombstoned_at is None
    ]
    return sorted(records, key=lambda record: (record.normalized_title, record.notebook_id))


def _latest_completed_index_sync(
    connection: sqlite3.Connection,
    profile_id: str,
) -> tuple[datetime | None, dict[str, object]]:
    row = connection.execute(
        """
        SELECT ended_at, started_at, stats_json
        FROM sync_runs
        WHERE profile_id = ? AND scope = ? AND status = 'completed'
        ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
        LIMIT 1
        """,
        (profile_id, NOTEBOOK_INDEX_SCOPE),
    ).fetchone()
    if row is None:
        return None, {}
    return _parse_timestamp(row["ended_at"] or row["started_at"]), _parse_stats_json(row["stats_json"])


def _latest_completed_detail_sync(
    connection: sqlite3.Connection,
    profile_id: str,
    notebook_id: str,
) -> datetime | None:
    row = connection.execute(
        """
        SELECT ended_at, started_at
        FROM sync_runs
        WHERE profile_id = ?
          AND scope = ?
          AND target_id = ?
          AND status = 'completed'
        ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
        LIMIT 1
        """,
        (profile_id, NOTEBOOK_DETAIL_SCOPE, notebook_id),
    ).fetchone()
    if row is None:
        return None
    return _parse_timestamp(row["ended_at"] or row["started_at"])


def _is_index_fresh(
    connection: sqlite3.Connection,
    profile_id: str,
    *,
    now: datetime,
    freshness_seconds: int,
    auth_fingerprint: str | None = None,
) -> tuple[bool, str | None]:
    latest_sync, latest_stats = _latest_completed_index_sync(connection, profile_id)
    if latest_sync is None:
        return False, None
    if auth_fingerprint is not None and latest_stats.get("auth_fingerprint") != auth_fingerprint:
        return False, latest_sync.isoformat()
    age = now - latest_sync
    return age <= timedelta(seconds=freshness_seconds), latest_sync.isoformat()


def _is_detail_fresh(
    connection: sqlite3.Connection,
    profile_id: str,
    notebook_id: str,
    *,
    now: datetime,
    freshness_seconds: int,
) -> tuple[bool, str | None]:
    latest_sync = _latest_completed_detail_sync(connection, profile_id, notebook_id)
    if latest_sync is None:
        return False, None
    age = now - latest_sync
    return age <= timedelta(seconds=freshness_seconds), latest_sync.isoformat()


def _record_from_remote_notebook(
    notebook: Notebook,
    *,
    profile_id: str,
    synced_at: str,
    existing: NotebookRecord | None,
) -> NotebookRecord:
    created_at_remote = (
        notebook.created_at.isoformat()
        if notebook.created_at is not None
        else existing.created_at_remote if existing is not None else None
    )
    payload = {
        "id": notebook.id,
        "title": notebook.title,
        "created_at": created_at_remote,
        "sources_count": notebook.sources_count,
        "is_owner": notebook.is_owner,
    }
    return NotebookRecord(
        notebook_id=notebook.id,
        profile_id=profile_id,
        title=notebook.title,
        normalized_title=_normalize_title(notebook.title),
        is_owner=notebook.is_owner,
        share_visibility=existing.share_visibility if existing is not None else None,
        created_at_remote=created_at_remote,
        source_count=notebook.sources_count,
        artifact_count=existing.artifact_count if existing is not None else 0,
        note_count=existing.note_count if existing is not None else 0,
        summary_preview=existing.summary_preview if existing is not None else None,
        index_synced_at=synced_at,
        detail_synced_at=existing.detail_synced_at if existing is not None else None,
        remote_fingerprint=existing.remote_fingerprint if existing is not None else None,
        tombstoned_at=None,
        raw_json=json.dumps(payload, sort_keys=True),
    )


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


def _parse_detail_notebook_info(raw_detail: object) -> list[object]:
    if isinstance(raw_detail, list) and raw_detail and isinstance(raw_detail[0], list):
        return raw_detail[0]
    if isinstance(raw_detail, list):
        return raw_detail
    raise ValueError("Unexpected GET_NOTEBOOK response structure")


def _list_cached_artifacts(
    connection: sqlite3.Connection,
    notebook_id: str,
) -> list[ArtifactRecord]:
    repository = ArtifactRepository(connection)
    return sorted(repository.list_for_notebook(notebook_id), key=lambda record: record.artifact_id)


def _artifact_download_ref(raw_artifact: object) -> str | None:
    if not isinstance(raw_artifact, list) or len(raw_artifact) <= 6:
        return None
    media_block = raw_artifact[6]
    if not isinstance(media_block, list) or len(media_block) <= 5:
        return None
    media_list = media_block[5]
    if not isinstance(media_list, list) or not media_list:
        return None
    first_media = media_list[0]
    if not isinstance(first_media, list) or not first_media:
        return None
    return first_media[0] if isinstance(first_media[0], str) else None


def _artifact_record_from_raw(
    raw_artifact: object,
    *,
    notebook_id: str,
    profile_id: str,
    synced_at: str,
    existing: ArtifactRecord | None,
) -> ArtifactRecord:
    if not isinstance(raw_artifact, list) or not raw_artifact:
        raise ValueError(f"Invalid artifact entry in LIST_ARTIFACTS response: {raw_artifact!r}")

    parsed_artifact = Artifact.from_api_response(raw_artifact)
    raw_json = _canonical_json(raw_artifact)
    status = artifact_status_to_str(parsed_artifact.status)
    created_at = parsed_artifact.created_at.isoformat() if parsed_artifact.created_at else None
    requested_at = (
        existing.requested_at
        if existing is not None
        else created_at or synced_at
    )
    completed_at = (
        existing.completed_at
        if existing is not None and existing.completed_at is not None and status == "completed"
        else synced_at if status == "completed" else None
    )

    return ArtifactRecord(
        artifact_id=parsed_artifact.id,
        notebook_id=notebook_id,
        profile_id=profile_id,
        artifact_type=parsed_artifact.kind.value,
        submode=existing.submode if existing is not None else None,
        title=parsed_artifact.title,
        prompt_hash=existing.prompt_hash if existing is not None else None,
        status=status,
        requested_at=requested_at,
        last_polled_at=synced_at,
        completed_at=completed_at,
        download_ref=_artifact_download_ref(raw_artifact) or (
            existing.download_ref if existing is not None else None
        ),
        remote_fingerprint=_fingerprint_raw_payload(raw_artifact),
        raw_json=raw_json,
    )


async def sync_notebook_index(
    client,
    connection: sqlite3.Connection,
    *,
    profile_id: str | None = None,
    storage_path: str | Path | None = None,
    freshness_seconds: int | None = None,
    now: datetime | None = None,
    force_refresh: bool = False,
    trigger: str = NOTEBOOK_INDEX_TRIGGER,
) -> NotebookIndexState:
    """Return cached notebook rows when fresh, otherwise sync from remote."""
    resolved_now = _normalize_timestamp(now)
    resolved_profile_id = profile_id or _resolve_profile_id(
        connection,
        storage_path=storage_path,
    )
    current_auth_fingerprint = _current_auth_fingerprint(storage_path)
    freshness_window = (
        freshness_seconds
        if freshness_seconds is not None
        else get_notebook_index_freshness_seconds()
    )

    is_fresh, latest_synced_at = _is_index_fresh(
        connection,
        resolved_profile_id,
        now=resolved_now,
        freshness_seconds=freshness_window,
        auth_fingerprint=current_auth_fingerprint,
    )
    if is_fresh and not force_refresh:
        return NotebookIndexState(
            notebooks=_list_active_cached_notebooks(connection, resolved_profile_id),
            used_cache=True,
            synced_at=latest_synced_at,
        )

    trace = current_trace()
    trace_id = trace.trace_id if trace is not None else generate_trace_id(resolved_now)
    started_at = resolved_now.isoformat()
    run_id = _sync_run_id(resolved_now)
    sync_repository = SyncRunRepository(connection)
    sync_repository.upsert(
        SyncRunRecord(
            id=run_id,
            trace_id=trace_id,
            profile_id=resolved_profile_id,
            scope=NOTEBOOK_INDEX_SCOPE,
            target_id=None,
            trigger=trigger,
            started_at=started_at,
            ended_at=None,
            status="running",
            stats_json=None,
            error_text=None,
        )
    )

    notebook_repository = NotebookRepository(connection)
    try:
        remote_notebooks = await client.notebooks.list()
        synced_at = _timestamp_text(resolved_now)
        remote_ids = {notebook.id for notebook in remote_notebooks}

        for notebook in remote_notebooks:
            notebook_repository.upsert(
                _record_from_remote_notebook(
                    notebook,
                    profile_id=resolved_profile_id,
                    synced_at=synced_at,
                    existing=notebook_repository.get(notebook.id),
                )
            )

        tombstoned = 0
        for existing in notebook_repository.list_for_profile(resolved_profile_id):
            if existing.notebook_id in remote_ids or existing.tombstoned_at is not None:
                continue
            notebook_repository.upsert(
                replace(
                    existing,
                    index_synced_at=synced_at,
                    tombstoned_at=synced_at,
                )
            )
            tombstoned += 1

        active_notebooks = _list_active_cached_notebooks(connection, resolved_profile_id)
        stats = {
            "active_count": len(active_notebooks),
            "freshness_seconds": freshness_window,
            "remote_count": len(remote_notebooks),
            "tombstoned": tombstoned,
            "upserted": len(remote_notebooks),
        }
        if current_auth_fingerprint is not None:
            stats["auth_fingerprint"] = current_auth_fingerprint
        stats_json = json.dumps(stats, sort_keys=True)
        sync_repository.upsert(
            SyncRunRecord(
                id=run_id,
                trace_id=trace_id,
                profile_id=resolved_profile_id,
                scope=NOTEBOOK_INDEX_SCOPE,
                target_id=None,
                trigger=trigger,
                started_at=started_at,
                ended_at=synced_at,
                status="completed",
                stats_json=stats_json,
                error_text=None,
            )
        )
        return NotebookIndexState(
            notebooks=active_notebooks,
            used_cache=False,
            synced_at=synced_at,
            sync_run_id=run_id,
        )
    except Exception as exc:
        failed_at = _timestamp_text(resolved_now)
        sync_repository.upsert(
            SyncRunRecord(
                id=run_id,
                trace_id=trace_id,
                profile_id=resolved_profile_id,
                scope=NOTEBOOK_INDEX_SCOPE,
                target_id=None,
                trigger=trigger,
                started_at=started_at,
                ended_at=failed_at,
                status="failed",
                stats_json=None,
                error_text=str(exc),
            )
        )
        raise


async def sync_notebook_detail(
    client,
    connection: sqlite3.Connection,
    notebook_id: str,
    *,
    profile_id: str | None = None,
    storage_path: str | Path | None = None,
    freshness_seconds: int | None = None,
    now: datetime | None = None,
    force_refresh: bool = False,
    trigger: str = NOTEBOOK_DETAIL_TRIGGER,
) -> NotebookDetailState:
    """Return cached notebook detail when fresh, otherwise sync from remote."""
    resolved_now = _normalize_timestamp(now)
    resolved_profile_id = profile_id or _resolve_profile_id(
        connection,
        storage_path=storage_path,
    )
    freshness_window = (
        freshness_seconds
        if freshness_seconds is not None
        else get_notebook_detail_freshness_seconds()
    )

    is_fresh, latest_synced_at = _is_detail_fresh(
        connection,
        resolved_profile_id,
        notebook_id,
        now=resolved_now,
        freshness_seconds=freshness_window,
    )
    notebook_repository = NotebookRepository(connection)
    cached_notebook = notebook_repository.get(notebook_id)
    if is_fresh and not force_refresh and cached_notebook is not None:
        return NotebookDetailState(
            notebook=cached_notebook,
            sources=list_active_cached_sources(connection, notebook_id, now=resolved_now),
            artifacts=_list_cached_artifacts(connection, notebook_id),
            used_cache=True,
            synced_at=latest_synced_at,
        )

    trace = current_trace()
    trace_id = trace.trace_id if trace is not None else generate_trace_id(resolved_now)
    started_at = resolved_now.isoformat()
    run_id = _sync_run_id(resolved_now)
    sync_repository = SyncRunRepository(connection)
    sync_repository.upsert(
        SyncRunRecord(
            id=run_id,
            trace_id=trace_id,
            profile_id=resolved_profile_id,
            scope=NOTEBOOK_DETAIL_SCOPE,
            target_id=notebook_id,
            trigger=trigger,
            started_at=started_at,
            ended_at=None,
            status="running",
            stats_json=None,
            error_text=None,
        )
    )

    artifact_repository = ArtifactRepository(connection)
    try:
        raw_detail = await client.notebooks.get_raw(notebook_id)
        notebook_info = _parse_detail_notebook_info(raw_detail)
        remote_notebook = Notebook.from_api_response(notebook_info)
        synced_at = _timestamp_text(resolved_now)
        existing_notebook = notebook_repository.get(notebook_id)
        notebook_repository.upsert(
            NotebookRecord(
                notebook_id=notebook_id,
                profile_id=resolved_profile_id,
                title=remote_notebook.title,
                normalized_title=_normalize_title(remote_notebook.title),
                is_owner=remote_notebook.is_owner,
                share_visibility=existing_notebook.share_visibility if existing_notebook else None,
                created_at_remote=(
                    remote_notebook.created_at.isoformat()
                    if remote_notebook.created_at is not None
                    else existing_notebook.created_at_remote if existing_notebook else None
                ),
                source_count=existing_notebook.source_count if existing_notebook else 0,
                artifact_count=existing_notebook.artifact_count if existing_notebook else 0,
                note_count=existing_notebook.note_count if existing_notebook else 0,
                summary_preview=existing_notebook.summary_preview if existing_notebook else None,
                index_synced_at=existing_notebook.index_synced_at if existing_notebook else None,
                detail_synced_at=synced_at,
                remote_fingerprint=existing_notebook.remote_fingerprint if existing_notebook else None,
                tombstoned_at=None,
                raw_json=_canonical_json(raw_detail),
            )
        )

        raw_sources = notebook_info[1] if len(notebook_info) > 1 and isinstance(notebook_info[1], list) else []
        source_sync = reconcile_sources(
            connection,
            notebook_id=notebook_id,
            profile_id=resolved_profile_id,
            synced_at=synced_at,
            raw_sources=raw_sources,
            now=resolved_now,
        )

        raw_artifacts = await client.artifacts._list_raw(notebook_id)
        existing_artifacts = {
            record.artifact_id: record for record in artifact_repository.list_for_notebook(notebook_id)
        }
        remote_artifact_ids: set[str] = set()
        for raw_artifact in raw_artifacts:
            artifact_id = raw_artifact[0] if isinstance(raw_artifact, list) and raw_artifact else None
            artifact_record = _artifact_record_from_raw(
                raw_artifact,
                notebook_id=notebook_id,
                profile_id=resolved_profile_id,
                synced_at=synced_at,
                existing=existing_artifacts.get(str(artifact_id)),
            )
            artifact_repository.upsert(artifact_record)
            remote_artifact_ids.add(artifact_record.artifact_id)

        deleted_artifacts = 0
        for existing in existing_artifacts.values():
            if existing.artifact_id in remote_artifact_ids:
                continue
            artifact_repository.delete(existing.artifact_id)
            deleted_artifacts += 1

        sources = source_sync.sources
        existing_notebook = notebook_repository.get(notebook_id)
        notebook_repository.upsert(
            NotebookRecord(
                notebook_id=notebook_id,
                profile_id=resolved_profile_id,
                title=remote_notebook.title,
                normalized_title=_normalize_title(remote_notebook.title),
                is_owner=remote_notebook.is_owner,
                share_visibility=existing_notebook.share_visibility if existing_notebook else None,
                created_at_remote=(
                    remote_notebook.created_at.isoformat()
                    if remote_notebook.created_at is not None
                    else existing_notebook.created_at_remote if existing_notebook else None
                ),
                source_count=len(sources),
                artifact_count=len(remote_artifact_ids),
                note_count=existing_notebook.note_count if existing_notebook else 0,
                summary_preview=existing_notebook.summary_preview if existing_notebook else None,
                index_synced_at=existing_notebook.index_synced_at if existing_notebook else None,
                detail_synced_at=synced_at,
                remote_fingerprint=existing_notebook.remote_fingerprint if existing_notebook else None,
                tombstoned_at=None,
                raw_json=_canonical_json(raw_detail),
            )
        )

        artifacts = _list_cached_artifacts(connection, notebook_id)
        notebook = notebook_repository.get(notebook_id)
        if notebook is None:
            raise LookupError(f"unknown notebook after detail sync: {notebook_id}")
        notebook = replace(
            notebook,
            remote_fingerprint=compute_notebook_fingerprint(
                notebook,
                sources=sources,
                artifacts=artifacts,
            ),
        )
        notebook_repository.upsert(notebook)
        stats_json = json.dumps(
            {
                "artifact_count": len(artifacts),
                "deleted_artifacts": deleted_artifacts,
                "freshness_seconds": freshness_window,
                "source_count": len(sources),
                "tombstoned_sources": source_sync.tombstoned_count,
            },
            sort_keys=True,
        )
        sync_repository.upsert(
            SyncRunRecord(
                id=run_id,
                trace_id=trace_id,
                profile_id=resolved_profile_id,
                scope=NOTEBOOK_DETAIL_SCOPE,
                target_id=notebook_id,
                trigger=trigger,
                started_at=started_at,
                ended_at=synced_at,
                status="completed",
                stats_json=stats_json,
                error_text=None,
            )
        )
        return NotebookDetailState(
            notebook=notebook,
            sources=sources,
            artifacts=artifacts,
            used_cache=False,
            synced_at=synced_at,
            sync_run_id=run_id,
        )
    except Exception as exc:
        failed_at = _timestamp_text(resolved_now)
        sync_repository.upsert(
            SyncRunRecord(
                id=run_id,
                trace_id=trace_id,
                profile_id=resolved_profile_id,
                scope=NOTEBOOK_DETAIL_SCOPE,
                target_id=notebook_id,
                trigger=trigger,
                started_at=started_at,
                ended_at=failed_at,
                status="failed",
                stats_json=None,
                error_text=str(exc),
            )
        )
        raise


__all__ = [
    "DEFAULT_NOTEBOOK_DETAIL_FRESHNESS_SECONDS",
    "DEFAULT_NOTEBOOK_INDEX_FRESHNESS_SECONDS",
    "NOTEBOOK_DETAIL_FRESHNESS_ENV",
    "NOTEBOOK_DETAIL_SCOPE",
    "NOTEBOOK_DETAIL_TRIGGER",
    "NOTEBOOK_INDEX_FRESHNESS_ENV",
    "NOTEBOOK_INDEX_SCOPE",
    "NOTEBOOK_INDEX_TRIGGER",
    "NotebookDetailState",
    "NotebookIndexState",
    "get_notebook_detail_freshness_seconds",
    "get_notebook_index_freshness_seconds",
    "sync_notebook_detail",
    "sync_notebook_index",
]
