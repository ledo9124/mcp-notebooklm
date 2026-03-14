"""Unit tests for the retained ask continuity CLI helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

class TestDetermineConversationId:
    """Tests for _determine_conversation_id CLI helper."""

    def test_explicit_conversation_id_used(self):
        from notebooklm.cli.chat import _determine_conversation_id

        result = _determine_conversation_id(
            explicit_conversation_id="conv_explicit",
            explicit_notebook_id=None,
            resolved_notebook_id="nb_123",
            json_output=True,
        )
        assert result == "conv_explicit"

    def test_different_notebook_starts_new(self):
        from notebooklm.cli.chat import _determine_conversation_id

        with patch("notebooklm.cli.chat.get_current_notebook", return_value="nb_old"):
            result = _determine_conversation_id(
                explicit_conversation_id=None,
                explicit_notebook_id="nb_new",
                resolved_notebook_id="nb_new",
                json_output=True,
            )
        assert result is None

    def test_same_notebook_continues_cached(self):
        from notebooklm.cli.chat import _determine_conversation_id

        with (
            patch("notebooklm.cli.chat.get_current_notebook", return_value="nb_123"),
            patch("notebooklm.cli.chat.get_current_conversation", return_value="conv_cached"),
        ):
            result = _determine_conversation_id(
                explicit_conversation_id=None,
                explicit_notebook_id="nb_123",
                resolved_notebook_id="nb_123",
                json_output=True,
            )
        assert result == "conv_cached"

    def test_no_explicit_notebook_uses_cached(self):
        from notebooklm.cli.chat import _determine_conversation_id

        with patch("notebooklm.cli.chat.get_current_conversation", return_value="conv_cached"):
            result = _determine_conversation_id(
                explicit_conversation_id=None,
                explicit_notebook_id=None,
                resolved_notebook_id="nb_123",
                json_output=True,
            )
        assert result == "conv_cached"


class TestGetLatestConversationFromServer:
    """Tests for _get_latest_conversation_from_server CLI helper."""

    @pytest.mark.asyncio
    async def test_returns_conversation_id(self):
        from notebooklm.cli.chat import _get_latest_conversation_from_server

        client = MagicMock()
        client.chat.get_conversation_id = AsyncMock(return_value="conv_from_server")

        result = await _get_latest_conversation_from_server(client, "nb_123", json_output=True)
        assert result == "conv_from_server"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_conversations(self):
        from notebooklm.cli.chat import _get_latest_conversation_from_server

        client = MagicMock()
        client.chat.get_conversation_id = AsyncMock(return_value=None)

        result = await _get_latest_conversation_from_server(client, "nb_123", json_output=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from notebooklm.cli.chat import _get_latest_conversation_from_server

        client = MagicMock()
        client.chat.get_conversation_id = AsyncMock(side_effect=RuntimeError("Network error"))

        result = await _get_latest_conversation_from_server(client, "nb_123", json_output=True)
        assert result is None
