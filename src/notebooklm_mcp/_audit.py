"""Redacted audit log primitives for notebooklm-mcp."""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ._errors import DEFAULT_MAX_ERROR_MESSAGE_CHARS, sanitize_error_message

_SENSITIVE_ARG_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "content",
        "cookie",
        "cookies",
        "csrf",
        "custom_instructions",
        "custom_prompt",
        "password",
        "prompt",
        "raw_content",
        "refresh_token",
        "session",
        "session_id",
        "source_content",
        "source_text",
        "text",
        "token",
    }
)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in _SENSITIVE_ARG_KEYS:
        return True
    if normalized.endswith(("token", "secret", "password", "cookie")):
        return True
    return False


def _is_identifier_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in {"id", "notebook_id", "source_id", "conversation_id", "artifact_id"}:
        return True
    return normalized.endswith("_id")


def _summarize_value(key: str, value: Any) -> str:
    if _is_sensitive_key(key):
        if isinstance(value, str):
            return f"[{len(value)} chars]"
        if isinstance(value, (bytes, bytearray)):
            return f"[{len(value)} bytes]"
        if isinstance(value, (list, tuple, set, frozenset)):
            return f"[{len(value)} items]"
        if isinstance(value, Mapping):
            return f"[{len(value)} keys]"
        return "[REDACTED]"

    if isinstance(value, Enum):
        return value.name.lower()

    if isinstance(value, str):
        if _is_identifier_key(key):
            return value
        return f"[{len(value)} chars]"

    if isinstance(value, (bytes, bytearray)):
        return f"[{len(value)} bytes]"

    if isinstance(value, Mapping):
        return f"[{len(value)} keys]"

    if isinstance(value, (list, tuple, set, frozenset)):
        return f"[{len(value)} items]"

    if value is None:
        return "null"

    return str(value)


def summarize_args(args: Mapping[str, Any] | None) -> str:
    """Return a redacted summary string for tool args."""
    if not args:
        return "-"

    parts = []
    for key, value in args.items():
        parts.append(f"{key}={_summarize_value(key, value)}")
    return ", ".join(parts)


@dataclass(slots=True)
class AuditEntry:
    """One redacted audit record."""

    timestamp: str
    tool_name: str
    duration_ms: int
    status: str
    error_code: str | None
    args_summary: str
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_audit_entry(
    *,
    tool_name: str,
    duration_ms: int,
    status: str,
    error_code: str | None = None,
    args: Mapping[str, Any] | None = None,
    error_message: str | None = None,
    timestamp: str | None = None,
) -> AuditEntry:
    """Create a sanitized ``AuditEntry`` from raw values."""
    clean_status = "error" if status == "error" else "ok"
    clean_error = (
        sanitize_error_message(error_message, max_chars=DEFAULT_MAX_ERROR_MESSAGE_CHARS)
        if error_message
        else None
    )
    return AuditEntry(
        timestamp=timestamp or _utcnow_iso(),
        tool_name=tool_name,
        duration_ms=max(0, int(duration_ms)),
        status=clean_status,
        error_code=error_code,
        args_summary=summarize_args(args),
        error_message=clean_error,
    )


class AuditLog:
    """Bounded in-memory audit ring buffer with optional JSONL file sink."""

    def __init__(self, max_entries: int = 200, file_path: str | None = None) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be > 0")
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._file_path = Path(file_path) if file_path else None
        self._lock = threading.Lock()

    def record(self, entry: AuditEntry) -> None:
        """Append a pre-built entry, enforcing sanitization and sink write."""
        sanitized_entry = make_audit_entry(
            tool_name=entry.tool_name,
            duration_ms=entry.duration_ms,
            status=entry.status,
            error_code=entry.error_code,
            args={"summary": entry.args_summary},
            error_message=entry.error_message,
            timestamp=entry.timestamp,
        )
        # Preserve direct summary text exactly; only keep message sanitization from helper.
        sanitized_entry.args_summary = entry.args_summary

        with self._lock:
            self._entries.append(sanitized_entry)
            if self._file_path is not None:
                self._append_jsonl(sanitized_entry)

    def record_call(
        self,
        *,
        tool_name: str,
        duration_ms: int,
        status: str,
        error_code: str | None = None,
        args: Mapping[str, Any] | None = None,
        error_message: str | None = None,
        timestamp: str | None = None,
    ) -> AuditEntry:
        """Build and append an audit entry from raw values."""
        entry = make_audit_entry(
            tool_name=tool_name,
            duration_ms=duration_ms,
            status=status,
            error_code=error_code,
            args=args,
            error_message=error_message,
            timestamp=timestamp,
        )
        self.record(entry)
        return entry

    def recent(self, limit: int = 50) -> list[AuditEntry]:
        """Return newest-first entries up to ``limit``."""
        if limit <= 0:
            return []
        with self._lock:
            selected = list(self._entries)[-limit:]
        selected.reverse()
        return selected

    def clear(self) -> None:
        """Clear in-memory audit entries."""
        with self._lock:
            self._entries.clear()

    def _append_jsonl(self, entry: AuditEntry) -> None:
        assert self._file_path is not None
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(entry.to_dict(), ensure_ascii=False)
        with self._file_path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")


__all__ = [
    "AuditEntry",
    "AuditLog",
    "make_audit_entry",
    "summarize_args",
]
