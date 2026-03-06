"""MCP chat and conversation tools."""

from __future__ import annotations

import contextlib
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any


from notebooklm.exceptions import ConfigurationError, ValidationError
from notebooklm.types import ChatReference, Source

from .._errors import handle_mcp_errors
from .._result import make_tool_result


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


def _format_reference_location(reference: ChatReference) -> str | None:
    if reference.start_char is None and reference.end_char is None:
        return None
    if reference.start_char is not None and reference.end_char is not None:
        return f"{reference.start_char}-{reference.end_char}"
    if reference.start_char is not None:
        return str(reference.start_char)
    return str(reference.end_char)


async def _source_metadata_by_id(
    app_context: Any,
    notebook_id: str,
    source_ids: set[str],
) -> dict[str, Source]:
    if not source_ids:
        return {}

    async with _acquire_slot(app_context):
        sources = await app_context.client.sources.list(notebook_id)
    return {source.id: source for source in sources if source.id in source_ids}


def _citations_from_references(
    references: list[ChatReference],
    metadata: dict[str, Source],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []

    for reference in references:
        citation: dict[str, Any] = {"source_id": reference.source_id}
        source = metadata.get(reference.source_id)

        if source is not None and source.title:
            citation["title"] = source.title
        if source is not None and source.url:
            citation["url"] = source.url
        if reference.cited_text:
            citation["quote"] = reference.cited_text

        location = _format_reference_location(reference)
        if location is not None:
            citation["location"] = location

        citations.append(citation)

    return citations


def _quotes_from_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    quotes: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()

    for citation in citations:
        source_id = str(citation.get("source_id", ""))
        text = str(citation.get("quote", "") or "")
        location = citation.get("location")
        dedupe_key = (source_id, text, location if isinstance(location, str) else None)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        quote: dict[str, Any] = {
            "source_id": source_id,
            "text": text,
        }
        if isinstance(citation.get("title"), str):
            quote["title"] = citation["title"]
        if isinstance(location, str):
            quote["location"] = location
        if isinstance(citation.get("url"), str):
            quote["url"] = citation["url"]
        quotes.append(quote)

    return quotes


@handle_mcp_errors
async def notebooklm_chat_ask(
    ctx: MCPContext,
    notebook_id: str,
    question: str,
    source_ids: list[str] | None = None,
    conversation_id: str | None = None,
    save_as_note: bool = False,
    note_title: str | None = None,
) -> dict[str, Any]:
    """Ask a notebook question and return answer + citations."""
    app_context = _get_app_context(ctx)

    async with _acquire_slot(app_context):
        result = await app_context.client.chat.ask(
            notebook_id,
            question,
            source_ids=source_ids,
            conversation_id=conversation_id,
        )

    reference_source_ids = {reference.source_id for reference in result.references}
    metadata = await _source_metadata_by_id(app_context, notebook_id, reference_source_ids)
    citations = _citations_from_references(result.references, metadata)

    payload: dict[str, Any] = {
        "answer": result.answer,
        "citations": citations,
        "conversation_id": result.conversation_id,
    }

    if save_as_note:
        if result.answer.strip():
            effective_title = (
                note_title.strip()
                if isinstance(note_title, str) and note_title.strip()
                else f"Chat: {question[:50]}"
            )
            async with _acquire_slot(app_context):
                note = await app_context.client.notes.create(
                    notebook_id,
                    effective_title,
                    result.answer,
                )
            payload["note_saved"] = True
            payload["note_id"] = getattr(note, "id", None)
        else:
            payload["note_saved"] = False

    return make_tool_result(payload)


@handle_mcp_errors
async def notebooklm_chat_find_quotes(
    ctx: MCPContext,
    notebook_id: str,
    query: str,
    source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Find cited quote snippets relevant to a query."""
    app_context = _get_app_context(ctx)
    prompt = f"Find direct quotes that best answer: {query}"

    async with _acquire_slot(app_context):
        result = await app_context.client.chat.ask(
            notebook_id,
            prompt,
            source_ids=source_ids,
            conversation_id=None,
        )

    reference_source_ids = {reference.source_id for reference in result.references}
    metadata = await _source_metadata_by_id(app_context, notebook_id, reference_source_ids)
    citations = _citations_from_references(result.references, metadata)
    quotes = _quotes_from_citations(citations)

    return make_tool_result({"quotes": quotes})


@handle_mcp_errors
async def notebooklm_chat_summarize_sources(
    ctx: MCPContext,
    notebook_id: str,
    source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize selected or all notebook sources with citations."""
    app_context = _get_app_context(ctx)
    question = "Summarize the selected sources and cite the most important evidence."
    if not source_ids:
        question = "Summarize all notebook sources and cite the most important evidence."

    async with _acquire_slot(app_context):
        result = await app_context.client.chat.ask(
            notebook_id,
            question,
            source_ids=source_ids,
            conversation_id=None,
        )

    reference_source_ids = {reference.source_id for reference in result.references}
    metadata = await _source_metadata_by_id(app_context, notebook_id, reference_source_ids)
    citations = _citations_from_references(result.references, metadata)

    return make_tool_result(
        {
            "summary": result.answer,
            "citations": citations,
            "conversation_id": result.conversation_id,
        }
    )


@handle_mcp_errors
async def notebooklm_chat_get_conversation(
    ctx: MCPContext,
    notebook_id: str,
    conversation_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return conversation history as ordered user/assistant turns."""
    app_context = _get_app_context(ctx)
    resolved_limit = _coerce_positive_int(limit, field_name="limit", default=20)

    resolved_conversation_id = conversation_id
    if resolved_conversation_id is None:
        async with _acquire_slot(app_context):
            resolved_conversation_id = await app_context.client.chat.get_conversation_id(notebook_id)

    if not resolved_conversation_id:
        return make_tool_result({"turns": []})

    async with _acquire_slot(app_context):
        qa_pairs = await app_context.client.chat.get_history(
            notebook_id,
            limit=resolved_limit,
            conversation_id=resolved_conversation_id,
        )

    turns: list[dict[str, Any]] = []
    for question, answer in qa_pairs:
        turns.append({"role": "user", "content": question})
        turns.append({"role": "assistant", "content": answer})

    return make_tool_result(
        {
            "turns": turns,
            "conversation_id": resolved_conversation_id,
        }
    )


def register_chat_tools(server: Any) -> None:
    """Register chat tools with a FastMCP-like server instance."""
    tool = getattr(server, "tool", None)
    if not callable(tool):
        return

    registrations = (
        ("notebooklm_chat_ask", notebooklm_chat_ask, "Ask notebook questions with citations"),
        ("notebooklm_chat_find_quotes", notebooklm_chat_find_quotes, "Find quote snippets"),
        (
            "notebooklm_chat_summarize_sources",
            notebooklm_chat_summarize_sources,
            "Summarize sources with citations",
        ),
        (
            "notebooklm_chat_get_conversation",
            notebooklm_chat_get_conversation,
            "Get conversation history turns",
        ),
    )

    for name, fn, description in registrations:
        decorator = tool(name=name, description=description)
        decorator(fn)


__all__ = [
    "notebooklm_chat_ask",
    "notebooklm_chat_find_quotes",
    "notebooklm_chat_get_conversation",
    "notebooklm_chat_summarize_sources",
    "register_chat_tools",
]
