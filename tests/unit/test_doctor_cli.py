"""Unit tests for the fast local doctor command."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from click.testing import CliRunner

from notebooklm.auth import AuthTokens
from notebooklm.notebooklm_cli import cli
from notebooklm.profiles.manager import ProfileManager


def _write_storage_state(home, *, build_label: str = "boq_labs-tailwind-frontend_20260315.10_p0"):
    storage_path = home / "storage_state.json"
    storage_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "SID", "value": "test_sid", "domain": ".google.com"},
                    {"name": "HSID", "value": "test_hsid", "domain": ".google.com"},
                ],
                "bl": build_label,
            }
        ),
        encoding="utf-8",
    )
    return storage_path


def _seed_profile_snapshot(
    home,
    storage_path,
    *,
    captured_at: str,
    build_label: str = "boq_labs-tailwind-frontend_20260315.10_p0",
    status: str = "fresh",
):
    browser_profile = home / "browser_profile"
    browser_profile.mkdir(exist_ok=True)

    manager = ProfileManager.open()
    try:
        if manager.get_profile("default") is None:
            manager.create_profile(
                profile_id="default",
                display_name="Default",
                account_email="user@example.com",
                storage_state_path=storage_path,
                browser_profile_path=browser_profile,
                is_default=True,
            )
        manager.upsert_auth_snapshot(
            "default",
            cookie_fingerprint=AuthTokens(
                cookies={"HSID": "test_hsid", "SID": "test_sid"},
                csrf_token="csrf_snapshot",
                session_id="session_snapshot",
                build_label=build_label,
                storage_path=storage_path.resolve(),
            ).cookie_fingerprint,
            csrf_token="csrf_snapshot",
            session_id="session_snapshot",
            build_label=build_label,
            captured_at=captured_at,
            validated_at=captured_at,
            status=status,
            source="refresh_from_homepage",
        )
    finally:
        manager.close()


def test_doctor_json_reports_healthy_state(monkeypatch, tmp_path):
    """Healthy auth/profile/cache state should exit cleanly with a green diagnosis."""
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(tmp_path))
    storage_path = _write_storage_state(tmp_path)
    _seed_profile_snapshot(
        tmp_path,
        storage_path,
        captured_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}

    assert payload["ok"] is True
    assert payload["route"]["intent"] == "DOCTOR"
    assert payload["route"]["mode"] == "fast"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["freshness"] is None
    assert payload["result"]["status"] == "healthy"
    assert payload["result"]["summary"]["failed"] == 0
    assert payload["result"]["summary"]["warned"] == 0
    assert findings["auth_snapshot_present"]["status"] == "pass"
    assert findings["db_openable"]["status"] == "pass"
    assert findings["schema_current"]["status"] == "pass"


def test_doctor_json_reports_cold_install_as_degraded_without_creating_db(monkeypatch, tmp_path):
    """A clean NOTEBOOKLM_HOME without auth or DB should degrade, not break."""
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}

    assert payload["ok"] is False
    assert payload["result"]["status"] == "degraded"
    assert findings["auth_snapshot_present"]["status"] == "warn"
    assert findings["db_openable"]["status"] == "warn"
    assert findings["schema_current"]["status"] == "warn"
    assert findings["write_permissions_ok"]["status"] == "pass"
    assert not (tmp_path / "cache.db").exists()


def test_doctor_json_reports_corrupted_db_as_broken(monkeypatch, tmp_path):
    """Unreadable SQLite state should produce the broken exit code and a hard failure."""
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(tmp_path))
    (tmp_path / "cache.db").write_text("not a sqlite database", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}

    assert payload["ok"] is False
    assert payload["result"]["status"] == "broken"
    assert findings["db_openable"]["status"] == "fail"
    assert findings["schema_current"]["status"] == "fail"


def test_doctor_help_is_exposed_at_root(runner: CliRunner | None = None):
    """The root shell should expose the fast doctor command."""
    runner = runner or CliRunner()
    result = runner.invoke(cli, ["doctor", "--help"])

    assert result.exit_code == 0
    assert "Run fast local health checks" in result.output
    assert "check" in result.output
    assert "fix" in result.output
    assert "--json" in result.output


def test_doctor_check_help_lists_supported_categories(runner: CliRunner | None = None):
    """The targeted doctor check surface should advertise each supported category."""
    runner = runner or CliRunner()
    result = runner.invoke(cli, ["doctor", "check", "--help"])

    assert result.exit_code == 0
    assert "auth" in result.output
    assert "db" in result.output
    assert "workspace" in result.output
    assert "radar" in result.output
    assert "inbox" in result.output
