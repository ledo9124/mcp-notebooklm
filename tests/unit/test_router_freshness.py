"""Focused tests for the router cache-mode enforcement helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from notebooklm.contracts import Intent
from notebooklm.local.db import configure_connection
from notebooklm.local.migrations import run_default_migrations
from notebooklm.local.repositories import SyncRunRecord, SyncRunRepository
from notebooklm.profiles.manager import ProfileManager
from notebooklm.router.freshness import (
    CacheModeViolationError,
    collect_freshness_snapshot,
    decide_cache_mode,
    normalize_cache_mode,
)
from notebooklm.sync import NOTEBOOK_DETAIL_SCOPE, NOTEBOOK_INDEX_SCOPE


def _connect() -> sqlite3.Connection:
    connection = configure_connection(sqlite3.connect(":memory:"))
    run_default_migrations(connection)
    manager = ProfileManager(connection)
    manager.create_profile(
        profile_id="default",
        display_name="Default",
        storage_state_path="/tmp/storage.json",
        browser_profile_path="/tmp/browser-profile",
        is_default=True,
    )
    manager.switch_profile("default")
    return connection


def _seed_sync(
    connection: sqlite3.Connection,
    *,
    scope: str,
    ended_at: datetime,
    target_id: str | None = None,
) -> None:
    normalized = ended_at.astimezone(timezone.utc)
    run_id = f"sr_{scope}_{target_id or 'root'}_{normalized:%H%M%S}"
    SyncRunRepository(connection).upsert(
        SyncRunRecord(
            id=run_id,
            trace_id=f"trc_{run_id}",
            profile_id="default",
            scope=scope,
            target_id=target_id,
            trigger="test",
            started_at=(normalized - timedelta(seconds=5)).isoformat(),
            ended_at=normalized.isoformat(),
            status="completed",
            stats_json=None,
            error_text=None,
        )
    )


def test_collect_freshness_snapshot_reports_cache_ages_and_flags():
    connection = _connect()
    now = datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc)
    _seed_sync(
        connection,
        scope=NOTEBOOK_INDEX_SCOPE,
        ended_at=now - timedelta(minutes=2),
    )
    _seed_sync(
        connection,
        scope=NOTEBOOK_DETAIL_SCOPE,
        target_id="nb_alpha",
        ended_at=now - timedelta(seconds=90),
    )

    snapshot = collect_freshness_snapshot(
        connection,
        profile_id="default",
        notebook_id="nb_alpha",
        now=now,
    )

    assert snapshot.notebook_index_age_s == 120
    assert snapshot.notebook_detail_age_s == 90
    assert snapshot.notebook_index_is_fresh is True
    assert snapshot.notebook_detail_is_fresh is True


def test_decide_cache_mode_smart_uses_fresh_local_metadata_cache():
    connection = _connect()
    now = datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc)
    _seed_sync(
        connection,
        scope=NOTEBOOK_DETAIL_SCOPE,
        target_id="nb_alpha",
        ended_at=now - timedelta(seconds=30),
    )

    snapshot = collect_freshness_snapshot(
        connection,
        profile_id="default",
        notebook_id="nb_alpha",
        now=now,
    )
    decision = decide_cache_mode(
        Intent.LOCAL_METADATA,
        snapshot=snapshot,
        cache_mode="smart",
        metadata_scope="notebook_detail",
    )

    assert decision.source_of_truth == "local_cache"
    assert decision.used_cached_result is True
    assert decision.should_sync_metadata is False
    assert decision.metadata_scope == "notebook_detail"
    assert decision.freshness.used_cached_result is True


def test_decide_cache_mode_smart_escalates_stale_local_metadata():
    connection = _connect()
    now = datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc)
    _seed_sync(
        connection,
        scope=NOTEBOOK_DETAIL_SCOPE,
        target_id="nb_alpha",
        ended_at=now - timedelta(minutes=5),
    )

    snapshot = collect_freshness_snapshot(
        connection,
        profile_id="default",
        notebook_id="nb_alpha",
        now=now,
    )
    decision = decide_cache_mode(
        Intent.LOCAL_METADATA,
        snapshot=snapshot,
        cache_mode="smart",
        metadata_scope="notebook_detail",
    )

    assert decision.source_of_truth == "remote_http"
    assert decision.used_cached_result is False
    assert decision.should_sync_metadata is True
    assert decision.metadata_scope == "notebook_detail"
    assert "stale" in decision.reason


@pytest.mark.parametrize("cache_mode", ["refresh", "network"])
def test_decide_cache_mode_forced_remote_modes_sync_metadata(cache_mode):
    connection = _connect()
    now = datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc)
    _seed_sync(
        connection,
        scope=NOTEBOOK_INDEX_SCOPE,
        ended_at=now - timedelta(seconds=10),
    )

    snapshot = collect_freshness_snapshot(
        connection,
        profile_id="default",
        now=now,
    )
    decision = decide_cache_mode(
        Intent.LOCAL_METADATA,
        snapshot=snapshot,
        cache_mode=cache_mode,
        metadata_scope="notebook_index",
    )

    assert decision.source_of_truth == "remote_http"
    assert decision.used_cached_result is False
    assert decision.should_sync_metadata is True
    assert decision.metadata_scope == "notebook_index"


def test_decide_cache_mode_smart_keeps_query_remote():
    connection = _connect()
    now = datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc)
    _seed_sync(
        connection,
        scope=NOTEBOOK_DETAIL_SCOPE,
        target_id="nb_alpha",
        ended_at=now - timedelta(seconds=15),
    )

    snapshot = collect_freshness_snapshot(
        connection,
        profile_id="default",
        notebook_id="nb_alpha",
        now=now,
    )
    decision = decide_cache_mode(
        Intent.QUERY,
        snapshot=snapshot,
        cache_mode="smart",
    )

    assert decision.source_of_truth == "remote_http"
    assert decision.used_cached_result is False
    assert decision.should_sync_metadata is False
    assert decision.metadata_scope is None


@pytest.mark.parametrize(
    "intent",
    [
        Intent.REMOTE_METADATA,
        Intent.QUERY,
        Intent.GENERATION,
        Intent.RESEARCH,
    ],
)
def test_decide_cache_mode_offline_rejects_remote_intents(intent):
    snapshot = collect_freshness_snapshot(
        _connect(),
        profile_id="default",
        notebook_id="nb_alpha",
        now=datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(CacheModeViolationError, match="offline mode does not allow remote"):
        decide_cache_mode(intent, snapshot=snapshot, cache_mode="offline")


def test_decide_cache_mode_offline_requires_cached_metadata():
    snapshot = collect_freshness_snapshot(
        _connect(),
        profile_id="default",
        now=datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(CacheModeViolationError, match="requires cached notebook-index data"):
        decide_cache_mode(
            Intent.LOCAL_METADATA,
            snapshot=snapshot,
            cache_mode="offline",
            metadata_scope="notebook_index",
        )


def test_decide_cache_mode_offline_allows_stale_cached_metadata():
    connection = _connect()
    now = datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc)
    _seed_sync(
        connection,
        scope=NOTEBOOK_INDEX_SCOPE,
        ended_at=now - timedelta(hours=1),
    )

    snapshot = collect_freshness_snapshot(
        connection,
        profile_id="default",
        now=now,
    )
    decision = decide_cache_mode(
        Intent.LOCAL_METADATA,
        snapshot=snapshot,
        cache_mode="offline",
        metadata_scope="notebook_index",
    )

    assert decision.source_of_truth == "local_cache"
    assert decision.used_cached_result is True
    assert decision.should_sync_metadata is False
    assert decision.freshness.notebook_index_age_s == 3600
    assert decision.freshness.used_cached_result is True


def test_normalize_cache_mode_rejects_unknown_values():
    with pytest.raises(ValueError, match="Unsupported cache mode"):
        normalize_cache_mode("sideways")
