"""CLI tests for `notebooklm events`."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib
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


def _seed_event_rows() -> None:
    with connect_db() as connection:
        _seed_profile(connection)
        append_run_event(
            connection,
            "trc_alpha",
            "route.resolved",
            ts=datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc),
        )
        append_run_event(
            connection,
            "trc_beta",
            "cache.hit",
            run_id="qr_beta",
            ts=datetime(2026, 3, 15, 3, 1, tzinfo=timezone.utc),
        )
        append_run_event(
            connection,
            "trc_gamma",
            "sync.started",
            run_id="qr_gamma",
            ts=datetime(2026, 3, 15, 3, 2, tzinfo=timezone.utc),
        )


def test_events_tail_json_returns_recent_batch(runner):
    _seed_event_rows()

    result = runner.invoke(cli, ["events", "tail", "--limit", "2", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_METADATA"
    assert payload["route"]["mode"] == "events_tail"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["route"]["profile_id"] == "default"
    assert payload["result"]["follow"] is False
    assert payload["result"]["count"] == 2
    assert [event["kind"] for event in payload["result"]["events"]] == [
        "cache.hit",
        "sync.started",
    ]
    assert payload["result"]["events"][1]["trace_id"] == "trc_gamma"


def test_events_tail_follow_exits_cleanly_after_interrupt(runner, monkeypatch):
    _seed_event_rows()
    events_module = importlib.import_module("notebooklm.cli.events")
    state = {"calls": 0}

    def fake_sleep(_seconds: float) -> None:
        if state["calls"] == 0:
            state["calls"] += 1
            with connect_db() as connection:
                append_run_event(
                    connection,
                    "trc_delta",
                    "sync.finished",
                    run_id="qr_delta",
                    ts=datetime(2026, 3, 15, 3, 3, tzinfo=timezone.utc),
                )
            return
        raise KeyboardInterrupt

    monkeypatch.setattr(events_module.time, "sleep", fake_sleep)

    result = runner.invoke(cli, ["events", "tail", "--limit", "1", "--follow"])

    assert result.exit_code == 0, result.output
    assert "Recent Run Events" in result.output
    assert "sync.started" in result.output
    assert "sync.finished" in result.output


def test_events_group_help_lists_tail(runner):
    result = runner.invoke(cli, ["events", "--help"])

    assert result.exit_code == 0, result.output
    assert "tail" in result.output
