"""Unit tests for the approval-request repository helpers."""

from __future__ import annotations

import pytest

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import ApprovalRequestRecord, ApprovalRequestRepository


def test_approval_request_repository_supports_crud_queries_and_resolution(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        repository = ApprovalRequestRepository(connection)

        pending = ApprovalRequestRecord(
            id="appr_1",
            trace_id="trace_1",
            entity_type="source_import",
            entity_id="src_1",
            action="import",
            risk_tier="T2_KNOWLEDGE_MUTATION",
            requested_by="agent",
            requested_at="2026-03-15T01:00:00Z",
            status="pending",
            reason="Need approval before importing sources",
            resume_token="resume_1",
        )
        other = ApprovalRequestRecord(
            id="appr_2",
            trace_id="trace_2",
            entity_type="cache_prune",
            entity_id="cache",
            action="prune",
            risk_tier="T1_LOCAL_MUTATION",
            policy_name="workspace-default",
            requested_by="cli_user",
            requested_at="2026-03-15T02:00:00Z",
            resolved_at="2026-03-15T02:01:00Z",
            status="approved",
            decision_json='{"approved": true}',
        )

        repository.upsert(pending)
        repository.upsert(other)
        repository.upsert(
            ApprovalRequestRecord(
                id="appr_1",
                trace_id="trace_1",
                entity_type="source_import",
                entity_id="src_1",
                action="import",
                risk_tier="T2_KNOWLEDGE_MUTATION",
                requested_by="agent",
                requested_at="2026-03-15T01:00:00Z",
                status="pending",
                reason="Updated explanation",
                resume_token="resume_1",
            )
        )

        fetched = repository.get("appr_1")
        resume_fetched = repository.get_by_resume_token("resume_1")
        pending_rows = repository.list_pending()
        entity_rows = repository.list_for_entity("source_import", "src_1")

        repository.resolve(
            "appr_1",
            status="approved",
            resolved_at="2026-03-15T01:02:00Z",
            decision_json='{"approved": true, "by": "human"}',
        )
        resolved = repository.get("appr_1")
        pending_after_resolution = repository.list_pending()

        repository.delete("appr_2")

    assert fetched is not None
    assert resume_fetched == fetched
    assert fetched.reason == "Updated explanation"
    assert pending_rows == [fetched]
    assert entity_rows == [fetched]
    assert resolved is not None
    assert resolved.status == "approved"
    assert resolved.resolved_at == "2026-03-15T01:02:00Z"
    assert resolved.decision_json == '{"approved": true, "by": "human"}'
    assert pending_after_resolution == []

    with connect_db(db_path) as connection:
        assert ApprovalRequestRepository(connection).get("appr_2") is None


def test_approval_request_repository_requires_terminal_resolution_status(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        repository = ApprovalRequestRepository(connection)
        repository.upsert(
            ApprovalRequestRecord(
                id="appr_1",
                trace_id="trace_1",
                entity_type="doctor_repair",
                entity_id="repair_1",
                action="repair",
                risk_tier="T1_LOCAL_MUTATION",
                requested_by="doctor",
                requested_at="2026-03-15T03:00:00Z",
                status="pending",
            )
        )

        with pytest.raises(ValueError, match="terminal"):
            repository.resolve(
                "appr_1",
                status="pending",
                resolved_at="2026-03-15T03:01:00Z",
            )
