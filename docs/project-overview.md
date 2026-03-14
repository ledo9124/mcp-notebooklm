# Project Overview

**Status:** Active  
**Last Updated:** 2026-03-14

This document summarizes what the project does today and the main technologies used to implement it.

## Purpose

`notebooklm-py` is an unofficial automation toolkit for Google NotebookLM with:

- Async Python SDK
- Focused CLI for the retained MVP workflow
- Legacy/frozen MCP and BA reference code still kept in-tree

## Core Technology Stack

### Runtime and Packaging

- Python `>=3.10`
- Packaging/build: `setuptools`, `wheel`, `pyproject.toml`
- Distribution target: PyPI package `notebooklm-py`

### Main Runtime Dependencies

- `httpx`: async HTTP/RPC transport layer
- `click`: CLI command system
- `rich`: terminal UX and formatted output

### Optional Features

- `playwright`: browser-based login/session capture
- `mcp` + `pydantic`: legacy/frozen MCP server and typed tool schemas retained in-tree

### Development and Quality Tooling

- `pytest`, `pytest-asyncio`, `pytest-httpx`, `vcrpy`
- `ruff`, `mypy`, `pre-commit`

## High-Level Architecture

- `src/notebooklm/`: mainline Python SDK + CLI
  - `client.py`: `NotebookLMClient` entry point
  - `_core.py`: shared HTTP/RPC core, retry/auth refresh behavior
  - `_notebooks.py`, `_sources.py`, `_artifacts.py`, `_chat.py`, `_research.py`: active MVP domain APIs
  - `_notes.py`, `_settings.py`, `_sharing.py`: deferred compatibility APIs kept behind a reduced client facade
  - `rpc/`: RPC types, encoding, decoding
  - `cli/`: command groups for `auth/session`, `notebook`, `source`, `research`, `chat ask`, and reduced `generate`
- `src/notebooklm_mcp/`: legacy/frozen MCP server and BA runner reference code
  - tools/resources/prompts retained for archival and future re-entry work
  - excluded from the packaged mainline product surface on this branch

## Active Pruning Workstream

The repository is currently defining a smaller MVP boundary for the mainline CLI/SDK surface.

- [PRUNING_PLAN.md](../PRUNING_PLAN.md) is the file-by-file keep/delete/defer map.
- [MVP Pruning Contract](mvp-pruning-contract.md) records the retained user journeys, coupling constraints, removal order, and validation gates for that work.
- [MVP Pruning Verification](mvp-pruning-verification.md) records the latest prune-focused quality-gate results and residual risks.
- This overview tracks the actively supported mainline surface as pruning lands; some deferred SDK compatibility helpers may still exist in-tree without being part of the current CLI promise.

## Current Functional Coverage

### 1) Authentication and Session

- Browser login flow (`notebooklm login`)
- Storage-state based auth loading
- `NOTEBOOKLM_AUTH_JSON` support for CI/CD
- Context tracking for active notebook/conversation
- Automatic token refresh on auth failures

### 2) Notebook Management

- List and create notebooks
- Notebook summary/description retrieval
- Local notebook context management via `use`, `status`, and `clear`

### 3) Source Management

- Add sources from URL, YouTube, local files, and pasted text
- List sources and wait for source processing/readiness
- Start research-assisted source acquisition from web or Drive via `source add-research`
- Import discovered research sources through the retained research monitor flow

Direct Google Drive ingest plus the broader source metadata/intelligence shell (`get`, `rename`, `delete`, `refresh`, `fulltext`, `guide`, `stale`) are no longer part of the active mainline CLI contract on this branch.
- Wait for source processing/readiness

### 4) Chat and Conversation

- Ask questions with optional source filtering
- Continue existing conversations via local/server conversation continuity
- Citation/reference extraction in structured output

### 5) Deferred Chat Settings Internals

- Chat settings parity is no longer part of the active mainline CLI contract.
- Remaining compatibility helpers are deferred cleanup work rather than supported MVP behavior.

### 6) Research Workflows

- Start fast/deep research (web or drive)
- Poll/wait research status
- Import discovered research sources

### 7) Artifact Generation

- Generate: audio plus report modes (`briefing-doc`, `study-guide`)
- `generate ... --wait` returns the completed artifact URL directly
- Artifact delete/rename helpers remain available in the SDK

### 8) Artifact Retrieval and Polling

- Poll/wait helpers remain the canonical retrieval path for the active branch
- Historical download/export helpers now act as compatibility stubs and are not part of the active MVP promise

### 9) Deferred Notes, Settings, and Sharing Internals

- `NotebookLMClient` now constructs only the retained MVP subclients eagerly.
- `notes`, `settings`, and `sharing` remain lazily available for deferred compatibility paths.
- The standalone `notebooklm note ...`, `notebooklm share ...`, and `notebooklm language ...` CLI surfaces are no longer part of the active mainline MVP promise.

### 10) Local Generation Language Helpers

- The retained generate commands still use the local language helper/config path.
- The standalone root `language` command group is removed from the active CLI shell.

### 11) Legacy/Frozen MCP and BA Surface

- MCP tools/resources/prompts and BA runner code remain in-tree as reference material
- Those surfaces are not part of the packaged mainline product contract for this branch
- Boundary status and re-entry criteria are tracked in [MCP/BA Boundary Inventory](mvp-pruning-mcp-ba-boundary.md)

## Testing Coverage Areas

The repository includes unit, integration, CLI VCR, and E2E tests across:

- auth/session paths
- notebooks, sources, chat, research, and reduced artifact generation flows
- deferred compatibility surfaces (`notes`, `settings`, `sharing`) where they remain intentionally in-tree
- legacy/frozen MCP tools/resources and server behavior
- platform-specific behavior (including Windows compatibility)

## Key Constraints and Risk Profile

- Uses undocumented Google NotebookLM APIs (subject to upstream breakage)
- Sensitive auth/session handling is required
- Generation and research flows can be rate-limited by upstream services
