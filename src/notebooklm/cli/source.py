"""Source management CLI commands.

Commands:
    list         List sources in a notebook
    guide        Fetch the remote guide for one source
    add          Add a source (url, text, file, youtube)
    add-research Search web/drive and add sources from results
    delete       Delete one source with preview and safety guards
    wait         Wait for a source to finish processing
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

import click
from rich.table import Table

from .._url_utils import is_youtube_url
from ..client import NotebookLMClient
from ..contracts import (
    CacheUpdates,
    Diagnostics,
    Envelope,
    Freshness,
    Intent,
    Route,
    Transport,
    manifest_risk_guard,
)
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..local.events import append_run_event
from ..local.repositories import ApprovalRequestRepository, SourceRepository
from ..sync import invalidate_notebook_detail, sync_notebook_detail, sync_notebook_index
from ..types import SourceType
from .guards import require_destructive_approval, resolve_destructive_approvals
from .helpers import (
    console,
    display_research_sources,
    get_current_notebook,
    get_source_type_display,
    json_output_response,
    require_notebook,
    resolve_notebook_id,
    resolve_source_id,
    with_client,
)
from .research import start_research_run, wait_for_research_run
from .session import _inspect_auth_state, _trace_and_run_id


@click.group()
def source():
    """Source management commands.

    \b
    Commands:
      list         List sources in a notebook
      guide        Fetch the remote guide for a source
      add          Add a source (url, text, file, youtube)
      add-research Search web/drive and add sources from results
      delete       Delete one source with preview + approval guards
      wait         Wait for a source to finish processing

    \b
    Partial ID Support:
      `source wait` accepts partial SOURCE_ID values. Instead of typing the full
      UUID, you can use a prefix (e.g., 'abc' matches 'abc123def456...').
    """
    pass


def _invalidate_notebook_detail_cache(notebook_id: str, storage_path, *, reason: str) -> None:
    connection = connect_db()
    try:
        invalidate_notebook_detail(
            connection,
            notebook_id,
            storage_path=storage_path,
            reason=reason,
        )
    finally:
        connection.close()


def _trace_id(ctx: click.Context) -> str:
    trace_id = ctx.obj.get("trace_id") if ctx.obj else None
    return trace_id or "trc_unknown"


def _source_preview_payload(source: Any | None, *, source_id: str, notebook_id: str) -> dict[str, Any]:
    payload = {
        "id": source_id,
        "notebook_id": notebook_id,
    }
    if source is None:
        return payload

    title = getattr(source, "title", None)
    if title:
        payload["title"] = title
    url = getattr(source, "url", None)
    if url:
        payload["url"] = url
    source_kind = getattr(source, "kind", None)
    if source_kind is not None:
        payload["type"] = str(source_kind)
    return payload


_SOURCE_STATUS_FILTERS = ("ready", "processing", "preparing", "error", "unknown")
_SOURCE_TYPE_FILTERS = tuple(sorted(source_type.value for source_type in SourceType))
_SOURCE_GUIDE_RPC_BINDING = RPC_MAP[(Intent.REMOTE_METADATA.value, "source_guide")]
_SOURCE_DELETE_RPC_BINDING = RPC_MAP[("MUTATION", "source_delete")]
_SOURCE_LIST_MODE = "source_list"
_SOURCE_ADD_MODE = "source_add"
_SOURCE_WAIT_MODE = "source_wait"


def _profile_id(ctx: click.Context, *, fallback: str = "default") -> str:
    try:
        _, profile_id = _inspect_auth_state(ctx)
    except Exception:
        return fallback
    return profile_id


def _age_seconds(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))


def _tables_touched(*names: str) -> list[str]:
    touched: list[str] = []
    for name in names:
        if name and name not in touched:
            touched.append(name)
    return touched


def _binding_intent(binding, *, fallback: Intent) -> Intent:
    try:
        return Intent(binding.intent)
    except ValueError:
        if binding.intent == "MUTATION":
            return Intent.LOCAL_MUTATION
        return fallback


def _transport_for_source_of_truth(
    source_of_truth: str,
    *,
    binding=None,
) -> Transport:
    if source_of_truth == "local_cache":
        return Transport(kind="local")
    if binding is None:
        return Transport(kind="httpx")
    return Transport(
        kind=binding.transport_kind,
        endpoint=binding.endpoint,
        rpcid=binding.rpcid,
    )


def _source_list_source_of_truth(*, resolution_source: str, detail_used_cache: bool) -> str:
    if detail_used_cache and resolution_source in {"local_cache", "current_context"}:
        return "local_cache"
    if not detail_used_cache and resolution_source == "remote_lookup":
        return "remote_http"
    return "mixed"


def _source_list_reason(source_of_truth: str) -> str:
    if source_of_truth == "local_cache":
        return "List sources entirely from the locally cached notebook detail."
    if source_of_truth == "remote_http":
        return "Refresh notebook detail from NotebookLM before listing sources."
    return "Resolve the notebook locally where possible, then sync notebook detail before listing sources."


def _source_list_envelope(
    ctx: click.Context,
    *,
    payload: dict[str, Any],
    refresh: bool,
    elapsed_ms: int,
) -> dict[str, Any]:
    freshness = payload["freshness"]
    provenance = payload["provenance"]
    notebook = payload["notebook"]
    source_of_truth = _source_list_source_of_truth(
        resolution_source=str(provenance["resolution_source"]),
        detail_used_cache=bool(freshness["used_cache"]),
    )
    trace_id, run_id = _trace_and_run_id(ctx, _SOURCE_LIST_MODE)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.LOCAL_METADATA,
            mode=_SOURCE_LIST_MODE,
            notebook_id=str(notebook["id"]),
            profile_id=str(notebook["profile_id"]),
            source_of_truth=source_of_truth,
            cache_mode="refresh" if refresh else "smart",
            reason=_source_list_reason(source_of_truth),
            transport=_transport_for_source_of_truth(source_of_truth),
        ),
        freshness=Freshness(
            notebook_index_age_s=_age_seconds(freshness["index_synced_at"]),
            notebook_detail_age_s=_age_seconds(freshness["detail_synced_at"]),
            used_cached_result=bool(freshness["used_cache"]),
        ),
        result=payload,
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _source_guide_source_of_truth(payload: dict[str, Any]) -> str:
    freshness = payload["freshness"]
    provenance = payload["provenance"]
    if freshness["source_metadata_synced_at"] is None and provenance["resolution_source"] == "remote_lookup":
        return "remote_http"
    return "mixed"


def _source_guide_envelope(
    ctx: click.Context,
    *,
    notebook_id: str,
    profile_id: str,
    payload: dict[str, Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    source_of_truth = _source_guide_source_of_truth(payload)
    trace_id, run_id = _trace_and_run_id(ctx, _SOURCE_GUIDE_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=_binding_intent(_SOURCE_GUIDE_RPC_BINDING, fallback=Intent.REMOTE_METADATA),
            mode=_SOURCE_GUIDE_RPC_BINDING.mode,
            notebook_id=notebook_id,
            profile_id=profile_id,
            source_of_truth=source_of_truth,
            cache_mode="network",
            reason=(
                "Fetch the source guide from NotebookLM and update cached source preview metadata when available."
                if source_of_truth == "mixed"
                else "Resolve the source remotely and fetch its guide from NotebookLM."
            ),
            transport=_transport_for_source_of_truth(
                source_of_truth,
                binding=_SOURCE_GUIDE_RPC_BINDING,
            ),
        ),
        freshness=Freshness(
            notebook_detail_age_s=_age_seconds(payload["freshness"]["source_metadata_synced_at"]),
            used_cached_result=False,
        ),
        result=payload,
        cache_updates=CacheUpdates(
            tables_touched=_tables_touched("sources")
            if payload["provenance"]["cache_updated"]
            else []
        ),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _source_add_envelope(
    ctx: click.Context,
    *,
    notebook_id: str,
    payload: dict[str, Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, _SOURCE_ADD_MODE)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.LOCAL_MUTATION,
            mode=_SOURCE_ADD_MODE,
            notebook_id=notebook_id,
            profile_id=_profile_id(ctx),
            source_of_truth="remote_http",
            cache_mode="network",
            reason="Add a source in NotebookLM and invalidate cached notebook detail.",
            transport=Transport(kind="httpx"),
        ),
        result=payload,
        cache_updates=CacheUpdates(tables_touched=_tables_touched("notebooks", "sync_runs")),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _source_delete_envelope(
    ctx: click.Context,
    *,
    notebook_id: str,
    payload: dict[str, Any],
    dry_run: bool,
    elapsed_ms: int,
) -> dict[str, Any]:
    source_of_truth = "remote_http" if dry_run else "mixed"
    trace_id, run_id = _trace_and_run_id(ctx, _SOURCE_DELETE_RPC_BINDING.mode)
    tables_touched: list[str] = []
    if not dry_run:
        tables_touched = _tables_touched("sources", "notebooks", "sync_runs", "run_events")
        if payload.get("approval_requests_resolved"):
            tables_touched = _tables_touched(*tables_touched, "approval_requests")
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=_binding_intent(_SOURCE_DELETE_RPC_BINDING, fallback=Intent.LOCAL_MUTATION),
            mode=_SOURCE_DELETE_RPC_BINDING.mode,
            notebook_id=notebook_id,
            profile_id=_profile_id(ctx),
            source_of_truth=source_of_truth,
            cache_mode="network",
            reason=(
                "Preview the source targeted for deletion without mutating NotebookLM."
                if dry_run
                else "Delete the source in NotebookLM and reconcile the affected local cache state."
            ),
            transport=_transport_for_source_of_truth(
                source_of_truth,
                binding=_SOURCE_DELETE_RPC_BINDING,
            ),
        ),
        result=payload,
        cache_updates=CacheUpdates(tables_touched=tables_touched),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _source_wait_envelope(
    ctx: click.Context,
    *,
    notebook_id: str,
    payload: dict[str, Any],
    elapsed_ms: int,
    ok: bool,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, _SOURCE_WAIT_MODE)
    return Envelope(
        ok=ok,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.REMOTE_METADATA,
            mode=_SOURCE_WAIT_MODE,
            notebook_id=notebook_id,
            profile_id=_profile_id(ctx),
            source_of_truth="remote_http",
            cache_mode="network",
            reason="Poll NotebookLM until the source processing status reaches a terminal state.",
            transport=Transport(kind="httpx"),
        ),
        result=payload,
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _resolve_cached_notebook_selector(notebooks, selector: str) -> tuple[str | None, str]:
    normalized = selector.strip().casefold()
    if not normalized:
        return None, "raw_input"

    exact_id_matches = [notebook for notebook in notebooks if notebook.notebook_id == selector]
    if len(exact_id_matches) == 1:
        return exact_id_matches[0].notebook_id, "local_cache"

    exact_title_matches = [
        notebook
        for notebook in notebooks
        if (notebook.normalized_title or "").casefold() == normalized
    ]
    if len(exact_title_matches) == 1:
        return exact_title_matches[0].notebook_id, "local_cache"
    if len(exact_title_matches) > 1:
        raise click.ClickException(
            f"Notebook title '{selector}' matches {len(exact_title_matches)} notebooks. "
            "Use an ID prefix instead."
        )

    id_prefix_matches = [
        notebook for notebook in notebooks if notebook.notebook_id.casefold().startswith(normalized)
    ]
    if len(id_prefix_matches) == 1:
        return id_prefix_matches[0].notebook_id, "local_cache"
    if len(id_prefix_matches) > 1:
        lines = [f"Ambiguous notebook selector '{selector}' matches {len(id_prefix_matches)} notebooks:"]
        for notebook in id_prefix_matches[:5]:
            lines.append(f"  {notebook.notebook_id[:12]}... {notebook.title}")
        if len(id_prefix_matches) > 5:
            lines.append(f"  ... and {len(id_prefix_matches) - 5} more")
        lines.append("")
        lines.append("Specify more characters to narrow down.")
        raise click.ClickException("\n".join(lines))

    fuzzy_matches = [
        notebook for notebook in notebooks if normalized in (notebook.normalized_title or "")
    ]
    if len(fuzzy_matches) == 1:
        return fuzzy_matches[0].notebook_id, "local_cache"
    if len(fuzzy_matches) > 1:
        lines = [f"Notebook selector '{selector}' matches {len(fuzzy_matches)} cached notebooks:"]
        for notebook in fuzzy_matches[:5]:
            lines.append(f"  {notebook.notebook_id[:12]}... {notebook.title}")
        if len(fuzzy_matches) > 5:
            lines.append(f"  ... and {len(fuzzy_matches) - 5} more")
        lines.append("")
        lines.append("Specify more characters to narrow down.")
        raise click.ClickException("\n".join(lines))

    return None, "raw_input"


def _filtered_sources(sources, *, status_filter: str | None, source_type_filter: str | None):
    filtered = list(sources)
    if status_filter is not None:
        filtered = [source for source in filtered if source.status == status_filter]
    if source_type_filter is not None:
        filtered = [source for source in filtered if source.source_type == source_type_filter]
    return filtered


def _source_row_payload(source) -> dict[str, Any]:
    return {
        "id": source.source_id,
        "title": source.title,
        "type": source.source_type,
        "url": source.origin_uri,
        "status": source.status,
        "freshness_state": source.freshness_state,
        "added_at": source.added_at_remote,
        "updated_at": source.updated_at_remote,
    }


def _source_list_payload(
    detail_state,
    *,
    resolution_source: str,
    status_filter: str | None,
    source_type_filter: str | None,
) -> dict[str, Any]:
    notebook = detail_state.notebook
    sources = _filtered_sources(
        detail_state.sources,
        status_filter=status_filter,
        source_type_filter=source_type_filter,
    )
    return {
        "notebook": {
            "id": notebook.notebook_id,
            "title": notebook.title,
            "profile_id": notebook.profile_id,
        },
        "filters": {
            "status": status_filter,
            "type": source_type_filter,
        },
        "freshness": {
            "used_cache": detail_state.used_cache,
            "detail_synced_at": detail_state.synced_at,
            "index_synced_at": notebook.index_synced_at,
        },
        "provenance": {
            "resolution_source": resolution_source,
            "detail_source": "local_cache" if detail_state.used_cache else "remote_sync",
            "sync_run_id": detail_state.sync_run_id,
        },
        "sources": [_source_row_payload(source) for source in sources],
        "count": len(sources),
        "total_count": len(detail_state.sources),
    }


def _render_source_list(payload: dict[str, Any]) -> None:
    notebook = payload["notebook"]
    freshness = payload["freshness"]
    provenance = payload["provenance"]
    filters = payload["filters"]

    metadata = Table(title=f"Sources in {notebook['title'] or notebook['id']}")
    metadata.add_column("Field", style="cyan")
    metadata.add_column("Value", style="green")
    metadata.add_row("Notebook ID", str(notebook["id"]))
    metadata.add_row("Profile", str(notebook["profile_id"]))
    metadata.add_row(
        "Results",
        f"{payload['count']} of {payload['total_count']}"
        if payload["count"] != payload["total_count"]
        else str(payload["count"]),
    )
    metadata.add_row("Status filter", str(filters["status"] or "-"))
    metadata.add_row("Type filter", str(filters["type"] or "-"))
    metadata.add_row("Detail synced", str(freshness["detail_synced_at"] or "-"))
    metadata.add_row("Index synced", str(freshness["index_synced_at"] or "-"))
    metadata.add_row("Detail source", str(provenance["detail_source"]))
    metadata.add_row("Resolved via", str(provenance["resolution_source"]))
    metadata.add_row("Sync run", str(provenance["sync_run_id"] or "-"))
    console.print(metadata)

    sources = payload["sources"]
    if not sources:
        console.print("[yellow]No sources matched the current filters.[/yellow]")
        return

    table = Table(title="Sources")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Type")
    table.add_column("Status", style="yellow")
    table.add_column("Freshness", style="dim")

    for source in sources:
        table.add_row(
            str(source["id"]),
            str(source["title"] or "-"),
            get_source_type_display(str(source["type"])),
            str(source["status"]),
            str(source["freshness_state"] or "-"),
        )

    console.print(table)


def _source_guide_payload(
    guide: dict[str, Any],
    *,
    source: Any | None,
    source_id: str,
    notebook_id: str,
    cached_source,
    resolution_source: str,
    guide_fetched_at: str,
    content_preview_cached: bool,
    cache_updated: bool,
) -> dict[str, Any]:
    source_payload = _source_preview_payload(source, source_id=source_id, notebook_id=notebook_id)
    if cached_source is not None:
        source_payload.setdefault("title", cached_source.title)
        source_payload.setdefault("url", cached_source.origin_uri)
        source_payload.setdefault("type", cached_source.source_type)
        source_payload["status"] = cached_source.status
        source_payload["freshness_state"] = cached_source.freshness_state
    return {
        "source": source_payload,
        "guide": {
            "summary": guide.get("summary", ""),
            "keywords": guide.get("keywords", []),
        },
        "freshness": {
            "guide_fetched_at": guide_fetched_at,
            "source_metadata_synced_at": cached_source.synced_at if cached_source is not None else None,
            "source_metadata_freshness_state": (
                cached_source.freshness_state if cached_source is not None else "unknown"
            ),
        },
        "provenance": {
            "guide_source": "remote",
            "resolution_source": resolution_source,
            "content_preview_cached": content_preview_cached,
            "cache_updated": cache_updated,
        },
    }


def _render_source_guide(payload: dict[str, Any]) -> None:
    source = payload["source"]
    guide = payload["guide"]
    freshness = payload["freshness"]
    provenance = payload["provenance"]

    metadata = Table(title=f"Source Guide: {source.get('title') or source['id']}")
    metadata.add_column("Field", style="cyan")
    metadata.add_column("Value", style="green")
    metadata.add_row("Source ID", str(source["id"]))
    metadata.add_row("Notebook ID", str(source["notebook_id"]))
    metadata.add_row("Type", get_source_type_display(str(source.get("type") or "unknown")))
    metadata.add_row("Status", str(source.get("status") or "-"))
    metadata.add_row("URL", str(source.get("url") or "-"))
    metadata.add_row("Guide source", str(provenance["guide_source"]))
    metadata.add_row(
        "Source freshness",
        str(freshness["source_metadata_freshness_state"] or "unknown"),
    )
    metadata.add_row("Source synced", str(freshness["source_metadata_synced_at"] or "-"))
    metadata.add_row("Guide fetched", str(freshness["guide_fetched_at"]))
    metadata.add_row("Resolved via", str(provenance["resolution_source"]))
    metadata.add_row(
        "Cached preview",
        "yes" if provenance["content_preview_cached"] else "no",
    )
    metadata.add_row("Cache updated", "yes" if provenance["cache_updated"] else "no")
    console.print(metadata)

    summary = str(guide["summary"]).strip()
    if summary:
        console.print("\n[bold]Summary[/bold]")
        console.print(summary)
    else:
        console.print("\n[yellow]No guide summary returned.[/yellow]")

    keywords = [str(keyword).strip() for keyword in guide["keywords"] if str(keyword).strip()]
    console.print("\n[bold]Keywords[/bold]")
    console.print(", ".join(keywords) if keywords else "-")


@source.command("list")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--status",
    "status_filter",
    type=click.Choice(_SOURCE_STATUS_FILTERS),
    default=None,
    help="Filter sources by processing status.",
)
@click.option(
    "--type",
    "source_type_filter",
    type=click.Choice(_SOURCE_TYPE_FILTERS),
    default=None,
    help="Filter sources by source type.",
)
@click.option("--refresh", is_flag=True, help="Force a remote refresh before listing sources.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def source_list(ctx, notebook_id, status_filter, source_type_filter, refresh, json_output, client_auth):
    """List sources from local notebook metadata with optional filters."""
    started_at = time.perf_counter()

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            explicit_notebook_id = notebook_id
            current_notebook_id = get_current_notebook()
            selector = explicit_notebook_id or current_notebook_id
            nb_id = require_notebook(selector)

            with connect_db() as connection:
                resolution_source = "current_context" if explicit_notebook_id is None else "remote_lookup"
                nb_id_resolved = current_notebook_id if explicit_notebook_id is None else None

                if explicit_notebook_id is not None:
                    index_state = await sync_notebook_index(
                        client,
                        connection,
                        storage_path=client_auth.storage_path,
                        force_refresh=refresh,
                    )
                    nb_id_resolved, resolution_source = _resolve_cached_notebook_selector(
                        index_state.notebooks,
                        nb_id,
                    )

                if nb_id_resolved is None:
                    nb_id_resolved = await resolve_notebook_id(client, nb_id)
                    resolution_source = "remote_lookup"

                detail_state = await sync_notebook_detail(
                    client,
                    connection,
                    nb_id_resolved,
                    storage_path=client_auth.storage_path,
                    force_refresh=refresh,
                )
                payload = _source_list_payload(
                    detail_state,
                    resolution_source=resolution_source,
                    status_filter=status_filter,
                    source_type_filter=source_type_filter,
                )

            if json_output:
                json_output_response(
                    _source_list_envelope(
                        ctx,
                        payload=payload,
                        refresh=refresh,
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    )
                )
                return

            _render_source_list(payload)

    return _run()


@source.command("guide")
@click.argument("source_id")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def source_guide(ctx, source_id, notebook_id, json_output, client_auth):
    """Fetch the remote guide summary and keywords for one source."""
    started_at = time.perf_counter()

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            explicit_notebook_id = notebook_id
            current_notebook_id = get_current_notebook()
            selector = explicit_notebook_id or current_notebook_id
            nb_id = require_notebook(selector)

            with connect_db() as connection:
                resolution_source = "current_context" if explicit_notebook_id is None else "remote_lookup"
                nb_id_resolved = current_notebook_id if explicit_notebook_id is None else None

                if explicit_notebook_id is not None:
                    index_state = await sync_notebook_index(
                        client,
                        connection,
                        storage_path=client_auth.storage_path,
                    )
                    nb_id_resolved, resolution_source = _resolve_cached_notebook_selector(
                        index_state.notebooks,
                        nb_id,
                    )

                if nb_id_resolved is None:
                    nb_id_resolved = await resolve_notebook_id(client, nb_id)
                    resolution_source = "remote_lookup"

                resolved_id = await resolve_source_id(client, nb_id_resolved, source_id)
                guide = await client.sources.get_guide(nb_id_resolved, resolved_id)
                resolved_source = next(
                    (
                        candidate
                        for candidate in await client.sources.list(nb_id_resolved)
                        if candidate.id == resolved_id
                    ),
                    None,
                )

                fetched_at = datetime.now(timezone.utc).isoformat()
                source_repository = SourceRepository(connection)
                cached_source = source_repository.get(resolved_id)
                content_preview_cached = False
                cache_updated = False
                new_preview = str(guide.get("summary") or "").strip() or None

                if cached_source is not None:
                    content_preview_cached = new_preview is not None
                    if cached_source.content_preview != new_preview:
                        cached_source = replace(cached_source, content_preview=new_preview)
                        source_repository.upsert(cached_source)
                        cache_updated = True

                payload = _source_guide_payload(
                    guide,
                    source=resolved_source,
                    source_id=resolved_id,
                    notebook_id=nb_id_resolved,
                    cached_source=cached_source,
                    resolution_source=resolution_source,
                    guide_fetched_at=fetched_at,
                    content_preview_cached=content_preview_cached,
                    cache_updated=cache_updated,
                )

            if json_output:
                json_output_response(
                    _source_guide_envelope(
                        ctx,
                        notebook_id=nb_id_resolved,
                        profile_id=(
                            cached_source.profile_id if cached_source is not None else _profile_id(ctx)
                        ),
                        payload=payload,
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    )
                )
                return

            _render_source_guide(payload)

    return _run()


@source.command("add")
@click.argument("content")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--type",
    "source_type",
    type=click.Choice(["url", "text", "file", "youtube"]),
    default=None,
    help="Source type (auto-detected if not specified)",
)
@click.option("--title", help="Title for text sources")
@click.option("--mime-type", help="MIME type for file sources")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def source_add(ctx, content, notebook_id, source_type, title, mime_type, json_output, client_auth):
    """Add a source to a notebook.

    \b
    Source type is auto-detected:
      - URLs (http/https) -> url or youtube
      - Existing files (.txt, .md) -> text
      - Other content -> text (inline)
      - Use --type to override

    \b
    Examples:
      source add https://example.com              # URL
      source add ./doc.md                         # Local file upload
      source add https://youtube.com/...          # YouTube video
      source add "My notes here"                  # Inline text
      source add "My notes" --title "Research"   # Text with custom title
    """
    nb_id = require_notebook(notebook_id)
    started_at = time.perf_counter()

    # Auto-detect source type if not specified
    detected_type = source_type
    file_content = None
    file_title = title

    if detected_type is None:
        if content.startswith(("http://", "https://")):
            detected_type = "youtube" if is_youtube_url(content) else "url"
        elif Path(content).exists():
            file_path = Path(content).resolve()  # Resolve symlinks
            # Security: Ensure it's a regular file (not a symlink to sensitive file)
            if not file_path.is_file():
                raise click.ClickException(f"Not a regular file: {content}")
            # All files use add_file() for proper type detection
            detected_type = "file"
        else:
            detected_type = "text"
            file_title = title or "Pasted Text"

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            if detected_type == "url" or detected_type == "youtube":
                src = await client.sources.add_url(nb_id_resolved, content)
            elif detected_type == "text":
                text_content = file_content if file_content is not None else content
                text_title = file_title or "Untitled"
                src = await client.sources.add_text(nb_id_resolved, text_title, text_content)
            elif detected_type == "file":
                src = await client.sources.add_file(nb_id_resolved, content, mime_type)
            _invalidate_notebook_detail_cache(
                nb_id_resolved,
                client_auth.storage_path,
                reason="source.add",
            )

            if json_output:
                data = {
                    "source": {
                        "id": src.id,
                        "title": src.title,
                        "type": str(src.kind),
                        "url": src.url,
                    }
                }
                json_output_response(
                    _source_add_envelope(
                        ctx,
                        notebook_id=nb_id_resolved,
                        payload=data,
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    )
                )
                return

            console.print(f"[green]Added source:[/green] {src.id}")

    if not json_output:
        with console.status(f"Adding {detected_type} source..."):
            return _run()
    return _run()


@source.command("add-research")
@click.argument("query")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--from",
    "search_source",
    type=click.Choice(["web", "drive"]),
    default="web",
    help="Search source (default: web)",
)
@click.option(
    "--mode",
    type=click.Choice(["fast", "deep"]),
    default="fast",
    help="Search mode (default: fast)",
)
@click.option("--import-all", is_flag=True, help="Import all found sources")
@click.option(
    "--no-wait",
    is_flag=True,
    help="Start research and return immediately (use 'research status/wait' to monitor)",
)
@with_client
def source_add_research(
    ctx, query, notebook_id, search_source, mode, import_all, no_wait, client_auth
):
    """Search web or drive and add sources from results.

    \b
    Examples:
      source add-research "machine learning"              # Search web
      source add-research "project docs" --from drive     # Search Google Drive
      source add-research "AI papers" --mode deep         # Deep search
      source add-research "tutorials" --import-all        # Auto-import all results
      source add-research "topic" --mode deep --no-wait   # Non-blocking deep search
    """
    nb_id = require_notebook(notebook_id)

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            console.print(f"[yellow]Starting {mode} research on {search_source}...[/yellow]")
            result = await start_research_run(
                ctx,
                client=client,
                notebook_id=nb_id_resolved,
                query=query,
                search_source=search_source,
                mode=mode,
            )

            research_id = result["research_id"]
            console.print(f"[dim]Research ID: {research_id}[/dim]")

            # Non-blocking mode: return immediately
            if no_wait:
                console.print(
                    "[green]Research started.[/green] "
                    f"Use 'research wait {research_id}' to monitor."
                )
                return

            completed = await wait_for_research_run(
                ctx,
                client=client,
                notebook_id=nb_id_resolved,
                timeout=300,
                interval=5,
                import_all=import_all,
                research_id=research_id,
                storage_path=client_auth.storage_path,
            )
            console.print()
            display_research_sources(completed.get("sources", []))
            if import_all and completed.get("imported"):
                console.print(f"[green]Imported {completed['imported']} sources[/green]")

    return _run()


@source.command("delete")
@click.argument("source_id")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option("--dry-run", is_flag=True, help="Preview the source that would be deleted.")
@click.option("--yes", "assume_yes", is_flag=True, help="Confirm source deletion.")
@click.option("--approval-token", default=None, help="Approval token from a prior refusal.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@manifest_risk_guard("source.delete")
@with_client
def source_delete(
    ctx,
    source_id,
    notebook_id,
    dry_run,
    assume_yes,
    approval_token,
    json_output,
    client_auth,
):
    """Delete one source from a notebook."""
    nb_id = require_notebook(notebook_id)
    started_at = time.perf_counter()

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            sources = await client.sources.list(nb_id_resolved)
            resolved_id = await resolve_source_id(client, nb_id_resolved, source_id)
            source = next((candidate for candidate in sources if candidate.id == resolved_id), None)
            preview = _source_preview_payload(
                source,
                source_id=resolved_id,
                notebook_id=nb_id_resolved,
            )
            command_path = f"notebooklm source delete {resolved_id} --notebook {nb_id_resolved}"

            if dry_run:
                payload = {"deleted": False, "dry_run": True, "source": preview}
                if json_output:
                    json_output_response(
                        _source_delete_envelope(
                            ctx,
                            notebook_id=nb_id_resolved,
                            payload=payload,
                            dry_run=True,
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                        )
                    )
                    return
                console.print(
                    f"[yellow]Dry run:[/yellow] would delete source {resolved_id} from {nb_id_resolved}."
                )
                if preview.get("title"):
                    console.print(f"[bold]Title:[/bold] {preview['title']}")
                return

            with connect_db() as connection:
                require_destructive_approval(
                    ApprovalRequestRepository(connection),
                    entity_label=f"Source {resolved_id}",
                    entity_type="source_delete",
                    entity_id=resolved_id,
                    action="delete",
                    reason=(
                        f"Approval required before deleting source {resolved_id} "
                        f"from notebook {nb_id_resolved}."
                    ),
                    command_path=command_path,
                    preview_command=f"{command_path} --dry-run",
                    approval_token=approval_token,
                    assume_yes=assume_yes,
                    json_output=json_output,
                    ctx=ctx,
                    binding=_SOURCE_DELETE_RPC_BINDING,
                    profile_id=_profile_id(ctx),
                    notebook_id=nb_id_resolved,
                    source_of_truth="mixed",
                    cache_mode="network",
                    route_reason="Delete the source in NotebookLM and reconcile the affected local cache state.",
                    diagnostics=Diagnostics(
                        retries=0,
                        auth_refreshed=False,
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    ),
                )

            await client.sources.delete(nb_id_resolved, resolved_id)

            with connect_db() as connection:
                deleted_at = datetime.now(timezone.utc).isoformat()
                source_repository = SourceRepository(connection)
                cached_source = source_repository.get(resolved_id)
                if cached_source is not None:
                    source_repository.upsert(
                        replace(
                            cached_source,
                            tombstoned_at=deleted_at,
                            synced_at=deleted_at,
                        )
                    )

                approval_requests_resolved = resolve_destructive_approvals(
                    ApprovalRequestRepository(connection),
                    entity_type="source_delete",
                    entity_id=resolved_id,
                    action="delete",
                    decision_json=json.dumps(
                        {
                            "approved": True,
                            "source_id": resolved_id,
                            "notebook_id": nb_id_resolved,
                        },
                        sort_keys=True,
                    ),
                )
                invalidate_notebook_detail(
                    connection,
                    nb_id_resolved,
                    storage_path=client_auth.storage_path,
                    reason="source.delete",
                )
                append_run_event(
                    connection,
                    _trace_id(ctx),
                    "source.deleted",
                    payload={
                        "source_id": resolved_id,
                        "notebook_id": nb_id_resolved,
                        "title": preview.get("title"),
                        "approval_requests_resolved": approval_requests_resolved,
                    },
                )

            payload = {
                "deleted": True,
                "source": preview,
                "approval_requests_resolved": approval_requests_resolved,
            }
            if json_output:
                json_output_response(
                    _source_delete_envelope(
                        ctx,
                        notebook_id=nb_id_resolved,
                        payload=payload,
                        dry_run=False,
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    )
                )
                return

            if preview.get("title"):
                console.print(f"[green]Deleted source:[/green] {resolved_id} - {preview['title']}")
            else:
                console.print(f"[green]Deleted source:[/green] {resolved_id}")

    return _run()


@source.command("wait")
@click.argument("source_id")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--timeout",
    default=120,
    type=int,
    help="Maximum seconds to wait (default: 120)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def source_wait(ctx, source_id, notebook_id, timeout, json_output, client_auth):
    """Wait for a source to finish processing.

    After adding a source, it needs to be processed before it can be used
    for chat or artifact generation. This command polls until the source
    is ready or fails.

    SOURCE_ID can be a full UUID or a partial prefix (e.g., 'abc' matches 'abc123...').

    \b
    Exit codes:
      0 - Source is ready
      1 - Source not found or processing failed
      2 - Timeout reached

    \b
    Examples:
      source wait abc123                    # Wait for source to be ready
      source wait abc123 --timeout 300      # Wait up to 5 minutes
      source wait abc123 --json             # Output status as JSON

    \b
    Subagent pattern for long-running operations:
      # In main conversation, add source then spawn subagent to wait:
      notebooklm source add https://example.com
      # Subagent runs: notebooklm source wait <source_id>
    """
    from ..types import SourceNotFoundError, SourceProcessingError, SourceTimeoutError

    nb_id = require_notebook(notebook_id)
    started_at = time.perf_counter()

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            resolved_id = await resolve_source_id(client, nb_id_resolved, source_id)

            if not json_output:
                console.print(f"[dim]Waiting for source {resolved_id}...[/dim]")

            try:
                source = await client.sources.wait_until_ready(
                    nb_id_resolved,
                    resolved_id,
                    timeout=float(timeout),
                )

                if json_output:
                    data = {
                        "source_id": source.id,
                        "title": source.title,
                        "status": "ready",
                        "status_code": source.status,
                    }
                    json_output_response(
                        _source_wait_envelope(
                            ctx,
                            notebook_id=nb_id_resolved,
                            payload=data,
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                            ok=True,
                        )
                    )
                else:
                    console.print(f"[green]✓ Source ready:[/green] {source.id}")
                    if source.title:
                        console.print(f"[bold]Title:[/bold] {source.title}")

            except SourceNotFoundError as e:
                if json_output:
                    data = {
                        "source_id": e.source_id,
                        "status": "not_found",
                        "error": str(e),
                    }
                    json_output_response(
                        _source_wait_envelope(
                            ctx,
                            notebook_id=nb_id_resolved,
                            payload=data,
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                            ok=False,
                        )
                    )
                else:
                    console.print(f"[red]✗ Source not found:[/red] {e.source_id}")
                raise SystemExit(1) from None

            except SourceProcessingError as e:
                if json_output:
                    data = {
                        "source_id": e.source_id,
                        "status": "error",
                        "status_code": e.status,
                        "error": str(e),
                    }
                    json_output_response(
                        _source_wait_envelope(
                            ctx,
                            notebook_id=nb_id_resolved,
                            payload=data,
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                            ok=False,
                        )
                    )
                else:
                    console.print(f"[red]✗ Source processing failed:[/red] {e.source_id}")
                raise SystemExit(1) from None

            except SourceTimeoutError as e:
                if json_output:
                    data = {
                        "source_id": e.source_id,
                        "status": "timeout",
                        "last_status_code": e.last_status,
                        "timeout_seconds": int(e.timeout),
                        "error": str(e),
                    }
                    json_output_response(
                        _source_wait_envelope(
                            ctx,
                            notebook_id=nb_id_resolved,
                            payload=data,
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                            ok=False,
                        )
                    )
                else:
                    console.print(f"[yellow]⚠ Timeout waiting for source:[/yellow] {e.source_id}")
                    console.print(f"[dim]Last status: {e.last_status}[/dim]")
                raise SystemExit(2) from None

    return _run()
