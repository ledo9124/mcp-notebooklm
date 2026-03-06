"""Unit tests for notebooklm_mcp._audit."""

from __future__ import annotations

import json

import pytest

from notebooklm.rpc.types import ChatGoal
from notebooklm_mcp._audit import AuditEntry, AuditLog, make_audit_entry, summarize_args


def test_summarize_args_redacts_sensitive_content_but_keeps_ids() -> None:
    summary = summarize_args(
        {
            "notebook_id": "nb-123",
            "question": "What is the secret?",
            "custom_prompt": "TOP SECRET PROMPT CONTENT",
            "source_content": "RAW SOURCE CONTENT",
            "source_ids": ["src-1", "src-2"],
            "goal": ChatGoal.CUSTOM,
        }
    )

    assert "nb-123" in summary
    assert "What is the secret?" not in summary
    assert "TOP SECRET PROMPT CONTENT" not in summary
    assert "RAW SOURCE CONTENT" not in summary
    assert "question=[19 chars]" in summary
    assert "custom_prompt=[25 chars]" in summary
    assert "source_ids=[2 items]" in summary
    assert "goal=custom" in summary


def test_summarize_args_redacts_cookies_and_custom_prompt_values() -> None:
    summary = summarize_args(
        {
            "notebook_id": "nb-123",
            "cookies": "abc123",
            "custom_prompt": "SECRET_PROMPT",
        }
    )

    assert "cookies=abc123" not in summary
    assert "SECRET_PROMPT" not in summary
    assert "cookies=[6 chars]" in summary
    assert "custom_prompt=[13 chars]" in summary


def test_make_audit_entry_sanitizes_error_message_and_normalizes_status() -> None:
    entry = make_audit_entry(
        tool_name="notebooklm_tools.ask",
        duration_ms=7,
        status="unexpected",
        args={"question": "hello"},
        error_message="Authorization=BearerX https://x/y?token=abc&foo=bar",
    )

    assert entry.status == "ok"
    assert entry.error_message is not None
    assert "BearerX" not in entry.error_message
    assert "abc" not in entry.error_message
    assert "foo=%5BREDACTED%5D" in entry.error_message


def test_audit_log_ring_buffer_bounded_and_recent_is_newest_first() -> None:
    audit = AuditLog(max_entries=3)

    for idx in range(1, 5):
        audit.record_call(
            tool_name=f"tool_{idx}",
            duration_ms=idx,
            status="ok",
            args={"notebook_id": f"nb-{idx}"},
            timestamp=f"2026-03-05T12:00:0{idx}Z",
        )

    recent = audit.recent(limit=10)
    assert len(recent) == 3
    assert [item.tool_name for item in recent] == ["tool_4", "tool_3", "tool_2"]


def test_recent_limit_and_clear() -> None:
    audit = AuditLog(max_entries=10)
    audit.record_call(tool_name="a", duration_ms=1, status="ok", args={})
    audit.record_call(tool_name="b", duration_ms=1, status="ok", args={})
    audit.record_call(tool_name="c", duration_ms=1, status="ok", args={})

    limited = audit.recent(limit=2)
    assert [entry.tool_name for entry in limited] == ["c", "b"]

    audit.clear()
    assert audit.recent() == []


def test_record_appends_jsonl_when_file_sink_configured(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    audit = AuditLog(max_entries=5, file_path=str(path))

    audit.record_call(
        tool_name="notebooklm_tools.remove_source",
        duration_ms=42,
        status="error",
        error_code="invalid_params",
        args={
            "notebook_id": "nb-9",
            "source_id": "src-5",
            "source_text": "secret source content",
        },
        error_message="token=abc123",
        timestamp="2026-03-05T12:30:00Z",
    )

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["tool_name"] == "notebooklm_tools.remove_source"
    assert payload["status"] == "error"
    assert payload["error_code"] == "invalid_params"
    assert payload["args_summary"].startswith("notebook_id=nb-9")
    assert "secret source content" not in payload["args_summary"]
    assert "abc123" not in (payload["error_message"] or "")


def test_record_accepts_prebuilt_entry() -> None:
    audit = AuditLog(max_entries=2)
    entry = AuditEntry(
        timestamp="2026-03-05T12:00:00Z",
        tool_name="tool_name",
        duration_ms=5,
        status="ok",
        error_code=None,
        args_summary="notebook_id=nb-1",
    )
    audit.record(entry)
    recent = audit.recent()
    assert len(recent) == 1
    assert recent[0].tool_name == "tool_name"
    assert recent[0].args_summary == "notebook_id=nb-1"


def test_invalid_max_entries_raises() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        AuditLog(max_entries=0)
