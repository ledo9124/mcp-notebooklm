"""Global user-settings MCP tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any

from notebooklm.exceptions import ValidationError

from .._errors import handle_mcp_errors
from .._result import make_tool_result
from ..server import AppContext

logger = logging.getLogger("notebooklm_mcp.tools.settings")


def _resolve_app_context(ctx: MCPContext) -> AppContext:
    request_context = getattr(ctx, "request_context", None)
    app = getattr(request_context, "lifespan_context", None)
    if app is None:
        app = getattr(ctx, "lifespan_context", None)
    if isinstance(app, AppContext):
        return app
    raise RuntimeError("NotebookLM MCP lifespan context is unavailable.")


def _require_language(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("language must be a non-empty string.")
    return value.strip()


def _serialize_output_language(language: str | None) -> dict[str, Any]:
    return {
        "language": language,
        "is_default": language is None,
        "scope": "global",
    }


def _register_tool(
    server: Any,
    *,
    name: str,
    description: str,
    handler: Callable[..., Any],
) -> None:
    tool_factory = getattr(server, "tool", None)
    if not callable(tool_factory):
        logger.warning("Cannot register tool %s: server has no callable tool()", name)
        return

    for kwargs in (
        {"name": name, "description": description},
        {"name": name},
        {},
    ):
        try:
            decorator = tool_factory(**kwargs)
        except TypeError:
            continue

        if not callable(decorator):
            continue

        decorator(handler)
        return

    raise RuntimeError(f"Failed to register MCP tool: {name}")


def register_settings_tools(server: Any) -> dict[str, Callable[..., Any]]:
    """Register global user-settings tools and return handlers keyed by tool name."""

    @handle_mcp_errors
    async def notebooklm_output_language_get(ctx: MCPContext) -> dict[str, Any]:
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            language = await app.client.settings.get_output_language()
        return make_tool_result(_serialize_output_language(language))

    @handle_mcp_errors
    async def notebooklm_output_language_set(
        ctx: MCPContext,
        language: str,
    ) -> dict[str, Any]:
        clean_language = _require_language(language)
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            after = await app.client.settings.set_output_language(clean_language)

        payload: dict[str, Any] = {
            "success": True,
            "requested_language": clean_language,
            "response_parsed": after is not None,
            "after": _serialize_output_language(after),
        }
        if after is None:
            payload["warnings"] = [
                "Server response did not include a parseable output language value."
            ]
        return make_tool_result(payload)

    handlers: dict[str, Callable[..., Any]] = {
        "notebooklm_output_language_get": notebooklm_output_language_get,
        "notebooklm_output_language_set": notebooklm_output_language_set,
    }

    descriptions = {
        "notebooklm_output_language_get": (
            "Read the account-global output language used for artifact generation."
        ),
        "notebooklm_output_language_set": (
            "Set the account-global output language used for artifact generation."
        ),
    }

    for name, handler in handlers.items():
        _register_tool(
            server,
            name=name,
            description=descriptions[name],
            handler=handler,
        )

    return handlers


__all__ = ["register_settings_tools"]
