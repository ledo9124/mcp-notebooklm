"""CLI tests for `notebooklm doctor` fast mode."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from notebooklm.auth import AuthTokens
from notebooklm.local.db import connect_db
from notebooklm.local.repositories import NotebookRecord, NotebookRepository
from notebooklm.notebooklm_cli import cli
from notebooklm.profiles.manager import ProfileManager


def _write_storage_state(storage_path, *, build_label: str | None = None) -> None:
    payload = {
        "cookies": [
            {"name": "SID", "value": "test_sid", "domain": ".google.com"},
            {"name": "HSID", "value": "test_hsid", "domain": ".google.com"},
        ]
    }
    if build_label is not None:
        payload["bl"] = build_label
    storage_path.write_text(json.dumps(payload), encoding="utf-8")


def _create_profile_snapshot(
    home_dir,
    storage_path,
    *,
    build_label: str = "boq_labs-tailwind-frontend_20260315.20_p0",
    captured_at: str | None = None,
    status: str = "fresh",
) -> None:
    browser_profile = home_dir / "browser_profile"
    browser_profile.mkdir(exist_ok=True)

    with connect_db() as connection:
        manager = ProfileManager(connection)
        if manager.get_profile("default") is None:
            manager.create_profile(
                profile_id="default",
                display_name="Default",
                account_email="user@example.com",
                storage_state_path=storage_path,
                browser_profile_path=browser_profile,
                is_default=True,
            )
        else:
            manager.update_profile(
                "default",
                account_email="user@example.com",
                storage_state_path=storage_path,
                browser_profile_path=browser_profile,
                is_default=True,
            )
        fingerprint = AuthTokens(
            cookies={"HSID": "test_hsid", "SID": "test_sid"},
            csrf_token="csrf_snapshot",
            session_id="session_snapshot",
            build_label=build_label,
            storage_path=storage_path.resolve(),
        ).cookie_fingerprint
        manager.upsert_auth_snapshot(
            "default",
            cookie_fingerprint=fingerprint,
            csrf_token="csrf_snapshot",
            session_id="session_snapshot",
            build_label=build_label,
            captured_at=captured_at,
            validated_at=captured_at,
            status=status,
            source="refresh_from_homepage",
        )


def test_doctor_json_reports_cold_install_without_creating_db(runner, tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))

    result = runner.invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["freshness"] is None
    assert payload["route"]["intent"] == "DOCTOR"
    assert payload["route"]["mode"] == "fast"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["status"] == "degraded"
    assert payload["result"]["summary"]["failed"] >= 1
    assert payload["result"]["db"]["exists"] is False
    assert home_dir.joinpath("cache.db").exists() is False
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}
    assert "auth_snapshot_present" in findings
    assert "db_openable" in findings


def test_doctor_fix_dry_run_lists_missing_dirs_without_creating_them(
    runner, tmp_path, monkeypatch
):
    home_dir = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))

    result = runner.invoke(cli, ["doctor", "fix", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "DOCTOR"
    assert payload["route"]["mode"] == "doctor_fix"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["status"] == "preview"
    assert payload["result"]["dry_run"] is True
    assert payload["result"]["summary"] == {"planned": 2, "applied": 0}
    assert [repair["path"] for repair in payload["result"]["repairs"]] == [
        str(home_dir),
        str(home_dir / "browser_profile"),
    ]
    assert all(repair["applied"] is False for repair in payload["result"]["repairs"])
    assert home_dir.exists() is False


def test_doctor_fix_applies_missing_dirs(runner, tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))

    result = runner.invoke(cli, ["doctor", "fix", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "repaired"
    assert payload["result"]["dry_run"] is False
    assert payload["result"]["summary"] == {"planned": 2, "applied": 2}
    assert all(repair["applied"] is True for repair in payload["result"]["repairs"])
    assert home_dir.is_dir()
    assert home_dir.joinpath("browser_profile").is_dir()


def test_doctor_json_reports_healthy_when_snapshot_and_db_are_current(
    runner, tmp_path, monkeypatch
):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    storage_path = home_dir / "storage_state.json"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_storage_state(storage_path, build_label="boq_labs-tailwind-frontend_20260315.20_p0")
    _create_profile_snapshot(
        home_dir,
        storage_path,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )

    result = runner.invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["result"]["status"] == "healthy"
    assert payload["result"]["summary"]["warned"] == 0
    assert payload["result"]["summary"]["failed"] == 0
    assert payload["result"]["db"]["schema_version"] is not None
    assert payload["route"]["profile_id"] == "default"


def test_doctor_check_auth_json_limits_findings_to_auth_category(
    runner, tmp_path, monkeypatch
):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    storage_path = home_dir / "storage_state.json"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_storage_state(storage_path, build_label="boq_labs-tailwind-frontend_20260315.20_p0")
    _create_profile_snapshot(
        home_dir,
        storage_path,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )

    result = runner.invoke(cli, ["doctor", "check", "auth", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}

    assert payload["ok"] is True
    assert payload["route"]["mode"] == "doctor_check"
    assert payload["result"]["mode"] == "check"
    assert payload["result"]["category"] == "auth"
    assert set(findings) == {
        "auth_snapshot_present",
        "auth_snapshot_fresh",
        "build_label_present",
    }
    assert findings["auth_snapshot_present"]["status"] == "pass"
    assert findings["auth_snapshot_fresh"]["status"] == "pass"
    assert findings["build_label_present"]["status"] == "pass"


def test_doctor_check_workspace_warns_when_workspace_index_fts_is_stale(
    runner, tmp_path, monkeypatch
):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))

    with connect_db(home_dir / "cache.db") as connection:
        browser_profile = home_dir / "browser_profile"
        browser_profile.mkdir(exist_ok=True)
        ProfileManager(connection).create_profile(
            profile_id="default",
            display_name="Default",
            storage_state_path=home_dir / "storage_state.json",
            browser_profile_path=browser_profile,
            is_default=True,
        )
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id="nb_history",
                profile_id="default",
                title="History Notebook",
                normalized_title="history notebook",
            )
        )
        with connection:
            connection.execute(
                """
                INSERT INTO workspaces (
                    id,
                    profile_id,
                    name,
                    slug,
                    description,
                    kind,
                    query_policy_json,
                    approval_policy_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "ws_market",
                    "default",
                    "Market Intel",
                    "market-intel",
                    "workspace for tests",
                    "static",
                    None,
                    None,
                    "2026-03-15T05:00:00Z",
                    "2026-03-15T05:00:00Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO workspace_index_entries (
                    id,
                    workspace_id,
                    profile_id,
                    notebook_id,
                    notebook_title,
                    notebook_summary,
                    title_aliases_text,
                    source_titles_text,
                    source_snippets_text,
                    tags_json,
                    recent_query_text,
                    content_text,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "wsi_market_nb_history",
                    "ws_market",
                    "default",
                    "nb_history",
                    "History Notebook",
                    "Renewal memo",
                    "history notebook",
                    "Renewal Deck",
                    "renewal source snippet",
                    '["renewal","market"]',
                    "renewal clause summary",
                    "History Notebook Renewal memo Renewal Deck renewal source snippet market",
                    "2026-03-15T05:00:00Z",
                ),
            )

    result = runner.invoke(cli, ["doctor", "check", "workspace", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}

    assert payload["ok"] is False
    assert payload["route"]["mode"] == "doctor_check"
    assert payload["result"]["category"] == "workspace"
    assert findings["workspace_tables_ready"]["status"] == "pass"
    assert findings["workspace_index_fresh"]["status"] == "warn"
    assert "stale" in findings["workspace_index_fresh"]["message"]


def test_doctor_json_reports_corrupted_db_as_broken(runner, tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_storage_state(
        home_dir / "storage_state.json",
        build_label="boq_labs-tailwind-frontend_20260315.21_p0",
    )
    (home_dir / "cache.db").write_text("not a sqlite database", encoding="utf-8")

    result = runner.invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "broken"
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}
    assert findings["db_openable"]["status"] == "fail"
    assert "could not be opened" in findings["db_openable"]["message"]


def test_doctor_plain_output_uses_degraded_exit_code_for_stale_snapshot(
    runner, tmp_path, monkeypatch
):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    storage_path = home_dir / "storage_state.json"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_storage_state(storage_path, build_label="boq_labs-tailwind-frontend_20260315.22_p0")
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    _create_profile_snapshot(home_dir, storage_path, captured_at=stale_ts, status="fresh")

    result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 1, result.output
    assert "Doctor" in result.output
    assert "auth_snapshot_fresh" in result.output
    assert "degraded" in result.output


def test_doctor_json_reports_storage_path_outside_home_as_inconsistent(
    runner, tmp_path, monkeypatch
):
    home_dir = tmp_path / "home"
    external_dir = tmp_path / "external"
    home_dir.mkdir()
    external_dir.mkdir()
    storage_path = external_dir / "storage_state.json"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_storage_state(storage_path, build_label="boq_labs-tailwind-frontend_20260315.23_p0")

    result = runner.invoke(cli, ["--storage", str(storage_path), "doctor", "--json"])

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}
    assert "notebooklm_home_consistent" in findings
    assert "outside NOTEBOOKLM_HOME" in findings["notebooklm_home_consistent"]["message"]


def _stub_auth_tokens(storage_path) -> AuthTokens:
    return AuthTokens(
        cookies={"SID": "test_sid", "HSID": "test_hsid"},
        csrf_token="csrf",
        session_id="session",
        build_label="boq_labs-tailwind-frontend_20260315.24_p0",
        storage_path=storage_path.resolve(),
    )


class _HealthyDoctorClient:
    def __init__(self, auth_tokens):
        self.auth_tokens = auth_tokens
        self.notebooks = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def list(self):
        return []


def test_doctor_deep_json_reports_healthy_when_deep_checks_pass(
    runner, tmp_path, monkeypatch
):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    storage_path = home_dir / "storage_state.json"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_storage_state(storage_path, build_label="boq_labs-tailwind-frontend_20260315.24_p0")
    _create_profile_snapshot(
        home_dir,
        storage_path,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )
    monkeypatch.setattr("notebooklm.cli.doctor.get_auth_tokens", lambda ctx: _stub_auth_tokens(storage_path))
    monkeypatch.setattr("notebooklm.cli.doctor.NotebookLMClient", _HealthyDoctorClient)

    result = runner.invoke(cli, ["doctor", "--deep", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["route"]["mode"] == "deep"
    assert payload["result"]["mode"] == "deep"
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}
    assert findings["cache_integrity_ok"]["status"] == "pass"
    assert findings["foreign_keys_ok"]["status"] == "pass"
    assert findings["fts_health_ok"]["status"] == "pass"
    assert findings["remote_auth_probe"]["status"] == "pass"
    assert findings["rpc_canary"]["status"] == "pass"


def test_doctor_deep_json_reports_remote_auth_probe_failure(
    runner, tmp_path, monkeypatch
):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    storage_path = home_dir / "storage_state.json"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_storage_state(storage_path, build_label="boq_labs-tailwind-frontend_20260315.25_p0")
    _create_profile_snapshot(
        home_dir,
        storage_path,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )
    monkeypatch.setattr(
        "notebooklm.cli.doctor.get_auth_tokens",
        lambda ctx: (_ for _ in ()).throw(RuntimeError("token refresh failed")),
    )

    result = runner.invoke(cli, ["doctor", "--deep", "--json"])

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}
    assert findings["remote_auth_probe"]["status"] == "fail"
    assert "token refresh failed" in findings["remote_auth_probe"]["message"]
    assert findings["rpc_canary"]["status"] == "warn"


def test_doctor_deep_json_reports_hidden_foreign_key_violations(
    runner, tmp_path, monkeypatch
):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    storage_path = home_dir / "storage_state.json"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_storage_state(storage_path, build_label="boq_labs-tailwind-frontend_20260315.26_p0")
    _create_profile_snapshot(
        home_dir,
        storage_path,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )
    with connect_db() as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        with connection:
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
                ("src_broken_fk", "missing_notebook", "default", "web_page", "ready"),
            )
        connection.execute("PRAGMA foreign_keys=ON")

    monkeypatch.setattr("notebooklm.cli.doctor.get_auth_tokens", lambda ctx: _stub_auth_tokens(storage_path))
    monkeypatch.setattr("notebooklm.cli.doctor.NotebookLMClient", _HealthyDoctorClient)

    result = runner.invoke(cli, ["doctor", "--deep", "--json"])

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}
    assert findings["foreign_keys_ok"]["status"] == "fail"
    assert "sources" in findings["foreign_keys_ok"]["message"]
