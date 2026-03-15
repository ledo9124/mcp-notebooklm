"""Contract tests for the core metadata tables in the local cache schema."""

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


def _table_info(connection: sqlite3.Connection, table_name: str) -> dict[str, sqlite3.Row]:
    return {
        row["name"]: row
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _foreign_keys(connection: sqlite3.Connection, table_name: str) -> dict[str, sqlite3.Row]:
    return {
        row["from"]: row
        for row in connection.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    }


def test_notebooks_table_matches_b023a_contract():
    connection = _connect()

    columns = _table_info(connection, "notebooks")
    foreign_keys = _foreign_keys(connection, "notebooks")

    assert list(columns) == [
        "notebook_id",
        "profile_id",
        "title",
        "normalized_title",
        "is_owner",
        "share_visibility",
        "created_at_remote",
        "source_count",
        "artifact_count",
        "note_count",
        "summary_preview",
        "index_synced_at",
        "detail_synced_at",
        "remote_fingerprint",
        "approval_policy_json",
        "tombstoned_at",
        "raw_json",
    ]
    assert columns["normalized_title"]["notnull"] == 1
    assert columns["source_count"]["dflt_value"] == "0"
    assert columns["artifact_count"]["dflt_value"] == "0"
    assert columns["note_count"]["dflt_value"] == "0"
    assert columns["approval_policy_json"]["notnull"] == 0
    assert columns["tombstoned_at"]["notnull"] == 0
    assert columns["raw_json"]["notnull"] == 0
    assert foreign_keys["profile_id"]["table"] == "profiles"


def test_sources_table_matches_b023b_contract():
    connection = _connect()

    columns = _table_info(connection, "sources")
    foreign_keys = _foreign_keys(connection, "sources")

    assert list(columns) == [
        "source_id",
        "notebook_id",
        "profile_id",
        "source_type",
        "title",
        "origin_uri",
        "status",
        "freshness_state",
        "drive_syncable",
        "content_preview",
        "added_at_remote",
        "updated_at_remote",
        "synced_at",
        "remote_fingerprint",
        "tombstoned_at",
        "raw_json",
    ]
    assert columns["source_type"]["notnull"] == 1
    assert columns["status"]["notnull"] == 1
    assert columns["synced_at"]["notnull"] == 0
    assert columns["tombstoned_at"]["notnull"] == 0
    assert foreign_keys["notebook_id"]["table"] == "notebooks"
    assert foreign_keys["profile_id"]["table"] == "profiles"


def test_artifacts_table_matches_b023c_contract():
    connection = _connect()

    columns = _table_info(connection, "artifacts")
    foreign_keys = _foreign_keys(connection, "artifacts")

    assert list(columns) == [
        "artifact_id",
        "notebook_id",
        "profile_id",
        "artifact_type",
        "submode",
        "title",
        "prompt_hash",
        "status",
        "requested_at",
        "last_polled_at",
        "completed_at",
        "download_ref",
        "remote_fingerprint",
        "raw_json",
    ]
    assert columns["artifact_type"]["notnull"] == 1
    assert columns["status"]["notnull"] == 1
    assert columns["requested_at"]["notnull"] == 1
    assert columns["download_ref"]["notnull"] == 0
    assert columns["completed_at"]["notnull"] == 0
    assert foreign_keys["notebook_id"]["table"] == "notebooks"
    assert foreign_keys["profile_id"]["table"] == "profiles"


def test_research_runs_table_matches_b023d_contract():
    connection = _connect()

    columns = _table_info(connection, "research_runs")
    foreign_keys = _foreign_keys(connection, "research_runs")

    assert list(columns) == [
        "research_id",
        "notebook_id",
        "profile_id",
        "mode",
        "query_text",
        "status",
        "discovered_count",
        "imported_count",
        "started_at",
        "updated_at",
        "raw_json",
    ]
    assert columns["mode"]["notnull"] == 1
    assert columns["query_text"]["notnull"] == 1
    assert columns["status"]["notnull"] == 1
    assert columns["discovered_count"]["dflt_value"] == "0"
    assert columns["imported_count"]["dflt_value"] == "0"
    assert foreign_keys["notebook_id"]["table"] == "notebooks"
    assert foreign_keys["profile_id"]["table"] == "profiles"
