#!/usr/bin/env python3
"""OpenAI Agents SDK + notebooklm_mcp integration example.

Legacy/frozen note:
    This example is retained as historical reference while the mainline branch
    is focused on the CLI/SDK MVP and does not actively ship notebooklm_mcp.

This example demonstrates MCP interoperability with OpenAI Agents SDK by
connecting to notebooklm_mcp over stdio and running a basic workflow:
1. List notebooks
2. Create a notebook
3. Add a URL source
4. Ask a question

Prerequisites:
    pip install "notebooklm-py[mcp,browser]" "openai-agents"
    playwright install chromium
    notebooklm login
    export OPENAI_API_KEY="..."

Usage:
    python docs/examples/openai-agents-example.py
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from agents import Agent, Runner
from agents.mcp import MCPServerStdio
from agents.model_settings import ModelSettings


MCP_COMMAND = "python"
MCP_ARGS = ["-m", "notebooklm_mcp"]


def _workflow_prompt(*, title: str, url: str, question: str) -> str:
    return (
        "Use NotebookLM MCP tools and execute these steps in order:\n"
        "1) Call notebooklm_notebooks_list\n"
        f"2) Call notebooklm_notebooks_create with title={title!r}\n"
        f"3) Call notebooklm_sources_add_url with the new notebook_id and url={url!r}\n"
        f"4) Call notebooklm_chat_ask with that notebook_id and question={question!r}\n"
        "If any tool fails, stop and report the tool name plus a brief reason.\n"
        "Return compact JSON with keys: notebook_id, source_id, answer, notes."
    )


async def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for the OpenAI Agents SDK.")

    demo_title = f"MCP OpenAI Demo {datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    source_url = "https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)"
    question = "Summarize the architecture in 5 bullets."

    async with MCPServerStdio(
        name="NotebookLM MCP",
        params={"command": MCP_COMMAND, "args": MCP_ARGS},
        cache_tools_list=True,
        client_session_timeout_seconds=60,
    ) as mcp_server:
        agent = Agent(
            name="NotebookLM MCP Operator",
            instructions=(
                "You are a precise assistant. Prefer MCP tool calls over assumptions, "
                "and keep outputs concise and machine-readable when asked."
            ),
            model="gpt-4.1-mini",
            mcp_servers=[mcp_server],
            model_settings=ModelSettings(tool_choice="required"),
            mcp_config={"convert_schemas_to_strict": True},
        )

        try:
            result = await Runner.run(
                agent,
                _workflow_prompt(title=demo_title, url=source_url, question=question),
                max_turns=20,
            )
        except Exception as exc:  # pragma: no cover - example error path
            print("Workflow failed while executing MCP tool calls.")
            print(f"Error: {exc}")
            return

    print("Workflow completed.")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
