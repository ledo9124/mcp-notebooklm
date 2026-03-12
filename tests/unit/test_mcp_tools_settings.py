"""Unit tests for notebooklm_mcp.tools.settings."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.server import AppContext
from notebooklm_mcp.tools.settings import register_settings_tools


class _FakeServer:
    def __init__(self) -> None:
        self.registered: dict[str, dict[str, object]] = {}

    def tool(
        self, *, name: str | None = None, description: str | None = None
    ):  # pragma: no cover - exercised via decorator usage
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


def test_register_settings_tools_registers_expected_names() -> None:
    server = _FakeServer()
    handlers = register_settings_tools(server)

    expected = {
        "notebooklm_output_language_get",
        "notebooklm_output_language_set",
    }
    assert set(handlers) == expected
    assert set(server.registered) == expected


@pytest.mark.asyncio
async def test_output_language_get_returns_structured_global_payload() -> None:
    client = MagicMock()
    client.settings = MagicMock()
    client.settings.get_output_language = AsyncMock(return_value="ja")
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_settings_tools(server)

    result = await handlers["notebooklm_output_language_get"](_make_ctx(app, server))

    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["language"] == "ja"  # type: ignore[index]
    assert structured["is_default"] is False  # type: ignore[index]
    assert structured["scope"] == "global"  # type: ignore[index]
    assert _decode_text_result(result) == structured


@pytest.mark.asyncio
async def test_output_language_get_marks_default_when_unset() -> None:
    client = MagicMock()
    client.settings = MagicMock()
    client.settings.get_output_language = AsyncMock(return_value=None)
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_settings_tools(server)

    result = await handlers["notebooklm_output_language_get"](_make_ctx(app, server))

    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["language"] is None  # type: ignore[index]
    assert structured["is_default"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_output_language_set_persists_requested_language() -> None:
    client = MagicMock()
    client.settings = MagicMock()
    client.settings.set_output_language = AsyncMock(return_value="fr")
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_settings_tools(server)

    result = await handlers["notebooklm_output_language_set"](
        _make_ctx(app, server),
        language="fr",
    )

    client.settings.set_output_language.assert_awaited_once_with("fr")
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["success"] is True  # type: ignore[index]
    assert structured["requested_language"] == "fr"  # type: ignore[index]
    assert structured["response_parsed"] is True  # type: ignore[index]
    assert structured["after"]["language"] == "fr"  # type: ignore[index]
    assert _decode_text_result(result) == structured


@pytest.mark.asyncio
async def test_output_language_set_reports_unparsed_server_response() -> None:
    client = MagicMock()
    client.settings = MagicMock()
    client.settings.set_output_language = AsyncMock(return_value=None)
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_settings_tools(server)

    result = await handlers["notebooklm_output_language_set"](
        _make_ctx(app, server),
        language="de",
    )

    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["response_parsed"] is False  # type: ignore[index]
    assert structured["after"]["language"] is None  # type: ignore[index]
    assert structured["warnings"] == [  # type: ignore[index]
        "Server response did not include a parseable output language value."
    ]


@pytest.mark.asyncio
async def test_output_language_set_rejects_blank_language() -> None:
    client = MagicMock()
    client.settings = MagicMock()
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_settings_tools(server)

    with pytest.raises(MCPToolError, match="language must be a non-empty string"):
        await handlers["notebooklm_output_language_set"](
            _make_ctx(app, server),
            language="   ",
        )

    client.settings.set_output_language.assert_not_called()
