"""Unit tests for notebooklm_mcp.tools.experimental_artifacts."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm.rpc.types import (
    AudioFormat,
    AudioLength,
    InfographicDetail,
    InfographicOrientation,
)
from notebooklm.types import GenerationStatus
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.server import AppContext
from notebooklm_mcp.tools import experimental_artifacts as experimental_artifact_tools


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


def test_register_experimental_artifact_tools_registers_expected_names() -> None:
    server = _FakeServer()
    handlers = experimental_artifact_tools.register_experimental_artifact_tools(server)

    expected = {
        "notebooklm_audio_overviews_generate",
        "notebooklm_audio_overviews_wait",
        "notebooklm_audio_overviews_download",
        "notebooklm_video_overviews_generate",
        "notebooklm_video_overviews_wait",
        "notebooklm_video_overviews_download",
        "notebooklm_infographics_generate",
        "notebooklm_infographics_wait",
        "notebooklm_infographics_download",
        "notebooklm_slide_decks_generate",
        "notebooklm_slide_decks_wait",
        "notebooklm_slide_decks_download",
    }
    assert set(handlers) == expected
    assert set(server.registered) == expected


@pytest.mark.asyncio
async def test_audio_generate_uses_enums_and_experimental_payload() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.generate_audio = AsyncMock(
        return_value=GenerationStatus(task_id="aud-1", status="pending")
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = experimental_artifact_tools.register_experimental_artifact_tools(server)

    result = await handlers["notebooklm_audio_overviews_generate"](
        _make_ctx(app, server),
        notebook_id="nb-1",
        source_ids=["src-1"],
        language="ja",
        instructions="Keep it terse.",
        audio_format="debate",
        audio_length="long",
    )

    client.artifacts.generate_audio.assert_awaited_once_with(
        "nb-1",
        source_ids=["src-1"],
        language="ja",
        instructions="Keep it terse.",
        audio_format=AudioFormat.DEBATE,
        audio_length=AudioLength.LONG,
    )
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["artifact_kind"] == "audio"  # type: ignore[index]
    assert structured["experimental"] is True  # type: ignore[index]
    assert structured["critical_path"] is False  # type: ignore[index]
    assert structured["audio_format"] == "debate"  # type: ignore[index]
    assert structured["audio_length"] == "long"  # type: ignore[index]
    assert structured["warnings"] == [experimental_artifact_tools._EXPERIMENTAL_GUIDANCE]  # type: ignore[index]
    assert _decode_text_result(result) == structured


@pytest.mark.asyncio
async def test_video_wait_returns_experimental_status_payload() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.wait_for_completion = AsyncMock(
        return_value=GenerationStatus(
            task_id="vid-9",
            status="completed",
            metadata={"url": "https://example.test/video"},
        )
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = experimental_artifact_tools.register_experimental_artifact_tools(server)

    result = await handlers["notebooklm_video_overviews_wait"](
        _make_ctx(app, server),
        notebook_id="nb-2",
        task_id="vid-9",
        timeout=120,
    )

    client.artifacts.wait_for_completion.assert_awaited_once_with(
        "nb-2",
        "vid-9",
        initial_interval=2.0,
        max_interval=10.0,
        timeout=120,
    )
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["artifact_kind"] == "video"  # type: ignore[index]
    assert structured["status"] == "completed"  # type: ignore[index]
    assert structured["experimental"] is True  # type: ignore[index]
    assert structured["warnings"] == [experimental_artifact_tools._EXPERIMENTAL_GUIDANCE]  # type: ignore[index]


@pytest.mark.asyncio
async def test_infographics_generate_maps_orientation_and_detail_level() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.generate_infographic = AsyncMock(
        return_value=GenerationStatus(task_id="info-3", status="queued")
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = experimental_artifact_tools.register_experimental_artifact_tools(server)

    result = await handlers["notebooklm_infographics_generate"](
        _make_ctx(app, server),
        notebook_id="nb-3",
        source_ids=["src-a", "src-b"],
        orientation="portrait",
        detail_level="detailed",
    )

    client.artifacts.generate_infographic.assert_awaited_once_with(
        "nb-3",
        source_ids=["src-a", "src-b"],
        language="en",
        instructions=None,
        orientation=InfographicOrientation.PORTRAIT,
        detail_level=InfographicDetail.DETAILED,
    )
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["artifact_kind"] == "infographic"  # type: ignore[index]
    assert structured["orientation"] == "portrait"  # type: ignore[index]
    assert structured["detail_level"] == "detailed"  # type: ignore[index]


@pytest.mark.asyncio
async def test_slide_decks_download_supports_pptx_and_serializes_output_format() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.download_slide_deck = AsyncMock(return_value="/tmp/slides.pptx")
    app = _make_app(client)
    server = _FakeServer()
    handlers = experimental_artifact_tools.register_experimental_artifact_tools(server)

    result = await handlers["notebooklm_slide_decks_download"](
        _make_ctx(app, server),
        notebook_id="nb-4",
        output_path="/tmp/requested.pptx",
        artifact_id="deck-7",
        output_format="pptx",
    )

    client.artifacts.download_slide_deck.assert_awaited_once_with(
        "nb-4",
        "/tmp/requested.pptx",
        artifact_id="deck-7",
        output_format="pptx",
    )
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["artifact_kind"] == "slide_deck"  # type: ignore[index]
    assert structured["success"] is True  # type: ignore[index]
    assert structured["output_format"] == "pptx"  # type: ignore[index]
    assert structured["warnings"] == [experimental_artifact_tools._EXPERIMENTAL_GUIDANCE]  # type: ignore[index]


@pytest.mark.asyncio
async def test_slide_decks_download_rejects_unknown_output_format() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    app = _make_app(client)
    server = _FakeServer()
    handlers = experimental_artifact_tools.register_experimental_artifact_tools(server)

    with pytest.raises(MCPToolError, match="output_format must be one of: pdf, pptx"):
        await handlers["notebooklm_slide_decks_download"](
            _make_ctx(app, server),
            notebook_id="nb-4",
            output_path="/tmp/requested.key",
            output_format="key",
        )

    client.artifacts.download_slide_deck.assert_not_called()
