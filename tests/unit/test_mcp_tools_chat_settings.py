"""Unit tests for notebooklm_mcp.tools.chat_settings."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm.rpc.types import ChatGoal, ChatResponseLength
from notebooklm.types import UNSET, ChatSettings
from notebooklm_mcp._config import MCPConfig
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.server import AppContext
from notebooklm_mcp.tools.chat_settings import register_chat_settings_tools


class _FakeServer:
    def __init__(self, config: MCPConfig | None = None) -> None:
        self._notebooklm_mcp_config = config or MCPConfig()
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


def test_register_chat_settings_tools_registers_expected_names() -> None:
    server = _FakeServer()
    handlers = register_chat_settings_tools(server)

    expected = {
        "notebooklm_settings_get",
        "notebooklm_settings_patch",
        "notebooklm_settings_reset",
    }
    assert set(handlers) == expected
    assert set(server.registered) == expected


@pytest.mark.asyncio
async def test_settings_get_redacts_custom_prompt_but_reports_metadata() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.get_settings = AsyncMock(
        return_value=ChatSettings(
            goal=ChatGoal.CUSTOM,
            response_length=ChatResponseLength.SHORTER,
            custom_prompt="Use a tutor voice and cite steps.",
            source="server",
        )
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_chat_settings_tools(server)

    result = await handlers["notebooklm_settings_get"](_make_ctx(app, server), notebook_id="nb-1")

    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["goal"] == "custom"  # type: ignore[index]
    assert structured["response_length"] == "shorter"  # type: ignore[index]
    assert structured["custom_prompt_set"] is True  # type: ignore[index]
    assert structured["custom_prompt_len"] == 33  # type: ignore[index]
    assert "fingerprint" in structured  # type: ignore[operator]
    assert _decode_text_result(result) == structured
    assert "custom_prompt" not in structured  # type: ignore[operator]


@pytest.mark.asyncio
async def test_settings_patch_mode_uses_update_settings_with_unset_defaults() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.update_settings = AsyncMock(
        return_value=ChatSettings(
            goal=ChatGoal.LEARNING_GUIDE,
            response_length=ChatResponseLength.LONGER,
            custom_prompt=None,
            source="server",
        )
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_chat_settings_tools(server)

    result = await handlers["notebooklm_settings_patch"](
        _make_ctx(app, server),
        notebook_id="nb-2",
        response_length="longer",
    )

    client.chat.update_settings.assert_awaited_once_with(
        "nb-2",
        goal=UNSET,
        response_length=ChatResponseLength.LONGER,
        custom_prompt=UNSET,
        strict=True,
    )
    assert result["structuredContent"]["success"] is True  # type: ignore[index]
    assert result["structuredContent"]["after"]["response_length"] == "longer"  # type: ignore[index]


@pytest.mark.asyncio
async def test_settings_patch_set_mode_writes_absolute_defaults() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.set_settings = AsyncMock(return_value=None)
    client.chat.get_settings = AsyncMock(
        return_value=ChatSettings(
            goal=ChatGoal.DEFAULT,
            response_length=ChatResponseLength.DEFAULT,
            custom_prompt=None,
            source="server",
        )
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_chat_settings_tools(server)

    await handlers["notebooklm_settings_patch"](
        _make_ctx(app, server),
        notebook_id="nb-3",
        mode="set",
    )

    set_call = client.chat.set_settings.await_args
    assert set_call.args[0] == "nb-3"
    settings_obj = set_call.args[1]
    assert isinstance(settings_obj, ChatSettings)
    assert settings_obj.goal == ChatGoal.DEFAULT
    assert settings_obj.response_length == ChatResponseLength.DEFAULT
    assert settings_obj.custom_prompt is None


@pytest.mark.asyncio
async def test_settings_reset_requires_confirm_true() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    app = _make_app(client)
    server = _FakeServer(MCPConfig(enable_destructive_tools=True))
    handlers = register_chat_settings_tools(server)

    with pytest.raises(MCPToolError, match="confirm must be true"):
        await handlers["notebooklm_settings_reset"](
            _make_ctx(app, server),
            notebook_id="nb-4",
            confirm=False,
        )

    client.chat.reset_settings.assert_not_called()


@pytest.mark.asyncio
async def test_settings_reset_requires_destructive_tools_enabled() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    app = _make_app(client)
    server = _FakeServer(MCPConfig(enable_destructive_tools=False))
    handlers = register_chat_settings_tools(server)

    with pytest.raises(MCPToolError, match="disabled"):
        await handlers["notebooklm_settings_reset"](
            _make_ctx(app, server),
            notebook_id="nb-4",
            confirm=True,
        )

    client.chat.reset_settings.assert_not_called()


@pytest.mark.asyncio
async def test_settings_patch_rejects_invalid_mode() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_chat_settings_tools(server)

    with pytest.raises(MCPToolError, match="mode must be one of: patch, set"):
        await handlers["notebooklm_settings_patch"](
            _make_ctx(app, server),
            notebook_id="nb-5",
            mode="merge",
        )


@pytest.mark.asyncio
async def test_settings_patch_mode_allows_explicit_null_custom_prompt() -> None:
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.update_settings = AsyncMock(
        return_value=ChatSettings(
            goal=ChatGoal.DEFAULT,
            response_length=ChatResponseLength.DEFAULT,
            custom_prompt=None,
            source="server",
        )
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_chat_settings_tools(server)

    await handlers["notebooklm_settings_patch"](
        _make_ctx(app, server),
        notebook_id="nb-6",
        custom_prompt=None,
    )

    client.chat.update_settings.assert_awaited_once_with(
        "nb-6",
        goal=UNSET,
        response_length=UNSET,
        custom_prompt=None,
        strict=True,
    )
