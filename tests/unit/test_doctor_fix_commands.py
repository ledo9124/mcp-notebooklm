"""Standalone tests for doctor-fix repairs without importing the full root CLI."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types

import click
from click.testing import CliRunner

from notebooklm.local.db import connect_db
from notebooklm.local.events import append_run_event, list_run_events
from notebooklm.local.repositories import (
    LeaseRecord,
    LeaseRepository,
    NotebookRecord,
    NotebookRepository,
    QueryResultRecord,
    QueryResultRepository,
    QueryRunRecord,
    QueryRunRepository,
)
from notebooklm.profiles import LEGACY_DEFAULT_PROFILE_ID, ProfileManager


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR_PATH = REPO_ROOT / "src/notebooklm/cli/doctor.py"


def _load_doctor_module():
    package_name = "notebooklm.cli"
    doctor_module_name = "notebooklm.cli.doctor"
    original_package = sys.modules.get(package_name)
    original_doctor_module = sys.modules.get(doctor_module_name)
    created_package = False

    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(DOCTOR_PATH.parent)]
        sys.modules[package_name] = package
        created_package = True

    spec = importlib.util.spec_from_file_location(doctor_module_name, DOCTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[doctor_module_name] = module
    spec.loader.exec_module(module)

    if created_package:
        sys.modules.pop(package_name, None)
    elif original_package is not None:
        sys.modules[package_name] = original_package

    if original_doctor_module is None:
        sys.modules.pop(doctor_module_name, None)
    else:
        sys.modules[doctor_module_name] = original_doctor_module

    return module


register_doctor_commands = _load_doctor_module().register_doctor_commands
DOCTOR_GLOBALS = register_doctor_commands.__globals__


@click.group()
@click.option("--storage", "storage_path", default=None)
@click.pass_context
def doctor_only_cli(ctx: click.Context, storage_path: str | None) -> None:
    """Minimal Click shell that exposes the doctor commands in isolation."""
    ctx.ensure_object(dict)
    ctx.obj["storage_path"] = storage_path
    ctx.obj.setdefault("trace_id", "trc_test_doctor_fix")
    ctx.obj.setdefault("trace", None)


register_doctor_commands(doctor_only_cli)


def _write_legacy_storage(home_dir, *, build_label: str = "bl-legacy-123") -> None:
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


def _seed_default_profile(home_dir, *, profile_id: str = "default") -> Path:
    storage_path = home_dir / "storage_state.json"
    _write_legacy_storage(home_dir)
    browser_profile = home_dir / "browser_profile"
    browser_profile.mkdir(exist_ok=True)

    with connect_db(home_dir / "cache.db") as connection:
        manager = ProfileManager(connection)
        if manager.get_profile(profile_id) is None:
            manager.create_profile(
                profile_id=profile_id,
                display_name="Default",
                account_email="user@example.com",
                storage_state_path=storage_path,
                browser_profile_path=browser_profile,
                is_default=True,
            )
        else:
            manager.update_profile(
                profile_id,
                account_email="user@example.com",
                storage_state_path=storage_path,
                browser_profile_path=browser_profile,
                is_default=True,
            )
    return storage_path


def _seed_leases(home_dir) -> None:
    with connect_db(home_dir / "cache.db") as connection:
        repository = LeaseRepository(connection)
        repository.acquire(
            LeaseRecord(
                id="lease_stale",
                scope_type="workspace",
                scope_id="ws_1",
                holder="agent-a",
                purpose="stale holder",
                advisory=True,
                acquired_at="2000-01-01T00:00:00Z",
                expires_at="2000-01-01T00:10:00Z",
            )
        )
        repository.acquire(
            LeaseRecord(
                id="lease_active",
                scope_type="workspace",
                scope_id="ws_1",
                holder="agent-b",
                purpose="active holder",
                advisory=True,
                acquired_at="2999-01-01T00:00:00Z",
                expires_at="2999-01-01T00:10:00Z",
            )
        )


def _seed_mismatched_snapshot(home_dir) -> None:
    storage_path = home_dir / "storage_state.json"
    _write_legacy_storage(home_dir, build_label="bl-current-123")
    browser_profile = home_dir / "browser_profile"
    browser_profile.mkdir(exist_ok=True)

    with connect_db(home_dir / "cache.db") as connection:
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
        manager.upsert_auth_snapshot(
            "default",
            cookie_fingerprint="cookie:stale",
            csrf_token="csrf_snapshot",
            session_id="session_snapshot",
            build_label="bl-stale-123",
            captured_at="2026-03-15T03:00:00+00:00",
            validated_at="2026-03-15T03:00:30+00:00",
            status="fresh",
            source="refresh_from_homepage",
        )


def _seed_bundle_event(home_dir) -> None:
    with connect_db(home_dir / "cache.db") as connection:
        append_run_event(
            connection,
            "trc_bundle",
            "doctor.check.completed",
            run_id="run_bundle",
            payload={"cookie_value": "secret-cookie", "status": "ok"},
        )


def _seed_history_and_workspace_index_gap(home_dir) -> None:
    storage_path = _seed_default_profile(home_dir)
    with connect_db(home_dir / "cache.db") as connection:
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id="nb_history",
                profile_id="default",
                title="History Notebook",
                normalized_title="history notebook",
                index_synced_at="2026-03-15T05:00:00Z",
                detail_synced_at="2026-03-15T05:00:00Z",
                raw_json='{"id":"nb_history"}',
            )
        )
        QueryRunRepository(connection).upsert(
            QueryRunRecord(
                id="qr_history_1",
                trace_id="trc_history_1",
                profile_id="default",
                notebook_id="nb_history",
                intent="ask",
                mode="answer",
                prompt_text="find the renewal clause",
                prompt_hash="hash-history-1",
                cache_policy="smart",
                route_reason="remote query",
                source_of_truth="remote_http",
                started_at="2026-03-15T03:00:00Z",
                ended_at="2026-03-15T03:00:02Z",
                status="completed",
            )
        )
        QueryResultRepository(connection).upsert(
            QueryResultRecord(
                query_run_id="qr_history_1",
                result_type="answer",
                answer_text="The renewal clause appears in section 4.",
                citations_json='["citation-1"]',
                result_json='{"summary":"renewal clause"}',
                created_at="2026-03-15T03:00:02Z",
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

    assert storage_path.exists()


def _seed_stuck_watch(home_dir) -> None:
    _seed_default_profile(home_dir)
    with connect_db(home_dir / "cache.db") as connection:
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
                    schedule_json,
                    next_run_at,
                    last_run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "watch_1",
                    "default",
                    "source",
                    "src_missing",
                    "local_file_hash",
                    '{"path":"/tmp/missing.txt"}',
                    "active",
                    '{"interval":"hourly"}',
                    "2026-03-15T04:00:00Z",
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
                    "wtr_stuck",
                    "watch_1",
                    "trc_watch_1",
                    "default",
                    "2026-03-15T03:00:00Z",
                    None,
                    "running",
                    None,
                    None,
                    None,
                ),
            )


def _seed_incomplete_notebook_metadata(home_dir) -> Path:
    storage_path = _seed_default_profile(home_dir)
    with connect_db(home_dir / "cache.db") as connection:
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id="nb_resync",
                profile_id="default",
                title="Needs Detail",
                normalized_title="needs detail",
                index_synced_at="2026-03-15T04:00:00Z",
                detail_synced_at=None,
                raw_json=None,
            )
        )
    return storage_path


def test_doctor_fix_dry_run_plans_legacy_profile_mapping(monkeypatch, tmp_path):
    home_dir = tmp_path / "legacy-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_legacy_storage(home_dir)
    (home_dir / "browser_profile").mkdir()

    runner = CliRunner()
    result = runner.invoke(doctor_only_cli, ["doctor", "fix", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "preview"
    assert payload["result"]["summary"] == {"planned": 1, "applied": 0}
    assert payload["result"]["repairs"] == [
        {
            "kind": "migrate_legacy_profile_mapping",
            "path": str(home_dir / "storage_state.json"),
            "description": "Import the legacy storage_state/browser_profile layout into the profile cache.",
            "applied": False,
        }
    ]
    assert home_dir.joinpath("cache.db").exists() is False


def test_doctor_fix_applies_legacy_profile_mapping(monkeypatch, tmp_path):
    home_dir = tmp_path / "legacy-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_legacy_storage(home_dir)
    (home_dir / "browser_profile").mkdir()

    runner = CliRunner()
    result = runner.invoke(doctor_only_cli, ["doctor", "fix", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "repaired"
    assert payload["result"]["summary"] == {"planned": 1, "applied": 1}
    assert home_dir.joinpath("cache.db").is_file()

    with connect_db() as connection:
        manager = ProfileManager(connection)
        profile = manager.require_profile(LEGACY_DEFAULT_PROFILE_ID)
        snapshot = manager.require_auth_snapshot(LEGACY_DEFAULT_PROFILE_ID)

    assert profile.storage_state_path == (home_dir / "storage_state.json").resolve()
    assert profile.browser_profile_path == (home_dir / "browser_profile").resolve()
    assert snapshot.status == "legacy_imported"
    assert snapshot.source == "legacy_import"


def test_doctor_fix_dry_run_plans_stale_lease_cleanup(monkeypatch, tmp_path):
    home_dir = tmp_path / "leases-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    (home_dir / "browser_profile").mkdir()
    _seed_leases(home_dir)

    runner = CliRunner()
    result = runner.invoke(doctor_only_cli, ["doctor", "fix", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "preview"
    assert payload["result"]["summary"] == {"planned": 1, "applied": 0}
    assert payload["result"]["repairs"] == [
        {
            "kind": "expire_stale_leases",
            "path": str(home_dir / "cache.db"),
            "description": "Expire 1 stale lease from the local cache.",
            "applied": False,
        }
    ]

    with connect_db() as connection:
        repository = LeaseRepository(connection)
        assert repository.get("lease_stale") is not None
        assert repository.get("lease_active") is not None


def test_doctor_fix_applies_stale_lease_cleanup(monkeypatch, tmp_path):
    home_dir = tmp_path / "leases-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    (home_dir / "browser_profile").mkdir()
    _seed_leases(home_dir)

    runner = CliRunner()
    result = runner.invoke(doctor_only_cli, ["doctor", "fix", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "repaired"
    assert payload["result"]["summary"] == {"planned": 1, "applied": 1}

    with connect_db() as connection:
        repository = LeaseRepository(connection)
        events = list_run_events(connection, payload["trace_id"])
        assert repository.get("lease_stale") is None
        assert repository.get("lease_active") is not None

    assert [event.kind for event in events] == [
        "doctor.run.started",
        "doctor.repair.completed",
    ]
    assert all(event.run_id == payload["run_id"] for event in events)
    assert events[0].payload["mode"] == "fix"
    assert events[1].payload == {
        "mode": "fix",
        "kind": "expire_stale_leases",
        "path": str(home_dir / "cache.db"),
    }


def test_doctor_fix_rebuilds_fts_indexes_and_vacuums_cache(monkeypatch, tmp_path):
    home_dir = tmp_path / "fts-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _seed_history_and_workspace_index_gap(home_dir)

    runner = CliRunner()
    preview = runner.invoke(doctor_only_cli, ["doctor", "fix", "--dry-run", "--json"])

    assert preview.exit_code == 0, preview.output
    preview_payload = json.loads(preview.output)
    assert [repair["kind"] for repair in preview_payload["result"]["repairs"]] == [
        "rebuild_fts_indexes",
        "vacuum_analyze",
    ]
    assert preview_payload["result"]["summary"] == {"planned": 2, "applied": 0}

    result = runner.invoke(doctor_only_cli, ["doctor", "fix", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "repaired"
    assert payload["result"]["summary"] == {"planned": 2, "applied": 2}

    with connect_db() as connection:
        history_matches = connection.execute(
            "SELECT run_id FROM history_fts WHERE history_fts MATCH ?",
            ("renewal",),
        ).fetchall()
        workspace_matches = connection.execute(
            """
            SELECT notebook_id
            FROM workspace_index_fts
            WHERE workspace_index_fts MATCH ?
            """,
            ("market",),
        ).fetchall()
        events = [
            event
            for event in list_run_events(connection, payload["trace_id"])
            if event.run_id == payload["run_id"]
        ]

    assert [row["run_id"] for row in history_matches] == ["qr_history_1"]
    assert [row["notebook_id"] for row in workspace_matches] == ["nb_history"]
    assert [event.kind for event in events[-3:]] == [
        "doctor.run.started",
        "doctor.repair.completed",
        "doctor.repair.completed",
    ]
    assert [event.payload["kind"] for event in events[-2:]] == [
        "rebuild_fts_indexes",
        "vacuum_analyze",
    ]


def test_doctor_fix_retries_stuck_watch_runs(monkeypatch, tmp_path):
    home_dir = tmp_path / "watch-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _seed_stuck_watch(home_dir)

    runner = CliRunner()
    preview = runner.invoke(doctor_only_cli, ["doctor", "fix", "--dry-run", "--json"])

    assert preview.exit_code == 0, preview.output
    preview_payload = json.loads(preview.output)
    assert [repair["kind"] for repair in preview_payload["result"]["repairs"]] == [
        "retry_stuck_watches",
        "vacuum_analyze",
    ]

    result = runner.invoke(doctor_only_cli, ["doctor", "fix", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    with connect_db() as connection:
        watch_run = connection.execute(
            "SELECT status, ended_at, result_json FROM watch_runs WHERE id = ?",
            ("wtr_stuck",),
        ).fetchone()
        watch = connection.execute(
            "SELECT next_run_at FROM watches WHERE id = ?",
            ("watch_1",),
        ).fetchone()

    result_payload = json.loads(watch_run["result_json"])
    assert watch_run["status"] == "cancelled"
    assert watch_run["ended_at"] == watch["next_run_at"]
    assert result_payload["doctor_repair"] == "retry_stuck_watch"
    assert result_payload["status"] == "cancelled"
    assert payload["result"]["summary"] == {"planned": 2, "applied": 2}


def test_doctor_fix_resyncs_incomplete_notebook_metadata(monkeypatch, tmp_path):
    home_dir = tmp_path / "resync-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    storage_path = _seed_incomplete_notebook_metadata(home_dir)

    class _DummyDoctorClient:
        def __init__(self, auth_tokens):
            self.auth_tokens = auth_tokens

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    calls: list[tuple[str, object]] = []

    async def _fake_sync_notebook_index(client, connection, **kwargs):
        calls.append(("index", kwargs))
        with connection:
            connection.execute(
                """
                UPDATE notebooks
                SET index_synced_at = ?
                WHERE notebook_id = ?
                """,
                ("2026-03-15T06:10:00Z", "nb_resync"),
            )
        return types.SimpleNamespace(
            notebooks=[types.SimpleNamespace(notebook_id="nb_resync")]
        )

    async def _fake_sync_notebook_detail(client, connection, notebook_id, **kwargs):
        calls.append(("detail", notebook_id, kwargs))
        with connection:
            connection.execute(
                """
                UPDATE notebooks
                SET detail_synced_at = ?, raw_json = ?
                WHERE notebook_id = ?
                """,
                ("2026-03-15T06:11:00Z", '{"id":"nb_resync"}', notebook_id),
            )
        return types.SimpleNamespace(notebook_id=notebook_id)

    monkeypatch.setitem(
        DOCTOR_GLOBALS,
        "get_auth_tokens",
        lambda ctx: types.SimpleNamespace(storage_path=storage_path.resolve()),
    )
    monkeypatch.setitem(DOCTOR_GLOBALS, "NotebookLMClient", _DummyDoctorClient)
    monkeypatch.setitem(DOCTOR_GLOBALS, "sync_notebook_index", _fake_sync_notebook_index)
    monkeypatch.setitem(DOCTOR_GLOBALS, "sync_notebook_detail", _fake_sync_notebook_detail)

    runner = CliRunner()
    preview = runner.invoke(doctor_only_cli, ["doctor", "fix", "--dry-run", "--json"])

    assert preview.exit_code == 0, preview.output
    preview_payload = json.loads(preview.output)
    assert preview_payload["result"]["repairs"] == [
        {
            "kind": "resync_notebook_metadata",
            "path": str(home_dir / "cache.db"),
            "description": "Resync metadata for 1 cached notebook with incomplete local detail.",
            "applied": False,
        }
    ]

    result = runner.invoke(doctor_only_cli, ["doctor", "fix", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["summary"] == {"planned": 1, "applied": 1}
    assert calls == [
        (
            "index",
            {
                "profile_id": "default",
                "storage_path": storage_path.resolve(),
                "force_refresh": True,
                "trigger": "doctor_fix",
            },
        ),
        (
            "detail",
            "nb_resync",
            {
                "profile_id": "default",
                "storage_path": storage_path.resolve(),
                "force_refresh": True,
                "trigger": "doctor_fix",
            },
        ),
    ]

    with connect_db() as connection:
        notebook = NotebookRepository(connection).get("nb_resync")

    assert notebook is not None
    assert notebook.index_synced_at == "2026-03-15T06:10:00Z"
    assert notebook.detail_synced_at == "2026-03-15T06:11:00Z"
    assert notebook.raw_json == '{"id":"nb_resync"}'


def test_doctor_warns_when_snapshot_fingerprint_no_longer_matches_storage(monkeypatch, tmp_path):
    home_dir = tmp_path / "auth-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _seed_mismatched_snapshot(home_dir)

    runner = CliRunner()
    result = runner.invoke(doctor_only_cli, ["doctor", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "degraded"
    findings = {finding["check"]: finding for finding in payload["result"]["findings"]}
    assert findings["auth_snapshot_fresh"]["status"] == "warn"
    assert "does not match the current storage cookies" in findings["auth_snapshot_fresh"]["message"]

    with connect_db() as connection:
        events = list_run_events(connection, payload["trace_id"])

    assert events[0].kind == "doctor.run.started"
    assert events[0].run_id == payload["run_id"]
    assert events[0].payload["mode"] == "fast"
    completed = [event for event in events if event.kind == "doctor.check.completed"]
    assert len(completed) == len(payload["result"]["findings"])
    assert all(event.run_id == payload["run_id"] for event in events)
    assert {event.payload["check"] for event in completed} == set(findings)
    assert all(event.payload["mode"] == "fast" for event in completed)


def test_doctor_fix_marks_mismatched_snapshot_invalid(monkeypatch, tmp_path):
    home_dir = tmp_path / "auth-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _seed_mismatched_snapshot(home_dir)

    runner = CliRunner()
    preview = runner.invoke(doctor_only_cli, ["doctor", "fix", "--dry-run", "--json"])

    assert preview.exit_code == 0, preview.output
    preview_payload = json.loads(preview.output)
    assert preview_payload["result"]["repairs"] == [
        {
            "kind": "mark_auth_snapshot_invalid",
            "path": str(home_dir / "storage_state.json"),
            "description": (
                "Mark the persisted auth snapshot invalid because it no longer matches "
                "the current storage cookies."
            ),
            "applied": False,
        }
    ]

    result = runner.invoke(doctor_only_cli, ["doctor", "fix", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "repaired"
    assert payload["result"]["summary"] == {"planned": 1, "applied": 1}

    with connect_db() as connection:
        manager = ProfileManager(connection)
        snapshot = manager.require_auth_snapshot("default")

    assert snapshot.status == "invalid"
    assert snapshot.validated_at is None
    assert snapshot.source == "refresh_from_homepage"


def test_doctor_bundle_json_writes_redacted_support_artifact(monkeypatch, tmp_path):
    home_dir = tmp_path / "bundle-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_legacy_storage(home_dir)
    (home_dir / "browser_profile").mkdir()
    _seed_bundle_event(home_dir)

    runner = CliRunner()
    result = runner.invoke(doctor_only_cli, ["doctor", "bundle", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["route"]["mode"] == "doctor_bundle"
    assert payload["result"]["status"] == "created"
    bundle_path = Path(payload["result"]["bundle_path"])
    assert bundle_path.is_file()
    assert bundle_path.parent == home_dir / "support-bundles"

    bundle = payload["result"]["bundle"]
    assert bundle["doctor"]["status"] in {"healthy", "degraded"}
    assert bundle["db"]["table_counts"]["run_events"] >= 1
    assert any(
        event.get("payload", {}).get("cookie_value") == "<redacted>"
        for event in bundle["recent_events"]
    )

    bundle_text = bundle_path.read_text(encoding="utf-8")
    assert "sid-cookie" not in bundle_text
    assert "secret-cookie" not in bundle_text


def test_support_bundle_create_alias_uses_same_bundle_flow(monkeypatch, tmp_path):
    home_dir = tmp_path / "bundle-home"
    home_dir.mkdir()
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home_dir))
    _write_legacy_storage(home_dir)
    (home_dir / "browser_profile").mkdir()
    _seed_bundle_event(home_dir)

    runner = CliRunner()
    output_path = home_dir / "custom-bundle.json"
    result = runner.invoke(
        doctor_only_cli,
        ["support-bundle", "create", "--json", "--output", str(output_path)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["status"] == "created"
    assert Path(payload["result"]["bundle_path"]) == output_path.resolve()
    assert output_path.is_file()
