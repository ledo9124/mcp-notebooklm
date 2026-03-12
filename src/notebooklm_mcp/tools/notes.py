"""MCP note-management and curated note-to-source tools."""

from __future__ import annotations

import contextlib
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any

from notebooklm.exceptions import ConfigurationError, ValidationError
from notebooklm.rpc.types import source_status_to_str
from notebooklm.types import Note, Source

from .._config import MCPConfig, load_config
from .._errors import handle_mcp_errors
from .._result import make_tool_result

_CURATION_KIND_TO_SOURCE_TYPE = {
    "clarification": "SUPPORTING_CLARIFICATION",
    "decision": "SUPPORTING_DECISION",
}


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


def _require_text(value: str | None, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name=field_name)


def _coerce_bool(value: bool | None, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValidationError(f"{field_name} must be a boolean")
    return value


def _coerce_positive_int(value: int | None, *, field_name: str, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValidationError(f"{field_name} must be a positive integer")
    return value


def _coerce_curation_kind(value: str) -> str:
    kind = _require_text(value, field_name="curation_kind").lower()
    if kind not in _CURATION_KIND_TO_SOURCE_TYPE:
        raise ValidationError("curation_kind must be one of: clarification, decision")
    return kind


def _note_to_summary(note: Note, *, include_content: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "note_id": note.id,
        "title": note.title,
    }
    if note.created_at is not None:
        payload["created_at"] = note.created_at.isoformat()
    if include_content:
        payload["content"] = note.content
    else:
        payload["content_preview"] = note.content[:200]
        payload["content_length"] = len(note.content)
    return payload


def _source_to_summary(source: Source) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_id": source.id,
        "title": source.title,
        "status": source_status_to_str(source.status),
        "ready": source.is_ready,
    }
    if source.kind is not None:
        payload["kind"] = source.kind.value
    return payload


async def _get_note_or_raise(app_context: Any, notebook_id: str, note_id: str) -> Note:
    async with _acquire_slot(app_context):
        note = await app_context.client.notes.get(notebook_id, note_id)
    if note is None:
        raise ValidationError(f"note_id not found: {note_id}")
    return note


@handle_mcp_errors
async def notebooklm_notes_list(ctx: MCPContext, notebook_id: str) -> dict[str, Any]:
    """List notebook notes."""
    app_context = _get_app_context(ctx)
    clean_notebook_id = _require_text(notebook_id, field_name="notebook_id")
    async with _acquire_slot(app_context):
        notes = await app_context.client.notes.list(clean_notebook_id)
    return make_tool_result({"notes": [_note_to_summary(note, include_content=False) for note in notes]})


@handle_mcp_errors
async def notebooklm_notes_get(ctx: MCPContext, notebook_id: str, note_id: str) -> dict[str, Any]:
    """Get a single notebook note."""
    app_context = _get_app_context(ctx)
    clean_notebook_id = _require_text(notebook_id, field_name="notebook_id")
    clean_note_id = _require_text(note_id, field_name="note_id")
    note = await _get_note_or_raise(app_context, clean_notebook_id, clean_note_id)
    return make_tool_result({"note": _note_to_summary(note, include_content=True)})


@handle_mcp_errors
async def notebooklm_notes_create(
    ctx: MCPContext,
    notebook_id: str,
    title: str,
    content: str = "",
) -> dict[str, Any]:
    """Create a notebook note."""
    app_context = _get_app_context(ctx)
    clean_notebook_id = _require_text(notebook_id, field_name="notebook_id")
    clean_title = _require_text(title, field_name="title")
    if not isinstance(content, str):
        raise ValidationError("content must be a string")

    async with _acquire_slot(app_context):
        note = await app_context.client.notes.create(clean_notebook_id, clean_title, content)
    return make_tool_result({"note": _note_to_summary(note, include_content=True)})


@handle_mcp_errors
async def notebooklm_notes_save(
    ctx: MCPContext,
    notebook_id: str,
    note_id: str,
    title: str | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    """Update note title and/or content."""
    app_context = _get_app_context(ctx)
    clean_notebook_id = _require_text(notebook_id, field_name="notebook_id")
    clean_note_id = _require_text(note_id, field_name="note_id")
    clean_title = _optional_text(title, field_name="title")
    if content is not None and not isinstance(content, str):
        raise ValidationError("content must be a string")
    if clean_title is None and content is None:
        raise ValidationError("Provide title and/or content")

    existing = await _get_note_or_raise(app_context, clean_notebook_id, clean_note_id)
    next_title = clean_title or existing.title or "Untitled"
    next_content = existing.content if content is None else content

    async with _acquire_slot(app_context):
        await app_context.client.notes.update(
            clean_notebook_id,
            clean_note_id,
            content=next_content,
            title=next_title,
        )

    return make_tool_result(
        {
            "note": {
                "note_id": clean_note_id,
                "title": next_title,
                "content": next_content,
            }
        }
    )


@handle_mcp_errors
async def notebooklm_notes_delete(
    ctx: MCPContext,
    notebook_id: str,
    note_id: str,
    confirm: bool,
) -> dict[str, Any]:
    """Delete a notebook note when destructive tools are enabled and confirmed."""
    app_context = _get_app_context(ctx)
    config = _resolve_runtime_config(ctx, fallback=load_config())
    if not config.enable_destructive_tools:
        raise ValidationError(
            "Note deletion is disabled. Set NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1 to enable."
        )
    if confirm is not True:
        raise ValidationError("confirm=true is required for note deletion")

    clean_notebook_id = _require_text(notebook_id, field_name="notebook_id")
    clean_note_id = _require_text(note_id, field_name="note_id")
    async with _acquire_slot(app_context):
        await app_context.client.notes.delete(clean_notebook_id, clean_note_id)
    return make_tool_result({"success": True})


@handle_mcp_errors
async def notebooklm_notes_create_curated_source(
    ctx: MCPContext,
    notebook_id: str,
    curation_kind: str,
    note_id: str | None = None,
    title: str | None = None,
    content: str | None = None,
    create_note: bool = True,
    wait: bool = False,
    wait_timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Create a note-backed curated source for clarification or decision capture."""
    app_context = _get_app_context(ctx)
    clean_notebook_id = _require_text(notebook_id, field_name="notebook_id")
    clean_curation_kind = _coerce_curation_kind(curation_kind)
    should_create_note = _coerce_bool(create_note, field_name="create_note", default=True)
    resolved_wait = _coerce_bool(wait, field_name="wait", default=False)
    resolved_wait_timeout_ms = _coerce_positive_int(
        wait_timeout_ms,
        field_name="wait_timeout_ms",
        default=120_000,
    )

    clean_note_id = _optional_text(note_id, field_name="note_id")
    clean_title = _optional_text(title, field_name="title")
    if content is not None and not isinstance(content, str):
        raise ValidationError("content must be a string")

    note: Note | None = None
    if clean_note_id is not None:
        note = await _get_note_or_raise(app_context, clean_notebook_id, clean_note_id)
    else:
        if clean_title is None or not isinstance(content, str) or not content.strip():
            raise ValidationError(
                "Provide note_id or provide both title and non-empty content for curated source capture"
            )
        if should_create_note:
            async with _acquire_slot(app_context):
                note = await app_context.client.notes.create(clean_notebook_id, clean_title, content)
        else:
            note = Note(
                id="",
                notebook_id=clean_notebook_id,
                title=clean_title,
                content=content,
            )

    source_title = note.title or clean_title or "Curated Note Source"
    source_content = note.content
    if not source_content.strip():
        raise ValidationError("Curated note content must be non-empty before converting to a source")

    async with _acquire_slot(app_context):
        source = await app_context.client.sources.add_text(
            clean_notebook_id,
            source_title,
            source_content,
            wait=resolved_wait,
            wait_timeout=resolved_wait_timeout_ms / 1000.0,
        )

    warnings = [
        "This creates a synthesized text source from note content; NotebookLM does not expose a first-class note conversion API.",
        "Treat note-derived sources as supporting clarification or decision evidence, not as replacements for primary requirement sources.",
    ]

    return make_tool_result(
        {
            "note": None if not note.id else _note_to_summary(note, include_content=True),
            "source": _source_to_summary(source),
            "source_origin": "note",
            "curation_kind": clean_curation_kind,
            "source_type_hint": _CURATION_KIND_TO_SOURCE_TYPE[clean_curation_kind],
            "warnings": warnings,
        }
    )


def register_notes_tools(server: Any) -> None:
    """Register note tools with a FastMCP-like server instance."""
    tool = getattr(server, "tool", None)
    if not callable(tool):
        return

    registrations = (
        ("notebooklm_notes_list", notebooklm_notes_list, "List notebook notes"),
        ("notebooklm_notes_get", notebooklm_notes_get, "Get notebook note content"),
        ("notebooklm_notes_create", notebooklm_notes_create, "Create notebook note"),
        ("notebooklm_notes_save", notebooklm_notes_save, "Update notebook note content"),
        ("notebooklm_notes_delete", notebooklm_notes_delete, "Delete notebook note (destructive)"),
        (
            "notebooklm_notes_create_curated_source",
            notebooklm_notes_create_curated_source,
            "Create a clarification/decision source from note content",
        ),
    )

    for name, fn, description in registrations:
        decorator = tool(name=name, description=description)
        decorator(fn)


__all__ = [
    "notebooklm_notes_create",
    "notebooklm_notes_create_curated_source",
    "notebooklm_notes_delete",
    "notebooklm_notes_get",
    "notebooklm_notes_list",
    "notebooklm_notes_save",
    "register_notes_tools",
]
