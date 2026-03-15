"""Unit tests for approval-policy inheritance resolution."""

from __future__ import annotations

from notebooklm.approval_policies import resolve_approval_policy
from notebooklm.local.db import connect_db
from notebooklm.local.repositories import NotebookRecord, NotebookRepository, WorkspaceRecord, WorkspaceRepository
from notebooklm.profiles.manager import ProfileManager


def _seed_profile(connection, *, profile_id: str = "default", approval_policy_json: str | None = None) -> None:
    ProfileManager(connection).create_profile(
        profile_id=profile_id,
        display_name="Default",
        storage_state_path="/tmp/default/storage_state.json",
        browser_profile_path="/tmp/default/browser_profile",
        is_default=True,
        approval_policy_json=approval_policy_json,
    )


def _seed_notebook(
    connection,
    *,
    profile_id: str = "default",
    notebook_id: str = "nb_123",
    approval_policy_json: str | None = None,
) -> None:
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id=notebook_id,
            profile_id=profile_id,
            title="Notebook",
            normalized_title="notebook",
            approval_policy_json=approval_policy_json,
        )
    )


def _seed_workspace(
    connection,
    *,
    profile_id: str = "default",
    workspace_id: str = "ws_123",
    approval_policy_json: str | None = None,
) -> None:
    WorkspaceRepository(connection).upsert(
        WorkspaceRecord(
            id=workspace_id,
            profile_id=profile_id,
            name="Workspace",
            slug="workspace",
            kind="static",
            approval_policy_json=approval_policy_json,
            created_at="2026-03-15T00:00:00Z",
            updated_at="2026-03-15T00:00:00Z",
        )
    )


def test_resolve_approval_policy_defaults_to_manual_when_nothing_is_configured(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(connection)
        _seed_notebook(connection)
        resolved = resolve_approval_policy(
            connection,
            entity_type="source_delete",
            action="delete",
            risk_tier="T3_DESTRUCTIVE",
            profile_id="default",
            notebook_id="nb_123",
        )

    assert resolved.mode == "manual"
    assert resolved.policy_name == "default"
    assert resolved.source == "default"
    assert resolved.match_kind == "default"


def test_resolve_approval_policy_honors_command_workspace_notebook_profile_precedence(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(
            connection,
            approval_policy_json='{"name":"profile-auto","default":"auto"}',
        )
        _seed_notebook(
            connection,
            approval_policy_json='{"name":"notebook-manual","default":"manual"}',
        )
        _seed_workspace(
            connection,
            approval_policy_json='{"name":"workspace-auto","default":"auto"}',
        )

        profile_only = resolve_approval_policy(
            connection,
            entity_type="source_delete",
            action="delete",
            risk_tier="T3_DESTRUCTIVE",
            profile_id="default",
        )
        notebook_override = resolve_approval_policy(
            connection,
            entity_type="source_delete",
            action="delete",
            risk_tier="T3_DESTRUCTIVE",
            profile_id="default",
            notebook_id="nb_123",
        )
        workspace_override = resolve_approval_policy(
            connection,
            entity_type="source_delete",
            action="delete",
            risk_tier="T3_DESTRUCTIVE",
            profile_id="default",
            notebook_id="nb_123",
            workspace_id="ws_123",
        )
        command_override = resolve_approval_policy(
            connection,
            entity_type="source_delete",
            action="delete",
            risk_tier="T3_DESTRUCTIVE",
            profile_id="default",
            notebook_id="nb_123",
            workspace_id="ws_123",
            command_override={"name": "command-manual", "default": "manual"},
        )

    assert (profile_only.mode, profile_only.policy_name, profile_only.source) == (
        "auto",
        "profile-auto",
        "profile",
    )
    assert (notebook_override.mode, notebook_override.policy_name, notebook_override.source) == (
        "manual",
        "notebook-manual",
        "notebook",
    )
    assert (workspace_override.mode, workspace_override.policy_name, workspace_override.source) == (
        "auto",
        "workspace-auto",
        "workspace",
    )
    assert (command_override.mode, command_override.policy_name, command_override.source) == (
        "manual",
        "command-manual",
        "command_override",
    )


def test_resolve_approval_policy_prefers_entity_then_action_then_risk_then_default_rules(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(
            connection,
            approval_policy_json=(
                '{"name":"profile-policy","default":"manual",'
                '"risk_tiers":{"T3_DESTRUCTIVE":"auto"},'
                '"actions":{"delete":"manual"},'
                '"entity_types":{"source_delete":"auto"}}'
            ),
        )

        entity_match = resolve_approval_policy(
            connection,
            entity_type="source_delete",
            action="delete",
            risk_tier="T3_DESTRUCTIVE",
            profile_id="default",
        )
        action_match = resolve_approval_policy(
            connection,
            entity_type="notebook_delete",
            action="delete",
            risk_tier="T3_DESTRUCTIVE",
            profile_id="default",
        )
        risk_match = resolve_approval_policy(
            connection,
            entity_type="cache_prune",
            action="prune",
            risk_tier="T3_DESTRUCTIVE",
            profile_id="default",
        )
        default_match = resolve_approval_policy(
            connection,
            entity_type="cache_prune",
            action="prune",
            risk_tier="T1_LOCAL_MUTATION",
            profile_id="default",
        )

    assert (entity_match.mode, entity_match.match_kind) == ("auto", "entity_type")
    assert (action_match.mode, action_match.match_kind) == ("manual", "action")
    assert (risk_match.mode, risk_match.match_kind) == ("auto", "risk_tier")
    assert (default_match.mode, default_match.match_kind) == ("manual", "default")
