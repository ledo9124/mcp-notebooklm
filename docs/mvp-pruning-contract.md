# MVP Pruning Contract

Support artifact for `bd-27n.1.1`.

This document turns [PRUNING_PLAN.md](../PRUNING_PLAN.md) into an execution contract for the MVP-pruning workstream. Use it to answer three questions before deleting or shrinking any surface:

1. Should this surface still exist in the MVP?
2. What has to be removed first so imports and user flows do not break?
3. What checks prove the phase landed safely?

## Architecture Snapshot

- `src/notebooklm/` is the mainline product surface: async SDK, Click CLI, auth/bootstrap, and RPC transport.
- `src/notebooklm/notebooklm_cli.py` is the `notebooklm` entry point. It imports command groups through `src/notebooklm/cli/__init__.py` and then registers top-level and grouped commands.
- `src/notebooklm/client.py` is the SDK import hub. `NotebookLMClient` now eagerly constructs notebooks, sources, artifacts, chat, and research, while `notes`, `settings`, and `sharing` remain as lazy deferred-compatibility properties.
- `src/notebooklm/__init__.py` is the public package boundary. It re-exports the client, auth helpers, exceptions, and a broad type surface.
- `src/notebooklm_mcp/` is a separate legacy/frozen server product retained in-tree outside the packaged mainline surface. `src/notebooklm_mcp/server.py` still builds the FastMCP server and registers tools, resources, and prompts for that archived boundary.
- `src/notebooklm_mcp/ba/` is an additional BA workflow layer under the MCP tree, not part of the core CLI/SDK bootstrap story.

## Status Vocabulary

| Status | Meaning | Contributor rule |
| --- | --- | --- |
| `KEEP` | Supported MVP surface. | Preserve it in code, help text, docs, and tests. |
| `DELETE` | Remove from the mainline branch during pruning. | Delete the front-door surface and its dead imports/callers in the same phase. |
| `DEFER` | Not part of the intended MVP, but temporarily retained because callers or compatibility boundaries still depend on it. | Do not advertise it as endorsed scope; remove only after dependencies are gone. |
| `LEGACY/FROZEN` | Outside the MVP and intentionally quarantined behind a side boundary. | No new scope. Keep isolated, clearly marked, and out of the mainline promise. |

`DEFER` and `LEGACY/FROZEN` are different. `DEFER` means "still entangled with the mainline and cannot be safely deleted yet." `LEGACY/FROZEN` means "separate boundary that survives temporarily but is explicitly outside the MVP."

## MVP User-Complete Workflows

The pruned product must still support at least these coherent zero-to-output flows:

1. Auth/bootstrap:
   `notebooklm login -> notebooklm auth check -> notebooklm create -> notebooklm use -> notebooklm status`
2. Direct source ingestion:
   `notebooklm source add -> notebooklm source wait -> notebooklm ask`
3. Research-assisted ingestion:
   `notebooklm source add-research --no-wait -> notebooklm research status|wait --import-all -> notebooklm ask`
4. Minimal generation:
   `notebooklm generate audio --wait` or `notebooklm generate report --format briefing-doc|study-guide --wait`

Anything that does not help preserve one of those flows starts from `DELETE`, `DEFER`, or `LEGACY/FROZEN`, not from "keep it just in case."

## Command-Surface Contract

| Surface | MVP state | Status | Notes |
| --- | --- | --- | --- |
| Session top-level: `login`, `use`, `status`, `clear`, `auth check` | Keep | `KEEP` | Core bootstrap and diagnostics path. |
| Notebook top-level: `list`, `create`, `summary` | Keep | `KEEP` | Minimal notebook lifecycle for bootstrap and summary. |
| Notebook top-level: `delete`, `rename` | Remove | `DELETE` | Useful but not required for the MVP bootstrap loop. |
| Chat top-level: `ask` | Keep | `KEEP` | Preserve minimal conversation continuity only. |
| Chat top-level: `configure`, `history` | Remove | `DELETE` | Chat settings parity and note/history features are outside MVP. |
| Source group: `list`, `add`, `wait`, `add-research` | Keep | `KEEP` | Covers direct and research-assisted acquisition. |
| Source group: `get`, `fulltext`, `guide`, `stale`, `delete`, `rename`, `refresh`, `add-drive` | Remove from user-facing CLI | `DELETE` | Valuable internals may survive briefly, but the front-door CLI promise should go. |
| Research group: `status`, `wait` | Keep | `KEEP` | Needed to monitor `source add-research --no-wait`. |
| Generate group: `audio` | Keep | `KEEP` | Canonical MVP artifact flow. |
| Generate group: `report` limited to `briefing-doc` and `study-guide` | Keep in reduced form | `KEEP` | `blog-post`, `custom`, and non-core report affordances are not MVP promises. |
| Generate group: `video`, `slide-deck`, `revise-slide`, `quiz`, `flashcards`, `infographic`, `data-table`, `mind-map` | Remove | `DELETE` | Outside the supportable MVP. |
| Grouped command surfaces: `artifact`, `download`, `note`, `share`, `skill`, `language` | Remove | `DELETE` | Entire groups fall outside the target product. |
| `notebooklm-mcp` entry point and `src/notebooklm_mcp/**` | Quarantine | `LEGACY/FROZEN` | Separate product boundary, not part of the MVP CLI/SDK promise. See [MCP/BA boundary inventory](mvp-pruning-mcp-ba-boundary.md). |
| `src/notebooklm_mcp/ba/**` | Quarantine | `LEGACY/FROZEN` | Nested under MCP; explicitly out of current MVP scope. See [MCP/BA boundary inventory](mvp-pruning-mcp-ba-boundary.md). |

## SDK and Module Contract

| Surface | MVP state | Status | Notes |
| --- | --- | --- | --- |
| `NotebookLMClient.notebooks` | Keep reduced lifecycle | `KEEP` | Keep `list`, `create`, `get`, `get_summary`, `get_description`, `get_raw`; remove delete/rename/share helpers later. |
| `NotebookLMClient.sources` | Keep | `KEEP` | Main MVP promise is add/list/wait plus acquisition support. Broader source helpers may remain as implementation detail during transition. |
| `NotebookLMClient.chat` | Keep reduced ask path | `KEEP` | Preserve ask plus only the continuity helpers required to keep conversations usable. |
| `NotebookLMClient.research` | Keep | `KEEP` | Supports `add-research -> status/wait -> import` flow. |
| `NotebookLMClient.artifacts` | Keep reduced artifact backend | `KEEP` | Restrict to status/wait plus audio and constrained report generation. |
| `NotebookLMClient.notes` | Lazy compatibility hold only | `DEFER` | No longer part of the active CLI promise; retained for deferred callers and historical surfaces. |
| `NotebookLMClient.settings` | Lazy compatibility hold only | `DEFER` | Root `language` CLI is gone, but the SDK helper remains available lazily. |
| `NotebookLMClient.sharing` | Lazy compatibility hold only | `DEFER` | Remove only after compatibility callers are deliberately cut. |
| `src/notebooklm/_notes.py` | Temporary hold only | `DEFER` | Retained for deferred notes/mind-map compatibility paths. |
| `src/notebooklm/_sharing.py` | Temporary hold only | `DEFER` | Out of scope, but still part of the current client/public surface. |
| `src/notebooklm/_settings.py` | Temporary hold only | `DEFER` | Retained only for lazy compatibility and local generation-language support. |
| `src/notebooklm/_chat_settings.py` | Archived parser stock only | `LEGACY/FROZEN` | Active `src/notebooklm/_chat.py` no longer depends on it; retain only as frozen parser/test stock until a deliberate cleanup removes it. |
| `src/notebooklm/__init__.py` | Hold as public compatibility boundary | `DEFER` | Do not treat package-export cleanup as a prerequisite for the CLI MVP. See [Package API Break Strategy](mvp-pruning-package-api-strategy.md). |

## Coupling Map and No-Delete-Before Rules

1. Root CLI registration is two-hop. `src/notebooklm/notebooklm_cli.py` imports command groups from `src/notebooklm/cli/__init__.py`, and that package re-exports leaf modules. Removing a CLI leaf requires removing both the root registration and the `cli/__init__.py` re-export in the same change.
2. `NotebookLMClient` is still the import hub. It now eagerly constructs only the retained MVP subclients, but `notes`, `settings`, and `sharing` remain lazy compatibility properties. Removing `_notes.py`, `_settings.py`, or `_sharing.py` still requires clearing the deferred callers first.
3. `cli/language.py` mixes helper library and command surface. `src/notebooklm/cli/generate.py` imports `SUPPORTED_LANGUAGES` and `get_language`, while `src/notebooklm/cli/session.py` imports `set_language` for post-login server sync. The `language` command group can disappear before the helper file disappears, but helper relocation or session cleanup must happen first.
4. The active CLI chat flow is now reduced to `ask`; note-save/history branches are gone from the mainline shell. Remaining notes coupling lives in deferred compatibility callers and frozen reference material rather than in the supported CLI path.
5. Mind maps no longer flow through the active artifact backend. The note-backed mind-map surfaces now survive only as deferred compatibility behavior and should be treated as such in follow-up deletion work.
6. `src/notebooklm/__init__.py` is a public API promise, not just internal glue. It re-exports a broad type and exception surface in addition to `NotebookLMClient`. Pruning that file is a deliberate package-compatibility decision and should not be mixed casually into early CLI pruning.
7. MCP is already a separate product boundary. `src/notebooklm_mcp/__main__.py` still owns transport startup and `src/notebooklm_mcp/server.py` still registers tools/resources/prompts around a shared `NotebookLMClient` lifespan, but that boundary is no longer shipped as part of the packaged mainline product.
8. `src/notebooklm/_chat_settings.py` is no longer on the active `ChatAPI` execution path. Remaining references belong to archived parser/test stock, so treat it as `LEGACY/FROZEN`, not as a hidden blocker for core CLI/SDK pruning.
9. `docs/stability.md` currently defines the `__all__` exports in `src/notebooklm/__init__.py` as stable public API within the current major version. Internal pruning beads therefore must not silently contract the package root; that requires a dedicated compatibility/release decision.

## Intended Removal Order

1. Freeze terminology and contract first. Future beads should cite this document and [PRUNING_PLAN.md](../PRUNING_PLAN.md), not reconstruct intent from old chat.
2. Quarantine `src/notebooklm_mcp/ba/**` behind a documented `LEGACY/FROZEN` boundary. Boundary note: [docs/mvp-pruning-mcp-ba-boundary.md](mvp-pruning-mcp-ba-boundary.md).
3. Quarantine the rest of `src/notebooklm_mcp/**` and the `notebooklm-mcp` entry point behind that same boundary.
4. Remove standalone CLI leaves with the lowest coupling first: `skill` and then `src/notebooklm/data/SKILL.md`, then `share`.
5. Remove note-dependent chat branches before deleting `note` or shrinking note-backed internals.
6. Remove `download` and `artifact` command groups before shrinking the artifact backend.
7. Reduce `generate.py` and `src/notebooklm/_artifacts.py` to audio plus constrained report generation.
8. Reduce notebook surface to `list`, `create`, and `summary`, then trim `_notebooks.py`.
9. Reduce source CLI surface to add/list/wait/add-research while keeping the research monitor loop intact.
10. Remove chat-settings parity and chat-history surfaces, then reclassify `_chat_settings.py` as archived parser stock until a deliberate cleanup deletes it.
11. Remove post-login language sync, then split or inline the remaining language helpers, then shrink `NotebookLMClient`.
12. Only after the steps above, decide whether `_notes.py`, `_sharing.py`, and `_settings.py` move from `DEFER` to `DELETE` in an explicit follow-up branch. See [Deferred Module Disposition](mvp-pruning-deferred-module-disposition.md).
13. Keep `src/notebooklm/__init__.py` on its own package-API break lane with migration notes and an explicit versioning decision. See [Package API Break Strategy](mvp-pruning-package-api-strategy.md).

## Validation Matrix

| Check | When required | Minimum pass bar | Evidence anchors |
| --- | --- | --- | --- |
| Import smoke | Every phase | `notebooklm` package imports cleanly, `NotebookLMClient` constructs, and any still-supported side boundary imports without immediate failure. | `src/notebooklm/__init__.py`, `src/notebooklm/client.py`, `src/notebooklm_mcp/__init__.py` |
| CLI help truthfulness | Any CLI surface change | Root help and retained command-group help list only the supported MVP commands. Removed groups must disappear from registration and docs in the same phase. | `src/notebooklm/notebooklm_cli.py`, `src/notebooklm/cli/__init__.py`, `docs/cli-reference.md`, `README.md` |
| Bootstrap workflow smoke | Any change touching session/notebook/source/chat/generate/research | The user-complete workflows in this contract still work end-to-end, or the phase is not complete. | `tests/integration/test_notebooks.py`, `tests/integration/test_sources.py`, `tests/integration/test_chat.py`, `tests/integration/test_artifacts.py`, `tests/integration/test_research_api.py` |
| Focused unit and integration coverage | Any module reduction | The tests nearest the edited surface are updated and green before handoff. | `tests/unit/*`, `tests/integration/*`, `tests/e2e/*` |
| Packaging and entry-point truthfulness | Any deletion of command groups, data files, extras, or scripts | `pyproject.toml` scripts, optional deps, and package data match the surviving product. No orphaned `SKILL.md`/entry point remains. | `pyproject.toml`, `src/notebooklm/data/SKILL.md` |
| Docs/help updates | Every externally visible scope cut | README, project overview, CLI reference, and any relevant API/MCP docs state the same boundary as the code. | `README.md`, `docs/project-overview.md`, `docs/cli-reference.md`, `docs/python-api.md`, `docs/mcp-tools.md` |

## Contributor Checklist

Before closing any pruning bead, confirm all of the following:

- The changed surface is explicitly classified as `KEEP`, `DELETE`, `DEFER`, or `LEGACY/FROZEN`.
- The change preserves at least one MVP user-complete workflow.
- Any removed CLI leaf was also removed from root registration and `cli/__init__.py`.
- `NotebookLMClient` still imports and constructs cleanly after the edit.
- Related docs and help text were updated in the same phase.
- The validation rows for the touched phase were executed, not deferred without a recorded reason.
