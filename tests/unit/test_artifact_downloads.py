"""Focused tests for the reduced ArtifactsAPI backend surface."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm._artifacts import ArtifactsAPI
from notebooklm.exceptions import ValidationError
from notebooklm.rpc.types import ReportFormat


def make_api() -> tuple[ArtifactsAPI, MagicMock]:
    core = MagicMock()
    core.get_source_ids = AsyncMock(return_value=["src_1", "src_2"])
    core.rpc_call = AsyncMock(return_value=[["art_123"]])
    notes = MagicMock()
    return ArtifactsAPI(core, notes), core


@pytest.mark.asyncio
async def test_generate_report_briefing_doc_uses_supported_prompt() -> None:
    api, core = make_api()

    result = await api.generate_report(
        "nb_123",
        report_format=ReportFormat.BRIEFING_DOC,
        extra_instructions="Focus on launch risks.",
    )

    assert result.task_id == "art_123"
    create_call = core.rpc_call.await_args_list[-1]
    params = create_call.args[1]
    prompt = params[2][7][1][5]
    assert "Executive Summary" in prompt
    assert prompt.endswith("Focus on launch risks.")


@pytest.mark.asyncio
async def test_generate_report_study_guide_uses_supported_prompt() -> None:
    api, core = make_api()

    result = await api.generate_report("nb_123", report_format=ReportFormat.STUDY_GUIDE)

    assert result.task_id == "art_123"
    create_call = core.rpc_call.await_args_list[-1]
    params = create_call.args[1]
    assert params[2][7][1][0] == "Study Guide"


@pytest.mark.asyncio
async def test_generate_report_rejects_removed_formats() -> None:
    api, _ = make_api()

    with pytest.raises(ValidationError) as exc_info:
        await api.generate_report("nb_123", report_format=ReportFormat.BLOG_POST)

    assert "not supported on this branch" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_report_rejects_custom_prompt() -> None:
    api, _ = make_api()

    with pytest.raises(ValidationError) as exc_info:
        await api.generate_report(
            "nb_123",
            report_format=ReportFormat.BRIEFING_DOC,
            custom_prompt="Write it as a screenplay.",
        )

    assert "custom_prompt is not supported" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("generate_video", {"notebook_id": "nb_123"}),
        ("generate_quiz", {"notebook_id": "nb_123"}),
        ("generate_flashcards", {"notebook_id": "nb_123"}),
        ("generate_infographic", {"notebook_id": "nb_123"}),
        ("generate_slide_deck", {"notebook_id": "nb_123"}),
        ("revise_slide", {"notebook_id": "nb_123", "artifact_id": "art_1", "slide_index": 0, "prompt": "Tighten this slide."}),
        ("generate_data_table", {"notebook_id": "nb_123"}),
        ("generate_mind_map", {"notebook_id": "nb_123"}),
    ],
)
async def test_removed_generation_methods_raise_validation_error(
    method_name: str, kwargs: dict[str, object]
) -> None:
    api, _ = make_api()

    with pytest.raises(ValidationError) as exc_info:
        await getattr(api, method_name)(**kwargs)

    assert "not supported on this branch" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("download_audio", {"notebook_id": "nb_123", "output_path": "audio.mp3"}),
        ("download_report", {"notebook_id": "nb_123", "output_path": "report.md"}),
        ("download_data_table", {"notebook_id": "nb_123", "output_path": "table.csv"}),
        ("download_mind_map", {"notebook_id": "nb_123", "output_path": "mind-map.json"}),
        ("export_report", {"notebook_id": "nb_123", "artifact_id": "art_1"}),
        ("export_data_table", {"notebook_id": "nb_123", "artifact_id": "art_1"}),
        ("export", {"notebook_id": "nb_123", "artifact_id": "art_1"}),
    ],
)
async def test_removed_download_and_export_methods_raise_validation_error(
    method_name: str, kwargs: dict[str, object]
) -> None:
    api, _ = make_api()

    with pytest.raises(ValidationError) as exc_info:
        await getattr(api, method_name)(**kwargs)

    assert "not supported on this branch" in str(exc_info.value)
