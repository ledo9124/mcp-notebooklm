"""Mind-map MCP helpers with explicit optional-artifact guardrails."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any

from notebooklm.exceptions import ValidationError

from .._errors import handle_mcp_errors
from .._result import make_tool_result

logger = logging.getLogger("notebooklm_mcp.tools.mind_maps")

_MIND_MAP_GUIDANCE = (
    "Mind maps are optional note-backed aids for topic coverage and onboarding. "
    "Do not treat them as required or authoritative BA workflow outputs."
)


def _resolve_app_context(ctx: MCPContext) -> Any:
    request_context = getattr(ctx, "request_context", None)
    app = getattr(request_context, "lifespan_context", None)
    if app is None:
        app = getattr(ctx, "lifespan_context", None)
    if app is not None and hasattr(app, "client"):
        return app
    raise RuntimeError("NotebookLM MCP lifespan context is unavailable.")


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value.strip()


def _optional_text(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field=field)


def _optional_source_ids(value: Sequence[str] | None) -> list[str] | None:
    if value is None:
        return None
    return [_require_text(item, field="source_ids[]") for item in value]


def _mind_map_base_payload() -> dict[str, Any]:
    return {
        "artifact_kind": "mind_map",
        "draft_assistance_only": True,
        "authoritative_for_ba_runner": False,
        "critical_path": False,
        "note_backed": True,
        "stability": "optional_note_backed",
        "usage_guidance": _MIND_MAP_GUIDANCE,
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


def register_mind_map_tools(server: Any) -> dict[str, Callable[..., Any]]:
    """Register mind-map helper tools."""

    @handle_mcp_errors
    async def notebooklm_mind_maps_generate(
        ctx: MCPContext,
        notebook_id: str,
        source_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_source_ids = _optional_source_ids(source_ids)
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            result = await app.client.artifacts.generate_mind_map(
                clean_notebook_id,
                source_ids=clean_source_ids,
            )

        payload = _mind_map_base_payload()
        payload.update(
            {
                "notebook_id": clean_notebook_id,
                "source_ids": clean_source_ids or [],
                "mind_map": result.get("mind_map") if isinstance(result, dict) else None,
                "note_id": result.get("note_id") if isinstance(result, dict) else None,
            }
        )
        warnings = [_MIND_MAP_GUIDANCE]
        if payload["note_id"] is None:
            warnings.append("Mind map generation returned no persisted note_id.")
        if payload["mind_map"] is None:
            warnings.append("Mind map generation returned no mind_map payload.")
        payload["warnings"] = warnings
        return make_tool_result(payload)

    @handle_mcp_errors
    async def notebooklm_mind_maps_download(
        ctx: MCPContext,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_output_path = _require_text(output_path, field="output_path")
        clean_artifact_id = _optional_text(artifact_id, field="artifact_id")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            downloaded_to = await app.client.artifacts.download_mind_map(
                clean_notebook_id,
                clean_output_path,
                artifact_id=clean_artifact_id,
            )

        payload = _mind_map_base_payload()
        payload.update(
            {
                "success": True,
                "notebook_id": clean_notebook_id,
                "artifact_id": clean_artifact_id,
                "output_path": downloaded_to,
                "warnings": [_MIND_MAP_GUIDANCE],
            }
        )
        return make_tool_result(payload)

    registrations = {
        "notebooklm_mind_maps_generate": notebooklm_mind_maps_generate,
        "notebooklm_mind_maps_download": notebooklm_mind_maps_download,
    }

    _register_tool(
        server,
        name="notebooklm_mind_maps_generate",
        description="Generate an optional note-backed mind map",
        handler=notebooklm_mind_maps_generate,
    )
    _register_tool(
        server,
        name="notebooklm_mind_maps_download",
        description="Download an optional mind map artifact",
        handler=notebooklm_mind_maps_download,
    )
    return registrations


__all__ = [
    "register_mind_map_tools",
]
