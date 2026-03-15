"""Unit tests for notebook detail sync helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm.local.db import configure_connection
from notebooklm.local.migrations import run_default_migrations
from notebooklm.local.repositories import (
    ArtifactRecord,
    ArtifactRepository,
    NotebookRecord,
    NotebookRepository,
    SourceRecord,
    SourceRepository,
)
from notebooklm.profiles.manager import ProfileManager
from notebooklm.sync import NOTEBOOK_DETAIL_SCOPE, sync_notebook_detail


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


def _raw_source(
    source_id: str,
    title: str,
    *,
    type_code: int,
    status_code: int,
    url: str | None = None,
    created_at: int = 1704067200,
    updated_at: int | None = None,
) -> list[object]:
    metadata = [
        None,
        100,
        [created_at, 0],
        ["version", [updated_at or created_at, 0]],
        type_code,
        None,
        1,
        [url] if url else [],
    ]
    return [[[source_id], title, metadata, [None, status_code]]][0]


def _raw_detail(
    notebook_id: str,
    title: str,
    sources: list[list[object]],
) -> list[object]:
    return [
        [
            title,
            sources,
            notebook_id,
            "📘",
            None,
            [None, False, None, None, None, [1704067000, 0]],
        ]
    ]


def _raw_artifact(
    artifact_id: str,
    title: str,
    *,
    artifact_type: int,
    status: int,
    created_at: int | None = None,
    download_ref: str | None = None,
) -> list[object]:
    payload: list[object] = [artifact_id, title, artifact_type, None, status]
    if download_ref is not None:
        while len(payload) <= 6:
            payload.append(None)
        payload[6] = [None, None, None, None, None, [[download_ref, None, "application/octet-stream"]]]
    if created_at is not None:
        while len(payload) <= 15:
            payload.append(None)
        payload[15] = [created_at]
    return payload


def _client_with_detail(raw_detail: list[object], raw_artifacts: list[list[object]]) -> MagicMock:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.notebooks.get_raw = AsyncMock(return_value=raw_detail)
    client.artifacts = MagicMock()
    client.artifacts._list_raw = AsyncMock(return_value=raw_artifacts)
    return client


@pytest.mark.asyncio
async def test_sync_notebook_detail_fetches_remote_and_records_sync_run():
    connection = _connect()
    client = _client_with_detail(
        _raw_detail(
            "nb_1",
            "Notebook Sync",
            [
                _raw_source(
                    "src_1",
                    "Alpha Source",
                    type_code=5,
                    status_code=2,
                    url="https://example.com/a",
                    created_at=1704067200,
                    updated_at=1704067300,
                ),
                _raw_source(
                    "src_2",
                    "Beta PDF",
                    type_code=3,
                    status_code=5,
                    created_at=1704067400,
                ),
            ],
        ),
        [
            _raw_artifact(
                "art_audio",
                "Audio Overview",
                artifact_type=1,
                status=3,
                created_at=1704067600,
                download_ref="https://storage.googleapis.com/audio.mp4",
            ),
            _raw_artifact(
                "art_report",
                "Briefing Doc",
                artifact_type=2,
                status=1,
            ),
        ],
    )

    state = await sync_notebook_detail(
        client,
        connection,
        "nb_1",
        profile_id="default",
        now=datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc),
    )

    assert state.used_cache is False
    assert state.sync_run_id is not None
    assert state.notebook.notebook_id == "nb_1"
    assert state.notebook.source_count == 2
    assert state.notebook.artifact_count == 2
    assert state.notebook.detail_synced_at == state.synced_at
    assert state.notebook.remote_fingerprint

    sources = {record.source_id: record for record in state.sources}
    assert sources["src_1"].source_type == "web_page"
    assert sources["src_1"].status == "ready"
    assert sources["src_1"].origin_uri == "https://example.com/a"
    assert sources["src_2"].source_type == "pdf"
    assert sources["src_2"].status == "preparing"

    artifacts = {record.artifact_id: record for record in state.artifacts}
    assert artifacts["art_audio"].artifact_type == "audio"
    assert artifacts["art_audio"].status == "completed"
    assert artifacts["art_audio"].download_ref == "https://storage.googleapis.com/audio.mp4"
    assert artifacts["art_report"].artifact_type == "report"
    assert artifacts["art_report"].status == "in_progress"

    row = connection.execute("SELECT * FROM sync_runs WHERE id = ?", (state.sync_run_id,)).fetchone()
    assert row is not None
    assert row["scope"] == NOTEBOOK_DETAIL_SCOPE
    assert row["target_id"] == "nb_1"
    assert row["status"] == "completed"
    assert row["trace_id"].startswith("trc_")
    assert json.loads(row["stats_json"]) == {
        "artifact_count": 2,
        "deleted_artifacts": 0,
        "freshness_seconds": 120,
        "source_count": 2,
        "tombstoned_sources": 0,
    }


@pytest.mark.asyncio
async def test_sync_notebook_detail_uses_cache_when_sync_is_fresh():
    connection = _connect()
    client = _client_with_detail(
        _raw_detail(
            "nb_cached",
            "Cached Notebook",
            [_raw_source("src_1", "Only Source", type_code=5, status_code=2)],
        ),
        [_raw_artifact("art_1", "Audio Overview", artifact_type=1, status=3)],
    )

    start = datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc)
    first = await sync_notebook_detail(client, connection, "nb_cached", profile_id="default", now=start)
    client.notebooks.get_raw.reset_mock()
    client.artifacts._list_raw.reset_mock()

    second = await sync_notebook_detail(
        client,
        connection,
        "nb_cached",
        profile_id="default",
        now=datetime(2026, 3, 15, 4, 1, tzinfo=timezone.utc),
    )

    assert first.used_cache is False
    assert second.used_cache is True
    assert second.sync_run_id is None
    assert second.notebook.notebook_id == "nb_cached"
    assert len(second.sources) == 1
    client.notebooks.get_raw.assert_not_called()
    client.artifacts._list_raw.assert_not_called()


@pytest.mark.asyncio
async def test_sync_notebook_detail_tombstones_missing_sources_and_deletes_missing_artifacts():
    connection = _connect()
    notebook_repository = NotebookRepository(connection)
    source_repository = SourceRepository(connection)
    artifact_repository = ArtifactRepository(connection)

    notebook_repository.upsert(
        NotebookRecord(
            notebook_id="nb_2",
            profile_id="default",
            title="Old Notebook",
            normalized_title="old notebook",
            source_count=2,
            artifact_count=2,
            detail_synced_at="2026-03-15T03:00:00+00:00",
        )
    )
    source_repository.upsert(
        SourceRecord(
            source_id="src_keep",
            notebook_id="nb_2",
            profile_id="default",
            source_type="web_page",
            status="ready",
            title="Keep",
            synced_at="2026-03-15T03:00:00+00:00",
        )
    )
    source_repository.upsert(
        SourceRecord(
            source_id="src_old",
            notebook_id="nb_2",
            profile_id="default",
            source_type="pdf",
            status="ready",
            title="Old",
            synced_at="2026-03-15T03:00:00+00:00",
        )
    )
    artifact_repository.upsert(
        ArtifactRecord(
            artifact_id="art_keep",
            notebook_id="nb_2",
            profile_id="default",
            artifact_type="audio",
            status="processing",
            requested_at="2026-03-14T00:00:00+00:00",
            title="Keep Audio",
        )
    )
    artifact_repository.upsert(
        ArtifactRecord(
            artifact_id="art_old",
            notebook_id="nb_2",
            profile_id="default",
            artifact_type="report",
            status="completed",
            requested_at="2026-03-14T00:10:00+00:00",
            title="Old Report",
        )
    )

    client = _client_with_detail(
        _raw_detail(
            "nb_2",
            "Updated Notebook",
            [_raw_source("src_keep", "Keep", type_code=5, status_code=2)],
        ),
        [_raw_artifact("art_keep", "Keep Audio", artifact_type=1, status=3)],
    )

    state = await sync_notebook_detail(
        client,
        connection,
        "nb_2",
        profile_id="default",
        now=datetime(2026, 3, 15, 4, 5, tzinfo=timezone.utc),
        freshness_seconds=1,
    )

    assert {record.source_id for record in state.sources} == {"src_keep"}
    assert {record.artifact_id for record in state.artifacts} == {"art_keep"}

    tombstoned = source_repository.get("src_old")
    assert tombstoned is not None
    assert tombstoned.tombstoned_at == state.synced_at

    assert artifact_repository.get("art_old") is None
    kept_artifact = artifact_repository.get("art_keep")
    assert kept_artifact is not None
    assert kept_artifact.requested_at == "2026-03-14T00:00:00+00:00"

    updated_notebook = notebook_repository.get("nb_2")
    assert updated_notebook is not None
    assert updated_notebook.title == "Updated Notebook"
    assert updated_notebook.source_count == 1
    assert updated_notebook.artifact_count == 1
