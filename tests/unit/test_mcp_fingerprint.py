"""Unit tests for notebooklm_mcp._fingerprint."""

from __future__ import annotations

import re

import pytest

from notebooklm.types import ChatGoal, ChatResponseLength
from notebooklm_mcp._fingerprint import (
    DEFAULT_FINGERPRINT_LENGTH,
    fingerprint_settings,
)


def test_fingerprint_is_deterministic() -> None:
    first = fingerprint_settings("default", "shorter", "custom prompt")
    second = fingerprint_settings("default", "shorter", "custom prompt")
    assert first == second


def test_fingerprint_changes_when_settings_change() -> None:
    baseline = fingerprint_settings("default", "shorter", "prompt")
    changed_goal = fingerprint_settings("custom", "shorter", "prompt")
    changed_length = fingerprint_settings("default", "longer", "prompt")
    changed_prompt = fingerprint_settings("default", "shorter", "different")

    assert baseline != changed_goal
    assert baseline != changed_length
    assert baseline != changed_prompt


def test_none_prompt_and_empty_prompt_have_distinct_fingerprints() -> None:
    none_prompt = fingerprint_settings("default", "default", None)
    empty_prompt = fingerprint_settings("default", "default", "")
    assert none_prompt != empty_prompt


def test_fingerprint_supports_enum_inputs() -> None:
    enum_value = fingerprint_settings(ChatGoal.DEFAULT, ChatResponseLength.DEFAULT, None)
    raw_value = fingerprint_settings(ChatGoal.DEFAULT.value, ChatResponseLength.DEFAULT.value, None)
    assert enum_value == raw_value


def test_fingerprint_is_hex_and_expected_length() -> None:
    fingerprint = fingerprint_settings("default", "default", None)
    assert len(fingerprint) == DEFAULT_FINGERPRINT_LENGTH
    assert re.fullmatch(r"[0-9a-f]+", fingerprint)


def test_fingerprint_handles_unicode() -> None:
    fingerprint = fingerprint_settings("learning_guide", "longer", "ทดสอบ ✅")
    assert len(fingerprint) == DEFAULT_FINGERPRINT_LENGTH


def test_custom_length() -> None:
    fingerprint = fingerprint_settings("default", "default", None, length=16)
    assert len(fingerprint) == 16


def test_invalid_length_raises() -> None:
    with pytest.raises(ValueError, match="length"):
        fingerprint_settings("default", "default", None, length=0)

