# Source Manifest

- Feature key: `convert-from-mcp-to-cli`
- Run id: `run-20260312T141020Z-a5fc8e53`
- Schema version: `ba.source_manifest.v1.0`
- Source count: 4
- Status counts: `READY`=4
- Parse quality counts: `HIGH`=4

## Sources

| Source Key | Title | Type | Priority | Status | Quality | Freshness | Snapshot |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `feature-requirement` | Feature requirement: convert from MCP to CLI | `PRIMARY_REQUIREMENT` | `REQUIRED` | `READY` | `HIGH` | `fresh` | `feature-requirement-f4b00896bdf4` |
| `cli-quickstart-inline` | CLI quickstart excerpt | `SUPPORTING_TECH` | `HIGH` | `READY` | `HIGH` | `fresh` | `cli-quickstart-inline-ff2d11f7d81c` |
| `phase0-parity-matrix-inline` | Phase 0 capability parity matrix | `SUPPORTING_TECH` | `HIGH` | `READY` | `HIGH` | `fresh` | `phase0-parity-matrix-inline-0e41b635cf12` |
| `ba-runner-parity-audit-inline` | BA runner parity audit | `SUPPORTING_TECH` | `HIGH` | `READY` | `HIGH` | `fresh` | `ba-runner-parity-audit-inline-8ad4ab75796b` |

## Details

### `feature-requirement`

- Title: Feature requirement: convert from MCP to CLI
- Source ref: `# Feature: convert from MCP to CLI

Objective:
- Create an implementation pack for a feature named `convert from mcp to cli`.

Required scope:
- Use repository evidence to identify the current MCP-oriented surfaces and the corresponding CLI capabilities that already exist.
- Describe the changes needed to shift the user-facing workflow from MCP-oriented entry points to CLI-native entry points where the repo already supports them.
- Keep parity gaps explicit when the repo shows that SDK or CLI support differs from MCP support.
- Do not invent capabilities, commands, or behavior that are not supported by the current repository evidence.

Constraints:
- Prefer repository-backed facts over assumptions.
- Treat missing or partial parity as warnings or open questions rather than silent assumptions.`
- Content kind: `INLINE_TEXT`
- Source type: `PRIMARY_REQUIREMENT`
- Priority: `REQUIRED`
- Status: `READY`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `feature-requirement-f4b00896bdf4`
- Notebook source id: `efa59066-3be6-431e-a862-a14bbdef1583`
- Notes: _none_
- Used in screens: _none yet_

### `cli-quickstart-inline`

- Title: CLI quickstart excerpt
- Source ref: `## CLI Quickstart

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
````
- Content kind: `INLINE_TEXT`
- Source type: `SUPPORTING_TECH`
- Priority: `HIGH`
- Status: `READY`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `cli-quickstart-inline-ff2d11f7d81c`
- Notebook source id: `e9528ed0-cecc-45f8-be85-9240999ce9f0`
- Notes: Verified from README CLI quickstart section.
- Used in screens: _none yet_

### `phase0-parity-matrix-inline`

- Title: Phase 0 capability parity matrix
- Source ref: `# Phase 0 Capability Parity Matrix

Support artifact for `bd-yae.1.1`.

This document inventories the `notebooklm-py` capabilities that the revised BA-runner plan explicitly called out for Phase 0 and maps them against the current SDK, CLI, and MCP surfaces.

## Executive Summary

- The SDK in `src/notebooklm/` is materially broader than the current MCP surface in `src/notebooklm_mcp/`.
- Current MCP coverage is strongest for notebooks, basic sources, chat, and notebook-scoped chat settings.
- Current MCP coverage is weak or absent for full-fidelity source audit data, notes CRUD, raw research controls, artifact generation/export, and global output-language settings.
- That gap argues for a dedicated BA capability adapter under `src/notebooklm_mcp/ba/` that wraps the SDK directly, rather than trying to force the BA runner through the existing generic MCP tool set first.
- Full source snapshotting for BA runs must not rely on the current MCP source-content surface alone, because `notebooklm_sources_get_content` and the matching resource return capped previews rather than guaranteed full source text.

## Current Server Boundary

`src/notebooklm_mcp/tools/__init__.py` registers only:

- notebooks
- sources
- chat
- chat settings
- ops
- workflows

There is no current MCP tool module for:

- notes
- research primitives
- artifact generation or export
- global user settings such as output language

Resources in `src/notebooklm_mcp/resources.py` are similarly narrow: notebooks, notebook detail, source content preview, and recent audit entries. Prompts in `src/notebooklm_mcp/prompts.py` are limited to notebook summary and source analysis templates.

## Parity Matrix

| Capability | BA importance | SDK evidence | CLI evidence | MCP evidence | Current state | Phase-0 implication |
| --- | --- | --- | --- | --- | --- | --- |
| Source fulltext, guide, freshness, refresh, readiness | Critical | `src/notebooklm/_sources.py` exposes `get_fulltext()`, `get_guide()`, `check_freshness()`, `refresh()`, and `wait_until_ready()` | `src/notebooklm/cli/source.py` exposes `fulltext`, `guide`, `stale`, `refresh`, and `wait` | `src/notebooklm_mcp/tools/sources.py` exposes `notebooklm_sources_wait_ready` and `notebooklm_sources_get_content`; `src/notebooklm_mcp/resources.py` exposes source content preview | Partial MCP parity | The BA adapter should wrap the SDK source methods directly. Current MCP content access is preview-capped, so it is insufficient for deterministic snapshotting. Guide/freshness/refresh are not exposed through MCP today. |
| Notes CRUD and note-to-source behavior | Helpful for clarification loops; important for note-derived fixtures | `src/notebooklm/_notes.py` exposes note CRUD; `src/notebooklm/_sources.py` exposes `add_text()` for source creation from text | `src/notebooklm/cli/chat.py` exposes `ask --save-as-note` and `history --save`; note commands live in `src/notebooklm/cli/note.py` | `src/notebooklm_mcp/tools/chat.py` supports `save_as_note` via `notes.create()`, but `src/notebooklm_mcp/tools/workflows.py` saves "notes" by calling `sources.add_text()` and returning a source ID | Partial and inconsistent | The BA adapter should normalize two distinct behaviors: real notebook notes and text-source creation from synthesized note content. Current MCP lacks general notes CRUD and any explicit note-to-source helper. |
| Notebook chat settings (goal, response length, custom prompt) | Helpful | `src/notebooklm/_chat.py` exposes `get_settings()`, `set_settings()`, `update_settings()`, and `reset_settings()` | `src/notebooklm/cli/chat.py` exposes `configure` and settings display/reset flows | `src/notebooklm_mcp/tools/chat_settings.py` exposes `notebooklm_settings_get`, `notebooklm_settings_patch`, and `notebooklm_settings_reset` | Good parity | This is already exposed cleanly enough for BA use. The BA adapter can wrap the SDK calls without needing new generic MCP work first. |
| Global output language | Helpful; required for output parity when BA artifacts are language-sensitive | `src/notebooklm/_settings.py` exposes `get_output_language()` and `set_output_language()` | `src/notebooklm/cli/language.py` exposes `language list/get/set` and makes clear the setting is account-global | No matching MCP tool or resource is registered | Missing from MCP | The BA adapter should wrap the SDK settings surface directly. A generic MCP language tool can come later if the team wants parity outside `ba.*`. |
| Research controls (start, poll, import discovered sources) | Helpful | `src/notebooklm/_research.py` exposes `start()`, `poll()`, and `import_sources()` | `src/notebooklm/cli/source.py` starts research with `add-research`; `src/notebooklm/cli/research.py` exposes status/wait/import flows | `src/notebooklm_mcp/tools/workflows.py` exposes only the high-level `notebooklm_workflow_research` macro, not raw research primitives | Partial MCP parity | The BA adapter should include raw research controls so the BA subsystem is not forced through one opinionated workflow. Generic MCP research tools are currently absent. |
| Report generation, download, and export | Helpful but not core to the deterministic BA bundle | `src/notebooklm/_artifacts.py` exposes `generate_report()`, `download_report()`, `export_report()`, and generic `export()` | `src/notebooklm/cli/generate.py`, `src/notebooklm/cli/download.py`, and `src/notebooklm/cli/artifact.py` expose report generation/download/export | No artifact tool module is registered in MCP | Missing from MCP | The BA adapter can wrap report generation without waiting for generic MCP parity. If report helpers become public `ba.*` affordances, expose them through thin BA wrappers instead of expanding generic MCP tools first. |
| Data-table generation, download, and export | Helpful / optional | `src/notebooklm/_artifacts.py` exposes `generate_data_table()`, `download_data_table()`, and `export_data_table()` | `src/notebooklm/cli/generate.py`, `src/notebooklm/cli/download.py`, and `src/notebooklm/cli/artifact.py` cover the flow | No MCP artifact/data-table surface exists | Missing from MCP | Same pattern as reports: adapter first, optional public BA wrapper later, no need to grow generic MCP surface before Phase 0 closes. |
| Mind-map generation and download | Optional | `src/notebooklm/_artifacts.py` exposes `generate_mind_map()` and `download_mind_map()`; `src/notebooklm/_notes.py` exposes `list_mind_maps()` because storage is note-backed | `src/notebooklm/cli/generate.py` and `src/notebooklm/cli/download.py` expose mind-map flows | No MCP artifact or mind-map surface exists | Missing from MCP | The adapter should hide the note-backed storage quirk. This is lower priority than source, notes, language, and research seams for the BA critical path. |

## High-Signal Findings

### 1. MCP source content is not full-fidelity

`src/notebooklm_mcp/tools/sources.py::notebooklm_sources_get_content()` calls `client.sources.get_fulltext()` and then truncates the returned content to `min(requested_max, config.source_content_max_chars)`.

That is acceptable for interactive inspection, but it is not acceptable as the canonical BA snapshot path. Phase 1 snapshotting should call the SDK directly through the BA adapter and persist the full content plus metadata.

### 2. Notes behavior is currently split across two incompatible patterns

- `src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask()` can save a real notebook note via `client.notes.create()`.
- `src/notebooklm_mcp/tools/workflows.py::notebooklm_workflow_research()` saves a "research note" by creating a text source via `client.sources.add_text()`.

The BA subsystem should not expose that inconsistency to downstream modules. The adapter needs an explicit note bridge with named semantics such as:

- create notebook note
- create source from synthesized note content
- return the resulting object kind explicitly

### 3. Output language is only available below the current MCP boundary

The SDK and CLI support global output-language management, but the MCP server does not expose it. If BA runs need language-aware artifact generation or drafting assistance, the adapter must own that seam.

### 4. Research is available in the SDK, but MCP only exposes one macro

The current MCP workflow helper is useful, but it is not a substitute for raw `start -> poll -> import` control when a future BA pipeline needs staged or selective research behavior.

### 5. Artifact parity is a large MCP gap

The SDK and CLI already support report, data-table, and mind-map flows. The current MCP server does not register any artifact tool module. That means Phase 0 should assume:

- the upstream capability exists,
- the BA runner can call it through an adapter,
- public generic MCP parity is still missing.`
- Content kind: `INLINE_TEXT`
- Source type: `SUPPORTING_TECH`
- Priority: `HIGH`
- Status: `READY`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `phase0-parity-matrix-inline-0e41b635cf12`
- Notebook source id: `be5989ed-a219-45c2-b914-649073192cb2`
- Notes: Verified from docs/ba-phase0-capability-parity-matrix.md.
- Used in screens: _none yet_

### `ba-runner-parity-audit-inline`

- Title: BA runner parity audit
- Source ref: `# BA Runner Parity Audit

Status: draft evidence artifact for `bd-yae.1.1`  
Last updated: 2026-03-12

## Scope

This audit checks whether the current repository already exposes the raw NotebookLM capabilities that the planned BA runner needs. It is grounded in code paths under `src/notebooklm/`, `src/notebooklm_mcp/`, `src/notebooklm/cli/`, and the current MCP docs.

The target is not "generic feature completeness." The target is whether a future `src/notebooklm_mcp/ba/` subsystem can rely on existing SDK/CLI substrate or whether it must first add new MCP surface area and capability-adapter seams.

## Architecture Summary

- `src/notebooklm/client.py` exposes `NotebookLMClient` as the main facade over namespaced APIs: notebooks, sources, notes, artifacts, chat, research, settings, and sharing.
- `src/notebooklm/_core.py` is the shared RPC/HTTP/auth layer. The SDK surface is the real substrate; the CLI mostly proves and packages that substrate.
- `src/notebooklm/cli/` is a broad Click-based wrapper over the SDK and currently reaches far more NotebookLM functionality than the MCP layer does.
- `src/notebooklm_mcp/server.py` builds a FastMCP server with one shared `AppContext` containing a connected `NotebookLMClient`, concurrency semaphore, stats, and optional audit log.
- `src/notebooklm_mcp/tools/__init__.py` registers notebook, source, chat, chat-settings, ops, and workflow tools. These are mostly thin wrappers over selected SDK calls.
- `src/notebooklm_mcp/resources.py` and `src/notebooklm_mcp/prompts.py` expose only a small resource/prompt surface today.

Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over `NotebookLMClient`, not around the current MCP tool surface as-is.

## Key Findings

1. Current MCP parity is strongest on notebook CRUD, basic source ingestion, chat, notebook chat settings, and a small number of workflow wrappers.
2. The most important BA blocker is the source-intelligence gap: Drive add, refresh, freshness, and guide are in SDK/CLI but not MCP.
3. Notes are not exposed as a first-class MCP surface. Worse, `notebooklm_workflow_research(..., save_as_note=true)` currently creates a text source, not a note.
4. Global output language is implemented in the SDK/CLI and entirely absent from MCP, even though later BA drafting flows will depend on it.
5. Direct research controls and almost the entire artifact lifecycle are present in the SDK/CLI and absent from MCP.
6. Note export / note-to-source conversion should be treated as unresolved. The code comments imply it, but the current public code surface does not implement it.

## Recommended Priority Order

1. Carve out `src/notebooklm_mcp/ba/` and define a capability adapter over `NotebookLMClient`, using the call sites above as the contract boundary.
2. Add MCP parity for source intelligence first: `add_drive`, `refresh`, `check_freshness`, `get_guide`, and richer source metadata access.
3. Add a dedicated note surface and resolve the current note-versus-text-source ambiguity in workflow helpers.
4. Expose direct research controls and global output language.
5. Add report/data-table/mind-map artifact generation plus poll/wait/download/export support.
6. Expand MCP resources/prompts only after the underlying capability adapter and missing raw surfaces are in place.`
- Content kind: `INLINE_TEXT`
- Source type: `SUPPORTING_TECH`
- Priority: `HIGH`
- Status: `READY`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `ba-runner-parity-audit-inline-8ad4ab75796b`
- Notebook source id: `20e2dc5b-0e5d-4903-970f-062c4e61f971`
- Notes: Verified from docs/ba-runner-parity-audit.md.
- Used in screens: _none yet_
