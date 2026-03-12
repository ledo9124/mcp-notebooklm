"""Experimental MCP helpers for optional non-core NotebookLM artifacts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any

from notebooklm.exceptions import ValidationError
from notebooklm.rpc.types import (
    AudioFormat,
    AudioLength,
    InfographicDetail,
    InfographicOrientation,
    SlideDeckFormat,
    SlideDeckLength,
    VideoFormat,
    VideoStyle,
)

from .._errors import handle_mcp_errors
from .._mapping import map_from_enum, map_to_enum
from .._result import make_tool_result
from .artifacts import (
    _optional_source_ids,
    _optional_text,
    _register_tool,
    _require_positive,
    _require_text,
    _resolve_app_context,
)

_EXPERIMENTAL_GUIDANCE = (
    "These artifact helpers are optional, experimental, and off the BA runner "
    "critical path. Do not treat them as required or production-stable BA "
    "workflow outputs."
)


def _optional_enum(
    value: str | None,
    enum_class: type[Any],
    *,
    field_name: str,
) -> Any | None:
    if value is None:
        return None
    return map_to_enum(value, enum_class, field_name=field_name)


def _finalize_payload(artifact_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    finalized = {
        "artifact_kind": artifact_kind,
        "draft_assistance_only": True,
        "authoritative_for_ba_runner": False,
        "critical_path": False,
        "experimental": True,
        "stability": "experimental_optional",
        "usage_guidance": _EXPERIMENTAL_GUIDANCE,
    }
    finalized.update(payload)
    warnings = list(finalized.get("warnings", []))
    if _EXPERIMENTAL_GUIDANCE not in warnings:
        warnings.append(_EXPERIMENTAL_GUIDANCE)
    finalized["warnings"] = warnings
    return finalized


def _serialize_generation_status(
    artifact_kind: str,
    *,
    notebook_id: str,
    status: Any,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "notebook_id": notebook_id,
        "task_id": status.task_id,
        "status": status.status,
        "error": status.error,
        "error_code": status.error_code,
        "metadata": status.metadata,
    }
    if extra:
        payload.update(extra)
    return _finalize_payload(artifact_kind, payload)


def _serialize_download_result(
    artifact_kind: str,
    *,
    notebook_id: str,
    output_path: str,
    artifact_id: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "success": True,
        "notebook_id": notebook_id,
        "artifact_id": artifact_id,
        "output_path": output_path,
    }
    if extra:
        payload.update(extra)
    return _finalize_payload(artifact_kind, payload)


def _build_wait_handler(tool_name: str, artifact_kind: str) -> Callable[..., Any]:
    @handle_mcp_errors
    async def _handler(
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
                artifact_kind,
                notebook_id=clean_notebook_id,
                status=status,
            )
        )

    _handler.__name__ = tool_name
    return _handler


def _build_download_handler(
    tool_name: str,
    artifact_kind: str,
    *,
    download_method_name: str,
) -> Callable[..., Any]:
    @handle_mcp_errors
    async def _handler(
        ctx: MCPContext,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_output_path = _require_text(output_path, field="output_path")
        clean_artifact_id = _optional_text(artifact_id, field="artifact_id")
        app = _resolve_app_context(ctx)
        download_method = getattr(app.client.artifacts, download_method_name)
        async with app.acquire_slot():
            saved_path = await download_method(
                clean_notebook_id,
                clean_output_path,
                artifact_id=clean_artifact_id,
            )
        return make_tool_result(
            _serialize_download_result(
                artifact_kind,
                notebook_id=clean_notebook_id,
                output_path=saved_path,
                artifact_id=clean_artifact_id,
            )
        )

    _handler.__name__ = tool_name
    return _handler


def register_experimental_artifact_tools(
    server: Any,
) -> dict[str, Callable[..., Any]]:
    """Register experimental optional-artifact helpers."""

    @handle_mcp_errors
    async def notebooklm_audio_overviews_generate(
        ctx: MCPContext,
        notebook_id: str,
        source_ids: list[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
        audio_format: str | None = None,
        audio_length: str | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_source_ids = _optional_source_ids(source_ids)
        clean_language = _require_text(language, field="language")
        clean_instructions = _optional_text(instructions, field="instructions")
        normalized_format = _optional_enum(
            audio_format,
            AudioFormat,
            field_name="audio_format",
        )
        normalized_length = _optional_enum(
            audio_length,
            AudioLength,
            field_name="audio_length",
        )
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            status = await app.client.artifacts.generate_audio(
                clean_notebook_id,
                source_ids=clean_source_ids,
                language=clean_language,
                instructions=clean_instructions,
                audio_format=normalized_format,
                audio_length=normalized_length,
            )
        return make_tool_result(
            _serialize_generation_status(
                "audio",
                notebook_id=clean_notebook_id,
                status=status,
                extra={
                    "source_ids": clean_source_ids or [],
                    "language": clean_language,
                    "instructions": clean_instructions,
                    "audio_format": (
                        map_from_enum(normalized_format)
                        if normalized_format is not None
                        else None
                    ),
                    "audio_length": (
                        map_from_enum(normalized_length)
                        if normalized_length is not None
                        else None
                    ),
                },
            )
        )

    @handle_mcp_errors
    async def notebooklm_video_overviews_generate(
        ctx: MCPContext,
        notebook_id: str,
        source_ids: list[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
        video_format: str | None = None,
        video_style: str | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_source_ids = _optional_source_ids(source_ids)
        clean_language = _require_text(language, field="language")
        clean_instructions = _optional_text(instructions, field="instructions")
        normalized_format = _optional_enum(
            video_format,
            VideoFormat,
            field_name="video_format",
        )
        normalized_style = _optional_enum(
            video_style,
            VideoStyle,
            field_name="video_style",
        )
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            status = await app.client.artifacts.generate_video(
                clean_notebook_id,
                source_ids=clean_source_ids,
                language=clean_language,
                instructions=clean_instructions,
                video_format=normalized_format,
                video_style=normalized_style,
            )
        return make_tool_result(
            _serialize_generation_status(
                "video",
                notebook_id=clean_notebook_id,
                status=status,
                extra={
                    "source_ids": clean_source_ids or [],
                    "language": clean_language,
                    "instructions": clean_instructions,
                    "video_format": (
                        map_from_enum(normalized_format)
                        if normalized_format is not None
                        else None
                    ),
                    "video_style": (
                        map_from_enum(normalized_style)
                        if normalized_style is not None
                        else None
                    ),
                },
            )
        )

    @handle_mcp_errors
    async def notebooklm_infographics_generate(
        ctx: MCPContext,
        notebook_id: str,
        source_ids: list[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
        orientation: str | None = None,
        detail_level: str | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_source_ids = _optional_source_ids(source_ids)
        clean_language = _require_text(language, field="language")
        clean_instructions = _optional_text(instructions, field="instructions")
        normalized_orientation = _optional_enum(
            orientation,
            InfographicOrientation,
            field_name="orientation",
        )
        normalized_detail = _optional_enum(
            detail_level,
            InfographicDetail,
            field_name="detail_level",
        )
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            status = await app.client.artifacts.generate_infographic(
                clean_notebook_id,
                source_ids=clean_source_ids,
                language=clean_language,
                instructions=clean_instructions,
                orientation=normalized_orientation,
                detail_level=normalized_detail,
            )
        return make_tool_result(
            _serialize_generation_status(
                "infographic",
                notebook_id=clean_notebook_id,
                status=status,
                extra={
                    "source_ids": clean_source_ids or [],
                    "language": clean_language,
                    "instructions": clean_instructions,
                    "orientation": (
                        map_from_enum(normalized_orientation)
                        if normalized_orientation is not None
                        else None
                    ),
                    "detail_level": (
                        map_from_enum(normalized_detail)
                        if normalized_detail is not None
                        else None
                    ),
                },
            )
        )

    @handle_mcp_errors
    async def notebooklm_slide_decks_generate(
        ctx: MCPContext,
        notebook_id: str,
        source_ids: list[str] | None = None,
        language: str = "en",
        instructions: str | None = None,
        slide_format: str | None = None,
        slide_length: str | None = None,
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_source_ids = _optional_source_ids(source_ids)
        clean_language = _require_text(language, field="language")
        clean_instructions = _optional_text(instructions, field="instructions")
        normalized_format = _optional_enum(
            slide_format,
            SlideDeckFormat,
            field_name="slide_format",
        )
        normalized_length = _optional_enum(
            slide_length,
            SlideDeckLength,
            field_name="slide_length",
        )
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            status = await app.client.artifacts.generate_slide_deck(
                clean_notebook_id,
                source_ids=clean_source_ids,
                language=clean_language,
                instructions=clean_instructions,
                slide_format=normalized_format,
                slide_length=normalized_length,
            )
        return make_tool_result(
            _serialize_generation_status(
                "slide_deck",
                notebook_id=clean_notebook_id,
                status=status,
                extra={
                    "source_ids": clean_source_ids or [],
                    "language": clean_language,
                    "instructions": clean_instructions,
                    "slide_format": (
                        map_from_enum(normalized_format)
                        if normalized_format is not None
                        else None
                    ),
                    "slide_length": (
                        map_from_enum(normalized_length)
                        if normalized_length is not None
                        else None
                    ),
                },
            )
        )

    notebooklm_audio_overviews_wait = _build_wait_handler(
        "notebooklm_audio_overviews_wait",
        "audio",
    )
    notebooklm_video_overviews_wait = _build_wait_handler(
        "notebooklm_video_overviews_wait",
        "video",
    )
    notebooklm_infographics_wait = _build_wait_handler(
        "notebooklm_infographics_wait",
        "infographic",
    )
    notebooklm_slide_decks_wait = _build_wait_handler(
        "notebooklm_slide_decks_wait",
        "slide_deck",
    )

    notebooklm_audio_overviews_download = _build_download_handler(
        "notebooklm_audio_overviews_download",
        "audio",
        download_method_name="download_audio",
    )
    notebooklm_video_overviews_download = _build_download_handler(
        "notebooklm_video_overviews_download",
        "video",
        download_method_name="download_video",
    )
    notebooklm_infographics_download = _build_download_handler(
        "notebooklm_infographics_download",
        "infographic",
        download_method_name="download_infographic",
    )

    @handle_mcp_errors
    async def notebooklm_slide_decks_download(
        ctx: MCPContext,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        output_format: str = "pdf",
    ) -> dict[str, Any]:
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_output_path = _require_text(output_path, field="output_path")
        clean_artifact_id = _optional_text(artifact_id, field="artifact_id")
        clean_output_format = _require_text(
            output_format,
            field="output_format",
        ).casefold()
        if clean_output_format not in {"pdf", "pptx"}:
            raise ValidationError("output_format must be one of: pdf, pptx.")
        app = _resolve_app_context(ctx)
        async with app.acquire_slot():
            saved_path = await app.client.artifacts.download_slide_deck(
                clean_notebook_id,
                clean_output_path,
                artifact_id=clean_artifact_id,
                output_format=clean_output_format,
            )
        return make_tool_result(
            _serialize_download_result(
                "slide_deck",
                notebook_id=clean_notebook_id,
                output_path=saved_path,
                artifact_id=clean_artifact_id,
                extra={"output_format": clean_output_format},
            )
        )

    handlers: dict[str, Callable[..., Any]] = {
        "notebooklm_audio_overviews_generate": notebooklm_audio_overviews_generate,
        "notebooklm_audio_overviews_wait": notebooklm_audio_overviews_wait,
        "notebooklm_audio_overviews_download": notebooklm_audio_overviews_download,
        "notebooklm_video_overviews_generate": notebooklm_video_overviews_generate,
        "notebooklm_video_overviews_wait": notebooklm_video_overviews_wait,
        "notebooklm_video_overviews_download": notebooklm_video_overviews_download,
        "notebooklm_infographics_generate": notebooklm_infographics_generate,
        "notebooklm_infographics_wait": notebooklm_infographics_wait,
        "notebooklm_infographics_download": notebooklm_infographics_download,
        "notebooklm_slide_decks_generate": notebooklm_slide_decks_generate,
        "notebooklm_slide_decks_wait": notebooklm_slide_decks_wait,
        "notebooklm_slide_decks_download": notebooklm_slide_decks_download,
    }

    descriptions = {
        "notebooklm_audio_overviews_generate": (
            "Generate an experimental audio overview artifact for optional draft assistance only."
        ),
        "notebooklm_audio_overviews_wait": (
            "Wait for an experimental audio overview generation task to finish."
        ),
        "notebooklm_audio_overviews_download": (
            "Download an experimental audio overview artifact."
        ),
        "notebooklm_video_overviews_generate": (
            "Generate an experimental video overview artifact for optional draft assistance only."
        ),
        "notebooklm_video_overviews_wait": (
            "Wait for an experimental video overview generation task to finish."
        ),
        "notebooklm_video_overviews_download": (
            "Download an experimental video overview artifact."
        ),
        "notebooklm_infographics_generate": (
            "Generate an experimental infographic artifact for optional draft assistance only."
        ),
        "notebooklm_infographics_wait": (
            "Wait for an experimental infographic generation task to finish."
        ),
        "notebooklm_infographics_download": (
            "Download an experimental infographic artifact."
        ),
        "notebooklm_slide_decks_generate": (
            "Generate an experimental slide deck artifact for optional draft assistance only."
        ),
        "notebooklm_slide_decks_wait": (
            "Wait for an experimental slide deck generation task to finish."
        ),
        "notebooklm_slide_decks_download": (
            "Download an experimental slide deck artifact."
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


__all__ = ["register_experimental_artifact_tools"]
