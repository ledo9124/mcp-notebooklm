"""Unit tests for notebooklm_mcp.tools.mind_maps."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from notebooklm_mcp.tools import mind_maps as mind_map_tools


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
async def test_notebooklm_mind_maps_generate_returns_guardrails() -> None:
    seen: dict[str, Any] = {}

    class _ArtifactsAPI:
        async def generate_mind_map(
            self,
            notebook_id: str,
            source_ids: list[str] | None = None,
        ) -> dict[str, Any]:
            seen["generate"] = (notebook_id, source_ids)
            return {"mind_map": {"name": "Coverage Map"}, "note_id": "note-7"}

    app = _FakeAppContext(client=SimpleNamespace(artifacts=_ArtifactsAPI()))
    result = await mind_map_tools.register_mind_map_tools(SimpleNamespace(tool=lambda **_: lambda fn: fn))[
        "notebooklm_mind_maps_generate"
    ](
        _ctx(app),
        notebook_id="nb-1",
        source_ids=["src-1", "src-2"],
    )

    payload = _structured(result)
    assert payload["artifact_kind"] == "mind_map"
    assert payload["draft_assistance_only"] is True
    assert payload["authoritative_for_ba_runner"] is False
    assert payload["critical_path"] is False
    assert payload["note_backed"] is True
    assert payload["stability"] == "optional_note_backed"
    assert payload["notebook_id"] == "nb-1"
    assert payload["source_ids"] == ["src-1", "src-2"]
    assert payload["note_id"] == "note-7"
    assert payload["mind_map"] == {"name": "Coverage Map"}
    assert "optional note-backed aids" in payload["warnings"][0]
    assert seen["generate"] == ("nb-1", ["src-1", "src-2"])
    assert app.slot_entries == 1


@pytest.mark.asyncio
async def test_notebooklm_mind_maps_download_returns_guardrails() -> None:
    seen: dict[str, Any] = {}

    class _ArtifactsAPI:
        async def download_mind_map(
            self,
            notebook_id: str,
            output_path: str,
            artifact_id: str | None = None,
        ) -> str:
            seen["download"] = (notebook_id, output_path, artifact_id)
            return output_path

    app = _FakeAppContext(client=SimpleNamespace(artifacts=_ArtifactsAPI()))
    result = await mind_map_tools.register_mind_map_tools(SimpleNamespace(tool=lambda **_: lambda fn: fn))[
        "notebooklm_mind_maps_download"
    ](
        _ctx(app),
        notebook_id="nb-1",
        output_path="/tmp/mind-map.json",
        artifact_id="art-9",
    )

    payload = _structured(result)
    assert payload == {
        "artifact_kind": "mind_map",
        "draft_assistance_only": True,
        "authoritative_for_ba_runner": False,
        "critical_path": False,
        "note_backed": True,
        "stability": "optional_note_backed",
        "usage_guidance": mind_map_tools._MIND_MAP_GUIDANCE,
        "success": True,
        "notebook_id": "nb-1",
        "artifact_id": "art-9",
        "output_path": "/tmp/mind-map.json",
        "warnings": [mind_map_tools._MIND_MAP_GUIDANCE],
    }
    assert seen["download"] == ("nb-1", "/tmp/mind-map.json", "art-9")


def test_register_mind_map_tools_registers_all_tool_names() -> None:
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
    returned = mind_map_tools.register_mind_map_tools(server)

    assert set(returned) == {
        "notebooklm_mind_maps_generate",
        "notebooklm_mind_maps_download",
    }
    assert set(server.registered) == set(returned)
