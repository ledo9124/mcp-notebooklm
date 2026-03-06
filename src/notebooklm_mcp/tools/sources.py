"""MCP source-management tools."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import os
from pathlib import Path
import tempfile
import time
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any


from notebooklm.exceptions import ConfigurationError, ValidationError
from notebooklm.rpc.types import source_status_to_str
from notebooklm.types import Source

from .._config import MCPConfig, load_config
from .._errors import handle_mcp_errors
from .._result import make_tool_result

DEFAULT_WAIT_TIMEOUT_MS = 60_000
DEFAULT_POLL_INTERVAL_MS = 1_500


def _now() -> float:
    return time.monotonic()


def _get_app_context(ctx: MCPContext) -> Any:
    candidate = None

    if hasattr(ctx, "request_context"):
        request_context = getattr(ctx, "request_context")
        candidate = getattr(request_context, "lifespan_context", None)
    elif hasattr(ctx, "lifespan_context"):
        candidate = getattr(ctx, "lifespan_context")
    else:
        candidate = ctx

    if candidate is None or not hasattr(candidate, "client"):
        raise ConfigurationError("MCP tool context does not provide AppContext.client")
    return candidate


def _resolve_runtime_config(ctx: MCPContext, fallback: MCPConfig) -> MCPConfig:
    request_context = getattr(ctx, "request_context", None)
    server = getattr(request_context, "server", None)
    config = getattr(server, "_notebooklm_mcp_config", None)
    if isinstance(config, MCPConfig):
        return config
    return fallback


@contextlib.asynccontextmanager
async def _acquire_slot(app_context: Any):
    acquire_slot = getattr(app_context, "acquire_slot", None)
    if callable(acquire_slot):
        async with acquire_slot():
            yield
        return
    yield


def _coerce_positive_int(value: int | None, *, field_name: str, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValidationError(f"{field_name} must be a positive integer")
    return value


def _source_to_summary(source: Source) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "source_id": source.id,
        "title": source.title,
        "kind": source.kind.value,
        "status": source_status_to_str(source.status),
    }
    if source.created_at is not None:
        summary["created_at"] = source.created_at.isoformat()
    return summary


async def _list_sources(app_context: Any, notebook_id: str) -> list[Source]:
    async with _acquire_slot(app_context):
        return await app_context.client.sources.list(notebook_id)


async def _wait_for_sources(
    app_context: Any,
    notebook_id: str,
    *,
    source_ids: set[str] | None = None,
    timeout_ms: int = DEFAULT_WAIT_TIMEOUT_MS,
    poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS,
) -> tuple[bool, list[dict[str, Any]]]:
    timeout_seconds = timeout_ms / 1000.0
    poll_seconds = poll_interval_ms / 1000.0
    started_at = _now()
    statuses: list[dict[str, Any]] = []

    while True:
        sources = await _list_sources(app_context, notebook_id)
        tracked = [src for src in sources if source_ids is None or src.id in source_ids]
        statuses = [_source_to_summary(src) for src in tracked]

        if tracked and all(item["status"] == "ready" for item in statuses):
            return True, statuses

        if any(item["status"] == "error" for item in statuses):
            return False, statuses

        if _now() - started_at >= timeout_seconds:
            return False, statuses

        await asyncio.sleep(poll_seconds)


@handle_mcp_errors
async def notebooklm_sources_list(ctx: MCPContext, notebook_id: str) -> dict[str, Any]:
    """List all sources for a notebook."""
    app_context = _get_app_context(ctx)
    sources = await _list_sources(app_context, notebook_id)
    return make_tool_result({"sources": [_source_to_summary(source) for source in sources]})


@handle_mcp_errors
async def notebooklm_sources_add_url(
    ctx: MCPContext,
    notebook_id: str,
    url: str,
    wait: bool = True,
    timeout_ms: int | None = None,
    poll_interval_ms: int | None = None,
) -> dict[str, Any]:
    """Add a URL source with optional bounded wait."""
    app_context = _get_app_context(ctx)
    resolved_timeout_ms = _coerce_positive_int(
        timeout_ms,
        field_name="timeout_ms",
        default=DEFAULT_WAIT_TIMEOUT_MS,
    )
    resolved_poll_interval_ms = _coerce_positive_int(
        poll_interval_ms,
        field_name="poll_interval_ms",
        default=DEFAULT_POLL_INTERVAL_MS,
    )

    async with _acquire_slot(app_context):
        source = await app_context.client.sources.add_url(notebook_id, url, wait=False)

    payload: dict[str, Any] = {
        "source_id": source.id,
        "status": source_status_to_str(source.status),
        "ready": source.is_ready,
    }

    if wait:
        ready, statuses = await _wait_for_sources(
            app_context,
            notebook_id,
            source_ids={source.id},
            timeout_ms=resolved_timeout_ms,
            poll_interval_ms=resolved_poll_interval_ms,
        )
        payload["ready"] = ready
        if statuses:
            payload["status"] = statuses[0]["status"]
            payload["statuses"] = statuses

    return make_tool_result(payload)


@handle_mcp_errors
async def notebooklm_sources_add_text(
    ctx: MCPContext,
    notebook_id: str,
    title: str,
    content: str,
) -> dict[str, Any]:
    """Add a text source."""
    app_context = _get_app_context(ctx)
    async with _acquire_slot(app_context):
        source = await app_context.client.sources.add_text(notebook_id, title, content)

    return make_tool_result(
        {
            "source_id": source.id,
            "status": source_status_to_str(source.status),
        }
    )


@handle_mcp_errors
async def notebooklm_sources_add_file(
    ctx: MCPContext,
    notebook_id: str,
    filename: str,
    mime_type: str,
    data_base64: str,
    title: str | None = None,
) -> dict[str, Any]:
    """Add a file source using base64 content payload."""
    app_context = _get_app_context(ctx)

    try:
        raw_bytes = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("data_base64 must be valid base64 data") from exc

    suffix = Path(filename).suffix
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=suffix,
            delete=False,
        ) as temp_file:
            temp_file.write(raw_bytes)
            temp_path = temp_file.name

        async with _acquire_slot(app_context):
            source = await app_context.client.sources.add_file(
                notebook_id,
                temp_path,
                mime_type=mime_type,
            )

            if title and title != source.title:
                source = await app_context.client.sources.rename(notebook_id, source.id, title)
    finally:
        if temp_path:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_path)

    return make_tool_result(
        {
            "source_id": source.id,
            "status": source_status_to_str(source.status),
        }
    )


@handle_mcp_errors
async def notebooklm_sources_remove(
    ctx: MCPContext,
    notebook_id: str,
    source_id: str,
    confirm: bool,
) -> dict[str, Any]:
    """Remove a source when destructive tools are enabled and confirmed."""
    app_context = _get_app_context(ctx)
    config = _resolve_runtime_config(ctx, fallback=load_config())
    if not config.enable_destructive_tools:
        raise ValidationError(
            "Source removal is disabled. Set NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1 to enable."
        )
    if confirm is not True:
        raise ValidationError("confirm=true is required for source removal")

    async with _acquire_slot(app_context):
        await app_context.client.sources.delete(notebook_id, source_id)
    return make_tool_result({"success": True})


@handle_mcp_errors
async def notebooklm_sources_wait_ready(
    ctx: MCPContext,
    notebook_id: str,
    timeout_ms: int | None = None,
    poll_interval_ms: int | None = None,
) -> dict[str, Any]:
    """Poll source statuses until all tracked sources are ready or timeout."""
    app_context = _get_app_context(ctx)
    resolved_timeout_ms = _coerce_positive_int(
        timeout_ms,
        field_name="timeout_ms",
        default=DEFAULT_WAIT_TIMEOUT_MS,
    )
    resolved_poll_interval_ms = _coerce_positive_int(
        poll_interval_ms,
        field_name="poll_interval_ms",
        default=DEFAULT_POLL_INTERVAL_MS,
    )

    ready, statuses = await _wait_for_sources(
        app_context,
        notebook_id,
        timeout_ms=resolved_timeout_ms,
        poll_interval_ms=resolved_poll_interval_ms,
    )
    return make_tool_result({"ready": ready, "statuses": statuses})


@handle_mcp_errors
async def notebooklm_sources_get_content(
    ctx: MCPContext,
    notebook_id: str,
    source_id: str,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Get source content with a configured size cap."""
    app_context = _get_app_context(ctx)
    config = load_config()
    cap = config.source_content_max_chars

    if max_chars is None:
        requested_max = cap
    else:
        requested_max = _coerce_positive_int(max_chars, field_name="max_chars", default=cap)

    effective_max = min(requested_max, cap)

    async with _acquire_slot(app_context):
        fulltext = await app_context.client.sources.get_fulltext(notebook_id, source_id)

    content = fulltext.content
    truncated = len(content) > effective_max
    preview = content[:effective_max]

    return make_tool_result(
        {
            "source_id": source_id,
            "content": preview,
            "truncated": truncated,
            "returned_chars": len(preview),
            "total_chars": len(content),
            "max_chars": effective_max,
        }
    )


def register_sources_tools(server: Any) -> None:
    """Register source tools with a FastMCP-like server instance."""
    tool = getattr(server, "tool", None)
    if not callable(tool):
        return

    registrations = (
        ("notebooklm_sources_list", notebooklm_sources_list, "List notebook sources"),
        ("notebooklm_sources_add_url", notebooklm_sources_add_url, "Add URL source"),
        ("notebooklm_sources_add_text", notebooklm_sources_add_text, "Add text source"),
        ("notebooklm_sources_add_file", notebooklm_sources_add_file, "Add file source"),
        ("notebooklm_sources_remove", notebooklm_sources_remove, "Remove source (destructive)"),
        ("notebooklm_sources_wait_ready", notebooklm_sources_wait_ready, "Wait for sources readiness"),
        ("notebooklm_sources_get_content", notebooklm_sources_get_content, "Get source fulltext"),
    )

    for name, fn, description in registrations:
        decorator = tool(name=name, description=description)
        decorator(fn)


__all__ = [
    "DEFAULT_POLL_INTERVAL_MS",
    "DEFAULT_WAIT_TIMEOUT_MS",
    "notebooklm_sources_add_file",
    "notebooklm_sources_add_text",
    "notebooklm_sources_add_url",
    "notebooklm_sources_get_content",
    "notebooklm_sources_list",
    "notebooklm_sources_remove",
    "notebooklm_sources_wait_ready",
    "register_sources_tools",
]
