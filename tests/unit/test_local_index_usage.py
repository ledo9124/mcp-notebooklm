"""Planner and contract checks for MVP cache indexes."""

from __future__ import annotations

import sqlite3

from notebooklm.local.schema import apply_schema_v1


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    with connection:
        apply_schema_v1(connection)
    return connection


def _insert_profile(connection: sqlite3.Connection, profile_id: str) -> None:
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


def _insert_notebook(
    connection: sqlite3.Connection,
    *,
    notebook_id: str,
    profile_id: str,
    title: str,
    normalized_title: str,
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO notebooks (
                notebook_id,
                profile_id,
                title,
                normalized_title
            ) VALUES (?, ?, ?, ?)
            """,
            (notebook_id, profile_id, title, normalized_title),
        )


def test_notebooks_profile_title_index_matches_b026a_contract():
    connection = _connect()

    index_row = next(
        row
        for row in connection.execute("PRAGMA index_list(notebooks)").fetchall()
        if row["name"] == "idx_notebooks_profile_normalized_title"
    )
    index_columns = [
        row["name"]
        for row in connection.execute(
            "PRAGMA index_info(idx_notebooks_profile_normalized_title)"
        ).fetchall()
    ]

    assert index_row["unique"] == 0
    assert index_columns == ["profile_id", "normalized_title"]


def test_notebooks_lookup_plan_uses_profile_title_index():
    connection = _connect()
    _insert_profile(connection, "profile_a")
    _insert_profile(connection, "profile_b")
    _insert_notebook(
        connection,
        notebook_id="nb_a_match",
        profile_id="profile_a",
        title="Quarterly Report",
        normalized_title="quarterly-report",
    )
    _insert_notebook(
        connection,
        notebook_id="nb_a_other",
        profile_id="profile_a",
        title="Roadmap",
        normalized_title="roadmap",
    )
    _insert_notebook(
        connection,
        notebook_id="nb_b_same_title",
        profile_id="profile_b",
        title="Quarterly Report",
        normalized_title="quarterly-report",
    )

    plan_rows = connection.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT notebook_id
        FROM notebooks
        WHERE profile_id = ? AND normalized_title = ?
        """,
        ("profile_a", "quarterly-report"),
    ).fetchall()
    detail_text = " ".join(str(row["detail"]) for row in plan_rows)

    matched = connection.execute(
        """
        SELECT notebook_id
        FROM notebooks
        WHERE profile_id = ? AND normalized_title = ?
        """,
        ("profile_a", "quarterly-report"),
    ).fetchall()

    assert "USING INDEX idx_notebooks_profile_normalized_title" in detail_text
    assert [row["notebook_id"] for row in matched] == ["nb_a_match"]
