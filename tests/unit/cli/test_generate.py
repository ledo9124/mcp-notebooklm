"""Tests for the reduced generate CLI surface."""

import importlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from notebooklm.notebooklm_cli import cli
from notebooklm.rpc.types import ReportFormat
from notebooklm.types import GenerationStatus

from .conftest import create_mock_client, patch_client_for_module


class TestGenerateAudio:
    def test_generate_audio(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(
                return_value={"artifact_id": "audio_123", "status": "processing"}
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["generate", "audio", "deep dive on the key debates", "-n", "nb_123"],
                )

        assert result.exit_code == 0
        assert "audio_123" in result.output or "Started" in result.output
        mock_client.artifacts.generate_audio.assert_awaited_once()
        call_kwargs = mock_client.artifacts.generate_audio.call_args.kwargs
        assert call_kwargs["instructions"] == "deep dive on the key debates"

    def test_generate_audio_with_wait(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            initial_status = GenerationStatus(task_id="audio_123", status="pending")
            completed_status = GenerationStatus(
                task_id="audio_123",
                status="completed",
                url="https://example.com/audio.mp3",
            )
            mock_client.artifacts.generate_audio = AsyncMock(return_value=initial_status)
            mock_client.artifacts.wait_for_completion = AsyncMock(return_value=completed_status)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "audio", "--wait", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "audio.mp3" in result.output
        mock_client.artifacts.wait_for_completion.assert_awaited_once_with(
            "nb_123",
            "audio_123",
            timeout=300.0,
        )

    def test_generate_audio_failure(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "audio", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "Audio generation failed" in result.output

    def test_generate_audio_json_output(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(
                return_value={"task_id": "audio_123", "status": "processing"}
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "audio", "--json", "-n", "nb_123"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {"task_id": "audio_123", "status": "pending"}


class TestGenerateReport:
    def test_generate_report_default(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_report = AsyncMock(
                return_value={"artifact_id": "report_123", "status": "processing"}
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "report", "-n", "nb_123"])

        assert result.exit_code == 0
        call_kwargs = mock_client.artifacts.generate_report.call_args.kwargs
        assert call_kwargs["report_format"] == ReportFormat.BRIEFING_DOC
        assert call_kwargs["extra_instructions"] is None

    def test_generate_report_study_guide(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_report = AsyncMock(
                return_value={"artifact_id": "report_123", "status": "processing"}
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["generate", "report", "--format", "study-guide", "-n", "nb_123"],
                )

        assert result.exit_code == 0
        call_kwargs = mock_client.artifacts.generate_report.call_args.kwargs
        assert call_kwargs["report_format"] == ReportFormat.STUDY_GUIDE

    def test_generate_report_combines_description_and_append(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_report = AsyncMock(
                return_value={"artifact_id": "report_123", "status": "processing"}
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    [
                        "generate",
                        "report",
                        "Focus on AI trends",
                        "--append",
                        "Target audience: beginners",
                        "-n",
                        "nb_123",
                    ],
                )

        assert result.exit_code == 0
        call_kwargs = mock_client.artifacts.generate_report.call_args.kwargs
        assert call_kwargs["report_format"] == ReportFormat.BRIEFING_DOC
        assert call_kwargs["extra_instructions"] == (
            "Focus on AI trends\n\nTarget audience: beginners"
        )

    def test_generate_report_json_output(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_report = AsyncMock(
                return_value={"task_id": "report_123", "status": "processing"}
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "report", "--json", "-n", "nb_123"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {"task_id": "report_123", "status": "pending"}


class TestGenerateCommandsExist:
    def test_generate_group_help_only_shows_supported_commands(self, runner):
        result = runner.invoke(cli, ["generate", "--help"])

        assert result.exit_code == 0
        assert "audio" in result.output
        assert "report" in result.output
        assert "video" not in result.output
        assert "quiz" not in result.output
        assert "slide-deck" not in result.output
        assert "mind-map" not in result.output

    @pytest.mark.parametrize(
        "command",
        [
            "video",
            "slide-deck",
            "quiz",
            "flashcards",
            "infographic",
            "data-table",
            "mind-map",
            "revise-slide",
        ],
    )
    def test_removed_generate_subcommands_are_absent(self, runner, command):
        result = runner.invoke(cli, ["generate", command, "--help"])

        assert result.exit_code == 2
        assert "No such command" in result.output

    def test_retry_option_in_audio_help(self, runner):
        result = runner.invoke(cli, ["generate", "audio", "--help"])

        assert result.exit_code == 0
        assert "--retry" in result.output

    def test_retry_option_in_report_help(self, runner):
        result = runner.invoke(cli, ["generate", "report", "--help"])

        assert result.exit_code == 0
        assert "--retry" in result.output


class TestGenerateLanguageValidation:
    def test_invalid_language_code_rejected(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["generate", "audio", "--language", "xx_INVALID", "-n", "nb_123"],
                )

        assert result.exit_code != 0
        assert "Unknown language code: xx_INVALID" in result.output

    def test_valid_language_code_accepted(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(
                return_value={"artifact_id": "audio_123", "status": "processing"}
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(
                    cli,
                    ["generate", "audio", "--language", "fr", "-n", "nb_123"],
                )

        assert result.exit_code == 0
        assert mock_client.artifacts.generate_audio.call_args.kwargs["language"] == "fr"


class TestCalculateBackoffDelay:
    def test_initial_delay(self):
        from notebooklm.cli.generate import calculate_backoff_delay

        assert calculate_backoff_delay(0, initial_delay=60.0) == 60.0

    def test_exponential_backoff(self):
        from notebooklm.cli.generate import calculate_backoff_delay

        assert calculate_backoff_delay(1, initial_delay=60.0) == 120.0
        assert calculate_backoff_delay(2, initial_delay=60.0) == 240.0

    def test_max_delay_cap(self):
        from notebooklm.cli.generate import calculate_backoff_delay

        assert calculate_backoff_delay(10, initial_delay=60.0, max_delay=300.0) == 300.0

    def test_custom_multiplier(self):
        from notebooklm.cli.generate import calculate_backoff_delay

        assert calculate_backoff_delay(1, initial_delay=10.0, multiplier=3.0) == 30.0


class TestGenerateWithRetry:
    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        from notebooklm.cli.generate import generate_with_retry

        success_result = GenerationStatus(task_id="task_123", status="pending")
        generate_fn = AsyncMock(return_value=success_result)

        result = await generate_with_retry(generate_fn, max_retries=3, artifact_type="audio")

        assert result == success_result
        assert generate_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self):
        from notebooklm.cli.generate import generate_with_retry

        rate_limited = GenerationStatus(
            task_id="",
            status="failed",
            error="Rate limited",
            error_code="USER_DISPLAYABLE_ERROR",
        )
        success_result = GenerationStatus(task_id="task_123", status="pending")
        generate_fn = AsyncMock(side_effect=[rate_limited, success_result])

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await generate_with_retry(
                generate_fn,
                max_retries=3,
                artifact_type="audio",
                json_output=True,
            )

        assert result == success_result
        assert generate_fn.call_count == 2
        mock_sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        from notebooklm.cli.generate import generate_with_retry

        rate_limited = GenerationStatus(
            task_id="",
            status="failed",
            error="Rate limited",
            error_code="USER_DISPLAYABLE_ERROR",
        )
        generate_fn = AsyncMock(return_value=rate_limited)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await generate_with_retry(
                generate_fn,
                max_retries=2,
                artifact_type="audio",
                json_output=True,
            )

        assert result == rate_limited
        assert generate_fn.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_when_max_retries_zero(self):
        from notebooklm.cli.generate import generate_with_retry

        rate_limited = GenerationStatus(
            task_id="",
            status="failed",
            error="Rate limited",
            error_code="USER_DISPLAYABLE_ERROR",
        )
        generate_fn = AsyncMock(return_value=rate_limited)

        result = await generate_with_retry(
            generate_fn,
            max_retries=0,
            artifact_type="audio",
            json_output=True,
        )

        assert result == rate_limited
        assert generate_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_delays_increase_exponentially(self):
        from notebooklm.cli.generate import generate_with_retry

        rate_limited = GenerationStatus(
            task_id="",
            status="failed",
            error="Rate limited",
            error_code="USER_DISPLAYABLE_ERROR",
        )
        generate_fn = AsyncMock(return_value=rate_limited)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await generate_with_retry(
                generate_fn,
                max_retries=3,
                artifact_type="audio",
                json_output=True,
            )

        delays = [call.args[0] for call in mock_sleep.await_args_list]
        assert delays == [60.0, 120.0, 240.0]


class TestRateLimitDetection:
    def test_rate_limit_message_shown(self, runner, mock_auth):
        rate_limited = GenerationStatus(
            task_id="",
            status="failed",
            error="Rate limited",
            error_code="USER_DISPLAYABLE_ERROR",
        )

        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(return_value=rate_limited)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "audio", "-n", "nb_123"])

        assert "rate limited by Google" in result.output
        assert "--retry" in result.output

    def test_rate_limit_json_output(self, runner, mock_auth):
        rate_limited = GenerationStatus(
            task_id="",
            status="failed",
            error="Rate limited",
            error_code="USER_DISPLAYABLE_ERROR",
        )

        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(return_value=rate_limited)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "audio", "-n", "nb_123", "--json"])

        data = json.loads(result.output)
        assert data["error"] is True
        assert data["code"] == "RATE_LIMITED"


class TestResolveLanguageDirect:
    def test_invalid_language_raises_bad_parameter(self):
        import click

        generate_module = importlib.import_module("notebooklm.cli.generate")

        with pytest.raises(click.BadParameter) as exc_info:
            generate_module.resolve_language("xx_INVALID")
        assert "Unknown language code: xx_INVALID" in str(exc_info.value)
        assert "supported codes" in str(exc_info.value)

    def test_none_language_with_config_returns_config(self):
        generate_module = importlib.import_module("notebooklm.cli.generate")

        with patch.object(generate_module, "get_language", return_value="fr"):
            assert generate_module.resolve_language(None) == "fr"

    def test_none_language_no_config_returns_default(self):
        generate_module = importlib.import_module("notebooklm.cli.generate")

        with patch.object(generate_module, "get_language", return_value=None):
            assert generate_module.resolve_language(None) == "en"


class TestOutputGenerationStatusDirect:
    def setup_method(self):
        self.generate_module = importlib.import_module("notebooklm.cli.generate")

    def _make_status(
        self,
        *,
        is_complete: bool = False,
        is_failed: bool = False,
        task_id: str | None = None,
        url: str | None = None,
        error: str | None = None,
    ):
        status = MagicMock()
        status.is_complete = is_complete
        status.is_failed = is_failed
        status.task_id = task_id
        status.url = url
        status.error = error
        return status

    def test_json_completed_with_url(self):
        status = self._make_status(
            is_complete=True,
            task_id="task_123",
            url="https://example.com/audio.mp3",
        )

        with patch.object(self.generate_module, "json_output_response") as mock_json:
            self.generate_module._output_generation_status(status, "audio", json_output=True)

        mock_json.assert_called_once_with(
            {
                "task_id": "task_123",
                "status": "completed",
                "url": "https://example.com/audio.mp3",
            }
        )

    def test_json_failed(self):
        status = self._make_status(is_failed=True, error="Something went wrong")

        with patch.object(self.generate_module, "json_error_response") as mock_err:
            self.generate_module._output_generation_status(status, "audio", json_output=True)

        mock_err.assert_called_once_with("GENERATION_FAILED", "Something went wrong")

    def test_json_failed_no_error_message(self):
        status = self._make_status(is_failed=True, error=None)

        with patch.object(self.generate_module, "json_error_response") as mock_err:
            self.generate_module._output_generation_status(status, "audio", json_output=True)

        mock_err.assert_called_once_with("GENERATION_FAILED", "Audio generation failed")

    def test_text_completed_with_url(self):
        status = self._make_status(
            is_complete=True,
            task_id="task_123",
            url="https://example.com/audio.mp3",
        )

        with patch.object(self.generate_module, "console") as mock_console:
            self.generate_module._output_generation_status(status, "audio", json_output=False)

        mock_console.print.assert_called_once_with(
            "[green]Audio ready:[/green] https://example.com/audio.mp3"
        )

    def test_text_pending_without_task_id_shows_status(self):
        status = MagicMock()
        status.is_complete = False
        status.is_failed = False

        with (
            patch.object(self.generate_module, "_extract_task_id", return_value=None),
            patch.object(self.generate_module, "console") as mock_console,
        ):
            self.generate_module._output_generation_status(status, "audio", json_output=False)

        call_text = mock_console.print.call_args.args[0]
        assert "[yellow]Started:[/yellow]" in call_text


class TestExtractTaskIdDirect:
    def setup_method(self):
        self.generate_module = importlib.import_module("notebooklm.cli.generate")

    def test_extract_from_list_first_string(self):
        assert self.generate_module._extract_task_id(["task_abc", "other"]) == "task_abc"

    def test_extract_from_list_first_not_string(self):
        assert self.generate_module._extract_task_id([123, "other"]) is None

    def test_extract_from_empty_list(self):
        assert self.generate_module._extract_task_id([]) is None

    def test_extract_from_dict_task_id(self):
        assert self.generate_module._extract_task_id({"task_id": "t1", "status": "pending"}) == "t1"

    def test_extract_from_dict_artifact_id(self):
        assert self.generate_module._extract_task_id({"artifact_id": "a1"}) == "a1"

    def test_extract_from_object_with_task_id(self):
        status = MagicMock()
        status.task_id = "task_obj"
        assert self.generate_module._extract_task_id(status) == "task_obj"


class TestHandleGenerationResultPaths:
    def test_generation_result_with_generation_status_object(self, runner, mock_auth):
        status = GenerationStatus(task_id="task_gen_1", status="pending")

        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(return_value=status)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "audio", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "task_gen_1" in result.output or "Started" in result.output

    def test_generation_result_with_list_input(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(return_value=["task_list_1", "extra"])
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "audio", "-n", "nb_123"])

        assert result.exit_code == 0
        assert "task_list_1" in result.output or "Started" in result.output

    def test_generation_result_falsy_json_shows_error(self, runner, mock_auth):
        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "audio", "-n", "nb_123", "--json"])

        data = json.loads(result.output)
        assert data["error"] is True
        assert data["code"] == "GENERATION_FAILED"

    def test_generation_with_wait_and_generation_status(self, runner, mock_auth):
        initial_status = GenerationStatus(task_id="task_wait_1", status="pending")
        completed_status = GenerationStatus(
            task_id="task_wait_1",
            status="completed",
            url="https://example.com/result.mp3",
        )

        with patch_client_for_module("generate") as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.artifacts.generate_audio = AsyncMock(return_value=initial_status)
            mock_client.artifacts.wait_for_completion = AsyncMock(return_value=completed_status)
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = ("csrf", "session")
                result = runner.invoke(cli, ["generate", "audio", "-n", "nb_123", "--wait"])

        assert result.exit_code == 0
        mock_client.artifacts.wait_for_completion.assert_awaited_once()


class TestGenerateWithRetryConsoleOutput:
    @pytest.mark.asyncio
    async def test_retry_shows_console_message_when_not_json(self):
        generate_module = importlib.import_module("notebooklm.cli.generate")

        rate_limited = GenerationStatus(
            task_id="",
            status="failed",
            error="Rate limited",
            error_code="USER_DISPLAYABLE_ERROR",
        )
        success_result = GenerationStatus(task_id="task_123", status="pending")
        generate_fn = AsyncMock(side_effect=[rate_limited, success_result])

        with (
            patch.object(generate_module, "console") as mock_console,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await generate_module.generate_with_retry(
                generate_fn,
                max_retries=1,
                artifact_type="audio",
                json_output=False,
            )

        assert result == success_result
        call_text = mock_console.print.call_args.args[0]
        assert "Retrying" in call_text
