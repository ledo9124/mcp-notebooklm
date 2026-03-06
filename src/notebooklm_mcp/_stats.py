"""Operational counters for notebooklm-mcp diagnostics."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
import threading
import time
from typing import Any

from ._errors import sanitize_error_message

DEFAULT_WINDOW_SECONDS = 3600.0
DEFAULT_MAX_ERROR_EVENTS = 100
DEFAULT_MAX_ERROR_MESSAGE_CHARS = 200


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    """Redacted error event tracked in rolling diagnostics windows."""

    ts: str
    code: str
    tool: str | None = None
    message: str | None = None


class InflightGuard(AbstractContextManager[None], AbstractAsyncContextManager[None]):
    """Context manager that increments/decrements ``Stats.inflight`` safely."""

    def __init__(self, stats: "Stats") -> None:
        self._stats = stats

    def __enter__(self) -> None:
        self._stats._inc_inflight()
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._stats._dec_inflight()
        return False

    async def __aenter__(self) -> None:
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return self.__exit__(exc_type, exc, tb)


class Stats:
    """Thread-safe operational counters with rolling one-hour windows."""

    def __init__(
        self,
        *,
        time_fn: Callable[[], float] | None = None,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        max_error_events: int = DEFAULT_MAX_ERROR_EVENTS,
        max_error_message_chars: int = DEFAULT_MAX_ERROR_MESSAGE_CHARS,
    ) -> None:
        self._time_fn = time_fn or time.time
        self._window_seconds = float(window_seconds)
        self._max_error_events = max(1, int(max_error_events))
        self._max_error_message_chars = max(1, int(max_error_message_chars))
        self._lock = threading.Lock()
        self._start_time = self._time_fn()
        self._requests_total = 0
        self._requests_window: deque[float] = deque()
        self._errors_total = 0
        self._errors_by_code: Counter[str] = Counter()
        self._errors_window: deque[tuple[float, ErrorEvent]] = deque(maxlen=self._max_error_events)
        self._backoff_window: deque[float] = deque()
        self._inflight = 0

    def record_request(self, tool_name: str | None = None) -> None:
        """Record a tool request event."""
        del tool_name  # Reserved for future per-tool counters
        with self._lock:
            now = self._time_fn()
            self._prune(now)
            self._requests_total += 1
            self._requests_window.append(now)

    def record_error(self, tool_name: str, code: str, message: str) -> None:
        """Record a redacted error event."""
        sanitized = sanitize_error_message(message, max_chars=self._max_error_message_chars)
        event = ErrorEvent(
            ts=self._to_iso(self._time_fn()),
            code=code,
            tool=tool_name or None,
            message=sanitized or None,
        )
        with self._lock:
            now = self._time_fn()
            self._prune(now)
            self._errors_total += 1
            self._errors_by_code[code] += 1
            self._errors_window.append((now, event))

    def record_backoff(self) -> None:
        """Record a rate-limit/backoff event."""
        with self._lock:
            now = self._time_fn()
            self._prune(now)
            self._backoff_window.append(now)

    def enter_inflight(self) -> InflightGuard:
        """Return a context guard for inflight tracking."""
        return InflightGuard(self)

    def snapshot(self) -> dict[str, Any]:
        """Return a diagnostics snapshot suitable for JSON responses."""
        with self._lock:
            now = self._time_fn()
            self._prune(now)
            errors_recent = [event for _, event in reversed(self._errors_window)]
            return {
                "start_time": self._to_iso(self._start_time),
                "uptime_seconds": max(0.0, now - self._start_time),
                "requests_total": self._requests_total,
                "requests_1h": len(self._requests_window),
                "errors_total": self._errors_total,
                "errors_by_code": dict(self._errors_by_code),
                "errors_1h": [self._event_to_dict(event) for event in errors_recent],
                "backoff_events_1h": len(self._backoff_window),
                "inflight": self._inflight,
            }

    def _inc_inflight(self) -> None:
        with self._lock:
            now = self._time_fn()
            self._prune(now)
            self._inflight += 1

    def _dec_inflight(self) -> None:
        with self._lock:
            now = self._time_fn()
            self._prune(now)
            self._inflight = max(0, self._inflight - 1)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._requests_window and self._requests_window[0] < cutoff:
            self._requests_window.popleft()
        while self._backoff_window and self._backoff_window[0] < cutoff:
            self._backoff_window.popleft()
        while self._errors_window and self._errors_window[0][0] < cutoff:
            self._errors_window.popleft()

    @staticmethod
    def _to_iso(epoch_seconds: float) -> str:
        return datetime.fromtimestamp(epoch_seconds, UTC).isoformat()

    @staticmethod
    def _event_to_dict(event: ErrorEvent) -> dict[str, Any]:
        return {
            "ts": event.ts,
            "code": event.code,
            "tool": event.tool,
            "message": event.message,
        }


__all__ = [
    "DEFAULT_MAX_ERROR_EVENTS",
    "DEFAULT_MAX_ERROR_MESSAGE_CHARS",
    "DEFAULT_WINDOW_SECONDS",
    "ErrorEvent",
    "InflightGuard",
    "Stats",
]
