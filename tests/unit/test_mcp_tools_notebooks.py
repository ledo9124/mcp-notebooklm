"""Unit tests for notebooklm_mcp.tools.notebooks."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from notebooklm_mcp._config import MCPConfig
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.server import AppContext
from notebooklm_mcp.tools.notebooks import register_notebook_tools
from notebooklm.types import Notebook, NotebookDescription, SuggestedTopic


class _FakeServer:
    def __init__(self, config: MCPConfig | None = None) -> None:
        self._notebooklm_mcp_config = config or MCPConfig()
        self.registered: dict[str, dict[str, object]] = {}

    def tool(
        self, *, name: str | None = None, description: str | None = None
    ):  # pragma: no cover - exercised through decorator calls
        def _decorator(func):
            self.registered[name or func.__name__] = {
                "handler": func,
                "description": description,
            }
            return func

        return _decorator


def _make_app(client: object) -> AppContext:
    return AppContext(  # type: ignore[arg-type]
        client=client,
        semaphore=asyncio.Semaphore(5),
        max_inflight=5,
    )


def _make_ctx(app: AppContext, server: _FakeServer) -> SimpleNamespace:
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=app,
            server=server,
        )
    )


def _decode_text_result(result: dict[str, object]) -> dict[str, object]:
    content = result["content"]  # type: ignore[index]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    text = first["text"]
    assert isinstance(text, str)
    return json.loads(text)


def test_register_notebook_tools_registers_expected_names() -> None:
    server = _FakeServer()
    handlers = register_notebook_tools(server)

    expected = {
        "notebooklm_notebooks_list",
        "notebooklm_notebooks_create",
        "notebooklm_notebooks_rename",
        "notebooklm_notebooks_delete",
        "notebooklm_notebooks_get_summary",
    }

    assert set(handlers) == expected
    assert set(server.registered) == expected


@pytest.mark.asyncio
async def test_notebooks_list_returns_structured_and_text_payload() -> None:
    notebook = Notebook(
        id="nb-1",
        title="Roadmap",
        created_at=datetime(2026, 3, 5, 10, 30, 0),
        sources_count=2,
    )
    client = MagicMock()
    client.notebooks = MagicMock()
    client.notebooks.list = AsyncMock(return_value=[notebook])
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_notebook_tools(server)

    result = await handlers["notebooklm_notebooks_list"](_make_ctx(app, server))

    structured = result["structuredContent"]  # type: ignore[index]
    assert isinstance(structured, dict)
    notebooks = structured["notebooks"]  # type: ignore[index]
    assert isinstance(notebooks, list)
    assert notebooks == [
        {
            "notebook_id": "nb-1",
            "title": "Roadmap",
            "source_count": 2,
            "created_at": "2026-03-05T10:30:00",
        }
    ]
    assert _decode_text_result(result) == structured


@pytest.mark.asyncio
async def test_notebooks_list_uses_parser_source_count() -> None:
    notebook = Notebook.from_api_response(
        [
            "Roadmap",
            [["src_a"], ["src_b"], ["src_c"]],
            "nb-raw",
            "📘",
        ]
    )
    client = MagicMock()
    client.notebooks = MagicMock()
    client.notebooks.list = AsyncMock(return_value=[notebook])
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_notebook_tools(server)

    result = await handlers["notebooklm_notebooks_list"](_make_ctx(app, server))

    structured = result["structuredContent"]  # type: ignore[index]
    assert isinstance(structured, dict)
    notebooks = structured["notebooks"]  # type: ignore[index]
    assert isinstance(notebooks, list)
    assert notebooks == [
        {
            "notebook_id": "nb-raw",
            "title": "Roadmap",
            "source_count": 3,
        }
    ]


@pytest.mark.asyncio
async def test_notebooks_create_calls_client_and_returns_identifier() -> None:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.notebooks.create = AsyncMock(
        return_value=Notebook(
            id="nb-42",
            title="Project Atlas",
        )
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_notebook_tools(server)

    result = await handlers["notebooklm_notebooks_create"](
        _make_ctx(app, server), title="Project Atlas"
    )

    client.notebooks.create.assert_awaited_once_with("Project Atlas")
    assert result["structuredContent"] == {  # type: ignore[index]
        "notebook_id": "nb-42",
        "title": "Project Atlas",
    }


@pytest.mark.asyncio
async def test_notebooks_delete_requires_destructive_flag() -> None:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.notebooks.delete = AsyncMock(return_value=True)
    app = _make_app(client)
    server = _FakeServer(MCPConfig(enable_destructive_tools=False))
    handlers = register_notebook_tools(server)

    with pytest.raises(MCPToolError, match="destructive tools"):
        await handlers["notebooklm_notebooks_delete"](
            _make_ctx(app, server),
            notebook_id="nb-1",
            confirm=True,
        )

    client.notebooks.delete.assert_not_called()


@pytest.mark.asyncio
async def test_notebooks_delete_requires_confirm_true() -> None:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.notebooks.delete = AsyncMock(return_value=True)
    app = _make_app(client)
    server = _FakeServer(MCPConfig(enable_destructive_tools=True))
    handlers = register_notebook_tools(server)

    with pytest.raises(MCPToolError, match="confirm must be true"):
        await handlers["notebooklm_notebooks_delete"](
            _make_ctx(app, server),
            notebook_id="nb-1",
            confirm=False,
        )

    client.notebooks.delete.assert_not_called()


@pytest.mark.asyncio
async def test_notebooks_delete_success_when_enabled() -> None:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.notebooks.delete = AsyncMock(return_value=True)
    app = _make_app(client)
    server = _FakeServer(MCPConfig(enable_destructive_tools=True))
    handlers = register_notebook_tools(server)

    result = await handlers["notebooklm_notebooks_delete"](
        _make_ctx(app, server),
        notebook_id="nb-99",
        confirm=True,
    )

    client.notebooks.delete.assert_awaited_once_with("nb-99")
    assert result["structuredContent"] == {"success": True}  # type: ignore[index]


@pytest.mark.asyncio
async def test_notebooks_delete_falls_back_to_legacy_rpc_helper() -> None:
    client = SimpleNamespace(
        _core=object(),
        notebooks=SimpleNamespace(),
    )
    app = _make_app(client)
    server = _FakeServer(MCPConfig(enable_destructive_tools=True))
    handlers = register_notebook_tools(server)

    with patch(
        "notebooklm_mcp.tools.notebooks._delete_notebook_rpc",
        new=AsyncMock(return_value=True),
    ) as delete_rpc:
        result = await handlers["notebooklm_notebooks_delete"](
            _make_ctx(app, server),
            notebook_id="nb-legacy",
            confirm=True,
        )

    delete_rpc.assert_awaited_once_with(client._core, "nb-legacy")
    assert result["structuredContent"] == {"success": True}  # type: ignore[index]


@pytest.mark.asyncio
async def test_notebooks_rename_falls_back_to_legacy_rpc_helper() -> None:
    client = SimpleNamespace(
        _core=object(),
        notebooks=SimpleNamespace(),
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_notebook_tools(server)
    renamed = Notebook(id="nb-legacy", title="Renamed")

    with patch(
        "notebooklm_mcp.tools.notebooks._rename_notebook_rpc",
        new=AsyncMock(return_value=renamed),
    ) as rename_rpc:
        result = await handlers["notebooklm_notebooks_rename"](
            _make_ctx(app, server),
            notebook_id="nb-legacy",
            title="Renamed",
        )

    rename_rpc.assert_awaited_once_with(client._core, "nb-legacy", "Renamed")
    assert result["structuredContent"] == {  # type: ignore[index]
        "success": True,
        "notebook": {
            "notebook_id": "nb-legacy",
            "title": "Renamed",
            "source_count": 0,
        },
    }


@pytest.mark.asyncio
async def test_notebooks_get_summary_includes_topics_and_source_count() -> None:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.sources = MagicMock()
    client.notebooks.get_description = AsyncMock(
        return_value=NotebookDescription(
            summary="Key themes",
            suggested_topics=[SuggestedTopic(question="What changed?", prompt="Analyze deltas")],
        )
    )
    client.sources.list = AsyncMock(return_value=[object(), object(), object()])
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_notebook_tools(server)

    result = await handlers["notebooklm_notebooks_get_summary"](
        _make_ctx(app, server),
        notebook_id="nb-10",
    )

    summary = result["structuredContent"]["summary"]  # type: ignore[index]
    assert summary == {
        "description": "Key themes",
        "source_count": 3,
        "suggested_topics": [
            {
                "question": "What changed?",
                "prompt": "Analyze deltas",
            }
        ],
    }
