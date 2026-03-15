"""Unit tests for legacy NOTEBOOKLM_HOME profile bootstrap."""

from __future__ import annotations

import json

from notebooklm.local.db import connect_db
from notebooklm.profiles import LEGACY_DEFAULT_PROFILE_ID, ProfileManager, has_legacy_profile_layout


def _write_legacy_storage(home_dir, *, build_label="bl-legacy-123") -> None:
    (home_dir / "storage_state.json").write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "SID",
                        "value": "sid-cookie",
                        "domain": ".google.com",
                    }
                ],
                "bl": build_label,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_legacy_context(home_dir) -> None:
    (home_dir / "context.json").write_text(
        json.dumps(
            {
                "notebook_id": "nb_legacy",
                "conversation_id": "conv_legacy",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_connect_db_bootstraps_legacy_profile_without_moving_files(monkeypatch, tmp_path):
    """First default DB creation should map the legacy home layout into the DB."""
    home_dir = tmp_path / "legacy-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_legacy_storage(home_dir)
    _write_legacy_context(home_dir)
    (home_dir / "browser_profile").mkdir()

    assert has_legacy_profile_layout() is True

    with connect_db() as connection:
        manager = ProfileManager(connection)
        profile = manager.require_profile(LEGACY_DEFAULT_PROFILE_ID)
        snapshot = manager.require_auth_snapshot(LEGACY_DEFAULT_PROFILE_ID)
        app_state = connection.execute(
            """
            SELECT active_profile_id, current_notebook_id, current_conversation_id
            FROM app_state
            """
        ).fetchone()

    assert profile.is_default is True
    assert profile.storage_state_path == (home_dir / "storage_state.json").resolve()
    assert profile.browser_profile_path == (home_dir / "browser_profile").resolve()
    assert snapshot.cookie_fingerprint
    assert snapshot.build_label == "bl-legacy-123"
    assert snapshot.status == "legacy_imported"
    assert snapshot.source == "legacy_import"
    assert app_state["active_profile_id"] == LEGACY_DEFAULT_PROFILE_ID
    assert app_state["current_notebook_id"] == "nb_legacy"
    assert app_state["current_conversation_id"] == "conv_legacy"
    assert (home_dir / "storage_state.json").exists()
    assert (home_dir / "browser_profile").exists()


def test_connect_db_skips_legacy_import_without_complete_layout(monkeypatch, tmp_path):
    """The legacy import should require both storage_state.json and browser_profile/."""
    home_dir = tmp_path / "legacy-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_legacy_storage(home_dir)

    assert has_legacy_profile_layout() is False

    with connect_db() as connection:
        manager = ProfileManager(connection)
        assert manager.list_profiles() == []


def test_connect_db_bootstraps_legacy_profile_only_once(monkeypatch, tmp_path):
    """Reopening the default DB should not duplicate the imported legacy profile."""
    home_dir = tmp_path / "legacy-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_legacy_storage(home_dir)
    (home_dir / "browser_profile").mkdir()

    with connect_db() as connection:
        manager = ProfileManager(connection)
        assert len(manager.list_profiles()) == 1

    with connect_db() as connection:
        manager = ProfileManager(connection)
        profiles = manager.list_profiles()
        snapshot_rows = connection.execute("SELECT COUNT(*) FROM auth_snapshots").fetchone()[0]

    assert len(profiles) == 1
    assert profiles[0].profile_id == LEGACY_DEFAULT_PROFILE_ID
    assert snapshot_rows == 1
