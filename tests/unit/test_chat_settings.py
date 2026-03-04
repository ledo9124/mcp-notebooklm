"""Unit tests for chat settings types and parser utilities."""

import pytest

from notebooklm._chat_settings import parse_chat_settings
from notebooklm.exceptions import ChatSettingsParseError, ChatSettingsValidationError
from notebooklm.rpc import ChatGoal, ChatResponseLength
from notebooklm.types import UNSET, ChatSettings


class TestChatSettingsValidation:
    """Validation tests for the ChatSettings dataclass."""

    def test_custom_goal_requires_prompt(self):
        """CUSTOM goal requires a non-empty prompt."""
        with pytest.raises(ChatSettingsValidationError):
            ChatSettings(
                goal=ChatGoal.CUSTOM,
                response_length=ChatResponseLength.DEFAULT,
                custom_prompt=None,
            )

    def test_custom_goal_rejects_blank_prompt(self):
        """Blank custom prompts are rejected."""
        with pytest.raises(ChatSettingsValidationError):
            ChatSettings(
                goal=ChatGoal.CUSTOM,
                response_length=ChatResponseLength.DEFAULT,
                custom_prompt="   ",
            )

    def test_custom_goal_prompt_length_cap(self):
        """Custom prompt must be <= 10,000 chars."""
        with pytest.raises(ChatSettingsValidationError):
            ChatSettings(
                goal=ChatGoal.CUSTOM,
                response_length=ChatResponseLength.DEFAULT,
                custom_prompt="x" * 10_001,
            )

    def test_non_custom_goal_requires_none_prompt(self):
        """Non-custom goals must not carry custom_prompt."""
        with pytest.raises(ChatSettingsValidationError):
            ChatSettings(
                goal=ChatGoal.DEFAULT,
                response_length=ChatResponseLength.DEFAULT,
                custom_prompt="should fail",
            )

    def test_source_value_must_be_valid(self):
        """Unknown source labels are rejected."""
        with pytest.raises(ChatSettingsValidationError):
            ChatSettings(
                goal=ChatGoal.DEFAULT,
                response_length=ChatResponseLength.DEFAULT,
                custom_prompt=None,
                source="invalid",  # type: ignore[arg-type]
            )

    def test_valid_custom_settings(self):
        """Valid custom settings are accepted."""
        settings = ChatSettings(
            goal=ChatGoal.CUSTOM,
            response_length=ChatResponseLength.SHORTER,
            custom_prompt="Be concise and educational.",
            source="server",
        )

        assert settings.goal == ChatGoal.CUSTOM
        assert settings.response_length == ChatResponseLength.SHORTER
        assert settings.custom_prompt == "Be concise and educational."
        assert settings.source == "server"

    def test_unset_sentinel_repr(self):
        """UNSET sentinel has stable repr for debugging."""
        assert repr(UNSET) == "UNSET"


class TestParseChatSettings:
    """Parser tests for signature-based settings discovery."""

    def test_parse_happy_path_default_mode(self):
        """Parser finds default style + longer response length."""
        raw = {"payload": [None, [[[1], [4]]], "noise"]}

        parsed = parse_chat_settings(raw)

        assert parsed == ChatSettings(
            goal=ChatGoal.DEFAULT,
            response_length=ChatResponseLength.LONGER,
            custom_prompt=None,
            source="server",
        )

    def test_parse_custom_mode(self):
        """Parser returns CUSTOM mode with preserved prompt."""
        raw = [0, [1, [[2, "Act as a calculus tutor"], [5]]]]

        parsed = parse_chat_settings(raw)

        assert parsed.goal == ChatGoal.CUSTOM
        assert parsed.response_length == ChatResponseLength.SHORTER
        assert parsed.custom_prompt == "Act as a calculus tutor"
        assert parsed.source == "server"

    def test_parse_multiple_candidates_picks_highest_score(self):
        """Known-code candidate should beat unknown-code candidate."""
        raw = [
            [[99], [42]],  # shape matches but unknown codes
            {"deep": [0, 1, [[1], [1]]]},  # valid known candidate
        ]

        parsed = parse_chat_settings(raw)

        assert parsed.goal == ChatGoal.DEFAULT
        assert parsed.response_length == ChatResponseLength.DEFAULT
        assert parsed.source == "server"

    def test_parse_strict_unknown_codes_raises(self):
        """Strict parsing rejects unknown goal/length codes."""
        raw = {"data": [[[99], [42]]]}

        with pytest.raises(ChatSettingsParseError):
            parse_chat_settings(raw, strict=True)

    def test_parse_non_strict_unknown_codes_warns_and_fallbacks(self):
        """Non-strict parsing warns and falls back to DEFAULT/DEFAULT."""
        raw = {"data": [[[99], [42]]]}

        with pytest.warns(RuntimeWarning, match="Unknown chat settings codes"):
            parsed = parse_chat_settings(raw, strict=False)

        assert parsed == ChatSettings(
            goal=ChatGoal.DEFAULT,
            response_length=ChatResponseLength.DEFAULT,
            custom_prompt=None,
            source="unknown",
        )

    def test_parse_custom_without_prompt_raises(self):
        """CUSTOM goal without prompt is invalid."""
        raw = {"data": [[[2], [1]]]}

        with pytest.raises(ChatSettingsParseError, match="CUSTOM goal"):
            parse_chat_settings(raw)

    def test_parse_enforces_max_nodes_cap(self):
        """Traversal aborts when node cap is exceeded."""
        raw = [[[[[[[[[[[[[]]]]]]]]]]]]]

        with pytest.raises(ChatSettingsParseError, match="node cap"):
            parse_chat_settings(raw, max_nodes=5)

    def test_parse_enforces_max_depth_cap(self):
        """Candidate deeper than max_depth should not be considered."""
        raw = [[[[[[[1], [1]]]]]]]

        with pytest.raises(ChatSettingsParseError, match="No chat settings signature"):
            parse_chat_settings(raw, max_depth=2)

