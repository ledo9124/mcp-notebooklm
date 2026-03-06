"""Prompt registration for notebooklm-mcp."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from notebooklm.exceptions import ValidationError


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value.strip()


async def notebook_summary(notebook_id: str) -> list[dict[str, str]]:
    """Prompt template for high-level notebook orientation."""
    clean_notebook_id = _require_text(notebook_id, field="notebook_id")
    return [
        {
            "role": "user",
            "content": (
                f"Summarize notebook {clean_notebook_id}. "
                "List all major sources, key themes, and open questions."
            ),
        }
    ]


async def source_analysis(notebook_id: str, source_id: str) -> list[dict[str, str]]:
    """Prompt template for detailed analysis of a single source."""
    clean_notebook_id = _require_text(notebook_id, field="notebook_id")
    clean_source_id = _require_text(source_id, field="source_id")
    return [
        {
            "role": "user",
            "content": (
                f"Analyze source {clean_source_id} in notebook {clean_notebook_id}. "
                "Identify arguments, evidence quality, assumptions, and conclusions."
            ),
        }
    ]


def _register_prompt(
    server: Any,
    *,
    name: str,
    description: str,
    handler: Callable[..., Any],
) -> None:
    prompt_factory = getattr(server, "prompt", None)
    if not callable(prompt_factory):
        return

    for kwargs in (
        {"name": name, "description": description},
        {"name": name},
        {},
    ):
        try:
            decorator = prompt_factory(**kwargs)
        except TypeError:
            continue

        if not callable(decorator):
            continue

        decorator(handler)
        return

    raise RuntimeError(f"Failed to register MCP prompt: {name}")


def register_prompts(server: Any) -> dict[str, Callable[..., Any]]:
    """Register MCP prompts with the server instance."""
    handlers: dict[str, Callable[..., Any]] = {
        "notebook_summary": notebook_summary,
        "source_analysis": source_analysis,
    }

    descriptions = {
        "notebook_summary": (
            "Summarize notebook contents, source coverage, and key themes."
        ),
        "source_analysis": (
            "Analyze one source with focus on arguments, evidence, and conclusions."
        ),
    }

    for name, handler in handlers.items():
        _register_prompt(
            server,
            name=name,
            description=descriptions[name],
            handler=handler,
        )

    return handlers


__all__ = ["notebook_summary", "register_prompts", "source_analysis"]
