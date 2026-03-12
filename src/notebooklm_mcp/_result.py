"""Shared MCP tool result formatting helpers."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def make_tool_result(data: Any, *, indent: int = 2) -> dict[str, Any]:
    """Return MCP-style dual output with structured JSON and text fallback."""
    structured = to_json_compatible(data)
    return {
        "structuredContent": structured,
        "content": [
            {
                "type": "text",
                "text": json.dumps(structured, indent=indent, sort_keys=True, ensure_ascii=False),
            }
        ],
    }


def to_json_compatible(value: Any) -> Any:
    """Normalize Python values into JSON-serializable data recursively."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Enum):
        return to_json_compatible(value.value)

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, BaseModel):
        return to_json_compatible(value.model_dump(mode="json"))

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_json_compatible(dataclasses.asdict(value))

    if isinstance(value, Mapping):
        return {str(k): to_json_compatible(v) for k, v in value.items()}

    if isinstance(value, set):
        return [to_json_compatible(item) for item in sorted(value, key=repr)]

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_json_compatible(item) for item in value]

    return str(value)


__all__ = [
    "make_tool_result",
    "to_json_compatible",
]
