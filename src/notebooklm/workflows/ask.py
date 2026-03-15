"""Internal workflow helpers for the retained `ask` command."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from notebooklm.types import AskResult

from .runtime import (
    LookupCurrentValue,
    NotebookTargetCandidate,
    NotebookTargetResolution,
    NoticeCallback,
    ResolveNotebookId,
    ResolveSourceIds,
    resolve_notebook_target,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AskWorkflowResult:
    """Result of preparing and executing one retained ask workflow call."""

    result: AskResult
    resolved_notebook_id: str
    resolved_source_ids: list[str] | None
    resumed_from_server: bool


def determine_conversation_id(
    *,
    explicit_conversation_id: str | None,
    explicit_notebook_id: str | None,
    resolved_notebook_id: str,
    json_output: bool,
    get_current_notebook: LookupCurrentValue,
    get_current_conversation: LookupCurrentValue,
    emit_notice: NoticeCallback | None = None,
) -> str | None:
    """Choose the conversation to continue for the ask workflow."""
    if explicit_conversation_id:
        return explicit_conversation_id

    cached_notebook = get_current_notebook()
    if explicit_notebook_id and cached_notebook and resolved_notebook_id != cached_notebook:
        if emit_notice is not None and not json_output:
            emit_notice("Different notebook specified, starting new conversation...")
        return None

    return get_current_conversation()


async def get_latest_conversation_from_server(
    client: Any,
    notebook_id: str,
    *,
    json_output: bool,
    emit_notice: NoticeCallback | None = None,
) -> str | None:
    """Fetch the latest server-backed conversation for one notebook."""
    try:
        conversation_id = await client.chat.get_conversation_id(notebook_id)
        if conversation_id:
            if emit_notice is not None and not json_output:
                emit_notice(f"Continuing conversation {conversation_id[:8]}...")
            return conversation_id
    except Exception as exc:
        logger.debug(
            "Failed to fetch last conversation (%s): %s",
            type(exc).__name__,
            exc,
        )
        if emit_notice is not None and not json_output:
            emit_notice("Starting new conversation (history unavailable)")
    return None


async def run_ask_workflow(
    client: Any,
    *,
    question: str,
    notebook_id: str,
    resolved_notebook_id: str | None = None,
    explicit_notebook_id: str | None,
    conversation_id: str | None,
    source_ids: tuple[str, ...],
    json_output: bool,
    resolve_notebook_id: ResolveNotebookId,
    resolve_source_ids: ResolveSourceIds,
    get_current_notebook: LookupCurrentValue,
    get_current_conversation: LookupCurrentValue,
    emit_notice: NoticeCallback | None = None,
) -> AskWorkflowResult:
    """Execute the retained ask control flow through a reusable workflow helper."""
    resolved_notebook_id = resolved_notebook_id or await resolve_notebook_id(client, notebook_id)
    effective_conversation_id = determine_conversation_id(
        explicit_conversation_id=conversation_id,
        explicit_notebook_id=explicit_notebook_id,
        resolved_notebook_id=resolved_notebook_id,
        json_output=json_output,
        get_current_notebook=get_current_notebook,
        get_current_conversation=get_current_conversation,
        emit_notice=emit_notice,
    )

    resumed_from_server = False
    if not effective_conversation_id:
        effective_conversation_id = await get_latest_conversation_from_server(
            client,
            resolved_notebook_id,
            json_output=json_output,
            emit_notice=emit_notice,
        )
        resumed_from_server = effective_conversation_id is not None

    resolved_source_ids = await resolve_source_ids(client, resolved_notebook_id, source_ids)
    result = await client.chat.ask(
        resolved_notebook_id,
        question,
        source_ids=resolved_source_ids,
        conversation_id=effective_conversation_id,
    )

    return AskWorkflowResult(
        result=result,
        resolved_notebook_id=resolved_notebook_id,
        resolved_source_ids=resolved_source_ids,
        resumed_from_server=resumed_from_server,
    )


__all__ = [
    "AskWorkflowResult",
    "determine_conversation_id",
    "get_latest_conversation_from_server",
    "NotebookTargetCandidate",
    "NotebookTargetResolution",
    "resolve_notebook_target",
    "run_ask_workflow",
]
