"""Unit tests for notebooklm_mcp.resources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from notebooklm.exceptions import SourceNotFoundError
from notebooklm.types import Notebook, Source, SourceFulltext
from notebooklm_mcp._audit import AuditLog
from notebooklm_mcp._config import MCPConfig
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.resources import (
    notebooklm_resource_audit_recent,
    notebooklm_resource_notebook,
    notebooklm_resource_notebook_source,
    notebooklm_resource_notebooks,
    register_resources,
)


class _AcquireSlot:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@dataclass
class _FakeAppContext:
    client: Any

    def acquire_slot(self) -> _AcquireSlot:
        return _AcquireSlot()


def _ctx(app: _FakeAppContext) -> Any:
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app))


@pytest.mark.asyncio
async def test_notebooklm_resource_notebooks_returns_json_payload() -> None:
    class _NotebooksAPI:
        async def list(self) -> list[Notebook]:
            return [
                Notebook(
                    id="nb-1",
                    title="First",
                    created_at=datetime(2026, 3, 5, 12, 0, 0),
                    sources_count=2,
                )
            ]

    app = _FakeAppContext(client=SimpleNamespace(notebooks=_NotebooksAPI()))
    payload = await notebooklm_resource_notebooks(_ctx(app))
    parsed = json.loads(payload)

    assert parsed["notebooks"] == [
        {
            "created_at": "2026-03-05T12:00:00",
            "notebook_id": "nb-1",
            "source_count": 2,
            "title": "First",
        }
    ]


@pytest.mark.asyncio
async def test_notebooklm_resource_notebook_returns_summary_and_source_count() -> None:
    class _NotebooksAPI:
        async def get(self, notebook_id: str) -> Notebook:
            assert notebook_id == "nb-1"
            return Notebook(id=notebook_id, title="Notebook", created_at=None, sources_count=0)

        async def get_summary(self, notebook_id: str) -> str:
            assert notebook_id == "nb-1"
            return "Summary text"

    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Source]:
            assert notebook_id == "nb-1"
            return [Source(id="src-1"), Source(id="src-2")]

    app = _FakeAppContext(
        client=SimpleNamespace(notebooks=_NotebooksAPI(), sources=_SourcesAPI())
    )
    payload = await notebooklm_resource_notebook(_ctx(app), notebook_id="nb-1")
    parsed = json.loads(payload)

    assert parsed == {
        "notebook_id": "nb-1",
        "source_count": 2,
        "summary": "Summary text",
        "title": "Notebook",
    }


@pytest.mark.asyncio
async def test_notebooklm_resource_notebook_source_truncates_content(monkeypatch: pytest.MonkeyPatch) -> None:
    class _SourcesAPI:
        async def get(self, notebook_id: str, source_id: str) -> Source | None:
            assert notebook_id == "nb-1"
            assert source_id == "src-1"
            return Source(id=source_id, title="Doc", url="https://example.com")

        async def get_fulltext(self, notebook_id: str, source_id: str) -> SourceFulltext:
            assert notebook_id == "nb-1"
            assert source_id == "src-1"
            return SourceFulltext(
                source_id=source_id,
                title="Doc",
                content="abcdefghij",
                _type_code=3,
                url="https://example.com",
                char_count=10,
            )

    monkeypatch.setattr(
        "notebooklm_mcp.resources.load_config",
        lambda: MCPConfig(source_content_max_chars=5),
    )

    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()))
    payload = await notebooklm_resource_notebook_source(
        _ctx(app),
        notebook_id="nb-1",
        source_id="src-1",
    )
    parsed = json.loads(payload)

    assert parsed["content"] == "abcde"
    assert parsed["truncated"] is True
    assert parsed["total_chars"] == 10
    assert parsed["source"]["source_id"] == "src-1"


@pytest.mark.asyncio
async def test_notebooklm_resource_notebook_source_not_found_maps_error() -> None:
    class _SourcesAPI:
        async def get(self, notebook_id: str, source_id: str) -> Source | None:
            return None

        async def get_fulltext(self, notebook_id: str, source_id: str) -> SourceFulltext:
            raise SourceNotFoundError(source_id)

    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()))
    with pytest.raises(MCPToolError) as exc_info:
        await notebooklm_resource_notebook_source(
            _ctx(app),
            notebook_id="nb-1",
            source_id="src-404",
        )

    assert exc_info.value.error_code == "invalid_params"


@pytest.mark.asyncio
async def test_notebooklm_resource_audit_recent_reports_disabled_when_not_configured() -> None:
    app = _FakeAppContext(client=SimpleNamespace())
    payload = await notebooklm_resource_audit_recent(_ctx(app))
    parsed = json.loads(payload)

    assert parsed == {
        "enabled": False,
        "message": "Audit logging is not enabled.",
    }


@pytest.mark.asyncio
async def test_notebooklm_resource_audit_recent_returns_redacted_newest_entries() -> None:
    audit = AuditLog(max_entries=200)
    for idx in range(60):
        audit.record_call(
            tool_name=f"tool_{idx}",
            duration_ms=idx,
            status="ok",
            args={
                "notebook_id": f"nb-{idx}",
                "cookies": f"secret-cookie-{idx}",
                "custom_prompt": "TOP SECRET PROMPT",
            },
            timestamp=f"2026-03-05T12:00:{idx % 60:02d}Z",
        )

    app = _FakeAppContext(client=SimpleNamespace(),)
    setattr(app, "audit", audit)
    payload = await notebooklm_resource_audit_recent(_ctx(app))
    parsed = json.loads(payload)

    assert isinstance(parsed, list)
    assert len(parsed) == 50
    assert parsed[0]["tool_name"] == "tool_59"
    assert parsed[-1]["tool_name"] == "tool_10"
    merged = json.dumps(parsed, ensure_ascii=False)
    assert "TOP SECRET PROMPT" not in merged
    assert "secret-cookie-" not in merged


def test_register_resources_registers_all_uris() -> None:
    class _FakeServer:
        def __init__(self) -> None:
            self.registered: dict[str, Any] = {}

        def resource(self, uri: str):
            def _decorator(fn):
                self.registered[uri] = fn
                return fn

            return _decorator

    server = _FakeServer()
    register_resources(server)

    assert set(server.registered) == {
        "notebooklm://audit/recent",
        "notebooklm://notebooks",
        "notebooklm://notebooks/{notebook_id}",
        "notebooklm://notebooks/{notebook_id}/sources/{source_id}",
    }
