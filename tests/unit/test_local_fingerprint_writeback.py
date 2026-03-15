"""Unit tests for notebook fingerprint writeback helpers."""

from __future__ import annotations

from notebooklm.local.detail_sync import sync_notebook_detail_fingerprint
from notebooklm.local.db import connect_db
from notebooklm.local.repositories import (
    ArtifactRecord,
    ArtifactRepository,
    NotebookRecord,
    NotebookRepository,
    SourceRecord,
    SourceRepository,
)


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


def _seed_notebook(connection) -> NotebookRepository:
    repository = NotebookRepository(connection)
    repository.upsert(
        NotebookRecord(
            notebook_id="nb_1",
            profile_id="profile_a",
            title="Research Notebook",
            normalized_title="research-notebook",
            summary_preview="Initial summary",
            detail_synced_at="2026-03-15T00:05:00Z",
        )
    )
    return repository


def _seed_sources(connection) -> SourceRepository:
    repository = SourceRepository(connection)
    repository.upsert(
        SourceRecord(
            source_id="src_1",
            notebook_id="nb_1",
            profile_id="profile_a",
            source_type="url",
            status="ready",
            remote_fingerprint="src-fp-1",
        )
    )
    return repository


def _seed_artifacts(connection) -> ArtifactRepository:
    repository = ArtifactRepository(connection)
    repository.upsert(
        ArtifactRecord(
            artifact_id="art_1",
            notebook_id="nb_1",
            profile_id="profile_a",
            artifact_type="report",
            status="completed",
            requested_at="2026-03-15T00:06:00Z",
        )
    )
    return repository


def test_sync_notebook_detail_fingerprint_persists_remote_fingerprint(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        notebook_repository = _seed_notebook(connection)
        _seed_sources(connection)
        _seed_artifacts(connection)

        updated = sync_notebook_detail_fingerprint(connection, "nb_1")
        stored = notebook_repository.get("nb_1")

    assert updated.remote_fingerprint is not None
    assert len(updated.remote_fingerprint) == 64
    assert stored == updated


def test_sync_notebook_detail_fingerprint_recomputes_after_detail_state_changes(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        notebook_repository = _seed_notebook(connection)
        source_repository = _seed_sources(connection)
        artifact_repository = _seed_artifacts(connection)

        initial = sync_notebook_detail_fingerprint(connection, "nb_1")

        source_repository.upsert(
            SourceRecord(
                source_id="src_1",
                notebook_id="nb_1",
                profile_id="profile_a",
                source_type="url",
                status="processing",
                remote_fingerprint="src-fp-1b",
            )
        )
        source_repository.upsert(
            SourceRecord(
                source_id="src_2",
                notebook_id="nb_1",
                profile_id="profile_a",
                source_type="file",
                status="ready",
                remote_fingerprint="src-fp-2",
            )
        )
        artifact_repository.upsert(
            ArtifactRecord(
                artifact_id="art_1",
                notebook_id="nb_1",
                profile_id="profile_a",
                artifact_type="report",
                status="pending",
                requested_at="2026-03-15T00:06:00Z",
            )
        )
        notebook_repository.upsert(
            NotebookRecord(
                notebook_id="nb_1",
                profile_id="profile_a",
                title="Research Notebook",
                normalized_title="research-notebook",
                summary_preview="Updated summary after detail sync",
                detail_synced_at="2026-03-15T00:10:00Z",
            )
        )

        updated = sync_notebook_detail_fingerprint(connection, "nb_1")
        stored = notebook_repository.get("nb_1")

    assert updated.remote_fingerprint is not None
    assert updated.remote_fingerprint != initial.remote_fingerprint
    assert stored == updated


def test_sync_notebook_detail_fingerprint_rejects_unknown_notebook(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")

        try:
            sync_notebook_detail_fingerprint(connection, "missing")
        except LookupError as error:
            assert "missing" in str(error)
        else:
            raise AssertionError("expected missing notebook to raise LookupError")
