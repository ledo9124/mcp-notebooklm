"""Helpers for invalidating local metadata sync state after remote mutations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from notebooklm.local.repositories import (
    ArtifactRecord,
    ArtifactRepository,
    NotebookRecord,
    NotebookRepository,
)
from notebooklm.paths import get_browser_profile_dir
from notebooklm.profiles.manager import ProfileManager

from .notebooks import NOTEBOOK_DETAIL_SCOPE, NOTEBOOK_INDEX_SCOPE


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


def _ensure_profile_id(
    connection: sqlite3.Connection,
    *,
    profile_id: str | None = None,
    storage_path: str | Path | None = None,
) -> str:
    manager = ProfileManager(connection)

    if profile_id is not None:
        profile = manager.get_profile(profile_id)
        if profile is not None:
            return profile.profile_id
        if storage_path is None:
            raise LookupError(f"Unknown profile: {profile_id}")
        return _create_profile_for_storage(
            manager,
            profile_id=profile_id,
            storage_path=storage_path,
        )

    if storage_path is not None:
        resolved_storage_path = Path(storage_path).expanduser().resolve()
        for profile in manager.list_profiles():
            if profile.storage_state_path == resolved_storage_path:
                return profile.profile_id
        return _create_profile_for_storage(manager, storage_path=resolved_storage_path)

    active_profile = manager.get_active_profile()
    if active_profile is not None:
        return active_profile.profile_id

    profiles = manager.list_profiles()
    if len(profiles) == 1:
        return profiles[0].profile_id

    raise LookupError("No active profile is available for cache invalidation")


def _create_profile_for_storage(
    manager: ProfileManager,
    *,
    storage_path: str | Path,
    profile_id: str | None = None,
) -> str:
    existing_profiles = manager.list_profiles()
    profile_count = len(existing_profiles)
    resolved_profile_id = profile_id or ("default" if profile_count == 0 else f"profile_{profile_count + 1}")
    display_name = "Default" if resolved_profile_id == "default" else f"Profile {profile_count + 1}"
    profile = manager.create_profile(
        profile_id=resolved_profile_id,
        display_name=display_name,
        storage_state_path=storage_path,
        browser_profile_path=get_browser_profile_dir(),
        is_default=profile_count == 0,
    )
    return profile.profile_id


def _invalidate_completed_sync_runs(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    scope: str,
    target_id: str | None,
    reason: str,
) -> int:
    params: list[object] = [reason, profile_id, scope]
    target_clause = ""
    if target_id is not None:
        target_clause = " AND target_id = ?"
        params.append(target_id)
    cursor = connection.execute(
        f"""
        UPDATE sync_runs
        SET status = 'cancelled',
            error_text = COALESCE(error_text, ?)
        WHERE profile_id = ?
          AND scope = ?
          AND status = 'completed'
          {target_clause}
        """,
        params,
    )
    return cursor.rowcount


def invalidate_notebook_index(
    connection: sqlite3.Connection,
    *,
    profile_id: str | None = None,
    storage_path: str | Path | None = None,
    reason: str = "notebook.create",
) -> int:
    """Invalidate cached notebook-index freshness for the resolved profile."""
    resolved_profile_id = _ensure_profile_id(
        connection,
        profile_id=profile_id,
        storage_path=storage_path,
    )
    notebook_repository = NotebookRepository(connection)
    with connection:
        for notebook in notebook_repository.list_for_profile(resolved_profile_id):
            if notebook.index_synced_at is None:
                continue
            notebook_repository.upsert(replace(notebook, index_synced_at=None))
        return _invalidate_completed_sync_runs(
            connection,
            profile_id=resolved_profile_id,
            scope=NOTEBOOK_INDEX_SCOPE,
            target_id=None,
            reason=reason,
        )


def invalidate_notebook_detail(
    connection: sqlite3.Connection,
    notebook_id: str,
    *,
    profile_id: str | None = None,
    storage_path: str | Path | None = None,
    reason: str = "notebook.detail_mutation",
) -> int:
    """Invalidate cached notebook-detail freshness for a single notebook."""
    resolved_profile_id = _ensure_profile_id(
        connection,
        profile_id=profile_id,
        storage_path=storage_path,
    )
    notebook_repository = NotebookRepository(connection)
    with connection:
        notebook = notebook_repository.get(notebook_id)
        if notebook is not None:
            notebook_repository.upsert(
                replace(
                    notebook,
                    detail_synced_at=None,
                    remote_fingerprint=None,
                )
            )
        return _invalidate_completed_sync_runs(
            connection,
            profile_id=resolved_profile_id,
            scope=NOTEBOOK_DETAIL_SCOPE,
            target_id=notebook_id,
            reason=reason,
        )


def seed_pending_artifact(
    connection: sqlite3.Connection,
    notebook_id: str,
    artifact_id: str,
    *,
    artifact_type: str,
    profile_id: str | None = None,
    storage_path: str | Path | None = None,
    requested_at: datetime | None = None,
    title: str | None = None,
    submode: str | None = None,
    prompt_hash: str | None = None,
) -> ArtifactRecord:
    """Persist a pending artifact row so local detail views can reflect creation."""
    resolved_profile_id = _ensure_profile_id(
        connection,
        profile_id=profile_id,
        storage_path=storage_path,
    )
    notebook_repository = NotebookRepository(connection)
    artifact_repository = ArtifactRepository(connection)
    with connection:
        notebook = notebook_repository.get(notebook_id)
        if notebook is None:
            placeholder_title = notebook_id
            notebook_repository.upsert(
                NotebookRecord(
                    notebook_id=notebook_id,
                    profile_id=resolved_profile_id,
                    title=placeholder_title,
                    normalized_title=_normalize_title(placeholder_title),
                )
            )
        record = ArtifactRecord(
            artifact_id=artifact_id,
            notebook_id=notebook_id,
            profile_id=resolved_profile_id,
            artifact_type=artifact_type,
            submode=submode,
            title=title,
            prompt_hash=prompt_hash,
            status="pending",
            requested_at=_timestamp_text(requested_at),
            last_polled_at=None,
            completed_at=None,
            download_ref=None,
            remote_fingerprint=None,
            raw_json=None,
        )
        artifact_repository.upsert(record)
    return record


__all__ = [
    "invalidate_notebook_detail",
    "invalidate_notebook_index",
    "seed_pending_artifact",
]
