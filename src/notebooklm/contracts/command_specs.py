"""Typed command metadata for manifest-driven help and compatibility checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from notebooklm.contracts.risk import RiskTier


class DeprecationState(str, Enum):
    """Compatibility states used by the frozen Phase-0 manifest."""

    NONE = "none"
    WARN = "warn"


@dataclass(frozen=True)
class CompatibilitySpec:
    """Alias and deprecation metadata for a canonical command."""

    aliases: tuple[str, ...]
    deprecation_state: DeprecationState
    deprecation_warning: str | None = None

    @classmethod
    def from_manifest(cls, raw: Mapping[str, Any]) -> "CompatibilitySpec":
        return cls(
            aliases=tuple(raw.get("aliases", [])),
            deprecation_state=DeprecationState(raw["deprecation_state"]),
            deprecation_warning=raw.get("deprecation_warning"),
        )


@dataclass(frozen=True)
class CommandSpec:
    """Typed view over one `commands.<name>` entry from `capabilities.yaml`."""

    name: str
    intent: str
    risk_tier: RiskTier
    compatibility: CompatibilitySpec
    read_only: bool
    waitable: bool
    destructive: bool
    approval_gated: bool
    output: str | None = None
    mode: str | None = None
    remote: bool | None = None

    @classmethod
    def from_manifest(cls, name: str, raw: Mapping[str, Any]) -> "CommandSpec":
        return cls(
            name=name,
            intent=str(raw["intent"]),
            risk_tier=RiskTier(raw["risk_tier"]),
            compatibility=CompatibilitySpec.from_manifest(raw["compatibility"]),
            read_only=bool(raw["read_only"]),
            waitable=bool(raw["waitable"]),
            destructive=bool(raw["destructive"]),
            approval_gated=bool(raw["approval_gated"]),
            output=raw.get("output"),
            mode=raw.get("mode"),
            remote=raw.get("remote"),
        )


__all__ = ["CommandSpec", "CompatibilitySpec", "DeprecationState"]
