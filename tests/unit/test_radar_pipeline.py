"""Unit tests for the core change-radar source pipeline."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os

from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import (
    NotebookRecord,
    NotebookRepository,
    SourceRecord,
    SourceRepository,
)
from notebooklm.radar import list_due_watches, run_due_watches, run_watch
from notebooklm.sync.notebooks import NOTEBOOK_DETAIL_SCOPE


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
                1,
                f"/tmp/{profile_id}/storage_state.json",
                f"/tmp/{profile_id}/browser_profile",
                "2026-03-15T00:00:00Z",
                "2026-03-15T00:00:00Z",
                None,
            ),
        )
        connection.execute(
            """
            UPDATE app_state
            SET active_profile_id = ?
            WHERE singleton_key = 1
            """,
            (profile_id,),
        )


def _insert_notebook(
    connection,
    notebook_id: str,
    profile_id: str,
    *,
    detail_synced_at: str | None = "2026-03-15T02:00:00+00:00",
    remote_fingerprint: str | None = "fp_original",
) -> None:
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id=notebook_id,
            profile_id=profile_id,
            title="Radar Notebook",
            normalized_title="radar-notebook",
            detail_synced_at=detail_synced_at,
            remote_fingerprint=remote_fingerprint,
        )
    )


def _insert_source(
    connection,
    source_id: str,
    notebook_id: str,
    profile_id: str,
    *,
    source_type: str = "local_file",
    origin_uri: str | None = None,
    freshness_state: str | None = None,
) -> None:
    SourceRepository(connection).upsert(
        SourceRecord(
            source_id=source_id,
            notebook_id=notebook_id,
            profile_id=profile_id,
            source_type=source_type,
            status="ready",
            title=f"Source {source_id}",
            origin_uri=origin_uri,
            freshness_state=freshness_state,
        )
    )


def _insert_watch(
    connection,
    watch_id: str,
    profile_id: str,
    source_id: str,
    *,
    watch_kind: str = "local_file_hash",
    scope_type: str = "source",
    policy: dict[str, object] | None = None,
    schedule: dict[str, object] | None = None,
    next_run_at: str | None = None,
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO watches (
                id,
                profile_id,
                scope_type,
                scope_id,
                watch_kind,
                policy_json,
                status,
                schedule_json,
                next_run_at,
                last_run_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                watch_id,
                profile_id,
                scope_type,
                source_id,
                watch_kind,
                json.dumps(policy or {}, sort_keys=True, separators=(",", ":")),
                "active",
                json.dumps(schedule or {"interval": "daily"}, sort_keys=True, separators=(",", ":")),
                next_run_at,
                None,
            ),
        )


def _insert_completed_detail_sync(
    connection,
    *,
    profile_id: str,
    notebook_id: str,
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO sync_runs (
                id,
                trace_id,
                profile_id,
                scope,
                target_id,
                trigger,
                started_at,
                ended_at,
                status,
                stats_json,
                error_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sr_detail_1",
                "trc_detail_sync_1",
                profile_id,
                NOTEBOOK_DETAIL_SCOPE,
                notebook_id,
                "notebook_show",
                "2026-03-15T01:00:00+00:00",
                "2026-03-15T01:01:00+00:00",
                "completed",
                None,
                None,
            ),
        )


def _fetch_rows(connection, table_name: str):
    return connection.execute(f"SELECT * FROM {table_name} ORDER BY id ASC").fetchall()


def test_list_due_watches_and_run_due_watches_capture_a_baseline(tmp_path):
    db_path = tmp_path / "cache.db"
    target = tmp_path / "watched.txt"
    target.write_text("baseline\n", encoding="utf-8")

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_notebook(connection, "nb_1", "profile_a")
        _insert_source(
            connection,
            "src_due",
            "nb_1",
            "profile_a",
            origin_uri=target.as_uri(),
        )
        _insert_source(
            connection,
            "src_future",
            "nb_1",
            "profile_a",
            origin_uri=target.as_uri(),
        )
        _insert_watch(
            connection,
            "watch_due",
            "profile_a",
            "src_due",
            policy={"path": str(target)},
            next_run_at="2026-03-15T03:59:00+00:00",
        )
        _insert_watch(
            connection,
            "watch_future",
            "profile_a",
            "src_future",
            policy={"path": str(target)},
            next_run_at="2026-03-16T03:59:00+00:00",
        )

        due = list_due_watches(
            connection,
            now=datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc),
        )
        results = asyncio.run(
            run_due_watches(
                connection,
                now=datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc),
                trace_id="trc_radar_baseline",
            )
        )
        revisions = _fetch_rows(connection, "source_revisions")
        watch_runs = _fetch_rows(connection, "watch_runs")
        change_events = _fetch_rows(connection, "change_events")
        watch_due = connection.execute("SELECT * FROM watches WHERE id = 'watch_due'").fetchone()
        watch_future = connection.execute("SELECT * FROM watches WHERE id = 'watch_future'").fetchone()
        source_due = SourceRepository(connection).get("src_due")
        events = list_run_events(connection, "trc_radar_baseline")

    assert [watch.id for watch in due] == ["watch_due"]
    assert len(results) == 1
    assert results[0].watch_id == "watch_due"
    assert results[0].baseline_created is True
    assert results[0].changed is False
    assert results[0].status == "completed"

    assert len(revisions) == 1
    assert len(watch_runs) == 1
    assert len(change_events) == 0
    assert _fetch_rows(connection, "delta_briefings") == []
    assert watch_due["last_run_at"] == "2026-03-15T04:00:00+00:00"
    assert watch_due["next_run_at"] == "2026-03-16T04:00:00+00:00"
    assert watch_future["last_run_at"] is None
    assert source_due is not None
    assert source_due.freshness_state == "fresh"
    assert [event.kind for event in events] == ["watch.run.completed"]


def test_run_watch_records_material_change_and_invalidates_notebook_detail(tmp_path):
    db_path = tmp_path / "cache.db"
    target = tmp_path / "watched.txt"
    target.write_text("baseline\n", encoding="utf-8")

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_notebook(connection, "nb_1", "profile_a")
        _insert_source(
            connection,
            "src_change",
            "nb_1",
            "profile_a",
            origin_uri=target.as_uri(),
        )
        _insert_watch(
            connection,
            "watch_change",
            "profile_a",
            "src_change",
            policy={"path": str(target), "materiality": "normal"},
        )
        asyncio.run(
            run_watch(
                connection,
                "watch_change",
                now=datetime(2026, 3, 15, 4, 5, tzinfo=timezone.utc),
                trace_id="trc_radar_material_baseline",
            )
        )
        _insert_completed_detail_sync(connection, profile_id="profile_a", notebook_id="nb_1")

        target.write_text("changed content\n", encoding="utf-8")
        result = asyncio.run(
            run_watch(
                connection,
                "watch_change",
                now=datetime(2026, 3, 15, 4, 10, tzinfo=timezone.utc),
                trace_id="trc_radar_material_change",
            )
        )
        source = SourceRepository(connection).get("src_change")
        notebook = NotebookRepository(connection).get("nb_1")
        watch_runs = _fetch_rows(connection, "watch_runs")
        change_events = _fetch_rows(connection, "change_events")
        delta_briefings = _fetch_rows(connection, "delta_briefings")
        inbox_clusters = _fetch_rows(connection, "inbox_clusters")
        inbox_items = _fetch_rows(connection, "inbox_items")
        sync_run = connection.execute("SELECT * FROM sync_runs WHERE id = 'sr_detail_1'").fetchone()
        events = list_run_events(connection, "trc_radar_material_change")

    assert result.status == "completed"
    assert result.changed is True
    assert result.baseline_created is False
    assert result.change_kind == "content_hash_changed"
    assert result.severity == "material"
    assert result.invalidated_sync_runs == 1
    assert result.change_event_id is not None
    assert result.delta_briefing_id is not None
    assert result.source_revision_id is not None

    assert len(watch_runs) == 2
    assert len(change_events) == 1
    assert len(delta_briefings) == 1
    assert len(inbox_clusters) == 1
    assert len(inbox_items) == 1
    assert change_events[0]["state"] == "queued_inbox"
    payload = json.loads(change_events[0]["data_json"])
    assert payload["previous_revision_key"] != payload["current_revision_key"]
    assert payload["previous_content_hash"] != payload["current_content_hash"]
    assert payload["invalidated_sync_runs"] == 1
    assert payload["inbox_item_id"] == inbox_items[0]["id"]
    assert payload["inbox_cluster_id"] == inbox_clusters[0]["id"]
    assert payload["inbox_kind"] == "replacement"
    assert payload["suggested_action"] == "approve_replacement_candidate"
    briefing = delta_briefings[0]
    assert briefing["change_event_id"] == result.change_event_id
    assert "## What Changed" in briefing["summary_md"]
    assert "## Severity" in briefing["summary_md"]
    assert "## Affected Surfaces" in briefing["summary_md"]
    assert "## Recommended Action" in briefing["summary_md"]
    impact = json.loads(briefing["impact_json"])
    assert impact["notebooks"] == ["nb_1"]
    assert impact["stale_query_runs_possible"] is True
    recommended_actions = json.loads(briefing["recommended_actions_json"])
    assert recommended_actions["actions"][1]["kind"] == "resync_source"
    assert "staged inbox replacement candidate" in recommended_actions["actions"][1]["description"]
    inbox_item = inbox_items[0]
    assert inbox_item["origin"] == "change_radar"
    assert inbox_item["kind"] == "replacement"
    assert inbox_item["state"] == "pending"
    assert inbox_item["cluster_id"] == inbox_clusters[0]["id"]
    assert inbox_item["canonical_uri"] == target.as_uri()
    rationale = json.loads(inbox_item["rationale_json"])
    assert rationale["change_event_id"] == result.change_event_id
    assert rationale["delta_briefing_id"] == result.delta_briefing_id
    assert rationale["scores"] == {
        "relevance": inbox_item["relevance_score"],
        "novelty": inbox_item["novelty_score"],
        "trust": inbox_item["trust_score"],
    }
    assert rationale["scoring_context"] == {
        "workspace_match_count": 0,
        "query_history_match_count": 0,
        "prior_approved_count": 0,
        "prior_rejected_count": 0,
    }
    assert rationale["suggested_action"] == "approve_replacement_candidate"
    watch_run_payload = json.loads(watch_runs[1]["result_json"])
    assert watch_run_payload["change_event_state"] == "queued_inbox"
    assert watch_run_payload["inbox_item_id"] == inbox_item["id"]
    assert watch_run_payload["inbox_item_staged"] is True

    assert notebook is not None
    assert notebook.detail_synced_at is None
    assert notebook.remote_fingerprint is None
    assert sync_run["status"] == "cancelled"
    assert sync_run["error_text"] == "change_radar:watch_change:content_hash_changed"
    assert source is not None
    assert source.freshness_state == "stale"
    assert sorted(event.kind for event in events) == [
        "change.detected",
        "delta.briefing.created",
        "inbox.item.created",
        "watch.run.completed",
    ]


def test_run_watch_keeps_source_stale_while_material_change_event_is_open(tmp_path):
    db_path = tmp_path / "cache.db"
    target = tmp_path / "watched.txt"
    target.write_text("baseline\n", encoding="utf-8")

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_notebook(connection, "nb_1", "profile_a")
        _insert_source(
            connection,
            "src_open",
            "nb_1",
            "profile_a",
            origin_uri=target.as_uri(),
        )
        _insert_watch(
            connection,
            "watch_open",
            "profile_a",
            "src_open",
            policy={"path": str(target)},
        )
        asyncio.run(
            run_watch(
                connection,
                "watch_open",
                now=datetime(2026, 3, 15, 4, 15, tzinfo=timezone.utc),
                trace_id="trc_radar_open_baseline",
            )
        )
        target.write_text("changed content\n", encoding="utf-8")
        asyncio.run(
            run_watch(
                connection,
                "watch_open",
                now=datetime(2026, 3, 15, 4, 20, tzinfo=timezone.utc),
                trace_id="trc_radar_open_change",
            )
        )

        result = asyncio.run(
            run_watch(
                connection,
                "watch_open",
                now=datetime(2026, 3, 15, 4, 25, tzinfo=timezone.utc),
                trace_id="trc_radar_open_unchanged",
            )
        )
        source = SourceRepository(connection).get("src_open")
        change_events = _fetch_rows(connection, "change_events")
        delta_briefings = _fetch_rows(connection, "delta_briefings")
        inbox_items = _fetch_rows(connection, "inbox_items")
        events = list_run_events(connection, "trc_radar_open_unchanged")

    assert result.status == "completed"
    assert result.changed is False
    assert result.change_event_id is None
    assert len(change_events) == 1
    assert len(delta_briefings) == 1
    assert len(inbox_items) == 1
    assert change_events[0]["state"] == "queued_inbox"
    assert source is not None
    assert source.freshness_state == "stale"
    assert [event.kind for event in events] == ["watch.run.completed"]


def test_run_watch_records_minor_metadata_only_changes_without_invalidation(tmp_path):
    db_path = tmp_path / "cache.db"
    target = tmp_path / "watched.txt"
    target.write_text("baseline\n", encoding="utf-8")

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_notebook(connection, "nb_1", "profile_a")
        _insert_source(
            connection,
            "src_minor",
            "nb_1",
            "profile_a",
            origin_uri=target.as_uri(),
        )
        _insert_watch(
            connection,
            "watch_minor",
            "profile_a",
            "src_minor",
            policy={"path": str(target)},
        )
        asyncio.run(
            run_watch(
                connection,
                "watch_minor",
                now=datetime(2026, 3, 15, 4, 30, tzinfo=timezone.utc),
                trace_id="trc_radar_minor_baseline",
            )
        )

        stat = target.stat()
        os.utime(
            target,
            ns=(stat.st_atime_ns + 1_000_000_000, stat.st_mtime_ns + 1_000_000_000),
        )
        result = asyncio.run(
            run_watch(
                connection,
                "watch_minor",
                now=datetime(2026, 3, 15, 4, 35, tzinfo=timezone.utc),
                trace_id="trc_radar_minor_change",
            )
        )
        source = SourceRepository(connection).get("src_minor")
        notebook = NotebookRepository(connection).get("nb_1")
        change_events = _fetch_rows(connection, "change_events")
        delta_briefings = _fetch_rows(connection, "delta_briefings")
        inbox_clusters = _fetch_rows(connection, "inbox_clusters")
        inbox_items = _fetch_rows(connection, "inbox_items")
        events = list_run_events(connection, "trc_radar_minor_change")

    assert result.status == "completed"
    assert result.changed is True
    assert result.change_kind == "metadata_only_changed"
    assert result.severity == "minor"
    assert result.invalidated_sync_runs == 0
    assert result.delta_briefing_id is not None

    assert len(change_events) == 1
    assert len(delta_briefings) == 1
    assert change_events[0]["severity"] == "minor"
    assert change_events[0]["state"] == "new"
    assert inbox_clusters == []
    assert inbox_items == []
    recommended_actions = json.loads(delta_briefings[0]["recommended_actions_json"])
    assert recommended_actions["actions"][1]["kind"] == "monitor_source"
    assert source is not None
    assert source.freshness_state == "fresh"
    assert notebook is not None
    assert notebook.detail_synced_at == "2026-03-15T02:00:00+00:00"
    assert sorted(event.kind for event in events) == [
        "change.detected",
        "delta.briefing.created",
        "watch.run.completed",
    ]


def test_run_watch_stages_resync_inbox_item_for_material_metadata_change(tmp_path):
    db_path = tmp_path / "cache.db"
    target = tmp_path / "watched.txt"
    target.write_text("baseline\n", encoding="utf-8")

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_notebook(connection, "nb_1", "profile_a")
        _insert_source(
            connection,
            "src_metadata_material",
            "nb_1",
            "profile_a",
            origin_uri=target.as_uri(),
        )
        _insert_watch(
            connection,
            "watch_metadata_material",
            "profile_a",
            "src_metadata_material",
            policy={"path": str(target), "metadata_materiality": "material"},
        )
        asyncio.run(
            run_watch(
                connection,
                "watch_metadata_material",
                now=datetime(2026, 3, 15, 4, 45, tzinfo=timezone.utc),
                trace_id="trc_radar_metadata_material_baseline",
            )
        )
        _insert_completed_detail_sync(connection, profile_id="profile_a", notebook_id="nb_1")

        stat = target.stat()
        os.utime(
            target,
            ns=(stat.st_atime_ns + 2_000_000_000, stat.st_mtime_ns + 2_000_000_000),
        )
        result = asyncio.run(
            run_watch(
                connection,
                "watch_metadata_material",
                now=datetime(2026, 3, 15, 4, 50, tzinfo=timezone.utc),
                trace_id="trc_radar_metadata_material_change",
            )
        )
        source = SourceRepository(connection).get("src_metadata_material")
        notebook = NotebookRepository(connection).get("nb_1")
        change_events = _fetch_rows(connection, "change_events")
        delta_briefings = _fetch_rows(connection, "delta_briefings")
        inbox_clusters = _fetch_rows(connection, "inbox_clusters")
        inbox_items = _fetch_rows(connection, "inbox_items")
        sync_run = connection.execute("SELECT * FROM sync_runs WHERE id = 'sr_detail_1'").fetchone()
        events = list_run_events(connection, "trc_radar_metadata_material_change")

    assert result.status == "completed"
    assert result.changed is True
    assert result.change_kind == "metadata_only_changed"
    assert result.severity == "material"
    assert result.invalidated_sync_runs == 1
    assert len(change_events) == 1
    assert len(delta_briefings) == 1
    assert len(inbox_clusters) == 1
    assert len(inbox_items) == 1
    assert change_events[0]["state"] == "queued_inbox"
    payload = json.loads(change_events[0]["data_json"])
    assert payload["previous_content_hash"] == payload["current_content_hash"]
    assert payload["inbox_item_id"] == inbox_items[0]["id"]
    assert payload["inbox_kind"] == "resync"
    assert payload["suggested_action"] == "approve_resync_candidate"
    briefing = delta_briefings[0]
    assert "configured as material" in briefing["summary_md"]
    recommended_actions = json.loads(briefing["recommended_actions_json"])
    assert recommended_actions["actions"][1]["kind"] == "resync_source"
    assert "staged inbox resync candidate" in recommended_actions["actions"][1]["description"]
    inbox_item = inbox_items[0]
    assert inbox_item["origin"] == "change_radar"
    assert inbox_item["kind"] == "resync"
    assert inbox_item["state"] == "pending"
    assert inbox_item["cluster_id"] == inbox_clusters[0]["id"]
    rationale = json.loads(inbox_item["rationale_json"])
    assert rationale["change_event_id"] == result.change_event_id
    assert rationale["scores"] == {
        "relevance": inbox_item["relevance_score"],
        "novelty": inbox_item["novelty_score"],
        "trust": inbox_item["trust_score"],
    }
    assert rationale["scoring_context"] == {
        "workspace_match_count": 0,
        "query_history_match_count": 0,
        "prior_approved_count": 0,
        "prior_rejected_count": 0,
    }
    assert rationale["suggested_action"] == "approve_resync_candidate"
    assert source is not None
    assert source.freshness_state == "stale"
    assert notebook is not None
    assert notebook.detail_synced_at is None
    assert notebook.remote_fingerprint is None
    assert sync_run["status"] == "cancelled"
    assert sync_run["error_text"] == "change_radar:watch_metadata_material:metadata_only_changed"
    assert sorted(event.kind for event in events) == [
        "change.detected",
        "delta.briefing.created",
        "inbox.item.created",
        "watch.run.completed",
    ]


def test_run_watch_records_failures_for_unsupported_scope(tmp_path):
    db_path = tmp_path / "cache.db"
    target = tmp_path / "watched.txt"
    target.write_text("baseline\n", encoding="utf-8")

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_notebook(connection, "nb_1", "profile_a")
        _insert_source(
            connection,
            "src_fail",
            "nb_1",
            "profile_a",
            origin_uri=target.as_uri(),
        )
        _insert_watch(
            connection,
            "watch_fail",
            "profile_a",
            "src_fail",
            scope_type="notebook",
            policy={"path": str(target)},
        )

        result = asyncio.run(
            run_watch(
                connection,
                "watch_fail",
                now=datetime(2026, 3, 15, 4, 40, tzinfo=timezone.utc),
                trace_id="trc_radar_failed_watch",
            )
        )
        watch_runs = _fetch_rows(connection, "watch_runs")
        change_events = _fetch_rows(connection, "change_events")
        events = list_run_events(connection, "trc_radar_failed_watch")

    assert result.status == "failed"
    assert result.changed is False
    assert result.error_text is not None
    assert len(watch_runs) == 1
    assert watch_runs[0]["status"] == "failed"
    assert json.loads(watch_runs[0]["result_json"])["error"].startswith("watch scope")
    assert change_events == []
    assert [event.kind for event in events] == ["watch.run.completed"]
