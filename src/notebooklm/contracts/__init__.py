"""Contract package exports and manifest loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .command_specs import CommandSpec, CompatibilitySpec, DeprecationState
from .envelope_schema import CacheUpdates, Diagnostics, Envelope, Freshness, Route, Transport
from .intents import Intent
from .risk import RiskTier, manifest_risk_guard, risk_guard


CAPABILITIES_PATH = Path(__file__).with_name("capabilities.yaml")


def _parse_scalar(value: str) -> Any:
    """Parse the small YAML scalar subset used by capabilities.yaml."""
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "[]":
        return []
    if value == "null":
        return None
    if value.isdigit():
        return int(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _prepare_lines(path: Path) -> list[tuple[int, str]]:
    """Return indentation-aware manifest lines, skipping blanks and comments."""
    prepared: list[tuple[int, str]] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        prepared.append((len(raw_line) - len(raw_line.lstrip(" ")), stripped))

    return prepared


def _parse_block(lines: list[tuple[int, str]], start: int, indent: int) -> tuple[Any, int]:
    """Parse a mapping/list block from the prepared line stream."""
    current_indent, current_line = lines[start]
    if current_indent != indent:
        raise ValueError(f"Unexpected indentation at line {start + 1}: {current_line}")

    if current_line.startswith("- "):
        items: list[Any] = []
        index = start

        while index < len(lines):
            line_indent, line = lines[index]
            if line_indent < indent:
                break
            if line_indent != indent or not line.startswith("- "):
                break

            value = line[2:].strip()
            if value:
                items.append(_parse_scalar(value))
                index += 1
                continue

            nested, index = _parse_block(lines, index + 1, indent + 2)
            items.append(nested)

        return items, index

    mapping: dict[str, Any] = {}
    index = start

    while index < len(lines):
        line_indent, line = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent or line.startswith("- "):
            break

        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"Invalid mapping entry: {line}")

        value = value.lstrip()
        if value:
            mapping[key] = _parse_scalar(value)
            index += 1
            continue

        nested, index = _parse_block(lines, index + 1, indent + 2)
        mapping[key] = nested

    return mapping, index


def load_capabilities(path: str | Path | None = None) -> dict[str, Any]:
    """Load the Phase-0 capabilities manifest into plain Python data."""
    manifest_path = Path(path) if path is not None else CAPABILITIES_PATH
    prepared_lines = _prepare_lines(manifest_path)
    if not prepared_lines:
        raise ValueError(f"Manifest is empty: {manifest_path}")

    parsed, next_index = _parse_block(prepared_lines, 0, 0)
    if next_index != len(prepared_lines):
        raise ValueError(f"Unexpected trailing manifest content in {manifest_path}")
    if not isinstance(parsed, dict):
        raise ValueError(f"Manifest root must be a mapping: {manifest_path}")

    return parsed


__all__ = [
    "CAPABILITIES_PATH",
    "CacheUpdates",
    "CommandSpec",
    "CompatibilitySpec",
    "DeprecationState",
    "Diagnostics",
    "Envelope",
    "Freshness",
    "Intent",
    "RiskTier",
    "Route",
    "Transport",
    "load_capabilities",
    "manifest_risk_guard",
    "risk_guard",
]
