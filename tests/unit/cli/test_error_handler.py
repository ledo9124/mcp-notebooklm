"""Tests for centralized CLI error handling."""

import json

import pytest

from notebooklm.cli.error_handler import handle_errors
from notebooklm.exceptions import (
    AuthError,
    ConfigurationError,
    NetworkError,
    RateLimitError,
    RPCError,
    ValidationError,
)


def _assert_handle_errors_envelope(data: dict, *, code: str) -> dict:
    assert data["ok"] is False
    assert data["trace_id"].startswith("trc_")
    assert data["run_id"].startswith("run_")
    assert data["route"]["intent"] == "LOCAL_METADATA"
    assert data["route"]["mode"] == "handle_errors"
    assert data["route"]["notebook_id"] is None
    assert data["route"]["profile_id"] == "default"
    assert data["route"]["source_of_truth"] == "local_cache"
    assert data["route"]["cache_mode"] == "offline"
    assert data["route"]["transport"] == {"kind": "local", "endpoint": None, "rpcid": None}
    assert data["diagnostics"]["elapsed_ms"] == 0
    assert data["result"]["code"] == code
    return data["result"]


class TestHandleErrorsExitCodes:
    """Test that exceptions produce correct exit codes."""

    def test_validation_error_exits_with_code_1(self):
        """ValidationError should exit with code 1 (user error)."""
        with pytest.raises(SystemExit) as exc_info, handle_errors():
            raise ValidationError("Invalid input")
        assert exc_info.value.code == 1

    def test_auth_error_exits_with_code_1(self):
        """AuthError should exit with code 1 (user error)."""
        with pytest.raises(SystemExit) as exc_info, handle_errors():
            raise AuthError("Token expired")
        assert exc_info.value.code == 1

    def test_config_error_exits_with_code_1(self):
        """ConfigurationError should exit with code 1 (user error)."""
        with pytest.raises(SystemExit) as exc_info, handle_errors():
            raise ConfigurationError("Missing config")
        assert exc_info.value.code == 1

    def test_network_error_exits_with_code_1(self):
        """NetworkError should exit with code 1 (user error)."""
        with pytest.raises(SystemExit) as exc_info, handle_errors():
            raise NetworkError("Connection failed")
        assert exc_info.value.code == 1

    def test_rate_limit_error_exits_with_code_1(self):
        """RateLimitError should exit with code 1 (user error)."""
        with pytest.raises(SystemExit) as exc_info, handle_errors():
            raise RateLimitError("Too many requests")
        assert exc_info.value.code == 1

    def test_unexpected_error_exits_with_code_2(self):
        """Unexpected exceptions should exit with code 2 (system error)."""
        with pytest.raises(SystemExit) as exc_info, handle_errors():
            raise RuntimeError("Unexpected bug")
        assert exc_info.value.code == 2


class TestHandleErrorsJsonOutput:
    """Test JSON error output format."""

    def test_validation_error_json_format(self, capsys):
        """ValidationError should produce correct JSON structure."""
        with pytest.raises(SystemExit), handle_errors(json_output=True):
            raise ValidationError("Invalid input")

        output = capsys.readouterr().out
        data = json.loads(output)
        result = _assert_handle_errors_envelope(data, code="VALIDATION_ERROR")
        assert "Invalid input" in result["message"]

    def test_rate_limit_error_json_includes_retry_after(self, capsys):
        """RateLimitError with retry_after should include it in JSON output."""
        with pytest.raises(SystemExit), handle_errors(json_output=True):
            raise RateLimitError("Too many requests", retry_after=30)

        output = capsys.readouterr().out
        data = json.loads(output)
        result = _assert_handle_errors_envelope(data, code="RATE_LIMITED")
        assert result["retry_after"] == 30
        assert "30s" in result["message"]

    def test_rate_limit_error_json_without_retry_after(self, capsys):
        """RateLimitError without retry_after should not include extra field."""
        with pytest.raises(SystemExit), handle_errors(json_output=True):
            raise RateLimitError("Too many requests")

        output = capsys.readouterr().out
        data = json.loads(output)
        result = _assert_handle_errors_envelope(data, code="RATE_LIMITED")
        assert "retry_after" not in result

    def test_rpc_error_verbose_includes_method_id(self, capsys):
        """RPCError with verbose=True should include method_id in JSON."""
        with pytest.raises(SystemExit), handle_errors(json_output=True, verbose=True):
            raise RPCError("RPC failed", method_id="abc123")

        output = capsys.readouterr().out
        data = json.loads(output)
        result = _assert_handle_errors_envelope(data, code="NOTEBOOKLM_ERROR")
        assert result["method_id"] == "abc123"

    def test_rpc_error_non_verbose_excludes_method_id(self, capsys):
        """RPCError without verbose should not include method_id."""
        with pytest.raises(SystemExit), handle_errors(json_output=True, verbose=False):
            raise RPCError("RPC failed", method_id="abc123")

        output = capsys.readouterr().out
        data = json.loads(output)
        result = _assert_handle_errors_envelope(data, code="NOTEBOOKLM_ERROR")
        assert "method_id" not in result

    def test_unexpected_error_json_format(self, capsys):
        """Unexpected errors should produce UNEXPECTED_ERROR code."""
        with pytest.raises(SystemExit), handle_errors(json_output=True):
            raise RuntimeError("Something broke")

        output = capsys.readouterr().out
        data = json.loads(output)
        result = _assert_handle_errors_envelope(data, code="UNEXPECTED_ERROR")
        assert "Something broke" in result["message"]


class TestHandleErrorsTextOutput:
    """Test text error output with hints."""

    def test_auth_error_shows_hint(self, capsys):
        """AuthError should show re-authentication hint in text mode."""
        with pytest.raises(SystemExit), handle_errors(json_output=False):
            raise AuthError("Token expired")

        output = capsys.readouterr().err
        assert "Authentication error" in output
        assert "notebooklm login" in output

    def test_network_error_shows_hint(self, capsys):
        """NetworkError should show connection hint in text mode."""
        with pytest.raises(SystemExit), handle_errors(json_output=False):
            raise NetworkError("Connection refused")

        output = capsys.readouterr().err
        assert "Network error" in output
        assert "internet connection" in output

    def test_unexpected_error_shows_bug_report_hint(self, capsys):
        """Unexpected errors should show bug report hint."""
        with pytest.raises(SystemExit), handle_errors(json_output=False):
            raise RuntimeError("Oops")

        output = capsys.readouterr().err
        assert "Unexpected error" in output
        assert "bug" in output.lower()
        assert "github" in output.lower()

    def test_hint_not_shown_in_json_mode(self, capsys):
        """Hints should not appear in JSON output."""
        with pytest.raises(SystemExit), handle_errors(json_output=True):
            raise AuthError("Token expired")

        output = capsys.readouterr().out
        data = json.loads(output)
        # Hint text should not be in the JSON structure
        result = _assert_handle_errors_envelope(data, code="AUTH_ERROR")
        assert "login" not in json.dumps(result).lower()


class TestHandleErrorsKeyboardInterrupt:
    """Test keyboard interrupt handling."""

    def test_keyboard_interrupt_exits_with_code_130(self):
        """KeyboardInterrupt should exit with code 130."""
        with pytest.raises(SystemExit) as exc_info, handle_errors():
            raise KeyboardInterrupt()
        assert exc_info.value.code == 130

    def test_keyboard_interrupt_json_format(self, capsys):
        """KeyboardInterrupt should produce CANCELLED code in JSON mode."""
        with pytest.raises(SystemExit), handle_errors(json_output=True):
            raise KeyboardInterrupt()

        output = capsys.readouterr().out
        data = json.loads(output)
        _assert_handle_errors_envelope(data, code="CANCELLED")
