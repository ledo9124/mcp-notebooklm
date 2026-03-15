"""Local cache diagnostics and maintenance commands."""

from __future__ import annotations

import time

import click
from rich.table import Table

from ..contracts import CacheUpdates, Diagnostics, Envelope, Intent, Route, Transport, manifest_risk_guard
from ..contracts.rpc_map import RPC_MAP
from ..contracts.risk import RiskTier, guard_refusal_details
from ..local.cache import load_cache_status, prune_cache
from ..local.db import connect_db
from ..profiles.manager import ProfileManager
from .helpers import console, json_error_response, json_output_response
from .session import _trace_and_run_id


_LARGE_PRUNE_ROW_THRESHOLD = 10
_CACHE_STATUS_RPC_BINDING = RPC_MAP[(Intent.QUERY.value, "cache_status")]
_CACHE_PRUNE_RPC_BINDING = RPC_MAP[(Intent.LOCAL_MUTATION.value, "cache_prune")]


@click.group()
def cache():
    """Local cache diagnostics and maintenance."""
    pass


def _active_profile_id(cache_exists: bool) -> str:
    if not cache_exists:
        return "default"

    with connect_db() as connection:
        manager = ProfileManager(connection)
        active = manager.get_active_profile()
        if active is not None:
            return active.profile_id
        profiles = manager.list_profiles()
        if len(profiles) == 1:
            return profiles[0].profile_id
    return "default"


def _cache_status_envelope(
    ctx: click.Context,
    *,
    profile_id: str,
    status,
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, run_id = _trace_and_run_id(ctx, _CACHE_STATUS_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_CACHE_STATUS_RPC_BINDING.intent),
            mode=_CACHE_STATUS_RPC_BINDING.mode,
            notebook_id=None,
            profile_id=profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="Inspect local cache sizes, row counts, and sync timestamps.",
            transport=Transport(kind=_CACHE_STATUS_RPC_BINDING.transport_kind),
        ),
        result=status.to_dict(),
        freshness=None,
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _cache_prune_envelope(
    ctx: click.Context,
    *,
    profile_id: str,
    result,
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, run_id = _trace_and_run_id(ctx, _CACHE_PRUNE_RPC_BINDING.mode)
    tables_touched = []
    if not result.dry_run:
        tables_touched = sorted(
            table_name for table_name, deleted_count in result.deleted_counts.items() if deleted_count > 0
        )
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_CACHE_PRUNE_RPC_BINDING.intent),
            mode=_CACHE_PRUNE_RPC_BINDING.mode,
            notebook_id=None,
            profile_id=profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason=(
                "Preview tombstoned local cache rows and aged run events eligible for pruning."
                if result.dry_run
                else "Prune tombstoned local cache rows, rotate aged run events, and compact the SQLite cache when needed."
            ),
            transport=Transport(kind=_CACHE_PRUNE_RPC_BINDING.transport_kind),
        ),
        result=result.to_dict(),
        freshness=None,
        cache_updates=CacheUpdates(tables_touched=tables_touched),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


@cache.command("status")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("cache.status")
@click.pass_context
def cache_status(ctx: click.Context, json_output: bool) -> None:
    """Show row counts, on-disk sizes, and sync freshness for the local cache."""
    started_at = time.perf_counter()
    status = load_cache_status()
    profile_id = _active_profile_id(status.exists)
    if json_output:
        json_output_response(
            _cache_status_envelope(
                ctx,
                profile_id=profile_id,
                status=status,
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
        )
        return

    metrics = Table(title="Cache Status")
    metrics.add_column("Metric", style="dim")
    metrics.add_column("Value", style="cyan")
    metrics.add_row("DB path", status.db_path)
    metrics.add_row("DB present", "yes" if status.exists else "no")
    metrics.add_row("DB size", _format_bytes(status.db_size_bytes))
    metrics.add_row("WAL size", _format_bytes(status.wal_size_bytes))
    metrics.add_row("Oldest sync", status.oldest_sync_timestamp or "-")
    metrics.add_row("Newest sync", status.newest_sync_timestamp or "-")
    console.print(metrics)

    counts = Table(title="Cache Table Row Counts")
    counts.add_column("Table", style="dim")
    counts.add_column("Rows", justify="right", style="cyan")
    for table_name, row_count in status.table_counts.items():
        counts.add_row(table_name, str(row_count))
    console.print(counts)

    if not status.exists:
        console.print("\n[yellow]Cache DB does not exist yet.[/yellow]")


@cache.command("prune")
@click.option(
    "--older-than-days",
    default=30,
    show_default=True,
    type=click.IntRange(min=0),
    help="Delete tombstoned cache rows older than this many days.",
)
@click.option("--dry-run", is_flag=True, help="Preview rows that would be removed.")
@click.option("--yes", "assume_yes", is_flag=True, help="Confirm large prune operations.")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("cache.prune")
@click.pass_context
def cache_prune(
    ctx: click.Context,
    older_than_days: int,
    dry_run: bool,
    assume_yes: bool,
    json_output: bool,
) -> None:
    """Delete old cache rows, rotate aged run events, and compact the SQLite DB."""
    started_at = time.perf_counter()
    preview = prune_cache(older_than_days=older_than_days, dry_run=True)
    profile_id = _active_profile_id(preview.exists)
    if dry_run:
        result = preview
    else:
        if preview.total_candidates >= _LARGE_PRUNE_ROW_THRESHOLD and not assume_yes:
            message = (
                f"Refusing to prune {preview.total_candidates} row(s) without --yes. "
                f"Run with --dry-run to preview or pass --yes to confirm large cache mutations."
            )
            if json_output:
                json_error_response(
                    "CONFIRM_REQUIRED",
                    message,
                    extra=guard_refusal_details(
                        RiskTier.T1_LOCAL_MUTATION,
                        next_step_kind="confirm",
                        next_step="--yes",
                        extra={
                            "total_candidates": preview.total_candidates,
                            "threshold": _LARGE_PRUNE_ROW_THRESHOLD,
                        },
                    ),
                    ctx=ctx,
                    binding=_CACHE_PRUNE_RPC_BINDING,
                    profile_id=profile_id,
                    source_of_truth="local_cache",
                    cache_mode="offline",
                    reason=(
                        "Prune tombstoned local cache rows, rotate aged run events, "
                        "and compact the SQLite cache when needed."
                    ),
                    diagnostics=Diagnostics(
                        retries=0,
                        auth_refreshed=False,
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    ),
                )
            raise click.ClickException(message)

        result = prune_cache(older_than_days=older_than_days, dry_run=False)

    profile_id = _active_profile_id(result.exists)
    if json_output:
        json_output_response(
            _cache_prune_envelope(
                ctx,
                profile_id=profile_id,
                result=result,
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
        )
        return

    counts = Table(title="Cache Prune")
    counts.add_column("Table", style="dim")
    counts.add_column("Candidates", justify="right", style="yellow")
    counts.add_column("Deleted", justify="right", style="green")
    for table_name in sorted(result.candidate_counts):
        counts.add_row(
            table_name,
            str(result.candidate_counts[table_name]),
            str(result.deleted_counts[table_name]),
        )

    console.print(f"[bold]Cache DB:[/bold] {result.db_path}")
    console.print(counts)

    if not result.exists:
        console.print("\n[yellow]Cache DB does not exist yet; nothing to prune.[/yellow]")
        return

    if result.dry_run:
        console.print(
            f"\n[yellow]Dry run:[/yellow] {result.total_candidates} row(s) would be removed "
            f"with `--older-than-days {result.older_than_days}`."
        )
        return

    if result.total_deleted:
        console.print(
            f"\n[green]Pruned {result.total_deleted} row(s)[/green] "
            f"and compacted the cache database."
        )
    else:
        console.print(
            "\n[green]Nothing eligible for deletion or rotation.[/green] Vacuum skipped."
        )


def _format_bytes(num_bytes: int) -> str:
    """Render a byte count using a compact binary suffix."""
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


__all__ = ["cache", "cache_prune", "cache_status"]
