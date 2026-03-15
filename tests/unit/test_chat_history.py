"""Unit tests for the retained ask continuity CLI helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from notebooklm.workflows.ask import determine_conversation_id, get_latest_conversation_from_server

class TestDetermineConversationId:
    """Tests for determine_conversation_id workflow helper."""

    def test_explicit_conversation_id_used(self):
        result = determine_conversation_id(
            explicit_conversation_id="conv_explicit",
            explicit_notebook_id=None,
            resolved_notebook_id="nb_123",
            json_output=True,
            get_current_notebook=lambda: None,
            get_current_conversation=lambda: None,
        )
        assert result == "conv_explicit"

    def test_different_notebook_starts_new(self):
        result = determine_conversation_id(
            explicit_conversation_id=None,
            explicit_notebook_id="nb_new",
            resolved_notebook_id="nb_new",
            json_output=True,
            get_current_notebook=lambda: "nb_old",
            get_current_conversation=lambda: "conv_cached",
        )
        assert result is None

    def test_same_notebook_continues_cached(self):
        result = determine_conversation_id(
            explicit_conversation_id=None,
            explicit_notebook_id="nb_123",
            resolved_notebook_id="nb_123",
            json_output=True,
            get_current_notebook=lambda: "nb_123",
            get_current_conversation=lambda: "conv_cached",
        )
        assert result == "conv_cached"

    def test_no_explicit_notebook_uses_cached(self):
        result = determine_conversation_id(
            explicit_conversation_id=None,
            explicit_notebook_id=None,
            resolved_notebook_id="nb_123",
            json_output=True,
            get_current_notebook=lambda: None,
            get_current_conversation=lambda: "conv_cached",
        )
        assert result == "conv_cached"


class TestGetLatestConversationFromServer:
    """Tests for get_latest_conversation_from_server workflow helper."""

    @pytest.mark.asyncio
    async def test_returns_conversation_id(self):
        client = MagicMock()
        client.chat.get_conversation_id = AsyncMock(return_value="conv_from_server")

        result = await get_latest_conversation_from_server(client, "nb_123", json_output=True)
        assert result == "conv_from_server"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_conversations(self):
        client = MagicMock()
        client.chat.get_conversation_id = AsyncMock(return_value=None)

        result = await get_latest_conversation_from_server(client, "nb_123", json_output=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        client = MagicMock()
        client.chat.get_conversation_id = AsyncMock(side_effect=RuntimeError("Network error"))

        result = await get_latest_conversation_from_server(client, "nb_123", json_output=True)
        assert result is None
