"""Trace-context primitives for command and workflow observability."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
from typing import Iterator


_CROCKFORD_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CURRENT_TRACE: ContextVar["TraceContext | None"] = ContextVar(
    "notebooklm_current_trace",
    default=None,
)


@dataclass(frozen=True)
class TraceContext:
    """Context-local identifiers that tie together one execution flow."""

    trace_id: str
    run_id: str | None = None

    def with_run_id(self, run_id: str | None) -> "TraceContext":
        """Return a copy of this trace context with an updated run identifier."""
        return TraceContext(trace_id=self.trace_id, run_id=run_id)


def _normalize_timestamp(ts: datetime | None = None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _encode_crockford_base32(value: int, length: int) -> str:
    chars = ["0"] * length
    for index in range(length - 1, -1, -1):
        chars[index] = _CROCKFORD_BASE32[value & 31]
        value >>= 5
    return "".join(chars)


def generate_trace_id(ts: datetime | None = None) -> str:
    """Generate a `trc_<ulid>` identifier using a stdlib-only ULID encoder."""
    timestamp = _normalize_timestamp(ts)
    timestamp_ms = int(timestamp.timestamp() * 1000)
    ulid_value = (timestamp_ms << 80) | secrets.randbits(80)
    return f"trc_{_encode_crockford_base32(ulid_value, 26)}"


def current_trace() -> TraceContext | None:
    """Return the currently bound trace context for this execution context."""
    return _CURRENT_TRACE.get()


def require_trace() -> TraceContext:
    """Return the active trace context or fail if the caller is outside tracing."""
    trace = current_trace()
    if trace is None:
        raise RuntimeError("No active trace context")
    return trace


@contextmanager
def bind_trace(
    trace: TraceContext | None = None,
    *,
    trace_id: str | None = None,
    run_id: str | None = None,
    ts: datetime | None = None,
) -> Iterator[TraceContext]:
    """Bind a trace context for the current call stack and restore on exit."""
    if trace is None:
        trace = TraceContext(trace_id=trace_id or generate_trace_id(ts), run_id=run_id)
    token = _CURRENT_TRACE.set(trace)
    try:
        yield trace
    finally:
        _CURRENT_TRACE.reset(token)


__all__ = [
    "TraceContext",
    "bind_trace",
    "current_trace",
    "generate_trace_id",
    "require_trace",
]
