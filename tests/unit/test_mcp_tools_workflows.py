"""Unit tests for notebooklm_mcp.tools.workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm.rpc.types import ChatGoal, ChatResponseLength, SourceStatus
from notebooklm.types import AskResult, ChatSettings, Note, Notebook, Source
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.tools import workflows as workflow_tools


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


@dataclass
class _ProgressCtx:
    app_context: _FakeAppContext
    progress_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def request_context(self) -> Any:
        return SimpleNamespace(lifespan_context=self.app_context)

    async def report_progress(self, **kwargs: Any) -> None:
        self.progress_calls.append(kwargs)


def _structured(result: dict[str, Any]) -> dict[str, Any]:
    return result["structuredContent"]


@pytest.mark.asyncio
async def test_bootstrap_workflow_dry_run_has_no_side_effects() -> None:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.sources = MagicMock()
    client.chat = MagicMock()
    client.notebooks.create = AsyncMock()
    client.notebooks.get = AsyncMock()
    client.sources.list = AsyncMock()
    client.chat.ask = AsyncMock()
    app = _FakeAppContext(client=client)
    ctx = _ProgressCtx(app)

    result = await workflow_tools.notebooklm_workflow_bootstrap_notebook(
        ctx,
        title="Research Notebook",
        sources={"urls": ["https://example.com"]},
        apply_settings={"mode": "patch", "response_length": "longer"},
        dry_run=True,
    )

    payload = _structured(result)
    assert payload["notebook"]["created"] is True
    assert payload["import"] == {"added": [], "skipped": [], "failed": []}
    assert payload["warnings"] == ["dry_run=true: no NotebookLM mutations were executed."]
    assert payload["plan"] == [
        "prepare_notebook",
        "import_sources",
        "wait_ready",
        "index_note",
        "apply_settings",
    ]

    client.notebooks.create.assert_not_called()
    client.notebooks.get.assert_not_called()
    client.sources.list.assert_not_called()
    client.chat.ask.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_workflow_full_success_path() -> None:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.sources = MagicMock()
    client.chat = MagicMock()

    client.notebooks.create = AsyncMock(
        return_value=Notebook(id="nb-1", title="Demo Notebook"),
    )

    wait_states = iter(
        [
            [],
            [Source(id="src-url", title="Url", status=SourceStatus.PROCESSING)],
            [Source(id="src-url", title="Url", status=SourceStatus.READY)],
        ]
    )
    client.sources.list = AsyncMock(side_effect=lambda _nb: next(wait_states))

    client.sources.add_url = AsyncMock(
        return_value=Source(id="src-url", title="Url", status=SourceStatus.PROCESSING)
    )
    client.sources.add_text = AsyncMock(
        side_effect=[
            Source(id="src-text", title="Intro", status=SourceStatus.READY),
            Source(id="src-index", title="Notebook Index (auto)", status=SourceStatus.READY),
        ]
    )
    client.sources.add_file = AsyncMock(
        return_value=Source(id="src-file", title="upload.txt", status=SourceStatus.READY)
    )
    client.sources.rename = AsyncMock(
        return_value=Source(id="src-file", title="Upload", status=SourceStatus.READY)
    )

    client.chat.ask = AsyncMock(
        return_value=AskResult(
            answer="Index summary text",
            conversation_id="conv-1",
            turn_number=1,
            is_follow_up=False,
            references=[],
        )
    )
    client.chat.update_settings = AsyncMock(
        return_value=ChatSettings(
            goal=ChatGoal.DEFAULT,
            response_length=ChatResponseLength.LONGER,
            custom_prompt=None,
            source="server",
        )
    )

    app = _FakeAppContext(client=client)
    ctx = _ProgressCtx(app)

    original_sleep = workflow_tools.asyncio.sleep
    workflow_tools.asyncio.sleep = AsyncMock(return_value=None)
    try:
        result = await workflow_tools.notebooklm_workflow_bootstrap_notebook(
            ctx,
            title="Demo Notebook",
            sources={
                "urls": ["https://example.com/a"],
                "texts": [{"title": "Intro", "content": "hello"}],
                "files": [
                    {
                        "filename": "upload.txt",
                        "mime_type": "text/plain",
                        "data_base64": "aGVsbG8=",
                        "title": "Upload",
                    }
                ],
            },
            wait_ready=True,
            apply_settings={"mode": "patch", "response_length": "longer"},
        )
    finally:
        workflow_tools.asyncio.sleep = original_sleep

    payload = _structured(result)
    assert payload["notebook"] == {
        "notebook_id": "nb-1",
        "title": "Demo Notebook",
        "created": True,
    }
    assert len(payload["import"]["added"]) == 3
    assert payload["import"]["failed"] == []
    assert payload["ready"] is True
    assert payload["index_note"] == {"created": True, "source_id": "src-index"}
    assert payload["settings"]["applied"] is True
    assert payload["settings"]["after"]["response_length"] == "longer"
    assert len(ctx.progress_calls) >= 5


@pytest.mark.asyncio
async def test_bootstrap_workflow_partial_import_failures_continue() -> None:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.sources = MagicMock()
    client.chat = MagicMock()

    client.notebooks.create = AsyncMock(return_value=Notebook(id="nb-2", title="Failures"))
    client.sources.list = AsyncMock(return_value=[])
    client.sources.add_url = AsyncMock(
        side_effect=[
            RuntimeError("token=abc exploded"),
            Source(id="src-ok", title="ok", status=SourceStatus.READY),
        ]
    )

    app = _FakeAppContext(client=client)
    ctx = _ProgressCtx(app)

    result = await workflow_tools.notebooklm_workflow_bootstrap_notebook(
        ctx,
        title="Failures",
        sources={"urls": ["https://bad.example", "https://ok.example"]},
        wait_ready=False,
        generate_index_note=False,
    )

    payload = _structured(result)
    assert payload["ready"] is False
    assert len(payload["import"]["added"]) == 1
    assert len(payload["import"]["failed"]) == 1
    assert "abc" not in payload["import"]["failed"][0]["error"]


@pytest.mark.asyncio
async def test_bootstrap_workflow_invalid_apply_settings_mode_raises() -> None:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.sources = MagicMock()
    client.chat = MagicMock()

    client.notebooks.get = AsyncMock(return_value=Notebook(id="nb-3", title="Existing"))
    client.sources.list = AsyncMock(return_value=[])

    app = _FakeAppContext(client=client)
    ctx = _ProgressCtx(app)

    with pytest.raises(MCPToolError) as exc_info:
        await workflow_tools.notebooklm_workflow_bootstrap_notebook(
            ctx,
            notebook_id="nb-3",
            wait_ready=False,
            generate_index_note=False,
            apply_settings={"mode": "merge"},
        )

    assert exc_info.value.error_code == "invalid_params"


@pytest.mark.asyncio
async def test_research_workflow_dry_run_returns_plan_only() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.sources = MagicMock()
    app = _FakeAppContext(client=client)
    ctx = _ProgressCtx(app)

    result = await workflow_tools.notebooklm_workflow_research(
        ctx,
        notebook_id="nb-1",
        question="What changed?",
        save_as_note=True,
        dry_run=True,
    )

    payload = _structured(result)
    assert payload["warnings"] == ["dry_run=true: no NotebookLM mutations were executed."]
    assert payload["plan"] == ["ensure_ready", "ask_question", "save_note"]
    assert payload["note"] == {"created": False}
    client.chat.ask.assert_not_called()


@pytest.mark.asyncio
async def test_research_workflow_timeout_returns_not_ready_without_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.sources = MagicMock()
    client.chat = MagicMock()

    client.sources.list = AsyncMock(
        return_value=[Source(id="src-1", title="Doc", status=SourceStatus.PROCESSING)]
    )
    client.chat.ask = AsyncMock()

    app = _FakeAppContext(client=client)
    ctx = _ProgressCtx(app)

    timeline = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(workflow_tools, "_now", lambda: next(timeline))
    monkeypatch.setattr(workflow_tools.asyncio, "sleep", AsyncMock(return_value=None))

    result = await workflow_tools.notebooklm_workflow_research(
        ctx,
        notebook_id="nb-2",
        question="Summarize",
        ensure_ready=True,
        timeout_ms=10,
        poll_interval_ms=250,
    )

    payload = _structured(result)
    assert payload["ready"] is False
    assert payload["statuses"] == [{"source_id": "src-1", "status": "processing"}]
    assert "question was not asked" in payload["warnings"][0]
    client.chat.ask.assert_not_called()


@pytest.mark.asyncio
async def test_research_workflow_success_with_citations_and_saved_note() -> None:
    client = MagicMock()
    client.sources = MagicMock()
    client.chat = MagicMock()
    client.notes = MagicMock()

    client.sources.list = AsyncMock(
        side_effect=[
            [Source(id="src-1", title="Paper A", status=SourceStatus.READY)],
            [Source(id="src-1", title="Paper A", url="https://example.com/a", status=SourceStatus.READY)],
        ]
    )
    client.chat.ask = AsyncMock(
        return_value=AskResult(
            answer="**Main finding** with evidence.",
            conversation_id="conv-9",
            turn_number=2,
            is_follow_up=True,
            references=[
                SimpleNamespace(
                    source_id="src-1",
                    cited_text="evidence quote",
                    start_char=5,
                    end_char=12,
                )
            ],
        )
    )
    client.chat.get_settings = AsyncMock(
        return_value=ChatSettings(
            goal=ChatGoal.DEFAULT,
            response_length=ChatResponseLength.DEFAULT,
            custom_prompt=None,
            source="server",
        )
    )
    client.notes.create = AsyncMock(
        return_value=Note(
            id="note-1",
            notebook_id="nb-3",
            title="Research Note (auto)",
            content="saved",
        )
    )

    app = _FakeAppContext(client=client)
    ctx = _ProgressCtx(app)

    result = await workflow_tools.notebooklm_workflow_research(
        ctx,
        notebook_id="nb-3",
        question="What is the headline?",
        ensure_ready=True,
        citations=True,
        format="text",
        save_as_note=True,
    )

    payload = _structured(result)
    assert payload["ready"] is True
    assert payload["answer"] == "Main finding with evidence."
    assert payload["conversation_id"] == "conv-9"
    assert payload["citations"] == [
        {
            "source_id": "src-1",
            "title": "Paper A",
            "url": "https://example.com/a",
            "quote": "evidence quote",
            "location": "5-12",
        }
    ]
    assert payload["used_settings"] == {"goal": "default", "response_length": "default"}
    assert payload["note"] == {
        "created": True,
        "note_id": "note-1",
        "title": "Research Note (auto)",
    }
    assert len(ctx.progress_calls) >= 3


def test_register_workflow_tools_registers_all_workflow_macros() -> None:
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
    workflow_tools.register_workflow_tools(server)

    assert set(server.registered) == {
        "notebooklm_workflow_bootstrap_notebook",
        "notebooklm_workflow_research",
    }
