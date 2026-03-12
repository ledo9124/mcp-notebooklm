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

Python requirement: **3.10+**.

### Linux / macOS

```bash
# Runtime
pip install notebooklm-py

# Includes browser login dependency
pip install "notebooklm-py[browser]"
playwright install chromium
```

### Windows (PowerShell)

```powershell
# Runtime
pip install notebooklm-py

# Includes browser login dependency
pip install "notebooklm-py[browser]"
playwright install chromium
```

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
- Two-tier surface: generic NotebookLM parity tools plus workflow-native `ba.*` tools for deterministic BA implementation-pack runs
- Built-in resources and prompt templates for common NotebookLM workflows
- Structured output (`structuredContent`) with text JSON fallback for compatibility
- Optional destructive-tool safety gate (`NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1` + `confirm=true`)

### Quick start (Linux / macOS)

```bash
# Install MCP runtime support
pip install "notebooklm-py[mcp,browser]"
playwright install chromium

# Authenticate NotebookLM
notebooklm login

# Run MCP server (stdio transport — default)
notebooklm-mcp serve

# Run with HTTP transport (recommended for remote/agent use)
notebooklm-mcp serve --http
```

### Quick start (Windows PowerShell)

```powershell
# Install MCP runtime support
pip install "notebooklm-py[mcp,browser]"
playwright install chromium

# Authenticate NotebookLM
notebooklm login

# Run MCP server (stdio transport — default)
notebooklm-mcp serve

# Run with HTTP transport
notebooklm-mcp serve --http
```

### Transport modes

| Transport | Start command | Agent connection |
| --- | --- | --- |
| `stdio` (default) | `notebooklm-mcp serve` | Local subprocess (no URL) |
| `streamable-http` (recommended HTTP) | `notebooklm-mcp serve --http` | `http://127.0.0.1:8764/mcp` |
| `sse` (legacy HTTP) | `notebooklm-mcp serve --sse` | `http://127.0.0.1:8765/sse` |

> **Backward compatibility:** `python -m notebooklm_mcp` and the legacy `--transport` flag still work.

### HTTP configuration

- Defaults: `NOTEBOOKLM_MCP_HOST=127.0.0.1`, `NOTEBOOKLM_MCP_PORT=8764`
- Environment variables: `NOTEBOOKLM_MCP_HOST`, `NOTEBOOKLM_MCP_PORT`
- CLI overrides: `--host`, `--port` (higher precedence than env vars)
- Effective precedence: CLI flags > env vars > built-in defaults

### Examples

```bash
# Start HTTP on custom port
notebooklm-mcp serve --http --port 9000

# Start on all interfaces (explicit risk acceptance)
notebooklm-mcp serve --http --host 0.0.0.0

# Enable verbose debug logging
notebooklm-mcp serve --http -v
```

### BA Runner Quickstart

The MCP surface now exposes two layers:

- Generic parity tools under `notebooklm_*` for notebooks, sources, notes, chat, settings, artifacts, and research.
- Workflow-native BA tools under `ba.*` for evidence-first implementation-pack generation.

Current public BA tools:

- `ba.start_run`
- `ba.register_sources`
- `ba.status`
- `ba.validate_bundle`
- `ba.run_pipeline`
- `ba.rerun_impacted`

Most automation should start with `ba.run_pipeline`; the other `ba.*` tools exist for stepwise control, inspection, standalone validation reruns, and targeted incremental reruns after source changes.

Minimal `ba.run_pipeline` example:

```json
{
  "name": "ba.run_pipeline",
  "arguments": {
    "notebook_id": "nb-123",
    "feature_key": "customer-onboarding",
    "mode": "balanced",
    "output_dir": "/absolute/path/to/workspace",
    "sources": [
      {
        "source_key": "requirements",
        "title": "Customer onboarding requirements",
        "path_or_url_or_text": "# Customer onboarding\nUsers can create an account with email, full name, and plan selection.",
        "source_type": "PRIMARY_REQUIREMENT",
        "priority": "REQUIRED",
        "content_kind": "INLINE_TEXT"
      },
      {
        "source_key": "contract",
        "title": "Customer onboarding contract",
        "path_or_url_or_text": "POST /api/customers creates an account and returns customerId plus status.",
        "source_type": "PRIMARY_CONTRACT",
        "priority": "HIGH",
        "content_kind": "INLINE_TEXT"
      }
    ]
  }
}
```

Notes:

- `ba.run_pipeline` persists the bundle under `<output_dir>/docs/features/<feature_key>/`.
- `ba.status` exposes the persisted run state, next step, and resumability hints.
- `ba.validate_bundle` reruns deterministic QA checks after manual edits or external mutations.
- `ba.rerun_impacted` reuses the stored baseline to update only impacted screens when source changes stay narrow enough.
- For a runnable stdio MCP example, see [BA Runner MCP Flow](docs/examples/ba-runner-mcp-flow.py).
- For request/response details on every BA tool, see [MCP Tool Reference](docs/mcp-tools.md#ba-runner).

### Logging

- **Default:** clean, minimal output — only startup banner and errors
- **Verbose (`-v`):** DEBUG level with timestamps and logger names
- `NOTEBOOKLM_MCP_LOG_LEVEL` environment variable is also supported
- All logs go to **stderr** (safe for stdio transport)

Security note:

- The default bind is loopback (`127.0.0.1`) to keep the MCP endpoint local-only.
- Binding to `0.0.0.0` exposes NotebookLM operations to your network. Do this only when intentionally deploying behind trusted network controls.

Claude Desktop HTTP config example (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "notebooklm-http": {
      "url": "http://127.0.0.1:8764/mcp"
    }
  }
}
```

For Claude Desktop setup and troubleshooting, see:
- [Claude Desktop MCP Setup](docs/mcp-claude-desktop.md)
- [MCP Tool Reference](docs/mcp-tools.md)
- [BA Runner MCP Flow](docs/examples/ba-runner-mcp-flow.py)
- [OpenAI Agents SDK MCP Example](docs/examples/openai-agents-example.py)

For multi-agent contributor coordination in this repo (session sync, inbox checks, progress updates, and file reservations), see [AGENTS.md](AGENTS.md).

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
- [BA Runner MCP Flow](docs/examples/ba-runner-mcp-flow.py)
- [OpenAI Agents SDK MCP Example](docs/examples/openai-agents-example.py)
- [RPC Development](docs/rpc-development.md)
- [RPC Reference](docs/rpc-reference.md)
