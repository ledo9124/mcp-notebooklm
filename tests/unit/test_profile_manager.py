"""Unit tests for the local profile manager."""

from __future__ import annotations

import pytest

from notebooklm.local.db import connect_db
from notebooklm.profiles.manager import ProfileManager


def test_profile_manager_persists_profiles_snapshots_and_active_selection(tmp_path):
    """Profiles, snapshots, and the active selection should survive a reopen."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        manager = ProfileManager(connection)
        created = manager.create_profile(
            profile_id="default",
            display_name="Default",
            account_email="user@example.com",
            storage_state_path=tmp_path / "storage_state.json",
            browser_profile_path=tmp_path / "browser_profile",
            is_default=True,
            approval_policy_json='{"name":"profile-default","default":"manual"}',
        )
        snapshot = manager.upsert_auth_snapshot(
            "default",
            cookie_fingerprint="cookie:abc",
            csrf_token="csrf-token",
            session_id="session-id",
            build_label="prod-123",
            status="fresh",
            source="login",
        )
        active = manager.switch_profile("default")

    with connect_db(db_path) as connection:
        manager = ProfileManager(connection)
        persisted_profile = manager.require_profile("default")
        persisted_snapshot = manager.require_auth_snapshot("default")
        active_profile = manager.get_active_profile()

    assert created.profile_id == "default"
    assert created.is_default is True
    assert created.approval_policy_json == '{"name":"profile-default","default":"manual"}'
    assert snapshot.build_label == "prod-123"
    assert active.profile_id == "default"
    assert persisted_profile.account_email == "user@example.com"
    assert persisted_profile.approval_policy_json == '{"name":"profile-default","default":"manual"}'
    assert persisted_profile.storage_state_path == (tmp_path / "storage_state.json").resolve()
    assert persisted_snapshot.session_id == "session-id"
    assert active_profile is not None
    assert active_profile.profile_id == "default"


def test_profile_manager_updates_fields_and_keeps_a_single_default(tmp_path):
    """Promoting a profile to default should clear the old default and persist updates."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        manager = ProfileManager(connection)
        manager.create_profile(
            profile_id="default",
            display_name="Default",
            storage_state_path=tmp_path / "default.json",
            browser_profile_path=tmp_path / "default-browser",
        )
        updated = manager.create_profile(
            profile_id="work",
            display_name="Work",
            storage_state_path=tmp_path / "work.json",
            browser_profile_path=tmp_path / "work-browser",
            account_email="work@example.com",
            is_default=True,
        )
        renamed = manager.update_profile(
            "work",
            display_name="Work Profile",
            approval_policy_json='{"name":"work-auto","default":"auto"}',
            last_login_at="2026-03-15T00:00:00+00:00",
        )
        profiles = {profile.profile_id: profile for profile in manager.list_profiles()}

    assert updated.is_default is True
    assert renamed.display_name == "Work Profile"
    assert renamed.approval_policy_json == '{"name":"work-auto","default":"auto"}'
    assert renamed.last_login_at == "2026-03-15T00:00:00+00:00"
    assert profiles["default"].is_default is False
    assert profiles["work"].is_default is True


def test_profile_manager_delete_cascades_snapshots_and_clears_active_profile(tmp_path):
    """Deleting a profile should remove its snapshot and clear the active profile."""
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        manager = ProfileManager(connection)
        manager.create_profile(
            profile_id="default",
            display_name="Default",
            storage_state_path=tmp_path / "storage_state.json",
            browser_profile_path=tmp_path / "browser_profile",
        )
        manager.upsert_auth_snapshot(
            "default",
            cookie_fingerprint="cookie:abc",
            csrf_token="csrf-token",
            session_id="session-id",
            build_label="prod-123",
        )
        manager.switch_profile("default")

        assert manager.delete_profile("default") is True
        assert manager.get_profile("default") is None
        assert manager.get_auth_snapshot("default") is None
        assert manager.get_active_profile() is None

        with pytest.raises(KeyError, match="Unknown profile"):
            manager.switch_profile("missing")
