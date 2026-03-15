"""Unit tests for the approval_requests table schema."""

from __future__ import annotations

import sqlite3

import pytest

from notebooklm.local.schema import apply_schema_v1


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    return connection


def test_apply_schema_v1_creates_approval_requests_with_normalized_columns():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)

    columns = connection.execute("PRAGMA table_info(approval_requests)").fetchall()

    assert [row["name"] for row in columns] == [
        "id",
        "trace_id",
        "entity_type",
        "entity_id",
        "action",
        "risk_tier",
        "policy_name",
        "requested_by",
        "requested_at",
        "resolved_at",
        "status",
        "reason",
        "resume_token",
        "decision_json",
    ]

    nullable_by_name = {row["name"]: row["notnull"] == 0 for row in columns}
    assert nullable_by_name["id"] is False
    assert nullable_by_name["trace_id"] is False
    assert nullable_by_name["entity_type"] is False
    assert nullable_by_name["entity_id"] is False
    assert nullable_by_name["action"] is False
    assert nullable_by_name["risk_tier"] is False
    assert nullable_by_name["requested_by"] is False
    assert nullable_by_name["requested_at"] is False
    assert nullable_by_name["status"] is False
    assert nullable_by_name["policy_name"] is True
    assert nullable_by_name["resolved_at"] is True
    assert nullable_by_name["reason"] is True
    assert nullable_by_name["resume_token"] is True
    assert nullable_by_name["decision_json"] is True


def test_approval_requests_enforces_id_prefix_status_and_risk_tier_constraints():
    connection = _connect()

    with connection:
        apply_schema_v1(connection)
        connection.execute(
            """
            INSERT INTO approval_requests (
                id,
                trace_id,
                entity_type,
                entity_id,
                action,
                risk_tier,
                requested_by,
                requested_at,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "appr_valid",
                "trace_1",
                "source_import",
                "src_1",
                "import",
                "T2_KNOWLEDGE_MUTATION",
                "agent",
                "2026-03-15T01:00:00Z",
                "pending",
            ),
        )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO approval_requests (
                    id,
                    trace_id,
                    entity_type,
                    entity_id,
                    action,
                    risk_tier,
                    requested_by,
                    requested_at,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "invalid",
                    "trace_2",
                    "cache_prune",
                    "cache",
                    "prune",
                    "T1_LOCAL_MUTATION",
                    "cli_user",
                    "2026-03-15T01:05:00Z",
                    "pending",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO approval_requests (
                    id,
                    trace_id,
                    entity_type,
                    entity_id,
                    action,
                    risk_tier,
                    requested_by,
                    requested_at,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "appr_invalid_risk",
                    "trace_3",
                    "cache_prune",
                    "cache",
                    "prune",
                    "T4_UNKNOWN",
                    "cli_user",
                    "2026-03-15T01:06:00Z",
                    "pending",
                ),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                """
                INSERT INTO approval_requests (
                    id,
                    trace_id,
                    entity_type,
                    entity_id,
                    action,
                    risk_tier,
                    requested_by,
                    requested_at,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "appr_invalid_status",
                    "trace_4",
                    "cache_prune",
                    "cache",
                    "prune",
                    "T1_LOCAL_MUTATION",
                    "cli_user",
                    "2026-03-15T01:07:00Z",
                    "queued",
                ),
            )
