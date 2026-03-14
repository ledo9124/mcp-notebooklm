# Phase 0 Capability Parity Matrix

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
| Source fulltext, guide, freshness, refresh, readiness | Critical | `src/notebooklm/_sources.py` exposes `get_fulltext()`, `get_guide()`, `check_freshness()`, `refresh()`, and `wait_until_ready()` | Active mainline CLI retains `wait`; `fulltext`, `guide`, `stale`, and `refresh` were pruned from `src/notebooklm/cli/source.py` | `src/notebooklm_mcp/tools/sources.py` exposes `notebooklm_sources_wait_ready` and `notebooklm_sources_get_content`; `src/notebooklm_mcp/resources.py` exposes source content preview | Partial MCP parity | The BA adapter should wrap the SDK source methods directly. Current MCP content access is preview-capped, so it is insufficient for deterministic snapshotting. Guide/freshness/refresh are not exposed through MCP today, and the reduced mainline CLI is no longer the parity reference for those capabilities. |
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
- public generic MCP parity is still missing.

## Must-Have Adapter Call Sites

The Phase-0 capability adapter for `src/notebooklm_mcp/ba/` should wrap the SDK directly and avoid importing CLI modules. At minimum, it should provide seams over these call families:

- Source intelligence:
  `sources.add_url()`, `sources.add_file()`, `sources.add_text()`, `sources.wait_until_ready()`, `sources.get_fulltext()`, `sources.get_guide()`, `sources.check_freshness()`, `sources.refresh()`
- Notes and note bridges:
  `notes.create()`, `notes.get()`, `notes.list()`, plus a deliberate wrapper over `sources.add_text()` for note-derived source creation
- Notebook chat settings:
  `chat.get_settings()`, `chat.update_settings()`, `chat.set_settings()`, `chat.reset_settings()`
- Global output language:
  `settings.get_output_language()`, `settings.set_output_language()`
- Research:
  `research.start()`, `research.poll()`, `research.import_sources()`
- Artifact generation and completion:
  `artifacts.generate_report()`, `artifacts.generate_data_table()`, `artifacts.generate_mind_map()`, `artifacts.wait_for_completion()`
- Artifact retrieval and export:
  `artifacts.download_report()`, `artifacts.download_data_table()`, `artifacts.download_mind_map()`, `artifacts.export_report()`, `artifacts.export_data_table()`

## Recommended Interpretation For Phase 0

- `bd-yae.1.2` should assume the BA subsystem plugs into the existing MCP server shell but talks to a dedicated adapter layer for capability access.
- `bd-yae.1.3` should treat SDK-backed capability normalization as the main job, not generic MCP parity expansion.
- `bd-yae.1.4` and `bd-yae.1.5` should assume full-fidelity source snapshotting and explicit note/source object kinds, because the current MCP preview and mixed note behavior are not stable enough as workflow foundations.
