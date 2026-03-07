"""Unit tests for e2e chat history helper retry/skip behavior."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from e2e import test_chat as e2e_test_chat

ChatHistoryE2EHelper = e2e_test_chat.TestChatHistoryE2E
ChatHistoryE2EHelper.__test__ = False


@pytest.mark.asyncio
async def test_get_existing_turns_or_skip_skips_when_no_conversation_id() -> None:
    helper = ChatHistoryE2EHelper()
    client = SimpleNamespace(
        chat=SimpleNamespace(
            get_conversation_id=AsyncMock(return_value=None),
            get_conversation_turns=AsyncMock(),
        )
    )

    with pytest.raises(pytest.skip.Exception, match="No conversation history available"):
        await helper._get_existing_turns_or_skip(client, "nb_readonly")

    client.chat.get_conversation_turns.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_existing_turns_or_skip_retries_until_readable_turns() -> None:
    helper = ChatHistoryE2EHelper()
    expected_turns = [
        [None, None, 1, "Question?"],
        [None, None, 2, None, [["Answer."]]],
    ]
    client = SimpleNamespace(
        chat=SimpleNamespace(
            get_conversation_id=AsyncMock(return_value="conv_001"),
            get_conversation_turns=AsyncMock(side_effect=[[], [[]], [expected_turns]]),
        )
    )

    with patch("e2e.test_chat.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        turns = await helper._get_existing_turns_or_skip(client, "nb_readonly")

    assert turns == expected_turns
    assert client.chat.get_conversation_turns.await_count == 3
    assert mock_sleep.await_count == 2


@pytest.mark.asyncio
async def test_get_existing_turns_or_skip_skips_after_empty_payload_retries() -> None:
    helper = ChatHistoryE2EHelper()
    client = SimpleNamespace(
        chat=SimpleNamespace(
            get_conversation_id=AsyncMock(return_value="conv_001"),
            get_conversation_turns=AsyncMock(side_effect=[[], [[]], [[]]]),
        )
    )

    with patch("e2e.test_chat.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        with pytest.raises(pytest.skip.Exception, match="returned no readable turns"):
            await helper._get_existing_turns_or_skip(client, "nb_readonly")

    assert client.chat.get_conversation_turns.await_count == 3
    assert mock_sleep.await_count == 2
