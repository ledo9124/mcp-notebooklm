"""Dataclass models for the canonical Phase-0 JSON envelope."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Literal

from notebooklm.contracts.intents import Intent


def _normalize(value: Any) -> Any:
    """Recursively convert dataclasses and enums into plain JSON-like values."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _normalize(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


@dataclass(frozen=True)
class Transport:
    """Execution transport details captured in the route metadata."""

    kind: Literal["httpx", "local"]
    endpoint: str | None = None
    rpcid: str | None = None


@dataclass(frozen=True)
class Route:
    """Routing metadata shared by all canonical JSON responses."""

    intent: Intent
    mode: str | None
    notebook_id: str | None
    profile_id: str
    source_of_truth: Literal["local_cache", "remote_http", "mixed"]
    cache_mode: Literal["smart", "refresh", "offline", "network"]
    reason: str
    transport: Transport


@dataclass(frozen=True)
class Freshness:
    """Cache freshness metadata for commands that depend on cached state."""

    notebook_index_age_s: int | None = None
    notebook_detail_age_s: int | None = None
    used_cached_result: bool = False


@dataclass(frozen=True)
class CacheUpdates:
    """Post-run cache mutation summary."""

    tables_touched: list[str] = field(default_factory=list)
    invalidated: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Diagnostics:
    """Basic execution diagnostics carried in the canonical envelope."""

    retries: int = 0
    auth_refreshed: bool = False
    elapsed_ms: int = 0


@dataclass(frozen=True)
class Envelope:
    """Canonical response envelope for human and JSON-oriented command output."""

    ok: bool
    trace_id: str
    run_id: str
    route: Route
    result: dict[str, Any] = field(default_factory=dict)
    freshness: Freshness | None = None
    cache_updates: CacheUpdates = field(default_factory=CacheUpdates)
    diagnostics: Diagnostics = field(default_factory=Diagnostics)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-Python representation ready for JSON serialization."""
        return _normalize(self)


__all__ = [
    "CacheUpdates",
    "Diagnostics",
    "Envelope",
    "Freshness",
    "Route",
    "Transport",
]
