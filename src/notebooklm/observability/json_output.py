"""Trace-aware JSON output helpers for Click-based CLI commands."""

from __future__ import annotations

import json
from typing import Any

import click

from .tracing import current_trace

_PATCH_SENTINEL = "_notebooklm_trace_json_patch"


def _inject_trace_id(message: Any) -> Any:
    """Add the active trace ID to JSON-object strings when available."""
    if not isinstance(message, str):
        return message

    trace = current_trace()
    if trace is None:
        return message

    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return message

    if not isinstance(payload, dict):
        return message

    existing_trace_id = payload.get("trace_id")
    if existing_trace_id not in (None, "", "trc_unknown"):
        return message

    payload["trace_id"] = trace.trace_id
    return json.dumps(payload, indent=2)


def install_trace_json_echo() -> None:
    """Patch ``click.echo`` once so traced CLI JSON includes ``trace_id``."""
    if getattr(click.echo, _PATCH_SENTINEL, False):
        return

    original_echo = click.echo

    def traced_echo(
        message: Any | None = None,
        file: Any | None = None,
        nl: bool = True,
        err: bool = False,
        color: bool | None = None,
    ) -> None:
        original_echo(
            _inject_trace_id(message),
            file=file,
            nl=nl,
            err=err,
            color=color,
        )

    setattr(traced_echo, _PATCH_SENTINEL, True)
    click.echo = traced_echo


__all__ = ["install_trace_json_echo"]
