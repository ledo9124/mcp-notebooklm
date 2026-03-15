"""CLI tests for `notebooklm` radar and watch commands."""

from __future__ import annotations

import json
import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from notebooklm.auth import AuthTokens
from notebooklm.cli.radar import radar, watch
from notebooklm.local.db import connect_db
from notebooklm.local.repositories import NotebookRecord, NotebookRepository, SourceRecord, SourceRepository


def _seed_profile(connection, profile_id: str = "default") -> None:
    existing = connection.execute(
        "SELECT profile_id FROM profiles WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    if existing is not None:
        return

    with connection:
        connection.execute(
            """
            INSERT INTO profiles (
                profile_id,
                display_name,
                account_email,
                is_default,
                storage_state_path,
                browser_profile_path,
                created_at,
                updated_at,
                last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                "Default",
                "default@example.com",
                1,
                "/tmp/default/storage_state.json",
                "/tmp/default/browser_profile",
                "2026-03-15T00:00:00Z",
                "2026-03-15T00:00:00Z",
                None,
            ),
        )


def _seed_notebook(connection) -> None:
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id="nb_123",
            profile_id="default",
            title="Radar Notebook",
            normalized_title="radar notebook",
        )
    )


def _seed_source(connection, *, source_id: str = "src_1", freshness_state: str | None = "stale") -> None:
    SourceRepository(connection).upsert(
        SourceRecord(
            source_id=source_id,
            notebook_id="nb_123",
            profile_id="default",
            source_type="web_page",
            status="ready",
            title=f"Source {source_id}",
            origin_uri=f"https://example.com/{source_id}",
            freshness_state=freshness_state,
        )
    )


def _seed_watch(
    connection,
    *,
    watch_id: str = "watch_1",
    source_id: str = "src_1",
    status: str = "active",
    next_run_at: str | None = "2026-03-15T03:59:00+00:00",
) -> None:
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
                watch_id,
                "default",
                "source",
                source_id,
                "web_diff",
                json.dumps({"materiality": "normal"}, sort_keys=True),
                status,
                json.dumps({"interval": "daily"}, sort_keys=True),
                next_run_at,
                "2026-03-15T02:00:00+00:00",
            ),
        )


def _seed_research_run(
    connection,
    *,
    research_id: str = "res_seed",
    notebook_id: str = "nb_123",
    profile_id: str = "default",
    mode: str = "deep",
    query_text: str = "AI research",
    status: str = "completed",
    sources: list[dict[str, str]] | None = None,
    search_source: str = "web",
) -> None:
    _seed_profile(connection, profile_id)
    _seed_notebook(connection)
    payload = {
        "research_id": research_id,
        "task_id": research_id,
        "status": status,
        "query": query_text,
        "sources": sources or [],
        "summary": "",
        "search_source": search_source,
    }
    with connection:
        connection.execute(
            """
            INSERT INTO research_runs (
                research_id,
                notebook_id,
                profile_id,
                mode,
                query_text,
                status,
                discovered_count,
                imported_count,
                started_at,
                updated_at,
                raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                research_id,
                notebook_id,
                profile_id,
                mode,
                query_text,
                status,
                len(payload["sources"]),
                0,
                "2026-03-15T04:00:00+00:00",
                "2026-03-15T04:05:00+00:00",
                json.dumps(payload, sort_keys=True),
            ),
        )


def _seed_event(
    connection,
    *,
    event_id: str = "evt_1",
    watch_id: str = "watch_1",
    source_id: str = "src_1",
    severity: str = "material",
    state: str = "new",
    created_at: str = "2026-03-15T04:00:00+00:00",
    change_kind: str = "content_hash_changed",
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO change_events (
                id,
                watch_id,
                source_id,
                notebook_id,
                workspace_id,
                change_kind,
                severity,
                state,
                created_at,
                data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                watch_id,
                source_id,
                "nb_123",
                None,
                change_kind,
                severity,
                state,
                created_at,
                json.dumps({"canonical_uri": f"https://example.com/{source_id}", "summary": event_id}),
            ),
        )


def _seed_briefing(
    connection,
    *,
    briefing_id: str = "brief_1",
    event_id: str = "evt_1",
    created_at: str = "2026-03-15T04:01:00+00:00",
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO delta_briefings (
                id,
                change_event_id,
                summary_md,
                impact_json,
                recommended_actions_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                briefing_id,
                event_id,
                "## What Changed\nSource changed materially.",
                json.dumps({"notebooks": ["nb_123"], "workspaces": [], "query_runs": []}, sort_keys=True),
                json.dumps({"actions": [{"kind": "review_change"}]}, sort_keys=True),
                created_at,
            ),
        )


def _seed_default_radar(tmp_path) -> None:
    with connect_db() as connection:
        _seed_profile(connection)
        _seed_notebook(connection)
        _seed_source(connection)
        _seed_watch(connection)
        _seed_event(connection)
        _seed_briefing(connection)


def _stub_auth_tokens(storage_path: Path) -> AuthTokens:
    return AuthTokens(
        cookies={"SID": "test_sid", "HSID": "test_hsid"},
        csrf_token="csrf",
        session_id="session",
        build_label="boq_labs-tailwind-frontend_20260315.24_p0",
        storage_path=storage_path.resolve(),
    )


def _mock_research_watch_client(*, start_payload: dict, poll_payloads: list[dict]) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.research = MagicMock()
    client.research.start = AsyncMock(return_value=start_payload)
    client.research.poll = AsyncMock(side_effect=poll_payloads)
    return client


def test_radar_status_json_summarizes_watches_and_events(runner, tmp_path):
    _seed_default_radar(tmp_path)
    with connect_db() as connection:
        _seed_source(connection, source_id="src_2", freshness_state="fresh")
        _seed_watch(
            connection,
            watch_id="watch_2",
            source_id="src_2",
            status="paused",
            next_run_at="2026-03-16T03:59:00+00:00",
        )
        _seed_event(
            connection,
            event_id="evt_2",
            watch_id="watch_2",
            source_id="src_2",
            severity="minor",
            state="ignored",
            created_at="2026-03-15T03:00:00+00:00",
            change_kind="metadata_only_changed",
        )
        _seed_briefing(connection, briefing_id="brief_2", event_id="evt_2")

    result = runner.invoke(radar, ["status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "RADAR_STATUS"
    assert payload["route"]["mode"] == "radar_status"
    assert payload["route"]["profile_id"] == "default"
    assert payload["route"]["source_of_truth"] == "local_cache"
    assert payload["route"]["cache_mode"] == "offline"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["profile_id"] == "default"
    assert payload["result"]["watches"]["total"] == 2
    assert payload["result"]["watches"]["active"] == 1
    assert payload["result"]["watches"]["paused"] == 1
    assert payload["result"]["watches"]["due_now"] == 1
    assert payload["result"]["events"]["total"] == 2
    assert payload["result"]["events"]["open"] == 1
    assert payload["result"]["events"]["by_state"] == {"ignored": 1, "new": 1}
    assert payload["result"]["events"]["by_severity"] == {"material": 1, "minor": 1}
    assert payload["result"]["latest_event"]["id"] == "evt_1"


def test_radar_list_json_defaults_to_open_events(runner, tmp_path):
    _seed_default_radar(tmp_path)
    with connect_db() as connection:
        _seed_event(
            connection,
            event_id="evt_ignored",
            severity="minor",
            state="ignored",
            created_at="2026-03-15T03:00:00+00:00",
            change_kind="metadata_only_changed",
        )
        _seed_briefing(connection, briefing_id="brief_ignored", event_id="evt_ignored")

    result = runner.invoke(radar, ["list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "RADAR_STATUS"
    assert payload["route"]["mode"] == "radar_list"
    assert payload["result"]["state_filter"] == "open"
    assert payload["result"]["count"] == 1
    assert [event["id"] for event in payload["result"]["events"]] == ["evt_1"]
    assert payload["result"]["events"][0]["briefing_id"] == "brief_1"


def test_radar_brief_json_returns_event_watch_and_briefing(runner, tmp_path):
    _seed_default_radar(tmp_path)

    result = runner.invoke(radar, ["brief", "evt_1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "RADAR_BRIEF"
    assert payload["route"]["mode"] == "radar_brief"
    assert payload["route"]["notebook_id"] == "nb_123"
    assert payload["result"]["event"]["id"] == "evt_1"
    assert payload["result"]["watch"]["id"] == "watch_1"
    assert payload["result"]["watch"]["policy"]["materiality"] == "normal"
    assert payload["result"]["briefing"]["id"] == "brief_1"
    assert payload["result"]["briefing"]["impact"]["notebooks"] == ["nb_123"]
    assert payload["result"]["briefing"]["recommended_actions"]["actions"][0]["kind"] == "review_change"


def test_radar_ignore_marks_event_ignored_and_refreshes_source_when_no_open_material_events(
    runner, tmp_path
):
    _seed_default_radar(tmp_path)

    result = runner.invoke(radar, ["ignore", "evt_1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "radar_ignore"
    assert payload["route"]["notebook_id"] == "nb_123"
    assert payload["result"]["event"]["state"] == "ignored"
    assert payload["result"]["source_freshness_state"] == "fresh"
    assert payload["cache_updates"]["tables_touched"] == ["change_events", "sources"]

    with connect_db() as connection:
        event = connection.execute(
            "SELECT state FROM change_events WHERE id = 'evt_1'"
        ).fetchone()
        source = SourceRepository(connection).get("src_1")

    assert event["state"] == "ignored"
    assert source is not None
    assert source.freshness_state == "fresh"


def test_radar_ignore_keeps_source_stale_when_another_open_material_event_exists(runner, tmp_path):
    _seed_default_radar(tmp_path)
    with connect_db() as connection:
        _seed_event(
            connection,
            event_id="evt_2",
            severity="critical",
            state="briefed",
            created_at="2026-03-15T04:02:00+00:00",
        )
        _seed_briefing(connection, briefing_id="brief_2", event_id="evt_2")

    result = runner.invoke(radar, ["ignore", "evt_1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["result"]["event"]["state"] == "ignored"
    assert payload["result"]["source_freshness_state"] == "stale"
    assert payload["cache_updates"]["tables_touched"] == ["change_events", "sources"]

    with connect_db() as connection:
        source = SourceRepository(connection).get("src_1")

    assert source is not None
    assert source.freshness_state == "stale"


def test_watch_add_json_creates_a_source_watch(runner, tmp_path):
    _seed_default_radar(tmp_path)

    result = runner.invoke(watch, ["add", "--source", "src_1", "--policy", "daily", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "watch_add"
    assert payload["route"]["profile_id"] == "default"
    assert payload["cache_updates"]["tables_touched"] == ["watches"]
    assert payload["result"]["watch"]["id"].startswith("watch_")
    assert payload["result"]["watch"]["scope_type"] == "source"
    assert payload["result"]["watch"]["scope_id"] == "src_1"
    assert payload["result"]["watch"]["watch_kind"] == "web_diff"
    assert payload["result"]["watch"]["schedule"] == {"interval": "daily"}
    assert payload["result"]["watch"]["policy"]["target_url"] == "https://example.com/src_1"
    assert payload["result"]["watch"]["source"]["id"] == "src_1"
    created_watch_id = payload["result"]["watch"]["id"]

    with connect_db() as connection:
        rows = connection.execute("SELECT * FROM watches ORDER BY id ASC").fetchall()
        created = connection.execute("SELECT * FROM watches WHERE id = ?", (created_watch_id,)).fetchone()

    assert len(rows) == 2
    assert created is not None
    assert created["scope_type"] == "source"
    assert created["scope_id"] == "src_1"
    assert created["watch_kind"] == "web_diff"
    assert json.loads(created["schedule_json"]) == {"interval": "daily"}


def test_watch_add_json_creates_a_research_watch(runner, tmp_path):
    with connect_db() as connection:
        _seed_research_run(connection)

    result = runner.invoke(watch, ["add", "--research", "res_seed", "--policy", "weekly", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "watch_add"
    assert payload["result"]["watch"]["scope_type"] == "research_query"
    assert payload["result"]["watch"]["scope_id"] == "res_seed"
    assert payload["result"]["watch"]["watch_kind"] == "deep_research"
    assert payload["result"]["watch"]["schedule"] == {"interval": "weekly"}
    assert payload["result"]["watch"]["research"]["id"] == "res_seed"
    assert payload["result"]["watch"]["research"]["query"] == "AI research"
    assert payload["result"]["watch"]["notebook"]["id"] == "nb_123"


def test_watch_list_json_returns_local_watch_rows(runner, tmp_path):
    _seed_default_radar(tmp_path)
    with connect_db() as connection:
        _seed_source(connection, source_id="src_2")
        _seed_watch(
            connection,
            watch_id="watch_2",
            source_id="src_2",
            status="paused",
            next_run_at="2026-03-16T03:59:00+00:00",
        )

    result = runner.invoke(watch, ["list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_METADATA"
    assert payload["route"]["mode"] == "watch_list"
    assert payload["result"]["profile_id"] == "default"
    assert payload["result"]["count"] == 2
    assert [item["id"] for item in payload["result"]["watches"]] == ["watch_1", "watch_2"]
    assert payload["result"]["watches"][0]["source"]["id"] == "src_1"
    assert payload["result"]["watches"][1]["status"] == "paused"


def test_watch_pause_json_marks_watch_paused(runner, tmp_path):
    _seed_default_radar(tmp_path)

    result = runner.invoke(watch, ["pause", "watch_1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "watch_pause"
    assert payload["result"]["watch"]["id"] == "watch_1"
    assert payload["result"]["watch"]["status"] == "paused"
    assert payload["cache_updates"]["tables_touched"] == ["watches"]

    with connect_db() as connection:
        row = connection.execute("SELECT status FROM watches WHERE id = 'watch_1'").fetchone()

    assert row["status"] == "paused"


def test_watch_run_now_json_executes_local_file_watch(runner, tmp_path):
    target = tmp_path / "watched.txt"
    target.write_text("baseline\n", encoding="utf-8")
    with connect_db() as connection:
        _seed_profile(connection)
        _seed_notebook(connection)
        SourceRepository(connection).upsert(
            SourceRecord(
                source_id="src_local",
                notebook_id="nb_123",
                profile_id="default",
                source_type="markdown",
                status="ready",
                title="Local Source",
                origin_uri=f"file://{target}",
            )
        )

    created = runner.invoke(watch, ["add", "--source", "src_local", "--policy", "daily", "--json"])
    assert created.exit_code == 0, created.output
    created_payload = json.loads(created.output)
    watch_id = created_payload["result"]["watch"]["id"]

    result = runner.invoke(watch, ["run-now", watch_id, "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "watch_run_now"
    assert payload["result"]["watch"]["id"] == watch_id
    assert payload["result"]["run"]["status"] == "completed"
    assert payload["result"]["run"]["baseline_created"] is True
    assert payload["result"]["run"]["source_revision_id"] is not None
    assert "watch_runs" in payload["cache_updates"]["tables_touched"]
    assert "source_revisions" in payload["cache_updates"]["tables_touched"]

    with connect_db() as connection:
        watch_runs = connection.execute("SELECT * FROM watch_runs WHERE watch_id = ?", (watch_id,)).fetchall()
        revisions = connection.execute(
            "SELECT * FROM source_revisions WHERE source_id = 'src_local' ORDER BY id ASC"
        ).fetchall()

    assert len(watch_runs) == 1
    assert watch_runs[0]["status"] == "completed"
    assert len(revisions) == 1


def test_watch_run_now_json_reruns_research_watch_and_stages_new_candidates(runner, tmp_path, monkeypatch):
    radar_module = importlib.import_module("notebooklm.cli.radar")
    storage_path = tmp_path / "storage_state.json"
    storage_path.write_text("{}", encoding="utf-8")
    with connect_db() as connection:
        _seed_research_run(
            connection,
            sources=[{"title": "Baseline Source", "url": "https://example.com/baseline"}],
        )

    created = runner.invoke(watch, ["add", "--research", "res_seed", "--policy", "daily", "--json"])
    assert created.exit_code == 0, created.output
    watch_id = json.loads(created.output)["result"]["watch"]["id"]

    mock_client = _mock_research_watch_client(
        start_payload={
            "task_id": "task_new",
            "report_id": "rep_1",
            "notebook_id": "nb_123",
            "query": "AI research",
            "mode": "deep",
        },
        poll_payloads=[
            {
                "task_id": "task_new",
                "status": "completed",
                "query": "AI research",
                "sources": [{"title": "New Source", "url": "https://example.com/new"}],
                "summary": "Fresh result set",
            }
        ],
    )
    monkeypatch.setattr(radar_module, "get_auth_tokens", lambda ctx: _stub_auth_tokens(storage_path))
    monkeypatch.setattr(radar_module, "NotebookLMClient", lambda auth: mock_client)

    result = runner.invoke(watch, ["run-now", watch_id, "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "watch_run_now"
    assert payload["result"]["watch"]["id"] == watch_id
    assert payload["result"]["watch"]["scope_type"] == "research_query"
    assert payload["result"]["watch"]["scope_id"] == "task_new"
    assert payload["result"]["watch"]["research"]["id"] == "task_new"
    assert payload["result"]["run"]["status"] == "completed"
    assert payload["result"]["run"]["changed"] is True
    assert payload["result"]["run"]["research_id_before"] == "res_seed"
    assert payload["result"]["run"]["research_id_after"] == "task_new"
    assert payload["result"]["run"]["staged"] == 1
    assert payload["result"]["run"]["sources_found"] == 1
    assert "watch_runs" in payload["cache_updates"]["tables_touched"]
    assert "research_runs" in payload["cache_updates"]["tables_touched"]
    assert "inbox_items" in payload["cache_updates"]["tables_touched"]

    with connect_db() as connection:
        watch_row = connection.execute(
            "SELECT scope_id, last_run_at, next_run_at FROM watches WHERE id = ?",
            (watch_id,),
        ).fetchone()
        watch_runs = connection.execute(
            "SELECT status, signature_before, signature_after, result_json FROM watch_runs WHERE watch_id = ?",
            (watch_id,),
        ).fetchall()
        inbox_items = connection.execute(
            "SELECT canonical_uri, state, origin FROM inbox_items ORDER BY id ASC"
        ).fetchall()
        events = connection.execute(
            "SELECT kind, run_id FROM run_events ORDER BY ts ASC, event_id ASC"
        ).fetchall()

    assert watch_row["scope_id"] == "task_new"
    assert watch_row["last_run_at"] is not None
    assert watch_row["next_run_at"] is not None
    assert len(watch_runs) == 1
    assert watch_runs[0]["status"] == "completed"
    assert watch_runs[0]["signature_before"] is not None
    assert watch_runs[0]["signature_after"] is not None
    assert json.loads(watch_runs[0]["result_json"])["staged"] == 1
    assert [(row["canonical_uri"], row["state"], row["origin"]) for row in inbox_items] == [
        ("https://example.com/new", "pending", "deep_research")
    ]
    assert any(event["kind"] == "research.started" and event["run_id"] == "task_new" for event in events)
    assert any(event["kind"] == "research.completed" and event["run_id"] == "task_new" for event in events)
    assert any(event["kind"] == "inbox.item.created" and event["run_id"] == "task_new" for event in events)
    assert any(event["kind"] == "watch.run.completed" for event in events)


def test_watch_add_workspace_json_returns_canonical_error(runner, tmp_path):
    _seed_default_radar(tmp_path)

    result = runner.invoke(watch, ["add", "--workspace", "market-intel", "--policy", "weekly", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "watch_add"
    assert payload["result"]["code"] == "WATCH_TARGET_NOT_FOUND"
