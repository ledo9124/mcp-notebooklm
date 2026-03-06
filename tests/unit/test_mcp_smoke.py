"""Smoke tests for notebooklm_mcp protocol surface."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from notebooklm.rpc.types import SourceStatus
from notebooklm.types import Notebook, Source, SourceFulltext
from notebooklm_mcp._config import MCPConfig
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.prompts import register_prompts
from notebooklm_mcp.resources import register_resources
from notebooklm_mcp.server import AppContext
from notebooklm_mcp.tools import register_tools


class _FakeServer:
    def __init__(self, config: MCPConfig | None = None) -> None:
        self._notebooklm_mcp_config = config or MCPConfig()
        self.tools: dict[str, Any] = {}
        self.resources: dict[str, Any] = {}
        self.prompts: dict[str, Any] = {}

    def tool(self, *, name: str | None = None, description: str | None = None):  # pragma: no cover
        assert isinstance(description, str) or description is None

        def _decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return _decorator

    def resource(self, uri: str):  # pragma: no cover
        def _decorator(func):
            self.resources[uri] = func
            return func

        return _decorator

    def prompt(
        self, *, name: str | None = None, description: str | None = None
    ):  # pragma: no cover
        assert isinstance(description, str) or description is None

        def _decorator(func):
            self.prompts[name or func.__name__] = func
            return func

        return _decorator


def _make_app(client: Any) -> AppContext:
    return AppContext(  # type: ignore[arg-type]
        client=client,
        semaphore=asyncio.Semaphore(5),
        max_inflight=5,
    )


def _ctx(app: AppContext, server: _FakeServer) -> Any:
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=app,
            server=server,
        )
    )


def _decode_text_result(result: dict[str, Any]) -> dict[str, Any]:
    content = result["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    text = first["text"]
    assert isinstance(text, str)
    return json.loads(text)


def test_smoke_registers_mcp_surface() -> None:
    server = _FakeServer()
    register_tools(server)
    register_resources(server)
    register_prompts(server)

    expected_tools = {
        "notebooklm_notebooks_list",
        "notebooklm_notebooks_create",
        "notebooklm_notebooks_rename",
        "notebooklm_notebooks_delete",
        "notebooklm_notebooks_get_summary",
        "notebooklm_sources_list",
        "notebooklm_sources_add_url",
        "notebooklm_sources_add_text",
        "notebooklm_sources_add_file",
        "notebooklm_sources_remove",
        "notebooklm_sources_wait_ready",
        "notebooklm_sources_get_content",
        "notebooklm_chat_ask",
        "notebooklm_chat_find_quotes",
        "notebooklm_chat_summarize_sources",
        "notebooklm_chat_get_conversation",
        "notebooklm_settings_get",
        "notebooklm_settings_patch",
        "notebooklm_settings_reset",
        "notebooklm_diagnose",
        "notebooklm_debug_stats",
        "notebooklm_workflow_bootstrap_notebook",
        "notebooklm_workflow_research",
    }
    assert expected_tools.issubset(server.tools)

    expected_resources = {
        "notebooklm://audit/recent",
        "notebooklm://notebooks",
        "notebooklm://notebooks/{notebook_id}",
        "notebooklm://notebooks/{notebook_id}/sources/{source_id}",
    }
    assert set(server.resources) == expected_resources

    assert set(server.prompts) == {"notebook_summary", "source_analysis"}

    two_phase_tools = {
        "notebooklm_sources_remove_prepare",
        "notebooklm_sources_remove_commit",
        "notebooklm_notebooks_delete_prepare",
        "notebooklm_notebooks_delete_commit",
    }
    registered_2pc = set(server.tools) & two_phase_tools
    assert registered_2pc in (set(), two_phase_tools)


@pytest.mark.asyncio
async def test_smoke_structured_output_and_resource_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NotebooksAPI:
        async def list(self) -> list[Notebook]:
            return [
                Notebook(
                    id="nb-1",
                    title="Roadmap",
                    created_at=datetime(2026, 3, 5, 20, 31, 0),
                    sources_count=2,
                )
            ]

        async def get(self, notebook_id: str) -> Notebook:
            assert notebook_id == "nb-1"
            return Notebook(id="nb-1", title="Roadmap", created_at=None, sources_count=2)

        async def get_summary(self, notebook_id: str) -> str:
            assert notebook_id == "nb-1"
            return "Summary text"

    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Source]:
            assert notebook_id == "nb-1"
            return [
                Source(id="src-1", title="Doc One", status=SourceStatus.READY),
                Source(id="src-2", title="Doc Two", status=SourceStatus.PROCESSING),
            ]

        async def get(self, notebook_id: str, source_id: str) -> Source:
            assert notebook_id == "nb-1"
            assert source_id == "src-1"
            return Source(id="src-1", title="Doc One", status=SourceStatus.READY)

        async def get_fulltext(self, notebook_id: str, source_id: str) -> SourceFulltext:
            assert notebook_id == "nb-1"
            assert source_id == "src-1"
            return SourceFulltext(
                source_id="src-1",
                title="Doc One",
                content="abcdefghij",
                _type_code=3,
                char_count=10,
            )

    monkeypatch.setattr(
        "notebooklm_mcp.resources.load_config",
        lambda: MCPConfig(source_content_max_chars=5),
    )

    client = SimpleNamespace(
        notebooks=_NotebooksAPI(),
        sources=_SourcesAPI(),
    )
    app = _make_app(client)
    server = _FakeServer()
    register_tools(server)
    register_resources(server)
    register_prompts(server)

    result = await server.tools["notebooklm_notebooks_list"](_ctx(app, server))
    structured = result["structuredContent"]
    assert structured["notebooks"][0]["created_at"] == "2026-03-05T20:31:00"
    assert _decode_text_result(result) == structured

    sources_list = await server.tools["notebooklm_sources_list"](
        _ctx(app, server),
        notebook_id="nb-1",
    )
    source_payload = sources_list["structuredContent"]["sources"]
    assert source_payload[0]["status"] == "ready"
    assert source_payload[1]["status"] == "processing"

    notebooks_resource = await server.resources["notebooklm://notebooks"](_ctx(app, server))
    parsed_notebooks_resource = json.loads(notebooks_resource)
    assert parsed_notebooks_resource["notebooks"][0]["notebook_id"] == "nb-1"

    source_resource = await server.resources["notebooklm://notebooks/{notebook_id}/sources/{source_id}"](
        _ctx(app, server),
        notebook_id="nb-1",
        source_id="src-1",
    )
    parsed_source_resource = json.loads(source_resource)
    assert parsed_source_resource["content"] == "abcde"
    assert parsed_source_resource["truncated"] is True
    assert parsed_source_resource["returned_chars"] == 5

    prompt_messages = await server.prompts["notebook_summary"]("nb-1")
    assert prompt_messages[0]["role"] == "user"
    assert "nb-1" in prompt_messages[0]["content"]


@pytest.mark.asyncio
async def test_smoke_destructive_handlers_blocked_when_flag_disabled() -> None:
    client = SimpleNamespace(
        notebooks=SimpleNamespace(delete=AsyncMock(return_value=True)),
        sources=SimpleNamespace(delete=AsyncMock(return_value=True)),
        chat=SimpleNamespace(
            reset_settings=AsyncMock(return_value=None),
            get_settings=AsyncMock(return_value=SimpleNamespace()),
        ),
    )
    app = _make_app(client)
    server = _FakeServer(MCPConfig(enable_destructive_tools=False))
    register_tools(server)

    with pytest.raises(MCPToolError, match="destructive tools"):
        await server.tools["notebooklm_notebooks_delete"](
            _ctx(app, server),
            notebook_id="nb-1",
            confirm=True,
        )

    with pytest.raises(MCPToolError, match="disabled"):
        await server.tools["notebooklm_sources_remove"](
            _ctx(app, server),
            notebook_id="nb-1",
            source_id="src-1",
            confirm=True,
        )

    with pytest.raises(MCPToolError, match="disabled"):
        await server.tools["notebooklm_settings_reset"](
            _ctx(app, server),
            notebook_id="nb-1",
            confirm=True,
        )

    client.notebooks.delete.assert_not_awaited()
    client.sources.delete.assert_not_awaited()
    client.chat.reset_settings.assert_not_awaited()
