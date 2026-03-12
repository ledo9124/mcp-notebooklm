"""Unit tests for notebooklm_mcp.tools.artifacts."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm.rpc.types import ExportType, ReportFormat
from notebooklm.types import GenerationStatus
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp.server import AppContext
from notebooklm_mcp.tools.artifacts import register_artifact_tools


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


def test_register_artifact_tools_registers_expected_names() -> None:
    server = _FakeServer()
    handlers = register_artifact_tools(server)

    expected = {
        "notebooklm_reports_generate",
        "notebooklm_reports_wait",
        "notebooklm_reports_download",
        "notebooklm_reports_export",
        "notebooklm_data_tables_generate",
        "notebooklm_data_tables_wait",
        "notebooklm_data_tables_download",
        "notebooklm_data_tables_export",
    }
    assert set(handlers) == expected
    assert set(server.registered) == expected


@pytest.mark.asyncio
async def test_reports_generate_uses_report_format_and_assistive_payload() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.generate_report = AsyncMock(
        return_value=GenerationStatus(task_id="rep-1", status="pending")
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_artifact_tools(server)

    result = await handlers["notebooklm_reports_generate"](
        _make_ctx(app, server),
        notebook_id="nb-1",
        report_format="blog-post",
        source_ids=["src-1", "src-2"],
        language="ja",
        extra_instructions="Focus on risks.",
    )

    client.artifacts.generate_report.assert_awaited_once_with(
        "nb-1",
        report_format=ReportFormat.BLOG_POST,
        source_ids=["src-1", "src-2"],
        language="ja",
        custom_prompt=None,
        extra_instructions="Focus on risks.",
    )
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["artifact_kind"] == "report"  # type: ignore[index]
    assert structured["draft_assistance_only"] is True  # type: ignore[index]
    assert structured["authoritative_for_ba_runner"] is False  # type: ignore[index]
    assert structured["report_format"] == "blog-post"  # type: ignore[index]
    assert _decode_text_result(result) == structured


@pytest.mark.asyncio
async def test_reports_generate_rejects_invalid_custom_contract() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_artifact_tools(server)

    with pytest.raises(MCPToolError, match="custom_prompt is required"):
        await handlers["notebooklm_reports_generate"](
            _make_ctx(app, server),
            notebook_id="nb-1",
            report_format="custom",
        )

    client.artifacts.generate_report.assert_not_called()


@pytest.mark.asyncio
async def test_data_tables_generate_forwards_instruction_contract() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.generate_data_table = AsyncMock(
        return_value=GenerationStatus(task_id="tbl-1", status="in_progress")
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_artifact_tools(server)

    result = await handlers["notebooklm_data_tables_generate"](
        _make_ctx(app, server),
        notebook_id="nb-2",
        instructions="Compare endpoints and dependencies",
        source_ids=["src-a"],
        language="en",
    )

    client.artifacts.generate_data_table.assert_awaited_once_with(
        "nb-2",
        source_ids=["src-a"],
        language="en",
        instructions="Compare endpoints and dependencies",
    )
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["artifact_kind"] == "data_table"  # type: ignore[index]
    assert structured["task_id"] == "tbl-1"  # type: ignore[index]


@pytest.mark.asyncio
async def test_reports_wait_serializes_generation_status() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.wait_for_completion = AsyncMock(
        return_value=GenerationStatus(
            task_id="rep-9",
            status="completed",
            metadata={"url": "https://example.test/report"},
        )
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_artifact_tools(server)

    result = await handlers["notebooklm_reports_wait"](
        _make_ctx(app, server),
        notebook_id="nb-3",
        task_id="rep-9",
        timeout=120,
    )

    client.artifacts.wait_for_completion.assert_awaited_once_with(
        "nb-3",
        "rep-9",
        initial_interval=2.0,
        max_interval=10.0,
        timeout=120,
    )
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["status"] == "completed"  # type: ignore[index]
    assert structured["metadata"] == {"url": "https://example.test/report"}  # type: ignore[index]


@pytest.mark.asyncio
async def test_data_tables_download_returns_saved_path() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.download_data_table = AsyncMock(return_value="/tmp/table.csv")
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_artifact_tools(server)

    result = await handlers["notebooklm_data_tables_download"](
        _make_ctx(app, server),
        notebook_id="nb-4",
        output_path="/tmp/requested.csv",
        artifact_id="tbl-42",
    )

    client.artifacts.download_data_table.assert_awaited_once_with(
        "nb-4",
        "/tmp/requested.csv",
        artifact_id="tbl-42",
    )
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["success"] is True  # type: ignore[index]
    assert structured["output_path"] == "/tmp/table.csv"  # type: ignore[index]
    assert structured["artifact_id"] == "tbl-42"  # type: ignore[index]


@pytest.mark.asyncio
async def test_reports_export_serializes_export_type_and_result() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.export_report = AsyncMock(
        return_value={"url": "https://docs.google.com/document/d/123"}
    )
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_artifact_tools(server)

    result = await handlers["notebooklm_reports_export"](
        _make_ctx(app, server),
        notebook_id="nb-5",
        artifact_id="rep-5",
        title="BA Draft",
        export_type="sheets",
    )

    client.artifacts.export_report.assert_awaited_once_with(
        "nb-5",
        "rep-5",
        title="BA Draft",
        export_type=ExportType.SHEETS,
    )
    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["success"] is True  # type: ignore[index]
    assert structured["export_type"] == "sheets"  # type: ignore[index]
    assert structured["result"] == {"url": "https://docs.google.com/document/d/123"}  # type: ignore[index]


@pytest.mark.asyncio
async def test_data_tables_export_marks_missing_result_as_warning() -> None:
    client = MagicMock()
    client.artifacts = MagicMock()
    client.artifacts.export_data_table = AsyncMock(return_value=None)
    app = _make_app(client)
    server = _FakeServer()
    handlers = register_artifact_tools(server)

    result = await handlers["notebooklm_data_tables_export"](
        _make_ctx(app, server),
        notebook_id="nb-6",
        artifact_id="tbl-9",
        title="Sheet Export",
    )

    structured = result["structuredContent"]  # type: ignore[index]
    assert structured["success"] is False  # type: ignore[index]
    assert structured["export_type"] == "sheets"  # type: ignore[index]
    assert structured["warnings"] == ["Export returned no result payload."]  # type: ignore[index]
