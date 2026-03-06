"""Unit tests for notebooklm_mcp.prompts."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from notebooklm.exceptions import ValidationError
from notebooklm_mcp import prompts as prompt_module


class _FakeServer:
    def __init__(self) -> None:
        self.registered: dict[str, dict[str, object]] = {}

    def prompt(
        self, *, name: str | None = None, description: str | None = None
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def _decorator(func: Callable[..., object]) -> Callable[..., object]:
            self.registered[name or func.__name__] = {
                "handler": func,
                "description": description,
            }
            return func

        return _decorator


def test_register_prompts_registers_expected_prompt_names() -> None:
    server = _FakeServer()
    handlers = prompt_module.register_prompts(server)

    expected = {"notebook_summary", "source_analysis"}
    assert set(handlers) == expected
    assert set(server.registered) == expected


@pytest.mark.asyncio
async def test_notebook_summary_template_includes_notebook_id() -> None:
    messages = await prompt_module.notebook_summary("nb-1")

    assert messages == [
        {
            "role": "user",
            "content": (
                "Summarize notebook nb-1. "
                "List all major sources, key themes, and open questions."
            ),
        }
    ]


@pytest.mark.asyncio
async def test_source_analysis_template_includes_notebook_and_source_id() -> None:
    messages = await prompt_module.source_analysis("nb-2", "src-9")

    assert messages == [
        {
            "role": "user",
            "content": (
                "Analyze source src-9 in notebook nb-2. "
                "Identify arguments, evidence quality, assumptions, and conclusions."
            ),
        }
    ]


@pytest.mark.asyncio
async def test_prompt_templates_validate_non_empty_ids() -> None:
    with pytest.raises(ValidationError, match="notebook_id must be a non-empty string"):
        await prompt_module.notebook_summary(" ")

    with pytest.raises(ValidationError, match="source_id must be a non-empty string"):
        await prompt_module.source_analysis("nb-1", "")

