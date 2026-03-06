# notebooklm-py
<p align="left">
  <img src="https://raw.githubusercontent.com/teng-lin/notebooklm-py/main/notebooklm-py.png" alt="notebooklm-py logo" width="128">
</p>

Unofficial async Python API + CLI for Google NotebookLM.

[![PyPI version](https://img.shields.io/pypi/v/notebooklm-py.svg)](https://pypi.org/project/notebooklm-py/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](https://pypi.org/project/notebooklm-py/)
[![Tests](https://github.com/teng-lin/notebooklm-py/actions/workflows/test.yml/badge.svg)](https://github.com/teng-lin/notebooklm-py/actions/workflows/test.yml)

**Repository:** <https://github.com/teng-lin/notebooklm-py>

> **Warning: Unofficial API**
>
> This library uses undocumented Google NotebookLM APIs and may break when Google changes internal endpoints.
>
> - Not affiliated with Google
> - Subject to rate limits and auth/session expiration
> - Best for automation, prototyping, and internal workflows

## What It Covers

- Notebook lifecycle: create, list, rename, delete, summary
- Sources: URL, YouTube, file upload, pasted text, Google Drive, source fulltext/guide/freshness
- Chat: ask, settings parity (style + response length), history, save to notes
- Research: web/drive research runs, poll/wait, import discovered sources
- Artifacts: audio, video, slide deck, infographic, report, quiz, flashcards, data table, mind map
- Sharing: public access, view level, and per-user permissions
- CLI skill integration: `notebooklm skill install` for Claude Code workflows

## Installation

```bash
# Runtime
pip install notebooklm-py

# Includes browser login dependency
pip install "notebooklm-py[browser]"
playwright install chromium
```

Python requirement: **3.10+**.

## Authenticate

```bash
# Browser login (first run)
notebooklm login

# Optional diagnostics
notebooklm auth check --test

# Verify access
notebooklm list
```

## CLI Quickstart

```bash
# 1) Create notebook and set context
notebooklm create "AI Research"
notebooklm use <notebook_id>

# 2) Add sources
notebooklm source add "https://en.wikipedia.org/wiki/Artificial_intelligence"
notebooklm source add "./paper.pdf"
notebooklm source add-research "AI safety timeline" --mode deep --no-wait
notebooklm research wait --import-all

# 3) Ask questions
notebooklm ask "What are the main themes?"
notebooklm ask "Give me a study plan" --save-as-note --note-title "Study plan"

# 4) Generate artifacts (wait for completion before downloading)
notebooklm generate audio "Focus on key debates" --format deep-dive --wait
notebooklm generate quiz --difficulty hard --wait
notebooklm generate slide-deck --wait

# 5) Download artifacts
notebooklm download audio ./podcast.mp3
notebooklm download quiz --format markdown ./quiz.md
notebooklm download slide-deck --format pptx ./slides.pptx
```

## Python Quickstart

```python
import asyncio
from notebooklm import NotebookLMClient, QuizDifficulty


async def main():
    async with await NotebookLMClient.from_storage() as client:
        # Create notebook and add source
        nb = await client.notebooks.create("Research Demo")
        await client.sources.add_url(
            nb.id,
            "https://en.wikipedia.org/wiki/Artificial_intelligence",
            wait=True,
        )

        # Ask a question
        answer = await client.chat.ask(nb.id, "Summarize the core argument")
        print(answer.answer)

        # Generate + download quiz
        quiz = await client.artifacts.generate_quiz(nb.id, difficulty=QuizDifficulty.HARD)
        await client.artifacts.wait_for_completion(nb.id, quiz.task_id)
        await client.artifacts.download_quiz(
            nb.id,
            "quiz.md",
            artifact_id=quiz.task_id,
            output_format="markdown",
        )


asyncio.run(main())
```

## MCP Server

`notebooklm-py` also ships an MCP server (`notebooklm_mcp`) so agent hosts can call NotebookLM via standardized tools/resources.

Why use MCP here:
- Agent-native tool calling for notebooks, sources, chat, settings, and workflow macros
- Built-in resources and prompt templates for common NotebookLM workflows
- Structured output (`structuredContent`) with text JSON fallback for compatibility
- Optional destructive-tool safety gate (`NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1` + `confirm=true`)

Quick start:

```bash
# Install MCP runtime support
pip install "notebooklm-py[mcp,browser]"
playwright install chromium

# Authenticate NotebookLM
notebooklm login

# Run MCP server (stdio transport)
python -m notebooklm_mcp
```

For Claude Desktop setup and troubleshooting, see:
- [Claude Desktop MCP Setup](docs/mcp-claude-desktop.md)
- [MCP Tool Reference](docs/mcp-tools.md)
- [OpenAI Agents SDK MCP Example](docs/examples/openai-agents-example.py)

For multi-agent contributor coordination in this repo (session sync, inbox checks, progress updates, and file reservations), see [AGENT.md](AGENT.md).

## Useful CLI Commands

- `notebooklm --help`
- `notebooklm source --help`
- `notebooklm generate --help`
- `notebooklm download --help`
- `notebooklm language list`
- `notebooklm language set <code>`
- `notebooklm status --paths`

## Configuration

Key environment variables:

- `NOTEBOOKLM_HOME`: move all local state (auth, context, browser profile)
- `NOTEBOOKLM_AUTH_JSON`: provide auth inline for CI/CD (no auth file write)

See [Configuration](docs/configuration.md) for details and precedence rules.

## Documentation

- [CLI Reference](docs/cli-reference.md)
- [Python API Reference](docs/python-api.md)
- [Configuration](docs/configuration.md)
- [Troubleshooting](docs/troubleshooting.md)
- [API Stability](docs/stability.md)
- [Development Guide](docs/development.md)
- [MCP Tool Reference](docs/mcp-tools.md)
- [Claude Desktop MCP Setup](docs/mcp-claude-desktop.md)
- [OpenAI Agents SDK MCP Example](docs/examples/openai-agents-example.py)
- [RPC Development](docs/rpc-development.md)
- [RPC Reference](docs/rpc-reference.md)
