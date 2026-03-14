"""Integration tests for the retained ArtifactsAPI MVP contract."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_httpx import HTTPXMock

from notebooklm import NotebookLMClient
from notebooklm.exceptions import ValidationError
from notebooklm.rpc import AudioFormat, AudioLength, RPCError, RPCMethod, ReportFormat


def _build_notebook_payload(*source_ids: str) -> list[list[object]]:
    source_entries = [
        [[source_id], f"Source {index}", [None, 0], [None, 2]]
        for index, source_id in enumerate(source_ids, start=1)
    ]
    return [
        [
            "Test Notebook",
            source_entries,
            "nb_123",
            "📘",
            None,
            [None, None, None, None, None, [1704067200, 0]],
        ]
    ]


def _queue_generation(
    httpx_mock: HTTPXMock,
    build_rpc_response,
    *,
    artifact_id: str,
    title: str,
    source_ids: tuple[str, ...] = ("src_001",),
    status_code: int = 1,
) -> None:
    notebook_response = build_rpc_response(
        RPCMethod.GET_NOTEBOOK,
        _build_notebook_payload(*source_ids),
    )
    generation_response = build_rpc_response(
        RPCMethod.CREATE_ARTIFACT,
        [[artifact_id, title, "2024-01-05", None, status_code]],
    )
    httpx_mock.add_response(content=notebook_response.encode())
    httpx_mock.add_response(content=generation_response.encode())


def _list_response(build_rpc_response, *artifacts: list[object]) -> str:
    return build_rpc_response(RPCMethod.LIST_ARTIFACTS, [list(artifacts)])


class TestArtifactsGenerationMvp:
    @pytest.mark.asyncio
    async def test_generate_audio(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        _queue_generation(
            httpx_mock,
            build_rpc_response,
            artifact_id="audio_123",
            title="Audio Overview",
        )

        async with NotebookLMClient(auth_tokens) as client:
            result = await client.artifacts.generate_audio("nb_123")

        assert result.task_id == "audio_123"
        assert result.status in {"pending", "in_progress"}
        assert len(httpx_mock.get_requests()) == 2
        assert RPCMethod.CREATE_ARTIFACT.value in str(httpx_mock.get_requests()[-1].url)

    @pytest.mark.asyncio
    async def test_generate_audio_with_format_and_length(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        _queue_generation(
            httpx_mock,
            build_rpc_response,
            artifact_id="audio_456",
            title="Audio Overview",
        )

        async with NotebookLMClient(auth_tokens) as client:
            result = await client.artifacts.generate_audio(
                "nb_123",
                audio_format=AudioFormat.DEBATE,
                audio_length=AudioLength.LONG,
            )

        assert result.task_id == "audio_456"

    @pytest.mark.asyncio
    async def test_generate_report_briefing_doc(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        _queue_generation(
            httpx_mock,
            build_rpc_response,
            artifact_id="report_123",
            title="Briefing Doc",
        )

        async with NotebookLMClient(auth_tokens) as client:
            result = await client.artifacts.generate_report("nb_123")

        assert result.task_id == "report_123"
        assert result.status in {"pending", "in_progress"}

    @pytest.mark.asyncio
    async def test_generate_study_guide(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        _queue_generation(
            httpx_mock,
            build_rpc_response,
            artifact_id="study_123",
            title="Study Guide",
        )

        async with NotebookLMClient(auth_tokens) as client:
            result = await client.artifacts.generate_study_guide("nb_123")

        assert result.task_id == "study_123"

    @pytest.mark.asyncio
    async def test_generate_report_rejects_unsupported_format(
        self,
        auth_tokens,
    ) -> None:
        async with NotebookLMClient(auth_tokens) as client:
            with pytest.raises(ValidationError, match="not supported on this branch"):
                await client.artifacts.generate_report(
                    "nb_123",
                    report_format=ReportFormat.BLOG_POST,
                )

    @pytest.mark.asyncio
    async def test_generate_report_rejects_custom_prompt(
        self,
        auth_tokens,
    ) -> None:
        async with NotebookLMClient(auth_tokens) as client:
            with pytest.raises(ValidationError, match="custom_prompt is not supported"):
                await client.artifacts.generate_report(
                    "nb_123",
                    custom_prompt="Write it like a screenplay.",
                )


class TestArtifactsStatusMvp:
    @pytest.mark.asyncio
    async def test_poll_status_pending_when_task_missing(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        response = _list_response(
            build_rpc_response,
            ["some_other_artifact", "Briefing Doc", 2, None, 3],
        )
        httpx_mock.add_response(content=response.encode())

        async with NotebookLMClient(auth_tokens) as client:
            result = await client.artifacts.poll_status("nb_123", "unknown_task_id")

        assert result.status == "pending"
        assert result.task_id == "unknown_task_id"

    @pytest.mark.asyncio
    async def test_poll_status_completed_report_no_url_check(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        response = _list_response(
            build_rpc_response,
            ["report_task", "Briefing Doc", 2, None, 3],
        )
        httpx_mock.add_response(content=response.encode())

        async with NotebookLMClient(auth_tokens) as client:
            result = await client.artifacts.poll_status("nb_123", "report_task")

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_poll_status_completed_audio_without_url_downgrades_to_in_progress(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        response = _list_response(
            build_rpc_response,
            ["audio_task", "Audio Overview", 1, None, 3],
        )
        httpx_mock.add_response(content=response.encode())

        async with NotebookLMClient(auth_tokens) as client:
            result = await client.artifacts.poll_status("nb_123", "audio_task")

        assert result.status == "in_progress"

    @pytest.mark.asyncio
    async def test_poll_status_completed_audio_with_ready_url(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        audio_artifact = [
            "audio_ready",
            "Audio Overview",
            1,
            None,
            3,
            None,
            [
                None,
                None,
                None,
                None,
                None,
                [["https://storage.googleapis.com/audio.mp4", None, "audio/mp4"]],
            ],
        ]
        response = _list_response(build_rpc_response, audio_artifact)
        httpx_mock.add_response(content=response.encode())

        async with NotebookLMClient(auth_tokens) as client:
            result = await client.artifacts.poll_status("nb_123", "audio_ready")

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_wait_for_completion_returns_completed_status(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        pending = _list_response(
            build_rpc_response,
            ["task_wait", "Audio Overview", 1, None, 1],
        )
        completed = _list_response(
            build_rpc_response,
            [
                "task_wait",
                "Audio Overview",
                1,
                None,
                3,
                None,
                [
                    None,
                    None,
                    None,
                    None,
                    None,
                    [["https://storage.googleapis.com/audio.mp4", None, "audio/mp4"]],
                ],
            ],
        )
        httpx_mock.add_response(content=pending.encode())
        httpx_mock.add_response(content=completed.encode())

        async with NotebookLMClient(auth_tokens) as client:
            result = await client.artifacts.wait_for_completion(
                "nb_123",
                "task_wait",
                initial_interval=0.0,
                max_interval=0.0,
            )

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_wait_for_completion_deprecated_poll_interval_warning(
        self,
        auth_tokens,
        httpx_mock: HTTPXMock,
        build_rpc_response,
    ) -> None:
        response = _list_response(
            build_rpc_response,
            ["task_dep", "Briefing Doc", 2, None, 3],
        )
        httpx_mock.add_response(content=response.encode())

        async with NotebookLMClient(auth_tokens) as client:
            with pytest.warns(DeprecationWarning):
                result = await client.artifacts.wait_for_completion(
                    "nb_123",
                    "task_dep",
                    poll_interval=0.0,
                )

        assert result.status == "completed"


class TestArtifactsGenerateErrorHandling:
    @pytest.mark.asyncio
    async def test_generate_audio_user_displayable_error_returns_failed(
        self,
        auth_tokens,
    ) -> None:
        async with NotebookLMClient(auth_tokens) as client:
            err = RPCError("You have exceeded your quota")
            err.rpc_code = "USER_DISPLAYABLE_ERROR"
            with patch.object(
                client.artifacts._core,
                "rpc_call",
                AsyncMock(side_effect=err),
            ):
                result = await client.artifacts.generate_audio(
                    "nb_123",
                    source_ids=["src_001"],
                )

        assert result.status == "failed"
        assert result.error_code == "USER_DISPLAYABLE_ERROR"

    @pytest.mark.asyncio
    async def test_generate_audio_other_rpc_error_reraises(
        self,
        auth_tokens,
    ) -> None:
        async with NotebookLMClient(auth_tokens) as client:
            err = RPCError("Server error")
            err.rpc_code = "INTERNAL_ERROR"
            with (
                patch.object(
                    client.artifacts._core,
                    "rpc_call",
                    AsyncMock(side_effect=err),
                ),
                pytest.raises(RPCError),
            ):
                await client.artifacts.generate_audio(
                    "nb_123",
                    source_ids=["src_001"],
                )
