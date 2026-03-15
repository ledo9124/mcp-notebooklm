"""Unit tests for notebook index sync helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm.local.db import configure_connection
from notebooklm.local.migrations import run_default_migrations
from notebooklm.local.repositories import NotebookRecord, NotebookRepository
from notebooklm.profiles.manager import ProfileManager
from notebooklm.sync import (
    DEFAULT_NOTEBOOK_INDEX_FRESHNESS_SECONDS,
    NOTEBOOK_INDEX_SCOPE,
    sync_notebook_index,
)
from notebooklm.types import Notebook


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


def _client_with_notebooks(notebooks: list[Notebook]) -> MagicMock:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.notebooks.list = AsyncMock(return_value=notebooks)
    return client


@pytest.mark.asyncio
async def test_sync_notebook_index_fetches_remote_and_records_sync_run():
    connection = _connect()
    client = _client_with_notebooks(
        [
            Notebook(
                id="nb_alpha",
                title="Alpha Notebook",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                sources_count=2,
                is_owner=True,
            ),
            Notebook(
                id="nb_beta",
                title="Beta Notebook",
                created_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
                sources_count=0,
                is_owner=False,
            ),
        ]
    )

    state = await sync_notebook_index(
        client,
        connection,
        profile_id="default",
        now=datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc),
    )

    assert state.used_cache is False
    assert state.sync_run_id is not None
    assert [record.notebook_id for record in state.notebooks] == ["nb_alpha", "nb_beta"]

    stored = {record.notebook_id: record for record in NotebookRepository(connection).list_for_profile("default")}
    assert stored["nb_alpha"].normalized_title == "alpha notebook"
    assert stored["nb_alpha"].source_count == 2
    assert stored["nb_alpha"].index_synced_at == state.synced_at
    assert stored["nb_beta"].is_owner is False

    row = connection.execute("SELECT * FROM sync_runs WHERE id = ?", (state.sync_run_id,)).fetchone()
    assert row is not None
    assert row["scope"] == NOTEBOOK_INDEX_SCOPE
    assert row["status"] == "completed"
    assert row["trace_id"].startswith("trc_")
    assert json.loads(row["stats_json"]) == {
        "active_count": 2,
        "freshness_seconds": DEFAULT_NOTEBOOK_INDEX_FRESHNESS_SECONDS,
        "remote_count": 2,
        "tombstoned": 0,
        "upserted": 2,
    }


@pytest.mark.asyncio
async def test_sync_notebook_index_uses_cache_when_latest_sync_is_fresh():
    connection = _connect()
    client = _client_with_notebooks(
        [
            Notebook(
                id="nb_cached",
                title="Cached Notebook",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                sources_count=1,
                is_owner=True,
            )
        ]
    )
    start = datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc)

    first = await sync_notebook_index(client, connection, profile_id="default", now=start)
    client.notebooks.list.reset_mock()

    second = await sync_notebook_index(
        client,
        connection,
        profile_id="default",
        now=start + timedelta(minutes=1),
    )

    assert first.used_cache is False
    assert second.used_cache is True
    assert [record.notebook_id for record in second.notebooks] == ["nb_cached"]
    client.notebooks.list.assert_not_called()


@pytest.mark.asyncio
async def test_sync_notebook_index_bypasses_fresh_cache_when_auth_fingerprint_changes(tmp_path):
    connection = _connect()
    storage_file = tmp_path / "storage_state.json"
    storage_file.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "SID", "value": "sid_old", "domain": ".google.com"},
                ]
            }
        ),
        encoding="utf-8",
    )
    client = _client_with_notebooks(
        [
            Notebook(
                id="nb_cached",
                title="Cached Notebook",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                sources_count=1,
                is_owner=True,
            )
        ]
    )
    start = datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc)

    first = await sync_notebook_index(
        client,
        connection,
        profile_id="default",
        storage_path=storage_file,
        now=start,
    )
    first_row = connection.execute("SELECT stats_json FROM sync_runs WHERE id = ?", (first.sync_run_id,)).fetchone()
    first_stats = json.loads(first_row["stats_json"])
    client.notebooks.list.reset_mock()

    storage_file.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "SID", "value": "sid_new", "domain": ".google.com"},
                ]
            }
        ),
        encoding="utf-8",
    )
    client.notebooks.list.return_value = [
        Notebook(
            id="nb_fresh",
            title="Fresh Notebook",
            created_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            sources_count=2,
            is_owner=True,
        )
    ]

    second = await sync_notebook_index(
        client,
        connection,
        profile_id="default",
        storage_path=storage_file,
        now=start + timedelta(minutes=1),
    )

    assert second.used_cache is False
    assert [record.notebook_id for record in second.notebooks] == ["nb_fresh"]
    client.notebooks.list.assert_awaited_once()

    second_row = connection.execute(
        "SELECT stats_json FROM sync_runs WHERE id = ?",
        (second.sync_run_id,),
    ).fetchone()
    second_stats = json.loads(second_row["stats_json"])
    assert first_stats["auth_fingerprint"] != second_stats["auth_fingerprint"]


@pytest.mark.asyncio
async def test_sync_notebook_index_tombstones_missing_notebooks_and_preserves_detail_fields():
    connection = _connect()
    repository = NotebookRepository(connection)
    repository.upsert(
        NotebookRecord(
            notebook_id="nb_keep",
            profile_id="default",
            title="Keep Me",
            normalized_title="keep me",
            is_owner=False,
            share_visibility="shared",
            created_at_remote="2024-01-01T00:00:00+00:00",
            source_count=1,
            artifact_count=3,
            note_count=4,
            summary_preview="Existing summary",
            index_synced_at="2026-03-15T02:50:00+00:00",
            detail_synced_at="2026-03-15T02:51:00+00:00",
            remote_fingerprint="fp_keep",
            tombstoned_at=None,
            raw_json="{\"cached\":true}",
        )
    )
    repository.upsert(
        NotebookRecord(
            notebook_id="nb_gone",
            profile_id="default",
            title="Gone",
            normalized_title="gone",
            is_owner=True,
            created_at_remote="2024-01-02T00:00:00+00:00",
            source_count=0,
            index_synced_at="2026-03-15T02:50:00+00:00",
            tombstoned_at=None,
        )
    )

    client = _client_with_notebooks(
        [
            Notebook(
                id="nb_keep",
                title="Keep Me Updated",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                sources_count=5,
                is_owner=True,
            )
        ]
    )

    state = await sync_notebook_index(
        client,
        connection,
        profile_id="default",
        now=datetime(2026, 3, 15, 3, 5, tzinfo=timezone.utc),
        freshness_seconds=1,
    )

    kept = repository.get("nb_keep")
    gone = repository.get("nb_gone")

    assert kept is not None
    assert kept.title == "Keep Me Updated"
    assert kept.source_count == 5
    assert kept.artifact_count == 3
    assert kept.note_count == 4
    assert kept.summary_preview == "Existing summary"
    assert kept.detail_synced_at == "2026-03-15T02:51:00+00:00"
    assert kept.remote_fingerprint == "fp_keep"
    assert kept.tombstoned_at is None

    assert gone is not None
    assert gone.tombstoned_at == state.synced_at


@pytest.mark.asyncio
async def test_sync_notebook_index_respects_overridden_freshness_window():
    connection = _connect()
    client = _client_with_notebooks(
        [
            Notebook(
                id="nb_one",
                title="Notebook One",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                sources_count=1,
                is_owner=True,
            )
        ]
    )
    start = datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc)

    await sync_notebook_index(client, connection, profile_id="default", now=start)
    client.notebooks.list.reset_mock()
    client.notebooks.list.return_value = [
        Notebook(
            id="nb_one",
            title="Notebook One",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            sources_count=2,
            is_owner=True,
        )
    ]

    state = await sync_notebook_index(
        client,
        connection,
        profile_id="default",
        now=start + timedelta(seconds=90),
        freshness_seconds=60,
    )

    assert state.used_cache is False
    client.notebooks.list.assert_awaited_once()
    assert state.notebooks[0].source_count == 2
