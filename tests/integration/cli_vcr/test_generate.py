"""CLI integration tests for generate commands.

These tests exercise the full CLI → Client → RPC path using VCR cassettes.
"""

import pytest

from notebooklm.notebooklm_cli import cli

from .conftest import assert_command_success, notebooklm_vcr, skip_no_cassettes

pytestmark = [pytest.mark.vcr, skip_no_cassettes]


class TestGenerateCommands:
    """Test 'notebooklm generate' commands."""

    @pytest.mark.parametrize(
        ("cassette", "extra_args"),
        [
            ("artifacts_generate_report.yaml", ["--format", "briefing-doc"]),
            ("artifacts_generate_study_guide.yaml", ["--format", "study-guide"]),
        ],
    )
    def test_generate_report(self, runner, mock_auth_for_vcr, mock_context, cassette, extra_args):
        """Retained generate report commands work with the real client."""
        with notebooklm_vcr.use_cassette(cassette):
            result = runner.invoke(cli, ["generate", "report", *extra_args])
            assert_command_success(result)
