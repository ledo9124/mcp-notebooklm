"""Unit tests for the local cache CLI and helper surface."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from click.testing import CliRunner

from notebooklm.cli.cache import cache as cache_group
from notebooklm.contracts import RiskTier
from notebooklm.local.cache import resolve_cache_db_path
from notebooklm.local.db import connect_db
from notebooklm.local.events import append_run_event
from notebooklm.notebooklm_cli import cli


def test_cache_status_json_reports_counts_sizes_and_sync_bounds(monkeypatch, tmp_path):
    """Cache status should summarize the live SQLite file without remote access."""
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))

    with connect_db() as connection:
        _insert_profile(connection)
        connection.execute(
            """
            INSERT INTO notebooks (
                notebook_id,
                profile_id,
                title,
                normalized_title,
                index_synced_at,
                detail_synced_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "nb_status",
                "default",
                "Cache Status",
                "cache status",
                "2026-03-10T01:00:00+00:00",
                "2026-03-12T01:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO sources (
                source_id,
                notebook_id,
                profile_id,
                source_type,
                status,
                synced_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "src_status",
                "nb_status",
                "default",
                "web_page",
                "ready",
                "2026-03-11T01:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO sync_runs (
                id,
                trace_id,
                profile_id,
                scope,
                trigger,
                started_at,
                ended_at,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sr_status",
                "trace-status",
                "default",
                "notebooks",
                "manual",
                "2026-03-09T01:00:00+00:00",
                "2026-03-13T01:00:00+00:00",
                "completed",
            ),
        )

    runner = CliRunner()
    result = runner.invoke(cli, ["cache", "status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "QUERY"
    assert payload["route"]["mode"] == "cache_status"
    assert payload["route"]["profile_id"] == "default"
    assert payload["route"]["source_of_truth"] == "local_cache"
    assert payload["route"]["cache_mode"] == "offline"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["exists"] is True
    assert payload["result"]["db_path"] == str(resolve_cache_db_path())
    assert payload["result"]["table_counts"]["profiles"] == 1
    assert payload["result"]["table_counts"]["notebooks"] == 1
    assert payload["result"]["table_counts"]["sources"] == 1
    assert payload["result"]["table_counts"]["sync_runs"] == 1
    assert payload["result"]["db_size_bytes"] > 0
    assert payload["result"]["wal_size_bytes"] >= 0
    assert payload["result"]["oldest_sync_timestamp"] == "2026-03-09T01:00:00+00:00"
    assert payload["result"]["newest_sync_timestamp"] == "2026-03-13T01:00:00+00:00"
    assert payload["trace_id"].startswith("trc_")
    assert payload["run_id"]
    assert payload["diagnostics"]["elapsed_ms"] >= 0


def test_cache_status_missing_db_is_a_noop(monkeypatch, tmp_path):
    """Status should not create a cache DB when NOTEBOOKLM_HOME is empty."""
    home = tmp_path / "empty-home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))

    runner = CliRunner()
    result = runner.invoke(cli, ["cache", "status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "cache_status"
    assert payload["result"]["exists"] is False
    assert payload["result"]["table_counts"]["notebooks"] == 0
    assert not resolve_cache_db_path().exists()


def test_cache_prune_dry_run_reports_candidates_without_mutating(monkeypatch, tmp_path):
    """Dry-run mode should report deletions without changing the database."""
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    _seed_prunable_cache()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["cache", "prune", "--older-than-days", "30", "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "cache_prune"
    assert payload["route"]["source_of_truth"] == "local_cache"
    assert payload["route"]["cache_mode"] == "offline"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["dry_run"] is True
    assert payload["result"]["candidate_counts"] == {"sources": 1, "notebooks": 1, "run_events": 1}
    assert payload["result"]["deleted_counts"] == {"sources": 0, "notebooks": 0, "run_events": 0}
    assert payload["result"]["total_candidates"] == 3
    assert payload["result"]["total_deleted"] == 0
    assert payload["result"]["vacuumed"] is False
    assert payload["cache_updates"]["tables_touched"] == []

    with connect_db() as connection:
        source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        notebook_count = connection.execute("SELECT COUNT(*) FROM notebooks").fetchone()[0]

    assert source_count == 2
    assert notebook_count == 1


def test_cache_prune_deletes_old_tombstones_and_sets_risk_metadata(monkeypatch, tmp_path):
    """Actual prune should remove old tombstones and expose the T1 risk tier."""
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    _seed_prunable_cache()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["cache", "prune", "--older-than-days", "30", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["deleted_counts"] == {"sources": 1, "notebooks": 1, "run_events": 1}
    assert payload["result"]["total_deleted"] == 3
    assert payload["result"]["vacuumed"] is True
    assert payload["cache_updates"]["tables_touched"] == ["notebooks", "run_events", "sources"]

    with connect_db() as connection:
        remaining_sources = connection.execute(
            "SELECT source_id FROM sources ORDER BY source_id"
        ).fetchall()
        remaining_notebooks = connection.execute(
            "SELECT notebook_id FROM notebooks ORDER BY notebook_id"
        ).fetchall()

    assert [row[0] for row in remaining_sources] == []
    assert [row[0] for row in remaining_notebooks] == []

    callback = cache_group.commands["prune"].callback
    assert getattr(callback, "__risk_tier__") is RiskTier.T1_LOCAL_MUTATION
    assert getattr(callback, "__approval_gated__") is False
    assert getattr(callback, "__destructive__") is False


def test_cache_prune_large_mutation_requires_yes_in_json_mode(monkeypatch, tmp_path):
    """Large T1 prune operations should refuse execution until the user confirms."""
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    _seed_prunable_cache(old_source_count=10, recent_source_count=0)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["cache", "prune", "--older-than-days", "30", "--json"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["route"]["intent"] == "LOCAL_MUTATION"
    assert payload["route"]["mode"] == "cache_prune"
    assert payload["route"]["profile_id"] == "default"
    assert payload["route"]["source_of_truth"] == "local_cache"
    assert payload["route"]["cache_mode"] == "offline"
    assert payload["route"]["transport"]["kind"] == "local"
    assert payload["result"]["code"] == "CONFIRM_REQUIRED"
    assert payload["result"]["next_step"] == "--yes"
    assert payload["result"]["next_step_kind"] == "confirm"
    assert payload["result"]["risk_tier"] == RiskTier.T1_LOCAL_MUTATION.value
    assert payload["result"]["risk_alias"] == RiskTier.T1_LOCAL_MUTATION.alias
    assert payload["result"]["guard_behavior"] == RiskTier.T1_LOCAL_MUTATION.guard_behavior
    assert payload["result"]["total_candidates"] == 12
    assert payload["result"]["threshold"] == 10

    with connect_db() as connection:
        source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        notebook_count = connection.execute("SELECT COUNT(*) FROM notebooks").fetchone()[0]

    assert source_count == 10
    assert notebook_count == 1


def test_cache_prune_large_dry_run_still_succeeds_without_yes(monkeypatch, tmp_path):
    """The T1 guard should not block preview-only runs."""
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    _seed_prunable_cache(old_source_count=10, recent_source_count=0)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["cache", "prune", "--older-than-days", "30", "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["dry_run"] is True
    assert payload["result"]["total_candidates"] == 12
    assert payload["result"]["total_deleted"] == 0


def test_cache_prune_large_mutation_allows_yes(monkeypatch, tmp_path):
    """Explicit confirmation should allow large prune operations to proceed."""
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    _seed_prunable_cache(old_source_count=10, recent_source_count=0)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["cache", "prune", "--older-than-days", "30", "--yes", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["deleted_counts"] == {"sources": 10, "notebooks": 1, "run_events": 1}
    assert payload["result"]["total_deleted"] == 12
    assert payload["result"]["vacuumed"] is True
    assert payload["cache_updates"]["tables_touched"] == ["notebooks", "run_events", "sources"]


def test_cache_prune_noop_skips_vacuum_when_nothing_is_old(monkeypatch, tmp_path):
    """No-op prune runs should skip VACUUM when no rows or events qualify."""
    home = tmp_path / "home"
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(home))
    _seed_non_prunable_cache()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["cache", "prune", "--older-than-days", "30", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["candidate_counts"] == {"sources": 0, "notebooks": 0, "run_events": 0}
    assert payload["result"]["deleted_counts"] == {"sources": 0, "notebooks": 0, "run_events": 0}
    assert payload["result"]["total_candidates"] == 0
    assert payload["result"]["total_deleted"] == 0
    assert payload["result"]["vacuumed"] is False
    assert payload["cache_updates"]["tables_touched"] == []


def _insert_profile(connection) -> None:
    """Insert the minimum profile row required by the local cache schema."""
    connection.execute(
        """
        INSERT INTO profiles (
            profile_id,
            display_name,
            storage_state_path,
            browser_profile_path,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "default",
            "Default",
            "/tmp/storage_state.json",
            "/tmp/browser_profile",
            "2026-03-15T00:00:00+00:00",
            "2026-03-15T00:00:00+00:00",
        ),
    )


def _seed_prunable_cache(old_source_count: int = 1, recent_source_count: int = 1) -> None:
    """Populate one old tombstoned notebook/source pair and one fresh source."""
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=31)).isoformat()
    recent = (now - timedelta(days=5)).isoformat()

    with connect_db() as connection:
        _insert_profile(connection)
        connection.execute(
            """
            INSERT INTO notebooks (
                notebook_id,
                profile_id,
                title,
                normalized_title,
                tombstoned_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("nb_old", "default", "Old Notebook", "old notebook", old),
        )
        for index in range(old_source_count):
            connection.execute(
                """
                INSERT INTO sources (
                    source_id,
                    notebook_id,
                    profile_id,
                    source_type,
                    status,
                    tombstoned_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"src_old_{index}", "nb_old", "default", "web_page", "ready", old),
            )
        for index in range(recent_source_count):
            connection.execute(
                """
                INSERT INTO sources (
                    source_id,
                    notebook_id,
                    profile_id,
                    source_type,
                    status,
                    tombstoned_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"src_recent_{index}", "nb_old", "default", "web_page", "ready", recent),
            )
        append_run_event(
            connection,
            "trc_old_cache",
            "cache.hit",
            ts=now - timedelta(days=31),
        )
        append_run_event(
            connection,
            "trc_recent_cache",
            "cache.miss",
            ts=now - timedelta(days=5),
        )


def _seed_non_prunable_cache() -> None:
    """Populate only fresh tombstones/events so cache prune becomes a no-op."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=5)).isoformat()

    with connect_db() as connection:
        _insert_profile(connection)
        connection.execute(
            """
            INSERT INTO notebooks (
                notebook_id,
                profile_id,
                title,
                normalized_title,
                tombstoned_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("nb_recent", "default", "Recent Notebook", "recent notebook", recent),
        )
        connection.execute(
            """
            INSERT INTO sources (
                source_id,
                notebook_id,
                profile_id,
                source_type,
                status,
                tombstoned_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("src_recent_only", "nb_recent", "default", "web_page", "ready", recent),
        )
        append_run_event(
            connection,
            "trc_recent_only",
            "cache.hit",
            ts=now - timedelta(days=5),
        )
