"""Additional unit tests for the reduced ArtifactsAPI backend."""

import asyncio
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from notebooklm._artifacts import ArtifactsAPI
from notebooklm.rpc.decoder import RPCError


@pytest.fixture
def mock_artifacts_api():
    """Create an ArtifactsAPI with mocked core and notes API."""
    mock_core = MagicMock()
    mock_core.rpc_call = AsyncMock()
    mock_core.get_source_ids = AsyncMock(return_value=[])
    mock_notes = MagicMock()
    api = ArtifactsAPI(mock_core, notes_api=mock_notes)
    return api, mock_core


class TestCallGenerateRateLimit:
    """Test supported generation error handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_returns_failed_status(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.side_effect = RPCError(
            "Rate limit exceeded",
            rpc_code="USER_DISPLAYABLE_ERROR",
        )

        result = await api.generate_audio("nb_123")

        assert result.status == "failed"
        assert result.error is not None
        assert "Rate limit" in result.error
        assert result.error_code == "USER_DISPLAYABLE_ERROR"

    @pytest.mark.asyncio
    async def test_other_rpc_error_propagates(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.side_effect = RPCError("Server error", rpc_code="INTERNAL_ERROR")

        with pytest.raises(RPCError, match="Server error"):
            await api.generate_audio("nb_123")


class TestWaitForCompletion:
    """Test wait_for_completion timeout and polling logic."""

    @pytest.mark.asyncio
    async def test_timeout_raises_error(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.return_value = [
            [
                [
                    "task_123",
                    "Title",
                    2,
                    None,
                    1,
                ]
            ]
        ]

        loop = asyncio.get_running_loop()
        time_values = iter([0, 0.1, 0.2, 0.5, 1.0, 2.0])

        def mock_time():
            try:
                return next(time_values)
            except StopIteration:
                return 10.0

        with (
            patch.object(loop, "time", mock_time),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(TimeoutError, match="timed out"),
        ):
            await api.wait_for_completion("nb_123", "task_123", timeout=1.5)

    @pytest.mark.asyncio
    async def test_wait_completes_successfully(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.side_effect = [
            [[[ "task_123", "Title", 2, None, 1 ]]],
            [[[ "task_123", "Title", 2, None, 3 ]]],
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await api.wait_for_completion("nb_123", "task_123", timeout=60.0)

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_poll_returns_pending_when_artifact_not_found(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.return_value = [
            [
                [
                    "other_artifact",
                    "Title",
                    2,
                    None,
                    3,
                ]
            ]
        ]

        result = await api.poll_status("nb_123", "task_123")

        assert result.status == "pending"
        assert result.task_id == "task_123"


class TestParseGenerationResult:
    """Test _parse_generation_result parsing logic."""

    def test_parse_null_result(self, mock_artifacts_api):
        api, _ = mock_artifacts_api

        result = api._parse_generation_result(None)

        assert result.status == "failed"
        assert result.task_id == ""
        assert "no artifact_id" in result.error.lower()

    def test_parse_empty_list_result(self, mock_artifacts_api):
        api, _ = mock_artifacts_api

        result = api._parse_generation_result([])

        assert result.status == "failed"
        assert result.task_id == ""
        assert "no artifact_id" in result.error.lower()

    def test_parse_valid_in_progress(self, mock_artifacts_api):
        api, _ = mock_artifacts_api

        result = api._parse_generation_result([["artifact_001", "Title", 1, None, 1]])

        assert result.task_id == "artifact_001"
        assert result.status == "in_progress"

    def test_parse_valid_completed(self, mock_artifacts_api):
        api, _ = mock_artifacts_api

        result = api._parse_generation_result([["artifact_002", "Title", 1, None, 3]])

        assert result.task_id == "artifact_002"
        assert result.status == "completed"

    def test_parse_unknown_status_code(self, mock_artifacts_api):
        api, _ = mock_artifacts_api

        result = api._parse_generation_result([["artifact_003", "Title", 1, None, 99]])

        assert result.task_id == "artifact_003"
        assert result.status == "unknown"


class TestDeprecationWarnings:
    """Test wait_for_completion deprecation path."""

    @pytest.mark.asyncio
    async def test_poll_interval_deprecation_warning(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.return_value = [
            [
                [
                    "task_123",
                    "Title",
                    2,
                    None,
                    3,
                ]
            ]
        ]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            await api.wait_for_completion("nb_123", "task_123", poll_interval=5.0)

        assert len(caught) == 1
        assert issubclass(caught[0].category, DeprecationWarning)
        assert "poll_interval is deprecated" in str(caught[0].message)


class TestIsMediaReady:
    """Test the MVP audio readiness guard."""

    def test_audio_with_valid_url(self, mock_artifacts_api):
        api, _ = mock_artifacts_api
        art = [
            "artifact_id",
            "title",
            1,
            None,
            3,
            None,
            [None, None, None, None, None, [["https://audio.url/file.mp4", None, "audio/mp4"]]],
        ]

        assert api._is_media_ready(art, 1) is True

    def test_audio_without_url(self, mock_artifacts_api):
        api, _ = mock_artifacts_api
        art = [
            "artifact_id",
            "title",
            1,
            None,
            3,
            None,
            [None, None, None, None, None, []],
        ]

        assert api._is_media_ready(art, 1) is False

    def test_audio_truncated_structure(self, mock_artifacts_api):
        api, _ = mock_artifacts_api

        assert api._is_media_ready(["artifact_id", "title", 1, None, 3], 1) is False

    def test_non_audio_artifact_returns_true(self, mock_artifacts_api):
        api, _ = mock_artifacts_api

        assert api._is_media_ready(["artifact_id", "title", 2, None, 3], 2) is True
        assert api._is_media_ready(["artifact_id", "title", 3, None, 3], 3) is True
        assert api._is_media_ready("not a list", 2) is True

    def test_unexpected_structure_returns_false_for_audio(self, mock_artifacts_api):
        api, _ = mock_artifacts_api

        assert api._is_media_ready("not a list", 1) is False


class TestPollStatusMediaReadiness:
    """Test poll_status with the reduced media-readiness behavior."""

    @pytest.mark.asyncio
    async def test_poll_status_audio_completed_with_url(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.return_value = [
            [[
                "task_123",
                "Audio Overview",
                1,
                None,
                3,
                None,
                [None, None, None, None, None, [["https://audio.url/file.mp4", None, "audio/mp4"]]],
            ]]
        ]

        status = await api.poll_status("nb_123", "task_123")

        assert status.status == "completed"

    @pytest.mark.asyncio
    async def test_poll_status_audio_completed_without_url(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.return_value = [
            [[
                "task_123",
                "Audio Overview",
                1,
                None,
                3,
                None,
                [None, None, None, None, None, []],
            ]]
        ]

        status = await api.poll_status("nb_123", "task_123")

        assert status.status == "in_progress"

    @pytest.mark.asyncio
    async def test_poll_status_non_audio_completed_without_url_check(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.return_value = [
            [[
                "task_123",
                "Video Overview",
                3,
                None,
                3,
                None,
                None,
                None,
                [],
            ]]
        ]

        status = await api.poll_status("nb_123", "task_123")

        assert status.status == "completed"

    @pytest.mark.asyncio
    async def test_poll_status_processing_status_unchanged(self, mock_artifacts_api):
        api, mock_core = mock_artifacts_api

        mock_core.rpc_call.return_value = [
            [[
                "task_123",
                "Audio Overview",
                1,
                None,
                1,
                None,
                [None, None, None, None, None, []],
            ]]
        ]

        status = await api.poll_status("nb_123", "task_123")

        assert status.status == "in_progress"
