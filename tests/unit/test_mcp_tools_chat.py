"""Unit tests for notebooklm_mcp.tools.chat."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from notebooklm.types import AskResult, ChatReference, Source
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.tools import chat as chat_tools


class _AcquireSlot:
    def __init__(self, app: "_FakeAppContext") -> None:
        self._app = app

    async def __aenter__(self) -> None:
        self._app.slot_entries += 1
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@dataclass
class _FakeAppContext:
    client: Any
    slot_entries: int = 0

    def acquire_slot(self) -> _AcquireSlot:
        return _AcquireSlot(self)


def _ctx(app_context: _FakeAppContext) -> Any:
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app_context))


def _structured(result: dict[str, Any]) -> dict[str, Any]:
    return result["structuredContent"]


@pytest.mark.asyncio
async def test_notebooklm_chat_ask_returns_citations_and_saves_note() -> None:
    long_answer = "A" * 4096
    seen: dict[str, Any] = {}

    class _ChatAPI:
        async def ask(
            self,
            notebook_id: str,
            question: str,
            source_ids: list[str] | None = None,
            conversation_id: str | None = None,
        ) -> AskResult:
            seen["ask"] = (notebook_id, question, source_ids, conversation_id)
            return AskResult(
                answer=long_answer,
                conversation_id="conv-1",
                turn_number=1,
                is_follow_up=False,
                references=[
                    ChatReference(
                        source_id="src-1",
                        cited_text="Quoted passage",
                        start_char=10,
                        end_char=45,
                    )
                ],
            )

    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Source]:
            assert notebook_id == "nb-1"
            return [
                Source(id="src-1", title="Doc One", url="https://example.com/doc-1"),
            ]

    class _NotesAPI:
        async def create(self, notebook_id: str, title: str, content: str) -> Any:
            seen["note"] = (notebook_id, title, content)
            return SimpleNamespace(id="note-1", title=title)

    app = _FakeAppContext(
        client=SimpleNamespace(chat=_ChatAPI(), sources=_SourcesAPI(), notes=_NotesAPI())
    )
    result = await chat_tools.notebooklm_chat_ask(
        _ctx(app),
        notebook_id="nb-1",
        question="What matters?",
        source_ids=["src-1"],
        conversation_id="conv-seed",
        save_as_note=True,
        note_title="Saved answer",
    )

    payload = _structured(result)
    assert payload["answer"] == long_answer
    assert payload["conversation_id"] == "conv-1"
    assert payload["note_saved"] is True
    assert payload["note_id"] == "note-1"
    assert payload["citations"] == [
        {
            "source_id": "src-1",
            "title": "Doc One",
            "quote": "Quoted passage",
            "location": "10-45",
            "url": "https://example.com/doc-1",
        }
    ]
    assert seen["ask"] == ("nb-1", "What matters?", ["src-1"], "conv-seed")
    assert seen["note"] == ("nb-1", "Saved answer", long_answer)
    assert app.slot_entries == 3


@pytest.mark.asyncio
async def test_notebooklm_chat_find_quotes_returns_deduplicated_quotes() -> None:
    class _ChatAPI:
        async def ask(
            self,
            notebook_id: str,
            question: str,
            source_ids: list[str] | None = None,
            conversation_id: str | None = None,
        ) -> AskResult:
            assert notebook_id == "nb-1"
            assert "Find direct quotes that best answer:" in question
            assert source_ids == ["src-1"]
            assert conversation_id is None
            return AskResult(
                answer="",
                conversation_id="conv-1",
                turn_number=1,
                is_follow_up=False,
                references=[
                    ChatReference(source_id="src-1", cited_text="Same quote"),
                    ChatReference(source_id="src-1", cited_text="Same quote"),
                    ChatReference(source_id="src-2", cited_text="Other quote", start_char=5),
                ],
            )

    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Source]:
            assert notebook_id == "nb-1"
            return [
                Source(id="src-1", title="Doc One", url="https://example.com/doc-1"),
                Source(id="src-2", title="Doc Two"),
            ]

    app = _FakeAppContext(client=SimpleNamespace(chat=_ChatAPI(), sources=_SourcesAPI()))
    result = await chat_tools.notebooklm_chat_find_quotes(
        _ctx(app),
        notebook_id="nb-1",
        query="find pricing constraints",
        source_ids=["src-1"],
    )

    payload = _structured(result)
    assert payload["quotes"] == [
        {
            "source_id": "src-1",
            "title": "Doc One",
            "text": "Same quote",
            "url": "https://example.com/doc-1",
        },
        {
            "source_id": "src-2",
            "title": "Doc Two",
            "text": "Other quote",
            "location": "5",
        },
    ]
    assert app.slot_entries == 2


@pytest.mark.asyncio
async def test_notebooklm_chat_summarize_sources_returns_summary_and_citations() -> None:
    class _ChatAPI:
        async def ask(
            self,
            notebook_id: str,
            question: str,
            source_ids: list[str] | None = None,
            conversation_id: str | None = None,
        ) -> AskResult:
            assert notebook_id == "nb-1"
            assert "Summarize the selected sources" in question
            assert source_ids == ["src-1"]
            assert conversation_id is None
            return AskResult(
                answer="Summary text",
                conversation_id="conv-summary",
                turn_number=1,
                is_follow_up=False,
                references=[ChatReference(source_id="src-1", cited_text="Evidence")],
            )

    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Source]:
            assert notebook_id == "nb-1"
            return [Source(id="src-1", title="Doc One")]

    app = _FakeAppContext(client=SimpleNamespace(chat=_ChatAPI(), sources=_SourcesAPI()))
    result = await chat_tools.notebooklm_chat_summarize_sources(
        _ctx(app),
        notebook_id="nb-1",
        source_ids=["src-1"],
    )

    payload = _structured(result)
    assert payload["summary"] == "Summary text"
    assert payload["conversation_id"] == "conv-summary"
    assert payload["citations"] == [
        {"source_id": "src-1", "title": "Doc One", "quote": "Evidence"}
    ]
    assert app.slot_entries == 2


@pytest.mark.asyncio
async def test_notebooklm_chat_get_conversation_uses_latest_id_when_missing() -> None:
    class _ChatAPI:
        async def get_conversation_id(self, notebook_id: str) -> str | None:
            assert notebook_id == "nb-1"
            return "conv-latest"

        async def get_history(
            self,
            notebook_id: str,
            limit: int = 100,
            conversation_id: str | None = None,
        ) -> list[tuple[str, str]]:
            assert notebook_id == "nb-1"
            assert limit == 2
            assert conversation_id == "conv-latest"
            return [("Q1", "A1"), ("Q2", "A2")]

    app = _FakeAppContext(client=SimpleNamespace(chat=_ChatAPI()))
    result = await chat_tools.notebooklm_chat_get_conversation(
        _ctx(app),
        notebook_id="nb-1",
        limit=2,
    )

    payload = _structured(result)
    assert payload == {
        "conversation_id": "conv-latest",
        "turns": [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
        ],
    }
    assert app.slot_entries == 2


@pytest.mark.asyncio
async def test_notebooklm_chat_get_conversation_returns_empty_without_history() -> None:
    class _ChatAPI:
        async def get_conversation_id(self, notebook_id: str) -> str | None:
            assert notebook_id == "nb-1"
            return None

    app = _FakeAppContext(client=SimpleNamespace(chat=_ChatAPI()))
    result = await chat_tools.notebooklm_chat_get_conversation(_ctx(app), notebook_id="nb-1")

    payload = _structured(result)
    assert payload == {"turns": []}
    assert app.slot_entries == 1


@pytest.mark.asyncio
async def test_notebooklm_chat_get_conversation_validates_limit() -> None:
    app = _FakeAppContext(client=SimpleNamespace(chat=SimpleNamespace()))

    with pytest.raises(MCPToolError) as exc_info:
        await chat_tools.notebooklm_chat_get_conversation(
            _ctx(app),
            notebook_id="nb-1",
            limit=0,
        )

    assert exc_info.value.error_code == "invalid_params"


def test_register_chat_tools_registers_all_tool_names() -> None:
    class _FakeServer:
        def __init__(self) -> None:
            self.registered: dict[str, Any] = {}

        def tool(self, *, name: str, description: str):
            assert isinstance(description, str)

            def _decorator(fn):
                self.registered[name] = fn
                return fn

            return _decorator

    server = _FakeServer()
    chat_tools.register_chat_tools(server)

    assert set(server.registered) == {
        "notebooklm_chat_ask",
        "notebooklm_chat_find_quotes",
        "notebooklm_chat_summarize_sources",
        "notebooklm_chat_get_conversation",
    }
