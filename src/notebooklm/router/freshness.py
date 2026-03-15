"""Cache-mode enforcement helpers for the experimental NL router."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from typing import Literal

from notebooklm.contracts import Freshness, Intent
from notebooklm.sync import (
    NOTEBOOK_DETAIL_SCOPE,
    NOTEBOOK_INDEX_SCOPE,
    get_notebook_detail_freshness_seconds,
    get_notebook_index_freshness_seconds,
)

CacheMode = Literal["smart", "refresh", "offline", "network"]
MetadataScope = Literal["notebook_index", "notebook_detail"]

_SUPPORTED_INTENTS = frozenset(
    {
        Intent.LOCAL_METADATA,
        Intent.REMOTE_METADATA,
        Intent.QUERY,
        Intent.GENERATION,
        Intent.RESEARCH,
    }
)
_REMOTE_ONLY_INTENTS = frozenset(
    {
        Intent.REMOTE_METADATA,
        Intent.QUERY,
        Intent.GENERATION,
        Intent.RESEARCH,
    }
)


class CacheModeViolationError(ValueError):
    """Raised when a cache mode cannot satisfy the requested route."""


@dataclass(frozen=True)
class FreshnessSnapshot:
    """Latest notebook-index/detail cache ages for one routing decision."""

    profile_id: str
    notebook_id: str | None
    notebook_index_synced_at: str | None
    notebook_detail_synced_at: str | None
    notebook_index_age_s: int | None
    notebook_detail_age_s: int | None
    notebook_index_is_fresh: bool
    notebook_detail_is_fresh: bool | None

    def to_contract(self, *, used_cached_result: bool) -> Freshness:
        """Return the canonical freshness payload for this snapshot."""
        return Freshness(
            notebook_index_age_s=self.notebook_index_age_s,
            notebook_detail_age_s=self.notebook_detail_age_s,
            used_cached_result=used_cached_result,
        )


@dataclass(frozen=True)
class CacheModeDecision:
    """Resolved routing policy for one intent under a cache mode."""

    cache_mode: CacheMode
    source_of_truth: Literal["local_cache", "remote_http"]
    reason: str
    used_cached_result: bool
    should_sync_metadata: bool
    metadata_scope: MetadataScope | None
    freshness: Freshness


def normalize_cache_mode(value: str | None) -> CacheMode:
    """Normalize user input into one of the supported cache modes."""
    if value is None:
        return "smart"

    normalized = value.strip().casefold()
    if not normalized:
        return "smart"
    if normalized not in {"smart", "refresh", "offline", "network"}:
        raise ValueError(f"Unsupported cache mode: {value!r}")
    return normalized  # type: ignore[return-value]


def collect_freshness_snapshot(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    notebook_id: str | None = None,
    now: datetime | None = None,
    notebook_index_freshness_seconds: int | None = None,
    notebook_detail_freshness_seconds: int | None = None,
) -> FreshnessSnapshot:
    """Collect the latest index/detail freshness state for one profile."""
    resolved_now = _normalize_now(now)
    index_window = (
        notebook_index_freshness_seconds
        if notebook_index_freshness_seconds is not None
        else get_notebook_index_freshness_seconds()
    )
    detail_window = (
        notebook_detail_freshness_seconds
        if notebook_detail_freshness_seconds is not None
        else get_notebook_detail_freshness_seconds()
    )

    index_synced_at = _latest_completed_sync_timestamp(
        connection,
        profile_id=profile_id,
        scope=NOTEBOOK_INDEX_SCOPE,
        target_id=None,
    )
    detail_synced_at = (
        _latest_completed_sync_timestamp(
            connection,
            profile_id=profile_id,
            scope=NOTEBOOK_DETAIL_SCOPE,
            target_id=notebook_id,
        )
        if notebook_id is not None
        else None
    )

    index_age_s = _age_seconds(index_synced_at, now=resolved_now)
    detail_age_s = _age_seconds(detail_synced_at, now=resolved_now)

    return FreshnessSnapshot(
        profile_id=profile_id,
        notebook_id=notebook_id,
        notebook_index_synced_at=index_synced_at,
        notebook_detail_synced_at=detail_synced_at,
        notebook_index_age_s=index_age_s,
        notebook_detail_age_s=detail_age_s,
        notebook_index_is_fresh=index_age_s is not None and index_age_s <= index_window,
        notebook_detail_is_fresh=(
            None
            if notebook_id is None
            else detail_age_s is not None and detail_age_s <= detail_window
        ),
    )


def decide_cache_mode(
    intent: Intent,
    *,
    snapshot: FreshnessSnapshot,
    cache_mode: str | None = "smart",
    metadata_scope: MetadataScope | None = None,
) -> CacheModeDecision:
    """Resolve cache-mode policy for one routed intent."""
    if intent not in _SUPPORTED_INTENTS:
        raise ValueError(f"Unsupported routing intent: {intent.value}")

    resolved_cache_mode = normalize_cache_mode(cache_mode)
    _validate_metadata_scope(intent, snapshot=snapshot, metadata_scope=metadata_scope)

    if resolved_cache_mode == "offline":
        return _offline_decision(intent, snapshot=snapshot, metadata_scope=metadata_scope)
    if resolved_cache_mode == "network":
        return _network_decision(intent, snapshot=snapshot, metadata_scope=metadata_scope)
    if resolved_cache_mode == "refresh":
        return _refresh_decision(intent, snapshot=snapshot, metadata_scope=metadata_scope)
    return _smart_decision(intent, snapshot=snapshot, metadata_scope=metadata_scope)


def _offline_decision(
    intent: Intent,
    *,
    snapshot: FreshnessSnapshot,
    metadata_scope: MetadataScope | None,
) -> CacheModeDecision:
    if intent in _REMOTE_ONLY_INTENTS:
        raise CacheModeViolationError(
            f"offline mode does not allow remote {intent.value} requests."
        )

    assert metadata_scope is not None
    if not _scope_has_cached_snapshot(snapshot, metadata_scope):
        raise CacheModeViolationError(
            "offline mode requires cached "
            f"{_scope_label(metadata_scope)} data, but no completed "
            f"{_scope_label(metadata_scope)} sync exists."
        )

    reason = (
        "offline mode keeps LOCAL_METADATA on cached "
        f"{_scope_label(metadata_scope)} data only."
    )
    return _local_decision(
        cache_mode="offline",
        snapshot=snapshot,
        metadata_scope=metadata_scope,
        reason=reason,
    )


def _network_decision(
    intent: Intent,
    *,
    snapshot: FreshnessSnapshot,
    metadata_scope: MetadataScope | None,
) -> CacheModeDecision:
    if intent is Intent.LOCAL_METADATA:
        assert metadata_scope is not None
        return _sync_decision(
            cache_mode="network",
            snapshot=snapshot,
            metadata_scope=metadata_scope,
            reason=(
                "network mode bypasses the local "
                f"{_scope_label(metadata_scope)} cache and forces remote sync."
            ),
        )

    return _remote_decision(
        cache_mode="network",
        snapshot=snapshot,
        metadata_scope=metadata_scope if intent is Intent.REMOTE_METADATA else None,
        should_sync_metadata=intent is Intent.REMOTE_METADATA and metadata_scope is not None,
        reason=f"network mode always uses remote transport for {intent.value}.",
    )


def _refresh_decision(
    intent: Intent,
    *,
    snapshot: FreshnessSnapshot,
    metadata_scope: MetadataScope | None,
) -> CacheModeDecision:
    if intent is Intent.LOCAL_METADATA:
        assert metadata_scope is not None
        return _sync_decision(
            cache_mode="refresh",
            snapshot=snapshot,
            metadata_scope=metadata_scope,
            reason=(
                "refresh mode forces remote "
                f"{_scope_label(metadata_scope)} sync before serving metadata."
            ),
        )

    return _remote_decision(
        cache_mode="refresh",
        snapshot=snapshot,
        metadata_scope=metadata_scope if intent is Intent.REMOTE_METADATA else None,
        should_sync_metadata=intent is Intent.REMOTE_METADATA and metadata_scope is not None,
        reason=f"refresh mode keeps {intent.value} on remote transport.",
    )


def _smart_decision(
    intent: Intent,
    *,
    snapshot: FreshnessSnapshot,
    metadata_scope: MetadataScope | None,
) -> CacheModeDecision:
    if intent in {Intent.QUERY, Intent.GENERATION, Intent.RESEARCH}:
        return _remote_decision(
            cache_mode="smart",
            snapshot=snapshot,
            metadata_scope=None,
            should_sync_metadata=False,
            reason=f"smart mode still executes {intent.value} remotely.",
        )

    if intent is Intent.REMOTE_METADATA:
        return _remote_decision(
            cache_mode="smart",
            snapshot=snapshot,
            metadata_scope=metadata_scope,
            should_sync_metadata=metadata_scope is not None,
            reason="smart mode keeps REMOTE_METADATA requests on remote transport.",
        )

    assert metadata_scope is not None
    if _scope_is_fresh(snapshot, metadata_scope):
        return _local_decision(
            cache_mode="smart",
            snapshot=snapshot,
            metadata_scope=metadata_scope,
            reason=(
                "smart mode kept LOCAL_METADATA on the local "
                f"{_scope_label(metadata_scope)} cache because the latest sync is fresh."
            ),
        )

    status = _scope_status(snapshot, metadata_scope)
    return _sync_decision(
        cache_mode="smart",
        snapshot=snapshot,
        metadata_scope=metadata_scope,
        reason=(
            "smart mode escalated LOCAL_METADATA to remote "
            f"{_scope_label(metadata_scope)} sync because the cache is {status}."
        ),
    )


def _local_decision(
    *,
    cache_mode: CacheMode,
    snapshot: FreshnessSnapshot,
    metadata_scope: MetadataScope,
    reason: str,
) -> CacheModeDecision:
    return CacheModeDecision(
        cache_mode=cache_mode,
        source_of_truth="local_cache",
        reason=reason,
        used_cached_result=True,
        should_sync_metadata=False,
        metadata_scope=metadata_scope,
        freshness=snapshot.to_contract(used_cached_result=True),
    )


def _sync_decision(
    *,
    cache_mode: CacheMode,
    snapshot: FreshnessSnapshot,
    metadata_scope: MetadataScope,
    reason: str,
) -> CacheModeDecision:
    return CacheModeDecision(
        cache_mode=cache_mode,
        source_of_truth="remote_http",
        reason=reason,
        used_cached_result=False,
        should_sync_metadata=True,
        metadata_scope=metadata_scope,
        freshness=snapshot.to_contract(used_cached_result=False),
    )


def _remote_decision(
    *,
    cache_mode: CacheMode,
    snapshot: FreshnessSnapshot,
    metadata_scope: MetadataScope | None,
    should_sync_metadata: bool,
    reason: str,
) -> CacheModeDecision:
    return CacheModeDecision(
        cache_mode=cache_mode,
        source_of_truth="remote_http",
        reason=reason,
        used_cached_result=False,
        should_sync_metadata=should_sync_metadata,
        metadata_scope=metadata_scope,
        freshness=snapshot.to_contract(used_cached_result=False),
    )


def _validate_metadata_scope(
    intent: Intent,
    *,
    snapshot: FreshnessSnapshot,
    metadata_scope: MetadataScope | None,
) -> None:
    if intent is Intent.LOCAL_METADATA and metadata_scope is None:
        raise ValueError("metadata_scope is required for LOCAL_METADATA requests.")
    if metadata_scope == "notebook_detail" and snapshot.notebook_id is None:
        raise ValueError(
            "notebook_id is required when evaluating notebook_detail freshness."
        )


def _latest_completed_sync_timestamp(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    scope: str,
    target_id: str | None,
) -> str | None:
    if target_id is None:
        row = connection.execute(
            """
            SELECT ended_at
            FROM sync_runs
            WHERE profile_id = ?
              AND scope = ?
              AND target_id IS NULL
              AND status = 'completed'
            ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
            LIMIT 1
            """,
            (profile_id, scope),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT ended_at
            FROM sync_runs
            WHERE profile_id = ?
              AND scope = ?
              AND target_id = ?
              AND status = 'completed'
            ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
            LIMIT 1
            """,
            (profile_id, scope, target_id),
        ).fetchone()
    return None if row is None else row["ended_at"]


def _scope_is_fresh(snapshot: FreshnessSnapshot, metadata_scope: MetadataScope) -> bool:
    if metadata_scope == "notebook_index":
        return snapshot.notebook_index_is_fresh
    return bool(snapshot.notebook_detail_is_fresh)


def _scope_has_cached_snapshot(
    snapshot: FreshnessSnapshot,
    metadata_scope: MetadataScope,
) -> bool:
    if metadata_scope == "notebook_index":
        return snapshot.notebook_index_age_s is not None
    return snapshot.notebook_detail_age_s is not None


def _scope_status(snapshot: FreshnessSnapshot, metadata_scope: MetadataScope) -> str:
    if _scope_has_cached_snapshot(snapshot, metadata_scope):
        return "fresh" if _scope_is_fresh(snapshot, metadata_scope) else "stale"
    return "missing"


def _scope_label(metadata_scope: MetadataScope) -> str:
    return metadata_scope.replace("_", "-")


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _age_seconds(timestamp: str | None, *, now: datetime) -> int | None:
    if timestamp is None:
        return None

    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _parse_timestamp(value: str) -> datetime | None:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "CacheMode",
    "CacheModeDecision",
    "CacheModeViolationError",
    "FreshnessSnapshot",
    "MetadataScope",
    "collect_freshness_snapshot",
    "decide_cache_mode",
    "normalize_cache_mode",
]
