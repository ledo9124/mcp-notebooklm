"""Unit tests for the post-MVP research inbox schema."""

from __future__ import annotations

import sqlite3

import pytest

from notebooklm.local.schema import apply_schema_v1


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _seed_profile_and_notebook(connection: sqlite3.Connection) -> None:
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
                "profile_a",
                "Profile A",
                "profile_a@example.com",
                1,
                "/tmp/profile_a/storage_state.json",
                "/tmp/profile_a/browser_profile",
                "2026-03-15T00:00:00Z",
                "2026-03-15T00:00:00Z",
                None,
            ),
        )
        connection.execute(
            """
            INSERT INTO notebooks (
                notebook_id,
                profile_id,
                title,
                normalized_title
            ) VALUES (?, ?, ?, ?)
            """,
            ("nb_1", "profile_a", "Notebook", "notebook"),
        )


def test_apply_schema_v1_creates_inbox_tables_with_expected_columns():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)

    item_columns = connection.execute("PRAGMA table_info(inbox_items)").fetchall()
    cluster_columns = connection.execute("PRAGMA table_info(inbox_clusters)").fetchall()

    assert [row["name"] for row in item_columns] == [
        "id",
        "profile_id",
        "notebook_id",
        "workspace_id",
        "origin",
        "kind",
        "state",
        "priority",
        "novelty_score",
        "relevance_score",
        "trust_score",
        "approval_required",
        "title",
        "canonical_uri",
        "snippet",
        "rationale_json",
        "created_at",
        "decision_at",
        "cluster_id",
    ]
    assert [row["name"] for row in cluster_columns] == [
        "id",
        "fingerprint",
        "canonical_uri",
        "representative_item_id",
    ]

    nullable_by_name = {row["name"]: row["notnull"] == 0 for row in item_columns}
    assert nullable_by_name["id"] is False
    assert nullable_by_name["profile_id"] is False
    assert nullable_by_name["origin"] is False
    assert nullable_by_name["kind"] is False
    assert nullable_by_name["state"] is False
    assert nullable_by_name["priority"] is False
    assert nullable_by_name["approval_required"] is False
    assert nullable_by_name["title"] is False
    assert nullable_by_name["created_at"] is False
    assert nullable_by_name["workspace_id"] is True
    assert nullable_by_name["canonical_uri"] is True
    assert nullable_by_name["decision_at"] is True
    assert nullable_by_name["cluster_id"] is True


def test_inbox_schema_enforces_foreign_keys_enums_score_bounds_and_unique_fingerprints():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)
        _seed_profile_and_notebook(connection)
        connection.execute(
            """
            INSERT INTO inbox_items (
                id,
                profile_id,
                notebook_id,
                origin,
                kind,
                state,
                priority,
                novelty_score,
                relevance_score,
                trust_score,
                approval_required,
                title,
                canonical_uri,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "item_1",
                "profile_a",
                "nb_1",
                "deep_research",
                "source",
                "pending",
                5,
                0.7,
                0.8,
                0.9,
                1,
                "Inbox Item",
                "https://example.com/item-1",
                "2026-03-15T01:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO inbox_clusters (
                id,
                fingerprint,
                canonical_uri,
                representative_item_id
            ) VALUES (?, ?, ?, ?)
            """,
            (
                "cluster_1",
                "fp_1",
                "https://example.com/item-1",
                "item_1",
            ),
        )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO inbox_items (
                    id,
                    profile_id,
                    notebook_id,
                    origin,
                    kind,
                    state,
                    title,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "item_bad_origin",
                    "profile_a",
                    "nb_1",
                    "unsupported",
                    "source",
                    "pending",
                    "Invalid",
                    "2026-03-15T01:05:00Z",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO inbox_items (
                    id,
                    profile_id,
                    notebook_id,
                    origin,
                    kind,
                    state,
                    novelty_score,
                    title,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "item_bad_score",
                    "profile_a",
                    "nb_1",
                    "manual",
                    "report",
                    "pending",
                    1.5,
                    "Invalid Score",
                    "2026-03-15T01:06:00Z",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO inbox_items (
                    id,
                    profile_id,
                    notebook_id,
                    origin,
                    kind,
                    state,
                    title,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "item_missing_profile",
                    "missing",
                    "nb_1",
                    "manual",
                    "report",
                    "pending",
                    "Missing Profile",
                    "2026-03-15T01:07:00Z",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO inbox_clusters (
                    id,
                    fingerprint,
                    canonical_uri
                ) VALUES (?, ?, ?)
                """,
                (
                    "cluster_2",
                    "fp_1",
                    "https://example.com/item-1",
                ),
            )
