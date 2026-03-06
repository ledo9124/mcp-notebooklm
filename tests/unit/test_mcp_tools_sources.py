"""Unit tests for notebooklm_mcp.tools.sources."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from notebooklm.rpc.types import SourceStatus
from notebooklm.types import Source, SourceFulltext
from notebooklm_mcp._config import MCPConfig
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.tools import sources as sources_tools


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
async def test_notebooklm_sources_list_returns_summaries() -> None:
    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Source]:
            assert notebook_id == "nb-1"
            return [
                Source(id="src-1", title="Doc", status=SourceStatus.READY),
                Source(id="src-2", title="Pending", status=SourceStatus.PROCESSING),
            ]

    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()))
    result = await sources_tools.notebooklm_sources_list(_ctx(app), notebook_id="nb-1")

    payload = _structured(result)
    assert [item["source_id"] for item in payload["sources"]] == ["src-1", "src-2"]
    assert payload["sources"][0]["status"] == "ready"
    assert payload["sources"][1]["status"] == "processing"
    assert app.slot_entries == 1


@pytest.mark.asyncio
async def test_notebooklm_sources_add_url_waits_until_ready() -> None:
    class _SourcesAPI:
        def __init__(self) -> None:
            self.list_calls = 0

        async def add_url(self, notebook_id: str, url: str, wait: bool) -> Source:
            assert notebook_id == "nb-1"
            assert url == "https://example.com"
            assert wait is False
            return Source(id="src-1", title=url, status=SourceStatus.PROCESSING)

        async def list(self, notebook_id: str) -> list[Source]:
            self.list_calls += 1
            status = SourceStatus.PROCESSING if self.list_calls == 1 else SourceStatus.READY
            return [Source(id="src-1", title="Doc", status=status)]

    async def _fast_sleep(_: float) -> None:
        return None

    api = _SourcesAPI()
    app = _FakeAppContext(client=SimpleNamespace(sources=api))
    ctx = _ctx(app)

    original_sleep = sources_tools.asyncio.sleep
    sources_tools.asyncio.sleep = _fast_sleep
    try:
        result = await sources_tools.notebooklm_sources_add_url(
            ctx,
            notebook_id="nb-1",
            url="https://example.com",
            wait=True,
            timeout_ms=10_000,
            poll_interval_ms=1,
        )
    finally:
        sources_tools.asyncio.sleep = original_sleep

    payload = _structured(result)
    assert payload["source_id"] == "src-1"
    assert payload["ready"] is True
    assert payload["status"] == "ready"


@pytest.mark.asyncio
async def test_notebooklm_sources_wait_ready_timeout_returns_partial_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Source]:
            return [Source(id="src-1", title="Doc", status=SourceStatus.PROCESSING)]

    async def _fast_sleep(_: float) -> None:
        return None

    timeline = iter([0.0, 0.0, 0.02, 0.02])
    monkeypatch.setattr(sources_tools, "_now", lambda: next(timeline))
    monkeypatch.setattr(sources_tools.asyncio, "sleep", _fast_sleep)

    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()))
    result = await sources_tools.notebooklm_sources_wait_ready(
        _ctx(app),
        notebook_id="nb-1",
        timeout_ms=10,
        poll_interval_ms=1,
    )

    payload = _structured(result)
    assert payload["ready"] is False
    assert payload["statuses"] == [
        {"source_id": "src-1", "title": "Doc", "kind": "unknown", "status": "processing"}
    ]


@pytest.mark.asyncio
async def test_notebooklm_sources_add_file_invalid_base64_raises_mcp_error() -> None:
    app = _FakeAppContext(client=SimpleNamespace(sources=SimpleNamespace()))

    with pytest.raises(MCPToolError) as exc_info:
        await sources_tools.notebooklm_sources_add_file(
            _ctx(app),
            notebook_id="nb-1",
            filename="doc.txt",
            mime_type="text/plain",
            data_base64="!!!not-base64!!!",
        )

    assert exc_info.value.error_code == "invalid_params"


@pytest.mark.asyncio
async def test_notebooklm_sources_add_file_uploads_and_optionally_renames() -> None:
    seen: dict[str, Any] = {}

    class _SourcesAPI:
        async def add_file(self, notebook_id: str, file_path: str, mime_type: str) -> Source:
            seen["add_file"] = (notebook_id, file_path, mime_type)
            with open(file_path, "rb") as handle:
                seen["raw"] = handle.read()
            return Source(id="src-1", title="upload.bin", status=SourceStatus.PROCESSING)

        async def rename(self, notebook_id: str, source_id: str, title: str) -> Source:
            seen["rename"] = (notebook_id, source_id, title)
            return Source(id=source_id, title=title, status=SourceStatus.PROCESSING)

    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()))
    result = await sources_tools.notebooklm_sources_add_file(
        _ctx(app),
        notebook_id="nb-1",
        filename="upload.bin",
        mime_type="application/octet-stream",
        data_base64="aGVsbG8=",  # "hello"
        title="Friendly Name",
    )

    payload = _structured(result)
    assert payload["source_id"] == "src-1"
    assert payload["status"] == "processing"
    assert seen["raw"] == b"hello"
    assert seen["rename"] == ("nb-1", "src-1", "Friendly Name")


@pytest.mark.asyncio
async def test_notebooklm_sources_remove_respects_gating() -> None:
    deleted: list[tuple[str, str]] = []

    class _SourcesAPI:
        async def delete(self, notebook_id: str, source_id: str) -> bool:
            deleted.append((notebook_id, source_id))
            return True

    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()))
    with pytest.raises(MCPToolError) as exc_info:
        await sources_tools.notebooklm_sources_remove(
            _ctx(app),
            notebook_id="nb-1",
            source_id="src-1",
            confirm=True,
        )
    assert exc_info.value.error_code == "invalid_params"
    with pytest.raises(MCPToolError):
        await sources_tools.notebooklm_sources_remove(
            _ctx(app, config=MCPConfig(enable_destructive_tools=True)),
            notebook_id="nb-1",
            source_id="src-1",
            confirm=False,
        )

    result = await sources_tools.notebooklm_sources_remove(
        _ctx(app, config=MCPConfig(enable_destructive_tools=True)),
        notebook_id="nb-1",
        source_id="src-1",
        confirm=True,
    )
    assert _structured(result) == {"success": True}
    assert deleted == [("nb-1", "src-1")]


@pytest.mark.asyncio
async def test_notebooklm_sources_get_content_enforces_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    class _SourcesAPI:
        async def get_fulltext(self, notebook_id: str, source_id: str) -> SourceFulltext:
            assert notebook_id == "nb-1"
            assert source_id == "src-1"
            return SourceFulltext(
                source_id=source_id,
                title="Doc",
                content="abcdefghij",
                _type_code=None,
                char_count=10,
            )

    monkeypatch.setattr(
        sources_tools,
        "load_config",
        lambda: MCPConfig(source_content_max_chars=5),
    )

    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()))
    result = await sources_tools.notebooklm_sources_get_content(
        _ctx(app),
        notebook_id="nb-1",
        source_id="src-1",
        max_chars=9,
    )
    payload = _structured(result)
    assert payload["content"] == "abcde"
    assert payload["truncated"] is True
    assert payload["max_chars"] == 5
    assert payload["total_chars"] == 10


def test_register_sources_tools_registers_all_tool_names() -> None:
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
    sources_tools.register_sources_tools(server)

    assert set(server.registered) == {
        "notebooklm_sources_list",
        "notebooklm_sources_add_url",
        "notebooklm_sources_add_text",
        "notebooklm_sources_add_file",
        "notebooklm_sources_remove",
        "notebooklm_sources_wait_ready",
        "notebooklm_sources_get_content",
    }
