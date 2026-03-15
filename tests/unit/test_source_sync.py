"""Unit tests for source metadata sync helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from notebooklm.local.db import configure_connection
from notebooklm.local.migrations import run_default_migrations
from notebooklm.local.repositories import NotebookRecord, NotebookRepository, SourceRecord, SourceRepository
from notebooklm.profiles.manager import ProfileManager
from notebooklm.sync.sources import list_active_cached_sources, reconcile_sources


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


def _seed_notebook(connection: sqlite3.Connection, notebook_id: str) -> None:
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id=notebook_id,
            profile_id="default",
            title=f"Notebook {notebook_id}",
            normalized_title=f"notebook {notebook_id}",
        )
    )


def test_reconcile_sources_updates_cached_records_and_preserves_local_fields() -> None:
    connection = _connect()
    _seed_notebook(connection, "nb_1")
    repository = SourceRepository(connection)
    repository.upsert(
        SourceRecord(
            source_id="src_doc",
            notebook_id="nb_1",
            profile_id="default",
            source_type="google_docs",
            status="processing",
            title="Old title",
            freshness_state="fresh",
            drive_syncable=True,
            content_preview="Keep me",
            synced_at="2026-03-15T03:00:00+00:00",
        )
    )

    result = reconcile_sources(
        connection,
        notebook_id="nb_1",
        profile_id="default",
        synced_at="2026-03-15T04:00:00+00:00",
        raw_sources=[
            _raw_source(
                "src_doc",
                "Drive Doc",
                type_code=1,
                status_code=2,
                url="https://docs.google.com/document/d/123",
                updated_at=1704067300,
            ),
            _raw_source(
                "src_pdf",
                "Reference PDF",
                type_code=3,
                status_code=5,
            ),
        ],
    )

    assert [record.source_id for record in result.sources] == ["src_doc", "src_pdf"]
    assert result.tombstoned_count == 0

    doc = repository.get("src_doc")
    assert doc is not None
    assert doc.title == "Drive Doc"
    assert doc.source_type == "google_docs"
    assert doc.status == "ready"
    assert doc.origin_uri == "https://docs.google.com/document/d/123"
    assert doc.freshness_state == "fresh"
    assert doc.drive_syncable is True
    assert doc.content_preview == "Keep me"
    assert doc.tombstoned_at is None
    assert doc.remote_fingerprint

    pdf = repository.get("src_pdf")
    assert pdf is not None
    assert pdf.source_type == "pdf"
    assert pdf.status == "preparing"
    assert pdf.freshness_state == "fresh"
    assert pdf.drive_syncable is None


def test_reconcile_sources_tombstones_missing_rows_and_filters_active_list() -> None:
    connection = _connect()
    _seed_notebook(connection, "nb_2")
    repository = SourceRepository(connection)
    repository.upsert(
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
    repository.upsert(
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

    result = reconcile_sources(
        connection,
        notebook_id="nb_2",
        profile_id="default",
        synced_at="2026-03-15T04:05:00+00:00",
        raw_sources=[
            _raw_source(
                "src_keep",
                "Keep",
                type_code=5,
                status_code=1,
                url="https://example.com/keep",
            )
        ],
    )

    assert [record.source_id for record in result.sources] == ["src_keep"]
    assert result.tombstoned_count == 1
    assert [
        record.source_id
        for record in list_active_cached_sources(
            connection,
            "nb_2",
            now=datetime(2026, 3, 15, 4, 5, tzinfo=timezone.utc),
        )
    ] == ["src_keep"]

    tombstoned = repository.get("src_old")
    assert tombstoned is not None
    assert tombstoned.tombstoned_at == "2026-03-15T04:05:00+00:00"

    kept = repository.get("src_keep")
    assert kept is not None
    assert kept.status == "processing"
    assert kept.freshness_state == "fresh"
    assert kept.tombstoned_at is None


def test_list_active_cached_sources_uses_status_aware_freshness_windows() -> None:
    connection = _connect()
    _seed_notebook(connection, "nb_3")
    repository = SourceRepository(connection)
    repository.upsert(
        SourceRecord(
            source_id="src_ready_fresh",
            notebook_id="nb_3",
            profile_id="default",
            source_type="web_page",
            status="ready",
            synced_at="2026-03-15T04:00:00+00:00",
        )
    )
    repository.upsert(
        SourceRecord(
            source_id="src_ready_stale",
            notebook_id="nb_3",
            profile_id="default",
            source_type="web_page",
            status="ready",
            synced_at="2026-03-15T03:49:00+00:00",
        )
    )
    repository.upsert(
        SourceRecord(
            source_id="src_processing_fresh",
            notebook_id="nb_3",
            profile_id="default",
            source_type="pdf",
            status="processing",
            synced_at="2026-03-15T03:59:50+00:00",
        )
    )
    repository.upsert(
        SourceRecord(
            source_id="src_preparing_stale",
            notebook_id="nb_3",
            profile_id="default",
            source_type="pdf",
            status="preparing",
            synced_at="2026-03-15T03:59:40+00:00",
        )
    )
    repository.upsert(
        SourceRecord(
            source_id="src_unknown",
            notebook_id="nb_3",
            profile_id="default",
            source_type="pdf",
            status="ready",
        )
    )

    sources = {
        record.source_id: record
        for record in list_active_cached_sources(
            connection,
            "nb_3",
            now=datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc),
        )
    }

    assert sources["src_ready_fresh"].freshness_state == "fresh"
    assert sources["src_ready_stale"].freshness_state == "stale"
    assert sources["src_processing_fresh"].freshness_state == "fresh"
    assert sources["src_preparing_stale"].freshness_state == "stale"
    assert sources["src_unknown"].freshness_state == "unknown"

    assert repository.get("src_ready_stale").freshness_state == "stale"
    assert repository.get("src_preparing_stale").freshness_state == "stale"
