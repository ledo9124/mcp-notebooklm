"""CLI tests for `notebooklm route` diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from notebooklm.cli.helpers import set_current_notebook
from notebooklm.local.db import connect_db
from notebooklm.local.repositories import NotebookRecord, NotebookRepository, SyncRunRecord, SyncRunRepository
from notebooklm.notebooklm_cli import cli
from notebooklm.profiles.manager import ProfileManager
from notebooklm.sync import NOTEBOOK_DETAIL_SCOPE, NOTEBOOK_INDEX_SCOPE


@pytest.fixture
def runner():
    return CliRunner()


def _prepare_local_home(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)
    (home / "storage_state.json").write_text("{}", encoding="utf-8")
    (home / "browser_profile").mkdir(exist_ok=True)
    with connect_db() as connection:
        manager = ProfileManager(connection)
        if manager.get_profile("default") is None:
            manager.create_profile(
                profile_id="default",
                display_name="Default",
                storage_state_path=str(home / "storage_state.json"),
                browser_profile_path=str(home / "browser_profile"),
                is_default=True,
            )


def _seed_notebook(notebook_id: str, title: str) -> None:
    with connect_db() as connection:
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id=notebook_id,
                profile_id="default",
                title=title,
                normalized_title=title.casefold(),
            )
        )


def _seed_sync(scope: str, ended_at: str, *, target_id: str | None = None) -> None:
    with connect_db() as connection:
        SyncRunRepository(connection).upsert(
            SyncRunRecord(
                id=f"sr_{scope}_{target_id or 'root'}",
                trace_id=f"trc_{scope}_{target_id or 'root'}",
                profile_id="default",
                scope=scope,
                target_id=target_id,
                trigger="test",
                started_at=ended_at,
                ended_at=ended_at,
                status="completed",
            )
        )


def test_route_explain_reports_structured_command_precedence(runner, monkeypatch, tmp_path):
    _prepare_local_home(monkeypatch, tmp_path)

    result = runner.invoke(cli, ["route", "explain", "generate report --format study-guide"])

    assert result.exit_code == 0, result.output
    assert "Structured command wins" in result.output
    assert "Command path: generate report" in result.output
    assert "NL classification" in result.output
    assert "notebook-routing heuristics are skipped" in result.output


def test_route_explain_reports_generation_resolution_and_freshness(
    runner,
    monkeypatch,
    tmp_path,
):
    _prepare_local_home(monkeypatch, tmp_path)
    _seed_notebook("nb_pricing", "Pricing")
    _seed_sync(NOTEBOOK_INDEX_SCOPE, "2026-03-15T06:09:00+00:00")
    _seed_sync(
        NOTEBOOK_DETAIL_SCOPE,
        "2026-03-15T06:09:30+00:00",
        target_id="nb_pricing",
    )
    set_current_notebook("nb_pricing", title="Pricing")

    result = runner.invoke(cli, ["route", "explain", "summarize current notebook"])

    assert result.exit_code == 0, result.output
    assert "Intent: GENERATION" in result.output
    assert "Workflow: generation workflow" in result.output
    assert "Source: current_context" in result.output
    assert "Notebook ID: nb_pricing" in result.output
    assert "Notebook index age:" in result.output
    assert "Notebook detail age:" in result.output
    assert "Source of truth: remote_http" in result.output
    assert "smart mode still executes GENERATION remotely" in result.output


def test_route_explain_reports_offline_block_for_remote_generation(
    runner,
    monkeypatch,
    tmp_path,
):
    _prepare_local_home(monkeypatch, tmp_path)
    _seed_notebook("nb_pricing", "Pricing")
    set_current_notebook("nb_pricing", title="Pricing")

    result = runner.invoke(
        cli,
        ["route", "explain", "summarize current notebook", "--cache-mode", "offline"],
    )

    assert result.exit_code == 0, result.output
    assert "Blocked by cache mode:" in result.output
    assert "offline mode does not allow remote GENERATION requests" in result.output


def test_route_explain_defers_freshness_when_source_query_has_no_target(
    runner,
    monkeypatch,
    tmp_path,
):
    _prepare_local_home(monkeypatch, tmp_path)
    _seed_notebook("nb_pricing", "Pricing")

    result = runner.invoke(cli, ["route", "explain", "which notebooks have PDF sources?"])

    assert result.exit_code == 0, result.output
    assert "Intent: LOCAL_METADATA" in result.output
    assert "Metadata scope: (pending)" in result.output
    assert "detail freshness" in result.output
    assert "target is known" in result.output
    assert "Decision: pending notebook-detail freshness" in result.output


def test_route_dry_run_reports_generation_target_and_transport(
    runner,
    monkeypatch,
    tmp_path,
):
    _prepare_local_home(monkeypatch, tmp_path)
    _seed_notebook("nb_pricing", "Pricing")
    _seed_sync(NOTEBOOK_INDEX_SCOPE, "2026-03-15T06:09:00+00:00")
    _seed_sync(
        NOTEBOOK_DETAIL_SCOPE,
        "2026-03-15T06:09:30+00:00",
        target_id="nb_pricing",
    )
    set_current_notebook("nb_pricing", title="Pricing")

    result = runner.invoke(cli, ["route", "summarize current notebook", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Route dry run" in result.output
    assert "Intent: GENERATION" in result.output
    assert "Target notebook: nb_pricing" in result.output
    assert "Command: summarize" in result.output
    assert "Mode: briefing_doc" in result.output
    assert "Transport: httpx" in result.output
    assert "Decision: resolved" in result.output


def test_route_dry_run_supports_json_with_options_before_request(
    runner,
    monkeypatch,
    tmp_path,
):
    _prepare_local_home(monkeypatch, tmp_path)
    _seed_notebook("nb_pricing", "Pricing")
    _seed_sync(NOTEBOOK_INDEX_SCOPE, "2026-03-15T06:09:00+00:00")
    _seed_sync(
        NOTEBOOK_DETAIL_SCOPE,
        "2026-03-15T06:09:30+00:00",
        target_id="nb_pricing",
    )
    set_current_notebook("nb_pricing", title="Pricing")

    result = runner.invoke(
        cli,
        ["route", "--json", "--dry-run", "summarize current notebook"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "route_dry_run"
    assert payload["result"]["view"] == "dry_run"
    assert payload["result"]["intent"]["value"] == "GENERATION"
    assert payload["result"]["notebook_resolution"]["notebook_id"] == "nb_pricing"
    assert payload["result"]["execution_plan"]["command_name"] == "summarize"
    assert payload["result"]["execution_plan"]["mode"] == "briefing_doc"
    assert payload["result"]["cache_decision"]["transport"]["kind"] == "httpx"


def test_route_explain_supports_json(runner, monkeypatch, tmp_path):
    _prepare_local_home(monkeypatch, tmp_path)

    result = runner.invoke(
        cli,
        ["route", "explain", "generate report --format study-guide", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "route_explain"
    assert payload["result"]["view"] == "explain"
    assert payload["result"]["structured_command"]["command_path"] == ["generate", "report"]
    assert "notebook-routing heuristics are skipped" in payload["result"]["structured_command"]["reason"]


def test_route_without_dry_run_is_rejected(runner, monkeypatch, tmp_path):
    _prepare_local_home(monkeypatch, tmp_path)

    result = runner.invoke(cli, ["route", "summarize current notebook"])

    assert result.exit_code != 0
    assert "Route execution is not implemented" in result.output


def test_route_group_help_lists_explain(runner):
    result = runner.invoke(cli, ["route", "--help"])

    assert result.exit_code == 0, result.output
    assert "explain" in result.output
