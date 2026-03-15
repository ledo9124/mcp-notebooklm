"""Shared approval helpers for destructive CLI mutations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import click

from ..approval_policies import ResolvedApprovalPolicy, resolve_approval_policy
from ..contracts import Diagnostics, Intent, Transport
from ..contracts.risk import RiskTier, guard_refusal_details
from ..local.repositories import ApprovalRequestRecord, ApprovalRequestRepository
from ..observability.tracing import generate_trace_id
from .helpers import json_error_response


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prefixed_trace_id(prefix: str) -> str:
    return generate_trace_id().replace("trc_", f"{prefix}_", 1)


def _approval_to_dict(approval: ApprovalRequestRecord) -> dict[str, Any]:
    return {
        "id": approval.id,
        "trace_id": approval.trace_id,
        "entity_type": approval.entity_type,
        "entity_id": approval.entity_id,
        "action": approval.action,
        "risk_tier": approval.risk_tier,
        "policy_name": approval.policy_name,
        "requested_by": approval.requested_by,
        "requested_at": approval.requested_at,
        "resolved_at": approval.resolved_at,
        "status": approval.status,
        "reason": approval.reason,
        "resume_token": approval.resume_token,
        "decision_json": approval.decision_json,
    }


def _pending_approval(
    approval_repository: ApprovalRequestRepository,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
) -> ApprovalRequestRecord | None:
    for approval in approval_repository.list_for_entity(entity_type, entity_id):
        if approval.action == action and approval.status == "pending":
            return approval
    return None


def ensure_destructive_approval_request(
    approval_repository: ApprovalRequestRepository,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    reason: str,
    requested_by: str = "agent",
    policy_name: str = "default",
) -> tuple[ApprovalRequestRecord, bool]:
    pending = _pending_approval(
        approval_repository,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
    )
    if pending is not None:
        return pending, False

    approval = ApprovalRequestRecord(
        id=_prefixed_trace_id("appr"),
        trace_id=generate_trace_id(),
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        risk_tier=RiskTier.T3_DESTRUCTIVE.value,
        policy_name=policy_name,
        requested_by=requested_by,
        requested_at=_utc_now(),
        status="pending",
        reason=reason,
        resume_token=_prefixed_trace_id("resume"),
    )
    approval_repository.upsert(approval)
    return approval, True


def destructive_approval_refusal(
    *,
    entity_label: str,
    entity_type: str,
    entity_id: str,
    action: str,
    command_path: str,
    approval: ApprovalRequestRecord,
    created: bool,
    resolved_policy: ResolvedApprovalPolicy,
) -> tuple[str, dict[str, Any]]:
    message = f"{entity_label} requires approval before {action}."
    full_command = f"{command_path} --approval-token {approval.id}"
    details = guard_refusal_details(
        RiskTier.T3_DESTRUCTIVE,
        next_step_kind="approval_token",
        next_step=f"--approval-token {approval.id}",
        extra={
            "approval_request": _approval_to_dict(approval),
            "approval_request_created": created,
            "approval_token": approval.id,
            "resume_token": approval.resume_token,
            "resume_command": full_command,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "policy_name": resolved_policy.policy_name,
            "policy_source": resolved_policy.source,
            "policy_match_kind": resolved_policy.match_kind,
            "policy_mode": resolved_policy.mode,
        },
    )
    return message, details


def require_destructive_approval(
    approval_repository: ApprovalRequestRepository,
    *,
    entity_label: str,
    entity_type: str,
    entity_id: str,
    action: str,
    reason: str,
    command_path: str,
    preview_command: str | None,
    approval_token: str | None,
    assume_yes: bool,
    json_output: bool,
    ctx: click.Context | None = None,
    binding: Any | None = None,
    profile_id: str = "default",
    notebook_id: str | None = None,
    workspace_id: str | None = None,
    approval_policy_override: object | None = None,
    source_of_truth: str = "local_cache",
    cache_mode: str = "offline",
    transport: Transport | None = None,
    route_reason: str | None = None,
    diagnostics: Diagnostics | None = None,
) -> None:
    resolved_policy = resolve_approval_policy(
        approval_repository._connection,
        entity_type=entity_type,
        action=action,
        risk_tier=RiskTier.T3_DESTRUCTIVE.value,
        profile_id=profile_id,
        notebook_id=notebook_id,
        workspace_id=workspace_id,
        command_override=approval_policy_override,
    )

    if resolved_policy.mode == "auto":
        return

    if assume_yes:
        return

    if approval_token is None and not json_output:
        if preview_command is None:
            guidance = f"Run `{command_path} --yes` to confirm."
        else:
            guidance = (
                f"Run `{preview_command}` to preview, or `{command_path} --yes` to confirm."
            )
        raise click.ClickException(
            f"{entity_label} requires explicit confirmation before {action}. {guidance}"
        )

    approval, created = ensure_destructive_approval_request(
        approval_repository,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        reason=reason,
        policy_name=resolved_policy.policy_name,
    )
    message, details = destructive_approval_refusal(
        entity_label=entity_label,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        command_path=command_path,
        approval=approval,
        created=created,
        resolved_policy=resolved_policy,
    )

    if approval_token is None:
        json_error_response(
            "APPROVAL_REQUIRED",
            message,
            extra=details,
            ctx=ctx,
            binding=binding,
            intent=Intent.LOCAL_MUTATION if binding is None else None,
            mode=None if binding is not None else f"{entity_type}_{action}",
            profile_id=profile_id,
            notebook_id=notebook_id,
            source_of_truth=source_of_truth,
            cache_mode=cache_mode,
            reason=route_reason or reason,
            transport=transport,
            diagnostics=diagnostics,
        )

    if approval_token != approval.id:
        invalid_message = f"Approval token {approval_token} is not valid for {entity_label}."
        if json_output:
            json_error_response(
                "APPROVAL_REQUIRED",
                invalid_message,
                extra=details,
                ctx=ctx,
                binding=binding,
                intent=Intent.LOCAL_MUTATION if binding is None else None,
                mode=None if binding is not None else f"{entity_type}_{action}",
                profile_id=profile_id,
                notebook_id=notebook_id,
                source_of_truth=source_of_truth,
                cache_mode=cache_mode,
                reason=route_reason or reason,
                transport=transport,
                diagnostics=diagnostics,
            )
        raise click.ClickException(f"{invalid_message} Use `{details['resume_command']}` instead.")


def resolve_destructive_approvals(
    approval_repository: ApprovalRequestRepository,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    decision_json: str | None = None,
) -> int:
    resolved = 0
    for approval in approval_repository.list_for_entity(entity_type, entity_id):
        if approval.action != action or approval.status != "pending":
            continue
        approval_repository.resolve(
            approval.id,
            status="approved",
            resolved_at=_utc_now(),
            decision_json=decision_json,
        )
        resolved += 1
    return resolved


__all__ = [
    "destructive_approval_refusal",
    "ensure_destructive_approval_request",
    "require_destructive_approval",
    "resolve_destructive_approvals",
]
