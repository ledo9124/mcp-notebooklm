"""Notebook management CLI commands."""

from dataclasses import replace
from datetime import datetime, timezone
import json
import time

import click
from rich.table import Table

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
from ..local.repositories import (
    ApprovalRequestRepository,
    NotebookRepository,
    SourceRepository,
)
from ..sync import (
    invalidate_notebook_detail,
    invalidate_notebook_index,
    sync_notebook_detail,
    sync_notebook_index,
)
from ..workflows.ask import NotebookTargetCandidate, resolve_notebook_target
from .guards import require_destructive_approval, resolve_destructive_approvals
from .helpers import (
    console,
    emit_compatibility_warning,
    json_output_response,
    require_notebook,
    resolve_notebook_id,
    set_current_notebook,
    with_client,
)
from .session import _inspect_auth_state, _trace_and_run_id


_NOTEBOOK_LIST_MODE = "notebook_list"
_NOTEBOOK_SHOW_MODE = "notebook_show"
_NOTEBOOK_USE_MODE = "notebook_use"
_NOTEBOOK_CREATE_MODE = "notebook_create"
_NOTEBOOK_DELETE_RPC_BINDING = RPC_MAP[("MUTATION", "notebook_delete")]


def _trace_id(ctx: click.Context) -> str:
    trace_id = ctx.obj.get("trace_id") if ctx.obj else None
    return trace_id or "trc_unknown"


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


def _notebook_preview_payload(notebook, *, cached_source_count: int | None) -> dict[str, object]:
    payload = {
        "id": notebook.id,
        "title": notebook.title,
    }
    if cached_source_count is not None:
        payload["cached_source_count"] = cached_source_count
    return payload


def _cached_notebook_candidates(notebooks) -> list[NotebookTargetCandidate]:
    return [
        NotebookTargetCandidate(
            notebook_id=notebook.notebook_id,
            title=notebook.title,
            normalized_title=notebook.normalized_title,
        )
        for notebook in notebooks
    ]


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
    delta = datetime.now(timezone.utc) - parsed
    return max(0, int(delta.total_seconds()))


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


def _transport_for_source(source_of_truth: str) -> Transport:
    if source_of_truth == "local_cache":
        return Transport(kind="local")
    return Transport(kind="httpx")


def _list_result_payload(state) -> dict[str, object]:
    return {
        "notebooks": [
            {
                "index": i,
                "id": nb.notebook_id,
                "title": nb.title,
                "is_owner": nb.is_owner,
                "created_at": nb.created_at_remote,
            }
            for i, nb in enumerate(state.notebooks, 1)
        ],
        "count": len(state.notebooks),
    }


def _list_json_envelope(
    ctx: click.Context,
    *,
    state,
    refresh: bool,
    elapsed_ms: int,
) -> dict[str, object]:
    source_of_truth = "local_cache" if state.used_cache else "remote_http"
    trace_id, run_id = _trace_and_run_id(ctx, _NOTEBOOK_LIST_MODE)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.LOCAL_METADATA,
            mode=_NOTEBOOK_LIST_MODE,
            notebook_id=None,
            profile_id=_profile_id(ctx),
            source_of_truth=source_of_truth,
            cache_mode="refresh" if refresh else "smart",
            reason="List notebooks from the cached index when fresh, otherwise refresh from NotebookLM.",
            transport=_transport_for_source(source_of_truth),
        ),
        freshness=Freshness(
            notebook_index_age_s=_age_seconds(state.synced_at),
            used_cached_result=state.used_cache,
        ),
        result=_list_result_payload(state),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _notebook_detail_payload(detail_state, *, resolution_source: str) -> dict[str, object]:
    notebook = detail_state.notebook
    return {
        "notebook": {
            "id": notebook.notebook_id,
            "title": notebook.title,
            "is_owner": notebook.is_owner,
            "created_at": notebook.created_at_remote,
            "source_count": notebook.source_count,
            "artifact_count": notebook.artifact_count,
            "summary_preview": notebook.summary_preview,
            "remote_fingerprint": notebook.remote_fingerprint,
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
        "sources": [
            {
                "id": source.source_id,
                "title": source.title,
                "status": source.status,
                "freshness_state": source.freshness_state,
                "origin_uri": source.origin_uri,
            }
            for source in detail_state.sources
        ],
        "artifacts": [
            {
                "id": artifact.artifact_id,
                "title": artifact.title,
                "artifact_type": artifact.artifact_type,
                "status": artifact.status,
                "requested_at": artifact.requested_at,
            }
            for artifact in detail_state.artifacts
        ],
    }


def _show_source_of_truth(*, resolution_source: str, detail_used_cache: bool) -> str:
    if detail_used_cache and resolution_source in {"local_cache", "current_context"}:
        return "local_cache"
    if not detail_used_cache and resolution_source == "remote_lookup":
        return "remote_http"
    return "mixed"


def _show_route_reason(source_of_truth: str) -> str:
    if source_of_truth == "local_cache":
        return "Resolved notebook detail fully from the local cache."
    if source_of_truth == "remote_http":
        return "Resolved notebook detail from NotebookLM after a remote selector lookup."
    return "Combined cached notebook resolution with remote metadata to show notebook detail."


def _show_json_envelope(
    ctx: click.Context,
    *,
    payload: dict[str, object],
    source_of_truth: str,
    refresh: bool,
    elapsed_ms: int,
) -> dict[str, object]:
    notebook = payload["notebook"]
    freshness = payload["freshness"]
    trace_id, run_id = _trace_and_run_id(ctx, _NOTEBOOK_SHOW_MODE)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.LOCAL_METADATA,
            mode=_NOTEBOOK_SHOW_MODE,
            notebook_id=str(notebook["id"]),
            profile_id=_profile_id(ctx),
            source_of_truth=source_of_truth,
            cache_mode="refresh" if refresh else "smart",
            reason=_show_route_reason(source_of_truth),
            transport=_transport_for_source(source_of_truth),
        ),
        freshness=Freshness(
            notebook_index_age_s=_age_seconds(freshness["index_synced_at"]),
            notebook_detail_age_s=_age_seconds(freshness["detail_synced_at"]),
            used_cached_result=bool(freshness["used_cache"]),
        ),
        result=payload,
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _selected_notebook_payload(notebook, *, created_at: str | None, resolution_source: str) -> dict[str, object]:
    return {
        "notebook": {
            "id": notebook.id,
            "title": notebook.title,
            "is_owner": notebook.is_owner,
            "created_at": created_at,
        },
        "provenance": {
            "resolution_source": resolution_source,
        },
    }


def _use_json_envelope(
    ctx: click.Context,
    *,
    notebook,
    created_at: str | None,
    resolution_source: str,
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, run_id = _trace_and_run_id(ctx, _NOTEBOOK_USE_MODE)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.LOCAL_METADATA,
            mode=_NOTEBOOK_USE_MODE,
            notebook_id=notebook.id,
            profile_id=_profile_id(ctx),
            source_of_truth="remote_http",
            cache_mode="network",
            reason="Resolved the notebook selector against the live remote notebook list and updated current context.",
            transport=Transport(kind="httpx"),
        ),
        freshness=Freshness(used_cached_result=False),
        result=_selected_notebook_payload(
            notebook,
            created_at=created_at,
            resolution_source=resolution_source,
        ),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _create_json_envelope(
    ctx: click.Context,
    *,
    notebook,
    created_at: str | None,
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, run_id = _trace_and_run_id(ctx, _NOTEBOOK_CREATE_MODE)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.LOCAL_MUTATION,
            mode=_NOTEBOOK_CREATE_MODE,
            notebook_id=notebook.id,
            profile_id=_profile_id(ctx),
            source_of_truth="remote_http",
            cache_mode="network",
            reason="Create a notebook in NotebookLM and invalidate the cached notebook index.",
            transport=Transport(kind="httpx"),
        ),
        result={
            "notebook": {
                "id": notebook.id,
                "title": notebook.title,
                "created_at": created_at,
            }
        },
        freshness=Freshness(used_cached_result=False),
        cache_updates=CacheUpdates(
            tables_touched=_tables_touched("notebooks", "sync_runs"),
        ),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _delete_json_envelope(
    ctx: click.Context,
    *,
    notebook_id: str,
    payload: dict[str, object],
    dry_run: bool,
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, run_id = _trace_and_run_id(ctx, _NOTEBOOK_DELETE_RPC_BINDING.mode)
    tables_touched: list[str] = []
    if not dry_run:
        tables_touched = _tables_touched("notebooks", "sources", "sync_runs", "run_events")
        if payload.get("approval_requests_resolved"):
            tables_touched = _tables_touched(*tables_touched, "approval_requests")
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=_binding_intent(_NOTEBOOK_DELETE_RPC_BINDING, fallback=Intent.LOCAL_MUTATION),
            mode=_NOTEBOOK_DELETE_RPC_BINDING.mode,
            notebook_id=notebook_id,
            profile_id=_profile_id(ctx),
            source_of_truth="mixed",
            cache_mode="network",
            reason=(
                "Resolve the notebook selector remotely and preview the cached impact of deleting it."
                if dry_run
                else "Delete the notebook in NotebookLM and reconcile the affected local cache state."
            ),
            transport=Transport(
                kind=_NOTEBOOK_DELETE_RPC_BINDING.transport_kind,
                endpoint=_NOTEBOOK_DELETE_RPC_BINDING.endpoint,
                rpcid=_NOTEBOOK_DELETE_RPC_BINDING.rpcid,
            ),
        ),
        result=payload,
        cache_updates=CacheUpdates(tables_touched=tables_touched),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_notebook_detail(payload: dict[str, object]) -> None:
    notebook = payload["notebook"]
    freshness = payload["freshness"]
    provenance = payload["provenance"]

    table = Table(title="Notebook Detail")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("ID", str(notebook["id"]))
    table.add_row("Title", str(notebook["title"]))
    table.add_row("Owner", "Owner" if notebook["is_owner"] else "Shared")
    table.add_row("Created", str(notebook["created_at"] or "-"))
    table.add_row("Sources", str(notebook["source_count"]))
    table.add_row("Artifacts", str(notebook["artifact_count"]))
    table.add_row("Detail synced", str(freshness["detail_synced_at"] or "-"))
    table.add_row("Index synced", str(freshness["index_synced_at"] or "-"))
    table.add_row("Detail source", str(provenance["detail_source"]))
    table.add_row("Resolved via", str(provenance["resolution_source"]))
    table.add_row("Sync run", str(provenance["sync_run_id"] or "-"))
    console.print(table)

    sources = payload["sources"]
    if sources:
        sources_table = Table(title="Sources")
        sources_table.add_column("ID", style="cyan")
        sources_table.add_column("Title", style="green")
        sources_table.add_column("Status")
        sources_table.add_column("Freshness", style="dim")
        for source in sources:
            sources_table.add_row(
                str(source["id"]),
                str(source["title"] or "-"),
                str(source["status"]),
                str(source["freshness_state"] or "-"),
            )
        console.print(sources_table)

    artifacts = payload["artifacts"]
    if artifacts:
        artifacts_table = Table(title="Artifacts")
        artifacts_table.add_column("ID", style="cyan")
        artifacts_table.add_column("Title", style="green")
        artifacts_table.add_column("Type")
        artifacts_table.add_column("Status")
        for artifact in artifacts:
            artifacts_table.add_row(
                str(artifact["id"]),
                str(artifact["title"] or "-"),
                str(artifact["artifact_type"]),
                str(artifact["status"]),
            )
        console.print(artifacts_table)


def register_notebook_commands(cli):
    """Register notebook commands on the main CLI group."""

    def _invalidate_notebook_index_cache(storage_path) -> None:
        connection = connect_db()
        try:
            invalidate_notebook_index(connection, storage_path=storage_path)
        finally:
            connection.close()

    async def _list_notebooks(
        client_auth,
        *,
        json_output: bool,
        refresh: bool,
        compatibility_warning_command: str | None = None,
    ) -> None:
        started_at = time.perf_counter()
        if compatibility_warning_command is not None:
            emit_compatibility_warning(
                compatibility_warning_command,
                enabled=not json_output,
            )
        async with NotebookLMClient(client_auth) as client:
            connection = connect_db()
            try:
                state = await sync_notebook_index(
                    client,
                    connection,
                    storage_path=client_auth.storage_path,
                    force_refresh=refresh,
                )
            finally:
                connection.close()

            notebooks = state.notebooks

            if json_output:
                json_output_response(
                    _list_json_envelope(
                        click.get_current_context(),
                        state=state,
                        refresh=refresh,
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    )
                )
                return

            table = Table(title="Notebooks")
            table.add_column("ID", style="cyan")
            table.add_column("Title", style="green")
            table.add_column("Owner")
            table.add_column("Created", style="dim")

            for nb in notebooks:
                created = "-"
                if nb.created_at_remote:
                    try:
                        created = datetime.fromisoformat(nb.created_at_remote).strftime("%Y-%m-%d")
                    except ValueError:
                        created = nb.created_at_remote
                owner_status = "Owner" if nb.is_owner else "Shared"
                table.add_row(nb.notebook_id, nb.title, owner_status, created)

            console.print(table)

    @click.group("notebook")
    def notebook_group():
        """Notebook metadata commands."""

    @notebook_group.command("list")
    @click.option("--refresh", is_flag=True, help="Force a remote refresh before listing notebooks.")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @with_client
    def notebook_list_cmd(ctx, refresh, json_output, client_auth):
        """List notebooks with local-first cache behavior."""

        return _list_notebooks(
            client_auth,
            json_output=json_output,
            refresh=refresh,
        )

    @notebook_group.command("use")
    @click.argument("notebook_selector")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @with_client
    def notebook_use_cmd(ctx, notebook_selector, json_output, client_auth):
        """Set the current notebook context by ID or exact title."""

        async def _run():
            started_at = time.perf_counter()
            async with NotebookLMClient(client_auth) as client:
                notebook = await _resolve_notebook_selector(
                    client,
                    notebook_selector,
                    echo_match=not json_output,
                )

            created_str = notebook.created_at.strftime("%Y-%m-%d") if notebook.created_at else None
            created_at = notebook.created_at.isoformat() if notebook.created_at else None
            set_current_notebook(
                notebook.id,
                notebook.title,
                notebook.is_owner,
                created_str,
            )

            if json_output:
                json_output_response(
                    _use_json_envelope(
                        ctx,
                        notebook=notebook,
                        created_at=created_at,
                        resolution_source="remote_lookup",
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    )
                )
                return

            table = Table()
            table.add_column("ID", style="cyan")
            table.add_column("Title", style="green")
            table.add_column("Owner")
            table.add_column("Created", style="dim")
            table.add_row(
                notebook.id,
                notebook.title,
                "Owner" if notebook.is_owner else "Shared",
                created_str or "-",
            )
            console.print(table)

        return _run()

    @notebook_group.command("show")
    @click.argument("notebook_selector")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @click.option("--refresh", is_flag=True, help="Force a remote refresh of notebook detail.")
    @with_client
    def notebook_show_cmd(ctx, notebook_selector, json_output, refresh, client_auth):
        """Show one notebook using local-first metadata with freshness details."""

        async def _run():
            started_at = time.perf_counter()
            async with NotebookLMClient(client_auth) as client:
                with connect_db() as connection:
                    index_state = await sync_notebook_index(
                        client,
                        connection,
                        storage_path=client_auth.storage_path,
                    )
                    try:
                        resolution = resolve_notebook_target(
                            explicit_notebook_id=notebook_selector,
                            current_notebook_id=None,
                            cached_candidates=_cached_notebook_candidates(index_state.notebooks),
                        )
                    except ValueError as exc:
                        raise click.ClickException(str(exc)) from exc

                    resolution_source = resolution.source
                    resolved_id = resolution.target
                    if resolved_id is None or resolution.source == "raw_input":
                        notebook = await _resolve_notebook_selector(
                            client,
                            notebook_selector,
                            echo_match=not json_output,
                        )
                        resolved_id = notebook.id
                        resolution_source = "remote_lookup"

                    detail_state = await sync_notebook_detail(
                        client,
                        connection,
                        resolved_id,
                        storage_path=client_auth.storage_path,
                        force_refresh=refresh,
                    )
                    payload = _notebook_detail_payload(
                        detail_state,
                        resolution_source=resolution_source,
                    )
                    source_of_truth = _show_source_of_truth(
                        resolution_source=resolution_source,
                        detail_used_cache=detail_state.used_cache,
                    )

                if json_output:
                    json_output_response(
                        _show_json_envelope(
                            ctx,
                            payload=payload,
                            source_of_truth=source_of_truth,
                            refresh=refresh,
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                        )
                    )
                    return

                _render_notebook_detail(payload)

        return _run()

    cli.add_command(notebook_group)

    @cli.command("list")
    @click.option("--refresh", is_flag=True, help="Force a remote refresh before listing notebooks.")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @with_client
    def list_cmd(ctx, refresh, json_output, client_auth):
        """List all notebooks."""

        return _list_notebooks(
            client_auth,
            json_output=json_output,
            refresh=refresh,
            compatibility_warning_command="notebooklm notebook list",
        )

    @cli.command("create")
    @click.argument("title")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @with_client
    def create_cmd(ctx, title, json_output, client_auth):
        """Create a new notebook."""

        async def _run():
            started_at = time.perf_counter()
            async with NotebookLMClient(client_auth) as client:
                nb = await client.notebooks.create(title)
                _invalidate_notebook_index_cache(client_auth.storage_path)

                if json_output:
                    json_output_response(
                        _create_json_envelope(
                            ctx,
                            notebook=nb,
                            created_at=nb.created_at.isoformat() if nb.created_at else None,
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                        )
                    )
                    return

                console.print(f"[green]Created notebook:[/green] {nb.id} - {nb.title}")

        return _run()

    @cli.command("delete")
    @click.argument("notebook_selector")
    @click.option("--dry-run", is_flag=True, help="Preview the notebook that would be deleted.")
    @click.option("--yes", "assume_yes", is_flag=True, help="Confirm notebook deletion.")
    @click.option("--approval-token", default=None, help="Approval token from a prior refusal.")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @manifest_risk_guard("notebook.delete")
    @with_client
    def delete_cmd(
        ctx,
        notebook_selector,
        dry_run,
        assume_yes,
        approval_token,
        json_output,
        client_auth,
    ):
        """Delete a notebook by ID or exact title."""

        async def _run():
            started_at = time.perf_counter()
            async with NotebookLMClient(client_auth) as client:
                notebook = await _resolve_notebook_selector(
                    client,
                    notebook_selector,
                    echo_match=not json_output,
                )
                with connect_db() as connection:
                    cached_source_count = len(SourceRepository(connection).list_for_notebook(notebook.id))

                preview = _notebook_preview_payload(
                    notebook,
                    cached_source_count=cached_source_count,
                )
                command_path = f"notebooklm delete {notebook.id}"

                if dry_run:
                    payload = {"deleted": False, "dry_run": True, "notebook": preview}
                    if json_output:
                        json_output_response(
                            _delete_json_envelope(
                                ctx,
                                notebook_id=notebook.id,
                                payload=payload,
                                dry_run=True,
                                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                            )
                        )
                        return
                    console.print(f"[yellow]Dry run:[/yellow] would delete notebook {notebook.id}.")
                    if notebook.title:
                        console.print(f"[bold]Title:[/bold] {notebook.title}")
                    return

                with connect_db() as connection:
                    require_destructive_approval(
                        ApprovalRequestRepository(connection),
                        entity_label=f"Notebook {notebook.id}",
                        entity_type="notebook_delete",
                        entity_id=notebook.id,
                        action="delete",
                        reason=f"Approval required before deleting notebook {notebook.id}.",
                        command_path=command_path,
                        preview_command=f"{command_path} --dry-run",
                        approval_token=approval_token,
                        assume_yes=assume_yes,
                        json_output=json_output,
                        ctx=ctx,
                        binding=_NOTEBOOK_DELETE_RPC_BINDING,
                        profile_id=_profile_id(ctx),
                        notebook_id=notebook.id,
                        source_of_truth="mixed",
                        cache_mode="network",
                        route_reason="Delete the notebook in NotebookLM and reconcile the affected local cache state.",
                        diagnostics=Diagnostics(
                            retries=0,
                            auth_refreshed=False,
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                        ),
                    )

                await client.notebooks.delete(notebook.id)

                with connect_db() as connection:
                    deleted_at = datetime.now(timezone.utc).isoformat()
                    notebook_repository = NotebookRepository(connection)
                    source_repository = SourceRepository(connection)

                    cached_notebook = notebook_repository.get(notebook.id)
                    if cached_notebook is not None:
                        notebook_repository.upsert(
                            replace(
                                cached_notebook,
                                tombstoned_at=deleted_at,
                                index_synced_at=None,
                                detail_synced_at=None,
                                remote_fingerprint=None,
                            )
                        )

                    for cached_source in source_repository.list_for_notebook(notebook.id):
                        if cached_source.tombstoned_at is not None:
                            continue
                        source_repository.upsert(
                            replace(
                                cached_source,
                                tombstoned_at=deleted_at,
                                synced_at=deleted_at,
                            )
                        )

                    connection.execute(
                        """
                        UPDATE app_state
                        SET current_notebook_id = NULL,
                            current_conversation_id = NULL
                        WHERE singleton_key = 1
                          AND current_notebook_id = ?
                        """,
                        (notebook.id,),
                    )

                    approval_requests_resolved = resolve_destructive_approvals(
                        ApprovalRequestRepository(connection),
                        entity_type="notebook_delete",
                        entity_id=notebook.id,
                        action="delete",
                        decision_json=json.dumps(
                            {
                                "approved": True,
                                "notebook_id": notebook.id,
                            },
                            sort_keys=True,
                        ),
                    )
                    invalidate_notebook_index(
                        connection,
                        storage_path=client_auth.storage_path,
                        reason="notebook.delete",
                    )
                    invalidate_notebook_detail(
                        connection,
                        notebook.id,
                        storage_path=client_auth.storage_path,
                        reason="notebook.delete",
                    )
                    append_run_event(
                        connection,
                        _trace_id(ctx),
                        "notebook.deleted",
                        payload={
                            "notebook_id": notebook.id,
                            "title": notebook.title,
                            "cached_source_count": cached_source_count,
                            "approval_requests_resolved": approval_requests_resolved,
                        },
                    )

                payload = {
                    "deleted": True,
                    "notebook": preview,
                    "approval_requests_resolved": approval_requests_resolved,
                }
                if json_output:
                    json_output_response(
                        _delete_json_envelope(
                            ctx,
                            notebook_id=notebook.id,
                            payload=payload,
                            dry_run=False,
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                        )
                    )
                    return

                console.print(f"[green]Deleted notebook:[/green] {notebook.id} - {notebook.title}")

        return _run()

    @cli.command("summary")
    @click.option(
        "-n",
        "--notebook",
        "notebook_id",
        default=None,
        help="Notebook ID (uses current if not set). Supports partial IDs.",
    )
    @click.option("--topics", is_flag=True, help="Include suggested topics")
    @with_client
    def summary_cmd(ctx, notebook_id, topics, client_auth):
        """Get notebook summary with AI-generated insights.

        NOTEBOOK_ID supports partial matching (e.g., 'abc' matches 'abc123...').

        \b
          Examples:
            notebooklm summary              # Summary only
            notebooklm summary --topics     # With suggested topics
        """
        emit_compatibility_warning("notebooklm overview")
        notebook_id = require_notebook(notebook_id)

        async def _run():
            async with NotebookLMClient(client_auth) as client:
                resolved_id = await resolve_notebook_id(client, notebook_id)
                description = await client.notebooks.get_description(resolved_id)
                if description and description.summary:
                    console.print("[bold cyan]Summary:[/bold cyan]")
                    console.print(description.summary)

                    if topics and description.suggested_topics:
                        console.print("\n[bold cyan]Suggested Topics:[/bold cyan]")
                        for i, topic in enumerate(description.suggested_topics, 1):
                            console.print(f"  {i}. {topic.question}")
                else:
                    console.print("[yellow]No summary available[/yellow]")

        return _run()
