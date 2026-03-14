"""Tests for local language helpers used by retained generate commands."""

import importlib
import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from notebooklm.notebooklm_cli import cli

language_module = importlib.import_module("notebooklm.cli.language")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_config_file(tmp_path):
    """Provide a temporary config file for testing language helpers."""
    config_file = tmp_path / "config.json"
    home_dir = tmp_path
    with (
        patch.object(language_module, "get_config_path", return_value=config_file),
        patch.object(language_module, "get_home_dir", return_value=home_dir),
    ):
        yield config_file


class TestLanguageHelpers:
    def test_supported_languages_contains_expected_codes(self):
        assert language_module.SUPPORTED_LANGUAGES["en"] == "English"
        assert "zh_Hans" in language_module.SUPPORTED_LANGUAGES
        assert "ja" in language_module.SUPPORTED_LANGUAGES
        assert "ko" in language_module.SUPPORTED_LANGUAGES

    def test_get_language_returns_none_when_unset(self, mock_config_file):
        assert language_module.get_language() is None

    def test_set_language_persists_code(self, mock_config_file):
        language_module.set_language("zh_Hans")

        config = json.loads(mock_config_file.read_text())
        assert config["language"] == "zh_Hans"
        assert language_module.get_language() == "zh_Hans"

    def test_set_language_preserves_existing_config(self, mock_config_file):
        mock_config_file.write_text(json.dumps({"theme": "test"}))

        language_module.set_language("fr")

        config = json.loads(mock_config_file.read_text())
        assert config == {"theme": "test", "language": "fr"}


class TestGenerateIntegration:
    def test_generate_audio_help_mentions_language_config(self, runner, mock_config_file):
        mock_config_file.write_text(json.dumps({"language": "zh_Hans"}))

        result = runner.invoke(cli, ["generate", "audio", "--help"])

        assert result.exit_code == 0
        assert "--language" in result.output
        assert "from config" in result.output.lower() or "default" in result.output.lower()


class TestCliSurface:
    def test_language_group_removed_from_root_cli(self, runner):
        result = runner.invoke(cli, ["language"])

        assert result.exit_code == 2
        assert "No such command 'language'" in result.output


class TestGetConfigErrorPaths:
    def test_get_config_json_decode_error(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("this is not valid json{{{")

        with patch.object(language_module, "get_config_path", return_value=config_file):
            result = language_module.get_config()

        assert result == {}

    def test_get_config_oserror(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"language": "en"}')

        with (
            patch.object(language_module, "get_config_path", return_value=config_file),
            patch.object(
                config_file.__class__, "read_text", side_effect=OSError("permission denied")
            ),
        ):
            result = language_module.get_config()

        assert result == {}
