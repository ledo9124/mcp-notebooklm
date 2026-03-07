"""Chat settings MCP tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any


from notebooklm.exceptions import ValidationError
from notebooklm.rpc.types import ChatGoal, ChatResponseLength
from notebooklm.types import UNSET, ChatSettings

from .._config import MCPConfig, load_config
from .._errors import handle_mcp_errors
from .._fingerprint import fingerprint_settings
from .._mapping import map_from_enum, map_to_enum
from .._result import make_tool_result
from ..server import AppContext

logger = logging.getLogger("notebooklm_mcp.tools.chat_settings")

# NOTE:
# Tool signatures are introspected into Pydantic schemas by FastMCP.
# Non-serializable default values (e.g. object()) trigger
# PydanticJsonSchemaWarning during schema generation.
_UNSET_PROMPT_SENTINEL = "__NOTEBOOKLM_MCP_UNSET_CUSTOM_PROMPT__"


def _resolve_app_context(ctx: MCPContext) -> AppContext:
    request_context = getattr(ctx, "request_context", None)
    app = getattr(request_context, "lifespan_context", None)
    if app is None:
        app = getattr(ctx, "lifespan_context", None)
    if isinstance(app, AppContext):
        return app
    raise RuntimeError("NotebookLM MCP lifespan context is unavailable.")


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value.strip()


def _resolve_runtime_config(ctx: MCPContext, fallback: MCPConfig) -> MCPConfig:
    request_context = getattr(ctx, "request_context", None)
    server = getattr(request_context, "server", None)
    config = getattr(server, "_notebooklm_mcp_config", None)
    if isinstance(config, MCPConfig):
        return config
    return fallback


def _ensure_reset_allowed(config: MCPConfig, *, confirm: bool) -> None:
    if not config.enable_destructive_tools:
        raise ValidationError(
            "Chat settings reset is disabled. Set "
            "NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1 to enable destructive tools."
        )
    if confirm is not True:
        raise ValidationError("confirm must be true to reset settings.")


def _parse_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in {"patch", "set"}:
        raise ValidationError("mode must be one of: patch, set.")
    return normalized


def _parse_goal(value: str | None) -> ChatGoal | object:
    if value is None:
        return UNSET
    return map_to_enum(value, ChatGoal, field_name="goal")


def _parse_response_length(value: str | None) -> ChatResponseLength | object:
    if value is None:
        return UNSET
    return map_to_enum(value, ChatResponseLength, field_name="response_length")


def _parse_optional_prompt(value: str | None, *, field: str) -> str | None | object:
    if value == _UNSET_PROMPT_SENTINEL:
        return UNSET
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string or null.")
    return value


def _serialize_settings(settings: ChatSettings) -> dict[str, Any]:
    goal = map_from_enum(settings.goal)
    response_length = map_from_enum(settings.response_length)
    custom_prompt = settings.custom_prompt

    payload: dict[str, Any] = {
        "goal": goal,
        "response_length": response_length,
        "custom_prompt_set": custom_prompt is not None,
        "fingerprint": fingerprint_settings(goal, response_length, custom_prompt),
    }
    if custom_prompt is not None:
        payload["custom_prompt_len"] = len(custom_prompt)
    return payload


def _resolve_set_payload(
    *,
    goal: str | None,
    response_length: str | None,
    custom_prompt: str | None,
) -> ChatSettings:
    goal_enum = (
        ChatGoal.DEFAULT
        if goal is None
        else map_to_enum(goal, ChatGoal, field_name="goal")
    )
    response_length_enum = (
        ChatResponseLength.DEFAULT
        if response_length is None
        else map_to_enum(response_length, ChatResponseLength, field_name="response_length")
    )

    if custom_prompt == _UNSET_PROMPT_SENTINEL:
        prompt = None
    elif custom_prompt is None:
        prompt = None
    elif isinstance(custom_prompt, str):
        prompt = custom_prompt
    else:
        raise ValidationError("custom_prompt must be a string or null.")

    return ChatSettings(
        goal=goal_enum,
        response_length=response_length_enum,
        custom_prompt=prompt,
        source="server",
    )


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


def register_chat_settings_tools(server: Any) -> dict[str, Callable[..., Any]]:
    """Register chat-settings tools and return handlers keyed by tool name."""
    fallback_config = load_config()

    @handle_mcp_errors
    async def notebooklm_settings_get(ctx: MCPContext, notebook_id: str) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            settings = await app.client.chat.get_settings(clean_notebook_id, strict=False)
        return make_tool_result(_serialize_settings(settings))

    @handle_mcp_errors
    async def notebooklm_settings_patch(
        ctx: MCPContext,
        notebook_id: str,
        mode: str = "patch",
        goal: str | None = None,
        response_length: str | None = None,
        custom_prompt: str | None = _UNSET_PROMPT_SENTINEL,
        strict: bool = True,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        app = _resolve_app_context(ctx)
        selected_mode = _parse_mode(mode)

        if selected_mode == "patch":
            goal_value = _parse_goal(goal)
            response_length_value = _parse_response_length(response_length)
            custom_prompt_value = _parse_optional_prompt(
                custom_prompt,
                field="custom_prompt",
            )
            async with app.acquire_slot():
                after = await app.client.chat.update_settings(
                    clean_notebook_id,
                    goal=goal_value,
                    response_length=response_length_value,
                    custom_prompt=custom_prompt_value,
                    strict=strict,
                )
        else:
            target = _resolve_set_payload(
                goal=goal,
                response_length=response_length,
                custom_prompt=custom_prompt,
            )
            async with app.acquire_slot():
                await app.client.chat.set_settings(clean_notebook_id, target)
                after = await app.client.chat.get_settings(clean_notebook_id, strict=False)

        return make_tool_result(
            {
                "success": True,
                "after": _serialize_settings(after),
            }
        )

    @handle_mcp_errors
    async def notebooklm_settings_reset(
        ctx: MCPContext,
        notebook_id: str,
        confirm: bool,
    ) -> dict[str, Any]:
        config = _resolve_runtime_config(ctx, fallback=fallback_config)
        _ensure_reset_allowed(config, confirm=confirm)
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            await app.client.chat.reset_settings(clean_notebook_id)
            after = await app.client.chat.get_settings(clean_notebook_id, strict=False)
        return make_tool_result(
            {
                "success": True,
                "after": _serialize_settings(after),
            }
        )

    handlers: dict[str, Callable[..., Any]] = {
        "notebooklm_settings_get": notebooklm_settings_get,
        "notebooklm_settings_patch": notebooklm_settings_patch,
        "notebooklm_settings_reset": notebooklm_settings_reset,
    }

    descriptions = {
        "notebooklm_settings_get": (
            "Read notebook chat settings without exposing custom prompt text."
        ),
        "notebooklm_settings_patch": (
            "Patch or set notebook chat settings (goal, response length, custom prompt)."
        ),
        "notebooklm_settings_reset": (
            "Reset notebook chat settings to defaults. Requires confirm=true and "
            "destructive tools enabled."
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


__all__ = ["register_chat_settings_tools"]
