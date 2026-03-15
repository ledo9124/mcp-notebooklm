"""Workspace commands backed by local SQLite metadata."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import re
import time
from typing import Any

import click
from rich.table import Table

from ..client import NotebookLMClient
from ..contracts import Diagnostics, Envelope, Intent, Route, Transport, manifest_risk_guard
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..local.repositories import (
    NotebookRepository,
    WorkspaceIndexEntryRepository,
    WorkspaceMemberRecord,
    WorkspaceMemberRepository,
    WorkspaceRecord,
    WorkspaceRepository,
)
from ..profiles.manager import ProfileManager
from ..workspaces import (
    WorkspaceExecutionFailure,
    WorkspaceExecutionResult,
    WorkspaceNotebookAnswer,
    WorkspaceProvenanceRecord,
    build_workspace_index,
    WorkspaceQueryInvocation,
    build_workspace_compare_payload,
    build_workspace_query_envelope,
    invoke_workspace_query,
)
from ..workflows.runtime import NotebookTargetCandidate, resolve_notebook_target
from .helpers import console, get_current_notebook, json_output_response, with_client
from .session import _trace_and_run_id

_WORKSPACE_LIST_RPC_BINDING = RPC_MAP[(Intent.LOCAL_METADATA.value, "workspace_list")]
_WORKSPACE_CREATE_RPC_BINDING = RPC_MAP[(Intent.LOCAL_MUTATION.value, "workspace_create")]
_WORKSPACE_ADD_RPC_BINDING = RPC_MAP[(Intent.LOCAL_MUTATION.value, "workspace_add")]
_WORKSPACE_REMOVE_RPC_BINDING = RPC_MAP[(Intent.LOCAL_MUTATION.value, "workspace_remove")]
_WORKSPACE_SHOW_RPC_BINDING = RPC_MAP[(Intent.LOCAL_METADATA.value, "workspace_show")]
_WORKSPACE_ASK_RPC_BINDING = RPC_MAP[(Intent.WORKSPACE_QUERY.value, "workspace_ask")]
_WORKSPACE_COMPARE_RPC_BINDING = RPC_MAP[(Intent.WORKSPACE_COMPARE.value, "workspace_compare")]
_WORKSPACE_INDEX_RPC_BINDING = RPC_MAP[(Intent.LOCAL_MUTATION.value, "workspace_index")]
_WORKSPACE_ASK_RUN_MODE = "ask"
_WORKSPACE_COMPARE_RUN_MODE = "compare"


@click.group()
def workspace() -> None:
    """Manage local workspaces and their search corpus."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:20]}"


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


def _slugify_workspace_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or value.casefold()


def _resolve_workspace(
    connection,
    *,
    profile_id: str,
    name_or_slug: str,
) -> WorkspaceRecord:
    repository = WorkspaceRepository(connection)
    workspace = repository.get_by_slug(profile_id, _slugify_workspace_name(name_or_slug))
    if workspace is not None:
        return workspace

    matches = [
        row
        for row in repository.list_for_profile(profile_id)
        if row.name.casefold() == name_or_slug.casefold()
    ]
    if matches:
        return sorted(matches, key=lambda row: (row.slug, row.id))[0]
    raise click.ClickException(f"Workspace not found in cache.db: {name_or_slug}")


def _entry_payload(entry) -> dict[str, object]:
    return {
        "entry_id": entry.id,
        "notebook_id": entry.notebook_id,
        "notebook_title": entry.notebook_title,
        "notebook_summary": entry.notebook_summary,
        "source_titles_text": entry.source_titles_text,
        "tags_json": entry.tags_json,
        "recent_query_text": entry.recent_query_text,
        "updated_at": entry.updated_at,
    }


def _workspace_payload(workspace_row: WorkspaceRecord) -> dict[str, object]:
    return {
        "id": workspace_row.id,
        "name": workspace_row.name,
        "slug": workspace_row.slug,
        "kind": workspace_row.kind,
        "description": workspace_row.description,
        "query_policy_json": workspace_row.query_policy_json,
        "approval_policy_json": workspace_row.approval_policy_json,
        "created_at": workspace_row.created_at,
        "updated_at": workspace_row.updated_at,
    }


def _workspace_member_payload(
    member_row: WorkspaceMemberRecord,
    *,
    notebook_title: str | None,
) -> dict[str, object]:
    return {
        "id": member_row.id,
        "notebook_id": member_row.notebook_id,
        "notebook_title": notebook_title,
        "priority": member_row.priority,
        "tags_json": member_row.tags_json,
        "enabled": member_row.enabled,
        "added_at": member_row.added_at,
    }


def _workspace_summary_payload(connection, workspace_row: WorkspaceRecord) -> dict[str, object]:
    members = WorkspaceMemberRepository(connection).list_for_workspace(workspace_row.id)
    entries = WorkspaceIndexEntryRepository(connection).list_for_workspace(workspace_row.id)
    payload = _workspace_payload(workspace_row)
    payload["member_count"] = sum(1 for member in members if member.enabled)
    payload["indexed_count"] = len(entries)
    return payload


def _workspace_members_payload(connection, workspace_row: WorkspaceRecord) -> list[dict[str, object]]:
    notebook_repository = NotebookRepository(connection)
    return [
        _workspace_member_payload(
            member_row,
            notebook_title=(
                notebook_repository.get(member_row.notebook_id).title
                if notebook_repository.get(member_row.notebook_id) is not None
                else None
            ),
        )
        for member_row in WorkspaceMemberRepository(connection).list_for_workspace(workspace_row.id)
    ]


def _workspace_local_envelope(
    ctx: click.Context,
    *,
    binding,
    profile_id: str,
    reason: str,
    result: dict[str, object],
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, run_id = _trace_and_run_id(ctx, binding.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(binding.intent),
            mode=binding.mode,
            notebook_id=None,
            profile_id=profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason=reason,
            transport=Transport(kind=binding.transport_kind),
        ),
        freshness=None,
        result=result,
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _cached_notebook_candidates(connection, profile_id: str) -> list[NotebookTargetCandidate]:
    return [
        NotebookTargetCandidate(
            notebook_id=notebook.notebook_id,
            title=notebook.title,
            normalized_title=notebook.normalized_title,
        )
        for notebook in NotebookRepository(connection).list_for_profile(profile_id)
        if notebook.tombstoned_at is None
    ]


def _resolve_workspace_notebook(
    connection,
    *,
    profile_id: str,
    notebook_selector: str | None,
):
    try:
        resolution = resolve_notebook_target(
            explicit_notebook_id=notebook_selector,
            current_notebook_id=get_current_notebook(),
            cached_candidates=_cached_notebook_candidates(connection, profile_id),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if resolution.target is None:
        raise click.ClickException(
            "No notebook specified. Provide --notebook or set context with 'notebooklm use <id>'."
        )
    if resolution.source == "raw_input":
        raise click.ClickException(f"Notebook not found in cache.db: {notebook_selector}")

    notebook_row = NotebookRepository(connection).get(resolution.target)
    if notebook_row is None or notebook_row.profile_id != profile_id or notebook_row.tombstoned_at is not None:
        if resolution.source == "current_context":
            raise click.ClickException(
                "Current notebook is not available in cache.db for the active profile."
            )
        raise click.ClickException(f"Notebook not found in cache.db: {notebook_selector or resolution.target}")
    return notebook_row, resolution.source


def _touch_workspace(connection, workspace_row: WorkspaceRecord, *, updated_at: str) -> WorkspaceRecord:
    updated_workspace = replace(workspace_row, updated_at=updated_at)
    WorkspaceRepository(connection).upsert(updated_workspace)
    return updated_workspace


def _require_static_workspace(workspace_row: WorkspaceRecord, *, action: str) -> None:
    if workspace_row.kind != "static":
        raise click.ClickException(f"Workspace {action} only supports static workspaces.")


def _record_workspace_events(
    connection,
    *,
    trace_id: str,
    workspace_row: WorkspaceRecord,
    question: str,
    execution: WorkspaceExecutionResult,
) -> None:
    try:
        append_run_event(
            connection,
            trace_id,
            "workspace.resolve.completed",
            run_id=execution.run.id,
            payload={
                "workspace_id": workspace_row.id,
                "workspace_slug": workspace_row.slug,
                "mode": execution.run.mode,
                "query_text": question,
                "plan_mode": execution.plan.mode,
                "candidate_count": execution.plan.candidate_count,
                "selected_notebook_ids": [
                    candidate.notebook_id for candidate in execution.plan.selected_candidates
                ],
                "used_fallback": execution.plan.used_fallback,
            },
        )
        append_run_event(
            connection,
            trace_id,
            "workspace.query.completed",
            run_id=execution.run.id,
            payload={
                "workspace_id": workspace_row.id,
                "workspace_slug": workspace_row.slug,
                "mode": execution.run.mode,
                "status": execution.run.status,
                "answer_count": len(execution.answers),
                "failure_count": len(execution.failures),
                "provenance_count": len(execution.synthesis.provenance),
            },
        )
    except Exception:
        return


def _workspace_plan_payload(plan) -> dict[str, object]:
    return {
        "mode": plan.mode,
        "reason": plan.reason,
        "candidate_count": plan.candidate_count,
        "used_fallback": plan.used_fallback,
        "selected_notebooks": [
            {
                "id": candidate.notebook_id,
                "title": candidate.notebook_title,
                "summary": candidate.notebook_summary,
                "member_priority": candidate.member_priority,
                "selection_reason": candidate.selection_reason,
                "fts_rank": candidate.fts_rank,
                "tags": list(candidate.tags),
            }
            for candidate in plan.selected_candidates
        ],
    }


def _workspace_answer_payload(answer: WorkspaceNotebookAnswer) -> dict[str, object]:
    return {
        "notebook_id": answer.notebook_id,
        "notebook_title": answer.notebook_title,
        "answer_text": answer.answer_text,
    }


def _workspace_failure_payload(failure: WorkspaceExecutionFailure) -> dict[str, object]:
    return {
        "notebook_id": failure.notebook_id,
        "notebook_title": failure.notebook_title,
        "error_type": failure.error_type,
        "message": failure.message,
    }


def _workspace_provenance_payload(item: WorkspaceProvenanceRecord) -> dict[str, object]:
    return {
        "notebook_id": item.notebook_id,
        "notebook_title": item.notebook_title,
        "contribution": item.contribution,
    }


def _workspace_run_payload(run) -> dict[str, object]:
    return {
        "id": run.id,
        "status": run.status,
        "mode": run.mode,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
    }


def _workspace_compare_payload(invocation: WorkspaceQueryInvocation) -> dict[str, object]:
    return invocation.comparison or build_workspace_compare_payload(invocation.execution)


def _workspace_ask_envelope(
    ctx: click.Context,
    *,
    workspace_row: WorkspaceRecord,
    question: str,
    execution: WorkspaceExecutionResult,
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, _ = _trace_and_run_id(ctx, _WORKSPACE_ASK_RPC_BINDING.mode)
    invocation = WorkspaceQueryInvocation(
        workspace=workspace_row,
        question=question,
        execution=execution,
    )
    return build_workspace_query_envelope(
        trace_id=trace_id,
        elapsed_ms=elapsed_ms,
        invocation=invocation,
        intent=Intent(_WORKSPACE_ASK_RPC_BINDING.intent),
        route_mode=_WORKSPACE_ASK_RPC_BINDING.mode,
        transport_kind=_WORKSPACE_ASK_RPC_BINDING.transport_kind,
    )


def _workspace_compare_envelope(
    ctx: click.Context,
    *,
    invocation: WorkspaceQueryInvocation,
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, _ = _trace_and_run_id(ctx, _WORKSPACE_COMPARE_RPC_BINDING.mode)
    return build_workspace_query_envelope(
        trace_id=trace_id,
        elapsed_ms=elapsed_ms,
        invocation=invocation,
        intent=Intent(_WORKSPACE_COMPARE_RPC_BINDING.intent),
        route_mode=_WORKSPACE_COMPARE_RPC_BINDING.mode,
        transport_kind=_WORKSPACE_COMPARE_RPC_BINDING.transport_kind,
    )


def _workspace_index_envelope(
    ctx: click.Context,
    *,
    workspace_row: WorkspaceRecord,
    entries: list,
    elapsed_ms: int,
) -> dict[str, object]:
    trace_id, run_id = _trace_and_run_id(ctx, _WORKSPACE_INDEX_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_WORKSPACE_INDEX_RPC_BINDING.intent),
            mode=_WORKSPACE_INDEX_RPC_BINDING.mode,
            notebook_id=None,
            profile_id=workspace_row.profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason="Rebuild workspace FTS corpus from cached local metadata.",
            transport=Transport(kind=_WORKSPACE_INDEX_RPC_BINDING.transport_kind),
        ),
        freshness=None,
        result={
            "workspace": {
                "id": workspace_row.id,
                "name": workspace_row.name,
                "slug": workspace_row.slug,
                "kind": workspace_row.kind,
            },
            "indexed_count": len(entries),
            "entries": [_entry_payload(entry) for entry in entries],
        },
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_workspace_ask(workspace_row: WorkspaceRecord, execution: WorkspaceExecutionResult) -> None:
    console.print(f"[bold cyan]Workspace:[/bold cyan] {workspace_row.name}")
    console.print(f"[dim]Plan: {execution.plan.mode}[/dim]")
    console.print(f"[dim]{execution.plan.reason}[/dim]")
    console.print("")
    console.print("[bold cyan]Answer:[/bold cyan]")
    console.print(execution.synthesis.answer)

    if execution.synthesis.provenance:
        provenance_table = Table(title="Provenance")
        provenance_table.add_column("Notebook", style="cyan")
        provenance_table.add_column("Contribution", style="green")
        for item in execution.synthesis.provenance:
            provenance_table.add_row(
                item.notebook_title or item.notebook_id,
                item.contribution,
            )
        console.print("")
        console.print(provenance_table)

    if execution.failures:
        failure_table = Table(title="Notebook Failures")
        failure_table.add_column("Notebook", style="yellow")
        failure_table.add_column("Error", style="red")
        for failure in execution.failures:
            failure_table.add_row(
                failure.notebook_title or failure.notebook_id,
                f"{failure.error_type}: {failure.message}",
            )
        console.print("")
        console.print(failure_table)

    console.print(
        f"\n[dim]Workspace run: {execution.run.id} ({execution.run.status})[/dim]"
    )


def _render_workspace_compare(invocation: WorkspaceQueryInvocation) -> None:
    workspace_row = invocation.workspace
    execution = invocation.execution
    comparison = _workspace_compare_payload(invocation)

    console.print(f"[bold cyan]Workspace:[/bold cyan] {workspace_row.name}")
    console.print(f"[dim]Plan: {execution.plan.mode}[/dim]")
    console.print(f"[dim]{execution.plan.reason}[/dim]")
    console.print("")
    console.print("[bold cyan]Compare Summary:[/bold cyan]")
    console.print(comparison["summary"])

    if comparison["overlap"]:
        console.print("")
        console.print("[bold cyan]Overlap:[/bold cyan]")
        for line in comparison["overlap"]:
            console.print(f"- {line}")

    if comparison["differences"]:
        differences_table = Table(title="Differences")
        differences_table.add_column("Notebook", style="cyan")
        differences_table.add_column("Position", style="green")
        for row in comparison["differences"]:
            differences_table.add_row(
                row["notebook_title"] or row["notebook_id"],
                row["position"],
            )
        console.print("")
        console.print(differences_table)

    contradictions = comparison.get("contradictions", [])
    if contradictions:
        contradictions_table = Table(title="Contradictions")
        contradictions_table.add_column("Topic", style="magenta")
        contradictions_table.add_column("Notebook A", style="cyan")
        contradictions_table.add_column("Notebook B", style="green")
        for row in contradictions:
            left = row["left"]
            right = row["right"]
            contradictions_table.add_row(
                row["topic"],
                f"{left['notebook_title'] or left['notebook_id']}: {left['position']}",
                f"{right['notebook_title'] or right['notebook_id']}: {right['position']}",
            )
        console.print("")
        console.print(contradictions_table)

    gap_fill_proposals = comparison.get("gap_fill_proposals")
    if isinstance(gap_fill_proposals, dict) and gap_fill_proposals.get("inbox_items"):
        if gap_fill_proposals.get("message"):
            console.print("")
            console.print(f"[dim]{gap_fill_proposals['message']}[/dim]")
        proposal_table = Table(title="Gap-Fill Proposals")
        proposal_table.add_column("State", style="yellow")
        proposal_table.add_column("Priority", justify="right", style="green")
        proposal_table.add_column("Title", style="cyan")
        for item in gap_fill_proposals["inbox_items"]:
            proposal_table.add_row(
                str(item["state"]),
                str(item["priority"]),
                str(item["title"]),
            )
        console.print("")
        console.print(proposal_table)

    if execution.failures:
        failure_table = Table(title="Notebook Failures")
        failure_table.add_column("Notebook", style="yellow")
        failure_table.add_column("Error", style="red")
        for failure in execution.failures:
            failure_table.add_row(
                failure.notebook_title or failure.notebook_id,
                f"{failure.error_type}: {failure.message}",
            )
        console.print("")
        console.print(failure_table)

    console.print(
        f"\n[dim]Workspace run: {execution.run.id} ({execution.run.status})[/dim]"
    )


def _render_workspace_index(workspace_row: WorkspaceRecord, entries: list) -> None:
    title = f"Workspace Index: {workspace_row.name}"
    if not entries:
        console.print(f"[yellow]{title} has no enabled notebooks to index.[/yellow]")
        return

    table = Table(title=title)
    table.add_column("Notebook", style="cyan")
    table.add_column("Summary", style="green")
    table.add_column("Sources", style="magenta")
    table.add_column("Tags", style="yellow")
    for entry in entries:
        table.add_row(
            entry.notebook_title or entry.notebook_id,
            entry.notebook_summary or "-",
            entry.source_titles_text or "-",
            entry.tags_json or "-",
        )
    console.print(table)
    console.print(f"[dim]Indexed {len(entries)} notebook(s) for workspace {workspace_row.slug}.[/dim]")


def _render_workspace_list(profile_id: str, workspaces_payload: list[dict[str, object]]) -> None:
    if not workspaces_payload:
        console.print(f"[yellow]No workspaces found for profile {profile_id}.[/yellow]")
        return

    table = Table(title=f"Workspaces ({profile_id})")
    table.add_column("Slug", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Kind", style="magenta")
    table.add_column("Members", justify="right", style="green")
    table.add_column("Indexed", justify="right", style="yellow")
    for workspace_payload in workspaces_payload:
        table.add_row(
            str(workspace_payload["slug"]),
            str(workspace_payload["name"]),
            str(workspace_payload["kind"]),
            str(workspace_payload["member_count"]),
            str(workspace_payload["indexed_count"]),
        )
    console.print(table)


def _render_workspace_show(
    workspace_row: WorkspaceRecord,
    *,
    workspace_payload: dict[str, object],
    member_payloads: list[dict[str, object]],
) -> None:
    console.print(f"[bold cyan]Workspace:[/bold cyan] {workspace_row.name}")
    console.print(
        f"[dim]Slug: {workspace_row.slug} | Kind: {workspace_row.kind} | "
        f"Members: {workspace_payload['member_count']} | Indexed: {workspace_payload['indexed_count']}[/dim]"
    )
    if workspace_row.description:
        console.print(workspace_row.description)

    if not member_payloads:
        console.print("\n[yellow]This workspace has no notebook members yet.[/yellow]")
        return

    table = Table(title=f"Members: {workspace_row.name}")
    table.add_column("Notebook", style="cyan")
    table.add_column("Notebook ID", style="white")
    table.add_column("Priority", justify="right", style="green")
    table.add_column("Enabled", style="yellow")
    for member_payload in member_payloads:
        table.add_row(
            str(member_payload["notebook_title"] or member_payload["notebook_id"]),
            str(member_payload["notebook_id"]),
            str(member_payload["priority"]),
            "yes" if bool(member_payload["enabled"]) else "no",
        )
    console.print("")
    console.print(table)


@workspace.command("list")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to active profile)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("workspace.list")
@click.pass_context
def workspace_list(ctx: click.Context, profile_id: str | None, json_output: bool) -> None:
    """List cached workspaces for one profile."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        workspaces = WorkspaceRepository(connection).list_for_profile(resolved_profile_id)
        workspaces_payload = [
            _workspace_summary_payload(connection, workspace_row)
            for workspace_row in workspaces
        ]

    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _workspace_local_envelope(
                ctx,
                binding=_WORKSPACE_LIST_RPC_BINDING,
                profile_id=resolved_profile_id,
                reason="List locally stored workspaces for one profile.",
                result={
                    "profile_id": resolved_profile_id,
                    "count": len(workspaces_payload),
                    "workspaces": workspaces_payload,
                },
                elapsed_ms=elapsed_ms,
            )
        )
        return

    _render_workspace_list(resolved_profile_id, workspaces_payload)


@workspace.command("create")
@click.argument("name")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to active profile)")
@click.option("--description", default=None, help="Optional workspace description")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("workspace.create")
@click.pass_context
def workspace_create(
    ctx: click.Context,
    name: str,
    profile_id: str | None,
    description: str | None,
    json_output: bool,
) -> None:
    """Create one static workspace."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        repository = WorkspaceRepository(connection)
        slug = _slugify_workspace_name(name)
        existing = repository.get_by_slug(resolved_profile_id, slug)
        if existing is not None:
            raise click.ClickException(f"Workspace already exists in cache.db: {existing.slug}")

        now = _utc_now()
        workspace_row = WorkspaceRecord(
            id=_stable_id("ws", resolved_profile_id, slug),
            profile_id=resolved_profile_id,
            name=name,
            slug=slug,
            kind="static",
            description=description,
            created_at=now,
            updated_at=now,
        )
        repository.upsert(workspace_row)
        build_workspace_index(connection, workspace=workspace_row, now=now)
        workspace_payload = _workspace_summary_payload(connection, workspace_row)

    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _workspace_local_envelope(
                ctx,
                binding=_WORKSPACE_CREATE_RPC_BINDING,
                profile_id=resolved_profile_id,
                reason="Create a static workspace in the local cache.",
                result={"workspace": workspace_payload},
                elapsed_ms=elapsed_ms,
            )
        )
        return

    console.print(f"[green]Created workspace {workspace_row.slug}.[/green]")


@workspace.command("add")
@click.argument("name")
@click.option(
    "--notebook",
    "notebook_selector",
    default=None,
    help="Notebook ID or title (defaults to current context)",
)
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to active profile)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("workspace.add")
@click.pass_context
def workspace_add(
    ctx: click.Context,
    name: str,
    notebook_selector: str | None,
    profile_id: str | None,
    json_output: bool,
) -> None:
    """Add one cached notebook to a static workspace."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        workspace_row = _resolve_workspace(
            connection,
            profile_id=resolved_profile_id,
            name_or_slug=name,
        )
        _require_static_workspace(workspace_row, action="add")
        notebook_row, resolution_source = _resolve_workspace_notebook(
            connection,
            profile_id=resolved_profile_id,
            notebook_selector=notebook_selector,
        )
        member_repository = WorkspaceMemberRepository(connection)
        existing_member = next(
            (
                member_row
                for member_row in member_repository.list_for_workspace(workspace_row.id)
                if member_row.notebook_id == notebook_row.notebook_id
            ),
            None,
        )
        now = _utc_now()
        member_row = WorkspaceMemberRecord(
            id=existing_member.id if existing_member is not None else _stable_id("wsm", workspace_row.id, notebook_row.notebook_id),
            workspace_id=workspace_row.id,
            notebook_id=notebook_row.notebook_id,
            added_at=existing_member.added_at if existing_member is not None else now,
            priority=existing_member.priority if existing_member is not None else 0,
            tags_json=existing_member.tags_json if existing_member is not None else None,
            enabled=True,
        )
        member_repository.upsert(member_row)
        workspace_row = _touch_workspace(connection, workspace_row, updated_at=now)
        build_workspace_index(connection, workspace=workspace_row, now=now)
        workspace_payload = _workspace_summary_payload(connection, workspace_row)
        member_payload = _workspace_member_payload(member_row, notebook_title=notebook_row.title)

    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _workspace_local_envelope(
                ctx,
                binding=_WORKSPACE_ADD_RPC_BINDING,
                profile_id=resolved_profile_id,
                reason="Add one cached notebook to a static workspace and refresh its local index.",
                result={
                    "workspace": workspace_payload,
                    "member": member_payload,
                    "resolved_notebook_source": resolution_source,
                },
                elapsed_ms=elapsed_ms,
            )
        )
        return

    console.print(
        f"[green]Added {notebook_row.title} to workspace {workspace_row.slug}.[/green]"
    )


@workspace.command("remove")
@click.argument("name")
@click.option(
    "--notebook",
    "notebook_selector",
    default=None,
    help="Notebook ID or title (defaults to current context)",
)
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to active profile)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("workspace.remove")
@click.pass_context
def workspace_remove(
    ctx: click.Context,
    name: str,
    notebook_selector: str | None,
    profile_id: str | None,
    json_output: bool,
) -> None:
    """Remove one cached notebook from a static workspace."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        workspace_row = _resolve_workspace(
            connection,
            profile_id=resolved_profile_id,
            name_or_slug=name,
        )
        _require_static_workspace(workspace_row, action="remove")
        notebook_row, resolution_source = _resolve_workspace_notebook(
            connection,
            profile_id=resolved_profile_id,
            notebook_selector=notebook_selector,
        )
        member_repository = WorkspaceMemberRepository(connection)
        member_row = next(
            (
                existing_member
                for existing_member in member_repository.list_for_workspace(workspace_row.id)
                if existing_member.notebook_id == notebook_row.notebook_id
            ),
            None,
        )
        if member_row is None:
            raise click.ClickException(
                f"Notebook {notebook_row.title} is not a member of workspace {workspace_row.slug}."
            )

        member_repository.delete(member_row.id)
        now = _utc_now()
        workspace_row = _touch_workspace(connection, workspace_row, updated_at=now)
        build_workspace_index(connection, workspace=workspace_row, now=now)
        workspace_payload = _workspace_summary_payload(connection, workspace_row)
        member_payload = _workspace_member_payload(member_row, notebook_title=notebook_row.title)

    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _workspace_local_envelope(
                ctx,
                binding=_WORKSPACE_REMOVE_RPC_BINDING,
                profile_id=resolved_profile_id,
                reason="Remove one cached notebook from a static workspace and refresh its local index.",
                result={
                    "workspace": workspace_payload,
                    "member": member_payload,
                    "resolved_notebook_source": resolution_source,
                },
                elapsed_ms=elapsed_ms,
            )
        )
        return

    console.print(
        f"[green]Removed {notebook_row.title} from workspace {workspace_row.slug}.[/green]"
    )


@workspace.command("show")
@click.argument("name")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to active profile)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("workspace.show")
@click.pass_context
def workspace_show(
    ctx: click.Context,
    name: str,
    profile_id: str | None,
    json_output: bool,
) -> None:
    """Show stored details for one workspace."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        workspace_row = _resolve_workspace(
            connection,
            profile_id=resolved_profile_id,
            name_or_slug=name,
        )
        workspace_payload = _workspace_summary_payload(connection, workspace_row)
        member_payloads = _workspace_members_payload(connection, workspace_row)
        entries = WorkspaceIndexEntryRepository(connection).list_for_workspace(workspace_row.id)

    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _workspace_local_envelope(
                ctx,
                binding=_WORKSPACE_SHOW_RPC_BINDING,
                profile_id=resolved_profile_id,
                reason="Show one locally stored workspace and its cached members.",
                result={
                    "workspace": workspace_payload,
                    "members": member_payloads,
                    "entries": [_entry_payload(entry) for entry in entries],
                },
                elapsed_ms=elapsed_ms,
            )
        )
        return

    _render_workspace_show(
        workspace_row,
        workspace_payload=workspace_payload,
        member_payloads=member_payloads,
    )


@workspace.command("ask")
@click.argument("name")
@click.argument("question")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to active profile)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("workspace.ask")
@with_client
def workspace_ask(
    ctx: click.Context,
    name: str,
    question: str,
    profile_id: str | None,
    json_output: bool,
    client_auth,
) -> Any:
    """Ask one workspace question across the best candidate notebooks."""
    started_at = time.perf_counter()

    async def _run() -> None:
        with connect_db() as connection:
            resolved_profile_id = _resolve_profile_id(connection, profile_id)
            workspace_row = _resolve_workspace(
                connection,
                profile_id=resolved_profile_id,
                name_or_slug=name,
            )

        trace_id, _ = _trace_and_run_id(ctx, _WORKSPACE_ASK_RPC_BINDING.mode)

        async def _ask_notebook(candidate, prompt: str):
            return await client.chat.ask(candidate.notebook_id, prompt)

        async with NotebookLMClient(client_auth) as client:
            with connect_db() as connection:
                try:
                    invocation = await invoke_workspace_query(
                        connection,
                        profile_id=resolved_profile_id,
                        name_or_slug=workspace_row.slug,
                        question=question,
                        trace_id=trace_id,
                        ask_notebook=_ask_notebook,
                        mode=_WORKSPACE_ASK_RUN_MODE,
                    )
                except (LookupError, ValueError) as exc:
                    raise click.ClickException(str(exc)) from exc

        workspace_row = invocation.workspace
        execution = invocation.execution

        elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        if json_output:
            json_output_response(
                _workspace_ask_envelope(
                    ctx,
                    workspace_row=workspace_row,
                    question=question,
                    execution=execution,
                    elapsed_ms=elapsed_ms,
                )
            )
            return

        _render_workspace_ask(workspace_row, execution)

    return _run()


@workspace.command("compare")
@click.argument("name")
@click.argument("question")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to active profile)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("workspace.compare")
@with_client
def workspace_compare(
    ctx: click.Context,
    name: str,
    question: str,
    profile_id: str | None,
    json_output: bool,
    client_auth,
) -> Any:
    """Compare notebook perspectives inside one workspace."""
    started_at = time.perf_counter()

    async def _run() -> None:
        with connect_db() as connection:
            resolved_profile_id = _resolve_profile_id(connection, profile_id)
            workspace_row = _resolve_workspace(
                connection,
                profile_id=resolved_profile_id,
                name_or_slug=name,
            )

        trace_id, _ = _trace_and_run_id(ctx, _WORKSPACE_COMPARE_RPC_BINDING.mode)

        async def _ask_notebook(candidate, prompt: str):
            return await client.chat.ask(candidate.notebook_id, prompt)

        async with NotebookLMClient(client_auth) as client:
            with connect_db() as connection:
                try:
                    invocation = await invoke_workspace_query(
                        connection,
                        profile_id=resolved_profile_id,
                        name_or_slug=workspace_row.slug,
                        question=question,
                        trace_id=trace_id,
                        ask_notebook=_ask_notebook,
                        mode=_WORKSPACE_COMPARE_RUN_MODE,
                    )
                except (LookupError, ValueError) as exc:
                    raise click.ClickException(str(exc)) from exc

        elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        if json_output:
            json_output_response(
                _workspace_compare_envelope(
                    ctx,
                    invocation=invocation,
                    elapsed_ms=elapsed_ms,
                )
            )
            return

        _render_workspace_compare(invocation)

    return _run()


@workspace.command("index")
@click.argument("name")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to active profile)")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("workspace.index")
@click.pass_context
def workspace_index(
    ctx: click.Context,
    name: str,
    profile_id: str | None,
    json_output: bool,
) -> None:
    """Rebuild the local FTS/BM25 corpus for one workspace."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        workspace_row = _resolve_workspace(
            connection,
            profile_id=resolved_profile_id,
            name_or_slug=name,
        )
        build_workspace_index(connection, workspace=workspace_row)
        entries = WorkspaceIndexEntryRepository(connection).list_for_workspace(workspace_row.id)

    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _workspace_index_envelope(
                ctx,
                workspace_row=workspace_row,
                entries=entries,
                elapsed_ms=elapsed_ms,
            )
        )
        return

    _render_workspace_index(workspace_row, entries)


__all__ = [
    "workspace",
    "workspace_add",
    "workspace_ask",
    "workspace_compare",
    "workspace_create",
    "workspace_index",
    "workspace_list",
    "workspace_remove",
    "workspace_show",
]
