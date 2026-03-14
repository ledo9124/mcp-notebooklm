# BA Runner Parity Audit

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

## Parity Matrix

### Foundation and Conversation Surface

| Capability | BA relevance | SDK status | CLI status | MCP status | Repo evidence / call sites | Notes / risks / recommended next action |
| --- | --- | --- | --- | --- | --- | --- |
| Notebook lifecycle: list/create/get/rename/delete | helpful | present | present | partial | `src/notebooklm/client.py`; notebook APIs in `src/notebooklm/_notebooks.py`; notebook MCP registration in `src/notebooklm_mcp/tools/notebooks.py`; MCP docs in `docs/mcp-tools.md` | MCP already covers core notebook CRUD, but the BA runner will likely want one normalized notebook handle model rather than raw tool-by-tool calls. |
| Notebook summary and description | helpful | present | present | partial | `client.notebooks.get_summary/get_description` exposed via `src/notebooklm/client.py`; notebook resource in `src/notebooklm_mcp/resources.py`; current MCP summary tool docs in `docs/mcp-tools.md` | Summary is available today; description parity is less explicit on the MCP side. Adapter should normalize notebook summary/description retrieval before BA workflows depend on it. |
| Chat ask with citations | critical | present | present | present | `src/notebooklm/client.py`; MCP `notebooklm_chat_ask` in `src/notebooklm_mcp/tools/chat.py`; CLI chat surface in `src/notebooklm/cli/` | This is one of the strongest existing MCP surfaces and can be reused directly inside BA workflows. |
| Conversation history and conversation reuse | helpful | present | present | present | `client.chat.ask/get_history/get_conversation_id` via `src/notebooklm/client.py`; `notebooklm_chat_get_conversation` in `src/notebooklm_mcp/tools/chat.py` | Good enough for BA clarification loops. Keep conversation IDs as first-class adapter fields. |
| Notebook chat settings: goal/response length/custom prompt | helpful | present | present | present | chat settings API in `src/notebooklm/_chat.py`; CLI settings commands; MCP registration in `src/notebooklm_mcp/tools/chat_settings.py` and workflow helper `_apply_chat_settings` in `src/notebooklm_mcp/tools/workflows.py` | MCP already exposes notebook-scoped chat settings well enough for BA bootstrap flows. |

### Source Ingestion and Source Intelligence

| Capability | BA relevance | SDK status | CLI status | MCP status | Repo evidence / call sites | Notes / risks / recommended next action |
| --- | --- | --- | --- | --- | --- | --- |
| Source ingest: URL/text/file | critical | present | present | present | `src/notebooklm/_sources.py` (`add_url`, `add_text`, `add_file`); CLI commands in `src/notebooklm/cli/source.py`; MCP registrations in `src/notebooklm_mcp/tools/sources.py` | Current MCP already handles the basic ingestion cases needed for bootstrap flows. |
| Source ingest: Google Drive | critical | present | removed from active mainline CLI | missing | `src/notebooklm/_sources.py` (`add_drive`); direct CLI `source_add_drive` was pruned from `src/notebooklm/cli/source.py`; no corresponding MCP registration in `src/notebooklm_mcp/tools/sources.py` | This is now an SDK-only parity gap for BA workflows that depend on Drive docs/slides/sheets as inputs. Add MCP tool and adapter method early. |
| Source list/get/delete/rename metadata management | critical | present | partial (`list` retained; `get`/`delete`/`rename` removed) | partial | `src/notebooklm/_sources.py` (`list`, `get`, `delete`, `rename`); active CLI now keeps only `list` in `src/notebooklm/cli/source.py`; MCP has `notebooklm_sources_list` and destructive remove in `src/notebooklm_mcp/tools/sources.py` | MCP still lacks a first-class source `get` tool and rename tool. The active mainline CLI is no longer a parity reference for the removed metadata-management commands. |
| Wait for source readiness | critical | present | present | present | `src/notebooklm/_sources.py` (`wait_until_ready`, `wait_for_sources`); `notebooklm_sources_wait_ready` in `src/notebooklm_mcp/tools/sources.py` | This already matches the BA runner's need to gate later steps on source readiness. |
| Source refresh | critical | present | removed from active mainline CLI | missing | `src/notebooklm/_sources.py` (`refresh`); direct CLI refresh was pruned from `src/notebooklm/cli/source.py`; no MCP tool registration for refresh | BA clarification loops still need reliable refresh for stale URL/Drive sources. Add MCP parity before BA source curation is designed. |
| Source freshness check | critical | present | removed from active mainline CLI | missing | `src/notebooklm/_sources.py` (`check_freshness`); direct CLI stale check was pruned from `src/notebooklm/cli/source.py`; no MCP tool/resource equivalent | The revised BA plan explicitly wants freshness in snapshots/manifests. This remains one of the most important phase-0 gaps. |
| Source guide: summary + keywords | critical | present | removed from active mainline CLI | missing | `src/notebooklm/_sources.py` (`get_guide`); direct CLI guide command was pruned from `src/notebooklm/cli/source.py`; no MCP tool/resource equivalent | BA source triage and context-packing will want guide metadata. Add a dedicated MCP surface, not just fulltext. |
| Source fulltext retrieval | critical | present | removed from active mainline CLI | partial | `src/notebooklm/_sources.py` (`get_fulltext`); direct CLI fulltext command was pruned from `src/notebooklm/cli/source.py`; MCP `notebooklm_sources_get_content` in `src/notebooklm_mcp/tools/sources.py`; source resource in `src/notebooklm_mcp/resources.py` | MCP only exposes capped content preview/fulltext retrieval, not the richer source-intelligence bundle the BA runner wants. Still useful as a base. |

### Notes, Research, and Global Settings

| Capability | BA relevance | SDK status | CLI status | MCP status | Repo evidence / call sites | Notes / risks / recommended next action |
| --- | --- | --- | --- | --- | --- | --- |
| Note CRUD | critical | present | present | missing | `src/notebooklm/_notes.py` (`list`, `get`, `create`, `update`, `delete`); `src/notebooklm/cli/note.py`; no note tool registration in `src/notebooklm_mcp/tools/__init__.py` | BA workflows need explicit note handling. Today MCP only exposes note creation indirectly from chat. Add a dedicated note surface. |
| Chat answer save-as-note | helpful | present | present | present | `notebooklm_chat_ask` creates real notes through `app_context.client.notes.create(...)` in `src/notebooklm_mcp/tools/chat.py` | This is one real MCP note path today, but it is too narrow to count as note parity. |
| Workflow research `save_as_note` semantics | critical | n/a | n/a | misleading partial | `src/notebooklm_mcp/tools/workflows.py` writes `app.client.sources.add_text(...)` when `save_as_note=true` | This does not create a NotebookLM note. It creates a text source. BA flows must not rely on this name/behavior mismatch. Fix semantics or rename the option before reuse. |
| Note export / note-to-source conversion | critical | unclear / absent | absent | absent | `src/notebooklm/_notes.py` docstring mentions export/conversion, but public methods only expose CRUD; `src/notebooklm/cli/note.py` shows CRUD only | Do not design downstream beads assuming this already exists. Treat it as an unresolved capability gap until implemented or disproven. |
| Research controls: start/poll/import | critical | present | present | missing | `src/notebooklm/_research.py` (`start`, `poll`, `import_sources`); CLI call sites in `src/notebooklm/cli/source.py` and `src/notebooklm/cli/research.py`; no direct MCP research tool set | Current MCP has a one-call research workflow helper, but not the direct control surface the BA runner will need for multi-step orchestration. |
| Global output language | critical | present | present | missing | `src/notebooklm/_settings.py` (`get_output_language`, `set_output_language`); CLI language commands in `src/notebooklm/cli/language.py`; no MCP exposure | The BA runner will need explicit language control for stable output shaping. Add MCP parity as a first-class setting, not as hidden config. |

### Artifacts, Export, Resources, and Prompts

| Capability | BA relevance | SDK status | CLI status | MCP status | Repo evidence / call sites | Notes / risks / recommended next action |
| --- | --- | --- | --- | --- | --- | --- |
| Report generation | critical | present | present | missing | `src/notebooklm/_artifacts.py` (`generate_report`); CLI artifact/download commands in `src/notebooklm/cli/artifact.py` and `src/notebooklm/cli/download.py` | Report generation is central to BA drafting flows and currently unavailable in MCP. |
| Data-table generation | critical | present | present | missing | `src/notebooklm/_artifacts.py` (`generate_data_table`); CLI artifact/download/export commands | This is central to structured extraction and evidence tabulation. Missing MCP parity blocks later BA beads directly. |
| Mind-map generation/download | helpful | present | present | missing | `src/notebooklm/_artifacts.py` (`generate_mind_map`, `download_mind_map`); CLI download command in `src/notebooklm/cli/download.py` | Useful but lower priority than report/data-table. Note that mind maps are stored through the notes system internally. |
| Quiz and flashcard generation | optional | present | present | missing | `src/notebooklm/_artifacts.py` (`generate_quiz`, `generate_flashcards`); CLI artifact/download commands | Not core for BA runner. Can stay behind later optional exposure. |
| Audio, video, slide deck, infographic generation | experimental | present | present | missing | `src/notebooklm/_artifacts.py` (`generate_audio`, `generate_video`, `generate_slide_deck`, `generate_infographic`); CLI artifact/download commands | These should remain explicitly experimental for the BA runner. |
| Artifact list/get/rename/delete/poll/wait | helpful | present | present | missing | `src/notebooklm/_artifacts.py` (`list`, `get`, `rename`, `delete`, `poll_status`, `wait_for_completion`); CLI artifact commands in `src/notebooklm/cli/artifact.py` | MCP cannot currently manage artifact lifecycles at all. Any BA artifact workflow will need this substrate. |
| Artifact download and Google export | critical | present | present | missing | `src/notebooklm/_artifacts.py` (`download_*`, `export_report`, `export_data_table`, `export`); CLI export in `src/notebooklm/cli/artifact.py`; download commands in `src/notebooklm/cli/download.py` | This is a major parity gap. BA workflows need both local downloads and Docs/Sheets export hooks. |
| MCP resources for notebook/source snapshotting | helpful | partial | n/a | partial | `src/notebooklm_mcp/resources.py` registers only `notebooklm://notebooks`, notebook detail, single-source content, and audit recent | Current resources are too thin for BA snapshot needs such as source guide, freshness, richer source manifests, or artifact/note views. |
| MCP prompts for BA-oriented orchestration | helpful | n/a | n/a | partial | `src/notebooklm_mcp/prompts.py` registers only `notebook_summary` and `source_analysis` | Prompts are intentionally minimal today and do not yet reflect BA workflows, evidence synthesis, or drafting stages. |

## Must-Have Capability Adapter Call Sites

The BA adapter should wrap SDK methods directly and expose normalized internal models, rather than composing the current MCP tools ad hoc.

- Notebook substrate:
  - `client.notebooks.list`
  - `client.notebooks.create`
  - `client.notebooks.get`
  - `client.notebooks.rename`
  - `client.notebooks.delete`
  - `client.notebooks.get_summary`
  - `client.notebooks.get_description`
- Source substrate:
  - `client.sources.list`
  - `client.sources.get`
  - `client.sources.add_url`
  - `client.sources.add_text`
  - `client.sources.add_file`
  - `client.sources.add_drive`
  - `client.sources.delete`
  - `client.sources.rename`
  - `client.sources.refresh`
  - `client.sources.check_freshness`
  - `client.sources.get_fulltext`
  - `client.sources.get_guide`
  - `client.sources.wait_until_ready`
  - `client.sources.wait_for_sources`
- Chat and notebook settings substrate:
  - `client.chat.ask`
  - `client.chat.get_history`
  - `client.chat.get_conversation_id`
  - `client.chat.get_settings`
  - `client.chat.update_settings`
  - `client.chat.set_settings`
  - `client.chat.reset_settings`
- Notes substrate:
  - `client.notes.list`
  - `client.notes.get`
  - `client.notes.create`
  - `client.notes.update`
  - `client.notes.delete`
- Research substrate:
  - `client.research.start`
  - `client.research.poll`
  - `client.research.import_sources`
- Global settings substrate:
  - `client.settings.get_output_language`
  - `client.settings.set_output_language`
- Artifact substrate:
  - `client.artifacts.list`
  - `client.artifacts.get`
  - `client.artifacts.generate_report`
  - `client.artifacts.generate_data_table`
  - `client.artifacts.generate_mind_map`
  - `client.artifacts.generate_quiz`
  - `client.artifacts.generate_flashcards`
  - `client.artifacts.generate_audio`
  - `client.artifacts.generate_video`
  - `client.artifacts.generate_slide_deck`
  - `client.artifacts.generate_infographic`
  - `client.artifacts.poll_status`
  - `client.artifacts.wait_for_completion`
  - `client.artifacts.download_report`
  - `client.artifacts.download_data_table`
  - `client.artifacts.download_mind_map`
  - `client.artifacts.download_quiz`
  - `client.artifacts.download_flashcards`
  - `client.artifacts.download_audio`
  - `client.artifacts.download_video`
  - `client.artifacts.download_slide_deck`
  - `client.artifacts.download_infographic`
  - `client.artifacts.export_report`
  - `client.artifacts.export_data_table`
  - `client.artifacts.export`
  - `client.artifacts.rename`
  - `client.artifacts.delete`

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
6. Expand MCP resources/prompts only after the underlying capability adapter and missing raw surfaces are in place.
