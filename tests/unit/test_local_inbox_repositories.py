"""Unit tests for research inbox repository helpers."""

from __future__ import annotations

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import (
    InboxClusterRecord,
    InboxClusterRepository,
    InboxItemRecord,
    InboxItemRepository,
    NotebookRecord,
    NotebookRepository,
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


def _seed_notebook(connection, profile_id: str, notebook_id: str = "nb_1") -> None:
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id=notebook_id,
            profile_id=profile_id,
            title="Notebook",
            normalized_title="notebook",
        )
    )


def test_inbox_item_repository_supports_crud_scoped_queries_and_cluster_lookup(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        _seed_notebook(connection, "profile_b", notebook_id="nb_b")

        item_repository = InboxItemRepository(connection)
        cluster_repository = InboxClusterRepository(connection)

        first = InboxItemRecord(
            id="item_1",
            profile_id="profile_a",
            notebook_id="nb_a",
            origin="deep_research",
            kind="source",
            state="pending",
            title="Alpha",
            created_at="2026-03-15T01:00:00Z",
            priority=8,
            novelty_score=0.7,
            relevance_score=0.9,
            trust_score=0.8,
            canonical_uri="https://example.com/alpha",
        )
        second = InboxItemRecord(
            id="item_2",
            profile_id="profile_a",
            notebook_id="nb_a",
            origin="manual",
            kind="report",
            state="pending",
            title="Beta",
            created_at="2026-03-15T01:05:00Z",
            priority=4,
            approval_required=False,
        )
        other_profile = InboxItemRecord(
            id="item_3",
            profile_id="profile_b",
            notebook_id="nb_b",
            origin="change_radar",
            kind="replacement",
            state="approved",
            title="Gamma",
            created_at="2026-03-15T01:10:00Z",
            priority=3,
        )

        item_repository.upsert(first)
        item_repository.upsert(second)
        item_repository.upsert(other_profile)

        cluster_repository.upsert(
            InboxClusterRecord(
                id="cluster_1",
                fingerprint="fp_alpha",
                canonical_uri="https://example.com/alpha",
                representative_item_id="item_1",
            )
        )
        item_repository.upsert(
            InboxItemRecord(
                id="item_1",
                profile_id="profile_a",
                notebook_id="nb_a",
                origin="deep_research",
                kind="source",
                state="pending",
                title="Alpha Updated",
                created_at="2026-03-15T01:00:00Z",
                priority=9,
                novelty_score=0.75,
                relevance_score=0.95,
                trust_score=0.85,
                canonical_uri="https://example.com/alpha",
                cluster_id="cluster_1",
            )
        )
        item_repository.upsert(
            InboxItemRecord(
                id="item_4",
                profile_id="profile_a",
                notebook_id="nb_a",
                origin="manual",
                kind="source",
                state="pending",
                title="Delta",
                created_at="2026-03-15T01:07:00Z",
                priority=6,
                cluster_id="cluster_1",
            )
        )

        fetched = item_repository.get("item_1")
        profile_rows = item_repository.list_for_profile("profile_a")
        pending_rows = item_repository.list_for_profile("profile_a", state="pending")
        notebook_rows = item_repository.list_for_notebook("nb_a")
        cluster_rows = item_repository.list_for_cluster("cluster_1")

        item_repository.delete("item_3")

    assert fetched is not None
    assert fetched.title == "Alpha Updated"
    assert fetched.cluster_id == "cluster_1"
    assert [record.id for record in profile_rows] == ["item_1", "item_4", "item_2"]
    assert pending_rows == profile_rows
    assert notebook_rows == profile_rows
    assert [record.id for record in cluster_rows] == ["item_1", "item_4"]

    with connect_db(db_path) as connection:
        assert InboxItemRepository(connection).get("item_3") is None


def test_inbox_cluster_repository_supports_fingerprint_lookup_and_nulls_representative_on_delete(
    tmp_path,
):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")

        item_repository = InboxItemRepository(connection)
        cluster_repository = InboxClusterRepository(connection)

        item_repository.upsert(
            InboxItemRecord(
                id="item_1",
                profile_id="profile_a",
                notebook_id="nb_a",
                origin="deep_research",
                kind="source",
                state="pending",
                title="Representative",
                created_at="2026-03-15T02:00:00Z",
            )
        )
        cluster_repository.upsert(
            InboxClusterRecord(
                id="cluster_1",
                fingerprint="fp_rep",
                representative_item_id="item_1",
            )
        )

        fetched = cluster_repository.get("cluster_1")
        by_fingerprint = cluster_repository.get_by_fingerprint("fp_rep")

        item_repository.delete("item_1")
        after_delete = cluster_repository.get("cluster_1")

    assert fetched is not None
    assert fetched == by_fingerprint
    assert after_delete is not None
    assert after_delete.representative_item_id is None
