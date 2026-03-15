"""Fast local health checks for NotebookLM runtime diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import platform
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

import click
from rich.table import Table

from .. import __version__ as PACKAGE_VERSION
from ..contracts import (
    Diagnostics,
    Envelope,
    Intent,
    Route,
    Transport,
    load_capabilities,
    manifest_risk_guard,
)
from ..local.cache import resolve_cache_db_path
from ..local.db import connect_db
from ..local.events import append_run_event, tail_run_events
from ..local.repositories import LeaseRepository
from ..local.schema import LATEST_SCHEMA_VERSION
from ..paths import get_path_info
from ..profiles import ProfileManager, bootstrap_legacy_profile, has_legacy_profile_layout
from ..sync import sync_notebook_detail, sync_notebook_index
from ..client import NotebookLMClient
from .helpers import console, get_auth_tokens, json_output_response, run_async
from .session import _inspect_auth_state, _trace_and_run_id


_AUTH_SNAPSHOT_MAX_AGE_SECONDS = 24 * 60 * 60
_MANIFEST_DOCTOR_COMMAND = "doctor"
_CHECK_STATUS_PASS = "pass"
_CHECK_STATUS_WARN = "warn"
_CHECK_STATUS_FAIL = "fail"
_DEEP_FTS_TABLE_SUFFIX = "fts"
_SUPPORT_BUNDLE_DIRNAME = "support-bundles"
_SUPPORT_BUNDLE_EVENT_LIMIT = 20
_SUPPORT_BUNDLE_FAILURE_LIMIT = 10
_REDACTED_PLACEHOLDER = "<redacted>"
_REDACTED_KEY_FRAGMENTS = ("approval", "cookie", "csrf", "secret", "session", "token")
_DOCTOR_FIX_SYNC_TRIGGER = "doctor_fix"
_STUCK_WATCH_STATUSES = ("pending", "running")
_HISTORY_FTS_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
    run_id UNINDEXED,
    trace_id UNINDEXED,
    profile_id UNINDEXED,
    prompt_text,
    answer_text,
    notebook_title,
    source_titles
)
"""
_WORKSPACE_FTS_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS workspace_index_fts USING fts5(
    entry_id UNINDEXED,
    workspace_id UNINDEXED,
    profile_id UNINDEXED,
    notebook_id UNINDEXED,
    notebook_title,
    notebook_summary,
    title_aliases_text,
    source_titles_text,
    source_snippets_text,
    tags_text,
    recent_query_text,
    content_text
)
"""


def _utc_now_iso() -> str:
    """Return a stable UTC timestamp format for local lease comparisons."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class _DoctorFinding:
    check: str
    severity: str
    status: str
    repairable: bool
    message: str
    suggested_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "check": self.check,
            "severity": self.severity,
            "status": self.status,
            "repairable": self.repairable,
            "message": self.message,
        }
        if self.suggested_action is not None:
            payload["suggested_action"] = self.suggested_action
        return payload


@dataclass(frozen=True)
class _DoctorState:
    profile_id: str
    path_info: dict[str, str]
    home_dir: Path
    db_path: Path
    requested_storage_path: Path | None
    db_exists: bool
    db_error: str | None
    schema_version: int | None
    auth_result: dict[str, Any] | None
    auth_error: str | None
    auth_missing: bool
    write_permissions_ok: bool


@dataclass(frozen=True)
class _DeepCheckContext:
    findings: list[_DoctorFinding]
    auth_tokens: Any | None = None


@dataclass(frozen=True)
class _DoctorRepair:
    kind: str
    path: Path
    description: str

    def to_dict(self, *, applied: bool) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "description": self.description,
            "applied": applied,
        }


def _collect_state(ctx: click.Context) -> _DoctorState:
    path_info = get_path_info()
    home_dir = Path(path_info["home_dir"])
    db_path = resolve_cache_db_path()
    requested_storage_path = None
    if ctx.obj and ctx.obj.get("storage_path") is not None:
        requested_storage_path = Path(ctx.obj["storage_path"]).expanduser().resolve()
    db_exists = db_path.exists()
    db_error: str | None = None
    schema_version: int | None = None

    if db_exists:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "app_state" in tables:
                row = connection.execute(
                    """
                    SELECT schema_version
                    FROM app_state
                    WHERE singleton_key = 1
                    """
                ).fetchone()
                if row is not None and row["schema_version"] is not None:
                    schema_version = int(row["schema_version"])
        except sqlite3.Error as exc:
            db_error = str(exc)
        finally:
            if connection is not None:
                connection.close()

    auth_result: dict[str, Any] | None = None
    profile_id = "default"
    auth_error: str | None = None
    auth_missing = False
    try:
        auth_result, profile_id = _inspect_auth_state(ctx)
    except FileNotFoundError:
        auth_missing = True
        auth_error = "Auth storage not found."
    except ValueError as exc:
        auth_error = f"Auth storage is unreadable: {exc}"
    except Exception as exc:  # pragma: no cover - defensive guard
        auth_error = f"Auth inspection failed: {exc}"

    return _DoctorState(
        profile_id=profile_id,
        path_info=path_info,
        home_dir=home_dir,
        db_path=db_path,
        requested_storage_path=requested_storage_path,
        db_exists=db_exists,
        db_error=db_error,
        schema_version=schema_version,
        auth_result=auth_result,
        auth_error=auth_error,
        auth_missing=auth_missing,
        write_permissions_ok=_write_permissions_ok(home_dir, db_path, db_exists),
    )


def _write_permissions_ok(home_dir: Path, db_path: Path, db_exists: bool) -> bool:
    if db_exists:
        return os.access(db_path, os.W_OK) and os.access(db_path.parent, os.W_OK)
    if home_dir.exists():
        if not home_dir.is_dir():
            return False
        return os.access(home_dir, os.W_OK)
    return os.access(home_dir.parent, os.W_OK)


def _evaluate_auth_snapshot_present(state: _DoctorState) -> _DoctorFinding:
    if state.auth_result is not None and state.auth_result["snapshot"]["present"]:
        return _DoctorFinding(
            check="auth_snapshot_present",
            severity="info",
            status=_CHECK_STATUS_PASS,
            repairable=False,
            message="Persisted auth snapshot is present.",
        )
    if state.auth_missing:
        return _DoctorFinding(
            check="auth_snapshot_present",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=True,
            message="No auth storage was found yet.",
            suggested_action="Run notebooklm login",
        )
    return _DoctorFinding(
        check="auth_snapshot_present",
        severity="warning",
        status=_CHECK_STATUS_WARN,
        repairable=True,
        message=state.auth_error or "No persisted auth snapshot is linked to the active storage.",
        suggested_action="Run notebooklm auth refresh",
    )


def _evaluate_auth_snapshot_fresh(state: _DoctorState) -> _DoctorFinding:
    snapshot = state.auth_result["snapshot"] if state.auth_result is not None else None
    if snapshot and snapshot["present"]:
        age_seconds = snapshot["age_seconds"]
        snapshot_status = snapshot["status"] or "unknown"
        if snapshot["matches_storage_cookies"] is False:
            return _DoctorFinding(
                check="auth_snapshot_fresh",
                severity="warning",
                status=_CHECK_STATUS_WARN,
                repairable=True,
                message=(
                    "Auth snapshot does not match the current storage cookies "
                    f"(status={snapshot_status})."
                ),
                suggested_action="Run notebooklm auth refresh",
            )
        if (
            age_seconds is not None
            and age_seconds <= _AUTH_SNAPSHOT_MAX_AGE_SECONDS
            and snapshot_status in {"fresh", "valid"}
        ):
            return _DoctorFinding(
                check="auth_snapshot_fresh",
                severity="info",
                status=_CHECK_STATUS_PASS,
                repairable=False,
                message=f"Auth snapshot is fresh ({age_seconds}s old, status={snapshot_status}).",
            )
        message = "Auth snapshot is present but stale or missing age metadata."
        if age_seconds is not None:
            message = (
                f"Auth snapshot is stale ({age_seconds}s old, status={snapshot_status})."
            )
        return _DoctorFinding(
            check="auth_snapshot_fresh",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=True,
            message=message,
            suggested_action="Run notebooklm auth refresh",
        )
    return _DoctorFinding(
        check="auth_snapshot_fresh",
        severity="warning",
        status=_CHECK_STATUS_WARN,
        repairable=False,
        message="Auth freshness cannot be assessed until a snapshot exists.",
    )


def _evaluate_build_label_present(state: _DoctorState) -> _DoctorFinding:
    if state.auth_result is not None and state.auth_result["build_label_present"]:
        return _DoctorFinding(
            check="build_label_present",
            severity="info",
            status=_CHECK_STATUS_PASS,
            repairable=False,
            message="Auth state includes a build label.",
        )
    return _DoctorFinding(
        check="build_label_present",
        severity="warning",
        status=_CHECK_STATUS_WARN,
        repairable=True,
        message="The current auth state is missing a build label.",
        suggested_action=(
            "Run notebooklm login"
            if state.auth_missing
            else "Run notebooklm auth refresh"
        ),
    )


def _evaluate_db_openable(state: _DoctorState) -> _DoctorFinding:
    if not state.db_exists:
        return _DoctorFinding(
            check="db_openable",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=False,
            message="Cache DB does not exist yet; this is normal before local metadata commands run.",
        )
    if state.db_error is None:
        return _DoctorFinding(
            check="db_openable",
            severity="info",
            status=_CHECK_STATUS_PASS,
            repairable=False,
            message=f"Cache DB opened successfully at {state.db_path}.",
        )
    return _DoctorFinding(
        check="db_openable",
        severity="critical",
        status=_CHECK_STATUS_FAIL,
        repairable=True,
        message=f"Cache DB could not be opened: {state.db_error}",
        suggested_action="Remove or repair the corrupted cache DB",
    )


def _evaluate_schema_current(state: _DoctorState) -> _DoctorFinding:
    if not state.db_exists:
        return _DoctorFinding(
            check="schema_current",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=False,
            message="Schema version is unavailable until the cache DB exists.",
        )
    if state.db_error is not None:
        return _DoctorFinding(
            check="schema_current",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=False,
            message="Schema version could not be checked because the cache DB is unreadable.",
        )
    if state.schema_version == LATEST_SCHEMA_VERSION:
        return _DoctorFinding(
            check="schema_current",
            severity="info",
            status=_CHECK_STATUS_PASS,
            repairable=False,
            message=f"Schema version is current ({LATEST_SCHEMA_VERSION}).",
        )
    if state.schema_version is None:
        return _DoctorFinding(
            check="schema_current",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message="Cache DB is missing app_state.schema_version.",
            suggested_action="Recreate the cache DB or run a migrating cache-backed command",
        )
    return _DoctorFinding(
        check="schema_current",
        severity="warning",
        status=_CHECK_STATUS_WARN,
        repairable=True,
        message=(
            f"Cache DB schema is at version {state.schema_version}; "
            f"expected {LATEST_SCHEMA_VERSION}."
        ),
        suggested_action="Run a cache-backed command to trigger migrations",
    )


def _evaluate_write_permissions_ok(state: _DoctorState) -> _DoctorFinding:
    if state.write_permissions_ok:
        target = state.db_path if state.db_exists else state.home_dir
        return _DoctorFinding(
            check="write_permissions_ok",
            severity="info",
            status=_CHECK_STATUS_PASS,
            repairable=False,
            message=f"Write permissions look valid for {target}.",
        )
    target = state.db_path if state.db_exists else state.home_dir
    return _DoctorFinding(
        check="write_permissions_ok",
        severity="critical",
        status=_CHECK_STATUS_FAIL,
        repairable=True,
        message=f"NotebookLM cannot write to {target}.",
        suggested_action="Fix filesystem permissions for NOTEBOOKLM_HOME",
    )


def _evaluate_notebooklm_home_consistent(state: _DoctorState) -> _DoctorFinding:
    if state.home_dir.exists() and not state.home_dir.is_dir():
        return _DoctorFinding(
            check="notebooklm_home_consistent",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message=f"NOTEBOOKLM_HOME points to a file, not a directory: {state.home_dir}",
            suggested_action="Set NOTEBOOKLM_HOME to a writable directory",
        )

    expected = {
        "storage_path": state.home_dir / "storage_state.json",
        "context_path": state.home_dir / "context.json",
        "config_path": state.home_dir / "config.json",
        "browser_profile_dir": state.home_dir / "browser_profile",
    }
    for key, expected_path in expected.items():
        actual = Path(state.path_info[key])
        if actual != expected_path:
            return _DoctorFinding(
                check="notebooklm_home_consistent",
                severity="critical",
                status=_CHECK_STATUS_FAIL,
                repairable=True,
                message=(
                    f"Resolved {key} path ({actual}) does not match NOTEBOOKLM_HOME "
                    f"({expected_path})."
                ),
                suggested_action="Unset conflicting path overrides and retry doctor",
            )

    active_storage_path: Path | None = state.requested_storage_path
    if (
        active_storage_path is None
        and state.auth_result is not None
        and state.auth_result.get("storage_path")
    ):
        active_storage_path = Path(state.auth_result["storage_path"]).expanduser().resolve()
    if active_storage_path is not None:
        try:
            active_storage_path.relative_to(state.home_dir)
        except ValueError:
            return _DoctorFinding(
                check="notebooklm_home_consistent",
                severity="critical",
                status=_CHECK_STATUS_FAIL,
                repairable=True,
                message=(
                    f"Active auth storage path ({active_storage_path}) is outside NOTEBOOKLM_HOME "
                    f"({state.home_dir})."
                ),
                suggested_action="Move storage_state.json under NOTEBOOKLM_HOME or unset --storage.",
            )

    return _DoctorFinding(
        check="notebooklm_home_consistent",
        severity="info",
        status=_CHECK_STATUS_PASS,
        repairable=False,
        message=f"All local state paths resolve under {state.home_dir}.",
    )


def _connect_readonly_db(state: _DoctorState) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{state.db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _list_table_names(state: _DoctorState) -> set[str] | None:
    if not state.db_exists or state.db_error is not None:
        return None

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        if connection is not None:
            connection.close()

    return {str(row["name"]) for row in rows}


def _evaluate_cache_integrity(state: _DoctorState) -> _DoctorFinding:
    if not state.db_exists:
        return _DoctorFinding(
            check="cache_integrity_ok",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=False,
            message="Cache integrity cannot be checked until the cache DB exists.",
        )
    if state.db_error is not None:
        return _DoctorFinding(
            check="cache_integrity_ok",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=False,
            message="Cache integrity could not be checked because the cache DB is unreadable.",
        )

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        return _DoctorFinding(
            check="cache_integrity_ok",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message=f"Cache integrity check failed: {exc}",
            suggested_action="Remove or repair the corrupted cache DB",
        )
    finally:
        if connection is not None:
            connection.close()

    messages = [str(row[0]) for row in rows if row and row[0] is not None]
    if messages == ["ok"]:
        return _DoctorFinding(
            check="cache_integrity_ok",
            severity="info",
            status=_CHECK_STATUS_PASS,
            repairable=False,
            message="SQLite integrity_check returned ok.",
        )
    return _DoctorFinding(
        check="cache_integrity_ok",
        severity="critical",
        status=_CHECK_STATUS_FAIL,
        repairable=True,
        message="SQLite integrity_check reported problems: " + "; ".join(messages or ["unknown"]),
        suggested_action="Remove or repair the corrupted cache DB",
    )


def _evaluate_foreign_keys(state: _DoctorState) -> _DoctorFinding:
    if not state.db_exists:
        return _DoctorFinding(
            check="foreign_keys_ok",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=False,
            message="Foreign-key validation cannot run until the cache DB exists.",
        )
    if state.db_error is not None:
        return _DoctorFinding(
            check="foreign_keys_ok",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=False,
            message="Foreign-key validation could not run because the cache DB is unreadable.",
        )

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.Error as exc:
        return _DoctorFinding(
            check="foreign_keys_ok",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message=f"Foreign-key validation failed: {exc}",
            suggested_action="Repair the cache DB relationships or recreate the DB",
        )
    finally:
        if connection is not None:
            connection.close()

    if not rows:
        return _DoctorFinding(
            check="foreign_keys_ok",
            severity="info",
            status=_CHECK_STATUS_PASS,
            repairable=False,
            message="SQLite foreign_key_check found no violations.",
        )
    formatted = ", ".join(
        f"{row['table']}:{row['rowid']}->{row['parent']}" for row in rows[:3]
    )
    return _DoctorFinding(
        check="foreign_keys_ok",
        severity="critical",
        status=_CHECK_STATUS_FAIL,
        repairable=True,
        message=f"SQLite foreign_key_check found violations ({formatted}).",
        suggested_action="Repair the cache DB relationships or recreate the DB",
    )


def _evaluate_fts_health(state: _DoctorState) -> _DoctorFinding:
    if not state.db_exists:
        return _DoctorFinding(
            check="fts_health_ok",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=False,
            message="FTS health cannot be checked until the cache DB exists.",
        )
    if state.db_error is not None:
        return _DoctorFinding(
            check="fts_health_ok",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=False,
            message="FTS health could not be checked because the cache DB is unreadable.",
        )

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND lower(name) LIKE ?
            ORDER BY name
            """,
            (f"%{_DEEP_FTS_TABLE_SUFFIX}",),
        ).fetchall()
        fts_tables = [str(row["name"]) for row in rows]
        if not fts_tables:
            return _DoctorFinding(
                check="fts_health_ok",
                severity="info",
                status=_CHECK_STATUS_PASS,
                repairable=False,
                message="No FTS tables exist yet; nothing to validate.",
            )
        for table_name in fts_tables:
            quoted_name = table_name.replace('"', '""')
            connection.execute(f'SELECT count(*) FROM "{quoted_name}"').fetchone()
    except sqlite3.Error as exc:
        return _DoctorFinding(
            check="fts_health_ok",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message=f"FTS health check failed: {exc}",
            suggested_action="Rebuild the affected FTS tables",
        )
    finally:
        if connection is not None:
            connection.close()

    return _DoctorFinding(
        check="fts_health_ok",
        severity="info",
        status=_CHECK_STATUS_PASS,
        repairable=False,
        message="FTS tables responded to read probes.",
    )


def _evaluate_required_tables(
    state: _DoctorState,
    *,
    check: str,
    label: str,
    required_tables: tuple[str, ...],
) -> _DoctorFinding:
    if not state.db_exists:
        return _DoctorFinding(
            check=check,
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=False,
            message=f"{label} checks are unavailable until the cache DB exists.",
        )
    if state.db_error is not None:
        return _DoctorFinding(
            check=check,
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=False,
            message=f"{label} checks could not run because the cache DB is unreadable.",
        )

    table_names = _list_table_names(state)
    if table_names is None:
        return _DoctorFinding(
            check=check,
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message=f"{label} table inventory could not be loaded from the cache DB.",
            suggested_action="Run a cache-backed command to trigger migrations",
        )

    missing = [table_name for table_name in required_tables if table_name not in table_names]
    if missing:
        return _DoctorFinding(
            check=check,
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message=f"{label} tables are missing from the cache DB: {', '.join(missing)}.",
            suggested_action="Run a cache-backed command to trigger migrations",
        )

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        counts = {
            table_name: int(
                connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0] or 0
            )
            for table_name in required_tables
        }
    except sqlite3.Error as exc:
        return _DoctorFinding(
            check=check,
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message=f"{label} tables could not be queried: {exc}",
            suggested_action="Repair the cache DB or recreate it from a clean sync",
        )
    finally:
        if connection is not None:
            connection.close()

    summary = ", ".join(f"{table_name}={counts[table_name]}" for table_name in required_tables)
    return _DoctorFinding(
        check=check,
        severity="info",
        status=_CHECK_STATUS_PASS,
        repairable=False,
        message=f"{label} tables are readable ({summary}).",
    )


def _evaluate_workspace_tables_ready(state: _DoctorState) -> _DoctorFinding:
    return _evaluate_required_tables(
        state,
        check="workspace_tables_ready",
        label="Workspace",
        required_tables=("workspaces", "workspace_members", "workspace_index_entries"),
    )


def _evaluate_workspace_index_fresh(state: _DoctorState) -> _DoctorFinding:
    if not state.db_exists:
        return _DoctorFinding(
            check="workspace_index_fresh",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=False,
            message="Workspace index freshness cannot be checked until the cache DB exists.",
        )
    if state.db_error is not None:
        return _DoctorFinding(
            check="workspace_index_fresh",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=False,
            message="Workspace index freshness could not be checked because the cache DB is unreadable.",
        )

    entry_count = _query_readonly_scalar(state, "SELECT COUNT(*) FROM workspace_index_entries")
    if entry_count is None:
        return _DoctorFinding(
            check="workspace_index_fresh",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message="Workspace index entries could not be counted from the cache DB.",
            suggested_action="Repair the cache DB or recreate it from a clean sync",
        )
    if entry_count == 0:
        return _DoctorFinding(
            check="workspace_index_fresh",
            severity="info",
            status=_CHECK_STATUS_PASS,
            repairable=False,
            message="No workspace index entries exist yet; nothing is waiting on FTS alignment.",
        )
    if _workspace_fts_needs_rebuild(state):
        return _DoctorFinding(
            check="workspace_index_fresh",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=True,
            message="Workspace FTS rows are missing or stale relative to workspace_index_entries.",
            suggested_action="Run notebooklm doctor fix --json",
        )
    return _DoctorFinding(
        check="workspace_index_fresh",
        severity="info",
        status=_CHECK_STATUS_PASS,
        repairable=False,
        message=f"Workspace FTS rows are aligned with {entry_count} workspace index entry(s).",
    )


def _evaluate_radar_tables_ready(state: _DoctorState) -> _DoctorFinding:
    return _evaluate_required_tables(
        state,
        check="radar_tables_ready",
        label="Radar",
        required_tables=("watches", "watch_runs", "source_revisions", "change_events", "delta_briefings"),
    )


def _evaluate_radar_watch_runs_healthy(state: _DoctorState) -> _DoctorFinding:
    if not state.db_exists:
        return _DoctorFinding(
            check="radar_watch_runs_healthy",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=False,
            message="Radar watch-run health cannot be checked until the cache DB exists.",
        )
    if state.db_error is not None:
        return _DoctorFinding(
            check="radar_watch_runs_healthy",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=False,
            message="Radar watch-run health could not be checked because the cache DB is unreadable.",
        )

    stuck_watch_runs = _count_stuck_watch_runs(state)
    if stuck_watch_runs:
        return _DoctorFinding(
            check="radar_watch_runs_healthy",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=True,
            message=f"{stuck_watch_runs} active watch run(s) appear stuck in pending/running state.",
            suggested_action="Run notebooklm doctor fix --json",
        )
    return _DoctorFinding(
        check="radar_watch_runs_healthy",
        severity="info",
        status=_CHECK_STATUS_PASS,
        repairable=False,
        message="Active radar watch runs do not show any stuck pending/running rows.",
    )


def _evaluate_inbox_tables_ready(state: _DoctorState) -> _DoctorFinding:
    return _evaluate_required_tables(
        state,
        check="inbox_tables_ready",
        label="Inbox",
        required_tables=("inbox_items", "inbox_clusters", "approval_requests"),
    )


def _evaluate_inbox_cluster_links_consistent(state: _DoctorState) -> _DoctorFinding:
    if not state.db_exists:
        return _DoctorFinding(
            check="inbox_cluster_links_consistent",
            severity="warning",
            status=_CHECK_STATUS_WARN,
            repairable=False,
            message="Inbox cluster consistency cannot be checked until the cache DB exists.",
        )
    if state.db_error is not None:
        return _DoctorFinding(
            check="inbox_cluster_links_consistent",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=False,
            message="Inbox cluster consistency could not be checked because the cache DB is unreadable.",
        )

    dangling_links = _query_readonly_scalar(
        state,
        """
        SELECT COUNT(*)
        FROM inbox_clusters
        LEFT JOIN inbox_items
            ON inbox_items.id = inbox_clusters.representative_item_id
        WHERE inbox_clusters.representative_item_id IS NOT NULL
          AND inbox_items.id IS NULL
        """,
    )
    if dangling_links is None:
        return _DoctorFinding(
            check="inbox_cluster_links_consistent",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message="Inbox cluster representative links could not be verified from the cache DB.",
            suggested_action="Repair the cache DB or recreate it from a clean sync",
        )
    if dangling_links:
        return _DoctorFinding(
            check="inbox_cluster_links_consistent",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message=f"Inbox clusters reference {dangling_links} missing representative item(s).",
            suggested_action="Repair the affected inbox clusters or recreate the cache DB",
        )
    return _DoctorFinding(
        check="inbox_cluster_links_consistent",
        severity="info",
        status=_CHECK_STATUS_PASS,
        repairable=False,
        message="Inbox cluster representative links are internally consistent.",
    )


def _evaluate_remote_auth_probe(ctx: click.Context, state: _DoctorState) -> _DeepCheckContext:
    if state.auth_missing:
        return _DeepCheckContext(
            findings=[
                _DoctorFinding(
                    check="remote_auth_probe",
                    severity="warning",
                    status=_CHECK_STATUS_WARN,
                    repairable=True,
                    message="Remote auth probe skipped because no auth storage exists yet.",
                    suggested_action="Run notebooklm login",
                )
            ]
        )
    try:
        auth_tokens = get_auth_tokens(ctx)
    except Exception as exc:
        return _DeepCheckContext(
            findings=[
                _DoctorFinding(
                    check="remote_auth_probe",
                    severity="critical",
                    status=_CHECK_STATUS_FAIL,
                    repairable=True,
                    message=f"Remote auth probe failed: {exc}",
                    suggested_action="Run notebooklm auth refresh",
                ),
                _DoctorFinding(
                    check="rpc_canary",
                    severity="warning",
                    status=_CHECK_STATUS_WARN,
                    repairable=False,
                    message="RPC canary skipped because the remote auth probe did not succeed.",
                ),
            ]
        )

    return _DeepCheckContext(
        findings=[
            _DoctorFinding(
                check="remote_auth_probe",
                severity="info",
                status=_CHECK_STATUS_PASS,
                repairable=False,
                message="Remote auth probe refreshed tokens successfully.",
            )
        ],
        auth_tokens=auth_tokens,
    )


def _evaluate_rpc_canary(auth_tokens: Any) -> _DoctorFinding:
    async def _probe() -> None:
        async with NotebookLMClient(auth_tokens) as client:
            await client.notebooks.list()

    try:
        run_async(_probe())
    except Exception as exc:
        return _DoctorFinding(
            check="rpc_canary",
            severity="critical",
            status=_CHECK_STATUS_FAIL,
            repairable=True,
            message=f"RPC canary failed: {exc}",
            suggested_action="Run notebooklm auth refresh",
        )
    return _DoctorFinding(
        check="rpc_canary",
        severity="info",
        status=_CHECK_STATUS_PASS,
        repairable=False,
        message="RPC canary succeeded against LIST_NOTEBOOKS.",
    )


_CHECK_BUILDERS = {
    "auth_snapshot_present": _evaluate_auth_snapshot_present,
    "auth_snapshot_fresh": _evaluate_auth_snapshot_fresh,
    "build_label_present": _evaluate_build_label_present,
    "db_openable": _evaluate_db_openable,
    "schema_current": _evaluate_schema_current,
    "write_permissions_ok": _evaluate_write_permissions_ok,
    "notebooklm_home_consistent": _evaluate_notebooklm_home_consistent,
}

_DEEP_CHECK_BUILDERS = {
    "cache_integrity_ok": _evaluate_cache_integrity,
    "foreign_keys_ok": _evaluate_foreign_keys,
    "fts_health_ok": _evaluate_fts_health,
}

_CATEGORY_CHECK_BUILDERS = {
    "workspace_tables_ready": _evaluate_workspace_tables_ready,
    "workspace_index_fresh": _evaluate_workspace_index_fresh,
    "radar_tables_ready": _evaluate_radar_tables_ready,
    "radar_watch_runs_healthy": _evaluate_radar_watch_runs_healthy,
    "inbox_tables_ready": _evaluate_inbox_tables_ready,
    "inbox_cluster_links_consistent": _evaluate_inbox_cluster_links_consistent,
}

_ALL_CHECK_BUILDERS = {
    **_CHECK_BUILDERS,
    **_DEEP_CHECK_BUILDERS,
    **_CATEGORY_CHECK_BUILDERS,
}


def _doctor_check_categories(capabilities: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    raw_categories = capabilities.get("doctor_check_categories")
    if not isinstance(raw_categories, dict):
        return {}

    categories: dict[str, tuple[str, ...]] = {}
    for category, raw_checks in raw_categories.items():
        if not isinstance(category, str) or not isinstance(raw_checks, list):
            continue
        check_names = tuple(check_name for check_name in raw_checks if isinstance(check_name, str))
        if check_names:
            categories[category] = check_names
    return categories


def _evaluate_requested_checks(
    ctx: click.Context,
    state: _DoctorState,
    *,
    check_names: tuple[str, ...],
) -> list[_DoctorFinding]:
    findings: list[_DoctorFinding] = []
    seen: set[str] = set()
    auth_probe_context: _DeepCheckContext | None = None

    for check_name in check_names:
        if check_name in seen:
            continue
        seen.add(check_name)

        if check_name == "remote_auth_probe":
            if auth_probe_context is None:
                auth_probe_context = _evaluate_remote_auth_probe(ctx, state)
            findings.extend(
                finding
                for finding in auth_probe_context.findings
                if finding.check == "remote_auth_probe"
            )
            continue

        if check_name == "rpc_canary":
            if auth_probe_context is None:
                auth_probe_context = _evaluate_remote_auth_probe(ctx, state)
            if auth_probe_context.auth_tokens is not None:
                findings.append(_evaluate_rpc_canary(auth_probe_context.auth_tokens))
            else:
                findings.extend(
                    finding
                    for finding in auth_probe_context.findings
                    if finding.check == "rpc_canary"
                )
            continue

        builder = _ALL_CHECK_BUILDERS.get(check_name)
        if builder is not None:
            findings.append(builder(state))

    return findings


def _doctor_repairs(state: _DoctorState) -> list[_DoctorRepair]:
    repairs: list[_DoctorRepair] = []
    if not state.home_dir.exists():
        repairs.append(
            _DoctorRepair(
                kind="create_directory",
                path=state.home_dir,
                description="Create NOTEBOOKLM_HOME.",
            )
        )

    browser_profile_dir = Path(state.path_info["browser_profile_dir"])
    if not browser_profile_dir.exists():
        repairs.append(
            _DoctorRepair(
                kind="create_directory",
                path=browser_profile_dir,
                description="Create the browser profile directory.",
            )
        )

    legacy_storage_path = Path(state.path_info["storage_path"])
    if _needs_legacy_profile_mapping(state):
        repairs.append(
            _DoctorRepair(
                kind="migrate_legacy_profile_mapping",
                path=legacy_storage_path,
                description=(
                    "Import the legacy storage_state/browser_profile layout into the profile cache."
                ),
            )
        )

    auth_storage_path = _broken_auth_snapshot_path(state)
    if auth_storage_path is not None:
        repairs.append(
            _DoctorRepair(
                kind="mark_auth_snapshot_invalid",
                path=auth_storage_path,
                description=(
                    "Mark the persisted auth snapshot invalid because it no longer matches "
                    "the current storage cookies."
                ),
            )
        )

    stale_leases = _count_stale_leases(state)
    if stale_leases:
        repairs.append(
            _DoctorRepair(
                kind="expire_stale_leases",
                path=state.db_path,
                description=(
                    f"Expire {stale_leases} stale lease"
                    f"{'' if stale_leases == 1 else 's'} from the local cache."
                ),
            )
        )

    if _fts_tables_need_rebuild(state):
        repairs.append(
            _DoctorRepair(
                kind="rebuild_fts_indexes",
                path=state.db_path,
                description="Rebuild history and workspace FTS tables from cached local rows.",
            )
        )

    stuck_watch_runs = _count_stuck_watch_runs(state)
    if stuck_watch_runs:
        repairs.append(
            _DoctorRepair(
                kind="retry_stuck_watches",
                path=state.db_path,
                description=(
                    f"Cancel {stuck_watch_runs} stuck watch run"
                    f"{'' if stuck_watch_runs == 1 else 's'} and reschedule "
                    "their watches for immediate retry."
                ),
            )
        )

    notebooks_needing_resync = _count_notebooks_needing_metadata_resync(state)
    if notebooks_needing_resync:
        repairs.append(
            _DoctorRepair(
                kind="resync_notebook_metadata",
                path=state.db_path,
                description=(
                    f"Resync metadata for {notebooks_needing_resync} cached notebook"
                    f"{'' if notebooks_needing_resync == 1 else 's'} with incomplete local detail."
                ),
            )
        )

    if _needs_vacuum_analyze(state, repairs):
        repairs.append(
            _DoctorRepair(
                kind="vacuum_analyze",
                path=state.db_path,
                description=(
                    "Checkpoint the SQLite WAL, vacuum the cache database, "
                    "and refresh planner statistics with ANALYZE."
                ),
            )
        )

    return repairs


def _needs_legacy_profile_mapping(state: _DoctorState) -> bool:
    if state.requested_storage_path is not None or not has_legacy_profile_layout():
        return False
    if not state.db_exists:
        return True

    profile_count = _query_readonly_scalar(state, "SELECT COUNT(*) FROM profiles")
    if profile_count is None:
        return False
    return int(profile_count) == 0


def _count_stale_leases(state: _DoctorState) -> int:
    if not state.db_exists or state.db_error is not None:
        return 0
    count = _query_readonly_scalar(
        state,
        """
        SELECT COUNT(*)
        FROM leases
        WHERE expires_at < ?
        """,
        (_utc_now_iso(),),
    )
    return int(count or 0)


def _fts_tables_need_rebuild(state: _DoctorState) -> bool:
    return _history_fts_needs_rebuild(state) or _workspace_fts_needs_rebuild(state)


def _history_fts_needs_rebuild(state: _DoctorState) -> bool:
    if not state.db_exists or state.db_error is not None:
        return False

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        current_row = connection.execute("SELECT COUNT(*) FROM history_fts").fetchone()
        expected_row = connection.execute(
            "SELECT COUNT(*) FROM query_runs WHERE status = 'completed'"
        ).fetchone()
    except sqlite3.Error:
        return True
    finally:
        if connection is not None:
            connection.close()

    current = int(current_row[0] or 0) if current_row is not None else 0
    expected = int(expected_row[0] or 0) if expected_row is not None else 0
    return current != expected


def _workspace_fts_needs_rebuild(state: _DoctorState) -> bool:
    if not state.db_exists or state.db_error is not None:
        return False

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        current_row = connection.execute("SELECT COUNT(*) FROM workspace_index_fts").fetchone()
        expected_row = connection.execute(
            "SELECT COUNT(*) FROM workspace_index_entries"
        ).fetchone()
    except sqlite3.Error:
        return True
    finally:
        if connection is not None:
            connection.close()

    current = int(current_row[0] or 0) if current_row is not None else 0
    expected = int(expected_row[0] or 0) if expected_row is not None else 0
    return current != expected


def _count_stuck_watch_runs(state: _DoctorState) -> int:
    if not state.db_exists or state.db_error is not None:
        return 0

    placeholders = ",".join("?" for _ in _STUCK_WATCH_STATUSES)
    count = _query_readonly_scalar(
        state,
        f"""
        SELECT COUNT(*)
        FROM watch_runs
        JOIN watches
            ON watches.id = watch_runs.watch_id
        WHERE watches.status = 'active'
          AND watch_runs.status IN ({placeholders})
          AND watch_runs.ended_at IS NULL
        """,
        _STUCK_WATCH_STATUSES,
    )
    return int(count or 0)


def _count_notebooks_needing_metadata_resync(state: _DoctorState) -> int:
    if (
        not state.db_exists
        or state.db_error is not None
        or state.auth_missing
        or state.auth_error is not None
    ):
        return 0

    count = _query_readonly_scalar(
        state,
        """
        SELECT COUNT(*)
        FROM notebooks
        WHERE profile_id = ?
          AND tombstoned_at IS NULL
          AND (
              index_synced_at IS NULL
              OR detail_synced_at IS NULL
              OR raw_json IS NULL
          )
        """,
        (state.profile_id,),
    )
    return int(count or 0)


def _needs_vacuum_analyze(state: _DoctorState, repairs: list[_DoctorRepair]) -> bool:
    if not state.db_exists or state.db_error is not None:
        return False

    if any(
        repair.kind in {"rebuild_fts_indexes", "retry_stuck_watches"}
        for repair in repairs
    ):
        return True

    freelist_count = _query_readonly_scalar(state, "PRAGMA freelist_count")
    return int(freelist_count or 0) > 0


def _broken_auth_snapshot_path(state: _DoctorState) -> Path | None:
    if state.auth_result is None or state.auth_result.get("profile") is None:
        return None

    snapshot = state.auth_result["snapshot"]
    if not snapshot["present"] or snapshot["matches_storage_cookies"] is not False:
        return None
    if snapshot["status"] == "invalid":
        return None

    storage_path = state.auth_result.get("storage_path")
    if not storage_path:
        return None
    return Path(storage_path)


def _query_readonly_scalar(
    state: _DoctorState,
    sql: str,
    params: tuple[object, ...] = (),
) -> int | None:
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        row = connection.execute(sql, params).fetchone()
    except sqlite3.Error:
        return None
    finally:
        if connection is not None:
            connection.close()

    if row is None:
        return None
    return int(row[0]) if row[0] is not None else None


def _workspace_tags_text(tags_json: str | None) -> str | None:
    if not tags_json:
        return None
    try:
        tags = json.loads(tags_json)
    except json.JSONDecodeError:
        return tags_json
    if not isinstance(tags, list):
        return tags_json
    values = [str(tag).strip() for tag in tags if str(tag).strip()]
    return " ".join(values) or None


def _extract_citation_source_ids(citations_json: str | None) -> tuple[str, ...]:
    if not citations_json:
        return ()

    try:
        citations = json.loads(citations_json)
    except json.JSONDecodeError:
        return ()
    if not isinstance(citations, list):
        return ()

    source_ids: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        source_id: str | None = None
        if isinstance(citation, dict):
            candidate = citation.get("source_id") or citation.get("sourceId")
            if isinstance(candidate, str):
                source_id = candidate.strip() or None
        elif isinstance(citation, str):
            source_id = citation.strip() or None
        if source_id is None or source_id in seen:
            continue
        seen.add(source_id)
        source_ids.append(source_id)
    return tuple(source_ids)


def _history_source_titles(
    *,
    notebook_id: str | None,
    citations_json: str | None,
    source_title_by_id: dict[str, str],
    source_titles_by_notebook: dict[str, str],
) -> str | None:
    citation_titles = [
        source_title_by_id[source_id]
        for source_id in _extract_citation_source_ids(citations_json)
        if source_id in source_title_by_id and source_title_by_id[source_id]
    ]
    if citation_titles:
        return ", ".join(citation_titles)
    if notebook_id is None:
        return None
    return source_titles_by_notebook.get(notebook_id)


def _rebuild_fts_indexes(state: _DoctorState) -> None:
    with connect_db(state.db_path) as connection:
        source_title_by_id: dict[str, str] = {}
        source_titles_by_notebook_lists: dict[str, list[str]] = {}
        source_rows = connection.execute(
            """
            SELECT source_id, notebook_id, title
            FROM sources
            WHERE tombstoned_at IS NULL
            ORDER BY notebook_id ASC, source_id ASC
            """
        ).fetchall()
        for row in source_rows:
            title = row["title"]
            if not isinstance(title, str) or not title.strip():
                continue
            source_title_by_id[row["source_id"]] = title
            source_titles_by_notebook_lists.setdefault(row["notebook_id"], []).append(title)
        source_titles_by_notebook = {
            notebook_id: ", ".join(titles)
            for notebook_id, titles in source_titles_by_notebook_lists.items()
        }

        history_rows = connection.execute(
            """
            SELECT
                query_runs.id AS run_id,
                query_runs.trace_id AS trace_id,
                query_runs.profile_id AS profile_id,
                query_runs.notebook_id AS notebook_id,
                query_runs.prompt_text AS prompt_text,
                query_results.answer_text AS answer_text,
                notebooks.title AS notebook_title,
                query_results.citations_json AS citations_json
            FROM query_runs
            LEFT JOIN query_results
                ON query_results.query_run_id = query_runs.id
            LEFT JOIN notebooks
                ON notebooks.notebook_id = query_runs.notebook_id
            WHERE query_runs.status = 'completed'
            ORDER BY COALESCE(query_runs.ended_at, query_runs.started_at) ASC, query_runs.id ASC
            """
        ).fetchall()
        workspace_rows = connection.execute(
            """
            SELECT
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
                content_text
            FROM workspace_index_entries
            ORDER BY updated_at ASC, id ASC
            """
        ).fetchall()

        connection.execute("DROP TABLE IF EXISTS history_fts")
        connection.execute(_HISTORY_FTS_CREATE_SQL)
        for row in history_rows:
            connection.execute(
                """
                INSERT INTO history_fts (
                    run_id,
                    trace_id,
                    profile_id,
                    prompt_text,
                    answer_text,
                    notebook_title,
                    source_titles
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["run_id"],
                    row["trace_id"],
                    row["profile_id"],
                    row["prompt_text"],
                    row["answer_text"],
                    row["notebook_title"],
                    _history_source_titles(
                        notebook_id=row["notebook_id"],
                        citations_json=row["citations_json"],
                        source_title_by_id=source_title_by_id,
                        source_titles_by_notebook=source_titles_by_notebook,
                    ),
                ),
            )

        connection.execute("DROP TABLE IF EXISTS workspace_index_fts")
        connection.execute(_WORKSPACE_FTS_CREATE_SQL)
        for row in workspace_rows:
            connection.execute(
                """
                INSERT INTO workspace_index_fts (
                    entry_id,
                    workspace_id,
                    profile_id,
                    notebook_id,
                    notebook_title,
                    notebook_summary,
                    title_aliases_text,
                    source_titles_text,
                    source_snippets_text,
                    tags_text,
                    recent_query_text,
                    content_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["workspace_id"],
                    row["profile_id"],
                    row["notebook_id"],
                    row["notebook_title"],
                    row["notebook_summary"],
                    row["title_aliases_text"],
                    row["source_titles_text"],
                    row["source_snippets_text"],
                    _workspace_tags_text(row["tags_json"]),
                    row["recent_query_text"],
                    row["content_text"],
                ),
            )


def _retry_stuck_watches(state: _DoctorState) -> None:
    now = _utc_now_iso()
    placeholders = ",".join("?" for _ in _STUCK_WATCH_STATUSES)
    with connect_db(state.db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT watch_runs.id AS run_id, watch_runs.watch_id AS watch_id
            FROM watch_runs
            JOIN watches
                ON watches.id = watch_runs.watch_id
            WHERE watches.status = 'active'
              AND watch_runs.status IN ({placeholders})
              AND watch_runs.ended_at IS NULL
            ORDER BY watch_runs.started_at ASC, watch_runs.id ASC
            """,
            _STUCK_WATCH_STATUSES,
        ).fetchall()
        if not rows:
            return

        watch_ids = sorted({row["watch_id"] for row in rows})
        result_json = json.dumps(
            {
                "doctor_repair": "retry_stuck_watch",
                "rescheduled_at": now,
                "status": "cancelled",
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        for row in rows:
            connection.execute(
                """
                UPDATE watch_runs
                SET ended_at = ?, status = 'cancelled', result_json = ?
                WHERE id = ?
                """,
                (now, result_json, row["run_id"]),
            )
        for watch_id in watch_ids:
            connection.execute(
                """
                UPDATE watches
                SET next_run_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now, watch_id),
            )


def _notebook_ids_needing_metadata_resync(connection, *, profile_id: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT notebook_id
        FROM notebooks
        WHERE profile_id = ?
          AND tombstoned_at IS NULL
          AND (
              index_synced_at IS NULL
              OR detail_synced_at IS NULL
              OR raw_json IS NULL
          )
        ORDER BY notebook_id ASC
        """,
        (profile_id,),
    ).fetchall()
    return [str(row["notebook_id"]) for row in rows]


def _resync_notebook_metadata(ctx: click.Context, state: _DoctorState) -> None:
    auth_tokens = get_auth_tokens(ctx)

    async def _repair() -> None:
        async with NotebookLMClient(auth_tokens) as client:
            with connect_db(state.db_path) as connection:
                target_notebook_ids = _notebook_ids_needing_metadata_resync(
                    connection,
                    profile_id=state.profile_id,
                )
                if not target_notebook_ids:
                    return

                index_state = await sync_notebook_index(
                    client,
                    connection,
                    profile_id=state.profile_id,
                    storage_path=auth_tokens.storage_path,
                    force_refresh=True,
                    trigger=_DOCTOR_FIX_SYNC_TRIGGER,
                )
                active_notebook_ids = {
                    notebook.notebook_id for notebook in index_state.notebooks
                }
                for notebook_id in target_notebook_ids:
                    if notebook_id not in active_notebook_ids:
                        continue
                    await sync_notebook_detail(
                        client,
                        connection,
                        notebook_id,
                        profile_id=state.profile_id,
                        storage_path=auth_tokens.storage_path,
                        force_refresh=True,
                        trigger=_DOCTOR_FIX_SYNC_TRIGGER,
                    )

    run_async(_repair())


def _vacuum_analyze_cache(state: _DoctorState) -> None:
    with connect_db(state.db_path) as connection:
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        connection.execute("ANALYZE")


def _apply_doctor_repair(
    ctx: click.Context, state: _DoctorState, repair: _DoctorRepair
) -> None:
    if repair.kind == "create_directory":
        repair.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        repair.path.chmod(0o700)
        return
    if repair.kind == "migrate_legacy_profile_mapping":
        with connect_db(state.db_path) as connection:
            bootstrap_legacy_profile(connection)
        return
    if repair.kind == "mark_auth_snapshot_invalid":
        with connect_db(state.db_path) as connection:
            manager = ProfileManager(connection)
            snapshot = manager.require_auth_snapshot(state.profile_id)
            manager.upsert_auth_snapshot(
                state.profile_id,
                cookie_fingerprint=snapshot.cookie_fingerprint,
                csrf_token=snapshot.csrf_token,
                session_id=snapshot.session_id,
                build_label=snapshot.build_label,
                captured_at=snapshot.captured_at,
                validated_at=None,
                status="invalid",
                source=snapshot.source,
            )
        return
    if repair.kind == "expire_stale_leases":
        with connect_db(state.db_path) as connection:
            LeaseRepository(connection).expire_stale(active_at=_utc_now_iso())
        return
    if repair.kind == "rebuild_fts_indexes":
        _rebuild_fts_indexes(state)
        return
    if repair.kind == "retry_stuck_watches":
        _retry_stuck_watches(state)
        return
    if repair.kind == "resync_notebook_metadata":
        _resync_notebook_metadata(ctx, state)
        return
    if repair.kind == "vacuum_analyze":
        _vacuum_analyze_cache(state)
        return
    raise ValueError(f"Unsupported doctor repair kind: {repair.kind}")


def _apply_doctor_repairs(
    ctx: click.Context,
    state: _DoctorState,
    repairs: list[_DoctorRepair],
    *,
    dry_run: bool,
) -> list[dict[str, Any]]:
    applied_repairs: list[dict[str, Any]] = []
    for repair in repairs:
        applied = not dry_run
        if applied:
            _apply_doctor_repair(ctx, state, repair)
        applied_repairs.append(repair.to_dict(applied=applied))
    return applied_repairs


def _record_doctor_events(
    state: _DoctorState,
    *,
    trace_id: str,
    run_id: str,
    mode: str,
    findings: list[_DoctorFinding] | None = None,
    repairs: list[dict[str, Any]] | None = None,
) -> None:
    if not state.db_path.exists():
        return

    try:
        with connect_db(state.db_path, apply_migrations=False) as connection:
            append_run_event(
                connection,
                trace_id,
                "doctor.run.started",
                run_id=run_id,
                payload={"mode": mode, "profile_id": state.profile_id},
            )
            for finding in findings or []:
                append_run_event(
                    connection,
                    trace_id,
                    "doctor.check.completed",
                    run_id=run_id,
                    payload={
                        "mode": mode,
                        "check": finding.check,
                        "severity": finding.severity,
                        "status": finding.status,
                        "repairable": finding.repairable,
                    },
                )
            for repair in repairs or []:
                if not repair["applied"]:
                    continue
                append_run_event(
                    connection,
                    trace_id,
                    "doctor.repair.completed",
                    run_id=run_id,
                    payload={
                        "mode": mode,
                        "kind": repair["kind"],
                        "path": repair["path"],
                    },
                )
    except Exception:
        return


def _doctor_result(
    ctx: click.Context,
    *,
    deep: bool = False,
    category: str | None = None,
) -> tuple[dict[str, Any], int]:
    state = _collect_state(ctx)
    capabilities = load_capabilities()
    category_map = _doctor_check_categories(capabilities)
    if category is None:
        check_names = tuple(
            check_name
            for check_name in capabilities.get("doctor_checks", [])
            if isinstance(check_name, str)
        )
        if deep:
            check_names += tuple(_DEEP_CHECK_BUILDERS) + ("remote_auth_probe", "rpc_canary")
        trace_mode = "doctor"
        route_mode = "deep" if deep else "fast"
        result_mode = "deep" if deep else "fast"
        event_mode = "deep" if deep else "fast"
        reason = "doctor deep checks" if deep else "doctor fast local checks"
    else:
        check_names = category_map.get(category, ())
        if not check_names:
            raise click.ClickException(f"Unsupported doctor check category '{category}'.")
        trace_mode = "doctor_check"
        route_mode = "doctor_check"
        result_mode = "check"
        event_mode = f"check:{category}"
        reason = f"doctor {category} targeted checks"

    findings = _evaluate_requested_checks(ctx, state, check_names=check_names)

    failed = sum(1 for finding in findings if finding.status == _CHECK_STATUS_FAIL)
    warned = sum(1 for finding in findings if finding.status == _CHECK_STATUS_WARN)
    passed = sum(1 for finding in findings if finding.status == _CHECK_STATUS_PASS)
    repairable = sum(
        1
        for finding in findings
        if finding.repairable and finding.status != _CHECK_STATUS_PASS
    )
    if failed:
        status = "broken"
        exit_code = 2
    elif warned:
        status = "degraded"
        exit_code = 1
    else:
        status = "healthy"
        exit_code = 0

    next_steps: list[str] = []
    for finding in findings:
        if finding.suggested_action and finding.suggested_action not in next_steps:
            next_steps.append(finding.suggested_action)

    trace_id, run_id = _trace_and_run_id(ctx, trace_mode)
    result = {
        "mode": result_mode,
        "status": status,
        "summary": {
            "passed": passed,
            "warned": warned,
            "failed": warned + failed,
            "repairable": repairable,
        },
        "findings": [finding.to_dict() for finding in findings],
        "repairs": [],
        "next_steps": next_steps,
        "auth": state.auth_result
        if state.auth_result is not None
        else {
            "auth_source": "unavailable",
            "storage_path": str(state.requested_storage_path)
            if state.requested_storage_path is not None
            else None,
            "error": state.auth_error,
        },
        "paths": state.path_info,
        "db": {
            "path": str(state.db_path),
            "exists": state.db_exists,
            "schema_version": state.schema_version,
            "expected_schema_version": LATEST_SCHEMA_VERSION,
        },
    }
    if category is not None:
        result["category"] = category
    envelope = Envelope(
        ok=status == "healthy",
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.DOCTOR,
            mode=route_mode,
            notebook_id=None,
            profile_id=state.profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason=reason,
            transport=Transport(kind="local"),
        ),
        result=result,
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=0),
    ).to_dict()
    _record_doctor_events(
        state,
        trace_id=trace_id,
        run_id=run_id,
        mode=event_mode,
        findings=findings,
    )
    return envelope, exit_code


def _doctor_fix_result(ctx: click.Context, *, dry_run: bool) -> tuple[dict[str, Any], int]:
    state = _collect_state(ctx)
    repairs = _doctor_repairs(state)
    applied_repairs = _apply_doctor_repairs(ctx, state, repairs, dry_run=dry_run)
    trace_id, run_id = _trace_and_run_id(ctx, "doctor_fix")

    if not applied_repairs:
        status = "noop"
        next_steps = ["Run `notebooklm doctor --json` if you need a fresh diagnosis."]
    elif dry_run:
        status = "preview"
        next_steps = ["Run `notebooklm doctor fix --json` to apply the planned repairs."]
    else:
        status = "repaired"
        next_steps = ["Run `notebooklm doctor --json` to verify the updated local state."]

    envelope = Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.DOCTOR,
            mode="doctor_fix",
            notebook_id=None,
            profile_id=state.profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="doctor fix local repair plan",
            transport=Transport(kind="local"),
        ),
        result={
            "mode": "fix",
            "status": status,
            "dry_run": dry_run,
            "summary": {
                "planned": len(applied_repairs),
                "applied": sum(1 for repair in applied_repairs if repair["applied"]),
            },
            "repairs": applied_repairs,
            "next_steps": next_steps,
        },
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=0),
    ).to_dict()
    _record_doctor_events(
        state,
        trace_id=trace_id,
        run_id=run_id,
        mode="fix",
        repairs=applied_repairs,
    )
    return envelope, 0


def _support_bundle_output_path(home_dir: Path, output_path: Path | None) -> Path:
    if output_path is not None:
        return output_path.expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return home_dir / _SUPPORT_BUNDLE_DIRNAME / f"support-bundle-{timestamp}.json"


def _redact_bundle_value(value: Any, *, field_name: str = "") -> Any:
    normalized_field = field_name.casefold()
    if any(fragment in normalized_field for fragment in _REDACTED_KEY_FRAGMENTS):
        return _REDACTED_PLACEHOLDER
    if isinstance(value, dict):
        return {
            key: _redact_bundle_value(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_bundle_value(item, field_name=field_name) for item in value]
    return value


def _bundle_db_stats(state: _DoctorState) -> dict[str, Any]:
    stats = {
        "path": str(state.db_path),
        "exists": state.db_exists,
        "schema_version": state.schema_version,
        "expected_schema_version": LATEST_SCHEMA_VERSION,
        "error": state.db_error,
        "table_counts": {},
    }
    if not state.db_exists or state.db_error is not None:
        return stats

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table_name in (
            "profiles",
            "auth_snapshots",
            "notebooks",
            "sources",
            "run_events",
            "sync_runs",
        ):
            if table_name in tables:
                stats["table_counts"][table_name] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                )
    except sqlite3.Error as exc:
        stats["error"] = str(exc)
    finally:
        if connection is not None:
            connection.close()

    return stats


def _bundle_recent_events(state: _DoctorState) -> list[dict[str, Any]]:
    if not state.db_exists or state.db_error is not None:
        return []

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        return [
            {
                "event_id": event.event_id,
                "trace_id": event.trace_id,
                "run_id": event.run_id,
                "kind": event.kind,
                "ts": event.ts,
                "payload": _redact_bundle_value(event.payload, field_name="payload"),
            }
            for event in tail_run_events(connection, limit=_SUPPORT_BUNDLE_EVENT_LIMIT)
        ]
    except sqlite3.Error:
        return []
    finally:
        if connection is not None:
            connection.close()


def _bundle_recent_failures(state: _DoctorState) -> list[dict[str, Any]]:
    if not state.db_exists or state.db_error is not None:
        return []

    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly_db(state)
        rows = connection.execute(
            """
            SELECT
                id,
                trace_id,
                scope,
                target_id,
                started_at,
                ended_at,
                error_text
            FROM sync_runs
            WHERE status = 'failed'
            ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
            LIMIT ?
            """,
            (_SUPPORT_BUNDLE_FAILURE_LIMIT,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        if connection is not None:
            connection.close()

    return [
        {
            "run_id": row["id"],
            "trace_id": row["trace_id"],
            "scope": row["scope"],
            "target_id": row["target_id"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "error_text": row["error_text"],
        }
        for row in rows
    ]


def _build_support_bundle(ctx: click.Context) -> dict[str, Any]:
    state = _collect_state(ctx)
    doctor_payload, _ = _doctor_result(ctx, deep=False)
    capabilities = load_capabilities()
    return {
        "bundle_version": 1,
        "generated_at": _utc_now_iso(),
        "manifest": {
            "command_count": len(capabilities.get("commands", {})),
            "doctor_checks": capabilities.get("doctor_checks", []),
        },
        "environment": {
            "package_version": PACKAGE_VERSION,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "paths": state.path_info,
        "db": _bundle_db_stats(state),
        "auth": _redact_bundle_value(
            state.auth_result
            if state.auth_result is not None
            else {
                "auth_source": "unavailable",
                "storage_path": str(state.requested_storage_path)
                if state.requested_storage_path is not None
                else None,
                "error": state.auth_error,
            }
        ),
        "doctor": {
            "status": doctor_payload["result"]["status"],
            "summary": doctor_payload["result"]["summary"],
            "findings": doctor_payload["result"]["findings"],
            "next_steps": doctor_payload["result"]["next_steps"],
        },
        "recent_events": _bundle_recent_events(state),
        "recent_failures": _bundle_recent_failures(state),
        "selected_logs": [],
    }


def _doctor_bundle_result(
    ctx: click.Context,
    *,
    output_path: Path | None,
) -> tuple[dict[str, Any], int]:
    state = _collect_state(ctx)
    bundle = _build_support_bundle(ctx)
    bundle_path = _support_bundle_output_path(state.home_dir, output_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    bundle_path.chmod(0o600)
    trace_id, run_id = _trace_and_run_id(ctx, "doctor_bundle")

    envelope = Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.DOCTOR,
            mode="doctor_bundle",
            notebook_id=None,
            profile_id=state.profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="support bundle local artifact",
            transport=Transport(kind="local"),
        ),
        result={
            "mode": "bundle",
            "status": "created",
            "bundle_path": str(bundle_path),
            "bundle": bundle,
        },
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=0),
    ).to_dict()
    return envelope, 0


def _render_doctor(payload: dict[str, Any]) -> None:
    result = payload["result"]
    summary = result["summary"]
    findings = result["findings"]

    summary_table = Table(title="Doctor")
    summary_table.add_column("Metric", style="dim")
    summary_table.add_column("Value", style="cyan")
    summary_table.add_row("Status", result["status"])
    summary_table.add_row("Mode", result.get("mode", "fast"))
    if result.get("category"):
        summary_table.add_row("Category", result["category"])
    auth = result.get("auth", {})
    summary_table.add_row("Auth Source", auth.get("auth_source") or auth.get("source") or "-")
    summary_table.add_row("Storage Path", auth.get("storage_path") or "-")
    summary_table.add_row("Cache DB", result["db"]["path"])
    summary_table.add_row("Passed", str(summary["passed"]))
    summary_table.add_row("Failed", str(summary["failed"]))
    summary_table.add_row("Repairable", str(summary["repairable"]))
    console.print(summary_table)

    findings_table = Table(title="Doctor Findings")
    findings_table.add_column("Check", style="dim")
    findings_table.add_column("Status")
    findings_table.add_column("Message", style="cyan")
    findings_table.add_column("Next Step", style="yellow")
    for finding in findings:
        status = finding["status"]
        if status == _CHECK_STATUS_FAIL:
            rendered_status = "[red]fail[/red]"
        elif status == _CHECK_STATUS_WARN:
            rendered_status = "[yellow]warn[/yellow]"
        else:
            rendered_status = "[green]pass[/green]"
        findings_table.add_row(
            finding["check"],
            rendered_status,
            finding["message"],
            finding.get("suggested_action", "-"),
        )
    console.print(findings_table)

    if result["next_steps"]:
        console.print("\n[bold]Next Steps[/bold]")
        for step in result["next_steps"]:
            console.print(f"  - {step}")


def _render_doctor_fix(payload: dict[str, Any]) -> None:
    result = payload["result"]
    summary = result["summary"]

    summary_table = Table(title="Doctor Fix")
    summary_table.add_column("Metric", style="dim")
    summary_table.add_column("Value", style="cyan")
    summary_table.add_row("Status", result["status"])
    summary_table.add_row("Dry Run", str(result["dry_run"]))
    summary_table.add_row("Planned", str(summary["planned"]))
    summary_table.add_row("Applied", str(summary["applied"]))
    console.print(summary_table)

    repairs = result["repairs"]
    if not repairs:
        console.print("\n[yellow]No local repairs are currently planned.[/yellow]")
    else:
        repairs_table = Table(title="Repairs")
        repairs_table.add_column("Kind", style="dim")
        repairs_table.add_column("Path", style="cyan")
        repairs_table.add_column("Description", style="white")
        repairs_table.add_column("Applied", style="yellow")
        for repair in repairs:
            repairs_table.add_row(
                repair["kind"],
                repair["path"],
                repair["description"],
                "yes" if repair["applied"] else "no",
            )
        console.print(repairs_table)

    if result["next_steps"]:
        console.print("\n[bold]Next Steps[/bold]")
        for step in result["next_steps"]:
            console.print(f"  - {step}")


def _render_doctor_bundle(payload: dict[str, Any]) -> None:
    result = payload["result"]
    bundle = result["bundle"]
    console.print(f"[green]Created support bundle:[/green] {result['bundle_path']}")
    console.print(f"[bold]Doctor status:[/bold] {bundle['doctor']['status']}")
    console.print(f"[bold]Recent events:[/bold] {len(bundle['recent_events'])}")
    console.print(f"[bold]Recent failures:[/bold] {len(bundle['recent_failures'])}")


def register_doctor_commands(cli) -> None:
    """Register fast doctor diagnostics on the root CLI shell."""
    doctor_categories = _doctor_check_categories(load_capabilities())

    @cli.group("doctor", invoke_without_command=True)
    @click.option("--deep", is_flag=True, help="Run remote probes and deep SQLite health checks")
    @click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
    @manifest_risk_guard(_MANIFEST_DOCTOR_COMMAND)
    @click.pass_context
    def doctor(ctx: click.Context, deep: bool, json_output: bool) -> None:
        """Run fast local health checks for auth, cache, and path state."""
        if ctx.invoked_subcommand is not None:
            return
        started_at = time.perf_counter()
        payload, exit_code = _doctor_result(ctx, deep=deep)
        payload["diagnostics"]["elapsed_ms"] = max(
            0, int((time.perf_counter() - started_at) * 1000)
        )

        if json_output:
            json_output_response(payload)
        else:
            _render_doctor(payload)

        if exit_code:
            raise SystemExit(exit_code)

    @doctor.command("check")
    @click.argument(
        "category",
        type=click.Choice(sorted(doctor_categories), case_sensitive=False),
    )
    @click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
    @manifest_risk_guard("doctor.check")
    @click.pass_context
    def doctor_check(ctx: click.Context, category: str, json_output: bool) -> None:
        """Run one targeted doctor diagnostics category."""
        started_at = time.perf_counter()
        payload, exit_code = _doctor_result(ctx, category=category.casefold())
        payload["diagnostics"]["elapsed_ms"] = max(
            0, int((time.perf_counter() - started_at) * 1000)
        )

        if json_output:
            json_output_response(payload)
        else:
            _render_doctor(payload)

        if exit_code:
            raise SystemExit(exit_code)

    @doctor.command("fix")
    @click.option("--dry-run", is_flag=True, help="Show planned local repairs without applying them")
    @click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
    @manifest_risk_guard("doctor.fix")
    @click.pass_context
    def doctor_fix(ctx: click.Context, dry_run: bool, json_output: bool) -> None:
        """Apply low-risk local doctor repairs."""
        started_at = time.perf_counter()
        payload, exit_code = _doctor_fix_result(ctx, dry_run=dry_run)
        payload["diagnostics"]["elapsed_ms"] = max(
            0, int((time.perf_counter() - started_at) * 1000)
        )

        if json_output:
            json_output_response(payload)
        else:
            _render_doctor_fix(payload)

        if exit_code:
            raise SystemExit(exit_code)

    @doctor.command("bundle")
    @click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False))
    @click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
    @manifest_risk_guard("doctor.bundle")
    @click.pass_context
    def doctor_bundle(ctx: click.Context, output_path: Path | None, json_output: bool) -> None:
        """Create a redacted local support bundle artifact."""
        started_at = time.perf_counter()
        payload, exit_code = _doctor_bundle_result(ctx, output_path=output_path)
        payload["diagnostics"]["elapsed_ms"] = max(
            0, int((time.perf_counter() - started_at) * 1000)
        )

        if json_output:
            json_output_response(payload)
        else:
            _render_doctor_bundle(payload)

        if exit_code:
            raise SystemExit(exit_code)

    @click.group("support-bundle")
    def support_bundle_group() -> None:
        """Compatibility alias for support bundle creation."""

    @support_bundle_group.command("create")
    @click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False))
    @click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
    @manifest_risk_guard("doctor.bundle")
    @click.pass_context
    def support_bundle_create(
        ctx: click.Context,
        output_path: Path | None,
        json_output: bool,
    ) -> None:
        """Create a redacted local support bundle artifact."""
        started_at = time.perf_counter()
        payload, exit_code = _doctor_bundle_result(ctx, output_path=output_path)
        payload["diagnostics"]["elapsed_ms"] = max(
            0, int((time.perf_counter() - started_at) * 1000)
        )

        if json_output:
            json_output_response(payload)
        else:
            _render_doctor_bundle(payload)

        if exit_code:
            raise SystemExit(exit_code)

    cli.add_command(support_bundle_group)


__all__ = ["register_doctor_commands"]
