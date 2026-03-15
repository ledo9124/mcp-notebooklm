"""Unit tests for the retained summarize workflow helper."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from notebooklm.types import ReportFormat
from notebooklm.workflows.summarize import (
    combine_report_instructions,
    display_name_for_report_format,
    run_summarize_workflow,
)


def test_combine_report_instructions_returns_none_when_empty():
    assert (
        combine_report_instructions(
            description=None,
            append_instructions=None,
        )
        is None
    )


def test_combine_report_instructions_joins_retained_prompt_parts():
    extra_instructions = combine_report_instructions(
        description="Focus on the key decisions.",
        append_instructions="Target audience: exec staff.",
    )

    assert extra_instructions == "Focus on the key decisions.\n\nTarget audience: exec staff."


def test_display_name_for_report_format_uses_supported_values():
    assert display_name_for_report_format(ReportFormat.BRIEFING_DOC) == "briefing document"
    assert display_name_for_report_format(ReportFormat.STUDY_GUIDE) == "study guide"


def test_display_name_for_report_format_rejects_unsupported_values():
    with pytest.raises(ValueError, match="Unsupported summarize report format"):
        display_name_for_report_format(ReportFormat.BLOG_POST)


@pytest.mark.asyncio
async def test_run_summarize_workflow_resolves_inputs_and_starts_report_generation():
    client = SimpleNamespace(
        artifacts=SimpleNamespace(
            generate_report=AsyncMock(return_value={"task_id": "report_123", "status": "processing"})
        )
    )
    resolve_notebook_id = AsyncMock(return_value="nb_123")
    resolve_source_ids = AsyncMock(return_value=["src_1", "src_2"])
    retry_calls: list[tuple[int, str, bool]] = []

    async def fake_generate_with_retry(generate_fn, max_retries, artifact_type, json_output):
        retry_calls.append((max_retries, artifact_type, json_output))
        return await generate_fn()

    workflow_result = await run_summarize_workflow(
        client,
        notebook_id="nb_partial",
        source_ids=("src_1", "src_2"),
        language="en",
        report_format=ReportFormat.BRIEFING_DOC,
        description="Focus on AI trends",
        append_instructions="Target audience: beginners",
        max_retries=2,
        json_output=True,
        resolve_notebook_id=resolve_notebook_id,
        resolve_source_ids=resolve_source_ids,
        generate_with_retry=fake_generate_with_retry,
    )

    assert workflow_result.result == {"task_id": "report_123", "status": "processing"}
    assert workflow_result.resolved_notebook_id == "nb_123"
    assert workflow_result.resolved_source_ids == ["src_1", "src_2"]
    assert workflow_result.extra_instructions == (
        "Focus on AI trends\n\nTarget audience: beginners"
    )
    assert workflow_result.format_display == "briefing document"
    assert retry_calls == [(2, "briefing document", True)]
    client.artifacts.generate_report.assert_awaited_once_with(
        "nb_123",
        source_ids=["src_1", "src_2"],
        language="en",
        report_format=ReportFormat.BRIEFING_DOC,
        extra_instructions="Focus on AI trends\n\nTarget audience: beginners",
    )


@pytest.mark.asyncio
async def test_run_summarize_workflow_preserves_study_guide_without_extra_prompt():
    client = SimpleNamespace(
        artifacts=SimpleNamespace(
            generate_report=AsyncMock(return_value={"artifact_id": "report_456", "status": "pending"})
        )
    )

    async def fake_generate_with_retry(generate_fn, *_args):
        return await generate_fn()

    workflow_result = await run_summarize_workflow(
        client,
        notebook_id="nb_456",
        source_ids=(),
        language="fr",
        report_format=ReportFormat.STUDY_GUIDE,
        description=None,
        append_instructions=None,
        max_retries=0,
        json_output=False,
        resolve_notebook_id=AsyncMock(return_value="nb_456"),
        resolve_source_ids=AsyncMock(return_value=None),
        generate_with_retry=fake_generate_with_retry,
    )

    assert workflow_result.extra_instructions is None
    assert workflow_result.format_display == "study guide"
    client.artifacts.generate_report.assert_awaited_once_with(
        "nb_456",
        source_ids=None,
        language="fr",
        report_format=ReportFormat.STUDY_GUIDE,
        extra_instructions=None,
    )
