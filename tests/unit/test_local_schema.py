"""Unit tests for the local SQLite schema payload."""

from __future__ import annotations

import sqlite3

import pytest

from notebooklm.local.schema import (
    APP_STATE_SINGLETON_KEY,
    HISTORY_TABLES,
    INDEX_NAMES,
    INBOX_TABLES,
    INITIAL_SCHEMA_VERSION,
    LEASE_TABLES,
    MVP_TABLES,
    POST_MVP_RUN_TABLES,
    RADAR_TABLES,
    WORKSPACE_TABLES,
    apply_schema_v1,
)


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _seed_profile_notebook_and_source(connection: sqlite3.Connection) -> None:
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
        connection.execute(
            """
            INSERT INTO sources (
                source_id,
                notebook_id,
                profile_id,
                source_type,
                status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("src_1", "nb_1", "profile_a", "web", "ready"),
        )


def test_apply_schema_v1_creates_all_current_tables_and_indexes():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)

    objects = connection.execute(
        """
        SELECT type, name
        FROM sqlite_master
        WHERE type IN ('table', 'index')
        """
    ).fetchall()
    names_by_type = {
        object_type: {row["name"] for row in objects if row["type"] == object_type}
        for object_type in ("table", "index")
    }

    assert set(MVP_TABLES).issubset(names_by_type["table"])
    assert set(HISTORY_TABLES).issubset(names_by_type["table"])
    assert set(INBOX_TABLES).issubset(names_by_type["table"])
    assert set(RADAR_TABLES).issubset(names_by_type["table"])
    assert set(LEASE_TABLES).issubset(names_by_type["table"])
    assert set(WORKSPACE_TABLES).issubset(names_by_type["table"])
    assert set(POST_MVP_RUN_TABLES).issubset(names_by_type["table"])
    assert set(INDEX_NAMES).issubset(names_by_type["index"])


def test_apply_schema_v1_is_idempotent_and_bootstraps_app_state_schema_version():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)
        apply_schema_v1(connection)

    columns = {
        row["name"]: row
        for row in connection.execute("PRAGMA table_info(app_state)").fetchall()
    }
    app_state = connection.execute(
        "SELECT singleton_key, schema_version FROM app_state"
    ).fetchone()

    assert "schema_version" in columns
    assert columns["schema_version"]["notnull"] == 1
    assert app_state["singleton_key"] == APP_STATE_SINGLETON_KEY
    assert app_state["schema_version"] == INITIAL_SCHEMA_VERSION


def test_profile_scoped_tables_enforce_foreign_keys():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)

    try:
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
                ("nb_missing_profile", "missing", "Title", "title"),
            )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("expected foreign key enforcement for notebooks.profile_id")


def test_apply_schema_v1_creates_profile_and_notebook_policy_columns():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)

    profile_columns = connection.execute("PRAGMA table_info(profiles)").fetchall()
    notebook_columns = connection.execute("PRAGMA table_info(notebooks)").fetchall()

    assert "approval_policy_json" in [row["name"] for row in profile_columns]
    assert "approval_policy_json" in [row["name"] for row in notebook_columns]


def test_apply_schema_v1_creates_radar_tables_with_expected_columns():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)

    watches_columns = connection.execute("PRAGMA table_info(watches)").fetchall()
    watch_runs_columns = connection.execute("PRAGMA table_info(watch_runs)").fetchall()
    source_revisions_columns = connection.execute(
        "PRAGMA table_info(source_revisions)"
    ).fetchall()
    change_events_columns = connection.execute("PRAGMA table_info(change_events)").fetchall()
    delta_briefings_columns = connection.execute(
        "PRAGMA table_info(delta_briefings)"
    ).fetchall()

    assert [row["name"] for row in watches_columns] == [
        "id",
        "profile_id",
        "scope_type",
        "scope_id",
        "watch_kind",
        "policy_json",
        "status",
        "schedule_json",
        "next_run_at",
        "last_run_at",
    ]
    assert [row["name"] for row in watch_runs_columns] == [
        "id",
        "watch_id",
        "trace_id",
        "profile_id",
        "started_at",
        "ended_at",
        "status",
        "signature_before",
        "signature_after",
        "result_json",
    ]
    assert [row["name"] for row in source_revisions_columns] == [
        "id",
        "source_id",
        "revision_key",
        "content_hash",
        "etag",
        "last_modified",
        "fetched_at",
        "metadata_json",
    ]
    assert [row["name"] for row in change_events_columns] == [
        "id",
        "watch_id",
        "source_id",
        "notebook_id",
        "workspace_id",
        "change_kind",
        "severity",
        "state",
        "created_at",
        "data_json",
    ]
    assert [row["name"] for row in delta_briefings_columns] == [
        "id",
        "change_event_id",
        "summary_md",
        "impact_json",
        "recommended_actions_json",
        "created_at",
    ]


def test_apply_schema_v1_creates_leases_table_with_expected_columns():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)

    leases_columns = connection.execute("PRAGMA table_info(leases)").fetchall()

    assert [row["name"] for row in leases_columns] == [
        "id",
        "scope_type",
        "scope_id",
        "holder",
        "purpose",
        "advisory",
        "acquired_at",
        "expires_at",
    ]


def test_apply_schema_v1_creates_workspace_tables_with_expected_columns():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)

    workspace_columns = connection.execute("PRAGMA table_info(workspaces)").fetchall()
    workspace_member_columns = connection.execute(
        "PRAGMA table_info(workspace_members)"
    ).fetchall()
    workspace_rule_columns = connection.execute(
        "PRAGMA table_info(workspace_rules)"
    ).fetchall()
    workspace_index_columns = connection.execute(
        "PRAGMA table_info(workspace_index_entries)"
    ).fetchall()
    workspace_index_fts = connection.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'workspace_index_fts'
        """
    ).fetchone()

    assert [row["name"] for row in workspace_columns] == [
        "id",
        "profile_id",
        "name",
        "slug",
        "description",
        "kind",
        "query_policy_json",
        "approval_policy_json",
        "created_at",
        "updated_at",
    ]
    assert [row["name"] for row in workspace_member_columns] == [
        "id",
        "workspace_id",
        "notebook_id",
        "priority",
        "tags_json",
        "enabled",
        "added_at",
    ]
    assert [row["name"] for row in workspace_rule_columns] == [
        "id",
        "workspace_id",
        "rule_type",
        "rule_json",
    ]
    assert [row["name"] for row in workspace_index_columns] == [
        "id",
        "workspace_id",
        "profile_id",
        "notebook_id",
        "notebook_title",
        "notebook_summary",
        "title_aliases_text",
        "source_titles_text",
        "source_snippets_text",
        "tags_json",
        "recent_query_text",
        "content_text",
        "updated_at",
    ]
    assert workspace_index_fts is not None
    assert "fts5" in workspace_index_fts["sql"].lower()


def test_apply_schema_v1_creates_post_mvp_run_tables_with_expected_columns():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)

    workspace_run_columns = connection.execute("PRAGMA table_info(workspace_runs)").fetchall()
    doctor_run_columns = connection.execute("PRAGMA table_info(doctor_runs)").fetchall()

    assert [row["name"] for row in workspace_run_columns] == [
        "id",
        "trace_id",
        "profile_id",
        "started_at",
        "ended_at",
        "status",
        "workspace_id",
        "mode",
        "query_text",
        "selected_notebooks_json",
        "plan_json",
        "result_json",
    ]
    assert [row["name"] for row in doctor_run_columns] == [
        "id",
        "trace_id",
        "profile_id",
        "started_at",
        "ended_at",
        "status",
        "mode",
        "overall_status",
        "summary_json",
    ]


def test_apply_schema_v1_creates_history_fts_virtual_table_and_supports_match_queries():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)
        connection.execute(
            """
            INSERT INTO history_fts (
                run_id,
                trace_id,
                profile_id,
                prompt_text,
                answer_text,
                notebook_title,
                source_titles
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "qr_history_1",
                "trc_history_1",
                "profile_a",
                "find the renewal clause",
                "The renewal clause appears in section 4.",
                "Vendor Contracts",
                "Master Service Agreement Renewal Addendum",
            ),
        )

    history_fts = connection.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'history_fts'
        """
    ).fetchone()
    matches = connection.execute(
        "SELECT run_id FROM history_fts WHERE history_fts MATCH ? ORDER BY rank",
        ("renewal",),
    ).fetchall()

    assert history_fts is not None
    assert "fts5" in history_fts["sql"].lower()
    assert [row["run_id"] for row in matches] == ["qr_history_1"]


def test_apply_schema_v1_creates_workspace_index_fts_and_supports_match_queries():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)
        connection.execute(
            """
            INSERT INTO workspace_index_fts (
                entry_id,
                workspace_id,
                profile_id,
                notebook_id,
                notebook_title,
                notebook_summary,
                title_aliases_text,
                source_titles_text,
                source_snippets_text,
                tags_text,
                recent_query_text,
                content_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "wsi_workspace_1",
                "ws_market",
                "profile_a",
                "nb_pricing",
                "Pricing Notebook",
                "Quarterly renewal plan",
                "pricing notebook",
                "Renewal Deck",
                "Discount ladder notes",
                "pricing renewal",
                "How did renewals change last quarter?",
                "Pricing Notebook Quarterly renewal plan Renewal Deck Discount ladder notes",
            ),
        )

    workspace_index_fts = connection.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'workspace_index_fts'
        """
    ).fetchone()
    matches = connection.execute(
        "SELECT notebook_id FROM workspace_index_fts WHERE workspace_index_fts MATCH ? ORDER BY rank",
        ("renewal",),
    ).fetchall()

    assert workspace_index_fts is not None
    assert "fts5" in workspace_index_fts["sql"].lower()
    assert [row["notebook_id"] for row in matches] == ["nb_pricing"]


def test_lease_schema_enforces_scope_and_boolean_constraints():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)
        connection.execute(
            """
            INSERT INTO leases (
                id,
                scope_type,
                scope_id,
                holder,
                purpose,
                advisory,
                acquired_at,
                expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "lease_1",
                "workspace",
                "ws_1",
                "agent-a",
                "build index",
                1,
                "2026-03-15T01:00:00Z",
                "2026-03-15T01:15:00Z",
            ),
        )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO leases (
                    id,
                    scope_type,
                    scope_id,
                    holder,
                    purpose,
                    acquired_at,
                    expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "lease_bad_scope",
                    "folder",
                    "ws_1",
                    "agent-a",
                    "invalid scope",
                    "2026-03-15T01:00:00Z",
                    "2026-03-15T01:15:00Z",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO leases (
                    id,
                    scope_type,
                    scope_id,
                    holder,
                    purpose,
                    advisory,
                    acquired_at,
                    expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "lease_bad_advisory",
                    "workspace",
                    "ws_1",
                    "agent-a",
                    "invalid advisory",
                    7,
                    "2026-03-15T01:00:00Z",
                    "2026-03-15T01:15:00Z",
                ),
            )


def test_post_mvp_run_schema_enforces_profile_foreign_keys_and_enums():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)
        _seed_profile_notebook_and_source(connection)
        connection.execute(
            """
            INSERT INTO workspace_runs (
                id,
                trace_id,
                profile_id,
                started_at,
                ended_at,
                status,
                workspace_id,
                mode,
                query_text,
                selected_notebooks_json,
                plan_json,
                result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "wr_1",
                "trc_wr_1",
                "profile_a",
                "2026-03-15T02:00:00Z",
                "2026-03-15T02:00:10Z",
                "completed",
                "ws_1",
                "ask",
                "summarize the sources",
                '["nb_1"]',
                '{"steps":["fanout","synthesize"]}',
                '{"answer":"done"}',
            ),
        )
        connection.execute(
            """
            INSERT INTO doctor_runs (
                id,
                trace_id,
                profile_id,
                started_at,
                ended_at,
                status,
                mode,
                overall_status,
                summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "dr_1",
                "trc_dr_1",
                "profile_a",
                "2026-03-15T03:00:00Z",
                "2026-03-15T03:00:05Z",
                "completed",
                "fast",
                "healthy",
                '{"checks":[{"key":"auth","status":"passed"}]}',
            ),
        )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO workspace_runs (
                    id,
                    trace_id,
                    profile_id,
                    started_at,
                    status,
                    workspace_id,
                    mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "wr_bad_profile",
                    "trc_wr_bad_profile",
                    "missing_profile",
                    "2026-03-15T02:10:00Z",
                    "running",
                    "ws_2",
                    "metadata",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO workspace_runs (
                    id,
                    trace_id,
                    profile_id,
                    started_at,
                    status,
                    workspace_id,
                    mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "wr_bad_mode",
                    "trc_wr_bad_mode",
                    "profile_a",
                    "2026-03-15T02:15:00Z",
                    "running",
                    "ws_2",
                    "draft",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO doctor_runs (
                    id,
                    trace_id,
                    profile_id,
                    started_at,
                    status,
                    mode,
                    overall_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "dr_bad_overall_status",
                    "trc_dr_bad_status",
                    "profile_a",
                    "2026-03-15T03:10:00Z",
                    "completed",
                    "deep",
                    "warn",
                ),
            )


def test_radar_schema_enforces_foreign_keys_and_enums():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)
        _seed_profile_notebook_and_source(connection)
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
                "watch_1",
                "profile_a",
                "source",
                "src_1",
                "web_diff",
                '{"materiality":"normal"}',
                "active",
                '{"interval":"daily"}',
                "2026-03-16T00:00:00Z",
                None,
            ),
        )
        connection.execute(
            """
            INSERT INTO watch_runs (
                id,
                watch_id,
                trace_id,
                profile_id,
                started_at,
                ended_at,
                status,
                signature_before,
                signature_after,
                result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "wtr_1",
                "watch_1",
                "trc_watch_1",
                "profile_a",
                "2026-03-15T01:00:00Z",
                "2026-03-15T01:01:00Z",
                "completed",
                "sig_old",
                "sig_new",
                '{"changed":true}',
            ),
        )
        connection.execute(
            """
            INSERT INTO source_revisions (
                id,
                source_id,
                revision_key,
                content_hash,
                etag,
                last_modified,
                fetched_at,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rev_1",
                "src_1",
                "etag:v1",
                "sha256:abc",
                "etag-1",
                "Sat, 15 Mar 2026 01:00:00 GMT",
                "2026-03-15T01:00:00Z",
                '{"adapter":"web"}',
            ),
        )
        connection.execute(
            """
            INSERT INTO change_events (
                id,
                watch_id,
                source_id,
                notebook_id,
                workspace_id,
                change_kind,
                severity,
                state,
                created_at,
                data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "evt_1",
                "watch_1",
                "src_1",
                "nb_1",
                None,
                "content_diff",
                "medium",
                "new",
                "2026-03-15T01:05:00Z",
                '{"summary":"material change"}',
            ),
        )
        connection.execute(
            """
            INSERT INTO delta_briefings (
                id,
                change_event_id,
                summary_md,
                impact_json,
                recommended_actions_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "brief_1",
                "evt_1",
                "Summary",
                '{"impact":"medium"}',
                '["review"]',
                "2026-03-15T01:06:00Z",
            ),
        )

    with pytest.raises(sqlite3.IntegrityError):
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
                    schedule_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "watch_bad_scope",
                    "profile_a",
                    "folder",
                    "src_1",
                    "web_diff",
                    "{}",
                    "active",
                    "{}",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO watch_runs (
                    id,
                    watch_id,
                    trace_id,
                    profile_id,
                    started_at,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "wtr_bad_status",
                    "watch_1",
                    "trc_watch_bad",
                    "profile_a",
                    "2026-03-15T01:10:00Z",
                    "unknown",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO source_revisions (
                    id,
                    source_id,
                    revision_key,
                    fetched_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    "rev_missing_source",
                    "src_missing",
                    "etag:v2",
                    "2026-03-15T01:11:00Z",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO change_events (
                    id,
                    watch_id,
                    change_kind,
                    severity,
                    state,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "evt_bad_state",
                    "watch_1",
                    "content_diff",
                    "high",
                    "stale",
                    "2026-03-15T01:12:00Z",
                ),
            )
