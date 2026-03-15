"""Change-radar review commands backed by the local SQLite cache."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import time
from typing import Any

import click
from rich.table import Table

from ..client import NotebookLMClient
from ..contracts import CacheUpdates, Diagnostics, Envelope, Intent, Route, Transport, manifest_risk_guard
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..local.events import append_run_event
from ..local.repositories import ResearchRunRepository, SourceRepository, WorkspaceRepository
from ..radar import list_due_watches, run_watch
from .helpers import console, get_auth_tokens, json_error_response, json_output_response, run_async
from .research import _decode_raw_payload, import_research_run, start_research_run, wait_for_research_run
from .session import _trace_and_run_id


_EVENT_OPEN_STATES = ("new", "briefed", "queued_inbox")
_EVENT_STATES = _EVENT_OPEN_STATES + ("ignored", "applied")
_EVENT_SEVERITIES = ("noise", "minor", "material", "critical")
_WATCH_INTERVAL_CHOICES = ("hourly", "daily", "weekly", "monthly")
_WATCH_INTERVAL_DELTAS = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}
_RESEARCH_WATCH_TIMEOUT_SECONDS = 300
_RESEARCH_WATCH_POLL_INTERVAL_SECONDS = 5
_WATCH_ADD_RPC_BINDING = RPC_MAP[(Intent.LOCAL_MUTATION.value, "watch_add")]
_WATCH_LIST_RPC_BINDING = RPC_MAP[(Intent.LOCAL_METADATA.value, "watch_list")]
_WATCH_PAUSE_RPC_BINDING = RPC_MAP[(Intent.LOCAL_MUTATION.value, "watch_pause")]
_WATCH_RUN_NOW_RPC_BINDING = RPC_MAP[(Intent.LOCAL_MUTATION.value, "watch_run_now")]
_RADAR_STATUS_RPC_BINDING = RPC_MAP[(Intent.RADAR_STATUS.value, "radar_status")]
_RADAR_LIST_RPC_BINDING = RPC_MAP[(Intent.RADAR_STATUS.value, "radar_list")]
_RADAR_BRIEF_RPC_BINDING = RPC_MAP[(Intent.RADAR_BRIEF.value, "radar_brief")]
_RADAR_IGNORE_RPC_BINDING = RPC_MAP[(Intent.LOCAL_MUTATION.value, "radar_ignore")]


@click.group()
def watch() -> None:
    """Manage local change-radar watch definitions."""


@click.group()
def radar() -> None:
    """Review local change-radar events and briefings."""


@dataclass(frozen=True)
class _CliWatchRunResult:
    """Local watch-run payload used for CLI-managed watch types."""

    watch_id: str
    watch_run_id: str
    trace_id: str
    status: str
    changed: bool
    baseline_created: bool
    signature_before: str | None
    signature_after: str | None
    source_revision_id: str | None
    change_event_id: str | None
    delta_briefing_id: str | None
    change_kind: str | None
    severity: str | None
    invalidated_sync_runs: int
    next_run_at: str | None
    error_text: str | None = None
    research_id_before: str | None = None
    research_id_after: str | None = None
    sources_found: int | None = None
    staged: int | None = None
    existing_inbox_count: int | None = None
    inbox_item_ids: list[str] | None = None
    message: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _decode_json(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _resolve_profile_id(connection, explicit_profile_id: str | None) -> str:
    if explicit_profile_id:
        return explicit_profile_id

    row = connection.execute(
        """
        SELECT profile_id
        FROM profiles
        ORDER BY is_default DESC, updated_at DESC, profile_id ASC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise click.ClickException("No local profiles found in cache.db.")
    return str(row["profile_id"])


def _watch_row_to_dict(row) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "scope_type": row["scope_type"],
        "scope_id": row["scope_id"],
        "watch_kind": row["watch_kind"],
        "status": row["status"],
        "next_run_at": row["next_run_at"],
        "last_run_at": row["last_run_at"],
    }
    policy = _decode_json(row["policy_json"])
    if policy is not None:
        payload["policy"] = policy
    schedule = _decode_json(row["schedule_json"])
    if schedule is not None:
        payload["schedule"] = schedule

    if row["source_id"] is not None or row["scope_type"] == "source":
        payload["source"] = {
            "id": row["source_id"] or row["scope_id"],
            "title": row["source_title"],
            "uri": row["source_uri"],
            "status": row["source_status"],
            "freshness_state": row["source_freshness_state"],
        }
    if row["notebook_id"] is not None:
        payload["notebook"] = {
            "id": row["notebook_id"],
            "title": row["notebook_title"],
        }
    if row["workspace_id"] is not None or row["scope_type"] == "workspace":
        payload["workspace"] = {
            "id": row["workspace_id"] or row["scope_id"],
            "name": row["workspace_name"],
            "slug": row["workspace_slug"],
        }
    if row["research_id"] is not None or row["scope_type"] == "research_query":
        payload["research"] = {
            "id": row["research_id"] or row["scope_id"],
            "query": row["research_query_text"],
            "mode": row["research_mode"],
            "status": row["research_status"],
            "discovered_count": row["research_discovered_count"],
            "imported_count": row["research_imported_count"],
            "updated_at": row["research_updated_at"],
        }

    return payload


def _watch_run_payload(result) -> dict[str, Any]:
    payload = {
        "watch_id": result.watch_id,
        "watch_run_id": result.watch_run_id,
        "trace_id": result.trace_id,
        "status": result.status,
        "changed": result.changed,
        "baseline_created": result.baseline_created,
        "signature_before": result.signature_before,
        "signature_after": result.signature_after,
        "source_revision_id": result.source_revision_id,
        "change_event_id": result.change_event_id,
        "delta_briefing_id": result.delta_briefing_id,
        "change_kind": result.change_kind,
        "severity": result.severity,
        "invalidated_sync_runs": result.invalidated_sync_runs,
        "next_run_at": result.next_run_at,
    }
    if result.error_text is not None:
        payload["error_text"] = result.error_text
    research_id_before = getattr(result, "research_id_before", None)
    if research_id_before is not None:
        payload["research_id_before"] = research_id_before
    research_id_after = getattr(result, "research_id_after", None)
    if research_id_after is not None:
        payload["research_id_after"] = research_id_after
    sources_found = getattr(result, "sources_found", None)
    if sources_found is not None:
        payload["sources_found"] = sources_found
    staged = getattr(result, "staged", None)
    if staged is not None:
        payload["staged"] = staged
    existing_inbox_count = getattr(result, "existing_inbox_count", None)
    if existing_inbox_count is not None:
        payload["existing_inbox_count"] = existing_inbox_count
    inbox_item_ids = getattr(result, "inbox_item_ids", None)
    if inbox_item_ids:
        payload["inbox_item_ids"] = inbox_item_ids
    message = getattr(result, "message", None)
    if message is not None:
        payload["message"] = message
    return payload


def _watch_notebook_id(watch_payload: dict[str, Any]) -> str | None:
    notebook = watch_payload.get("notebook")
    if isinstance(notebook, dict):
        notebook_id = notebook.get("id")
        if isinstance(notebook_id, str) and notebook_id:
            return notebook_id
    return None


def _watch_run_cache_updates(result, *, watch_payload: dict[str, Any]) -> CacheUpdates:
    tables_touched = ["watch_runs", "watches"]
    if result.source_revision_id is not None:
        tables_touched.append("source_revisions")
    if result.change_event_id is not None:
        tables_touched.append("change_events")
    if result.delta_briefing_id is not None:
        tables_touched.append("delta_briefings")
    if watch_payload["scope_type"] == "source" and result.status == "completed":
        tables_touched.append("sources")
    if watch_payload["scope_type"] == "research_query":
        tables_touched.append("research_runs")
        if getattr(result, "staged", 0) or getattr(result, "existing_inbox_count", 0):
            tables_touched.extend(["inbox_items", "inbox_clusters"])
    deduped: list[str] = []
    for table_name in tables_touched:
        if table_name not in deduped:
            deduped.append(table_name)
    return CacheUpdates(tables_touched=deduped)


def _watch_target_label(watch_payload: dict[str, Any]) -> str:
    if watch_payload["scope_type"] == "source":
        source = watch_payload.get("source", {})
        if isinstance(source, dict):
            return str(source.get("title") or source.get("id") or watch_payload["scope_id"])
    if watch_payload["scope_type"] == "workspace":
        workspace = watch_payload.get("workspace", {})
        if isinstance(workspace, dict):
            return str(workspace.get("name") or workspace.get("slug") or watch_payload["scope_id"])
    if watch_payload["scope_type"] == "research_query":
        research = watch_payload.get("research", {})
        if isinstance(research, dict):
            return str(research.get("query") or research.get("id") or watch_payload["scope_id"])
    return str(watch_payload["scope_id"])


def _list_watch_rows(connection, *, profile_id: str) -> list[Any]:
    return connection.execute(
        """
        SELECT
            w.id,
            w.profile_id,
            w.scope_type,
            w.scope_id,
            w.watch_kind,
            w.policy_json,
            w.status,
            w.schedule_json,
            w.next_run_at,
            w.last_run_at,
            s.source_id,
            s.title AS source_title,
            s.origin_uri AS source_uri,
              s.status AS source_status,
              s.freshness_state AS source_freshness_state,
              rr.research_id,
              rr.mode AS research_mode,
              rr.query_text AS research_query_text,
              rr.status AS research_status,
              rr.discovered_count AS research_discovered_count,
              rr.imported_count AS research_imported_count,
              rr.updated_at AS research_updated_at,
              COALESCE(s.notebook_id, rr.notebook_id) AS notebook_id,
              n.title AS notebook_title,
              ws.id AS workspace_id,
              ws.name AS workspace_name,
              ws.slug AS workspace_slug
          FROM watches AS w
          LEFT JOIN sources AS s
              ON w.scope_type = 'source' AND s.source_id = w.scope_id
          LEFT JOIN research_runs AS rr
              ON w.scope_type = 'research_query' AND rr.research_id = w.scope_id
          LEFT JOIN notebooks AS n
              ON COALESCE(s.notebook_id, rr.notebook_id) = n.notebook_id
          LEFT JOIN workspaces AS ws
              ON w.scope_type = 'workspace' AND ws.id = w.scope_id
        WHERE w.profile_id = ?
        ORDER BY
            CASE WHEN w.next_run_at IS NULL THEN 0 ELSE 1 END,
            w.next_run_at ASC,
            w.id ASC
        """,
        (profile_id,),
    ).fetchall()


def _fetch_watch_row(connection, watch_id: str):
    return connection.execute(
        """
        SELECT
            w.id,
            w.profile_id,
            w.scope_type,
            w.scope_id,
            w.watch_kind,
            w.policy_json,
            w.status,
            w.schedule_json,
            w.next_run_at,
            w.last_run_at,
            s.source_id,
            s.title AS source_title,
            s.origin_uri AS source_uri,
              s.status AS source_status,
              s.freshness_state AS source_freshness_state,
              rr.research_id,
              rr.mode AS research_mode,
              rr.query_text AS research_query_text,
              rr.status AS research_status,
              rr.discovered_count AS research_discovered_count,
              rr.imported_count AS research_imported_count,
              rr.updated_at AS research_updated_at,
              COALESCE(s.notebook_id, rr.notebook_id) AS notebook_id,
              n.title AS notebook_title,
              ws.id AS workspace_id,
              ws.name AS workspace_name,
              ws.slug AS workspace_slug
          FROM watches AS w
          LEFT JOIN sources AS s
              ON w.scope_type = 'source' AND s.source_id = w.scope_id
          LEFT JOIN research_runs AS rr
              ON w.scope_type = 'research_query' AND rr.research_id = w.scope_id
          LEFT JOIN notebooks AS n
              ON COALESCE(s.notebook_id, rr.notebook_id) = n.notebook_id
          LEFT JOIN workspaces AS ws
              ON w.scope_type = 'workspace' AND ws.id = w.scope_id
        WHERE w.id = ?
        """,
        (watch_id,),
    ).fetchone()


def _resolve_source_watch_target(source) -> tuple[str, dict[str, Any]]:
    origin_uri = (source.origin_uri or "").strip()
    if origin_uri.startswith(("http://", "https://")):
        return "web_diff", {"materiality": "normal", "target_url": origin_uri}
    if origin_uri.startswith("file://") or origin_uri.startswith("/"):
        return "local_file_hash", {"materiality": "normal", "target_path": origin_uri}
    if source.drive_syncable:
        raise click.ClickException(
            f"Source {source.source_id} is Drive-backed and drive-sync watches are not supported yet."
        )
    raise click.ClickException(
        f"Source {source.source_id} is not watchable yet. Only cached web URLs and local-file sources are supported."
    )


def _create_source_watch(connection, *, profile_id: str, source_id: str, interval: str) -> dict[str, Any]:
    source = SourceRepository(connection).get(source_id)
    if source is None or source.profile_id != profile_id:
        raise click.ClickException(f"Source not found in cache.db: {source_id}")

    watch_kind, policy = _resolve_source_watch_target(source)
    watch_id = f"watch_{secrets.token_hex(6)}"
    now_text = _utc_now().isoformat()
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
                profile_id,
                "source",
                source.source_id,
                watch_kind,
                _json_text(policy),
                "active",
                _json_text({"interval": interval}),
                now_text,
                None,
            ),
        )
    row = _fetch_watch_row(connection, watch_id)
    assert row is not None
    return _watch_row_to_dict(row)


def _create_research_watch(connection, *, profile_id: str, research_id: str, interval: str) -> dict[str, Any]:
    record = ResearchRunRepository(connection).get(research_id)
    if record is None or record.profile_id != profile_id:
        raise click.ClickException(f"Research run not found in cache.db: {research_id}")

    raw_payload = _decode_raw_payload(record)
    search_source = str(raw_payload.get("search_source") or "web").casefold()
    watch_id = f"watch_{secrets.token_hex(6)}"
    now_text = _utc_now().isoformat()
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
                profile_id,
                "research_query",
                research_id,
                "deep_research",
                _json_text(
                    {
                        "mode": record.mode,
                        "query": record.query_text,
                        "search_source": search_source,
                    }
                ),
                "active",
                _json_text({"interval": interval}),
                now_text,
                None,
            ),
        )
    row = _fetch_watch_row(connection, watch_id)
    assert row is not None
    return _watch_row_to_dict(row)


def _research_watch_signature(payload: dict[str, Any]) -> str:
    normalized_sources = []
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "").strip()
        url = str(source.get("url") or "").strip()
        if not title and not url:
            continue
        normalized_sources.append({"title": title, "url": url})
    normalized_sources.sort(key=lambda item: (item["url"], item["title"]))
    encoded = _json_text({"sources": normalized_sources}).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _watch_next_run_at(watch_payload: dict[str, Any], *, now: datetime) -> str | None:
    schedule = watch_payload.get("schedule")
    if not isinstance(schedule, dict):
        return None
    interval = str(schedule.get("interval") or "").casefold()
    delta = _WATCH_INTERVAL_DELTAS.get(interval)
    if delta is None:
        return None
    return (now + delta).isoformat()


def _persist_watch_run(
    *,
    watch_id: str,
    watch_run_id: str,
    trace_id: str,
    profile_id: str,
    started_at: str,
    ended_at: str,
    status: str,
    signature_before: str | None,
    signature_after: str | None,
    result_payload: dict[str, Any],
) -> None:
    with connect_db() as connection:
        with connection:
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
                    watch_run_id,
                    watch_id,
                    trace_id,
                    profile_id,
                    started_at,
                    ended_at,
                    status,
                    signature_before,
                    signature_after,
                    _json_text(result_payload),
                ),
            )


def _update_watch_schedule(
    *,
    watch_id: str,
    last_run_at: str,
    next_run_at: str | None,
    scope_id: str | None = None,
) -> None:
    sql = """
        UPDATE watches
        SET last_run_at = ?,
            next_run_at = ?
    """
    params: list[Any] = [last_run_at, next_run_at]
    if scope_id is not None:
        sql += ", scope_id = ?"
        params.append(scope_id)
    sql += " WHERE id = ?"
    params.append(watch_id)
    with connect_db() as connection:
        with connection:
            connection.execute(sql, params)


async def _run_research_query_watch(
    ctx: click.Context,
    *,
    watch_id: str,
    trace_id: str,
) -> _CliWatchRunResult:
    timestamp = _utc_now()
    started_at = timestamp.isoformat()
    ended_at = started_at
    watch_run_id = f"wtr_{secrets.token_hex(6)}"
    research_id_after: str | None = None
    signature_after: str | None = None

    with connect_db() as connection:
        row = _fetch_watch_row(connection, watch_id)
        if row is None:
            raise click.ClickException(f"Watch not found in cache.db: {watch_id}")
        watch_payload = _watch_row_to_dict(row)
        baseline = ResearchRunRepository(connection).get(str(row["scope_id"]))
        if baseline is None:
            raise click.ClickException(f"Research run not found in cache.db: {row['scope_id']}")

    baseline_payload = _decode_raw_payload(baseline)
    signature_before = _research_watch_signature(baseline_payload)
    next_run_at = _watch_next_run_at(watch_payload, now=timestamp)
    storage_path = ctx.obj.get("storage_path") if ctx.obj else None

    try:
        try:
            client_auth = get_auth_tokens(ctx)
        except FileNotFoundError as exc:
            raise click.ClickException("Authentication required to run a research watch.") from exc

        async with NotebookLMClient(client_auth) as client:
            started = await start_research_run(
                ctx,
                client=client,
                notebook_id=baseline.notebook_id,
                query=baseline.query_text,
                search_source=str(baseline_payload.get("search_source") or "web"),
                mode=baseline.mode,
            )
            research_id_after = str(started["research_id"])
            completed = await wait_for_research_run(
                ctx,
                client=client,
                notebook_id=baseline.notebook_id,
                timeout=_RESEARCH_WATCH_TIMEOUT_SECONDS,
                interval=_RESEARCH_WATCH_POLL_INTERVAL_SECONDS,
                import_all=False,
                research_id=research_id_after,
                storage_path=storage_path,
                json_output=False,
            )

            ended_at = _utc_now().isoformat()
            signature_after = _research_watch_signature(completed)
            changed = signature_after != signature_before
            sources_found = int(completed.get("sources_found") or len(completed.get("sources", [])))
            staged = 0
            existing_inbox_count = 0
            inbox_item_ids: list[str] = []
            message: str | None = None
            if changed:
                staged_result = await import_research_run(
                    ctx,
                    client=client,
                    research_id=research_id_after,
                    dry_run=False,
                    approval_token=None,
                    json_output=False,
                    storage_path=storage_path,
                    status=completed,
                )
                staged = int(staged_result.get("staged", 0))
                existing_inbox_count = int(staged_result.get("existing_inbox_count", 0))
                inbox_item_ids = list(staged_result.get("inbox_item_ids", []))
                message = staged_result.get("message")

        result_payload = {
            "changed": changed,
            "message": message,
            "research_id_after": research_id_after,
            "research_id_before": baseline.research_id,
            "sources_found": sources_found,
            "staged": staged,
            "existing_inbox_count": existing_inbox_count,
            "inbox_item_ids": inbox_item_ids,
        }
        _update_watch_schedule(
            watch_id=watch_id,
            last_run_at=ended_at,
            next_run_at=next_run_at,
            scope_id=research_id_after,
        )
        _persist_watch_run(
            watch_id=watch_id,
            watch_run_id=watch_run_id,
            trace_id=trace_id,
            profile_id=baseline.profile_id,
            started_at=started_at,
            ended_at=ended_at,
            status="completed",
            signature_before=signature_before,
            signature_after=signature_after,
            result_payload=result_payload,
        )
        with connect_db() as connection:
            append_run_event(
                connection,
                trace_id,
                "watch.run.completed",
                run_id=watch_run_id,
                payload={
                    **result_payload,
                    "status": "completed",
                    "watch_id": watch_id,
                },
            )
        return _CliWatchRunResult(
            watch_id=watch_id,
            watch_run_id=watch_run_id,
            trace_id=trace_id,
            status="completed",
            changed=changed,
            baseline_created=False,
            signature_before=signature_before,
            signature_after=signature_after,
            source_revision_id=None,
            change_event_id=None,
            delta_briefing_id=None,
            change_kind="research_results_changed" if changed else None,
            severity=None,
            invalidated_sync_runs=0,
            next_run_at=next_run_at,
            research_id_before=baseline.research_id,
            research_id_after=research_id_after,
            sources_found=sources_found,
            staged=staged,
            existing_inbox_count=existing_inbox_count,
            inbox_item_ids=inbox_item_ids,
            message=message,
        )
    except Exception as exc:
        ended_at = _utc_now().isoformat()
        error_payload = {
            "changed": False,
            "error": str(exc),
            "research_id_after": research_id_after,
            "research_id_before": baseline.research_id,
        }
        _update_watch_schedule(
            watch_id=watch_id,
            last_run_at=ended_at,
            next_run_at=next_run_at,
        )
        _persist_watch_run(
            watch_id=watch_id,
            watch_run_id=watch_run_id,
            trace_id=trace_id,
            profile_id=baseline.profile_id,
            started_at=started_at,
            ended_at=ended_at,
            status="failed",
            signature_before=signature_before,
            signature_after=signature_after,
            result_payload=error_payload,
        )
        with connect_db() as connection:
            append_run_event(
                connection,
                trace_id,
                "watch.run.completed",
                run_id=watch_run_id,
                payload={
                    "changed": False,
                    "error": str(exc),
                    "research_id_after": research_id_after,
                    "research_id_before": baseline.research_id,
                    "status": "failed",
                    "watch_id": watch_id,
                },
            )
        return _CliWatchRunResult(
            watch_id=watch_id,
            watch_run_id=watch_run_id,
            trace_id=trace_id,
            status="failed",
            changed=False,
            baseline_created=False,
            signature_before=signature_before,
            signature_after=signature_after,
            source_revision_id=None,
            change_event_id=None,
            delta_briefing_id=None,
            change_kind=None,
            severity=None,
            invalidated_sync_runs=0,
            next_run_at=next_run_at,
            error_text=str(exc),
            research_id_before=baseline.research_id,
            research_id_after=research_id_after,
            message=str(exc),
        )


def _emit_watch_error(
    *,
    ctx: click.Context,
    binding,
    code: str,
    message: str,
    reason: str,
    json_output: bool,
    started_at: float,
    profile_id: str = "default",
    notebook_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    if json_output:
        json_error_response(
            code,
            message,
            extra=extra,
            ctx=ctx,
            binding=binding,
            profile_id=profile_id,
            notebook_id=notebook_id,
            reason=reason,
            source_of_truth="local_cache",
            cache_mode="offline",
            diagnostics=Diagnostics(
                retries=0,
                auth_refreshed=False,
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            ),
        )
    raise click.ClickException(message)


def _count_by_key(rows, key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row[key])
        counts[value] = counts.get(value, 0) + 1
    return counts


def _event_row_to_dict(row) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "watch_id": row["watch_id"],
        "watch_kind": row["watch_kind"],
        "scope_type": row["scope_type"],
        "scope_id": row["scope_id"],
        "source_id": row["source_id"],
        "source_title": row["source_title"],
        "source_uri": row["source_uri"],
        "source_freshness_state": row["source_freshness_state"],
        "notebook_id": row["notebook_id"],
        "notebook_title": row["notebook_title"],
        "workspace_id": row["workspace_id"],
        "change_kind": row["change_kind"],
        "severity": row["severity"],
        "state": row["state"],
        "created_at": row["created_at"],
        "briefing_id": row["briefing_id"],
        "briefing_created_at": row["briefing_created_at"],
    }
    if "profile_id" in row.keys():
        payload["profile_id"] = row["profile_id"]
    data = _decode_json(row["data_json"])
    if data is not None:
        payload["data"] = data
    summary_md = row["summary_md"]
    if summary_md is not None:
        payload["summary_md"] = summary_md
    return payload


def _briefing_row_to_dict(row) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "change_event_id": row["change_event_id"],
        "created_at": row["created_at"],
        "summary_md": row["summary_md"],
    }
    impact = _decode_json(row["impact_json"])
    if impact is not None:
        payload["impact"] = impact
    recommended_actions = _decode_json(row["recommended_actions_json"])
    if recommended_actions is not None:
        payload["recommended_actions"] = recommended_actions
    return payload


def _fetch_status_payload(connection, profile_id: str) -> dict[str, Any]:
    due_count = sum(
        1 for watch in list_due_watches(connection) if watch.profile_id == profile_id
    )
    watch_rows = connection.execute(
        """
        SELECT id, status
        FROM watches
        WHERE profile_id = ?
        ORDER BY id ASC
        """,
        (profile_id,),
    ).fetchall()
    event_rows = connection.execute(
        """
        SELECT
            e.id,
            e.watch_id,
            e.change_kind,
            e.severity,
            e.state,
            e.created_at,
            e.data_json,
            w.watch_kind,
            w.scope_type,
            w.scope_id,
            e.source_id,
            s.title AS source_title,
            s.origin_uri AS source_uri,
            s.freshness_state AS source_freshness_state,
            e.notebook_id,
            n.title AS notebook_title,
            e.workspace_id,
            b.id AS briefing_id,
            b.created_at AS briefing_created_at,
            b.summary_md
        FROM change_events AS e
        INNER JOIN watches AS w ON w.id = e.watch_id
        LEFT JOIN sources AS s ON s.source_id = e.source_id
        LEFT JOIN notebooks AS n ON n.notebook_id = e.notebook_id
        LEFT JOIN delta_briefings AS b ON b.change_event_id = e.id
        WHERE w.profile_id = ?
        ORDER BY e.created_at DESC, e.id DESC
        """,
        (profile_id,),
    ).fetchall()

    events = [_event_row_to_dict(row) for row in event_rows]
    latest_event = events[0] if events else None
    open_count = sum(1 for event in events if event["state"] in _EVENT_OPEN_STATES)

    return {
        "profile_id": profile_id,
        "watches": {
            "total": len(watch_rows),
            "active": sum(1 for row in watch_rows if row["status"] == "active"),
            "paused": sum(1 for row in watch_rows if row["status"] == "paused"),
            "due_now": due_count,
            "by_status": _count_by_key(watch_rows, "status"),
        },
        "events": {
            "total": len(events),
            "open": open_count,
            "by_state": _count_by_key(event_rows, "state"),
            "by_severity": _count_by_key(event_rows, "severity"),
        },
        "latest_event": latest_event,
    }


def _list_event_rows(
    connection,
    *,
    profile_id: str,
    state_filter: str | None,
    severity_filter: str | None,
    include_all: bool,
) -> list[Any]:
    clauses = ["w.profile_id = ?"]
    params: list[object] = [profile_id]

    if state_filter is not None:
        clauses.append("e.state = ?")
        params.append(state_filter)
    elif not include_all:
        placeholders = ",".join("?" for _ in _EVENT_OPEN_STATES)
        clauses.append(f"e.state IN ({placeholders})")
        params.extend(_EVENT_OPEN_STATES)

    if severity_filter is not None:
        clauses.append("e.severity = ?")
        params.append(severity_filter)

    where_sql = " AND ".join(clauses)
    return connection.execute(
        f"""
        SELECT
            e.id,
            e.watch_id,
            e.change_kind,
            e.severity,
            e.state,
            e.created_at,
            e.data_json,
            w.watch_kind,
            w.scope_type,
            w.scope_id,
            e.source_id,
            s.title AS source_title,
            s.origin_uri AS source_uri,
            s.freshness_state AS source_freshness_state,
            e.notebook_id,
            n.title AS notebook_title,
            e.workspace_id,
            b.id AS briefing_id,
            b.created_at AS briefing_created_at,
            b.summary_md
        FROM change_events AS e
        INNER JOIN watches AS w ON w.id = e.watch_id
        LEFT JOIN sources AS s ON s.source_id = e.source_id
        LEFT JOIN notebooks AS n ON n.notebook_id = e.notebook_id
        LEFT JOIN delta_briefings AS b ON b.change_event_id = e.id
        WHERE {where_sql}
        ORDER BY e.created_at DESC, e.id DESC
        """,
        tuple(params),
    ).fetchall()


def _fetch_event_detail(connection, event_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    row = connection.execute(
        """
        SELECT
            e.id,
            e.watch_id,
            e.change_kind,
            e.severity,
            e.state,
            e.created_at,
            e.data_json,
            w.profile_id,
            w.scope_type,
            w.scope_id,
            w.watch_kind,
            w.policy_json,
            w.status AS watch_status,
            w.schedule_json,
            w.next_run_at,
            w.last_run_at,
            e.source_id,
            s.title AS source_title,
            s.origin_uri AS source_uri,
            s.freshness_state AS source_freshness_state,
            e.notebook_id,
            n.title AS notebook_title,
            e.workspace_id,
            b.id AS briefing_id,
            b.change_event_id,
            b.summary_md,
            b.impact_json,
            b.recommended_actions_json,
            b.created_at AS briefing_created_at
        FROM change_events AS e
        INNER JOIN watches AS w ON w.id = e.watch_id
        LEFT JOIN sources AS s ON s.source_id = e.source_id
        LEFT JOIN notebooks AS n ON n.notebook_id = e.notebook_id
        LEFT JOIN delta_briefings AS b ON b.change_event_id = e.id
        WHERE e.id = ?
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        raise click.ClickException(f"Radar event not found: {event_id}")
    if row["briefing_id"] is None:
        raise click.ClickException(f"Radar event {event_id} does not have a stored delta briefing.")

    event_payload = _event_row_to_dict(row)
    watch_payload = {
        "id": row["watch_id"],
        "profile_id": row["profile_id"],
        "scope_type": row["scope_type"],
        "scope_id": row["scope_id"],
        "watch_kind": row["watch_kind"],
        "status": row["watch_status"],
        "next_run_at": row["next_run_at"],
        "last_run_at": row["last_run_at"],
    }
    policy = _decode_json(row["policy_json"])
    if policy is not None:
        watch_payload["policy"] = policy
    schedule = _decode_json(row["schedule_json"])
    if schedule is not None:
        watch_payload["schedule"] = schedule
    briefing_payload = _briefing_row_to_dict(
        {
            "id": row["briefing_id"],
            "change_event_id": row["change_event_id"],
            "summary_md": row["summary_md"],
            "impact_json": row["impact_json"],
            "recommended_actions_json": row["recommended_actions_json"],
            "created_at": row["briefing_created_at"],
        }
    )
    return event_payload, watch_payload, briefing_payload


def _has_open_material_event(connection, *, source_id: str, exclude_event_id: str | None = None) -> bool:
    placeholders = ",".join("?" for _ in _EVENT_OPEN_STATES)
    params: list[object] = [source_id, *_EVENT_OPEN_STATES]
    extra = ""
    if exclude_event_id is not None:
        extra = " AND id != ?"
        params.append(exclude_event_id)
    row = connection.execute(
        f"""
        SELECT 1
        FROM change_events
        WHERE source_id = ?
          AND severity IN ('material', 'critical')
          AND state IN ({placeholders}){extra}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        tuple(params),
    ).fetchone()
    return row is not None


def _ignore_event(event_id: str) -> tuple[dict[str, Any], str | None]:
    with connect_db() as connection:
        row = connection.execute(
            """
            SELECT
                e.id,
                e.watch_id,
                e.source_id,
                e.notebook_id,
                e.workspace_id,
                e.change_kind,
                e.severity,
                e.state,
                e.created_at,
                e.data_json,
                w.profile_id,
                w.scope_type,
                w.scope_id,
                w.watch_kind,
                s.title AS source_title,
                s.origin_uri AS source_uri,
                s.freshness_state AS source_freshness_state,
                n.title AS notebook_title,
                b.id AS briefing_id,
                b.created_at AS briefing_created_at,
                b.summary_md
            FROM change_events AS e
            INNER JOIN watches AS w ON w.id = e.watch_id
            LEFT JOIN sources AS s ON s.source_id = e.source_id
            LEFT JOIN notebooks AS n ON n.notebook_id = e.notebook_id
            LEFT JOIN delta_briefings AS b ON b.change_event_id = e.id
            WHERE e.id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            raise click.ClickException(f"Radar event not found: {event_id}")
        if row["state"] == "applied":
            raise click.ClickException(f"Radar event {event_id} is already applied and cannot be ignored.")

        with connection:
            connection.execute(
                """
                UPDATE change_events
                SET state = 'ignored'
                WHERE id = ?
                """,
                (event_id,),
            )

            refreshed_source_state: str | None = row["source_freshness_state"]
            source_id = row["source_id"]
            if source_id is not None:
                repository = SourceRepository(connection)
                source = repository.get(source_id)
                if source is not None:
                    if _has_open_material_event(connection, source_id=source_id):
                        refreshed_source_state = "stale"
                    else:
                        refreshed_source_state = "fresh"
                    if source.freshness_state != refreshed_source_state:
                        repository.upsert(replace(source, freshness_state=refreshed_source_state))

        updated_row = connection.execute(
            """
            SELECT
                e.id,
                e.watch_id,
                e.source_id,
                e.notebook_id,
                e.workspace_id,
                e.change_kind,
                e.severity,
                e.state,
                e.created_at,
                e.data_json,
                w.profile_id,
                w.watch_kind,
                w.scope_type,
                w.scope_id,
                s.title AS source_title,
                s.origin_uri AS source_uri,
                s.freshness_state AS source_freshness_state,
                n.title AS notebook_title,
                b.id AS briefing_id,
                b.created_at AS briefing_created_at,
                b.summary_md
            FROM change_events AS e
            INNER JOIN watches AS w ON w.id = e.watch_id
            LEFT JOIN sources AS s ON s.source_id = e.source_id
            LEFT JOIN notebooks AS n ON n.notebook_id = e.notebook_id
            LEFT JOIN delta_briefings AS b ON b.change_event_id = e.id
            WHERE e.id = ?
            """,
            (event_id,),
        ).fetchone()
        assert updated_row is not None
        return _event_row_to_dict(updated_row), refreshed_source_state


def _radar_envelope(
    ctx: click.Context,
    *,
    ok: bool = True,
    binding,
    profile_id: str,
    notebook_id: str | None,
    result: dict[str, Any],
    reason: str,
    elapsed_ms: int,
    cache_updates: CacheUpdates | None = None,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, binding.mode)
    return Envelope(
        ok=ok,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(binding.intent),
            mode=binding.mode,
            notebook_id=notebook_id,
            profile_id=profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason=reason,
            transport=Transport(kind=binding.transport_kind),
        ),
        result=result,
        freshness=None,
        cache_updates=cache_updates or CacheUpdates(),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


@watch.command("add")
@click.option("--source", "source_id", default=None, help="Cached source ID to monitor.")
@click.option(
    "--workspace",
    "workspace_name",
    default=None,
    help="Workspace name to monitor (reserved for a later radar phase).",
)
@click.option(
    "--research",
    "research_id",
    default=None,
    help="Completed research run ID to rerun on schedule.",
)
@click.option(
    "--policy",
    "interval",
    type=click.Choice(_WATCH_INTERVAL_CHOICES, case_sensitive=False),
    default="daily",
    show_default=True,
    help="Schedule policy interval.",
)
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to local default)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("watch.add")
@click.pass_context
def watch_add(
    ctx: click.Context,
    source_id: str | None,
    workspace_name: str | None,
    research_id: str | None,
    interval: str,
    profile_id: str | None,
    json_output: bool,
) -> None:
    """Create a local watch for one cached source or saved research run."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile = _resolve_profile_id(connection, profile_id)
        selected_targets = [value for value in (source_id, workspace_name, research_id) if value is not None]
        if len(selected_targets) != 1:
            _emit_watch_error(
                ctx=ctx,
                binding=_WATCH_ADD_RPC_BINDING,
                code="INVALID_ARGUMENT",
                message="Pass exactly one of --source, --workspace, or --research.",
                reason="Create a local radar watch definition for one cached target.",
                json_output=json_output,
                started_at=started_at,
                profile_id=resolved_profile,
                extra={"expected": ["--source", "--workspace", "--research"]},
            )

        if workspace_name is not None:
            workspace = WorkspaceRepository(connection).get_by_slug(
                resolved_profile, workspace_name.casefold().replace(" ", "-")
            )
            if workspace is None:
                _emit_watch_error(
                    ctx=ctx,
                    binding=_WATCH_ADD_RPC_BINDING,
                    code="WATCH_TARGET_NOT_FOUND",
                    message=f"Workspace not found in cache.db: {workspace_name}",
                    reason="Create a local radar watch definition for one cached target.",
                    json_output=json_output,
                    started_at=started_at,
                    profile_id=resolved_profile,
                )
            _emit_watch_error(
                ctx=ctx,
                binding=_WATCH_ADD_RPC_BINDING,
                code="WATCH_SCOPE_UNSUPPORTED",
                message=(
                    "Workspace watches are not supported yet on this branch. "
                    "Use `watch add --source ...` for the R1 radar surface."
                ),
                reason="Create a local radar watch definition for one cached target.",
                json_output=json_output,
                started_at=started_at,
                profile_id=resolved_profile,
                extra={"requested_scope": "workspace", "workspace_id": workspace.id},
            )

        try:
            if research_id is not None:
                watch_payload = _create_research_watch(
                    connection,
                    profile_id=resolved_profile,
                    research_id=str(research_id),
                    interval=interval.casefold(),
                )
            else:
                watch_payload = _create_source_watch(
                    connection,
                    profile_id=resolved_profile,
                    source_id=str(source_id),
                    interval=interval.casefold(),
                )
        except click.ClickException as exc:
            _emit_watch_error(
                ctx=ctx,
                binding=_WATCH_ADD_RPC_BINDING,
                code="WATCH_TARGET_UNSUPPORTED",
                message=str(exc),
                reason="Create a local radar watch definition for one cached target.",
                json_output=json_output,
                started_at=started_at,
                profile_id=resolved_profile,
            )

    if json_output:
        json_output_response(
            _radar_envelope(
                ctx,
                binding=_WATCH_ADD_RPC_BINDING,
                profile_id=resolved_profile,
                notebook_id=_watch_notebook_id(watch_payload),
                result={"profile_id": resolved_profile, "watch": watch_payload},
                reason="Create a local radar watch definition for one cached target.",
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                cache_updates=CacheUpdates(tables_touched=["watches"]),
            )
        )
        return

    console.print(f"[green]Created watch:[/green] {watch_payload['id']}")
    console.print(
        f"[dim]{watch_payload['watch_kind']} {watch_payload['scope_type']} -> "
        f"{_watch_target_label(watch_payload)} ({watch_payload['status']})[/dim]"
    )


@watch.command("list")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to local default)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("watch.list")
@click.pass_context
def watch_list(ctx: click.Context, profile_id: str | None, json_output: bool) -> None:
    """List local watch definitions for the active profile."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile = _resolve_profile_id(connection, profile_id)
        watches = [_watch_row_to_dict(row) for row in _list_watch_rows(connection, profile_id=resolved_profile)]

    if json_output:
        json_output_response(
            _radar_envelope(
                ctx,
                binding=_WATCH_LIST_RPC_BINDING,
                profile_id=resolved_profile,
                notebook_id=_watch_notebook_id(watches[0]) if watches else None,
                result={"profile_id": resolved_profile, "count": len(watches), "watches": watches},
                reason="List locally stored radar watch definitions.",
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
        )
        return

    if not watches:
        console.print(f"[yellow]No watches found for profile {resolved_profile}.[/yellow]")
        return

    table = Table(title=f"Watches ({resolved_profile})")
    table.add_column("ID", style="cyan")
    table.add_column("Status", style="yellow")
    table.add_column("Kind", style="magenta")
    table.add_column("Scope", style="green")
    table.add_column("Target", style="white")
    table.add_column("Next Run", style="dim")
    for watch_payload in watches:
        table.add_row(
            watch_payload["id"],
            watch_payload["status"],
            watch_payload["watch_kind"],
            watch_payload["scope_type"],
            _watch_target_label(watch_payload),
            watch_payload["next_run_at"] or "due now",
        )
    console.print(table)


@watch.command("pause")
@click.argument("watch_id")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("watch.pause")
@click.pass_context
def watch_pause(ctx: click.Context, watch_id: str, json_output: bool) -> None:
    """Pause a local watch definition."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        row = _fetch_watch_row(connection, watch_id)
        if row is None:
            _emit_watch_error(
                ctx=ctx,
                binding=_WATCH_PAUSE_RPC_BINDING,
                code="WATCH_NOT_FOUND",
                message=f"Watch not found in cache.db: {watch_id}",
                reason="Pause an existing local radar watch definition.",
                json_output=json_output,
                started_at=started_at,
            )
        with connection:
            connection.execute(
                """
                UPDATE watches
                SET status = 'paused'
                WHERE id = ?
                """,
                (watch_id,),
            )
        updated_row = _fetch_watch_row(connection, watch_id)
        assert updated_row is not None
        watch_payload = _watch_row_to_dict(updated_row)

    if json_output:
        json_output_response(
            _radar_envelope(
                ctx,
                binding=_WATCH_PAUSE_RPC_BINDING,
                profile_id=watch_payload["profile_id"],
                notebook_id=_watch_notebook_id(watch_payload),
                result={"watch": watch_payload},
                reason="Pause an existing local radar watch definition.",
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                cache_updates=CacheUpdates(tables_touched=["watches"]),
            )
        )
        return

    console.print(f"[green]Paused watch:[/green] {watch_payload['id']}")


@watch.command("run-now")
@click.argument("watch_id")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("watch.run-now")
@click.pass_context
def watch_run_now(ctx: click.Context, watch_id: str, json_output: bool) -> None:
    """Execute one watch immediately using the local radar pipeline."""
    started_at = time.perf_counter()
    trace_id, _ = _trace_and_run_id(ctx, _WATCH_RUN_NOW_RPC_BINDING.mode)
    with connect_db() as connection:
        row = _fetch_watch_row(connection, watch_id)
        if row is None:
            _emit_watch_error(
                ctx=ctx,
                binding=_WATCH_RUN_NOW_RPC_BINDING,
                code="WATCH_NOT_FOUND",
                message=f"Watch not found in cache.db: {watch_id}",
                reason="Run one local radar watch immediately.",
                json_output=json_output,
                    started_at=started_at,
                )
        watch_payload = _watch_row_to_dict(row)
    if watch_payload["scope_type"] == "research_query":
        result = run_async(_run_research_query_watch(ctx, watch_id=watch_id, trace_id=trace_id))
    else:
        with connect_db() as connection:
            result = run_async(run_watch(connection, watch_id, trace_id=trace_id))
    with connect_db() as connection:
        updated_row = _fetch_watch_row(connection, watch_id)
        if updated_row is not None:
            watch_payload = _watch_row_to_dict(updated_row)

    run_payload = _watch_run_payload(result)
    ok = result.status == "completed"
    if json_output:
        json_output_response(
            _radar_envelope(
                ctx,
                ok=ok,
                binding=_WATCH_RUN_NOW_RPC_BINDING,
                profile_id=watch_payload["profile_id"],
                notebook_id=_watch_notebook_id(watch_payload),
                result={"watch": watch_payload, "run": run_payload},
                reason="Run one local radar watch immediately.",
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                cache_updates=_watch_run_cache_updates(result, watch_payload=watch_payload),
            )
        )
        if not ok:
            raise SystemExit(1)
        return

    if not ok:
        raise click.ClickException(
            f"Watch {watch_id} failed: {result.error_text or 'unknown local radar error'}"
        )

    console.print(f"[green]Watch run completed:[/green] {watch_payload['id']}")
    if result.baseline_created:
        console.print("[dim]Baseline captured for future change detection.[/dim]")
    elif result.changed:
        console.print(
            f"[dim]Change detected: {result.change_kind} ({result.severity or 'unknown'}).[/dim]"
        )
    else:
        console.print("[dim]No change detected on this run.[/dim]")
    if result.next_run_at is not None:
        console.print(f"[dim]Next scheduled run: {result.next_run_at}[/dim]")


@radar.command("status")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to local default)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("radar.status")
@click.pass_context
def radar_status(ctx: click.Context, profile_id: str | None, json_output: bool) -> None:
    """Summarize watch coverage and outstanding radar events."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile = _resolve_profile_id(connection, profile_id)
        payload = _fetch_status_payload(connection, resolved_profile)

    if json_output:
        json_output_response(
            _radar_envelope(
                ctx,
                binding=_RADAR_STATUS_RPC_BINDING,
                profile_id=resolved_profile,
                notebook_id=payload["latest_event"]["notebook_id"] if payload["latest_event"] else None,
                result=payload,
                reason="Summarize local radar watch coverage and outstanding events.",
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
        )
        return

    console.print(f"[bold]Radar Status[/bold] ({resolved_profile})")

    watches = Table(title="Watches")
    watches.add_column("Metric", style="dim")
    watches.add_column("Value", style="cyan")
    watches.add_row("Total", str(payload["watches"]["total"]))
    watches.add_row("Active", str(payload["watches"]["active"]))
    watches.add_row("Paused", str(payload["watches"]["paused"]))
    watches.add_row("Due now", str(payload["watches"]["due_now"]))
    console.print(watches)

    events = Table(title="Events")
    events.add_column("Metric", style="dim")
    events.add_column("Value", style="cyan")
    events.add_row("Total", str(payload["events"]["total"]))
    events.add_row("Open", str(payload["events"]["open"]))
    for severity in _EVENT_SEVERITIES:
        count = payload["events"]["by_severity"].get(severity)
        if count:
            events.add_row(f"Severity {severity}", str(count))
    for state in _EVENT_STATES:
        count = payload["events"]["by_state"].get(state)
        if count:
            events.add_row(f"State {state}", str(count))
    console.print(events)

    latest_event = payload["latest_event"]
    if latest_event is None:
        console.print("\n[yellow]No radar events recorded yet.[/yellow]")
        return

    latest = Table(title="Latest Event")
    latest.add_column("Field", style="dim")
    latest.add_column("Value", style="cyan")
    latest.add_row("Event", latest_event["id"])
    latest.add_row("State", latest_event["state"])
    latest.add_row("Severity", latest_event["severity"])
    latest.add_row("Change", latest_event["change_kind"])
    latest.add_row("Source", latest_event["source_title"] or latest_event["source_id"] or "-")
    latest.add_row("Created", latest_event["created_at"])
    console.print(latest)


@radar.command("list")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to local default)")
@click.option("--state", "state_filter", type=click.Choice(_EVENT_STATES), default=None)
@click.option("--severity", "severity_filter", type=click.Choice(_EVENT_SEVERITIES), default=None)
@click.option("--all", "include_all", is_flag=True, help="Include ignored/applied events.")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("radar.list")
@click.pass_context
def radar_list(
    ctx: click.Context,
    profile_id: str | None,
    state_filter: str | None,
    severity_filter: str | None,
    include_all: bool,
    json_output: bool,
) -> None:
    """List radar events for review."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile = _resolve_profile_id(connection, profile_id)
        rows = _list_event_rows(
            connection,
            profile_id=resolved_profile,
            state_filter=state_filter,
            severity_filter=severity_filter,
            include_all=include_all,
        )
    events = [_event_row_to_dict(row) for row in rows]
    effective_state_filter = state_filter or ("all" if include_all else "open")

    if json_output:
        json_output_response(
            _radar_envelope(
                ctx,
                binding=_RADAR_LIST_RPC_BINDING,
                profile_id=resolved_profile,
                notebook_id=events[0]["notebook_id"] if events else None,
                result={
                    "profile_id": resolved_profile,
                    "state_filter": effective_state_filter,
                    "severity_filter": severity_filter,
                    "count": len(events),
                    "events": events,
                },
                reason="List locally stored radar events for review.",
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
        )
        return

    if not events:
        console.print(f"[yellow]No radar events found for profile {resolved_profile}.[/yellow]")
        return

    table = Table(title=f"Radar Events ({resolved_profile})")
    table.add_column("ID", style="cyan")
    table.add_column("State", style="yellow")
    table.add_column("Severity", style="magenta")
    table.add_column("Change", style="green")
    table.add_column("Source", style="white")
    table.add_column("Created", style="dim")
    for event in events:
        table.add_row(
            event["id"],
            event["state"],
            event["severity"],
            event["change_kind"],
            event["source_title"] or event["source_id"] or "-",
            event["created_at"],
        )
    console.print(table)


@radar.command("brief")
@click.argument("event_id")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("radar.brief")
@click.pass_context
def radar_brief(ctx: click.Context, event_id: str, json_output: bool) -> None:
    """Show the stored delta briefing for one radar event."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        event_payload, watch_payload, briefing_payload = _fetch_event_detail(connection, event_id)

    payload = {
        "event": event_payload,
        "watch": watch_payload,
        "briefing": briefing_payload,
    }
    if json_output:
        json_output_response(
            _radar_envelope(
                ctx,
                binding=_RADAR_BRIEF_RPC_BINDING,
                profile_id=watch_payload["profile_id"],
                notebook_id=event_payload["notebook_id"],
                result=payload,
                reason="Inspect one locally stored radar delta briefing.",
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
        )
        return

    event_details = Table(title=f"Radar Brief {event_id}")
    event_details.add_column("Field", style="dim")
    event_details.add_column("Value", style="cyan")
    event_details.add_row("State", event_payload["state"])
    event_details.add_row("Severity", event_payload["severity"])
    event_details.add_row("Change", event_payload["change_kind"])
    event_details.add_row("Watch", watch_payload["id"])
    event_details.add_row("Watch kind", watch_payload["watch_kind"])
    event_details.add_row("Source", event_payload["source_title"] or event_payload["source_id"] or "-")
    event_details.add_row("Created", event_payload["created_at"])
    console.print(event_details)

    console.print("\n[bold]Summary[/bold]")
    console.print(briefing_payload["summary_md"])

    impact = briefing_payload.get("impact")
    if impact is not None:
        console.print("\n[bold]Impact[/bold]")
        console.print_json(data=json.dumps(impact, indent=2, sort_keys=True))

    recommended_actions = briefing_payload.get("recommended_actions")
    if recommended_actions is not None:
        console.print("\n[bold]Recommended Actions[/bold]")
        console.print_json(data=json.dumps(recommended_actions, indent=2, sort_keys=True))


@radar.command("ignore")
@click.argument("event_id")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("radar.ignore")
@click.pass_context
def radar_ignore(ctx: click.Context, event_id: str, json_output: bool) -> None:
    """Mark a radar event ignored and reconcile source freshness."""
    started_at = time.perf_counter()
    event_payload, refreshed_source_state = _ignore_event(event_id)
    payload = {
        "event": event_payload,
        "source_freshness_state": refreshed_source_state,
    }
    if json_output:
        json_output_response(
            _radar_envelope(
                ctx,
                binding=_RADAR_IGNORE_RPC_BINDING,
                profile_id=event_payload.get("profile_id", "default"),
                notebook_id=event_payload["notebook_id"],
                result=payload,
                reason="Ignore a local radar event and reconcile cached source freshness.",
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                cache_updates=CacheUpdates(
                    tables_touched=(
                        ["change_events", "sources"]
                        if refreshed_source_state is not None and event_payload["source_id"] is not None
                        else ["change_events"]
                    )
                ),
            )
        )
        return

    console.print(f"[green]Ignored radar event:[/green] {event_id}")
    if refreshed_source_state is not None and event_payload["source_id"] is not None:
        console.print(
            f"[dim]Source {event_payload['source_id']} freshness -> {refreshed_source_state}[/dim]"
        )


__all__ = [
    "watch",
    "watch_add",
    "watch_list",
    "watch_pause",
    "watch_run_now",
    "radar",
    "radar_brief",
    "radar_ignore",
    "radar_list",
    "radar_status",
]
