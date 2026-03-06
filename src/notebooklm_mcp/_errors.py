"""Exception mapping and sanitization helpers for notebooklm-mcp."""

from __future__ import annotations

import contextlib
import inspect
import logging
import re
from collections.abc import Callable, Mapping
from functools import wraps
import time
from typing import Any, ParamSpec, TypeVar, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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

MCP_INVALID_PARAMS_CODE = -32602
MCP_INTERNAL_ERROR_CODE = -32603
MCP_TOOL_EXECUTION_ERROR_CODE = -32000

DEFAULT_MAX_ERROR_MESSAGE_CHARS = 200

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "apikey",
        "api_key",
        "auth",
        "authorization",
        "code",
        "cookie",
        "csrf",
        "key",
        "password",
        "refresh_token",
        "session",
        "session_id",
        "sig",
        "signature",
        "state",
        "token",
    }
)

_REDACTED = "[REDACTED]"
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>(^|[\s,;]))"
    r"(?P<key>\b(?:cookie|set-cookie|authorization|bearer|token|csrf|session(?:_id)?|api[-_ ]?key|password)\b)"
    r"\s*[:=]\s*(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)

P = ParamSpec("P")
R = TypeVar("R")


class MCPToolError(RuntimeError):
    """MCP-compatible mapped error with code + structured metadata."""

    def __init__(
        self,
        message: str,
        *,
        mcp_code: int,
        error_code: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.mcp_code = mcp_code
        self.error_code = error_code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        """Return a structured payload for tool responses."""
        payload = {
            "ok": False,
            "error_code": self.error_code,
            "message": self.message,
        }
        payload.update(self.details)
        return payload


def sanitize_error_message(message: str, *, max_chars: int = DEFAULT_MAX_ERROR_MESSAGE_CHARS) -> str:
    """Sanitize potentially sensitive values from error messages."""
    compact = " ".join(str(message).split())
    if not compact:
        return "Unexpected error."

    compact = _URL_RE.sub(lambda match: _redact_url(match.group(0)), compact)
    compact = _SENSITIVE_ASSIGNMENT_RE.sub(_redact_assignment, compact)

    if max_chars > 0 and len(compact) > max_chars:
        compact = compact[: max_chars - 1] + "…"
    return compact


def map_exception(
    error: Exception,
    *,
    max_message_length: int = DEFAULT_MAX_ERROR_MESSAGE_CHARS,
) -> MCPToolError:
    """Map notebooklm-py exceptions to MCP-friendly errors."""
    message = sanitize_error_message(str(error), max_chars=max_message_length)

    if isinstance(error, ValidationError):
        return MCPToolError(
            message,
            mcp_code=MCP_INVALID_PARAMS_CODE,
            error_code="invalid_params",
        )

    if isinstance(error, NotebookNotFoundError):
        return MCPToolError(
            f"notebook_id not found: {error.notebook_id}",
            mcp_code=MCP_INVALID_PARAMS_CODE,
            error_code="invalid_params",
        )

    if isinstance(error, SourceNotFoundError):
        return MCPToolError(
            f"source_id not found: {error.source_id}",
            mcp_code=MCP_INVALID_PARAMS_CODE,
            error_code="invalid_params",
        )

    if isinstance(error, AuthError):
        return MCPToolError(
            message or "Authentication expired.",
            mcp_code=MCP_TOOL_EXECUTION_ERROR_CODE,
            error_code="auth_expired",
            details={"hint": "Run 'notebooklm login' to re-authenticate."},
        )

    if isinstance(error, RateLimitError):
        details: dict[str, Any] = {}
        if error.retry_after is not None:
            details["retry_after"] = error.retry_after
        return MCPToolError(
            message,
            mcp_code=MCP_TOOL_EXECUTION_ERROR_CODE,
            error_code="rate_limited",
            details=details,
        )

    if isinstance(error, RPCTimeoutError):
        return MCPToolError(
            message or "NotebookLM request timed out.",
            mcp_code=MCP_TOOL_EXECUTION_ERROR_CODE,
            error_code="rpc_timeout",
        )

    if isinstance(error, NetworkError):
        return MCPToolError(
            message or "Network error while calling NotebookLM.",
            mcp_code=MCP_TOOL_EXECUTION_ERROR_CODE,
            error_code="network_error",
        )

    if isinstance(error, ServerError):
        return MCPToolError(
            message or "NotebookLM server error.",
            mcp_code=MCP_TOOL_EXECUTION_ERROR_CODE,
            error_code="server_error",
        )

    if isinstance(error, NotebookLMError):
        return MCPToolError(
            message or "NotebookLM tool execution failed.",
            mcp_code=MCP_TOOL_EXECUTION_ERROR_CODE,
            error_code="tool_execution_error",
        )

    return MCPToolError(
        "Internal server error.",
        mcp_code=MCP_INTERNAL_ERROR_CODE,
        error_code="internal_error",
    )


def build_error_result(
    error: Exception,
    *,
    max_message_length: int = DEFAULT_MAX_ERROR_MESSAGE_CHARS,
) -> dict[str, Any]:
    """Return a structured error payload suitable for JSON tool responses."""
    mapped = error if isinstance(error, MCPToolError) else map_exception(
        error,
        max_message_length=max_message_length,
    )
    return mapped.to_dict()


def _resolve_app_context_from_candidate(candidate: Any) -> Any | None:
    if candidate is None:
        return None

    request_context = getattr(candidate, "request_context", None)
    app_context = getattr(request_context, "lifespan_context", None)
    if app_context is not None:
        return app_context

    app_context = getattr(candidate, "lifespan_context", None)
    if app_context is not None:
        return app_context

    return None


def _resolve_app_context_from_call(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> Any | None:
    candidates: list[Any] = []
    if args:
        candidates.append(args[0])
    if "ctx" in kwargs:
        candidates.append(kwargs["ctx"])
    if "context" in kwargs:
        candidates.append(kwargs["context"])

    for candidate in candidates:
        app_context = _resolve_app_context_from_candidate(candidate)
        if app_context is not None:
            return app_context
    return None


def _extract_audit_args(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
    except Exception:
        return {}

    payload: dict[str, Any] = {}
    for key, value in bound.arguments.items():
        if key in {"self", "cls", "ctx", "context", "request_context"}:
            continue
        payload[key] = value
    return payload


def _get_stats(app_context: Any) -> Any | None:
    stats = getattr(app_context, "stats", None) if app_context is not None else None
    if callable(getattr(stats, "record_request", None)):
        return stats
    return None


def _get_audit(app_context: Any) -> Any | None:
    audit = getattr(app_context, "audit", None) if app_context is not None else None
    if callable(getattr(audit, "record_call", None)):
        return audit
    return None


def _record_request(stats: Any | None, tool_name: str) -> None:
    if stats is None:
        return
    with contextlib.suppress(Exception):
        stats.record_request(tool_name)


def _duration_ms(start_ts: float) -> int:
    return max(0, int((time.perf_counter() - start_ts) * 1000))


def _record_success(
    audit: Any | None,
    *,
    tool_name: str,
    started_ts: float,
    args: Mapping[str, Any],
) -> None:
    if audit is None:
        return
    with contextlib.suppress(Exception):
        audit.record_call(
            tool_name=tool_name,
            duration_ms=_duration_ms(started_ts),
            status="ok",
            args=args,
        )


def _record_failure(
    stats: Any | None,
    audit: Any | None,
    *,
    tool_name: str,
    started_ts: float,
    args: Mapping[str, Any],
    error: MCPToolError,
) -> None:
    if stats is not None:
        with contextlib.suppress(Exception):
            stats.record_error(tool_name, error.error_code, error.message)
        if error.error_code == "rate_limited":
            with contextlib.suppress(Exception):
                stats.record_backoff()

    if audit is not None:
        with contextlib.suppress(Exception):
            audit.record_call(
                tool_name=tool_name,
                duration_ms=_duration_ms(started_ts),
                status="error",
                error_code=error.error_code,
                args=args,
                error_message=error.message,
            )


def _create_inflight_guard(stats: Any | None) -> Any | None:
    if stats is None:
        return None
    enter_inflight = getattr(stats, "enter_inflight", None)
    if not callable(enter_inflight):
        return None
    try:
        return enter_inflight()
    except Exception:
        return None


@contextlib.asynccontextmanager
async def _inflight_guard_async(stats: Any | None):
    guard = _create_inflight_guard(stats)
    if guard is None:
        yield
        return

    if callable(getattr(guard, "__aenter__", None)) and callable(
        getattr(guard, "__aexit__", None)
    ):
        async with guard:
            yield
        return

    if callable(getattr(guard, "__enter__", None)) and callable(
        getattr(guard, "__exit__", None)
    ):
        with guard:
            yield
        return

    yield


@contextlib.contextmanager
def _inflight_guard_sync(stats: Any | None):
    guard = _create_inflight_guard(stats)
    if guard is None:
        yield
        return

    if callable(getattr(guard, "__enter__", None)) and callable(
        getattr(guard, "__exit__", None)
    ):
        with guard:
            yield
        return

    yield


def handle_mcp_errors(
    func: Callable[P, R] | None = None,
    *,
    logger: logging.Logger | None = None,
    max_message_length: int = DEFAULT_MAX_ERROR_MESSAGE_CHARS,
) -> Callable[[Callable[P, R]], Callable[P, R]] | Callable[P, R]:
    """Decorator that maps tool exceptions to ``MCPToolError`` consistently."""

    def decorator(inner: Callable[P, R]) -> Callable[P, R]:
        active_logger = logger or logging.getLogger("notebooklm_mcp.errors")

        if inspect.iscoroutinefunction(inner):

            @wraps(inner)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                app_context = _resolve_app_context_from_call(cast(tuple[Any, ...], args), kwargs)
                stats = _get_stats(app_context)
                audit = _get_audit(app_context)
                tool_name = inner.__name__
                audit_args = _extract_audit_args(
                    cast(Callable[..., Any], inner),
                    cast(tuple[Any, ...], args),
                    kwargs,
                )
                started_ts = time.perf_counter()

                _record_request(stats, tool_name)
                async with _inflight_guard_async(stats):
                    try:
                        result = await cast(Callable[P, Any], inner)(*args, **kwargs)
                    except MCPToolError as mapped_error:
                        _record_failure(
                            stats,
                            audit,
                            tool_name=tool_name,
                            started_ts=started_ts,
                            args=audit_args,
                            error=mapped_error,
                        )
                        raise
                    except Exception as exc:
                        active_logger.exception("MCP tool execution failed: %s", tool_name)
                        mapped_error = map_exception(
                            exc,
                            max_message_length=max_message_length,
                        )
                        _record_failure(
                            stats,
                            audit,
                            tool_name=tool_name,
                            started_ts=started_ts,
                            args=audit_args,
                            error=mapped_error,
                        )
                        raise mapped_error from exc

                _record_success(
                    audit,
                    tool_name=tool_name,
                    started_ts=started_ts,
                    args=audit_args,
                )
                return result

            return cast(Callable[P, R], async_wrapper)

        @wraps(inner)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            app_context = _resolve_app_context_from_call(cast(tuple[Any, ...], args), kwargs)
            stats = _get_stats(app_context)
            audit = _get_audit(app_context)
            tool_name = inner.__name__
            audit_args = _extract_audit_args(
                cast(Callable[..., Any], inner),
                cast(tuple[Any, ...], args),
                kwargs,
            )
            started_ts = time.perf_counter()

            _record_request(stats, tool_name)
            with _inflight_guard_sync(stats):
                try:
                    result = inner(*args, **kwargs)
                except MCPToolError as mapped_error:
                    _record_failure(
                        stats,
                        audit,
                        tool_name=tool_name,
                        started_ts=started_ts,
                        args=audit_args,
                        error=mapped_error,
                    )
                    raise
                except Exception as exc:
                    active_logger.exception("MCP tool execution failed: %s", tool_name)
                    mapped_error = map_exception(
                        exc,
                        max_message_length=max_message_length,
                    )
                    _record_failure(
                        stats,
                        audit,
                        tool_name=tool_name,
                        started_ts=started_ts,
                        args=audit_args,
                        error=mapped_error,
                    )
                    raise mapped_error from exc

            _record_success(
                audit,
                tool_name=tool_name,
                started_ts=started_ts,
                args=audit_args,
            )
            return result

        return cast(Callable[P, R], sync_wrapper)

    if func is not None:
        return decorator(func)
    return decorator


def _redact_url(url: str) -> str:
    split = urlsplit(url)
    if not split.query:
        return url

    redacted_pairs = []
    for key, _ in parse_qsl(split.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_QUERY_KEYS:
            redacted_pairs.append((key, _REDACTED))
        else:
            redacted_pairs.append((key, _REDACTED))

    query = urlencode(redacted_pairs, doseq=True) if redacted_pairs else _REDACTED
    return urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


def _redact_assignment(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{match.group('key')}={_REDACTED}"


__all__ = [
    "DEFAULT_MAX_ERROR_MESSAGE_CHARS",
    "MCP_INTERNAL_ERROR_CODE",
    "MCP_INVALID_PARAMS_CODE",
    "MCP_TOOL_EXECUTION_ERROR_CODE",
    "MCPToolError",
    "build_error_result",
    "handle_mcp_errors",
    "map_exception",
    "sanitize_error_message",
]
