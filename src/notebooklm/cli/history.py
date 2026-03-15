"""Local query-history browsing commands."""

from __future__ import annotations

from datetime import datetime
import json
import sqlite3
import time
from typing import Any

import click
from rich.table import Table

from ..contracts import Diagnostics, Envelope, Intent, Route, Transport, manifest_risk_guard
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..local.repositories import (
    HistoryRunDetailRecord,
    HistorySearchHitRecord,
    QueryRunRepository,
)
from ..profiles.manager import ProfileManager
from .helpers import console, json_output_response
from .session import _trace_and_run_id


_HISTORY_SEARCH_RPC_BINDING = RPC_MAP[(Intent.LOCAL_METADATA.value, "history_search")]
_HISTORY_SHOW_RPC_BINDING = RPC_MAP[(Intent.LOCAL_METADATA.value, "history_show")]


@click.group()
def history() -> None:
    """Search and inspect local query history."""


def _resolve_profile_id(connection, explicit_profile_id: str | None) -> str:
    manager = ProfileManager(connection)
    if explicit_profile_id is not None:
        if manager.get_profile(explicit_profile_id) is None:
            raise click.ClickException(f"Profile not found in cache.db: {explicit_profile_id}")
        return explicit_profile_id

    active_profile = manager.get_active_profile()
    if active_profile is not None:
        return active_profile.profile_id

    profiles = manager.list_profiles()
    if len(profiles) == 1:
        return profiles[0].profile_id

    raise click.ClickException("No active local profile found in cache.db.")


def _decode_json_blob(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _parse_timestamp(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _duration_ms(started_at: str, ended_at: str | None) -> int | None:
    started = _parse_timestamp(started_at)
    ended = _parse_timestamp(ended_at)
    if started is None or ended is None:
        return None
    return max(0, int((ended - started).total_seconds() * 1000))


def _search_hit_payload(hit: HistorySearchHitRecord) -> dict[str, Any]:
    return {
        "run_id": hit.run_id,
        "trace_id": hit.trace_id,
        "profile_id": hit.profile_id,
        "notebook_id": hit.notebook_id,
        "notebook_title": hit.notebook_title,
        "intent": hit.intent,
        "mode": hit.mode,
        "status": hit.status,
        "prompt_text": hit.prompt_text,
        "answer_text": hit.answer_text,
        "source_titles": hit.source_titles,
        "started_at": hit.started_at,
        "ended_at": hit.ended_at,
        "rank": hit.rank,
    }


def _detail_payload(detail: HistoryRunDetailRecord) -> dict[str, Any]:
    run = detail.query_run
    result = detail.query_result
    return {
        "run": {
            "id": run.id,
            "trace_id": run.trace_id,
            "profile_id": run.profile_id,
            "notebook_id": run.notebook_id,
            "notebook_title": detail.notebook_title,
            "intent": run.intent,
            "mode": run.mode,
            "status": run.status,
            "prompt_text": run.prompt_text,
            "prompt_hash": run.prompt_hash,
            "settings_hash": run.settings_hash,
            "notebook_fingerprint": run.notebook_fingerprint,
            "cache_policy": run.cache_policy,
            "route_reason": run.route_reason,
            "source_of_truth": run.source_of_truth,
            "reused_from": run.reused_from,
        },
        "timing": {
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "duration_ms": _duration_ms(run.started_at, run.ended_at),
        },
        "result": None
        if result is None
        else {
            "result_type": result.result_type,
            "created_at": result.created_at,
            "answer_text": result.answer_text,
            "artifact_id": result.artifact_id,
            "citations": _decode_json_blob(result.citations_json),
            "result": _decode_json_blob(result.result_json),
        },
        "history_index": {
            "source_titles": detail.source_titles,
        },
    }


def _history_search_envelope(
    ctx: click.Context,
    *,
    profile_id: str,
    query: str,
    hits: list[HistorySearchHitRecord],
    elapsed_ms: int,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, _HISTORY_SEARCH_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_HISTORY_SEARCH_RPC_BINDING.intent),
            mode=_HISTORY_SEARCH_RPC_BINDING.mode,
            notebook_id=None,
            profile_id=profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="Search local query history via SQLite FTS.",
            transport=Transport(kind=_HISTORY_SEARCH_RPC_BINDING.transport_kind),
        ),
        freshness=None,
        result={
            "profile_id": profile_id,
            "query": query,
            "count": len(hits),
            "hits": [_search_hit_payload(hit) for hit in hits],
        },
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _history_show_envelope(
    ctx: click.Context,
    *,
    detail: HistoryRunDetailRecord,
    elapsed_ms: int,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, _HISTORY_SHOW_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_HISTORY_SHOW_RPC_BINDING.intent),
            mode=_HISTORY_SHOW_RPC_BINDING.mode,
            notebook_id=detail.query_run.notebook_id,
            profile_id=detail.query_run.profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="Inspect one persisted local query run.",
            transport=Transport(kind=_HISTORY_SHOW_RPC_BINDING.transport_kind),
        ),
        freshness=None,
        result=_detail_payload(detail),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_history_search(profile_id: str, query: str, hits: list[HistorySearchHitRecord]) -> None:
    if not hits:
        console.print(
            f"[yellow]No history matches found for profile {profile_id} and query {query!r}.[/yellow]"
        )
        return

    table = Table(title=f"History Search ({profile_id})")
    table.add_column("Run ID", style="cyan")
    table.add_column("Started", style="magenta")
    table.add_column("Notebook", style="green")
    table.add_column("Intent", style="yellow")
    table.add_column("Prompt", style="white")
    for hit in hits:
        table.add_row(
            hit.run_id,
            hit.started_at,
            hit.notebook_title or hit.notebook_id or "-",
            f"{hit.intent}:{hit.mode}",
            hit.prompt_text,
        )
    console.print(table)


def _render_history_detail(detail: HistoryRunDetailRecord) -> None:
    run = detail.query_run
    metadata = Table(title=f"History Run {run.id}")
    metadata.add_column("Field", style="dim")
    metadata.add_column("Value", style="cyan")
    metadata.add_row("Trace", run.trace_id)
    metadata.add_row("Profile", run.profile_id)
    metadata.add_row("Notebook", detail.notebook_title or run.notebook_id or "-")
    metadata.add_row("Intent", run.intent)
    metadata.add_row("Mode", run.mode)
    metadata.add_row("Status", run.status)
    metadata.add_row("Source of Truth", run.source_of_truth)
    metadata.add_row("Cache Policy", run.cache_policy)
    metadata.add_row("Route Reason", run.route_reason)
    metadata.add_row("Started", run.started_at)
    metadata.add_row("Ended", run.ended_at or "-")
    duration_ms = _duration_ms(run.started_at, run.ended_at)
    metadata.add_row("Duration", f"{duration_ms} ms" if duration_ms is not None else "-")
    console.print(metadata)

    console.print("\n[bold]Prompt[/bold]")
    console.print(run.prompt_text)

    if detail.query_result is not None and detail.query_result.answer_text:
        console.print("\n[bold]Answer[/bold]")
        console.print(detail.query_result.answer_text)

    if detail.source_titles:
        console.print("\n[bold]Indexed Sources[/bold]")
        console.print(detail.source_titles)

    if detail.query_result is not None:
        citations = _decode_json_blob(detail.query_result.citations_json)
        if citations:
            console.print("\n[bold]Citations[/bold]")
            console.print(citations)


@history.command("search")
@click.argument("query")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to active profile)")
@click.option("--limit", default=10, show_default=True, type=click.IntRange(min=1, max=100))
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("history.search")
@click.pass_context
def history_search(
    ctx: click.Context,
    query: str,
    profile_id: str | None,
    limit: int,
    json_output: bool,
) -> None:
    """Search local query history using the SQLite FTS index."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        try:
            hits = QueryRunRepository(connection).search_history(
                query,
                profile_id=resolved_profile_id,
                limit=limit,
            )
        except sqlite3.OperationalError as exc:
            raise click.ClickException(f"Invalid history search query {query!r}: {exc}") from exc

    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _history_search_envelope(
                ctx,
                profile_id=resolved_profile_id,
                query=query,
                hits=hits,
                elapsed_ms=elapsed_ms,
            )
        )
        return

    _render_history_search(resolved_profile_id, query, hits)


@history.command("show")
@click.argument("run_id")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("history.show")
@click.pass_context
def history_show(ctx: click.Context, run_id: str, json_output: bool) -> None:
    """Show the full persisted detail for one query run."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        detail = QueryRunRepository(connection).get_history_detail(run_id)
    if detail is None:
        raise click.ClickException(f"History run not found: {run_id}")

    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _history_show_envelope(
                ctx,
                detail=detail,
                elapsed_ms=elapsed_ms,
            )
        )
        return

    _render_history_detail(detail)


__all__ = ["history", "history_search", "history_show"]
