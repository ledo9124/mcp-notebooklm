# notebooklm-py

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

## Supported Surface Today

- Install package: `notebooklm-py`
- Python import package: `notebooklm`
- Console command: `notebooklm`
- Supported public workflows on this branch: auth/session, notebook bootstrap, source ingestion, research, chat, and the retained `generate` flows
- Deferred compatibility modules may still exist in-tree, but removed standalone CLI groups are not part of the active product promise
- Near-term roadmap: freeze this CLI/SDK contract first, then layer agent-first contract work above it instead of reviving removed legacy runtimes

## Installation

Python requirement: **3.10+**.

After installation, run the CLI as `notebooklm`. The Python examples in this repo import from `notebooklm`.

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

- [Project Overview](docs/project-overview.md)
- [CLI Reference](docs/cli-reference.md)
- [Python API Reference](docs/python-api.md)
- [Configuration](docs/configuration.md)
- [Troubleshooting](docs/troubleshooting.md)
- [API Stability](docs/stability.md)
- [Development Guide](docs/development.md)
- [RPC Development](docs/rpc-development.md)
- [RPC Reference](docs/rpc-reference.md)
