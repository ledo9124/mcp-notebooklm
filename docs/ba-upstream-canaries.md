# BA Upstream Canaries

Status: active canary guidance for `bd-yae.6.5`  
Last updated: 2026-03-12

## Purpose

The BA runner depends on undocumented NotebookLM APIs, a private SDK facade, and a public MCP layer. These canaries are meant to provide cheap early warning when one of those dependency surfaces drifts in a way that would break BA workflows.

They are intentionally structural rather than end-to-end:

- no live NotebookLM network traffic is required
- failures point to a specific capability area
- the suite stays fast enough to run as part of normal unit-test coverage

## Covered Areas

`tests/unit/test_ba_canaries.py` currently protects these areas:

- `source_ingest`: URL, text, file, and Drive ingest methods the BA adapter expects on `SourcesAPI`
- `source_snapshot`: source listing, lookup, fulltext, guide, and freshness methods used for persisted snapshots
- `structured_chat`: ask/history/conversation helpers used by extraction flows
- `notes_bridge`: note CRUD plus the current degraded note-to-source fallback via `sources.add_text(...)`
- `chat_settings`: notebook-scoped settings methods used by BA prompt control
- `output_language`: global output-language getters/setters
- `report_artifacts`: report generation, wait, download, and export helpers
- `data_table_artifacts`: data-table generation, wait, download, and export helpers
- `mind_map_artifacts`: current note-backed mind-map helpers
- `ba_public_tools`: currently registered workflow-native MCP handlers
- `source_and_chat_tools`, `notes_bridge_tools`, `settings_tools`, `artifact_tools`: required generic MCP tools that BA workflows or BA-adjacent automation rely on

## How To Run

```bash
PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q tests/unit/test_ba_canaries.py
```

## How To Interpret Failures

### SDK surface failures

If a failure mentions one of the SDK areas above, the usual cause is that a method disappeared, moved, or changed its required parameters in `src/notebooklm/`.

Typical examples:

- `source_snapshot`: `_sources.py` changed and the BA adapter may no longer be able to collect full-fidelity snapshots.
- `structured_chat`: `_chat.py` changed and extraction prompts may no longer have the conversation or citation helpers they expect.
- `notes_bridge`: `_notes.py` or the current note-to-text fallback assumptions changed.
- `chat_settings` or `output_language`: settings APIs moved or their signatures changed.
- `report_artifacts`, `data_table_artifacts`, or `mind_map_artifacts`: artifact helper signatures drifted and BA support flows may need adapter updates.

### MCP surface failures

If a failure mentions `ba_public_tools` or one of the MCP tool groups, the issue is in `src/notebooklm_mcp/tools/` registration or in one of the public handler modules.

Typical examples:

- `ba_public_tools`: one of the public `ba.*` handlers stopped registering
- `notes_bridge_tools`: note curation or note-to-source helpers disappeared from the MCP layer
- `settings_tools`: notebook settings or output-language helpers are no longer publicly reachable
- `artifact_tools`: report/data-table/mind-map helpers drifted out of the server registry

## Limits

These canaries do not prove that Google’s live NotebookLM backend still behaves the same. They only prove that the local SDK and MCP surfaces still expose the specific methods and tool names the BA runner is built around.

That tradeoff is intentional: these checks are early warning, not full integration confidence.
