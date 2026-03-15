"""Legacy NOTEBOOKLM_HOME bootstrap for the profile-backed local cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3

from notebooklm.auth import load_auth_from_storage
from notebooklm.paths import get_browser_profile_dir, get_context_path, get_storage_path

from notebooklm.local.schema import APP_STATE_SINGLETON_KEY

from .manager import ProfileManager


logger = logging.getLogger(__name__)

LEGACY_DEFAULT_PROFILE_ID = "default"
LEGACY_DEFAULT_PROFILE_NAME = "Default"
LEGACY_SNAPSHOT_SOURCE = "legacy_import"
LEGACY_SNAPSHOT_STATUS = "legacy_imported"


@dataclass(frozen=True)
class LegacyImportResult:
    """Outcome of the one-time legacy NOTEBOOKLM_HOME import."""

    detected: bool
    profile_created: bool
    snapshot_imported: bool
    context_imported: bool


def has_legacy_profile_layout() -> bool:
    """Return True when the pre-profile NOTEBOOKLM_HOME layout is present."""
    return get_storage_path().is_file() and get_browser_profile_dir().is_dir()


def bootstrap_legacy_profile(connection: sqlite3.Connection) -> LegacyImportResult:
    """Import the legacy NOTEBOOKLM_HOME layout into the profile tables once."""
    if not has_legacy_profile_layout():
        return LegacyImportResult(False, False, False, False)

    manager = ProfileManager(connection)
    if manager.list_profiles():
        return LegacyImportResult(True, False, False, False)

    storage_path = get_storage_path()
    browser_profile_dir = get_browser_profile_dir()
    profile = manager.create_profile(
        profile_id=LEGACY_DEFAULT_PROFILE_ID,
        display_name=LEGACY_DEFAULT_PROFILE_NAME,
        storage_state_path=storage_path,
        browser_profile_path=browser_profile_dir,
        is_default=True,
    )
    manager.switch_profile(profile.profile_id)

    snapshot_imported = _import_legacy_auth_snapshot(manager, storage_path)
    context_imported = _import_legacy_context(connection)
    return LegacyImportResult(True, True, snapshot_imported, context_imported)


def _import_legacy_auth_snapshot(manager: ProfileManager, storage_path: Path) -> bool:
    """Import the persisted cookie state into auth_snapshots when possible."""
    try:
        cookies = load_auth_from_storage(storage_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.debug("Skipping legacy auth snapshot import from %s: %s", storage_path, exc)
        return False

    build_label = ""
    try:
        storage_state = json.loads(storage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Skipping legacy build-label import from %s: %s", storage_path, exc)
    else:
        build_label = str(storage_state.get("bl", "") or "")

    manager.upsert_auth_snapshot(
        LEGACY_DEFAULT_PROFILE_ID,
        cookie_fingerprint=_cookie_fingerprint(cookies),
        csrf_token="",
        session_id="",
        build_label=build_label,
        captured_at=_file_timestamp(storage_path),
        validated_at=None,
        status=LEGACY_SNAPSHOT_STATUS,
        source=LEGACY_SNAPSHOT_SOURCE,
    )
    return True


def _import_legacy_context(connection: sqlite3.Connection) -> bool:
    """Import the legacy context.json notebook/conversation selection."""
    context_path = get_context_path()
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False

    with connection:
        connection.execute(
            """
            UPDATE app_state
            SET current_notebook_id = ?, current_conversation_id = ?
            WHERE singleton_key = ?
            """,
            (
                context.get("notebook_id"),
                context.get("conversation_id"),
                APP_STATE_SINGLETON_KEY,
            ),
        )
    return True


def _cookie_fingerprint(cookies: dict[str, str]) -> str:
    """Create a deterministic fingerprint without storing raw cookie values separately."""
    material = "\n".join(f"{name}={cookies[name]}" for name in sorted(cookies))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _file_timestamp(path: Path) -> str:
    """Use the legacy file mtime as the snapshot capture timestamp when available."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return datetime.now(timezone.utc).isoformat()


__all__ = [
    "LEGACY_DEFAULT_PROFILE_ID",
    "LEGACY_DEFAULT_PROFILE_NAME",
    "LEGACY_SNAPSHOT_SOURCE",
    "LEGACY_SNAPSHOT_STATUS",
    "LegacyImportResult",
    "bootstrap_legacy_profile",
    "has_legacy_profile_layout",
]
