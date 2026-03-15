# Project Overview

**Status:** Active  
**Last Updated:** 2026-03-15

This document summarizes what the project does today and the main technologies used to implement it.

## Purpose

`notebooklm-py` is an unofficial automation toolkit for Google NotebookLM with:

- Async Python SDK
- Focused CLI for the retained MVP workflow

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

## Current Product Boundary

The repository now treats the `notebooklm` CLI and the SDK under `src/notebooklm/**` as the supported product surface.

- The install/import boundary is: PyPI package `notebooklm-py`, Python package `notebooklm`, console command `notebooklm`.
- The actively supported user journeys are notebook bootstrap, source ingestion, research, chat, and the retained `generate` flows.
- Deferred SDK compatibility helpers may still exist in-tree without being part of the active CLI promise.
- Future agent-first work should layer on top of this frozen CLI/SDK boundary rather than reintroducing removed MCP/BA runtimes.
- This overview focuses on the surviving CLI/SDK contract after the MCP/BA cleanup work.

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

## Testing Coverage Areas

The repository includes unit, integration, CLI VCR, and E2E tests across:

- auth/session paths
- notebooks, sources, chat, research, and reduced artifact generation flows
- deferred compatibility surfaces (`notes`, `settings`, `sharing`) where they remain intentionally in-tree
- platform-specific behavior (including Windows compatibility)

## Key Constraints and Risk Profile

- Uses undocumented Google NotebookLM APIs (subject to upstream breakage)
- Sensitive auth/session handling is required
- Generation and research flows can be rate-limited by upstream services
