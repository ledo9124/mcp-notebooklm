"""CLI tests for `notebooklm inbox` triage commands."""

from __future__ import annotations

from dataclasses import replace
import json
from unittest.mock import AsyncMock

from notebooklm.local.db import connect_db
from notebooklm.local.events import list_run_events
from notebooklm.local.repositories import (
    ApprovalRequestRecord,
    ApprovalRequestRepository,
    InboxItemRecord,
    InboxItemRepository,
    NotebookRecord,
    NotebookRepository,
    WorkspaceRecord,
    WorkspaceRepository,
)
from notebooklm.notebooklm_cli import cli
from .conftest import create_mock_client, patch_client_for_module


def _seed_profile(connection, *, approval_policy_json: str | None = None) -> None:
    existing = connection.execute(
        "SELECT profile_id FROM profiles WHERE profile_id = ?",
        ("default",),
    ).fetchone()
    if existing is not None:
        if approval_policy_json is not None:
            with connection:
                connection.execute(
                    "UPDATE profiles SET approval_policy_json = ? WHERE profile_id = ?",
                    (approval_policy_json, "default"),
                )
        return

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
                approval_policy_json,
                created_at,
                updated_at,
                last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "default",
                "Default",
                "default@example.com",
                1,
                "/tmp/default/storage_state.json",
                "/tmp/default/browser_profile",
                approval_policy_json,
                "2026-03-15T00:00:00Z",
                "2026-03-15T00:00:00Z",
                None,
            ),
        )


def _seed_notebook(connection, *, approval_policy_json: str | None = None) -> None:
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id="nb_123",
            profile_id="default",
            title="Inbox Notebook",
            normalized_title="inbox notebook",
            approval_policy_json=approval_policy_json,
        )
    )


def _seed_workspace(connection, *, approval_policy_json: str | None = None) -> None:
    WorkspaceRepository(connection).upsert(
        WorkspaceRecord(
            id="ws_123",
            profile_id="default",
            name="Inbox Workspace",
            slug="inbox-workspace",
            kind="static",
            approval_policy_json=approval_policy_json,
            created_at="2026-03-15T00:00:00Z",
            updated_at="2026-03-15T00:00:00Z",
        )
    )


def _seed_item(
    connection,
    *,
    item_id: str = "item_1",
    state: str = "pending",
    approval_required: bool = True,
    kind: str = "source",
    canonical_uri: str | None = "https://example.com/source",
    rationale_json: str | None = None,
    priority: int = 7,
    workspace_id: str | None = None,
) -> InboxItemRecord:
    item = InboxItemRecord(
        id=item_id,
        profile_id="default",
        notebook_id="nb_123",
        workspace_id=workspace_id,
        origin="deep_research",
        kind=kind,
        state=state,
        title=f"Item {item_id}",
        created_at="2026-03-15T01:00:00Z",
        priority=priority,
        novelty_score=0.6,
        relevance_score=0.8,
        trust_score=0.9,
        approval_required=approval_required,
        canonical_uri=canonical_uri,
        snippet="Short summary",
        rationale_json=rationale_json,
    )
    InboxItemRepository(connection).upsert(item)
    return item


def _seed_default_inbox(tmp_path) -> None:
    with connect_db() as connection:
        _seed_profile(connection)
        _seed_notebook(connection)
        _seed_item(connection)


def test_inbox_list_json_uses_default_profile_and_returns_items(runner, tmp_path):
    _seed_default_inbox(tmp_path)
    with connect_db() as connection:
        _seed_item(connection, item_id="item_2", priority=3, approval_required=False)

    result = runner.invoke(cli, ["inbox", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "INBOX_TRIAGE"
    assert payload["route"]["mode"] == "inbox_list"
    assert payload["route"]["profile_id"] == "default"
    assert payload["route"]["source_of_truth"] == "local_cache"
    assert payload["route"]["cache_mode"] == "offline"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["profile_id"] == "default"
    assert payload["result"]["count"] == 2
    assert [item["id"] for item in payload["result"]["items"]] == ["item_1", "item_2"]


def test_inbox_view_json_decodes_rationale_payload(runner, tmp_path):
    _seed_default_inbox(tmp_path)
    with connect_db() as connection:
        _seed_item(
            connection,
            item_id="item_2",
            rationale_json=json.dumps({"why": "Novel source", "deferred_until": "2026-03-21"}),
        )

    result = runner.invoke(cli, ["inbox", "view", "item_2", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "inbox_view"
    assert payload["route"]["notebook_id"] == "nb_123"
    assert payload["result"]["item"]["id"] == "item_2"
    assert payload["result"]["item"]["rationale"]["why"] == "Novel source"
    assert payload["result"]["item"]["rationale"]["deferred_until"] == "2026-03-21"


def test_inbox_approve_updates_state_and_resolves_pending_approvals(runner, tmp_path):
    _seed_default_inbox(tmp_path)
    with connect_db() as connection:
        ApprovalRequestRepository(connection).upsert(
            ApprovalRequestRecord(
                id="appr_1",
                trace_id="trace_1",
                entity_type="inbox_item",
                entity_id="item_1",
                action="import",
                risk_tier="T2_KNOWLEDGE_MUTATION",
                requested_by="agent",
                requested_at="2026-03-15T01:01:00Z",
                status="pending",
            )
        )

    result = runner.invoke(cli, ["inbox", "approve", "item_1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "INBOX_APPLY"
    assert payload["route"]["mode"] == "inbox_approve"
    assert payload["route"]["notebook_id"] == "nb_123"
    assert payload["result"]["item"]["state"] == "approved"
    assert payload["result"]["approval_requests_resolved"] == 1
    assert payload["cache_updates"]["tables_touched"] == ["approval_requests", "inbox_items"]

    with connect_db() as connection:
        item = InboxItemRepository(connection).get("item_1")
        approval = ApprovalRequestRepository(connection).get("appr_1")
        events = list_run_events(connection, payload["trace_id"])

    assert item is not None
    assert item.state == "approved"
    assert item.decision_at is not None
    assert approval is not None
    assert approval.status == "approved"
    assert [event.kind for event in events] == ["approval.resolved"]
    assert events[0].run_id == payload["run_id"]
    assert events[0].payload == {
        "approval_id": "appr_1",
        "entity_type": "inbox_item",
        "entity_id": "item_1",
        "action": "import",
        "item_id": "item_1",
        "status": "approved",
    }


def test_inbox_reject_updates_state(runner, tmp_path):
    _seed_default_inbox(tmp_path)

    result = runner.invoke(cli, ["inbox", "reject", "item_1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "INBOX_TRIAGE"
    assert payload["route"]["mode"] == "inbox_reject"
    assert payload["result"]["item"]["state"] == "rejected"
    assert payload["cache_updates"]["tables_touched"] == ["inbox_items"]

    with connect_db() as connection:
        item = InboxItemRepository(connection).get("item_1")

    assert item is not None
    assert item.state == "rejected"


def test_inbox_defer_records_deferred_until_in_rationale(runner, tmp_path):
    _seed_default_inbox(tmp_path)

    result = runner.invoke(cli, ["inbox", "defer", "item_1", "--until", "2026-03-21", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "inbox_defer"
    assert payload["result"]["item"]["state"] == "deferred"
    assert payload["result"]["item"]["rationale"]["deferred_until"] == "2026-03-21"
    assert payload["cache_updates"]["tables_touched"] == ["inbox_items"]


def test_inbox_apply_batch_json_approves_matching_items_and_resolves_pending_approvals(runner, tmp_path):
    _seed_default_inbox(tmp_path)
    with connect_db() as connection:
        _seed_item(connection, item_id="item_2", priority=2)
        _seed_item(connection, item_id="item_3", state="deferred", priority=6)
        ApprovalRequestRepository(connection).upsert(
            ApprovalRequestRecord(
                id="appr_1",
                trace_id="trace_1",
                entity_type="inbox_item",
                entity_id="item_1",
                action="import",
                risk_tier="T2_KNOWLEDGE_MUTATION",
                requested_by="agent",
                requested_at="2026-03-15T01:01:00Z",
                status="pending",
            )
        )

    result = runner.invoke(cli, ["inbox", "apply-batch", "--filter", "pending:high", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "INBOX_APPLY"
    assert payload["route"]["mode"] == "inbox_apply_batch"
    assert payload["route"]["profile_id"] == "default"
    assert payload["route"]["source_of_truth"] == "local_cache"
    assert payload["route"]["cache_mode"] == "offline"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["filter"] == "pending:high"
    assert payload["result"]["state"] == "pending"
    assert payload["result"]["priority_band"] == "high"
    assert payload["result"]["matched_count"] == 1
    assert payload["result"]["updated_count"] == 1
    assert payload["result"]["approval_requests_resolved"] == 1
    assert [item["id"] for item in payload["result"]["items"]] == ["item_1"]
    assert payload["result"]["items"][0]["state"] == "approved"
    assert payload["cache_updates"]["tables_touched"] == ["approval_requests", "inbox_items"]

    with connect_db() as connection:
        item_1 = InboxItemRepository(connection).get("item_1")
        item_2 = InboxItemRepository(connection).get("item_2")
        item_3 = InboxItemRepository(connection).get("item_3")
        approval = ApprovalRequestRepository(connection).get("appr_1")
        events = list_run_events(connection, payload["trace_id"])

    assert item_1 is not None
    assert item_1.state == "approved"
    assert item_2 is not None
    assert item_2.state == "pending"
    assert item_3 is not None
    assert item_3.state == "deferred"
    assert approval is not None
    assert approval.status == "approved"
    assert [event.kind for event in events] == ["approval.resolved"]
    assert events[0].run_id == payload["run_id"]
    assert events[0].payload == {
        "approval_id": "appr_1",
        "entity_type": "inbox_item",
        "entity_id": "item_1",
        "action": "import",
        "item_id": "item_1",
        "status": "approved",
    }


def test_inbox_apply_batch_json_returns_noop_when_filter_matches_nothing(runner, tmp_path):
    _seed_default_inbox(tmp_path)

    result = runner.invoke(cli, ["inbox", "apply-batch", "--filter", "pending:low", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["result"]["matched_count"] == 0
    assert payload["result"]["updated_count"] == 0
    assert payload["result"]["approval_requests_resolved"] == 0
    assert payload["result"]["items"] == []
    assert payload["cache_updates"]["tables_touched"] == []

    with connect_db() as connection:
        item = InboxItemRepository(connection).get("item_1")

    assert item is not None
    assert item.state == "pending"


def test_inbox_apply_batch_help_and_invalid_filter(runner, tmp_path):
    help_result = runner.invoke(cli, ["inbox", "apply-batch", "--help"])

    assert help_result.exit_code == 0
    assert "Bulk-approve matching inbox items for later import" in help_result.output
    assert "--filter" in help_result.output

    _seed_default_inbox(tmp_path)
    invalid = runner.invoke(cli, ["inbox", "apply-batch", "--filter", "approved:high", "--json"])

    assert invalid.exit_code == 1
    assert "Unsupported inbox batch state 'approved'" in invalid.output


def test_inbox_import_adds_source_and_marks_item_applied(
    runner,
    tmp_path,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_default_inbox(tmp_path)
    with connect_db() as connection:
        item_repository = InboxItemRepository(connection)
        item = item_repository.get("item_1")
        assert item is not None
        item_repository.upsert(replace(item, state="approved"))

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client = create_mock_client()
        mock_client.sources.add_url = AsyncMock(
            return_value=type(
                "Source",
                (),
                {
                    "id": "src_imported",
                    "title": "Imported Source",
                    "url": "https://example.com/source",
                },
            )()
        )
        mock_client_cls.return_value = mock_client

        result = runner.invoke(cli, ["inbox", "import", "item_1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "INBOX_APPLY"
    assert payload["route"]["mode"] == "inbox_import"
    assert payload["route"]["notebook_id"] == "nb_123"
    assert payload["route"]["source_of_truth"] == "mixed"
    assert payload["route"]["cache_mode"] == "network"
    assert payload["result"]["item"]["state"] == "applied"
    assert payload["result"]["source"]["id"] == "src_imported"
    assert payload["cache_updates"]["tables_touched"] == ["inbox_items"]
    mock_client.sources.add_url.assert_awaited_once_with("nb_123", "https://example.com/source")

    with connect_db() as connection:
        item = InboxItemRepository(connection).get("item_1")
        events = list_run_events(connection, payload["trace_id"])

    assert item is not None
    assert item.state == "applied"
    assert [event.kind for event in events] == ["inbox.item.applied"]
    assert events[0].run_id == payload["run_id"]
    assert events[0].payload == {
        "item_id": "item_1",
        "notebook_id": "nb_123",
        "workspace_id": None,
        "kind": "source",
        "origin": "deep_research",
        "canonical_uri": "https://example.com/source",
    }


def test_inbox_import_requires_approval_when_flagged(
    runner,
    tmp_path,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_default_inbox(tmp_path)

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client_cls.return_value = create_mock_client()
        result = runner.invoke(cli, ["inbox", "import", "item_1", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["route"]["intent"] == "INBOX_APPLY"
    assert payload["route"]["mode"] == "inbox_import"
    assert payload["route"]["notebook_id"] == "nb_123"
    assert payload["route"]["profile_id"] == "default"
    assert payload["route"]["source_of_truth"] == "mixed"
    assert payload["route"]["cache_mode"] == "network"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["code"] == "APPROVAL_REQUIRED"
    assert "requires approval before import" in payload["result"]["message"]
    assert payload["result"]["next_step_kind"] == "approval_token"
    assert payload["result"]["approval_request_created"] is True
    assert payload["result"]["approval_token"].startswith("appr_")
    assert payload["result"]["resume_token"].startswith("resume_")
    assert payload["result"]["approval_request"]["entity_id"] == "item_1"
    assert payload["result"]["approval_request"]["status"] == "pending"
    assert payload["result"]["approval_request"]["policy_name"] == "default"
    assert payload["result"]["policy_name"] == "default"
    assert payload["result"]["policy_source"] == "default"
    assert payload["result"]["policy_match_kind"] == "default"
    assert payload["result"]["policy_mode"] == "manual"
    assert payload["result"]["resume_command"] == (
        "notebooklm inbox import "
        f"item_1 --resume-token {payload['result']['resume_token']}"
    )

    with connect_db() as connection:
        approvals = ApprovalRequestRepository(connection).list_for_entity("inbox_item", "item_1")
        events = list_run_events(connection, payload["trace_id"])

    assert len(approvals) == 1
    assert approvals[0].id == payload["result"]["approval_token"]
    assert approvals[0].policy_name == "default"
    assert approvals[0].resume_token == payload["result"]["resume_token"]
    assert [event.kind for event in events] == ["approval.requested"]
    assert events[0].run_id == payload["run_id"]
    assert events[0].payload == {
        "approval_id": payload["result"]["approval_token"],
        "entity_type": "inbox_item",
        "entity_id": "item_1",
        "action": "import",
        "item_id": "item_1",
        "risk_tier": "T2_KNOWLEDGE_MUTATION",
        "resume_token": payload["result"]["resume_token"],
    }


def test_inbox_import_profile_auto_policy_bypasses_approval(
    runner,
    tmp_path,
    mock_auth,
    mock_fetch_tokens,
):
    with connect_db() as connection:
        _seed_profile(connection, approval_policy_json='{"name":"profile-auto","default":"auto"}')
        _seed_notebook(connection)
        _seed_item(connection)

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client = create_mock_client()
        mock_client.sources.add_url = AsyncMock(
            return_value=type(
                "Source",
                (),
                {
                    "id": "src_imported",
                    "title": "Imported Source",
                    "url": "https://example.com/source",
                },
            )()
        )
        mock_client_cls.return_value = mock_client
        result = runner.invoke(cli, ["inbox", "import", "item_1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "inbox_import"
    assert payload["result"]["item"]["state"] == "applied"
    assert payload["result"]["source"]["id"] == "src_imported"
    assert payload["result"]["approval_requests_resolved"] == 0
    assert payload["cache_updates"]["tables_touched"] == ["inbox_items"]
    mock_client.sources.add_url.assert_awaited_once_with("nb_123", "https://example.com/source")

    with connect_db() as connection:
        approvals = ApprovalRequestRepository(connection).list_for_entity("inbox_item", "item_1")
        events = list_run_events(connection, payload["trace_id"])

    assert approvals == []
    assert [event.kind for event in events] == ["inbox.item.applied"]


def test_inbox_import_workspace_manual_policy_overrides_profile_and_notebook_auto(
    runner,
    tmp_path,
    mock_auth,
    mock_fetch_tokens,
):
    with connect_db() as connection:
        _seed_profile(connection, approval_policy_json='{"name":"profile-auto","default":"auto"}')
        _seed_notebook(connection, approval_policy_json='{"name":"notebook-auto","default":"auto"}')
        _seed_workspace(connection, approval_policy_json='{"name":"workspace-manual","default":"manual"}')
        _seed_item(connection, workspace_id="ws_123")

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client = create_mock_client()
        mock_client.sources.add_url = AsyncMock()
        mock_client_cls.return_value = mock_client
        result = runner.invoke(cli, ["inbox", "import", "item_1", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["result"]["code"] == "APPROVAL_REQUIRED"
    assert payload["result"]["approval_request"]["policy_name"] == "workspace-manual"
    assert payload["result"]["policy_name"] == "workspace-manual"
    assert payload["result"]["policy_source"] == "workspace"
    assert payload["result"]["policy_match_kind"] == "default"
    assert payload["result"]["policy_mode"] == "manual"
    mock_client.sources.add_url.assert_not_awaited()

    with connect_db() as connection:
        approvals = ApprovalRequestRepository(connection).list_for_entity("inbox_item", "item_1")
        events = list_run_events(connection, payload["trace_id"])

    assert len(approvals) == 1
    assert approvals[0].policy_name == "workspace-manual"
    assert [event.kind for event in events] == ["approval.requested"]


def test_inbox_import_accepts_approval_token_and_resolves_pending_request(
    runner,
    tmp_path,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_default_inbox(tmp_path)

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client_cls.return_value = create_mock_client()
        first = runner.invoke(cli, ["inbox", "import", "item_1", "--json"])

    assert first.exit_code == 1, first.output
    approval_token = json.loads(first.output)["result"]["approval_token"]

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client = create_mock_client()
        mock_client.sources.add_url = AsyncMock(
            return_value=type(
                "Source",
                (),
                {
                    "id": "src_imported",
                    "title": "Imported Source",
                    "url": "https://example.com/source",
                },
            )()
        )
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            cli,
            [
                "inbox",
                "import",
                "item_1",
                "--approval-token",
                approval_token,
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "inbox_import"
    assert payload["result"]["item"]["state"] == "applied"
    assert payload["result"]["source"]["id"] == "src_imported"
    assert payload["result"]["approval_requests_resolved"] == 1
    assert payload["cache_updates"]["tables_touched"] == ["approval_requests", "inbox_items"]
    mock_client.sources.add_url.assert_awaited_once_with("nb_123", "https://example.com/source")

    with connect_db() as connection:
        item = InboxItemRepository(connection).get("item_1")
        approval = ApprovalRequestRepository(connection).get(approval_token)
        events = list_run_events(connection, payload["trace_id"])

    assert item is not None
    assert item.state == "applied"
    assert approval is not None
    assert approval.status == "approved"
    assert approval.resolved_at is not None
    assert [event.kind for event in events] == ["approval.resolved", "inbox.item.applied"]
    assert all(event.run_id == payload["run_id"] for event in events)
    assert events[0].payload == {
        "approval_id": approval_token,
        "entity_type": "inbox_item",
        "entity_id": "item_1",
        "action": "import",
        "item_id": "item_1",
        "status": "approved",
    }
    assert events[1].payload == {
        "item_id": "item_1",
        "notebook_id": "nb_123",
        "workspace_id": None,
        "kind": "source",
        "origin": "deep_research",
        "canonical_uri": "https://example.com/source",
    }


def test_inbox_import_resume_token_waits_for_human_decision(
    runner,
    tmp_path,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_default_inbox(tmp_path)

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client_cls.return_value = create_mock_client()
        first = runner.invoke(cli, ["inbox", "import", "item_1", "--json"])

    assert first.exit_code == 1, first.output
    resume_token = json.loads(first.output)["result"]["resume_token"]

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client = create_mock_client()
        mock_client.sources.add_url = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            cli,
            [
                "inbox",
                "import",
                "item_1",
                "--resume-token",
                resume_token,
                "--json",
            ],
        )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["result"]["code"] == "APPROVAL_PENDING"
    assert payload["result"]["next_step_kind"] == "resume_token"
    assert payload["result"]["next_step"] == f"--resume-token {resume_token}"
    assert payload["result"]["approval_status"] == "pending"
    assert payload["result"]["approval_request"]["status"] == "pending"
    assert payload["result"]["resume_command"] == (
        f"notebooklm inbox import item_1 --resume-token {resume_token}"
    )
    mock_client.sources.add_url.assert_not_awaited()


def test_inbox_import_resume_token_succeeds_after_human_approval(
    runner,
    tmp_path,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_default_inbox(tmp_path)

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client_cls.return_value = create_mock_client()
        first = runner.invoke(cli, ["inbox", "import", "item_1", "--json"])

    assert first.exit_code == 1, first.output
    resume_token = json.loads(first.output)["result"]["resume_token"]

    approve = runner.invoke(cli, ["inbox", "approve", "item_1", "--json"])
    assert approve.exit_code == 0, approve.output

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client = create_mock_client()
        mock_client.sources.add_url = AsyncMock(
            return_value=type(
                "Source",
                (),
                {
                    "id": "src_imported",
                    "title": "Imported Source",
                    "url": "https://example.com/source",
                },
            )()
        )
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            cli,
            [
                "inbox",
                "import",
                "item_1",
                "--resume-token",
                resume_token,
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["result"]["item"]["state"] == "applied"
    assert payload["result"]["source"]["id"] == "src_imported"
    assert payload["result"]["approval_requests_resolved"] == 0
    assert payload["cache_updates"]["tables_touched"] == ["inbox_items"]
    mock_client.sources.add_url.assert_awaited_once_with("nb_123", "https://example.com/source")

    with connect_db() as connection:
        item = InboxItemRepository(connection).get("item_1")
        approval = ApprovalRequestRepository(connection).get_by_resume_token(resume_token)
        events = list_run_events(connection, payload["trace_id"])

    assert item is not None
    assert item.state == "applied"
    assert approval is not None
    assert approval.status == "approved"
    assert [event.kind for event in events] == ["inbox.item.applied"]


def test_inbox_import_resume_token_reports_rejected_approval(
    runner,
    tmp_path,
    mock_auth,
    mock_fetch_tokens,
):
    _seed_default_inbox(tmp_path)

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client_cls.return_value = create_mock_client()
        first = runner.invoke(cli, ["inbox", "import", "item_1", "--json"])

    assert first.exit_code == 1, first.output
    resume_token = json.loads(first.output)["result"]["resume_token"]

    reject = runner.invoke(cli, ["inbox", "reject", "item_1", "--json"])
    assert reject.exit_code == 0, reject.output

    with patch_client_for_module("inbox") as mock_client_cls:
        mock_client = create_mock_client()
        mock_client.sources.add_url = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            cli,
            [
                "inbox",
                "import",
                "item_1",
                "--resume-token",
                resume_token,
                "--json",
            ],
        )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["result"]["code"] == "APPROVAL_REJECTED"
    assert payload["result"]["next_step_kind"] == "resume_token"
    assert payload["result"]["approval_status"] == "rejected"
    assert payload["result"]["approval_request"]["status"] == "rejected"
    assert payload["result"]["resume_command"] == (
        f"notebooklm inbox import item_1 --resume-token {resume_token}"
    )
    mock_client.sources.add_url.assert_not_awaited()
