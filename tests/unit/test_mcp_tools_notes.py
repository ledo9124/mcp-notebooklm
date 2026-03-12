"""Unit tests for notebooklm_mcp.tools.notes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from notebooklm.rpc.types import SourceStatus
from notebooklm.types import Note, Source
from notebooklm_mcp._config import MCPConfig
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.tools import notes as notes_tools


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


def _ctx(app_context: _FakeAppContext, *, config: MCPConfig | None = None) -> Any:
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=app_context,
            server=SimpleNamespace(_notebooklm_mcp_config=config or MCPConfig()),
        )
    )


def _structured(result: dict[str, Any]) -> dict[str, Any]:
    return result["structuredContent"]


@pytest.mark.asyncio
async def test_notebooklm_notes_list_returns_summaries() -> None:
    class _NotesAPI:
        async def list(self, notebook_id: str) -> list[Note]:
            assert notebook_id == "nb-1"
            return [
                Note(
                    id="note-1",
                    notebook_id=notebook_id,
                    title="Decision",
                    content="Use server defaults.",
                    created_at=datetime(2026, 3, 12, 8, 0, 0),
                )
            ]

    app = _FakeAppContext(client=SimpleNamespace(notes=_NotesAPI()))
    result = await notes_tools.notebooklm_notes_list(_ctx(app), notebook_id="nb-1")

    payload = _structured(result)
    assert payload["notes"] == [
        {
            "note_id": "note-1",
            "title": "Decision",
            "created_at": "2026-03-12T08:00:00",
            "content_preview": "Use server defaults.",
            "content_length": 20,
        }
    ]
    assert app.slot_entries == 1


@pytest.mark.asyncio
async def test_notebooklm_notes_create_and_get_round_trip() -> None:
    seen: dict[str, Any] = {}

    class _NotesAPI:
        async def create(self, notebook_id: str, title: str, content: str) -> Note:
            seen["create"] = (notebook_id, title, content)
            return Note(id="note-1", notebook_id=notebook_id, title=title, content=content)

        async def get(self, notebook_id: str, note_id: str) -> Note:
            seen["get"] = (notebook_id, note_id)
            return Note(
                id=note_id,
                notebook_id=notebook_id,
                title="Decision",
                content="Prefer optimistic UI.",
            )

    app = _FakeAppContext(client=SimpleNamespace(notes=_NotesAPI()))

    created = await notes_tools.notebooklm_notes_create(
        _ctx(app),
        notebook_id="nb-1",
        title="Decision",
        content="Prefer optimistic UI.",
    )
    fetched = await notes_tools.notebooklm_notes_get(
        _ctx(app),
        notebook_id="nb-1",
        note_id="note-1",
    )

    assert _structured(created)["note"] == {
        "note_id": "note-1",
        "title": "Decision",
        "content": "Prefer optimistic UI.",
    }
    assert _structured(fetched)["note"] == {
        "note_id": "note-1",
        "title": "Decision",
        "content": "Prefer optimistic UI.",
    }
    assert seen["create"] == ("nb-1", "Decision", "Prefer optimistic UI.")
    assert seen["get"] == ("nb-1", "note-1")


@pytest.mark.asyncio
async def test_notebooklm_notes_save_preserves_unspecified_content() -> None:
    seen: dict[str, Any] = {}

    class _NotesAPI:
        async def get(self, notebook_id: str, note_id: str) -> Note:
            return Note(
                id=note_id,
                notebook_id=notebook_id,
                title="Old Title",
                content="Original content",
            )

        async def update(self, notebook_id: str, note_id: str, content: str, title: str) -> None:
            seen["update"] = (notebook_id, note_id, title, content)

    app = _FakeAppContext(client=SimpleNamespace(notes=_NotesAPI()))
    result = await notes_tools.notebooklm_notes_save(
        _ctx(app),
        notebook_id="nb-1",
        note_id="note-1",
        title="New Title",
    )

    assert _structured(result)["note"] == {
        "note_id": "note-1",
        "title": "New Title",
        "content": "Original content",
    }
    assert seen["update"] == ("nb-1", "note-1", "New Title", "Original content")


@pytest.mark.asyncio
async def test_notebooklm_notes_delete_respects_gating() -> None:
    deleted: list[tuple[str, str]] = []

    class _NotesAPI:
        async def delete(self, notebook_id: str, note_id: str) -> bool:
            deleted.append((notebook_id, note_id))
            return True

    app = _FakeAppContext(client=SimpleNamespace(notes=_NotesAPI()))

    with pytest.raises(MCPToolError, match="disabled"):
        await notes_tools.notebooklm_notes_delete(
            _ctx(app),
            notebook_id="nb-1",
            note_id="note-1",
            confirm=True,
        )

    with pytest.raises(MCPToolError, match="confirm=true"):
        await notes_tools.notebooklm_notes_delete(
            _ctx(app, config=MCPConfig(enable_destructive_tools=True)),
            notebook_id="nb-1",
            note_id="note-1",
            confirm=False,
        )

    result = await notes_tools.notebooklm_notes_delete(
        _ctx(app, config=MCPConfig(enable_destructive_tools=True)),
        notebook_id="nb-1",
        note_id="note-1",
        confirm=True,
    )

    assert _structured(result) == {"success": True}
    assert deleted == [("nb-1", "note-1")]


@pytest.mark.asyncio
async def test_notebooklm_notes_create_curated_source_creates_note_and_source() -> None:
    seen: dict[str, Any] = {}

    class _NotesAPI:
        async def create(self, notebook_id: str, title: str, content: str) -> Note:
            seen["note_create"] = (notebook_id, title, content)
            return Note(id="note-1", notebook_id=notebook_id, title=title, content=content)

    class _SourcesAPI:
        async def add_text(
            self,
            notebook_id: str,
            title: str,
            content: str,
            wait: bool,
            wait_timeout: float,
        ) -> Source:
            seen["source_add_text"] = (notebook_id, title, content, wait, wait_timeout)
            return Source(id="src-1", title=title, status=SourceStatus.READY)

    app = _FakeAppContext(client=SimpleNamespace(notes=_NotesAPI(), sources=_SourcesAPI()))
    result = await notes_tools.notebooklm_notes_create_curated_source(
        _ctx(app),
        notebook_id="nb-1",
        curation_kind="decision",
        title="Policy Decision",
        content="Require MFA before launch.",
        wait=True,
        wait_timeout_ms=90_000,
    )

    payload = _structured(result)
    assert payload["note"] == {
        "note_id": "note-1",
        "title": "Policy Decision",
        "content": "Require MFA before launch.",
    }
    assert payload["source"] == {
        "source_id": "src-1",
        "title": "Policy Decision",
        "status": "ready",
        "ready": True,
        "kind": "unknown",
    }
    assert payload["source_origin"] == "note"
    assert payload["curation_kind"] == "decision"
    assert payload["source_type_hint"] == "SUPPORTING_DECISION"
    assert "does not expose a first-class note conversion API" in payload["warnings"][0]
    assert seen["note_create"] == ("nb-1", "Policy Decision", "Require MFA before launch.")
    assert seen["source_add_text"] == (
        "nb-1",
        "Policy Decision",
        "Require MFA before launch.",
        True,
        90.0,
    )


@pytest.mark.asyncio
async def test_notebooklm_notes_create_curated_source_uses_existing_note() -> None:
    class _NotesAPI:
        async def get(self, notebook_id: str, note_id: str) -> Note:
            assert notebook_id == "nb-1"
            assert note_id == "note-7"
            return Note(
                id=note_id,
                notebook_id=notebook_id,
                title="Clarification",
                content="The list should default to newest first.",
            )

    class _SourcesAPI:
        async def add_text(
            self,
            notebook_id: str,
            title: str,
            content: str,
            wait: bool,
            wait_timeout: float,
        ) -> Source:
            assert notebook_id == "nb-1"
            assert title == "Clarification"
            assert content == "The list should default to newest first."
            assert wait is False
            assert wait_timeout == 120.0
            return Source(id="src-9", title=title, status=SourceStatus.PROCESSING)

    app = _FakeAppContext(client=SimpleNamespace(notes=_NotesAPI(), sources=_SourcesAPI()))
    result = await notes_tools.notebooklm_notes_create_curated_source(
        _ctx(app),
        notebook_id="nb-1",
        curation_kind="clarification",
        note_id="note-7",
    )

    payload = _structured(result)
    assert payload["note"]["note_id"] == "note-7"
    assert payload["source"]["source_id"] == "src-9"
    assert payload["source_type_hint"] == "SUPPORTING_CLARIFICATION"


def test_register_notes_tools_registers_all_tool_names() -> None:
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
    notes_tools.register_notes_tools(server)

    assert set(server.registered) == {
        "notebooklm_notes_list",
        "notebooklm_notes_get",
        "notebooklm_notes_create",
        "notebooklm_notes_save",
        "notebooklm_notes_delete",
        "notebooklm_notes_create_curated_source",
    }
