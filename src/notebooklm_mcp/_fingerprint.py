"""Opaque fingerprint helpers for MCP state drift detection."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

DEFAULT_FINGERPRINT_LENGTH = 12


def fingerprint_settings(
    goal: Any,
    response_length: Any,
    custom_prompt: str | None,
    *,
    length: int = DEFAULT_FINGERPRINT_LENGTH,
) -> str:
    """Compute a stable fingerprint for chat settings.

    ``custom_prompt=None`` is distinct from ``custom_prompt=""``.
    """
    payload = {
        "goal": _normalize_value(goal),
        "response_length": _normalize_value(response_length),
        "custom_prompt": _normalize_prompt(custom_prompt),
    }
    return _fingerprint_payload(payload, length=length)


def _fingerprint_payload(payload: dict[str, Any], *, length: int) -> str:
    if length <= 0:
        raise ValueError("length must be > 0")

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:length]


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _normalize_prompt(custom_prompt: str | None) -> dict[str, Any]:
    if custom_prompt is None:
        return {"state": "null"}
    return {"state": "value", "value": custom_prompt}


__all__ = [
    "DEFAULT_FINGERPRINT_LENGTH",
    "fingerprint_settings",
]
