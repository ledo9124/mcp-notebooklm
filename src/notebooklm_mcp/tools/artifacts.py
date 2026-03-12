"""Report and data-table MCP helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any

from notebooklm.exceptions import ValidationError
from notebooklm.rpc.types import ExportType, ReportFormat
from notebooklm.types import GenerationStatus

from .._errors import handle_mcp_errors
from .._mapping import map_from_enum, map_to_enum
from .._result import make_tool_result
from ..server import AppContext

logger = logging.getLogger("notebooklm_mcp.tools.artifacts")


def _resolve_app_context(ctx: MCPContext) -> AppContext:
    request_context = getattr(ctx, "request_context", None)
    app = getattr(request_context, "lifespan_context", None)
    if app is None:
        app = getattr(ctx, "lifespan_context", None)
    if isinstance(app, AppContext):
        return app
    raise RuntimeError("NotebookLM MCP lifespan context is unavailable.")


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value.strip()


def _optional_text(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field=field)


def _optional_source_ids(value: Sequence[str] | None) -> list[str] | None:
    if value is None:
        return None
    return [_require_text(item, field="source_ids[]") for item in value]


def _require_positive(value: float, *, field: str) -> float:
    if value <= 0:
        raise ValidationError(f"{field} must be greater than 0.")
    return value


def _artifact_base_payload(artifact_kind: str) -> dict[str, Any]:
    return {
        "artifact_kind": artifact_kind,
        "draft_assistance_only": True,
        "authoritative_for_ba_runner": False,
    }


def _serialize_generation_status(
    artifact_kind: str,
    status: GenerationStatus,
    *,
    notebook_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _artifact_base_payload(artifact_kind)
    payload.update(
        {
            "notebook_id": notebook_id,
            "task_id": status.task_id,
            "status": status.status,
            "error": status.error,
            "error_code": status.error_code,
            "metadata": status.metadata,
        }
    )
    if extra:
        payload.update(extra)
    return payload


def _serialize_download_result(
    artifact_kind: str,
    *,
    notebook_id: str,
    output_path: str,
    artifact_id: str | None,
) -> dict[str, Any]:
    payload = _artifact_base_payload(artifact_kind)
    payload.update(
        {
            "success": True,
            "notebook_id": notebook_id,
            "artifact_id": artifact_id,
            "output_path": output_path,
        }
    )
    return payload


def _serialize_export_result(
    artifact_kind: str,
    *,
    notebook_id: str,
    artifact_id: str,
    title: str,
    export_type: str,
    result: Any,
) -> dict[str, Any]:
    payload = _artifact_base_payload(artifact_kind)
    payload.update(
        {
            "success": result is not None,
            "notebook_id": notebook_id,
            "artifact_id": artifact_id,
            "title": title,
            "export_type": export_type,
            "result": result,
        }
    )
    if result is None:
        payload["warnings"] = ["Export returned no result payload."]
    return payload


def _require_report_contract(
    report_format: ReportFormat,
    *,
    custom_prompt: str | None,
    extra_instructions: str | None,
) -> tuple[str | None, str | None]:
    clean_prompt = _optional_text(custom_prompt, field="custom_prompt")
    clean_extra = _optional_text(extra_instructions, field="extra_instructions")

    if report_format is ReportFormat.CUSTOM:
        if clean_prompt is None:
            raise ValidationError(
                "custom_prompt is required when report_format is custom."
            )
        if clean_extra is not None:
            raise ValidationError(
                "extra_instructions is not supported when report_format is custom."
            )
        return clean_prompt, None

    if clean_prompt is not None:
        raise ValidationError(
            "custom_prompt is only supported when report_format is custom."
        )

    return None, clean_extra


def _register_tool(
    server: Any,
    *,
    name: str,
    description: str,
    handler: Callable[..., Any],
) -> None:
    tool_factory = getattr(server, "tool", None)
    if not callable(tool_factory):
        logger.warning("Cannot register tool %s: server has no callable tool()", name)
        return

    for kwargs in (
        {"name": name, "description": description},
        {"name": name},
        {},
    ):
        try:
            decorator = tool_factory(**kwargs)
        except TypeError:
            continue

        if not callable(decorator):
            continue

        decorator(handler)
        return

    raise RuntimeError(f"Failed to register MCP tool: {name}")


def register_artifact_tools(server: Any) -> dict[str, Callable[..., Any]]:
    """Register report and data-table helper tools."""

    @handle_mcp_errors
    async def notebooklm_reports_generate(
        ctx: MCPContext,
        notebook_id: str,
        report_format: str = "briefing-doc",
        source_ids: list[str] | None = None,
        language: str = "en",
        custom_prompt: str | None = None,
        extra_instructions: str | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_language = _require_text(language, field="language")
        normalized_format = map_to_enum(
            report_format,
            ReportFormat,
            field_name="report_format",
        )
        clean_prompt, clean_extra = _require_report_contract(
            normalized_format,
            custom_prompt=custom_prompt,
            extra_instructions=extra_instructions,
        )
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            status = await app.client.artifacts.generate_report(
                clean_notebook_id,
                report_format=normalized_format,
                source_ids=_optional_source_ids(source_ids),
                language=clean_language,
                custom_prompt=clean_prompt,
                extra_instructions=clean_extra,
            )
        return make_tool_result(
            _serialize_generation_status(
                "report",
                status,
                notebook_id=clean_notebook_id,
                extra={"report_format": map_from_enum(normalized_format)},
            )
        )

    @handle_mcp_errors
    async def notebooklm_data_tables_generate(
        ctx: MCPContext,
        notebook_id: str,
        instructions: str,
        source_ids: list[str] | None = None,
        language: str = "en",
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_instructions = _require_text(instructions, field="instructions")
        clean_language = _require_text(language, field="language")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            status = await app.client.artifacts.generate_data_table(
                clean_notebook_id,
                source_ids=_optional_source_ids(source_ids),
                language=clean_language,
                instructions=clean_instructions,
            )
        return make_tool_result(
            _serialize_generation_status(
                "data_table",
                status,
                notebook_id=clean_notebook_id,
            )
        )

    @handle_mcp_errors
    async def notebooklm_reports_wait(
        ctx: MCPContext,
        notebook_id: str,
        task_id: str,
        initial_interval: float = 2.0,
        max_interval: float = 10.0,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_task_id = _require_text(task_id, field="task_id")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            status = await app.client.artifacts.wait_for_completion(
                clean_notebook_id,
                clean_task_id,
                initial_interval=_require_positive(
                    initial_interval, field="initial_interval"
                ),
                max_interval=_require_positive(max_interval, field="max_interval"),
                timeout=_require_positive(timeout, field="timeout"),
            )
        return make_tool_result(
            _serialize_generation_status(
                "report",
                status,
                notebook_id=clean_notebook_id,
            )
        )

    @handle_mcp_errors
    async def notebooklm_data_tables_wait(
        ctx: MCPContext,
        notebook_id: str,
        task_id: str,
        initial_interval: float = 2.0,
        max_interval: float = 10.0,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_task_id = _require_text(task_id, field="task_id")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            status = await app.client.artifacts.wait_for_completion(
                clean_notebook_id,
                clean_task_id,
                initial_interval=_require_positive(
                    initial_interval, field="initial_interval"
                ),
                max_interval=_require_positive(max_interval, field="max_interval"),
                timeout=_require_positive(timeout, field="timeout"),
            )
        return make_tool_result(
            _serialize_generation_status(
                "data_table",
                status,
                notebook_id=clean_notebook_id,
            )
        )

    @handle_mcp_errors
    async def notebooklm_reports_download(
        ctx: MCPContext,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_output_path = _require_text(output_path, field="output_path")
        clean_artifact_id = _optional_text(artifact_id, field="artifact_id")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            saved_path = await app.client.artifacts.download_report(
                clean_notebook_id,
                clean_output_path,
                artifact_id=clean_artifact_id,
            )
        return make_tool_result(
            _serialize_download_result(
                "report",
                notebook_id=clean_notebook_id,
                output_path=saved_path,
                artifact_id=clean_artifact_id,
            )
        )

    @handle_mcp_errors
    async def notebooklm_data_tables_download(
        ctx: MCPContext,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_output_path = _require_text(output_path, field="output_path")
        clean_artifact_id = _optional_text(artifact_id, field="artifact_id")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            saved_path = await app.client.artifacts.download_data_table(
                clean_notebook_id,
                clean_output_path,
                artifact_id=clean_artifact_id,
            )
        return make_tool_result(
            _serialize_download_result(
                "data_table",
                notebook_id=clean_notebook_id,
                output_path=saved_path,
                artifact_id=clean_artifact_id,
            )
        )

    @handle_mcp_errors
    async def notebooklm_reports_export(
        ctx: MCPContext,
        notebook_id: str,
        artifact_id: str,
        title: str = "Export",
        export_type: str = "docs",
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_artifact_id = _require_text(artifact_id, field="artifact_id")
        clean_title = _require_text(title, field="title")
        normalized_export_type = map_to_enum(
            export_type,
            ExportType,
            field_name="export_type",
        )
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            result = await app.client.artifacts.export_report(
                clean_notebook_id,
                clean_artifact_id,
                title=clean_title,
                export_type=normalized_export_type,
            )
        return make_tool_result(
            _serialize_export_result(
                "report",
                notebook_id=clean_notebook_id,
                artifact_id=clean_artifact_id,
                title=clean_title,
                export_type=map_from_enum(normalized_export_type),
                result=result,
            )
        )

    @handle_mcp_errors
    async def notebooklm_data_tables_export(
        ctx: MCPContext,
        notebook_id: str,
        artifact_id: str,
        title: str = "Export",
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_artifact_id = _require_text(artifact_id, field="artifact_id")
        clean_title = _require_text(title, field="title")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            result = await app.client.artifacts.export_data_table(
                clean_notebook_id,
                clean_artifact_id,
                title=clean_title,
            )
        return make_tool_result(
            _serialize_export_result(
                "data_table",
                notebook_id=clean_notebook_id,
                artifact_id=clean_artifact_id,
                title=clean_title,
                export_type="sheets",
                result=result,
            )
        )

    handlers: dict[str, Callable[..., Any]] = {
        "notebooklm_reports_generate": notebooklm_reports_generate,
        "notebooklm_reports_wait": notebooklm_reports_wait,
        "notebooklm_reports_download": notebooklm_reports_download,
        "notebooklm_reports_export": notebooklm_reports_export,
        "notebooklm_data_tables_generate": notebooklm_data_tables_generate,
        "notebooklm_data_tables_wait": notebooklm_data_tables_wait,
        "notebooklm_data_tables_download": notebooklm_data_tables_download,
        "notebooklm_data_tables_export": notebooklm_data_tables_export,
    }

    descriptions = {
        "notebooklm_reports_generate": (
            "Generate a NotebookLM report artifact for draft assistance only."
        ),
        "notebooklm_reports_wait": (
            "Wait for a NotebookLM report generation task to finish."
        ),
        "notebooklm_reports_download": (
            "Download a completed NotebookLM report artifact."
        ),
        "notebooklm_reports_export": (
            "Export a NotebookLM report artifact to Google Docs or Sheets."
        ),
        "notebooklm_data_tables_generate": (
            "Generate a NotebookLM data-table artifact for draft assistance only."
        ),
        "notebooklm_data_tables_wait": (
            "Wait for a NotebookLM data-table generation task to finish."
        ),
        "notebooklm_data_tables_download": (
            "Download a completed NotebookLM data-table artifact."
        ),
        "notebooklm_data_tables_export": (
            "Export a NotebookLM data-table artifact to Google Sheets."
        ),
    }

    for name, handler in handlers.items():
        _register_tool(
            server,
            name=name,
            description=descriptions[name],
            handler=handler,
        )

    return handlers


__all__ = ["register_artifact_tools"]
