"""Resolve approval-policy inheritance for approval-gated commands."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import sqlite3
from typing import Any, Literal

from .local.repositories import NotebookRepository, WorkspaceRepository
from .profiles.manager import ProfileManager


ApprovalMode = Literal["manual", "auto"]
PolicySource = Literal["command_override", "workspace", "notebook", "profile", "default"]
MatchKind = Literal["default", "entity_type", "action", "risk_tier"]

_MODE_ALIASES: dict[str, ApprovalMode] = {
    "allow": "auto",
    "approved": "auto",
    "auto": "auto",
    "manual": "manual",
    "require_approval": "manual",
}


@dataclass(frozen=True)
class ResolvedApprovalPolicy:
    """One resolved approval-policy decision."""

    mode: ApprovalMode
    policy_name: str
    source: PolicySource
    match_kind: MatchKind


def _normalize_mode(value: object) -> ApprovalMode | None:
    if not isinstance(value, str):
        return None
    return _MODE_ALIASES.get(value.strip().casefold())


def _coerce_policy_config(raw_policy: object) -> Mapping[str, Any] | None:
    if raw_policy is None:
        return None
    if isinstance(raw_policy, Mapping):
        return raw_policy
    if isinstance(raw_policy, str):
        text = raw_policy.strip()
        if not text:
            return None
        mode = _normalize_mode(text)
        if mode is not None:
            return {"default": mode}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, Mapping):
            return parsed
        mode = _normalize_mode(parsed)
        if mode is not None:
            return {"default": mode}
    return None


def _default_policy_name(source: PolicySource) -> str:
    if source == "command_override":
        return "command-override"
    if source == "default":
        return "default"
    return f"{source}-default"


def _coerce_match(
    rule: object,
    *,
    source: PolicySource,
    fallback_name: str,
    match_kind: MatchKind,
) -> ResolvedApprovalPolicy | None:
    if isinstance(rule, Mapping):
        mode = _normalize_mode(rule.get("mode"))
        policy_name = str(rule.get("name") or fallback_name)
    else:
        mode = _normalize_mode(rule)
        policy_name = fallback_name
    if mode is None:
        return None
    return ResolvedApprovalPolicy(
        mode=mode,
        policy_name=policy_name,
        source=source,
        match_kind=match_kind,
    )


def _resolve_from_config(
    config: Mapping[str, Any],
    *,
    source: PolicySource,
    entity_type: str,
    action: str,
    risk_tier: str,
) -> ResolvedApprovalPolicy | None:
    fallback_name = str(config.get("name") or _default_policy_name(source))

    entity_rule = config.get("entity_types")
    if isinstance(entity_rule, Mapping) and entity_type in entity_rule:
        return _coerce_match(
            entity_rule[entity_type],
            source=source,
            fallback_name=fallback_name,
            match_kind="entity_type",
        )

    action_rule = config.get("actions")
    if isinstance(action_rule, Mapping) and action in action_rule:
        return _coerce_match(
            action_rule[action],
            source=source,
            fallback_name=fallback_name,
            match_kind="action",
        )

    risk_rule = config.get("risk_tiers")
    if isinstance(risk_rule, Mapping) and risk_tier in risk_rule:
        return _coerce_match(
            risk_rule[risk_tier],
            source=source,
            fallback_name=fallback_name,
            match_kind="risk_tier",
        )

    if "default" in config:
        return _coerce_match(
            config.get("default"),
            source=source,
            fallback_name=fallback_name,
            match_kind="default",
        )

    if "mode" in config:
        return _coerce_match(
            config.get("mode"),
            source=source,
            fallback_name=fallback_name,
            match_kind="default",
        )

    return None


def resolve_approval_policy(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    action: str,
    risk_tier: str,
    profile_id: str | None,
    notebook_id: str | None = None,
    workspace_id: str | None = None,
    command_override: object | None = None,
) -> ResolvedApprovalPolicy:
    """Resolve the effective approval policy using the configured precedence."""

    candidates: list[tuple[PolicySource, object | None]] = [("command_override", command_override)]

    if workspace_id is not None:
        workspace = WorkspaceRepository(connection).get(workspace_id)
        candidates.append(
            ("workspace", None if workspace is None else workspace.approval_policy_json)
        )

    if notebook_id is not None:
        notebook = NotebookRepository(connection).get(notebook_id)
        candidates.append(
            ("notebook", None if notebook is None else notebook.approval_policy_json)
        )

    if profile_id is not None:
        profile = ProfileManager(connection).get_profile(profile_id)
        candidates.append(
            ("profile", None if profile is None else profile.approval_policy_json)
        )

    for source, raw_policy in candidates:
        config = _coerce_policy_config(raw_policy)
        if config is None:
            continue
        resolved = _resolve_from_config(
            config,
            source=source,
            entity_type=entity_type,
            action=action,
            risk_tier=risk_tier,
        )
        if resolved is not None:
            return resolved

    return ResolvedApprovalPolicy(
        mode="manual",
        policy_name="default",
        source="default",
        match_kind="default",
    )


__all__ = ["ResolvedApprovalPolicy", "resolve_approval_policy"]
