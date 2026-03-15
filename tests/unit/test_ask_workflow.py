"""Unit tests for the retained ask workflow helper."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from notebooklm.types import AskResult
from notebooklm.workflows.ask import determine_conversation_id, run_ask_workflow


def _ask_result(
    *,
    answer: str = "The answer is 42.",
    conversation_id: str = "conv-001",
    is_follow_up: bool = False,
) -> AskResult:
    return AskResult(
        answer=answer,
        conversation_id=conversation_id,
        turn_number=1,
        is_follow_up=is_follow_up,
        references=[],
        raw_response="raw",
    )


def test_determine_conversation_id_prefers_explicit_value():
    selected = determine_conversation_id(
        explicit_conversation_id="conv-explicit",
        explicit_notebook_id="nb_123",
        resolved_notebook_id="nb_123",
        json_output=False,
        get_current_notebook=lambda: "nb_cached",
        get_current_conversation=lambda: "conv-cached",
    )

    assert selected == "conv-explicit"


def test_determine_conversation_id_starts_new_thread_when_user_switches_notebooks():
    notices: list[str] = []

    selected = determine_conversation_id(
        explicit_conversation_id=None,
        explicit_notebook_id="nb_new",
        resolved_notebook_id="nb_new",
        json_output=False,
        get_current_notebook=lambda: "nb_old",
        get_current_conversation=lambda: "conv-cached",
        emit_notice=notices.append,
    )

    assert selected is None
    assert notices == ["Different notebook specified, starting new conversation..."]


@pytest.mark.asyncio
async def test_run_ask_workflow_uses_cached_conversation_without_server_resume():
    client = SimpleNamespace(
        chat=SimpleNamespace(
            get_conversation_id=AsyncMock(return_value="conv-server"),
            ask=AsyncMock(return_value=_ask_result(is_follow_up=True)),
        )
    )
    resolve_notebook_id = AsyncMock(return_value="nb_123")
    resolve_source_ids = AsyncMock(return_value=["src_1", "src_2"])

    workflow_result = await run_ask_workflow(
        client,
        question="What changed?",
        notebook_id="nb_partial",
        explicit_notebook_id="nb_partial",
        conversation_id=None,
        source_ids=("src_1", "src_2"),
        json_output=False,
        resolve_notebook_id=resolve_notebook_id,
        resolve_source_ids=resolve_source_ids,
        get_current_notebook=lambda: "nb_123",
        get_current_conversation=lambda: "conv-local",
    )

    assert workflow_result.resolved_notebook_id == "nb_123"
    assert workflow_result.resolved_source_ids == ["src_1", "src_2"]
    assert workflow_result.resumed_from_server is False
    client.chat.get_conversation_id.assert_not_awaited()
    client.chat.ask.assert_awaited_once_with(
        "nb_123",
        "What changed?",
        source_ids=["src_1", "src_2"],
        conversation_id="conv-local",
    )


@pytest.mark.asyncio
async def test_run_ask_workflow_accepts_pre_resolved_notebook_id():
    client = SimpleNamespace(
        chat=SimpleNamespace(
            get_conversation_id=AsyncMock(return_value="conv-server"),
            ask=AsyncMock(return_value=_ask_result(is_follow_up=True)),
        )
    )
    resolve_notebook_id = AsyncMock(return_value="nb_should_not_be_used")

    workflow_result = await run_ask_workflow(
        client,
        question="What changed?",
        notebook_id="nb_partial",
        resolved_notebook_id="nb_123",
        explicit_notebook_id="nb_partial",
        conversation_id=None,
        source_ids=(),
        json_output=False,
        resolve_notebook_id=resolve_notebook_id,
        resolve_source_ids=AsyncMock(return_value=None),
        get_current_notebook=lambda: "nb_123",
        get_current_conversation=lambda: "conv-local",
    )

    assert workflow_result.resolved_notebook_id == "nb_123"
    resolve_notebook_id.assert_not_awaited()
    client.chat.ask.assert_awaited_once_with(
        "nb_123",
        "What changed?",
        source_ids=None,
        conversation_id="conv-local",
    )


@pytest.mark.asyncio
async def test_run_ask_workflow_resumes_from_server_when_no_local_conversation():
    notices: list[str] = []
    client = SimpleNamespace(
        chat=SimpleNamespace(
            get_conversation_id=AsyncMock(return_value="conv-server-1234"),
            ask=AsyncMock(
                return_value=_ask_result(
                    conversation_id="conv-server-1234",
                    is_follow_up=True,
                )
            ),
        )
    )

    workflow_result = await run_ask_workflow(
        client,
        question="Summarize this notebook.",
        notebook_id="nb_123",
        explicit_notebook_id="nb_123",
        conversation_id=None,
        source_ids=(),
        json_output=False,
        resolve_notebook_id=AsyncMock(return_value="nb_123"),
        resolve_source_ids=AsyncMock(return_value=None),
        get_current_notebook=lambda: "nb_123",
        get_current_conversation=lambda: None,
        emit_notice=notices.append,
    )

    assert workflow_result.resumed_from_server is True
    assert notices == ["Continuing conversation conv-ser..."]
    client.chat.get_conversation_id.assert_awaited_once_with("nb_123")
    client.chat.ask.assert_awaited_once_with(
        "nb_123",
        "Summarize this notebook.",
        source_ids=None,
        conversation_id="conv-server-1234",
    )


@pytest.mark.asyncio
async def test_run_ask_workflow_falls_back_to_new_conversation_after_resume_lookup_error():
    notices: list[str] = []
    client = SimpleNamespace(
        chat=SimpleNamespace(
            get_conversation_id=AsyncMock(side_effect=RuntimeError("boom")),
            ask=AsyncMock(return_value=_ask_result()),
        )
    )

    workflow_result = await run_ask_workflow(
        client,
        question="Start over",
        notebook_id="nb_123",
        explicit_notebook_id="nb_123",
        conversation_id=None,
        source_ids=(),
        json_output=False,
        resolve_notebook_id=AsyncMock(return_value="nb_123"),
        resolve_source_ids=AsyncMock(return_value=None),
        get_current_notebook=lambda: "nb_123",
        get_current_conversation=lambda: None,
        emit_notice=notices.append,
    )

    assert workflow_result.resumed_from_server is False
    assert notices == ["Starting new conversation (history unavailable)"]
    client.chat.ask.assert_awaited_once_with(
        "nb_123",
        "Start over",
        source_ids=None,
        conversation_id=None,
    )
