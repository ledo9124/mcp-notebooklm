"""Research inbox CLI commands."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import time
from typing import Any

import click
from rich.table import Table

from ..approval_policies import ResolvedApprovalPolicy, resolve_approval_policy
from ..client import NotebookLMClient
from ..contracts import CacheUpdates, Diagnostics, Envelope, Intent, Route, Transport, manifest_risk_guard
from ..contracts.rpc_map import RPC_MAP
from ..contracts.risk import RiskTier, guard_refusal_details
from ..local.db import connect_db
from ..local.events import append_run_event
from ..local.repositories import (
    ApprovalRequestRecord,
    ApprovalRequestRepository,
    InboxItemRecord,
    InboxItemRepository,
)
from ..observability.tracing import generate_trace_id
from .helpers import console, json_error_response, json_output_response, with_client
from .session import _trace_and_run_id


INBOX_STATES = ("pending", "approved", "rejected", "deferred", "applied", "expired")
_BATCH_APPLY_STATES = ("pending", "deferred")
_BATCH_PRIORITY_BANDS = ("low", "medium", "high")
_INBOX_LIST_RPC_BINDING = RPC_MAP[(Intent.INBOX_TRIAGE.value, "inbox_list")]
_INBOX_VIEW_RPC_BINDING = RPC_MAP[(Intent.INBOX_TRIAGE.value, "inbox_view")]
_INBOX_APPROVE_RPC_BINDING = RPC_MAP[(Intent.INBOX_APPLY.value, "inbox_approve")]
_INBOX_REJECT_RPC_BINDING = RPC_MAP[(Intent.INBOX_TRIAGE.value, "inbox_reject")]
_INBOX_DEFER_RPC_BINDING = RPC_MAP[(Intent.INBOX_TRIAGE.value, "inbox_defer")]
_INBOX_IMPORT_RPC_BINDING = RPC_MAP[(Intent.INBOX_APPLY.value, "inbox_import")]
_INBOX_APPLY_BATCH_RPC_BINDING = RPC_MAP[(Intent.INBOX_APPLY.value, "inbox_apply_batch")]
_INBOX_IMPORT_REASON = (
    "Apply a local inbox decision and import the selected source into NotebookLM."
)


@click.group()
def inbox() -> None:
    """Research inbox triage commands."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_rationale(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _merge_rationale(
    raw: str | None,
    *,
    updates: dict[str, Any] | None = None,
    drop_keys: tuple[str, ...] = (),
) -> str | None:
    if raw is None:
        data: dict[str, Any] = {}
    else:
        parsed = _decode_rationale(raw)
        data = parsed if isinstance(parsed, dict) else {"raw": raw}

    for key in drop_keys:
        data.pop(key, None)
    if updates:
        data.update(updates)
    if not data:
        return None
    return json.dumps(data, sort_keys=True)


def _priority_band(priority: int) -> str:
    if priority >= 4:
        return "high"
    if priority >= 2:
        return "medium"
    return "low"


def _parse_apply_batch_filter(filter_text: str) -> tuple[str, str | None]:
    raw = filter_text.strip().lower()
    if not raw:
        raise click.ClickException(
            "Inbox batch filter cannot be empty. Use '<state>' or '<state>:<priority-band>'."
        )

    state, separator, priority_band = raw.partition(":")
    if state not in _BATCH_APPLY_STATES:
        allowed = ", ".join(_BATCH_APPLY_STATES)
        raise click.ClickException(
            f"Unsupported inbox batch state '{state}'. Choose one of: {allowed}."
        )
    if separator and priority_band not in _BATCH_PRIORITY_BANDS:
        allowed = ", ".join(_BATCH_PRIORITY_BANDS)
        raise click.ClickException(
            f"Unsupported inbox batch priority band '{priority_band}'. Choose one of: {allowed}."
        )
    return state, priority_band or None


def _matches_apply_batch_filter(item: InboxItemRecord, *, priority_band: str | None) -> bool:
    if priority_band is None:
        return True
    return _priority_band(item.priority) == priority_band


def _item_to_dict(item: InboxItemRecord) -> dict[str, Any]:
    payload = {
        "id": item.id,
        "profile_id": item.profile_id,
        "notebook_id": item.notebook_id,
        "workspace_id": item.workspace_id,
        "origin": item.origin,
        "kind": item.kind,
        "state": item.state,
        "priority": item.priority,
        "novelty_score": item.novelty_score,
        "relevance_score": item.relevance_score,
        "trust_score": item.trust_score,
        "approval_required": item.approval_required,
        "title": item.title,
        "canonical_uri": item.canonical_uri,
        "snippet": item.snippet,
        "created_at": item.created_at,
        "decision_at": item.decision_at,
        "cluster_id": item.cluster_id,
    }
    rationale = _decode_rationale(item.rationale_json)
    if rationale is not None:
        payload["rationale"] = rationale
    return payload


def _approval_to_dict(approval: ApprovalRequestRecord) -> dict[str, Any]:
    payload = {
        "id": approval.id,
        "trace_id": approval.trace_id,
        "entity_type": approval.entity_type,
        "entity_id": approval.entity_id,
        "action": approval.action,
        "risk_tier": approval.risk_tier,
        "requested_by": approval.requested_by,
        "requested_at": approval.requested_at,
        "status": approval.status,
    }
    if approval.policy_name is not None:
        payload["policy_name"] = approval.policy_name
    if approval.resolved_at is not None:
        payload["resolved_at"] = approval.resolved_at
    if approval.reason is not None:
        payload["reason"] = approval.reason
    if approval.resume_token is not None:
        payload["resume_token"] = approval.resume_token
    decision = _decode_rationale(approval.decision_json)
    if decision is not None:
        payload["decision"] = decision
    return payload


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


def _get_item(repository: InboxItemRepository, item_id: str) -> InboxItemRecord:
    item = repository.get(item_id)
    if item is None:
        raise click.ClickException(f"Inbox item not found: {item_id}")
    return item


def _require_state(item: InboxItemRecord, *, allowed: tuple[str, ...], action: str) -> None:
    if item.state not in allowed:
        allowed_text = ", ".join(allowed)
        raise click.ClickException(
            f"Cannot {action} inbox item {item.id} from state '{item.state}'. "
            f"Allowed states: {allowed_text}."
        )


def _resolve_pending_approvals(
    connection,
    approval_repository: ApprovalRequestRepository,
    *,
    item_id: str,
    status: str,
    trace_id: str | None = None,
    run_id: str | None = None,
) -> int:
    resolved = 0
    for approval in approval_repository.list_for_entity("inbox_item", item_id):
        if approval.status != "pending":
            continue
        approval_repository.resolve(
            approval.id,
            status=status,
            resolved_at=_utc_now(),
            decision_json=json.dumps({"item_id": item_id, "status": status}),
        )
        if trace_id and run_id:
            _record_inbox_event(
                connection,
                trace_id=trace_id,
                run_id=run_id,
                kind="approval.resolved",
                payload={
                    "approval_id": approval.id,
                    "entity_type": approval.entity_type,
                    "entity_id": approval.entity_id,
                    "action": approval.action,
                    "item_id": item_id,
                    "status": status,
                },
            )
        resolved += 1
    return resolved


def _prefixed_trace_id(prefix: str) -> str:
    return generate_trace_id().replace("trc_", f"{prefix}_", 1)


def _record_inbox_event(
    connection,
    *,
    trace_id: str,
    run_id: str,
    kind: str,
    payload: dict[str, Any],
) -> None:
    try:
        append_run_event(connection, trace_id, kind, run_id=run_id, payload=payload)
    except Exception:
        return


def _pending_item_approval(
    approval_repository: ApprovalRequestRepository,
    *,
    item_id: str,
    action: str,
) -> ApprovalRequestRecord | None:
    for approval in approval_repository.list_for_entity("inbox_item", item_id):
        if approval.action == action and approval.status == "pending":
            return approval
    return None


def _ensure_import_approval_request(
    approval_repository: ApprovalRequestRepository,
    item: InboxItemRecord,
    *,
    policy_name: str = "default",
) -> tuple[ApprovalRequestRecord, bool]:
    pending = _pending_item_approval(approval_repository, item_id=item.id, action="import")
    if pending is not None:
        return pending, False

    approval = ApprovalRequestRecord(
        id=_prefixed_trace_id("appr"),
        trace_id=generate_trace_id(),
        entity_type="inbox_item",
        entity_id=item.id,
        action="import",
        risk_tier=RiskTier.T2_KNOWLEDGE_MUTATION.value,
        policy_name=policy_name,
        requested_by="agent",
        requested_at=_utc_now(),
        status="pending",
        reason=f"Approval required before importing inbox item {item.id}.",
        resume_token=_prefixed_trace_id("resume"),
    )
    approval_repository.upsert(approval)
    return approval, True


def _resume_import_command(item_id: str, resume_token: str | None) -> str | None:
    if not resume_token:
        return None
    return f"notebooklm inbox import {item_id} --resume-token {resume_token}"


def _import_approval_refusal(
    item: InboxItemRecord,
    approval: ApprovalRequestRecord,
    *,
    created: bool,
    resolved_policy: ResolvedApprovalPolicy,
) -> tuple[str, dict[str, Any]]:
    message = f"Inbox item {item.id} requires approval before import."
    full_command = _resume_import_command(
        item.id,
        approval.resume_token,
    ) or f"notebooklm inbox import {item.id} --approval-token {approval.id}"
    extra = {
        "approval_request": _approval_to_dict(approval),
        "approval_request_created": created,
        "approval_token": approval.id,
        "resume_token": approval.resume_token,
        "resume_command": full_command,
        "item_id": item.id,
    }
    details = guard_refusal_details(
        RiskTier.T2_KNOWLEDGE_MUTATION,
        next_step_kind="approval_token",
        next_step=f"--approval-token {approval.id}",
        extra=extra,
    )
    details.update(
        {
            "policy_name": resolved_policy.policy_name,
            "policy_source": resolved_policy.source,
            "policy_match_kind": resolved_policy.match_kind,
            "policy_mode": resolved_policy.mode,
        }
    )
    return message, details


def _resume_import_refusal(
    item: InboxItemRecord,
    approval: ApprovalRequestRecord,
    *,
    resolved_policy: ResolvedApprovalPolicy,
) -> tuple[str, str, dict[str, Any]]:
    if approval.status == "pending":
        code = "APPROVAL_PENDING"
        message = f"Inbox item {item.id} is still waiting for approval before import."
    else:
        code = "APPROVAL_REJECTED"
        message = (
            f"Inbox item {item.id} cannot resume import because approval is "
            f"{approval.status}."
        )
    details = guard_refusal_details(
        RiskTier.T2_KNOWLEDGE_MUTATION,
        next_step_kind="resume_token",
        next_step=f"--resume-token {approval.resume_token}",
        extra={
            "approval_request": _approval_to_dict(approval),
            "approval_token": approval.id,
            "resume_token": approval.resume_token,
            "resume_command": _resume_import_command(item.id, approval.resume_token),
            "item_id": item.id,
            "approval_status": approval.status,
        },
    )
    details.update(
        {
            "policy_name": resolved_policy.policy_name,
            "policy_source": resolved_policy.source,
            "policy_match_kind": resolved_policy.match_kind,
            "policy_mode": resolved_policy.mode,
        }
    )
    return code, message, details


def _invalid_resume_token_refusal(
    item: InboxItemRecord,
    resume_token: str,
) -> tuple[str, dict[str, Any]]:
    message = f"Resume token {resume_token} is not valid for inbox item {item.id}."
    details = guard_refusal_details(
        RiskTier.T2_KNOWLEDGE_MUTATION,
        next_step_kind="resume_token",
        next_step=f"--resume-token {resume_token}",
        extra={
            "item_id": item.id,
            "resume_token": resume_token,
        },
    )
    return message, details


def _emit_import_json_error(
    code: str,
    message: str,
    *,
    item: InboxItemRecord,
    details: dict[str, Any],
    ctx: click.Context | None,
    elapsed_ms: int,
) -> None:
    json_error_response(
        code,
        message,
        extra=details,
        ctx=ctx,
        binding=_INBOX_IMPORT_RPC_BINDING,
        profile_id=item.profile_id,
        notebook_id=item.notebook_id,
        source_of_truth="mixed",
        cache_mode="network",
        reason=_INBOX_IMPORT_REASON,
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    )


def _require_import_approval(
    connection,
    approval_repository: ApprovalRequestRepository,
    item: InboxItemRecord,
    *,
    approval_token: str | None,
    resume_token: str | None,
    json_output: bool,
    ctx: click.Context | None = None,
    elapsed_ms: int = 0,
    trace_id: str | None = None,
    run_id: str | None = None,
) -> None:
    resolved_policy = resolve_approval_policy(
        connection,
        entity_type="inbox_item",
        action="import",
        risk_tier=RiskTier.T2_KNOWLEDGE_MUTATION.value,
        profile_id=item.profile_id,
        notebook_id=item.notebook_id,
        workspace_id=item.workspace_id,
    )
    if resolved_policy.mode == "auto":
        return

    if resume_token is not None:
        approval = approval_repository.get_by_resume_token(resume_token)
        if (
            approval is None
            or approval.entity_type != "inbox_item"
            or approval.entity_id != item.id
            or approval.action != "import"
        ):
            invalid_message, invalid_details = _invalid_resume_token_refusal(
                item,
                resume_token,
            )
            if json_output:
                _emit_import_json_error(
                    "APPROVAL_REQUIRED",
                    invalid_message,
                    item=item,
                    details=invalid_details,
                    ctx=ctx,
                    elapsed_ms=elapsed_ms,
                )
                raise click.ClickException(invalid_message)

        if approval.status != "approved":
            code, message, details = _resume_import_refusal(
                item,
                approval,
                resolved_policy=resolved_policy,
            )
            if json_output:
                _emit_import_json_error(
                    code,
                    message,
                    item=item,
                    details=details,
                    ctx=ctx,
                    elapsed_ms=elapsed_ms,
                )
            if approval.status == "pending":
                raise click.ClickException(
                    f"{message} Run `notebooklm inbox approve {item.id}` or wait for a "
                    f"decision, then resume with `{details['resume_command']}`."
                )
            raise click.ClickException(message)
        return

    if not item.approval_required or item.state == "approved":
        return

    approval, created = _ensure_import_approval_request(
        approval_repository,
        item,
        policy_name=resolved_policy.policy_name,
    )
    if created and trace_id and run_id:
        _record_inbox_event(
            connection,
            trace_id=trace_id,
            run_id=run_id,
            kind="approval.requested",
            payload={
                "approval_id": approval.id,
                "entity_type": approval.entity_type,
                "entity_id": approval.entity_id,
                "action": approval.action,
                "item_id": item.id,
                "risk_tier": approval.risk_tier,
                "resume_token": approval.resume_token,
            },
        )
    message, details = _import_approval_refusal(
        item,
        approval,
        created=created,
        resolved_policy=resolved_policy,
    )

    if approval_token is None:
        if json_output:
            _emit_import_json_error(
                "APPROVAL_REQUIRED",
                message,
                item=item,
                details=details,
                ctx=ctx,
                elapsed_ms=elapsed_ms,
            )
        raise click.ClickException(
            f"{message} Run `notebooklm inbox approve {item.id}` or rerun with "
            f"`notebooklm inbox import {item.id} {details['next_step']}`. "
            f"After a human decision, resume with `{details['resume_command']}`."
        )

    if approval_token != approval.id:
        invalid_message = (
            f"Approval token {approval_token} is not valid for inbox item {item.id}."
        )
        if json_output:
            _emit_import_json_error(
                "APPROVAL_REQUIRED",
                invalid_message,
                item=item,
                details=details,
                ctx=ctx,
                elapsed_ms=elapsed_ms,
            )
        raise click.ClickException(
            f"{invalid_message} Use `{details['resume_command']}` instead."
        )


def _transition_item(
    item_id: str,
    *,
    state: str,
    action: str,
    allowed_states: tuple[str, ...],
    rationale_updates: dict[str, Any] | None = None,
    drop_rationale_keys: tuple[str, ...] = (),
    approval_status: str | None = None,
    trace_id: str | None = None,
    run_id: str | None = None,
) -> tuple[InboxItemRecord, int]:
    with connect_db() as connection:
        item_repository = InboxItemRepository(connection)
        approval_repository = ApprovalRequestRepository(connection)
        item = _get_item(item_repository, item_id)
        _require_state(item, allowed=allowed_states, action=action)

        updated = replace(
            item,
            state=state,
            decision_at=_utc_now(),
            rationale_json=_merge_rationale(
                item.rationale_json,
                updates=rationale_updates,
                drop_keys=drop_rationale_keys,
            ),
        )
        item_repository.upsert(updated)

        resolved = 0
        if approval_status is not None:
            resolved = _resolve_pending_approvals(
                connection,
                approval_repository,
                item_id=item_id,
                status=approval_status,
                trace_id=trace_id,
                run_id=run_id,
            )

        if state == "applied" and trace_id and run_id:
            _record_inbox_event(
                connection,
                trace_id=trace_id,
                run_id=run_id,
                kind="inbox.item.applied",
                payload={
                    "item_id": updated.id,
                    "notebook_id": updated.notebook_id,
                    "workspace_id": updated.workspace_id,
                    "kind": updated.kind,
                    "origin": updated.origin,
                    "canonical_uri": updated.canonical_uri,
                },
            )

        return updated, resolved


def _inbox_envelope(
    ctx: click.Context,
    *,
    binding,
    profile_id: str,
    notebook_id: str | None,
    source_of_truth: str,
    cache_mode: str,
    reason: str,
    result: dict[str, Any],
    elapsed_ms: int,
    cache_updates: CacheUpdates | None = None,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, binding.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(binding.intent),
            mode=binding.mode,
            notebook_id=notebook_id,
            profile_id=profile_id,
            source_of_truth=source_of_truth,
            cache_mode=cache_mode,
            reason=reason,
            transport=Transport(kind=binding.transport_kind),
        ),
        result=result,
        freshness=None,
        cache_updates=cache_updates or CacheUpdates(),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


@inbox.command("list")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to local default)")
@click.option("--state", "state_filter", type=click.Choice(INBOX_STATES), default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("inbox.list")
@click.pass_context
def inbox_list(ctx: click.Context, profile_id: str | None, state_filter: str | None, json_output: bool) -> None:
    """List inbox items for the selected profile."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        resolved_profile = _resolve_profile_id(connection, profile_id)
        items = InboxItemRepository(connection).list_for_profile(
            resolved_profile,
            state=state_filter,
        )

    if json_output:
        json_output_response(
            _inbox_envelope(
                ctx,
                binding=_INBOX_LIST_RPC_BINDING,
                profile_id=resolved_profile,
                notebook_id=None,
                source_of_truth="local_cache",
                cache_mode="offline",
                reason="List locally stored inbox items for one profile.",
                result={
                    "profile_id": resolved_profile,
                    "state": state_filter,
                    "count": len(items),
                    "items": [_item_to_dict(item) for item in items],
                },
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
        )
        return

    if not items:
        console.print(f"[yellow]No inbox items found for profile {resolved_profile}.[/yellow]")
        return

    table = Table(title=f"Inbox Items ({resolved_profile})")
    table.add_column("ID", style="cyan")
    table.add_column("State", style="yellow")
    table.add_column("Kind", style="magenta")
    table.add_column("Priority", justify="right", style="green")
    table.add_column("Title", style="white")
    for item in items:
        table.add_row(item.id, item.state, item.kind, str(item.priority), item.title)
    console.print(table)


@inbox.command("view")
@click.argument("item_id")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("inbox.view")
@click.pass_context
def inbox_view(ctx: click.Context, item_id: str, json_output: bool) -> None:
    """Show all stored details for one inbox item."""
    started_at = time.perf_counter()
    with connect_db() as connection:
        item = _get_item(InboxItemRepository(connection), item_id)
        payload = _item_to_dict(item)

    if json_output:
        json_output_response(
            _inbox_envelope(
                ctx,
                binding=_INBOX_VIEW_RPC_BINDING,
                profile_id=item.profile_id,
                notebook_id=item.notebook_id,
                source_of_truth="local_cache",
                cache_mode="offline",
                reason="Inspect one locally stored inbox item.",
                result={"item": payload},
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
        )
        return

    details = Table(title=f"Inbox Item {item.id}")
    details.add_column("Field", style="dim")
    details.add_column("Value", style="cyan")
    for field in (
        "state",
        "origin",
        "kind",
        "profile_id",
        "notebook_id",
        "workspace_id",
        "priority",
        "approval_required",
        "canonical_uri",
        "created_at",
        "decision_at",
        "cluster_id",
    ):
        value = payload.get(field)
        details.add_row(field, "-" if value is None else str(value))
    console.print(details)
    if item.snippet:
        console.print(f"\n[bold]Snippet[/bold]\n{item.snippet}")
    if "rationale" in payload:
        console.print("\n[bold]Rationale[/bold]")
        console.print_json(data=json.dumps(payload["rationale"], indent=2, sort_keys=True))


@inbox.command("approve")
@click.argument("item_id")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("inbox.approve")
@click.pass_context
def inbox_approve(ctx: click.Context, item_id: str, json_output: bool) -> None:
    """Approve one inbox item for later apply/import."""
    started_at = time.perf_counter()
    trace_id, run_id = _trace_and_run_id(ctx, "inbox_approve")
    item, resolved = _transition_item(
        item_id,
        state="approved",
        action="approve",
        allowed_states=("pending", "deferred"),
        drop_rationale_keys=("deferred_until",),
        approval_status="approved",
        trace_id=trace_id,
        run_id=run_id,
    )

    if json_output:
        json_output_response(
            _inbox_envelope(
                ctx,
                binding=_INBOX_APPROVE_RPC_BINDING,
                profile_id=item.profile_id,
                notebook_id=item.notebook_id,
                source_of_truth="local_cache",
                cache_mode="offline",
                reason="Approve a local inbox item for later import/apply.",
                result={
                    "item": _item_to_dict(item),
                    "approval_requests_resolved": resolved,
                },
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                cache_updates=CacheUpdates(
                    tables_touched=(["approval_requests"] if resolved else []) + ["inbox_items"]
                ),
            )
        )
        return

    console.print(f"[green]Approved inbox item:[/green] {item.id}")


@inbox.command("reject")
@click.argument("item_id")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("inbox.reject")
@click.pass_context
def inbox_reject(ctx: click.Context, item_id: str, json_output: bool) -> None:
    """Reject one inbox item."""
    started_at = time.perf_counter()
    trace_id, run_id = _trace_and_run_id(ctx, "inbox_reject")
    item, resolved = _transition_item(
        item_id,
        state="rejected",
        action="reject",
        allowed_states=("pending", "approved", "deferred"),
        drop_rationale_keys=("deferred_until",),
        approval_status="rejected",
        trace_id=trace_id,
        run_id=run_id,
    )

    if json_output:
        json_output_response(
            _inbox_envelope(
                ctx,
                binding=_INBOX_REJECT_RPC_BINDING,
                profile_id=item.profile_id,
                notebook_id=item.notebook_id,
                source_of_truth="local_cache",
                cache_mode="offline",
                reason="Reject a local inbox item.",
                result={
                    "item": _item_to_dict(item),
                    "approval_requests_resolved": resolved,
                },
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                cache_updates=CacheUpdates(
                    tables_touched=(["approval_requests"] if resolved else []) + ["inbox_items"]
                ),
            )
        )
        return

    console.print(f"[green]Rejected inbox item:[/green] {item.id}")


@inbox.command("defer")
@click.argument("item_id")
@click.option(
    "--until",
    "until",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Date when the item should become actionable again.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("inbox.defer")
@click.pass_context
def inbox_defer(ctx: click.Context, item_id: str, until: datetime, json_output: bool) -> None:
    """Defer one inbox item until a later date."""
    started_at = time.perf_counter()
    trace_id, run_id = _trace_and_run_id(ctx, "inbox_defer")
    item, _ = _transition_item(
        item_id,
        state="deferred",
        action="defer",
        allowed_states=("pending", "approved"),
        rationale_updates={"deferred_until": until.date().isoformat()},
        trace_id=trace_id,
        run_id=run_id,
    )

    if json_output:
        json_output_response(
            _inbox_envelope(
                ctx,
                binding=_INBOX_DEFER_RPC_BINDING,
                profile_id=item.profile_id,
                notebook_id=item.notebook_id,
                source_of_truth="local_cache",
                cache_mode="offline",
                reason="Defer a local inbox item until a later date.",
                result={"item": _item_to_dict(item)},
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                cache_updates=CacheUpdates(tables_touched=["inbox_items"]),
            )
        )
        return

    console.print(f"[green]Deferred inbox item:[/green] {item.id} until {until.date().isoformat()}")


@inbox.command("apply-batch")
@click.option("--profile", "profile_id", default=None, help="Profile ID (defaults to local default)")
@click.option(
    "--filter",
    "filter_text",
    required=True,
    help="Batch filter in the form '<state>' or '<state>:<priority-band>' (for example 'pending:high').",
)
@click.option("--limit", type=click.IntRange(min=1), default=None, help="Optional cap on matched items.")
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("inbox.apply-batch")
@click.pass_context
def inbox_apply_batch(
    ctx: click.Context,
    profile_id: str | None,
    filter_text: str,
    limit: int | None,
    json_output: bool,
) -> None:
    """Bulk-approve matching inbox items for later import."""
    started_at = time.perf_counter()
    trace_id, run_id = _trace_and_run_id(ctx, "inbox_apply_batch")
    state_filter, priority_band = _parse_apply_batch_filter(filter_text)

    with connect_db() as connection:
        resolved_profile = _resolve_profile_id(connection, profile_id)
        items = InboxItemRepository(connection).list_for_profile(resolved_profile, state=state_filter)

    matched_items = [
        item
        for item in items
        if _matches_apply_batch_filter(item, priority_band=priority_band)
    ]
    if limit is not None:
        matched_items = matched_items[:limit]

    updated_items: list[InboxItemRecord] = []
    approvals_resolved = 0
    for item in matched_items:
        updated, resolved = _transition_item(
            item.id,
            state="approved",
            action="apply-batch",
            allowed_states=_BATCH_APPLY_STATES,
            drop_rationale_keys=("deferred_until",),
            approval_status="approved",
            trace_id=trace_id,
            run_id=run_id,
        )
        updated_items.append(updated)
        approvals_resolved += resolved

    result = {
        "profile_id": resolved_profile,
        "filter": filter_text,
        "state": state_filter,
        "priority_band": priority_band,
        "matched_count": len(matched_items),
        "updated_count": len(updated_items),
        "approval_requests_resolved": approvals_resolved,
        "items": [_item_to_dict(item) for item in updated_items],
    }
    cache_updates = CacheUpdates(
        tables_touched=((["approval_requests"] if approvals_resolved else []) + (["inbox_items"] if updated_items else []))
    )

    if json_output:
        json_output_response(
            _inbox_envelope(
                ctx,
                binding=_INBOX_APPLY_BATCH_RPC_BINDING,
                profile_id=resolved_profile,
                notebook_id=None,
                source_of_truth="local_cache",
                cache_mode="offline",
                reason="Bulk-approve matching local inbox items for later import.",
                result=result,
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                cache_updates=cache_updates,
            )
        )
        return

    if not updated_items:
        console.print(
            f"[yellow]No inbox items matched filter '{filter_text}' for profile {resolved_profile}.[/yellow]"
        )
        return

    console.print(
        f"[green]Approved {len(updated_items)} inbox item(s)[/green] for profile {resolved_profile} "
        f"using filter '{filter_text}'."
    )


@inbox.command("import")
@click.argument("item_id")
@click.option(
    "--approval-token",
    default=None,
    help="Approval token to resume a blocked knowledge-mutation import.",
)
@click.option(
    "--resume-token",
    default=None,
    help="Resume token for a paused approval-gated inbox import.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@manifest_risk_guard("inbox.import")
@with_client
def inbox_import(
    ctx,
    item_id: str,
    approval_token: str | None,
    resume_token: str | None,
    json_output: bool,
    client_auth,
):
    """Import one approved source candidate into its notebook."""
    started_at = time.perf_counter()
    trace_id, run_id = _trace_and_run_id(ctx, "inbox_import")

    async def _run():
        with connect_db() as connection:
            item_repository = InboxItemRepository(connection)
            approval_repository = ApprovalRequestRepository(connection)
            item = _get_item(item_repository, item_id)

        if item.kind != "source":
            raise click.ClickException(
                f"Inbox item {item.id} has kind '{item.kind}'. Only source items can be imported."
            )
        if not item.canonical_uri:
            raise click.ClickException(
                f"Inbox item {item.id} does not have a canonical URI to import."
            )
        if not item.notebook_id:
            raise click.ClickException(f"Inbox item {item.id} is not linked to a notebook.")
        if item.state == "applied":
            raise click.ClickException(f"Inbox item {item.id} is already applied.")
        _require_import_approval(
            connection,
            approval_repository,
            item,
            approval_token=approval_token,
            resume_token=resume_token,
            json_output=json_output,
            ctx=ctx,
            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            trace_id=trace_id,
            run_id=run_id,
        )
        _require_state(item, allowed=("pending", "deferred", "approved"), action="import")

        async with NotebookLMClient(client_auth) as client:
            source = await client.sources.add_url(item.notebook_id, item.canonical_uri)

        updated, resolved = _transition_item(
            item.id,
            state="applied",
            action="import",
            allowed_states=("pending", "deferred", "approved"),
            drop_rationale_keys=("deferred_until",),
            approval_status="approved",
            trace_id=trace_id,
            run_id=run_id,
        )
        payload = {
            "item": _item_to_dict(updated),
            "source": {
                "id": source.id,
                "title": source.title,
                "url": source.url,
            },
            "approval_requests_resolved": resolved,
        }

        if json_output:
            json_output_response(
                _inbox_envelope(
                    ctx,
                    binding=_INBOX_IMPORT_RPC_BINDING,
                      profile_id=updated.profile_id,
                      notebook_id=updated.notebook_id,
                      source_of_truth="mixed",
                      cache_mode="network",
                      reason=_INBOX_IMPORT_REASON,
                      result=payload,
                      elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                      cache_updates=CacheUpdates(
                        tables_touched=(["approval_requests"] if resolved else []) + ["inbox_items"]
                    ),
                )
            )
            return

        console.print(f"[green]Imported inbox item:[/green] {updated.id} -> {source.id}")

    return _run()


__all__ = [
    "inbox",
    "inbox_approve",
    "inbox_apply_batch",
    "inbox_defer",
    "inbox_import",
    "inbox_list",
    "inbox_reject",
    "inbox_view",
]
