"""Notebook lifecycle MCP tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any


from notebooklm._notebooks import _delete_notebook_rpc, _rename_notebook_rpc
from notebooklm.exceptions import ValidationError
from notebooklm.types import Notebook, NotebookDescription

from .._config import MCPConfig, load_config
from .._errors import handle_mcp_errors
from .._result import make_tool_result
from ..server import AppContext

logger = logging.getLogger("notebooklm_mcp.tools.notebooks")


def _resolve_app_context(ctx: MCPContext) -> AppContext:
    request_context = getattr(ctx, "request_context", None)
    app = getattr(request_context, "lifespan_context", None)
    if app is None:
        app = getattr(ctx, "lifespan_context", None)
    if isinstance(app, AppContext):
        return app
    raise RuntimeError("NotebookLM MCP lifespan context is unavailable.")


def _resolve_runtime_config(ctx: MCPContext, fallback: MCPConfig) -> MCPConfig:
    request_context = getattr(ctx, "request_context", None)
    server = getattr(request_context, "server", None)
    config = getattr(server, "_notebooklm_mcp_config", None)
    if isinstance(config, MCPConfig):
        return config
    return fallback


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value.strip()


def _ensure_delete_allowed(config: MCPConfig, *, confirm: bool) -> None:
    if not config.enable_destructive_tools:
        raise ValidationError(
            "Notebook deletion is disabled. Set "
            "NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1 to enable destructive tools."
        )
    if confirm is not True:
        raise ValidationError("confirm must be true to delete a notebook.")


def _serialize_notebook(notebook: Notebook) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "notebook_id": notebook.id,
        "title": notebook.title,
        "source_count": notebook.sources_count,
    }
    if notebook.created_at is not None:
        payload["created_at"] = notebook.created_at
    return payload


def _serialize_summary(description: NotebookDescription, source_count: int) -> dict[str, Any]:
    return {
        "description": description.summary,
        "source_count": source_count,
        "suggested_topics": [
            {
                "question": topic.question,
                "prompt": topic.prompt,
            }
            for topic in description.suggested_topics
        ],
    }


async def _rename_notebook(client: Any, notebook_id: str, title: str) -> Notebook:
    rename = getattr(getattr(client, "notebooks", None), "rename", None)
    if rename is not None:
        try:
            return await rename(notebook_id, title)
        except TypeError:
            if not hasattr(client, "_core"):
                raise
    return await _rename_notebook_rpc(client._core, notebook_id, title)


async def _delete_notebook(client: Any, notebook_id: str) -> bool:
    delete = getattr(getattr(client, "notebooks", None), "delete", None)
    if delete is not None:
        try:
            return bool(await delete(notebook_id))
        except TypeError:
            if not hasattr(client, "_core"):
                raise
    return await _delete_notebook_rpc(client._core, notebook_id)


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


def register_notebook_tools(server: Any) -> dict[str, Callable[..., Any]]:
    """Register notebook lifecycle tools and return handlers keyed by tool name."""
    fallback_config = load_config()

    @handle_mcp_errors
    async def notebooklm_notebooks_list(ctx: MCPContext) -> dict[str, Any]:
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            notebooks = await app.client.notebooks.list()
        return make_tool_result({"notebooks": [_serialize_notebook(nb) for nb in notebooks]})

    @handle_mcp_errors
    async def notebooklm_notebooks_create(ctx: MCPContext, title: str) -> dict[str, Any]:
        clean_title = _require_text(title, field="title")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            notebook = await app.client.notebooks.create(clean_title)
        return make_tool_result(
            {
                "notebook_id": notebook.id,
                "title": notebook.title,
            }
        )

    @handle_mcp_errors
    async def notebooklm_notebooks_rename(
        ctx: MCPContext,
        notebook_id: str,
        title: str,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_title = _require_text(title, field="title")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            renamed = await _rename_notebook(app.client, clean_notebook_id, clean_title)
        return make_tool_result(
            {
                "success": True,
                "notebook": _serialize_notebook(renamed),
            }
        )

    @handle_mcp_errors
    async def notebooklm_notebooks_delete(
        ctx: MCPContext,
        notebook_id: str,
        confirm: bool,
    ) -> dict[str, Any]:
        config = _resolve_runtime_config(ctx, fallback_config)
        _ensure_delete_allowed(config, confirm=confirm)
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            success = await _delete_notebook(app.client, clean_notebook_id)
        return make_tool_result({"success": bool(success)})

    @handle_mcp_errors
    async def notebooklm_notebooks_get_summary(
        ctx: MCPContext,
        notebook_id: str,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            description = await app.client.notebooks.get_description(clean_notebook_id)
            sources = await app.client.sources.list(clean_notebook_id)
        return make_tool_result(
            {
                "summary": _serialize_summary(description, source_count=len(sources)),
            }
        )

    handlers: dict[str, Callable[..., Any]] = {
        "notebooklm_notebooks_list": notebooklm_notebooks_list,
        "notebooklm_notebooks_create": notebooklm_notebooks_create,
        "notebooklm_notebooks_rename": notebooklm_notebooks_rename,
        "notebooklm_notebooks_delete": notebooklm_notebooks_delete,
        "notebooklm_notebooks_get_summary": notebooklm_notebooks_get_summary,
    }

    descriptions = {
        "notebooklm_notebooks_list": (
            "List notebooks available to the authenticated NotebookLM account."
        ),
        "notebooklm_notebooks_create": "Create a new notebook with the provided title.",
        "notebooklm_notebooks_rename": "Rename an existing notebook.",
        "notebooklm_notebooks_delete": (
            "Delete a notebook. Requires confirm=true and destructive tools enabled."
        ),
        "notebooklm_notebooks_get_summary": (
            "Return notebook summary text and suggested topics with source count."
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


__all__ = ["register_notebook_tools"]
