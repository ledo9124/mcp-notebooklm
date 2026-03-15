"""Persistence helpers for local workspace run history."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import sqlite3

from ..local.repositories import WorkspaceRecord, WorkspaceRunRecord, WorkspaceRunRepository
from .planning import WorkspaceQueryPlan
from .synthesis import WorkspaceSynthesisResult


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_run_id(workspace_id: str, trace_id: str, mode: str) -> str:
    digest = hashlib.sha1(f"{workspace_id}::{trace_id}::{mode}".encode("utf-8")).hexdigest()
    return f"wr_{digest[:20]}"


def _json_text(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _plan_payload(plan: WorkspaceQueryPlan) -> dict[str, object]:
    return {
        "mode": plan.mode,
        "reason": plan.reason,
        "candidate_count": plan.candidate_count,
        "used_fallback": plan.used_fallback,
        "selected_notebooks": [
            {
                "id": candidate.notebook_id,
                "title": candidate.notebook_title,
                "selection_reason": candidate.selection_reason,
                "member_priority": candidate.member_priority,
                "fts_rank": candidate.fts_rank,
            }
            for candidate in plan.selected_candidates
        ],
    }


def _result_payload(result: WorkspaceSynthesisResult) -> dict[str, object]:
    return {
        "answer": result.answer,
        "provenance": [asdict(item) for item in result.provenance],
    }


def start_workspace_run(
    connection: sqlite3.Connection,
    *,
    workspace: WorkspaceRecord,
    trace_id: str,
    query_text: str,
    plan: WorkspaceQueryPlan,
    mode: str = "ask",
    started_at: str | None = None,
) -> WorkspaceRunRecord:
    """Persist a running workspace run before fan-out begins."""
    record = WorkspaceRunRecord(
        id=_stable_run_id(workspace.id, trace_id, mode),
        trace_id=trace_id,
        profile_id=workspace.profile_id,
        started_at=started_at or _utc_now(),
        ended_at=None,
        status="running",
        workspace_id=workspace.id,
        mode=mode,
        query_text=query_text,
        selected_notebooks_json=_json_text(list(plan.selected_notebook_ids)),
        plan_json=_json_text(_plan_payload(plan)),
        result_json=None,
    )
    WorkspaceRunRepository(connection).upsert(record)
    return record


def complete_workspace_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    result: WorkspaceSynthesisResult,
    status: str = "completed",
    ended_at: str | None = None,
) -> WorkspaceRunRecord:
    """Persist the final synthesized result for one workspace run."""
    repository = WorkspaceRunRepository(connection)
    existing = repository.get(run_id)
    if existing is None:
        raise KeyError(f"Workspace run not found: {run_id}")

    record = WorkspaceRunRecord(
        id=existing.id,
        trace_id=existing.trace_id,
        profile_id=existing.profile_id,
        started_at=existing.started_at,
        ended_at=ended_at or _utc_now(),
        status=status,
        workspace_id=existing.workspace_id,
        mode=existing.mode,
        query_text=existing.query_text,
        selected_notebooks_json=existing.selected_notebooks_json,
        plan_json=existing.plan_json,
        result_json=_json_text(_result_payload(result)),
    )
    repository.upsert(record)
    return record


__all__ = ["complete_workspace_run", "start_workspace_run"]
