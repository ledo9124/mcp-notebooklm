# Project Overview

**Status:** Active  
**Last Updated:** 2026-03-07

This document summarizes what the project does today and the main technologies used to implement it.

## Purpose

`notebooklm-py` is an unofficial automation toolkit for Google NotebookLM with:

- Async Python SDK
- Full-featured CLI
- MCP server for agent tool use

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
- `mcp` + `pydantic`: MCP server and typed tool schemas

### Development and Quality Tooling

- `pytest`, `pytest-asyncio`, `pytest-httpx`, `vcrpy`
- `ruff`, `mypy`, `pre-commit`

## High-Level Architecture

- `src/notebooklm/`: Python SDK + CLI
  - `client.py`: `NotebookLMClient` entry point
  - `_core.py`: shared HTTP/RPC core, retry/auth refresh behavior
  - `_notebooks.py`, `_sources.py`, `_artifacts.py`, `_chat.py`, `_research.py`, `_notes.py`, `_settings.py`, `_sharing.py`: domain APIs
  - `rpc/`: RPC types, encoding, decoding
  - `cli/`: command groups (`source`, `generate`, `download`, `artifact`, `note`, `share`, `research`, etc.)
- `src/notebooklm_mcp/`: MCP server
  - tool registration (notebooks, sources, chat, settings, workflows, ops)
  - MCP resources and prompts
  - stdio and HTTP transports

## Current Functional Coverage

### 1) Authentication and Session

- Browser login flow (`notebooklm login`)
- Storage-state based auth loading
- `NOTEBOOKLM_AUTH_JSON` support for CI/CD
- Context tracking for active notebook/conversation
- Automatic token refresh on auth failures

### 2) Notebook Management

- List, create, get, rename, delete notebooks
- Notebook summary/description retrieval
- Remove notebook from recent list

### 3) Source Management

- Add sources from URL, YouTube, local files, pasted text, Google Drive
- List/get/rename/delete sources
- Refresh sources and check freshness
- Retrieve full indexed source text and source guide
- Wait for source processing/readiness

### 4) Chat and Conversation

- Ask questions with optional source filtering
- Continue existing conversations
- Retrieve conversation history
- Save answers/history to notes
- Citation/reference extraction in structured output

### 5) Chat Settings

- Read and update chat goal/style
- Configure response length
- Set/reset custom prompt instructions

### 6) Research Workflows

- Start fast/deep research (web or drive)
- Poll/wait research status
- Import discovered research sources

### 7) Artifact Generation and Management

- Generate: audio, video, slide deck, slide revision, report, quiz, flashcards, infographic, data table, mind map
- Manage artifacts: list/get/rename/delete
- Poll/wait generation status
- Export selected artifacts to Google Docs/Sheets

### 8) Artifact Downloading

- Download all major artifact types
- Batch download (`--all`) and filtered selection (`--latest`, `--name`, `--artifact`)
- Format options such as PPTX slide deck and JSON/Markdown/HTML quiz/flashcards
- Dry-run and overwrite/no-clobber controls

### 9) Sharing and Access Control

- Public link enable/disable
- Viewer scope control (full notebook or chat-only)
- Per-user permission management (viewer/editor)

### 10) Language Settings

- List supported output languages
- Get/set global language preference for generation output

### 11) MCP Server Surface

- Tools for notebooks, sources, chat, settings, diagnostics, and workflow macros
- Resources for notebooks, notebook details, source content, and recent audit events
- Prompt templates for notebook summarization and source analysis
- Safety gating for destructive operations, with optional two-phase confirmation flow

## Testing Coverage Areas

The repository includes unit, integration, CLI VCR, and E2E tests across:

- auth/session paths
- notebooks, sources, chat, settings, research, sharing
- artifacts generation/download/export flows
- MCP tools/resources and server behavior
- platform-specific behavior (including Windows compatibility)

## Key Constraints and Risk Profile

- Uses undocumented Google NotebookLM APIs (subject to upstream breakage)
- Sensitive auth/session handling is required
- Generation and research flows can be rate-limited by upstream services
