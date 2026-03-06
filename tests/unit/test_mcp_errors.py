"""Unit tests for notebooklm_mcp._errors."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from notebooklm.exceptions import (
    AuthError,
    NetworkError,
    NotebookLMError,
    NotebookNotFoundError,
    RPCTimeoutError,
    RateLimitError,
    ServerError,
    SourceNotFoundError,
    ValidationError,
)
from notebooklm_mcp._errors import (
    MCP_INTERNAL_ERROR_CODE,
    MCP_INVALID_PARAMS_CODE,
    MCP_TOOL_EXECUTION_ERROR_CODE,
    MCPToolError,
    build_error_result,
    handle_mcp_errors,
    map_exception,
    sanitize_error_message,
)
from notebooklm_mcp._audit import AuditLog
from notebooklm_mcp._stats import Stats


def test_sanitize_error_message_redacts_sensitive_values() -> None:
    message = (
        "Authorization=Bearer123 token=abc123 "
        "https://example.com/path?token=abc&foo=bar Cookie:session=zzz"
    )
    sanitized = sanitize_error_message(message)

    assert "Bearer123" not in sanitized
    assert "abc123" not in sanitized
    assert "session=zzz" not in sanitized
    assert "token=%5BREDACTED%5D" in sanitized
    assert "foo=%5BREDACTED%5D" in sanitized


def test_sanitize_error_message_truncates() -> None:
    message = "x" * 40
    sanitized = sanitize_error_message(message, max_chars=12)
    assert len(sanitized) == 12
    assert sanitized.endswith("…")


def test_map_validation_error() -> None:
    mapped = map_exception(ValidationError("invalid notebook_id"))
    assert mapped.mcp_code == MCP_INVALID_PARAMS_CODE
    assert mapped.error_code == "invalid_params"


def test_map_notebook_not_found_error() -> None:
    mapped = map_exception(NotebookNotFoundError("nb-123"))
    assert mapped.mcp_code == MCP_INVALID_PARAMS_CODE
    assert mapped.error_code == "invalid_params"
    assert mapped.message == "notebook_id not found: nb-123"


def test_map_source_not_found_error() -> None:
    mapped = map_exception(SourceNotFoundError("src-123"))
    assert mapped.mcp_code == MCP_INVALID_PARAMS_CODE
    assert mapped.error_code == "invalid_params"
    assert mapped.message == "source_id not found: src-123"


def test_map_auth_error() -> None:
    mapped = map_exception(AuthError("expired token"))
    assert mapped.mcp_code == MCP_TOOL_EXECUTION_ERROR_CODE
    assert mapped.error_code == "auth_expired"
    assert mapped.details["hint"] == "Run 'notebooklm login' to re-authenticate."


def test_map_rate_limit_error_includes_retry_after() -> None:
    mapped = map_exception(RateLimitError("limited", retry_after=15))
    assert mapped.mcp_code == MCP_TOOL_EXECUTION_ERROR_CODE
    assert mapped.error_code == "rate_limited"
    assert mapped.details["retry_after"] == 15


def test_map_timeout_error() -> None:
    mapped = map_exception(RPCTimeoutError("timeout after token=abc"))
    assert mapped.mcp_code == MCP_TOOL_EXECUTION_ERROR_CODE
    assert mapped.error_code == "rpc_timeout"
    assert "abc" not in mapped.message


def test_map_network_error() -> None:
    mapped = map_exception(NetworkError("request failed token=abc"))
    assert mapped.mcp_code == MCP_TOOL_EXECUTION_ERROR_CODE
    assert mapped.error_code == "network_error"
    assert "abc" not in mapped.message


def test_map_server_error() -> None:
    mapped = map_exception(ServerError("500: upstream failed"))
    assert mapped.mcp_code == MCP_TOOL_EXECUTION_ERROR_CODE
    assert mapped.error_code == "server_error"


def test_map_notebooklm_error_catch_all() -> None:
    mapped = map_exception(NotebookLMError("general failure"))
    assert mapped.mcp_code == MCP_TOOL_EXECUTION_ERROR_CODE
    assert mapped.error_code == "tool_execution_error"


def test_map_internal_error_for_unknown_exception() -> None:
    mapped = map_exception(RuntimeError("boom"))
    assert mapped.mcp_code == MCP_INTERNAL_ERROR_CODE
    assert mapped.error_code == "internal_error"
    assert mapped.message == "Internal server error."


def test_build_error_result() -> None:
    payload = build_error_result(ValidationError("bad args"))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid_params"


def test_build_error_result_passes_through_mapped_error() -> None:
    mapped = MCPToolError(
        "already mapped",
        mcp_code=MCP_TOOL_EXECUTION_ERROR_CODE,
        error_code="custom_code",
        details={"x": 1},
    )
    payload = build_error_result(mapped)
    assert payload["message"] == "already mapped"
    assert payload["error_code"] == "custom_code"
    assert payload["x"] == 1


def test_handle_mcp_errors_sync_decorator_maps_exception() -> None:
    @handle_mcp_errors
    def failing_tool() -> None:
        raise ValidationError("bad request")

    with pytest.raises(MCPToolError) as exc_info:
        failing_tool()

    mapped = exc_info.value
    assert mapped.mcp_code == MCP_INVALID_PARAMS_CODE
    assert mapped.error_code == "invalid_params"


@pytest.mark.asyncio
async def test_handle_mcp_errors_async_decorator_maps_exception() -> None:
    @handle_mcp_errors
    async def failing_tool() -> None:
        raise AuthError("expired")

    with pytest.raises(MCPToolError) as exc_info:
        await failing_tool()

    mapped = exc_info.value
    assert mapped.mcp_code == MCP_TOOL_EXECUTION_ERROR_CODE
    assert mapped.error_code == "auth_expired"


@pytest.mark.asyncio
async def test_handle_mcp_errors_async_records_stats_and_audit() -> None:
    stats = Stats()
    audit = AuditLog(max_entries=10)
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(
                stats=stats,
                audit=audit,
            )
        )
    )

    @handle_mcp_errors
    async def tracked_tool(ctx: object, notebook_id: str, question: str) -> str:
        del ctx
        return f"ok:{notebook_id}:{question}"

    result = await tracked_tool(ctx, notebook_id="nb-1", question="secret value")

    assert result.startswith("ok:nb-1:")
    snapshot = stats.snapshot()
    assert snapshot["requests_total"] == 1
    assert snapshot["errors_total"] == 0
    assert snapshot["inflight"] == 0

    entries = audit.recent(limit=1)
    assert len(entries) == 1
    assert entries[0].tool_name == "tracked_tool"
    assert entries[0].status == "ok"
    assert "notebook_id=nb-1" in entries[0].args_summary
    assert "secret value" not in entries[0].args_summary


@pytest.mark.asyncio
async def test_handle_mcp_errors_async_records_rate_limit_backoff_and_audit_error() -> None:
    stats = Stats()
    audit = AuditLog(max_entries=10)
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(
                stats=stats,
                audit=audit,
            )
        )
    )

    @handle_mcp_errors
    async def limited_tool(ctx: object, question: str) -> None:
        del ctx, question
        raise RateLimitError("token=abc123", retry_after=5)

    with pytest.raises(MCPToolError) as exc_info:
        await limited_tool(ctx, question="what happened")

    assert exc_info.value.error_code == "rate_limited"

    snapshot = stats.snapshot()
    assert snapshot["requests_total"] == 1
    assert snapshot["errors_total"] == 1
    assert snapshot["errors_by_code"] == {"rate_limited": 1}
    assert snapshot["backoff_events_1h"] == 1
    assert snapshot["inflight"] == 0

    entries = audit.recent(limit=1)
    assert len(entries) == 1
    assert entries[0].tool_name == "limited_tool"
    assert entries[0].status == "error"
    assert entries[0].error_code == "rate_limited"
    assert entries[0].error_message is not None
    assert "abc123" not in entries[0].error_message
    assert "what happened" not in entries[0].args_summary
