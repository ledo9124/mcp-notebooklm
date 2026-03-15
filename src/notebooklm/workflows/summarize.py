"""Internal workflow helpers for retained summarize/report generation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from notebooklm.types import ReportFormat
from .runtime import ResolveNotebookId, ResolveSourceIds

RetryGeneration = Callable[[Callable[[], Awaitable[Any]], int, str, bool], Awaitable[Any]]

_FORMAT_DISPLAY = {
    ReportFormat.BRIEFING_DOC: "briefing document",
    ReportFormat.STUDY_GUIDE: "study guide",
}


@dataclass(frozen=True)
class SummarizeWorkflowResult:
    """Result of preparing and starting one retained report-generation flow."""

    result: Any
    resolved_notebook_id: str
    resolved_source_ids: list[str] | None
    extra_instructions: str | None
    format_display: str


def combine_report_instructions(
    *,
    description: str | None,
    append_instructions: str | None,
) -> str | None:
    """Merge the retained prompt extension inputs into one report prompt suffix."""

    extra_parts = [part for part in (description, append_instructions) if part]
    return "\n\n".join(extra_parts) if extra_parts else None


def display_name_for_report_format(report_format: ReportFormat) -> str:
    """Return the human-facing artifact label for one supported report format."""

    try:
        return _FORMAT_DISPLAY[report_format]
    except KeyError as exc:  # pragma: no cover - defensive guard for future callers
        raise ValueError(f"Unsupported summarize report format: {report_format!r}") from exc


async def run_summarize_workflow(
    client: Any,
    *,
    notebook_id: str,
    source_ids: tuple[str, ...],
    language: str,
    report_format: ReportFormat,
    description: str | None,
    append_instructions: str | None,
    max_retries: int,
    json_output: bool,
    resolve_notebook_id: ResolveNotebookId,
    resolve_source_ids: ResolveSourceIds,
    generate_with_retry: RetryGeneration,
) -> SummarizeWorkflowResult:
    """Resolve retained summarize inputs and start report generation."""

    resolved_notebook_id = await resolve_notebook_id(client, notebook_id)
    resolved_source_ids = await resolve_source_ids(client, resolved_notebook_id, source_ids)
    extra_instructions = combine_report_instructions(
        description=description,
        append_instructions=append_instructions,
    )
    format_display = display_name_for_report_format(report_format)

    async def _generate():
        return await client.artifacts.generate_report(
            resolved_notebook_id,
            source_ids=resolved_source_ids,
            language=language,
            report_format=report_format,
            extra_instructions=extra_instructions,
        )

    result = await generate_with_retry(
        _generate,
        max_retries,
        format_display,
        json_output,
    )
    return SummarizeWorkflowResult(
        result=result,
        resolved_notebook_id=resolved_notebook_id,
        resolved_source_ids=resolved_source_ids,
        extra_instructions=extra_instructions,
        format_display=format_display,
    )


__all__ = [
    "SummarizeWorkflowResult",
    "combine_report_instructions",
    "display_name_for_report_format",
    "run_summarize_workflow",
]
