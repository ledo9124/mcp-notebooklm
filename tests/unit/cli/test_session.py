"""Tests for session CLI commands (login, use, status, clear, auth)."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import click
import pytest
from click.testing import CliRunner

from notebooklm.notebooklm_cli import cli
from notebooklm.profiles.manager import ProfileManager
from notebooklm.auth import AuthTokens
from notebooklm.types import Notebook

from .conftest import create_mock_client, patch_main_cli_client


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_auth():
    with patch("notebooklm.cli.helpers.load_auth_from_storage") as mock:
        mock.return_value = {
            "SID": "test",
            "HSID": "test",
            "SSID": "test",
            "APISID": "test",
            "SAPISID": "test",
        }
        yield mock


@pytest.fixture
def mock_context_file(tmp_path):
    """Provide a temporary context file for testing context commands."""
    context_file = tmp_path / "context.json"
    with (
        patch("notebooklm.cli.helpers.get_context_path", return_value=context_file),
        patch("notebooklm.cli.session.get_context_path", return_value=context_file),
    ):
        yield context_file


# =============================================================================
# LOGIN COMMAND TESTS
# =============================================================================


class TestLoginCommand:
    def test_login_playwright_import_error_handling(self, runner):
        """Test that ImportError for playwright is handled gracefully."""
        # Patch the import inside the login function to raise ImportError
        with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            result = runner.invoke(cli, ["login"])

            # Should exit with code 1 and show helpful message
            assert result.exit_code == 1
            assert "Playwright not installed" in result.output or "pip install" in result.output

    def test_login_help_message(self, runner):
        """Test login command shows help information."""
        result = runner.invoke(cli, ["login", "--help"])

        assert result.exit_code == 0
        assert "Log in to NotebookLM" in result.output
        assert "--storage" in result.output

    def test_login_default_storage_path_info(self, runner):
        """Test login command help shows default storage path."""
        result = runner.invoke(cli, ["login", "--help"])

        assert result.exit_code == 0
        assert "storage_state.json" in result.output or "storage" in result.output.lower()

    def test_login_blocked_when_notebooklm_auth_json_set(self, runner, monkeypatch):
        """Test login command blocks when NOTEBOOKLM_AUTH_JSON is set."""
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", '{"cookies":[]}')

        result = runner.invoke(cli, ["login"])

        assert result.exit_code == 1
        assert "Cannot run 'login' when NOTEBOOKLM_AUTH_JSON is set" in result.output


# =============================================================================
# USE COMMAND TESTS
# =============================================================================


class TestUseCommand:
    def test_use_sets_notebook_context(self, runner, mock_auth, mock_context_file):
        """Test 'use' command sets the current notebook context."""
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.get = AsyncMock(
                return_value=Notebook(
                    id="nb_123",
                    title="Test Notebook",
                    created_at=datetime(2024, 1, 15),
                    is_owner=True,
                )
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = (
                    "csrf",
                    "session",
                    "boq_labs-tailwind-frontend_20260315.01_p0",
                )

                # Patch in session module where it's imported
                with patch(
                    "notebooklm.cli.session.resolve_notebook_id", new_callable=AsyncMock
                ) as mock_resolve:
                    mock_resolve.return_value = "nb_123"

                    result = runner.invoke(cli, ["use", "nb_123"])

        assert result.exit_code == 0
        assert "Deprecated compatibility command." in result.output
        assert "notebooklm notebook use <id-or-title>" in result.output
        assert "nb_123" in result.output or "Test Notebook" in result.output

    def test_use_with_partial_id(self, runner, mock_auth, mock_context_file):
        """Test 'use' command resolves partial notebook ID."""
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.get = AsyncMock(
                return_value=Notebook(
                    id="nb_full_id_123",
                    title="Resolved Notebook",
                    created_at=datetime(2024, 1, 15),
                    is_owner=True,
                )
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = (
                    "csrf",
                    "session",
                    "boq_labs-tailwind-frontend_20260315.01_p0",
                )

                # Patch in session module where it's imported
                with patch(
                    "notebooklm.cli.session.resolve_notebook_id", new_callable=AsyncMock
                ) as mock_resolve:
                    mock_resolve.return_value = "nb_full_id_123"

                    result = runner.invoke(cli, ["use", "nb_full"])

        assert result.exit_code == 0
        # Should show resolved full ID
        assert "nb_full_id_123" in result.output or "Resolved Notebook" in result.output

    def test_use_without_auth_sets_id_anyway(self, runner, mock_context_file):
        """Test 'use' command sets ID even without auth file."""
        with patch(
            "notebooklm.cli.helpers.load_auth_from_storage",
            side_effect=FileNotFoundError("No auth"),
        ):
            result = runner.invoke(cli, ["use", "nb_noauth"])

        # Should still set the context (with warning)
        assert result.exit_code == 0
        assert "nb_noauth" in result.output

    def test_use_shows_owner_status(self, runner, mock_auth, mock_context_file):
        """Test 'use' command displays ownership status correctly."""
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.get = AsyncMock(
                return_value=Notebook(
                    id="nb_shared",
                    title="Shared Notebook",
                    created_at=datetime(2024, 1, 15),
                    is_owner=False,  # Shared notebook
                )
            )
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = (
                    "csrf",
                    "session",
                    "boq_labs-tailwind-frontend_20260315.01_p0",
                )

                # Patch in session module where it's imported
                with patch(
                    "notebooklm.cli.session.resolve_notebook_id", new_callable=AsyncMock
                ) as mock_resolve:
                    mock_resolve.return_value = "nb_shared"

                    result = runner.invoke(cli, ["use", "nb_shared"])

        assert result.exit_code == 0
        assert "Shared" in result.output or "nb_shared" in result.output


# =============================================================================
# STATUS COMMAND TESTS
# =============================================================================


class TestStatusCommand:
    def test_status_no_context(self, runner, mock_context_file):
        """Test status command when no notebook is selected."""
        # Ensure context file doesn't exist
        if mock_context_file.exists():
            mock_context_file.unlink()

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "No notebook selected" in result.output or "use" in result.output.lower()

    def test_status_with_context(self, runner, mock_context_file):
        """Test status command shows current notebook context."""
        # Create context file with notebook info
        context_data = {
            "notebook_id": "nb_test_123",
            "title": "My Test Notebook",
            "is_owner": True,
            "created_at": "2024-01-15",
        }
        mock_context_file.write_text(json.dumps(context_data))

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "nb_test_123" in result.output or "My Test Notebook" in result.output

    def test_status_with_conversation(self, runner, mock_context_file):
        """Test status command shows conversation ID when set."""
        context_data = {
            "notebook_id": "nb_conv_test",
            "title": "Notebook with Conversation",
            "is_owner": True,
            "created_at": "2024-01-15",
            "conversation_id": "conv_abc123",
        }
        mock_context_file.write_text(json.dumps(context_data))

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "conv_abc123" in result.output or "Conversation" in result.output

    def test_status_json_output_with_context(self, runner, mock_context_file):
        """Test status --json outputs valid JSON."""
        context_data = {
            "notebook_id": "nb_json_test",
            "title": "JSON Test Notebook",
            "is_owner": True,
            "created_at": "2024-01-15",
        }
        mock_context_file.write_text(json.dumps(context_data))

        result = runner.invoke(cli, ["status", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["intent"] == "LOCAL_METADATA"
        assert payload["route"]["mode"] == "status"
        assert payload["route"]["notebook_id"] == "nb_json_test"
        assert payload["route"]["profile_id"] == "default"
        assert payload["route"]["source_of_truth"] == "local_cache"
        assert payload["route"]["cache_mode"] == "offline"
        assert payload["route"]["transport"]["kind"] == "local"
        assert payload["result"]["has_context"] is True
        assert payload["result"]["notebook"]["id"] == "nb_json_test"

    def test_status_json_output_no_context(self, runner, mock_context_file):
        """Test status --json outputs valid JSON when no context."""
        if mock_context_file.exists():
            mock_context_file.unlink()

        result = runner.invoke(cli, ["status", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["mode"] == "status"
        assert payload["route"]["notebook_id"] is None
        assert payload["result"]["has_context"] is False
        assert payload["result"]["notebook"] is None

    def test_status_handles_corrupted_context_file(self, runner, mock_context_file):
        """Test status handles corrupted context file gracefully."""
        # Write invalid JSON
        mock_context_file.write_text("{ invalid json }")

        result = runner.invoke(cli, ["status"])

        # Should not crash, should show minimal info or no context
        assert result.exit_code == 0


# =============================================================================
# CLEAR COMMAND TESTS
# =============================================================================


class TestClearCommand:
    def test_clear_removes_context(self, runner, mock_context_file):
        """Test clear command removes context file."""
        # Create context file
        context_data = {"notebook_id": "nb_to_clear", "title": "Clear Me"}
        mock_context_file.write_text(json.dumps(context_data))

        result = runner.invoke(cli, ["clear"])

        assert result.exit_code == 0
        assert "cleared" in result.output.lower() or "Context" in result.output

    def test_clear_when_no_context(self, runner, mock_context_file):
        """Test clear command when no context exists."""
        if mock_context_file.exists():
            mock_context_file.unlink()

        result = runner.invoke(cli, ["clear"])

        # Should succeed even if no context exists
        assert result.exit_code == 0


# =============================================================================
# EDGE CASES
# =============================================================================


class TestStatusPaths:
    """Tests for status --paths flag."""

    def test_status_paths_flag_shows_table(self, runner, mock_context_file):
        """Test status --paths shows configuration paths table."""
        with patch("notebooklm.cli.session.get_path_info") as mock_path_info:
            mock_path_info.return_value = {
                "home_dir": "/home/test/.notebooklm",
                "home_source": "default",
                "storage_path": "/home/test/.notebooklm/storage_state.json",
                "context_path": "/home/test/.notebooklm/context.json",
                "browser_profile_dir": "/home/test/.notebooklm/browser_profile",
            }

            result = runner.invoke(cli, ["status", "--paths"])

        assert result.exit_code == 0
        assert "Configuration Paths" in result.output
        assert "/home/test/.notebooklm" in result.output
        assert "storage_state.json" in result.output

    def test_status_paths_json_output(self, runner, mock_context_file):
        """Test status --paths --json outputs path info as JSON."""
        with patch("notebooklm.cli.session.get_path_info") as mock_path_info:
            mock_path_info.return_value = {
                "home_dir": "/custom/path/.notebooklm",
                "home_source": "NOTEBOOKLM_HOME",
                "storage_path": "/custom/path/.notebooklm/storage_state.json",
                "context_path": "/custom/path/.notebooklm/context.json",
                "browser_profile_dir": "/custom/path/.notebooklm/browser_profile",
            }

            result = runner.invoke(cli, ["status", "--paths", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["intent"] == "LOCAL_METADATA"
        assert payload["route"]["mode"] == "status_paths"
        assert payload["route"]["notebook_id"] is None
        assert payload["route"]["transport"]["kind"] == "local"
        assert "paths" in payload["result"]
        assert payload["result"]["paths"]["home_dir"] == "/custom/path/.notebooklm"
        assert payload["result"]["paths"]["home_source"] == "NOTEBOOKLM_HOME"

    def test_status_paths_shows_auth_json_note(self, runner, mock_context_file, monkeypatch):
        """Test status --paths shows note when NOTEBOOKLM_AUTH_JSON is set."""
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", '{"cookies":[]}')

        with patch("notebooklm.cli.session.get_path_info") as mock_path_info:
            mock_path_info.return_value = {
                "home_dir": "/home/test/.notebooklm",
                "home_source": "default",
                "storage_path": "/home/test/.notebooklm/storage_state.json",
                "context_path": "/home/test/.notebooklm/context.json",
                "browser_profile_dir": "/home/test/.notebooklm/browser_profile",
            }

            result = runner.invoke(cli, ["status", "--paths"])

        assert result.exit_code == 0
        assert "NOTEBOOKLM_AUTH_JSON is set" in result.output


# =============================================================================
# AUTH CHECK COMMAND TESTS
# =============================================================================


class TestAuthCheckCommand:
    """Tests for the 'auth check' command."""

    @pytest.fixture
    def mock_storage_path(self, tmp_path):
        """Provide a temporary storage path for testing."""
        storage_file = tmp_path / "storage_state.json"
        with patch("notebooklm.cli.session.get_storage_path", return_value=storage_file):
            yield storage_file

    def test_auth_check_storage_not_found(self, runner, mock_storage_path):
        """Test auth check when storage file doesn't exist."""
        # Ensure file doesn't exist
        if mock_storage_path.exists():
            mock_storage_path.unlink()

        result = runner.invoke(cli, ["auth", "check"])

        assert result.exit_code == 0
        assert "Storage exists" in result.output
        assert "fail" in result.output.lower() or "✗" in result.output

    def test_auth_check_storage_not_found_json(self, runner, mock_storage_path):
        """Test auth check --json when storage file doesn't exist."""
        if mock_storage_path.exists():
            mock_storage_path.unlink()

        result = runner.invoke(cli, ["auth", "check", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["route"]["intent"] == "DOCTOR"
        assert payload["route"]["mode"] == "check"
        assert payload["route"]["transport"]["kind"] == "local"
        assert payload["result"]["status"] == "error"
        assert payload["result"]["checks"]["storage_exists"] is False
        assert "not found" in payload["result"]["details"]["error"]

    def test_auth_check_invalid_json(self, runner, mock_storage_path):
        """Test auth check when storage file contains invalid JSON."""
        mock_storage_path.write_text("{ invalid json }")

        result = runner.invoke(cli, ["auth", "check"])

        assert result.exit_code == 0
        assert "JSON valid" in result.output
        assert "fail" in result.output.lower() or "✗" in result.output

    def test_auth_check_invalid_json_output(self, runner, mock_storage_path):
        """Test auth check --json when storage contains invalid JSON."""
        mock_storage_path.write_text("not valid json at all")

        result = runner.invoke(cli, ["auth", "check", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["result"]["status"] == "error"
        assert payload["result"]["checks"]["storage_exists"] is True
        assert payload["result"]["checks"]["json_valid"] is False
        assert "Invalid JSON" in payload["result"]["details"]["error"]

    def test_auth_check_missing_sid_cookie(self, runner, mock_storage_path):
        """Test auth check when SID cookie is missing."""
        # Valid JSON but no SID cookie
        storage_data = {
            "cookies": [
                {"name": "OTHER", "value": "test", "domain": ".google.com"},
            ]
        }
        mock_storage_path.write_text(json.dumps(storage_data))

        result = runner.invoke(cli, ["auth", "check"])

        assert result.exit_code == 0
        assert "SID" in result.output or "cookie" in result.output.lower()

    def test_auth_check_valid_storage(self, runner, mock_storage_path):
        """Test auth check with valid storage containing SID."""
        storage_data = {
            "cookies": [
                {"name": "SID", "value": "test_sid", "domain": ".google.com"},
                {"name": "HSID", "value": "test_hsid", "domain": ".google.com"},
                {"name": "SSID", "value": "test_ssid", "domain": ".google.com"},
            ]
        }
        mock_storage_path.write_text(json.dumps(storage_data))

        result = runner.invoke(cli, ["auth", "check"])

        assert result.exit_code == 0
        assert "pass" in result.output.lower() or "✓" in result.output
        assert "Authentication is valid" in result.output

    def test_auth_check_valid_storage_json(self, runner, mock_storage_path):
        """Test auth check --json with valid storage."""
        storage_data = {
            "cookies": [
                {"name": "SID", "value": "test_sid", "domain": ".google.com"},
                {"name": "HSID", "value": "test_hsid", "domain": ".google.com"},
            ]
        }
        mock_storage_path.write_text(json.dumps(storage_data))

        result = runner.invoke(cli, ["auth", "check", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["intent"] == "DOCTOR"
        assert payload["route"]["mode"] == "check"
        assert payload["route"]["source_of_truth"] == "local_cache"
        assert payload["route"]["cache_mode"] == "offline"
        assert payload["route"]["transport"]["kind"] == "local"
        assert payload["result"]["status"] == "ok"
        assert payload["result"]["checks"]["storage_exists"] is True
        assert payload["result"]["checks"]["json_valid"] is True
        assert payload["result"]["checks"]["cookies_present"] is True
        assert payload["result"]["checks"]["sid_cookie"] is True
        assert "SID" in payload["result"]["details"]["cookies_found"]

    def test_auth_check_honors_root_storage_override(self, runner, tmp_path, monkeypatch):
        """Test auth check uses the root --storage override before NOTEBOOKLM_HOME."""
        auth_home = tmp_path / "home"
        auth_home.mkdir()
        monkeypatch.setenv("NOTEBOOKLM_HOME", str(auth_home))

        override_path = tmp_path / "override_storage.json"
        override_path.write_text(
            json.dumps(
                {
                    "cookies": [
                        {"name": "SID", "value": "override_sid", "domain": ".google.com"},
                        {"name": "HSID", "value": "override_hsid", "domain": ".google.com"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli, ["--storage", str(override_path), "auth", "check", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["result"]["checks"]["storage_exists"] is True
        assert payload["result"]["checks"]["sid_cookie"] is True
        assert payload["result"]["details"]["storage_path"] == str(override_path.resolve())
        assert payload["result"]["details"]["auth_source"] == f"file ({override_path.resolve()})"

    def test_auth_check_with_test_flag_success(self, runner, mock_storage_path):
        """Test auth check --test with successful token fetch."""
        storage_data = {
            "cookies": [
                {"name": "SID", "value": "test_sid", "domain": ".google.com"},
            ]
        }
        mock_storage_path.write_text(json.dumps(storage_data))

        with patch("notebooklm.auth.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (
                "csrf_token_abc",
                "session_id_xyz",
                "boq_labs-tailwind-frontend_20260315.02_p0",
            )

            result = runner.invoke(cli, ["auth", "check", "--test"])

        assert result.exit_code == 0
        assert "Token fetch" in result.output
        assert "pass" in result.output.lower() or "✓" in result.output

    def test_auth_check_with_test_flag_failure(self, runner, mock_storage_path):
        """Test auth check --test when token fetch fails."""
        storage_data = {
            "cookies": [
                {"name": "SID", "value": "test_sid", "domain": ".google.com"},
            ]
        }
        mock_storage_path.write_text(json.dumps(storage_data))

        with patch("notebooklm.auth.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = ValueError("Authentication expired")

            result = runner.invoke(cli, ["auth", "check", "--test"])

        assert result.exit_code == 0
        assert "Token fetch" in result.output
        assert "fail" in result.output.lower() or "✗" in result.output
        assert "expired" in result.output.lower() or "refresh" in result.output.lower()

    def test_auth_check_with_test_flag_json(self, runner, mock_storage_path):
        """Test auth check --test --json with successful token fetch."""
        storage_data = {
            "cookies": [
                {"name": "SID", "value": "test_sid", "domain": ".google.com"},
            ]
        }
        mock_storage_path.write_text(json.dumps(storage_data))

        with patch("notebooklm.auth.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (
                "csrf_12345",
                "sess_67890",
                "boq_labs-tailwind-frontend_20260315.03_p0",
            )

            result = runner.invoke(cli, ["auth", "check", "--test", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["intent"] == "DOCTOR"
        assert payload["route"]["mode"] == "check"
        assert payload["route"]["source_of_truth"] == "mixed"
        assert payload["route"]["cache_mode"] == "network"
        assert payload["route"]["transport"]["kind"] == "httpx"
        assert payload["route"]["transport"]["endpoint"] == "https://notebooklm.google.com/"
        assert payload["result"]["status"] == "ok"
        assert payload["result"]["checks"]["token_fetch"] is True
        assert payload["result"]["details"]["csrf_length"] == 10
        assert payload["result"]["details"]["session_id_length"] == 10

    def test_auth_check_env_var_takes_precedence(self, runner, mock_storage_path, monkeypatch):
        """Test auth check uses NOTEBOOKLM_AUTH_JSON when set."""
        # Even if storage file doesn't exist, env var should work
        if mock_storage_path.exists():
            mock_storage_path.unlink()

        env_storage = {
            "cookies": [
                {"name": "SID", "value": "env_sid", "domain": ".google.com"},
            ]
        }
        monkeypatch.setenv("NOTEBOOKLM_AUTH_JSON", json.dumps(env_storage))

        result = runner.invoke(cli, ["auth", "check", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["result"]["status"] == "ok"
        assert payload["result"]["details"]["auth_source"] == "NOTEBOOKLM_AUTH_JSON"

    def test_auth_check_shows_cookie_domains(self, runner, mock_storage_path):
        """Test auth check displays cookie domains."""
        storage_data = {
            "cookies": [
                {"name": "SID", "value": "test_sid", "domain": ".google.com"},
                {"name": "NID", "value": "test_nid", "domain": ".google.com.sg"},
            ]
        }
        mock_storage_path.write_text(json.dumps(storage_data))

        result = runner.invoke(cli, ["auth", "check", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert ".google.com" in payload["result"]["details"]["cookie_domains"]

    def test_auth_check_shows_cookies_by_domain(self, runner, mock_storage_path):
        """Test auth check --json includes detailed cookies_by_domain."""
        storage_data = {
            "cookies": [
                {"name": "SID", "value": "test_sid", "domain": ".google.com"},
                {"name": "HSID", "value": "test_hsid", "domain": ".google.com"},
                {"name": "SSID", "value": "test_ssid", "domain": ".google.com"},
                {"name": "SID", "value": "regional_sid", "domain": ".google.com.sg"},
                {"name": "__Secure-1PSID", "value": "secure1", "domain": ".google.com"},
            ]
        }
        mock_storage_path.write_text(json.dumps(storage_data))

        result = runner.invoke(cli, ["auth", "check", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        cookies_by_domain = payload["result"]["details"]["cookies_by_domain"]

        # Verify .google.com has expected cookies
        assert ".google.com" in cookies_by_domain
        assert "SID" in cookies_by_domain[".google.com"]
        assert "HSID" in cookies_by_domain[".google.com"]
        assert "__Secure-1PSID" in cookies_by_domain[".google.com"]

        # Verify regional domain has its cookies
        assert ".google.com.sg" in cookies_by_domain
        assert "SID" in cookies_by_domain[".google.com.sg"]

    def test_auth_check_skipped_token_fetch_shown(self, runner, mock_storage_path):
        """Test auth check shows token fetch as skipped when --test not used."""
        storage_data = {
            "cookies": [
                {"name": "SID", "value": "test_sid", "domain": ".google.com"},
            ]
        }
        mock_storage_path.write_text(json.dumps(storage_data))

        result = runner.invoke(cli, ["auth", "check", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["result"]["checks"]["token_fetch"] is None  # Not tested

    def test_auth_check_help(self, runner):
        """Test auth check --help shows usage information."""
        result = runner.invoke(cli, ["auth", "check", "--help"])

        assert result.exit_code == 0
        assert "Check authentication status" in result.output
        assert "--test" in result.output
        assert "--json" in result.output


class TestAuthInspectAndRefreshCommands:
    """Tests for the 'auth inspect' and 'auth refresh' commands."""

    @pytest.fixture
    def auth_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTEBOOKLM_HOME", str(tmp_path))
        return tmp_path

    @pytest.fixture
    def storage_file(self, auth_home):
        storage_path = auth_home / "storage_state.json"
        storage_path.write_text(
            json.dumps(
                {
                    "cookies": [
                        {"name": "SID", "value": "test_sid", "domain": ".google.com"},
                        {"name": "HSID", "value": "test_hsid", "domain": ".google.com"},
                    ],
                    "bl": "boq_labs-tailwind-frontend_20260315.10_p0",
                }
            ),
            encoding="utf-8",
        )
        return storage_path

    def _create_profile_snapshot(self, auth_home, storage_file):
        browser_profile = auth_home / "browser_profile"
        browser_profile.mkdir()
        manager = ProfileManager.open()
        try:
            profile = manager.get_profile("default")
            if profile is None:
                manager.create_profile(
                    profile_id="default",
                    display_name="Default",
                    account_email="user@example.com",
                    storage_state_path=storage_file,
                    browser_profile_path=browser_profile,
                    is_default=True,
                )
            else:
                manager.update_profile(
                    "default",
                    account_email="user@example.com",
                    storage_state_path=storage_file,
                    browser_profile_path=browser_profile,
                    is_default=True,
                )
            manager.upsert_auth_snapshot(
                "default",
                cookie_fingerprint=AuthTokens(
                    cookies={"HSID": "test_hsid", "SID": "test_sid"},
                    csrf_token="",
                    session_id="",
                    build_label="boq_labs-tailwind-frontend_20260315.10_p0",
                    storage_path=storage_file.resolve(),
                ).cookie_fingerprint,
                csrf_token="csrf_snapshot",
                session_id="session_snapshot",
                build_label="boq_labs-tailwind-frontend_20260315.10_p0",
                captured_at="2026-03-15T03:00:00+00:00",
                validated_at="2026-03-15T03:00:30+00:00",
                status="fresh",
                source="refresh_from_homepage",
            )
        finally:
            manager.close()

    def test_auth_inspect_json_outputs_canonical_envelope(self, runner, auth_home, storage_file):
        self._create_profile_snapshot(auth_home, storage_file)

        result = runner.invoke(cli, ["auth", "inspect", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["intent"] == "DOCTOR"
        assert payload["route"]["mode"] == "inspect"
        assert payload["route"]["transport"]["kind"] == "local"
        assert payload["result"]["profile"]["profile_id"] == "default"
        assert payload["result"]["build_label_present"] is True
        assert payload["result"]["csrf_present"] is True
        assert payload["result"]["session_id_present"] is True
        assert payload["result"]["snapshot"]["present"] is True
        assert payload["result"]["snapshot"]["status"] == "fresh"
        assert payload["result"]["cookie_fingerprint"]

    def test_auth_inspect_plain_output_shows_fingerprint_not_raw_cookie(
        self, runner, auth_home, storage_file
    ):
        self._create_profile_snapshot(auth_home, storage_file)

        result = runner.invoke(cli, ["auth", "inspect"])

        assert result.exit_code == 0, result.output
        assert "Cookie fingerprint" in result.output
        assert "test_sid" not in result.output
        assert "Snapshot age (s)" in result.output

    def test_auth_refresh_json_outputs_canonical_envelope_and_persistence(
        self, runner, auth_home, storage_file
    ):
        self._create_profile_snapshot(auth_home, storage_file)

        with patch("notebooklm.cli.session.NotebookLMClient") as mock_client_cls:
            mock_client = create_mock_client()

            async def _refresh_auth():
                storage_data = json.loads(storage_file.read_text(encoding="utf-8"))
                storage_data["bl"] = "boq_labs-tailwind-frontend_20260315.11_p0"
                storage_file.write_text(json.dumps(storage_data), encoding="utf-8")

                manager = ProfileManager.open()
                try:
                    manager.upsert_auth_snapshot(
                        "default",
                        cookie_fingerprint=AuthTokens(
                            cookies={"HSID": "test_hsid", "SID": "test_sid"},
                            csrf_token="new_csrf",
                            session_id="new_session",
                            build_label="boq_labs-tailwind-frontend_20260315.11_p0",
                            storage_path=storage_file.resolve(),
                        ).cookie_fingerprint,
                        csrf_token="new_csrf",
                        session_id="new_session",
                        build_label="boq_labs-tailwind-frontend_20260315.11_p0",
                        captured_at="2026-03-15T03:10:00+00:00",
                        validated_at="2026-03-15T03:10:05+00:00",
                        status="fresh",
                        source="refresh_from_homepage",
                    )
                finally:
                    manager.close()

                return AuthTokens(
                    cookies={"SID": "test_sid", "HSID": "test_hsid"},
                    csrf_token="new_csrf",
                    session_id="new_session",
                    build_label="boq_labs-tailwind-frontend_20260315.11_p0",
                    storage_path=storage_file.resolve(),
                )

            mock_client.refresh_auth = AsyncMock(side_effect=_refresh_auth)
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["auth", "refresh", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["intent"] == "LOCAL_METADATA"
        assert payload["route"]["mode"] == "refresh"
        assert payload["route"]["transport"]["kind"] == "httpx"
        assert payload["diagnostics"]["auth_refreshed"] is True
        assert payload["result"]["build_label"] == "boq_labs-tailwind-frontend_20260315.11_p0"
        assert payload["result"]["persisted_to_storage"] is True
        assert payload["result"]["persisted_snapshot"] is True
        assert payload["result"]["snapshot"]["source"] == "refresh_from_homepage"
        mock_client.refresh_auth.assert_awaited_once()

    def test_auth_refresh_requires_file_backed_auth(self, runner, monkeypatch):
        monkeypatch.setenv(
            "NOTEBOOKLM_AUTH_JSON",
            json.dumps(
                {
                    "cookies": [
                        {"name": "SID", "value": "inline_sid", "domain": ".google.com"},
                    ]
                }
            ),
        )

        result = runner.invoke(cli, ["auth", "refresh"])

        assert result.exit_code == 1
        assert "requires file-backed auth" in result.output

    def test_auth_group_help_lists_inspect_and_refresh(self, runner):
        result = runner.invoke(cli, ["auth", "--help"])

        assert result.exit_code == 0
        assert "check" in result.output
        assert "inspect" in result.output
        assert "refresh" in result.output


# =============================================================================
# EDGE CASES
# =============================================================================


class TestSessionEdgeCases:
    def test_use_handles_api_error_gracefully(self, runner, mock_auth, mock_context_file):
        """Test 'use' command handles API errors gracefully."""
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client.notebooks.get = AsyncMock(side_effect=Exception("API Error: Rate limited"))
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = (
                    "csrf",
                    "session",
                    "boq_labs-tailwind-frontend_20260315.01_p0",
                )

                # Patch in session module where it's imported
                with patch(
                    "notebooklm.cli.session.resolve_notebook_id", new_callable=AsyncMock
                ) as mock_resolve:
                    mock_resolve.return_value = "nb_error"

                    result = runner.invoke(cli, ["use", "nb_error"])

        # Should still set context with warning, not crash
        assert result.exit_code == 0
        # Error message should be shown
        assert "Warning" in result.output or "Error" in result.output or "nb_error" in result.output

    def test_status_shows_shared_notebook_correctly(self, runner, mock_context_file):
        """Test status correctly shows shared (non-owner) notebooks."""
        context_data = {
            "notebook_id": "nb_shared",
            "title": "Shared With Me",
            "is_owner": False,
            "created_at": "2024-01-15",
        }
        mock_context_file.write_text(json.dumps(context_data))

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Shared" in result.output or "nb_shared" in result.output

    def test_use_click_exception_propagates(self, runner, mock_auth, mock_context_file):
        """Test 'use' command re-raises ClickException from resolve_notebook_id."""
        with patch_main_cli_client() as mock_client_cls:
            mock_client = create_mock_client()
            mock_client_cls.return_value = mock_client

            with patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = (
                    "csrf",
                    "session",
                    "boq_labs-tailwind-frontend_20260315.01_p0",
                )

                # Patch resolve_notebook_id to raise ClickException (e.g., ambiguous ID)
                with patch(
                    "notebooklm.cli.session.resolve_notebook_id", new_callable=AsyncMock
                ) as mock_resolve:
                    mock_resolve.side_effect = click.ClickException("Multiple notebooks match 'nb'")

                    result = runner.invoke(cli, ["use", "nb"])

        # ClickException should propagate (exit code 1)
        assert result.exit_code == 1
        assert "Multiple notebooks match" in result.output

    def test_status_corrupted_json_with_json_flag(self, runner, mock_context_file):
        """Test status --json handles corrupted context file gracefully."""
        # Write invalid JSON but with notebook_id in helpers
        mock_context_file.write_text("{ invalid json }")

        # Mock get_current_notebook to return an ID (simulating partial read)
        with patch("notebooklm.cli.session.get_current_notebook") as mock_get_nb:
            mock_get_nb.return_value = "nb_corrupted"

            result = runner.invoke(cli, ["status", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["route"]["intent"] == "LOCAL_METADATA"
        assert payload["route"]["mode"] == "status"
        assert payload["route"]["notebook_id"] == "nb_corrupted"
        assert payload["result"]["has_context"] is True
        assert payload["result"]["notebook"]["id"] == "nb_corrupted"
        # Title and is_owner should be None due to JSONDecodeError
        assert payload["result"]["notebook"]["title"] is None
        assert payload["result"]["notebook"]["is_owner"] is None
