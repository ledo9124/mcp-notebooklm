"""Resource registration for notebooklm-mcp."""

from __future__ import annotations

import json
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any


from notebooklm.exceptions import ConfigurationError, SourceNotFoundError

from ._config import load_config
from ._errors import handle_mcp_errors
from .tools.sources import _acquire_slot


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
        raise ConfigurationError("MCP resource context does not provide AppContext.client")
    return candidate


def _json_payload(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


@handle_mcp_errors
async def notebooklm_resource_notebooks(ctx: MCPContext) -> str:
    """Resolve ``notebooklm://notebooks`` resource."""
    app_context = _get_app_context(ctx)
    async with _acquire_slot(app_context):
        notebooks = await app_context.client.notebooks.list()

    items: list[dict[str, Any]] = []
    for notebook in notebooks:
        item: dict[str, Any] = {
            "notebook_id": notebook.id,
            "title": notebook.title,
            "source_count": notebook.sources_count,
        }
        if notebook.created_at is not None:
            item["created_at"] = notebook.created_at.isoformat()
        items.append(item)

    return _json_payload({"notebooks": items})


@handle_mcp_errors
async def notebooklm_resource_notebook(ctx: MCPContext, notebook_id: str) -> str:
    """Resolve ``notebooklm://notebooks/{notebook_id}`` resource."""
    app_context = _get_app_context(ctx)
    async with _acquire_slot(app_context):
        notebook = await app_context.client.notebooks.get(notebook_id)
        summary = await app_context.client.notebooks.get_summary(notebook_id)
        sources = await app_context.client.sources.list(notebook_id)

    payload: dict[str, Any] = {
        "notebook_id": notebook.id,
        "title": notebook.title,
        "source_count": len(sources),
        "summary": summary,
    }
    if notebook.created_at is not None:
        payload["created_at"] = notebook.created_at.isoformat()
    return _json_payload(payload)


@handle_mcp_errors
async def notebooklm_resource_notebook_source(
    ctx: MCPContext,
    notebook_id: str,
    source_id: str,
) -> str:
    """Resolve ``notebooklm://notebooks/{notebook_id}/sources/{source_id}`` resource."""
    app_context = _get_app_context(ctx)
    async with _acquire_slot(app_context):
        source = await app_context.client.sources.get(notebook_id, source_id)
        if source is None:
            raise SourceNotFoundError(source_id)
        fulltext = await app_context.client.sources.get_fulltext(notebook_id, source_id)

    cap = load_config().source_content_max_chars
    content = fulltext.content
    truncated = len(content) > cap
    preview = content[:cap]

    payload = {
        "source": {
            "source_id": source.id,
            "title": source.title,
            "kind": source.kind.value,
            "status": source.status,
            "url": source.url,
        },
        "content": preview,
        "truncated": truncated,
        "returned_chars": len(preview),
        "total_chars": len(content),
        "max_chars": cap,
    }
    return _json_payload(payload)


@handle_mcp_errors
async def notebooklm_resource_audit_recent(ctx: MCPContext) -> str:
    """Resolve ``notebooklm://audit/recent`` resource."""
    app_context = _get_app_context(ctx)
    audit = getattr(app_context, "audit", None)
    recent = getattr(audit, "recent", None) if audit is not None else None
    if not callable(recent):
        return _json_payload(
            {
                "enabled": False,
                "message": "Audit logging is not enabled.",
            }
        )

    entries = recent(limit=50)
    payload: list[dict[str, Any]] = []
    for entry in entries:
        to_dict = getattr(entry, "to_dict", None)
        if callable(to_dict):
            item = to_dict()
            if isinstance(item, dict):
                payload.append(item)
                continue
        if isinstance(entry, dict):
            payload.append(entry)

    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def register_resources(_server: Any) -> None:
    """Register MCP resources with the server instance."""
    resource = getattr(_server, "resource", None)
    if not callable(resource):
        return

    resource("notebooklm://notebooks")(notebooklm_resource_notebooks)
    resource("notebooklm://notebooks/{notebook_id}")(notebooklm_resource_notebook)
    resource("notebooklm://notebooks/{notebook_id}/sources/{source_id}")(
        notebooklm_resource_notebook_source
    )
    resource("notebooklm://audit/recent")(notebooklm_resource_audit_recent)


__all__ = [
    "notebooklm_resource_audit_recent",
    "notebooklm_resource_notebook",
    "notebooklm_resource_notebook_source",
    "notebooklm_resource_notebooks",
    "register_resources",
]
