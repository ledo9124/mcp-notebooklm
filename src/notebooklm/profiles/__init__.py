"""Profile persistence helpers for local NotebookLM state."""

from .legacy import (
    LEGACY_DEFAULT_PROFILE_ID,
    LEGACY_DEFAULT_PROFILE_NAME,
    LEGACY_SNAPSHOT_SOURCE,
    LEGACY_SNAPSHOT_STATUS,
    LegacyImportResult,
    bootstrap_legacy_profile,
    has_legacy_profile_layout,
)
from .manager import AuthSnapshotRecord, ProfileManager, ProfileRecord

__all__ = [
    "AuthSnapshotRecord",
    "LEGACY_DEFAULT_PROFILE_ID",
    "LEGACY_DEFAULT_PROFILE_NAME",
    "LEGACY_SNAPSHOT_SOURCE",
    "LEGACY_SNAPSHOT_STATUS",
    "LegacyImportResult",
    "ProfileManager",
    "ProfileRecord",
    "bootstrap_legacy_profile",
    "has_legacy_profile_layout",
]
