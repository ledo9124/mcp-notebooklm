"""Integration tests for notebooklm_mcp handler flow with VCR replay/record.

These tests exercise MCP tool handlers with a real NotebookLM client under VCR.
They are skipped when cassettes are unavailable unless NOTEBOOKLM_VCR_RECORD=1.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# Add tests directory to path for vcr_config import
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from conftest import get_vcr_auth, skip_no_cassettes  # noqa: E402
from notebooklm import NotebookLMClient  # noqa: E402
from notebooklm_mcp._config import MCPConfig  # noqa: E402
from notebooklm_mcp._errors import MCPToolError  # noqa: E402
from notebooklm_mcp.server import AppContext  # noqa: E402
from notebooklm_mcp.tools import register_tools  # noqa: E402
from vcr_config import notebooklm_vcr  # noqa: E402

pytestmark = [pytest.mark.vcr, skip_no_cassettes]


class _FakeServer:
    def __init__(self, config: MCPConfig | None = None) -> None:
        self._notebooklm_mcp_config = config or MCPConfig()
        self.tools: dict[str, Any] = {}

    def tool(self, *, name: str | None = None, description: str | None = None):  # pragma: no cover
        assert isinstance(description, str) or description is None

        def _decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return _decorator


def _ctx(app: AppContext, server: _FakeServer) -> Any:
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=app,
            server=server,
        )
    )


def _tool_payload(result: dict[str, Any]) -> dict[str, Any]:
    payload = result["structuredContent"]
    text_payload = result["content"][0]["text"]
    assert isinstance(payload, dict)
    assert isinstance(text_payload, str)
    assert json.loads(text_payload) == payload
    return payload


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_mcp_tool_workflow_record_replay() -> None:
    """Exercise an end-to-end MCP tool workflow against recorded/live API traffic."""
    auth = await get_vcr_auth()
    server = _FakeServer(MCPConfig(enable_destructive_tools=True))
    register_tools(server)

    async with NotebookLMClient(auth) as client:
        app = AppContext(  # type: ignore[arg-type]
            client=client,
            semaphore=asyncio.Semaphore(3),
            max_inflight=3,
        )
        ctx = _ctx(app, server)

        with notebooklm_vcr.use_cassette("notebooks_create.yaml"):
            created = await server.tools["notebooklm_notebooks_create"](ctx, title="MCP VCR Integration")
        created_payload = _tool_payload(created)
        notebook_id = str(created_payload["notebook_id"])
        assert notebook_id

        with notebooklm_vcr.use_cassette("sources_add_text.yaml"):
            add_text = await server.tools["notebooklm_sources_add_text"](
                ctx,
                notebook_id=notebook_id,
                title="MCP Integration Seed",
                content="Integration content for MCP replay.",
            )
        add_text_payload = _tool_payload(add_text)
        assert str(add_text_payload["source_id"])
        assert isinstance(add_text_payload["status"], str)

        with notebooklm_vcr.use_cassette("sources_list.yaml"):
            listed = await server.tools["notebooklm_sources_list"](ctx, notebook_id=notebook_id)
        listed_payload = _tool_payload(listed)
        assert isinstance(listed_payload["sources"], list)
        if not listed_payload["sources"]:
            pytest.skip("No sources returned in replay cassette")
        source_id = str(listed_payload["sources"][0]["source_id"])
        assert source_id

        with notebooklm_vcr.use_cassette("sources_get_fulltext.yaml"):
            try:
                content = await server.tools["notebooklm_sources_get_content"](
                    ctx,
                    notebook_id=notebook_id,
                    source_id=source_id,
                    max_chars=2_000,
                )
            except MCPToolError:
                pytest.skip("Fulltext replay cassette does not match dynamic source identity")
        content_payload = _tool_payload(content)
        assert isinstance(content_payload["content"], str)
        assert isinstance(content_payload["truncated"], bool)

        with notebooklm_vcr.use_cassette("chat_ask.yaml"):
            answer = await server.tools["notebooklm_chat_ask"](
                ctx,
                notebook_id=notebook_id,
                question="Give a concise summary.",
            )
        answer_payload = _tool_payload(answer)
        assert isinstance(answer_payload["answer"], str)
        assert isinstance(answer_payload["citations"], list)

        with notebooklm_vcr.use_cassette("notebooks_delete.yaml"):
            deleted = await server.tools["notebooklm_notebooks_delete"](
                ctx,
                notebook_id=notebook_id,
                confirm=True,
            )
        deleted_payload = _tool_payload(deleted)
        assert deleted_payload["success"] is True


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_mcp_add_file_tool_record_replay() -> None:
    """Verify base64 file upload path works through MCP handler + VCR replay."""
    auth = await get_vcr_auth()
    server = _FakeServer()
    register_tools(server)

    async with NotebookLMClient(auth) as client:
        app = AppContext(  # type: ignore[arg-type]
            client=client,
            semaphore=asyncio.Semaphore(2),
            max_inflight=2,
        )
        ctx = _ctx(app, server)

        with notebooklm_vcr.use_cassette("notebooks_list.yaml"):
            listed = await server.tools["notebooklm_notebooks_list"](ctx)
        listed_payload = _tool_payload(listed)
        if not listed_payload["notebooks"]:
            pytest.skip("No notebooks available in replay cassette")
        notebook_id = str(listed_payload["notebooks"][0]["notebook_id"])

        with notebooklm_vcr.use_cassette("sources_add_file.yaml"):
            uploaded = await server.tools["notebooklm_sources_add_file"](
                ctx,
                notebook_id=notebook_id,
                filename="mcp-upload.txt",
                mime_type="text/plain",
                data_base64=base64.b64encode(b"hello from mcp integration").decode("ascii"),
            )
        uploaded_payload = _tool_payload(uploaded)
        assert str(uploaded_payload["source_id"])
        assert isinstance(uploaded_payload["status"], str)
