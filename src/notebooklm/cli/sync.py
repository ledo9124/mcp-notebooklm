"""Explicit sync commands for local-first metadata caches."""

from __future__ import annotations

import time

import click
from rich.table import Table

from ..contracts import CacheUpdates, Diagnostics, Envelope, Intent, Route, Transport
from ..contracts.rpc_map import RPC_MAP
from ..client import NotebookLMClient
from ..local.db import connect_db
from ..sync import sync_notebook_detail, sync_notebook_index
from ..workflows.runtime import NotebookTargetCandidate, resolve_notebook_target
from .helpers import console, get_current_notebook, json_output_response, with_client
from .session import _trace_and_run_id

_SYNC_TRIGGER = "manual"
_SYNC_NOTEBOOKS_RPC_BINDING = RPC_MAP[(Intent.REMOTE_METADATA.value, "sync_notebooks")]
_SYNC_CACHE_TABLES = ["artifacts", "notebooks", "sources", "sync_runs"]


@click.group("sync")
def sync():
    """Explicit metadata sync commands."""


async def _resolve_notebook_selector(client, selector: str, *, echo_match: bool = True):
    notebooks = await client.notebooks.list()
    normalized = selector.strip().casefold()

    title_matches = [
        notebook
        for notebook in notebooks
        if (getattr(notebook, "title", None) or "").casefold() == normalized
    ]
    if len(title_matches) == 1:
        selected = title_matches[0]
        if echo_match and selected.id != selector:
            console.print(f"[dim]Matched title: {selected.id[:12]}... ({selected.title})[/dim]")
        return selected
    if len(title_matches) > 1:
        raise click.ClickException(
            f"Notebook title '{selector}' matches {len(title_matches)} notebooks. "
            "Use an ID prefix instead."
        )

    id_matches = [notebook for notebook in notebooks if notebook.id.lower().startswith(normalized)]
    if len(id_matches) == 1:
        selected = id_matches[0]
        if echo_match and selected.id != selector:
            console.print(f"[dim]Matched: {selected.id[:12]}... ({selected.title})[/dim]")
        return selected
    if not id_matches:
        raise click.ClickException(
            f"No notebook found matching '{selector}'. Run 'notebooklm list' to see notebooks."
        )

    lines = [f"Ambiguous notebook selector '{selector}' matches {len(id_matches)} notebooks:"]
    for notebook in id_matches[:5]:
        lines.append(f"  {notebook.id[:12]}... {notebook.title}")
    if len(id_matches) > 5:
        lines.append(f"  ... and {len(id_matches) - 5} more")
    lines.append("")
    lines.append("Specify more characters to narrow down.")
    raise click.ClickException("\n".join(lines))


def _cached_notebook_candidates(notebooks) -> list[NotebookTargetCandidate]:
    return [
        NotebookTargetCandidate(
            notebook_id=notebook.notebook_id,
            title=notebook.title,
            normalized_title=notebook.normalized_title,
        )
        for notebook in notebooks
    ]


def _detail_row(detail_state, *, resolution_source: str) -> dict[str, object]:
    notebook = detail_state.notebook
    detail_source = "local_cache" if detail_state.used_cache else "remote_sync"
    return {
        "id": notebook.notebook_id,
        "title": notebook.title,
        "source_count": notebook.source_count or 0,
        "artifact_count": notebook.artifact_count or 0,
        "detail_synced_at": detail_state.synced_at,
        "detail_source": detail_source,
        "resolution_source": resolution_source,
        "sync_run_id": detail_state.sync_run_id,
    }


def _sync_payload(
    *,
    scope: str,
    requested_notebook: str | None,
    current_notebook_id: str | None,
    index_state,
    notebooks: list[dict[str, object]],
    elapsed_ms: int,
) -> dict[str, object]:
    return {
        "scope": scope,
        "requested_notebook": requested_notebook,
        "current_notebook_id": current_notebook_id,
        "elapsed_ms": elapsed_ms,
        "index": {
            "count": len(index_state.notebooks),
            "used_cache": index_state.used_cache,
            "source": "local_cache" if index_state.used_cache else "remote_sync",
            "synced_at": index_state.synced_at,
            "sync_run_id": index_state.sync_run_id,
        },
        "stats": {
            "notebook_count": len(notebooks),
            "source_count": sum(int(notebook["source_count"]) for notebook in notebooks),
            "artifact_count": sum(int(notebook["artifact_count"]) for notebook in notebooks),
            "remote_sync_count": sum(
                1 for notebook in notebooks if notebook["detail_source"] == "remote_sync"
            ),
            "cache_reuse_count": sum(
                1 for notebook in notebooks if notebook["detail_source"] == "local_cache"
            ),
        },
        "notebooks": notebooks,
    }


def _sync_profile_id(index_state) -> str:
    if index_state.notebooks:
        return index_state.notebooks[0].profile_id
    return "default"


def _sync_envelope(
    ctx: click.Context,
    *,
    profile_id: str,
    notebook_id: str | None,
    result: dict[str, object],
    sync_all: bool,
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, run_id = _trace_and_run_id(ctx, _SYNC_NOTEBOOKS_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_SYNC_NOTEBOOKS_RPC_BINDING.intent),
            mode=_SYNC_NOTEBOOKS_RPC_BINDING.mode,
            notebook_id=notebook_id,
            profile_id=profile_id,
            source_of_truth="mixed",
            cache_mode="refresh",
            reason=(
                "Refresh the notebook index and sync notebook detail caches for all notebooks."
                if sync_all
                else "Refresh the notebook index and sync notebook detail cache for the selected notebook."
            ),
            transport=Transport(
                kind=_SYNC_NOTEBOOKS_RPC_BINDING.transport_kind,
                endpoint=_SYNC_NOTEBOOKS_RPC_BINDING.endpoint,
                rpcid=_SYNC_NOTEBOOKS_RPC_BINDING.rpcid,
            ),
        ),
        result=result,
        freshness=None,
        cache_updates=CacheUpdates(tables_touched=_SYNC_CACHE_TABLES),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_sync_payload(payload: dict[str, object]) -> None:
    metadata = Table(title="Notebook Sync")
    metadata.add_column("Field", style="cyan")
    metadata.add_column("Value", style="green")
    metadata.add_row("Scope", str(payload["scope"]))
    metadata.add_row("Requested", str(payload["requested_notebook"] or "-"))
    metadata.add_row("Current context", str(payload["current_notebook_id"] or "-"))
    index = payload["index"]
    metadata.add_row("Index count", str(index["count"]))
    metadata.add_row("Index source", str(index["source"]))
    metadata.add_row("Index synced", str(index["synced_at"] or "-"))
    metadata.add_row("Index sync run", str(index["sync_run_id"] or "-"))
    stats = payload["stats"]
    metadata.add_row("Notebook details synced", str(stats["notebook_count"]))
    metadata.add_row("Sources cached", str(stats["source_count"]))
    metadata.add_row("Artifacts cached", str(stats["artifact_count"]))
    console.print(metadata)

    notebooks = payload["notebooks"]
    if not notebooks:
        console.print("[yellow]No notebooks were synced.[/yellow]")
        return

    table = Table(title="Synced notebooks")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Resolved via")
    table.add_column("Sources")
    table.add_column("Artifacts")
    table.add_column("Detail source")
    table.add_column("Synced", style="dim")

    for notebook in notebooks:
        table.add_row(
            str(notebook["id"]),
            str(notebook["title"] or "-"),
            str(notebook["resolution_source"]),
            str(notebook["source_count"]),
            str(notebook["artifact_count"]),
            str(notebook["detail_source"]),
            str(notebook["detail_synced_at"] or "-"),
        )

    console.print(table)


@sync.command("notebooks")
@click.option("--all", "sync_all", is_flag=True, help="Sync every notebook in the refreshed index.")
@click.option(
    "-n",
    "--notebook",
    "notebook_selector",
    default=None,
    help="Notebook ID or exact title (defaults to current notebook context).",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def sync_notebooks(ctx, sync_all, notebook_selector, json_output, client_auth):
    """Refresh notebook index metadata and notebook detail caches."""

    if sync_all and notebook_selector:
        raise click.ClickException("Use either --all or --notebook, not both.")

    async def _run():
        started_at = time.perf_counter()
        current_notebook_id = get_current_notebook()
        if not sync_all and notebook_selector is None and current_notebook_id is None:
            raise click.ClickException(
                "No notebook specified. Use --all, --notebook X, or 'notebooklm use <id>' first."
            )

        async with NotebookLMClient(client_auth) as client:
            with connect_db() as connection:
                index_state = await sync_notebook_index(
                    client,
                    connection,
                    storage_path=client_auth.storage_path,
                    force_refresh=True,
                    trigger=_SYNC_TRIGGER,
                )

                notebook_rows: list[dict[str, object]] = []
                if sync_all:
                    for notebook in index_state.notebooks:
                        detail_state = await sync_notebook_detail(
                            client,
                            connection,
                            notebook.notebook_id,
                            storage_path=client_auth.storage_path,
                            force_refresh=True,
                            trigger=_SYNC_TRIGGER,
                        )
                        notebook_rows.append(
                            _detail_row(detail_state, resolution_source="local_cache")
                        )
                else:
                    try:
                        resolution = resolve_notebook_target(
                            explicit_notebook_id=notebook_selector,
                            current_notebook_id=current_notebook_id,
                            cached_candidates=_cached_notebook_candidates(index_state.notebooks),
                        )
                    except ValueError as exc:
                        raise click.ClickException(str(exc)) from exc

                    resolved_id = resolution.target
                    resolution_source = resolution.source
                    if resolved_id is None or resolution.source == "raw_input":
                        selector = notebook_selector or current_notebook_id
                        if selector is None:
                            raise click.ClickException(
                                "No notebook specified. Use --all, --notebook X, or 'notebooklm use <id>' first."
                            )
                        notebook = await _resolve_notebook_selector(
                            client,
                            selector,
                            echo_match=not json_output,
                        )
                        resolved_id = notebook.id
                        resolution_source = "remote_lookup"

                    detail_state = await sync_notebook_detail(
                        client,
                        connection,
                        resolved_id,
                        storage_path=client_auth.storage_path,
                        force_refresh=True,
                        trigger=_SYNC_TRIGGER,
                    )
                    notebook_rows.append(
                        _detail_row(detail_state, resolution_source=resolution_source)
                    )

        payload = _sync_payload(
            scope="all" if sync_all else "selected",
            requested_notebook=notebook_selector,
            current_notebook_id=current_notebook_id,
            index_state=index_state,
            notebooks=notebook_rows,
            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        )
        if json_output:
            json_output_response(
                _sync_envelope(
                    ctx,
                    profile_id=_sync_profile_id(index_state),
                    notebook_id=None if sync_all else (notebook_rows[0]["id"] if notebook_rows else None),
                    result=payload,
                    sync_all=sync_all,
                    elapsed_ms=payload["elapsed_ms"],
                )
            )
            return
        _render_sync_payload(payload)

    return _run()
