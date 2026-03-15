"""Unit tests for local sync invalidation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from notebooklm.local.db import configure_connection
from notebooklm.local.migrations import run_default_migrations
from notebooklm.local.repositories import ArtifactRepository, NotebookRecord, NotebookRepository
from notebooklm.profiles.manager import ProfileManager
from notebooklm.sync import (
    invalidate_notebook_detail,
    invalidate_notebook_index,
    seed_pending_artifact,
)


def _connect() -> sqlite3.Connection:
    connection = configure_connection(sqlite3.connect(":memory:"))
    run_default_migrations(connection)
    return connection


def _create_profile(connection: sqlite3.Connection, profile_id: str = "default") -> None:
    manager = ProfileManager(connection)
    manager.create_profile(
        profile_id=profile_id,
        display_name="Default",
        storage_state_path="/tmp/storage_state.json",
        browser_profile_path="/tmp/browser_profile",
        is_default=True,
    )
    manager.switch_profile(profile_id)


def test_invalidate_notebook_index_clears_profile_freshness_and_completed_runs() -> None:
    connection = _connect()
    _create_profile(connection)
    notebook_repository = NotebookRepository(connection)
    notebook_repository.upsert(
        NotebookRecord(
            notebook_id="nb_1",
            profile_id="default",
            title="Notebook",
            normalized_title="notebook",
            index_synced_at="2026-03-15T04:00:00+00:00",
        )
    )
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
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "sr_index",
                    "trc_index",
                    "default",
                    "notebook_index",
                    None,
                    "manual",
                    "2026-03-15T04:00:00+00:00",
                "2026-03-15T04:00:01+00:00",
                "completed",
            ),
        )
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
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sr_detail",
                "trc_detail",
                "default",
                "notebook_detail",
                "nb_1",
                "manual",
                "2026-03-15T04:00:00+00:00",
                "2026-03-15T04:00:01+00:00",
                "completed",
            ),
        )

    invalidated = invalidate_notebook_index(connection, profile_id="default")

    assert invalidated == 1
    notebook = notebook_repository.get("nb_1")
    assert notebook is not None
    assert notebook.index_synced_at is None

    index_run = connection.execute(
        "SELECT status, error_text FROM sync_runs WHERE id = ?",
        ("sr_index",),
    ).fetchone()
    detail_run = connection.execute(
        "SELECT status FROM sync_runs WHERE id = ?",
        ("sr_detail",),
    ).fetchone()
    assert index_run["status"] == "cancelled"
    assert index_run["error_text"] == "notebook.create"
    assert detail_run["status"] == "completed"


def test_invalidate_notebook_detail_only_clears_targeted_notebook_runs() -> None:
    connection = _connect()
    _create_profile(connection)
    notebook_repository = NotebookRepository(connection)
    notebook_repository.upsert(
        NotebookRecord(
            notebook_id="nb_1",
            profile_id="default",
            title="Notebook One",
            normalized_title="notebook one",
            index_synced_at="2026-03-15T04:00:00+00:00",
            detail_synced_at="2026-03-15T04:01:00+00:00",
            remote_fingerprint="fp_1",
        )
    )
    notebook_repository.upsert(
        NotebookRecord(
            notebook_id="nb_2",
            profile_id="default",
            title="Notebook Two",
            normalized_title="notebook two",
            detail_synced_at="2026-03-15T04:02:00+00:00",
            remote_fingerprint="fp_2",
        )
    )
    with connection:
        for run_id, target_id in (("sr_nb1", "nb_1"), ("sr_nb2", "nb_2")):
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
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    f"trc_{run_id}",
                    "default",
                    "notebook_detail",
                    target_id,
                    "manual",
                    "2026-03-15T04:00:00+00:00",
                    "2026-03-15T04:00:01+00:00",
                    "completed",
                ),
            )
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
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sr_index",
                "trc_index",
                "default",
                "notebooks",
                None,
                "manual",
                "2026-03-15T04:00:00+00:00",
                "2026-03-15T04:00:01+00:00",
                "completed",
            ),
        )

    invalidated = invalidate_notebook_detail(connection, "nb_1", profile_id="default", reason="source.add")

    assert invalidated == 1
    notebook_one = notebook_repository.get("nb_1")
    notebook_two = notebook_repository.get("nb_2")
    assert notebook_one is not None
    assert notebook_one.detail_synced_at is None
    assert notebook_one.index_synced_at == "2026-03-15T04:00:00+00:00"
    assert notebook_one.remote_fingerprint is None
    assert notebook_two is not None
    assert notebook_two.detail_synced_at == "2026-03-15T04:02:00+00:00"
    assert notebook_two.remote_fingerprint == "fp_2"

    first_run = connection.execute(
        "SELECT status, error_text FROM sync_runs WHERE id = ?",
        ("sr_nb1",),
    ).fetchone()
    second_run = connection.execute(
        "SELECT status FROM sync_runs WHERE id = ?",
        ("sr_nb2",),
    ).fetchone()
    index_run = connection.execute(
        "SELECT status FROM sync_runs WHERE id = ?",
        ("sr_index",),
    ).fetchone()
    assert first_run["status"] == "cancelled"
    assert first_run["error_text"] == "source.add"
    assert second_run["status"] == "completed"
    assert index_run["status"] == "completed"


def test_seed_pending_artifact_creates_missing_profile_and_placeholder_notebook(
    monkeypatch, tmp_path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    connection = _connect()
    storage_path = home / "storage_state.json"
    requested_at = datetime(2026, 3, 15, 4, 30, tzinfo=timezone.utc)

    record = seed_pending_artifact(
        connection,
        "nb_missing",
        "art_pending",
        artifact_type="audio",
        storage_path=storage_path,
        requested_at=requested_at,
    )

    profile = ProfileManager(connection).get_profile("default")
    notebook = NotebookRepository(connection).get("nb_missing")
    artifact = ArtifactRepository(connection).get("art_pending")

    assert profile is not None
    assert profile.storage_state_path == storage_path.resolve()
    assert record.profile_id == "default"
    assert record.status == "pending"
    assert record.requested_at == requested_at.isoformat()
    assert notebook is not None
    assert notebook.title == "nb_missing"
    assert notebook.normalized_title == "nb_missing"
    assert artifact is not None
    assert artifact.artifact_type == "audio"
    assert artifact.status == "pending"
