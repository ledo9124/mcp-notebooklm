"""Unit tests for drive-source stale detection."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import (
    InboxClusterRepository,
    InboxItemRecord,
    InboxItemRepository,
    NotebookRecord,
    NotebookRepository,
    SourceRecord,
    SourceRepository,
)
from notebooklm.radar import detect_drive_source_staleness


def _insert_profile(connection, profile_id: str) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO profiles (
                profile_id,
                display_name,
                account_email,
                is_default,
                storage_state_path,
                browser_profile_path,
                created_at,
                updated_at,
                last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                f"Profile {profile_id}",
                f"{profile_id}@example.com",
                0,
                f"/tmp/{profile_id}/storage_state.json",
                f"/tmp/{profile_id}/browser_profile",
                "2026-03-15T00:00:00Z",
                "2026-03-15T00:00:00Z",
                None,
            ),
        )


def _insert_notebook(connection, notebook_id: str, profile_id: str) -> None:
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id=notebook_id,
            profile_id=profile_id,
            title="Research Notebook",
            normalized_title="research-notebook",
        )
    )


def test_detect_drive_source_staleness_stages_pending_inbox_action(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_notebook(connection, "nb_1", "profile_a")
        source_repository = SourceRepository(connection)
        cluster_repository = InboxClusterRepository(connection)
        item_repository = InboxItemRepository(connection)

        source_repository.upsert(
            SourceRecord(
                source_id="src_drive_1",
                notebook_id="nb_1",
                profile_id="profile_a",
                source_type="google_docs",
                status="ready",
                title="Quarterly plan",
                origin_uri="https://docs.google.com/document/d/doc-1/edit",
                drive_syncable=True,
                synced_at="2026-03-15T01:00:00+00:00",
                updated_at_remote="2026-03-15T02:00:00+00:00",
            )
        )
        item_repository.upsert(
            InboxItemRecord(
                id="inb_prior_drive",
                profile_id="profile_a",
                notebook_id="nb_1",
                origin="change_radar",
                kind="resync",
                state="approved",
                title="Previously approved stale-source review",
                created_at="2026-03-15T03:00:00+00:00",
                canonical_uri="https://docs.google.com/document/d/doc-1/edit",
            )
        )

        detections = detect_drive_source_staleness(
            connection,
            "profile_a",
            now=datetime(2026, 3, 15, 4, 30, tzinfo=timezone.utc),
            trace_id="trc_test_drive_stale",
        )
        source = source_repository.get("src_drive_1")
        inbox_items = item_repository.list_for_profile("profile_a")
        inbox_clusters = cluster_repository.list_all()
        events = list_run_events(connection, "trc_test_drive_stale")

    assert len(detections) == 1
    detection = detections[0]
    assert detection.source_id == "src_drive_1"
    assert detection.stale_reason == "remote_updated_after_sync"
    assert detection.staged is True
    assert source is not None
    assert source.freshness_state == "stale"

    assert len(inbox_items) == 2
    item = item_repository.get(detection.inbox_item_id)
    assert item is not None
    assert item.id == detection.inbox_item_id
    assert item.origin == "change_radar"
    assert item.kind == "resync"
    assert item.state == "pending"
    assert item.title == "Drive source may be stale: Quarterly plan"
    assert item.cluster_id == detection.cluster_id
    assert item.canonical_uri == "https://docs.google.com/document/d/doc-1/edit"

    assert len(inbox_clusters) == 1
    cluster = inbox_clusters[0]
    assert cluster.id == detection.cluster_id
    assert cluster.representative_item_id == detection.inbox_item_id
    assert cluster.canonical_uri == "https://docs.google.com/document/d/doc-1/edit"
    rationale = json.loads(item.rationale_json or "{}")
    assert rationale["scores"] == {
        "relevance": item.relevance_score,
        "novelty": item.novelty_score,
        "trust": item.trust_score,
    }
    assert rationale["scoring_context"] == {
        "workspace_match_count": 0,
        "query_history_match_count": 0,
        "prior_approved_count": 1,
        "prior_rejected_count": 0,
    }

    assert sorted(event.kind for event in events) == ["change.detected", "inbox.item.created"]


def test_detect_drive_source_staleness_marks_fresh_sources_without_staging(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_notebook(connection, "nb_1", "profile_a")
        source_repository = SourceRepository(connection)
        item_repository = InboxItemRepository(connection)

        source_repository.upsert(
            SourceRecord(
                source_id="src_drive_fresh",
                notebook_id="nb_1",
                profile_id="profile_a",
                source_type="google_docs",
                status="ready",
                drive_syncable=True,
                synced_at="2026-03-15T02:00:00+00:00",
                updated_at_remote="2026-03-15T01:00:00+00:00",
            )
        )
        source_repository.upsert(
            SourceRecord(
                source_id="src_web",
                notebook_id="nb_1",
                profile_id="profile_a",
                source_type="web_page",
                status="ready",
                drive_syncable=False,
                synced_at="2026-03-15T01:00:00+00:00",
                updated_at_remote="2026-03-15T02:00:00+00:00",
            )
        )

        detections = detect_drive_source_staleness(connection, "profile_a")
        drive_source = source_repository.get("src_drive_fresh")
        web_source = source_repository.get("src_web")
        inbox_items = item_repository.list_for_profile("profile_a")

    assert detections == []
    assert drive_source is not None
    assert drive_source.freshness_state == "fresh"
    assert web_source is not None
    assert web_source.freshness_state is None
    assert inbox_items == []


def test_detect_drive_source_staleness_dedupes_existing_pending_item(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_notebook(connection, "nb_1", "profile_a")
        source_repository = SourceRepository(connection)
        item_repository = InboxItemRepository(connection)

        source_repository.upsert(
            SourceRecord(
                source_id="src_drive_2",
                notebook_id="nb_1",
                profile_id="profile_a",
                source_type="google_slides",
                status="ready",
                title="Roadmap deck",
                origin_uri="https://docs.google.com/presentation/d/deck-1/edit",
                drive_syncable=True,
                synced_at="2026-03-15T01:00:00+00:00",
                updated_at_remote="2026-03-15T03:00:00+00:00",
            )
        )

        first = detect_drive_source_staleness(
            connection,
            "profile_a",
            trace_id="trc_drive_dedupe_a",
        )
        second = detect_drive_source_staleness(
            connection,
            "profile_a",
            trace_id="trc_drive_dedupe_b",
        )
        inbox_items = item_repository.list_for_profile("profile_a")
        events = list_run_events(connection, "trc_drive_dedupe_b")

    assert len(first) == 1
    assert first[0].staged is True
    assert len(second) == 1
    assert second[0].staged is False
    assert second[0].inbox_item_id == first[0].inbox_item_id
    assert len(inbox_items) == 1
    assert events == []
