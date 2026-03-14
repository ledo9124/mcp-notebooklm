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

- Notebook bootstrap: auth/session setup, list/create, summary, and context selection
- Sources: URL, YouTube, file upload, pasted text, and readiness waiting
- Chat: ask with follow-up continuity and structured citations
- Research: web/drive research runs, poll/wait, import discovered sources
- Artifacts: audio generation plus report generation (`briefing-doc`, `study-guide`)

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
notebooklm ask "Give me a study plan" --json

# 4) Generate artifacts (`--wait` prints the ready URL)
notebooklm generate audio "Focus on key debates" --format deep-dive --wait
notebooklm generate report --format study-guide --wait
```

## Python Quickstart

```python
import asyncio
from notebooklm import NotebookLMClient


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

        # Generate a study guide and print the completed NotebookLM URL
        guide = await client.artifacts.generate_study_guide(nb.id)
        final = await client.artifacts.wait_for_completion(nb.id, guide.task_id)
        print(final.url)


asyncio.run(main())
```

## Useful CLI Commands

- `notebooklm --help`
- `notebooklm auth check --help`
- `notebooklm source --help`
- `notebooklm generate --help`
- `notebooklm research --help`
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
- [RPC Development](docs/rpc-development.md)
- [RPC Reference](docs/rpc-reference.md)
