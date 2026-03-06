"""Unit tests for notebooklm_mcp._result."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from notebooklm_mcp._result import make_tool_result, to_json_compatible


class _Mode(Enum):
    DEFAULT = "default"


@dataclass
class _Payload:
    notebook_id: str
    source_count: int


def test_to_json_compatible_handles_core_types() -> None:
    payload = {
        "ts": datetime(2026, 3, 5, 12, 0, 1),
        "mode": _Mode.DEFAULT,
        "data": _Payload(notebook_id="nb-1", source_count=3),
        "path": Path("/tmp/test.txt"),
        "tags": {"b", "a"},
        "none": None,
    }

    converted = to_json_compatible(payload)

    assert converted["ts"] == "2026-03-05T12:00:01"
    assert converted["mode"] == "default"
    assert converted["data"] == {"notebook_id": "nb-1", "source_count": 3}
    assert converted["path"] == "/tmp/test.txt"
    assert converted["tags"] == ["a", "b"]
    assert converted["none"] is None


def test_make_tool_result_has_structured_and_text_fallback() -> None:
    result = make_tool_result({"ok": True, "value": 1})

    assert "structuredContent" in result
    assert "content" in result
    assert result["content"][0]["type"] == "text"
    assert isinstance(result["content"][0]["text"], str)

    parsed = json.loads(result["content"][0]["text"])
    assert parsed == result["structuredContent"]


def test_make_tool_result_handles_non_json_object_with_string_fallback() -> None:
    class CustomObject:
        def __str__(self) -> str:
            return "custom-object"

    result = make_tool_result({"obj": CustomObject()})
    parsed = json.loads(result["content"][0]["text"])
    assert parsed["obj"] == "custom-object"

