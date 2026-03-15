"""Recent local run-event streaming commands."""

from __future__ import annotations

import time
from typing import Any

import click
from rich.table import Table

from ..contracts import Diagnostics, Envelope, Intent, Route, Transport, manifest_risk_guard
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..local.events import RunEvent, tail_run_events
from ..profiles.manager import ProfileManager
from .helpers import console, json_output_response
from .session import _trace_and_run_id


_EVENTS_TAIL_RPC_BINDING = RPC_MAP[(Intent.LOCAL_METADATA.value, "events_tail")]
_FOLLOW_SLEEP_SECONDS = 1.0


@click.group()
def events() -> None:
    """Inspect recent local run events."""


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


def _events_tail_envelope(
    ctx: click.Context,
    *,
    profile_id: str,
    events_batch: list[RunEvent],
    follow: bool,
    elapsed_ms: int,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, _EVENTS_TAIL_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_EVENTS_TAIL_RPC_BINDING.intent),
            mode=_EVENTS_TAIL_RPC_BINDING.mode,
            notebook_id=None,
            profile_id=profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="Tail the local run-event log.",
            transport=Transport(kind=_EVENTS_TAIL_RPC_BINDING.transport_kind),
        ),
        freshness=None,
        result={
            "follow": follow,
            "count": len(events_batch),
            "events": [_event_payload(event) for event in events_batch],
        },
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_events(events_batch: list[RunEvent]) -> None:
    if not events_batch:
        console.print("[yellow]No local run events found.[/yellow]")
        return

    table = Table(title="Recent Run Events")
    table.add_column("Timestamp", style="magenta")
    table.add_column("Trace", style="green")
    table.add_column("Kind", style="cyan")
    table.add_column("Run ID", style="yellow")
    for event in events_batch:
        table.add_row(event.ts, event.trace_id, event.kind, event.run_id or "-")
    console.print(table)


@events.command("tail")
@click.option("--limit", default=20, show_default=True, type=click.IntRange(min=1, max=100))
@click.option("--follow", is_flag=True, help="Poll for new events until interrupted")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("events.tail")
@click.pass_context
def events_tail(ctx: click.Context, limit: int, follow: bool, json_output: bool) -> None:
    """Show recent local run events, optionally following for new rows."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        profile_id = _active_profile_id(connection)
        batch = tail_run_events(connection, limit=limit)

    if json_output:
        json_output_response(
            _events_tail_envelope(
                ctx,
                profile_id=profile_id,
                events_batch=batch,
                follow=follow,
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
        )
    else:
        _render_events(batch)

    if not follow:
        return

    last_seen_ts = batch[-1].ts if batch else None
    last_seen_event_id = batch[-1].event_id if batch else None

    try:
        while True:
            time.sleep(_FOLLOW_SLEEP_SECONDS)
            with connect_db() as connection:
                next_batch = tail_run_events(
                    connection,
                    limit=limit,
                    after_ts=last_seen_ts,
                    after_event_id=last_seen_event_id,
                )
            if not next_batch:
                continue

            last_seen_ts = next_batch[-1].ts
            last_seen_event_id = next_batch[-1].event_id

            if json_output:
                json_output_response(
                    _events_tail_envelope(
                        ctx,
                        profile_id=profile_id,
                        events_batch=next_batch,
                        follow=True,
                        elapsed_ms=0,
                    )
                )
            else:
                _render_events(next_batch)
    except KeyboardInterrupt:
        return


__all__ = ["events", "events_tail"]
