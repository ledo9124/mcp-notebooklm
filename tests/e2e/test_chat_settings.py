"""Optional E2E smoke test for chat settings lifecycle.

Run manually with:
    NOTEBOOKLM_E2E=1 pytest tests/e2e/test_chat_settings.py -m e2e
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from notebooklm import ChatGoal, ChatResponseLength, ChatSettings
from notebooklm.notebooklm_cli import cli

from .conftest import requires_auth

_RUN_CHAT_SETTINGS_SMOKE = os.environ.get("NOTEBOOKLM_E2E") == "1"


@pytest.mark.e2e
@requires_auth
@pytest.mark.skipif(
    not _RUN_CHAT_SETTINGS_SMOKE,
    reason="Set NOTEBOOKLM_E2E=1 to run chat settings lifecycle smoke test.",
)
class TestChatSettingsLifecycleE2E:
    """E2E smoke lifecycle: set -> get -> patch -> reset -> CLI show."""

    @pytest.mark.asyncio
    async def test_chat_settings_lifecycle_smoke(self, client, temp_notebook, auth_tokens):
        notebook_id = temp_notebook.id
        custom_prompt = "Teach with concise bullets and one concrete example."

        await client.chat.set_settings(
            notebook_id,
            ChatSettings(
                goal=ChatGoal.CUSTOM,
                response_length=ChatResponseLength.DEFAULT,
                custom_prompt=custom_prompt,
                source="default",
            ),
        )

        current = await client.chat.get_settings(notebook_id, strict=True)
        assert current.goal == ChatGoal.CUSTOM
        assert current.response_length == ChatResponseLength.DEFAULT
        assert current.custom_prompt == custom_prompt

        patched = await client.chat.update_settings(
            notebook_id,
            response_length=ChatResponseLength.SHORTER,
        )
        assert patched.goal == ChatGoal.CUSTOM
        assert patched.response_length == ChatResponseLength.SHORTER
        assert patched.custom_prompt == custom_prompt

        await client.chat.reset_settings(notebook_id)
        reset = await client.chat.get_settings(notebook_id, strict=True)
        assert reset.goal == ChatGoal.DEFAULT
        assert reset.response_length == ChatResponseLength.DEFAULT
        assert reset.custom_prompt is None

        runner = CliRunner()
        with (
            patch("notebooklm.cli.helpers.load_auth_from_storage") as mock_auth,
            patch("notebooklm.cli.helpers.fetch_tokens", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_auth.return_value = auth_tokens.cookies
            mock_fetch.return_value = (auth_tokens.csrf_token, auth_tokens.session_id)
            result = runner.invoke(cli, ["configure", "-n", notebook_id, "--show", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["notebook_id"] == notebook_id
        assert payload["goal"] == "default"
        assert payload["response_length"] == "default"
        assert payload["custom_prompt"] is None
        assert payload["custom_prompt_len"] == 0
        assert payload["source"] in {"server", "default", "unknown"}

