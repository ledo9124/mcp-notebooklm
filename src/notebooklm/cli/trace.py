"""Local trace timeline inspection commands."""

from __future__ import annotations

import time
from typing import Any

import click
from rich.table import Table

from ..contracts import Diagnostics, Envelope, Intent, Route, Transport, manifest_risk_guard
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..local.events import RunEvent, list_run_events
from ..profiles.manager import ProfileManager
from .helpers import console, json_output_response
from .session import _trace_and_run_id


_TRACE_SHOW_RPC_BINDING = RPC_MAP[(Intent.LOCAL_METADATA.value, "trace_show")]


@click.group()
def trace() -> None:
    """Inspect persisted local traces."""


def _active_profile_id(connection) -> str:
    manager = ProfileManager(connection)
    active = manager.get_active_profile()
    if active is not None:
        return active.profile_id
    profiles = manager.list_profiles()
    if len(profiles) == 1:
        return profiles[0].profile_id
    return "default"


def _event_payload(event: RunEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "run_id": event.run_id,
        "kind": event.kind,
        "ts": event.ts,
        "payload": event.payload,
    }


def _trace_show_envelope(
    ctx: click.Context,
    *,
    profile_id: str,
    requested_trace_id: str,
    events: list[RunEvent],
    elapsed_ms: int,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, _TRACE_SHOW_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_TRACE_SHOW_RPC_BINDING.intent),
            mode=_TRACE_SHOW_RPC_BINDING.mode,
            notebook_id=None,
            profile_id=profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="Show the local run-event timeline for one trace.",
            transport=Transport(kind=_TRACE_SHOW_RPC_BINDING.transport_kind),
        ),
        freshness=None,
        result={
            "trace_id": requested_trace_id,
            "count": len(events),
            "events": [_event_payload(event) for event in events],
        },
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_trace_events(requested_trace_id: str, events: list[RunEvent]) -> None:
    table = Table(title=f"Trace {requested_trace_id}")
    table.add_column("Timestamp", style="magenta")
    table.add_column("Kind", style="cyan")
    table.add_column("Run ID", style="yellow")
    table.add_column("Payload", style="white")
    for event in events:
        table.add_row(
            event.ts,
            event.kind,
            event.run_id or "-",
            "-" if event.payload is None else str(event.payload),
        )
    console.print(table)


@trace.command("show")
@click.argument("trace_id")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("trace.show")
@click.pass_context
def trace_show(ctx: click.Context, trace_id: str, json_output: bool) -> None:
    """Show the full local event timeline for one trace."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        profile_id = _active_profile_id(connection)
        events = list_run_events(connection, trace_id)
    if not events:
        raise click.ClickException(f"No local events found for trace: {trace_id}")

    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _trace_show_envelope(
                ctx,
                profile_id=profile_id,
                requested_trace_id=trace_id,
                events=events,
                elapsed_ms=elapsed_ms,
            )
        )
        return

    _render_trace_events(trace_id, events)


__all__ = ["trace", "trace_show"]
