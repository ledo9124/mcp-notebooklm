"""CLI tests for `notebooklm trace`."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from notebooklm.local.db import connect_db
from notebooklm.local.events import append_run_event
from notebooklm.notebooklm_cli import cli
from notebooklm.profiles.manager import ProfileManager


def _seed_profile(connection) -> None:
    manager = ProfileManager(connection)
    if manager.get_profile("default") is not None:
        return
    manager.create_profile(
        profile_id="default",
        display_name="Default",
        account_email="default@example.com",
        storage_state_path="/tmp/default/storage_state.json",
        browser_profile_path="/tmp/default/browser_profile",
        is_default=True,
    )


def _seed_trace_rows() -> None:
    with connect_db() as connection:
        _seed_profile(connection)
        append_run_event(
            connection,
            "trc_trace_cli",
            "route.resolved",
            run_id="qr_trace_cli",
            payload={"mode": "answer"},
            ts=datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc),
        )
        append_run_event(
            connection,
            "trc_trace_cli",
            "cache.miss",
            run_id="qr_trace_cli",
            payload={"entity": "notebooks"},
            ts=datetime(2026, 3, 15, 3, 1, tzinfo=timezone.utc),
        )


def test_trace_show_json_returns_canonical_envelope(runner):
    _seed_trace_rows()

    result = runner.invoke(cli, ["trace", "show", "trc_trace_cli", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_METADATA"
    assert payload["route"]["mode"] == "trace_show"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["route"]["profile_id"] == "default"
    assert payload["result"]["trace_id"] == "trc_trace_cli"
    assert payload["result"]["count"] == 2
    assert [event["kind"] for event in payload["result"]["events"]] == [
        "route.resolved",
        "cache.miss",
    ]
    assert payload["result"]["events"][1]["payload"] == {"entity": "notebooks"}


def test_trace_show_errors_when_trace_not_found(runner):
    result = runner.invoke(cli, ["trace", "show", "trc_missing"])

    assert result.exit_code != 0
    assert "No local events found for trace: trc_missing" in result.output


def test_trace_group_help_lists_show(runner):
    result = runner.invoke(cli, ["trace", "--help"])

    assert result.exit_code == 0, result.output
    assert "show" in result.output
