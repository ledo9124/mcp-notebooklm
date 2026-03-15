"""CLI tests for the experimental `notebooklm agent` wrapper."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from click.testing import CliRunner

from notebooklm.cli.helpers import set_current_notebook
from notebooklm.local.db import connect_db
from notebooklm.notebooklm_cli import cli
from notebooklm.profiles.manager import ProfileManager


@pytest.fixture
def runner() -> CliRunner:
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


def _capture_agent_dispatch(monkeypatch) -> list[list[str]]:
    captured: list[list[str]] = []
    agent_module = import_module("notebooklm.cli.agent")

    def _capture(root_ctx, argv):
        del root_ctx
        captured.append(list(argv))
        return None

    monkeypatch.setattr(agent_module, "_invoke_root_command", _capture)
    return captured


def test_agent_routes_generation_request_to_summarize_command(runner, monkeypatch, tmp_path):
    _prepare_local_home(monkeypatch, tmp_path)
    captured = _capture_agent_dispatch(monkeypatch)
    set_current_notebook("nb_pricing", title="Pricing")

    result = runner.invoke(cli, ["agent", "summarize current notebook"])

    assert result.exit_code == 0, result.output
    assert captured == [["summarize", "--notebook", "nb_pricing", "summarize current notebook"]]
    assert "Routed GENERATION request to summarize" in result.output


def test_agent_preserves_structured_command_precedence(runner, monkeypatch, tmp_path):
    _prepare_local_home(monkeypatch, tmp_path)
    captured = _capture_agent_dispatch(monkeypatch)

    result = runner.invoke(cli, ["agent", "notebook list --refresh"])

    assert result.exit_code == 0, result.output
    assert captured == [["notebook", "list", "--refresh"]]
    assert "Structured command wins: notebook list" in result.output


def test_agent_passes_json_and_refresh_through_for_notebook_list(
    runner,
    monkeypatch,
    tmp_path,
):
    _prepare_local_home(monkeypatch, tmp_path)
    captured = _capture_agent_dispatch(monkeypatch)

    result = runner.invoke(cli, ["agent", "--cache-mode", "refresh", "--json", "list notebooks"])

    assert result.exit_code == 0, result.output
    assert captured == [["notebook", "list", "--refresh", "--json"]]
    assert result.output == ""


def test_agent_forwards_explicit_notebook_selector(runner, monkeypatch, tmp_path):
    _prepare_local_home(monkeypatch, tmp_path)
    captured = _capture_agent_dispatch(monkeypatch)

    result = runner.invoke(cli, ["agent", "--notebook", "nb_remote123", "summarize pricing notebook"])

    assert result.exit_code == 0, result.output
    assert captured == [["summarize", "--notebook", "nb_remote123", "summarize pricing notebook"]]


def test_agent_extracts_research_id_for_wait_requests(runner, monkeypatch, tmp_path):
    _prepare_local_home(monkeypatch, tmp_path)
    captured = _capture_agent_dispatch(monkeypatch)

    result = runner.invoke(cli, ["agent", "wait for research run r_123"])

    assert result.exit_code == 0, result.output
    assert captured == [["research", "wait", "r_123"]]


def test_agent_rejects_import_requests_without_research_id(runner, monkeypatch, tmp_path):
    _prepare_local_home(monkeypatch, tmp_path)
    _capture_agent_dispatch(monkeypatch)

    result = runner.invoke(cli, ["agent", "import research results"])

    assert result.exit_code == 1
    assert "requires an explicit research id" in result.output


def test_agent_rejects_unmapped_local_metadata_queries(runner, monkeypatch, tmp_path):
    _prepare_local_home(monkeypatch, tmp_path)
    _capture_agent_dispatch(monkeypatch)

    result = runner.invoke(cli, ["agent", "which notebooks have PDF sources?"])

    assert result.exit_code == 1
    assert "does not map to an executable structured workflow yet" in result.output
