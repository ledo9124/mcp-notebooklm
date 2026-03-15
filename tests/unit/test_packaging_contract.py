"""Packaging/install contract tests for the public CLI entrypoint."""

from pathlib import Path

from click.testing import CliRunner

from notebooklm.notebooklm_cli import cli


REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def test_distribution_name_and_console_script_stay_stable():
    """Keep package-install and executable names stable across CLI refactors."""
    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")

    assert 'name = "notebooklm-py"' in pyproject_text
    assert 'notebooklm = "notebooklm.notebooklm_cli:main"' in pyproject_text
    assert 'include = ["notebooklm", "notebooklm.*"]' in pyproject_text


def test_root_cli_help_uses_notebooklm_command_name():
    """Help output should continue to present the installed command as notebooklm."""
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"], prog_name="notebooklm")

    assert result.exit_code == 0
    assert result.output.startswith("Usage: notebooklm [OPTIONS] COMMAND [ARGS]...")
