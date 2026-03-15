"""Risk-tier primitives for the Phase-0 contract surface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, TypeVar


@dataclass(frozen=True)
class _RiskDetails:
    alias: str
    scope: str
    guard_behavior: str


class RiskTier(str, Enum):
    """Canonical risk tiers from CONTRACT_NORMALIZATION §1."""

    T0_READ = "T0_READ"
    T1_LOCAL_MUTATION = "T1_LOCAL_MUTATION"
    T2_KNOWLEDGE_MUTATION = "T2_KNOWLEDGE_MUTATION"
    T3_DESTRUCTIVE = "T3_DESTRUCTIVE"

    @property
    def alias(self) -> str:
        return _RISK_DETAILS[self].alias

    @property
    def scope(self) -> str:
        return _RISK_DETAILS[self].scope

    @property
    def guard_behavior(self) -> str:
        return _RISK_DETAILS[self].guard_behavior


_RISK_DETAILS = {
    RiskTier.T0_READ: _RiskDetails(
        alias="SAFE",
        scope="Read-only operations: list, show, doctor, ask, history, trace, events, workspace ask, radar brief, inbox view",
        guard_behavior="No approval needed",
    ),
    RiskTier.T1_LOCAL_MUTATION: _RiskDetails(
        alias="CAUTION",
        scope="Low-risk local mutations: rebuild index, clear stale leases, refresh auth, resync metadata, cache prune",
        guard_behavior="`--dry-run` supported; `--yes` needed if side effect is large",
    ),
    RiskTier.T2_KNOWLEDGE_MUTATION: _RiskDetails(
        alias="DANGEROUS",
        scope="External knowledge mutations: import source, import report, replace changed source, apply research results",
        guard_behavior="Approval required by default; policy can auto-approve specific patterns",
    ),
    RiskTier.T3_DESTRUCTIVE: _RiskDetails(
        alias="CRITICAL",
        scope="Destructive mutations: delete source, delete notebook, purge cache, reset profile, bulk deletes",
        guard_behavior="Explicit confirm/approval token required; two-step in non-interactive mode",
    ),
}

F = TypeVar("F", bound=Callable[..., Any])
GuardNextStepKind = Literal["confirm", "approval_token", "resume_token", "dry_run"]
_GUARD_NEXT_STEP_KINDS = {"confirm", "approval_token", "resume_token", "dry_run"}


@lru_cache(maxsize=None)
def _load_manifest_command_specs(
    manifest_path: str | None,
) -> dict[str, "CommandSpec"]:
    from . import load_capabilities
    from .command_specs import CommandSpec

    capabilities = load_capabilities(manifest_path)
    commands = capabilities.get("commands")
    if not isinstance(commands, dict):
        raise ValueError("Capabilities manifest is missing a `commands` mapping")

    return {
        name: CommandSpec.from_manifest(name, raw)
        for name, raw in commands.items()
        if isinstance(raw, dict)
    }


def risk_guard(
    tier: RiskTier,
    *,
    approval_gated: bool | None = None,
    destructive: bool | None = None,
) -> Callable[[F], F]:
    """Attach contract risk metadata to a callable for later enforcement layers."""

    def decorator(func: F) -> F:
        setattr(func, "__risk_tier__", tier)
        setattr(func, "__risk_alias__", tier.alias)
        setattr(
            func,
            "__approval_gated__",
            approval_gated if approval_gated is not None else tier in {
                RiskTier.T2_KNOWLEDGE_MUTATION,
                RiskTier.T3_DESTRUCTIVE,
            },
        )
        setattr(
            func,
            "__destructive__",
            destructive if destructive is not None else tier is RiskTier.T3_DESTRUCTIVE,
        )
        return func

    return decorator


def manifest_risk_guard(
    command_name: str,
    *,
    path: str | Path | None = None,
) -> Callable[[F], F]:
    """Attach risk metadata for one command by reading the capabilities manifest."""

    manifest_key = None if path is None else str(Path(path))
    command_specs = _load_manifest_command_specs(manifest_key)
    spec = command_specs.get(command_name)
    if spec is None:
        raise ValueError(f"Unknown command in capabilities manifest: {command_name}")

    return risk_guard(
        spec.risk_tier,
        approval_gated=spec.approval_gated,
        destructive=spec.destructive,
    )


def guard_refusal_details(
    tier: RiskTier,
    *,
    next_step_kind: GuardNextStepKind,
    next_step: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical refusal metadata for guarded command failures."""
    if next_step_kind not in _GUARD_NEXT_STEP_KINDS:
        raise ValueError(f"Unknown guard refusal next_step_kind: {next_step_kind}")
    if not next_step.strip():
        raise ValueError("Guard refusal next_step cannot be empty")

    details = dict(extra or {})
    details.update(
        {
            "next_step": next_step,
            "next_step_kind": next_step_kind,
            "risk_tier": tier.value,
            "risk_alias": tier.alias,
            "guard_behavior": tier.guard_behavior,
        }
    )
    return details


__all__ = ["RiskTier", "guard_refusal_details", "manifest_risk_guard", "risk_guard"]
