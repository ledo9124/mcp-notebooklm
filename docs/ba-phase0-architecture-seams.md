# Phase 0 Support Note: Architecture Seams and BA-Relevant Surface Boundaries

This note is an additive support artifact for `bd-yae.1.1`.

Its purpose is narrower than a full parity matrix:

- map the current runtime layers in the repository,
- identify the concrete seams between SDK, CLI, and MCP,
- call out BA-relevant exposure gaps that matter for `bd-yae.1.2` / `bd-yae.1.3` / `bd-yae.1.4`,
- explain why the revised plan's dedicated `src/notebooklm_mcp/ba/` subsystem is the right fit for this codebase.

## 1. Current Runtime Layers

### 1.1 SDK layer: `src/notebooklm/`

The core library is already broad and organized around a single async client:

- `src/notebooklm/client.py`
  - `NotebookLMClient` is the public entry point.
  - It wires domain APIs onto one shared `ClientCore`: notebooks, sources, notes, artifacts, chat, research, settings, and sharing.
- `src/notebooklm/_core.py`
  - `ClientCore` owns the `httpx.AsyncClient`, batchexecute request construction, response decoding, auth refresh retry, and a local conversation cache.
  - RPC calls are funneled through `rpc_call(...)`, which maps HTTP failures to library exceptions and retries once after auth refresh when possible.
- `src/notebooklm/auth.py`
  - `AuthTokens.from_storage()` loads cookies and fetches the CSRF/session tokens needed by RPC calls.
  - The auth layer is storage-state and cookie driven, not OAuth-token driven.
- `src/notebooklm/rpc/types.py`
  - Central enum/constants file for RPC method ids, artifact/source status enums, chat goal/length enums, export types, sharing enums, and endpoint URLs.
- `src/notebooklm/exceptions.py`
  - Public exception hierarchy already exists and is rich enough to support adapter-level normalization.

The main architectural implication is that the SDK already provides a strong capability layer for the BA runner to wrap. The BA subsystem should not need to invent a second transport abstraction.

### 1.2 CLI layer: `src/notebooklm/notebooklm_cli.py` + `src/notebooklm/cli/`

The CLI is a separate presentation layer over the SDK:

- `src/notebooklm/notebooklm_cli.py`
  - creates the main Click group,
  - registers top-level session/notebook/chat commands,
  - mounts subcommand groups such as `source`, `artifact`, `generate`, `download`, `note`, `share`, `research`, `skill`, and `language`.
- `src/notebooklm/cli/__init__.py`
  - is the aggregation point for command groups and shared helpers.
- `src/notebooklm/cli/grouped.py`
  - organizes help output into session/notebook/chat/groups/actions sections.

This matters because the CLI currently exposes more user-facing capability breadth than the MCP server. The BA runner should therefore treat the SDK as the source of truth and the CLI as evidence of existing product behavior, not as the integration seam.

### 1.3 MCP layer: `src/notebooklm_mcp/`

The MCP server is already a structured shell around the SDK:

- `src/notebooklm_mcp/server.py`
  - defines `AppContext`,
  - constructs the shared `NotebookLMClient`,
  - provides concurrency slots via a semaphore,
  - registers tools/resources/prompts after server construction.
- `src/notebooklm_mcp/_errors.py`
  - maps library exceptions to MCP-friendly error payloads,
  - records stats/audit information,
  - sanitizes error messages.
- `src/notebooklm_mcp/_result.py`
  - provides the shared dual-output `structuredContent` + text JSON fallback contract.
- `src/notebooklm_mcp/resources.py`
  - currently registers only a small resource surface.
- `src/notebooklm_mcp/prompts.py`
  - currently registers only two generic prompt templates.
- `src/notebooklm_mcp/tools/__init__.py`
  - registers notebooks, sources, chat, chat settings, ops, and workflow tools.

This layer is already opinionated in the right way: thin wrappers over the SDK, with shared lifecycle/config/error/result behavior. The BA runner should plug into this shell, not replace it.

## 2. BA-Relevant Capability Split

The important Phase 0 question is not "does the repo do X somewhere?" It is "where is X exposed today, and what is the cleanest seam for the BA runner?"

| Capability area | SDK | CLI | MCP | Notes |
| --- | --- | --- | --- | --- |
| Notebook lifecycle | Yes | Yes | Yes | `NotebooksAPI` is already mirrored cleanly by `tools/notebooks.py`. |
| Core source ingest/list/wait/fulltext | Yes | Yes | Partial | MCP covers list/add URL/add text/add file/wait/fulltext, but not the full source-management surface. |
| Source guide/freshness/refresh/Drive ingest | Yes | Present in source subsystem | No direct MCP surface | `SourcesAPI` includes `add_drive`, `refresh`, `check_freshness`, `get_guide`, and `get_fulltext`; current MCP surface stops earlier. |
| Chat ask/history/citations | Yes | Yes | Yes | Current MCP chat tools are thin wrappers over `client.chat`. |
| Notebook chat settings | Yes | Yes | Yes | Exposed through `tools/chat_settings.py` as notebook-level settings helpers. |
| Global output language | Yes | Yes | No | `SettingsAPI` manages global output language; CLI has a dedicated `language` group; MCP does not expose this surface today. |
| Notes CRUD | Yes | Yes | No direct notes tools | MCP only reaches notes indirectly through `save_as_note` flows in chat/workflow macros. |
| Note-derived curation / note-to-source helpers | Not yet cleanly exposed | Not exposed as a first-class note workflow | No | This is still a parity gap for BA clarification loops. |
| Research sessions (web/drive search + import) | Yes | Yes | No direct research parity | `ResearchAPI` exists, but current MCP "research" workflow is a question-asking macro, not the SDK research session surface. |
| Artifact generation/download/export | Yes | Yes | No | SDK/CLI already cover reports, data tables, mind maps, media, downloads, and export paths; MCP does not register artifact tools today. |
| Sharing/access control | Yes | Yes | No | Sharing stays entirely outside current MCP registration. |
| MCP resources/prompts | N/A | N/A | Narrow | Resources are currently notebooks/notebook/source/audit only; prompts are notebook summary and source analysis only. |

## 3. Important Code-Level Observations

### 3.1 The SDK breadth is real

The current `NotebookLMClient` surface already spans the capability families the revised BA plan depends on:

- notebooks via `src/notebooklm/_notebooks.py`
- sources via `src/notebooklm/_sources.py`
- chat via `src/notebooklm/_chat.py`
- artifacts via `src/notebooklm/_artifacts.py`
- research via `src/notebooklm/_research.py`
- notes via `src/notebooklm/_notes.py`
- global settings via `src/notebooklm/_settings.py`
- sharing via `src/notebooklm/_sharing.py`

That means the BA runner should be designed as an adapter over existing client capabilities, not as an excuse to extend `ClientCore` directly.

### 3.2 Current MCP parity is intentionally narrower

`src/notebooklm_mcp/tools/__init__.py` registers:

- notebook tools,
- source tools,
- chat tools,
- notebook chat-settings tools,
- ops tools,
- two generic workflow macros.

It does not currently register:

- research session controls,
- artifact generation/download/export tools,
- notes CRUD or note-curation helpers,
- sharing tools,
- global output-language controls.

This is not a criticism of the current MCP implementation. It is the key Phase 0 fact that later BA work must be built around.

### 3.3 `tools/workflows.py` is already the "do not sprawl here" warning sign

The revised plan's section 23.2 is consistent with the repo's actual shape:

- `src/notebooklm_mcp/tools/workflows.py` already holds substantial generic orchestration code.
- The existing registered workflows are `notebooklm_workflow_bootstrap_notebook` and `notebooklm_workflow_research`.
- The latter is not SDK research parity; it is a bounded "ensure ready, ask, optionally save note" macro over chat/source helpers.

Adding the BA runner as "more helpers in `tools/workflows.py`" would blend generic NotebookLM workflows with a domain-specific pipeline and make the server harder to reason about.

### 3.4 The global settings surface is separate from notebook chat settings

The current codebase distinguishes:

- notebook-level chat settings in `src/notebooklm/_chat.py` and `src/notebooklm_mcp/tools/chat_settings.py`
- global output language in `src/notebooklm/_settings.py` and `src/notebooklm/cli/language.py`

That distinction matters for the BA runner. A future capability adapter should not conflate notebook-local prompting controls with account-global artifact language configuration.

### 3.5 Notes parity is weaker than the code comments imply

`src/notebooklm/_notes.py` says notes "support operations like export to Docs/Sheets and conversion to sources", but the current implemented methods are:

- list/get/create/update/delete notes
- list/delete mind maps

The current CLI note group in `src/notebooklm/cli/note.py` is also CRUD-only.

So for BA clarification loops, note-derived curation should be treated as a parity gap that still needs deliberate design, not as a finished surface hidden somewhere in the repo.

## 4. Why a Dedicated `src/notebooklm_mcp/ba/` Subsystem Fits This Repo

The revised plan's recommended code layout in `notebooklm_mcp_upgrade_plan_revised.md` section 23.3 matches the current repository for four practical reasons.

### 4.1 It preserves the dependency direction that already works

The clean dependency chain today is:

`MCP shell -> NotebookLMClient SDK -> RPC/auth layer`

A BA subsystem under `src/notebooklm_mcp/ba/` can preserve that direction:

- `ba/capabilities.py` wraps `NotebookLMClient`
- `ba/tools.py` exposes `ba.*` MCP handlers
- the existing generic MCP shell keeps lifecycle, config, error mapping, result shaping, and concurrency control

### 4.2 It prevents BA logic from leaking into generic parity modules

Current generic MCP modules have clear domains:

- notebooks
- sources
- chat
- chat settings
- ops
- generic workflows

If BA pipeline state, evidence schemas, canonical extraction, readiness logic, rendering, and rerun policy are added directly into those modules, future parity work and future BA work will constantly collide.

### 4.3 It gives `bd-yae.1.3` a real adapter seam

`bd-yae.1.3` should not be a vague facade. The repo already points to the seam:

- `NotebookLMClient` is the public capability entry point,
- `ClientCore` already centralizes transport/auth behavior,
- `exceptions.py` already provides a meaningful error vocabulary.

So the BA adapter should normalize:

- what BA stages need,
- what is unsupported,
- what is degraded,
- what should remain generic SDK behavior.

It should not reimplement transport, auth refresh, or raw RPC structures.

### 4.4 It aligns with the Phase 0 gate

The revised plan's Phase 0 exit gate requires:

- a parity matrix,
- a capability adapter skeleton,
- core BA schemas,
- a run-store skeleton,
- a settled package layout.

Given the current repo shape, the only layout that plausibly satisfies that gate without later relocation churn is the dedicated `src/notebooklm_mcp/ba/` package described in section 23.3 of the revised plan.

## 5. Immediate Design Consequences for Phase 0

These are the practical consequences I would carry into `bd-yae.1.2` through `bd-yae.1.5`.

### 5.1 `bd-yae.1.2` package boundaries

`src/notebooklm_mcp/ba/` should be created as a first-class package, not as a loose helper directory. The existing MCP server should import BA registrars from that package the same way it already imports generic registrars.

### 5.2 `bd-yae.1.3` capability adapter

The adapter should wrap `NotebookLMClient`, not MCP tool handlers and not `ClientCore` directly.

Likely adapter buckets:

- source registration and ingest
- source snapshot access and metadata
- structured asks and citations
- notes/curation helpers
- settings/language parity
- artifact/report/data-table/mind-map helpers
- unsupported or experimental capability states

### 5.3 `bd-yae.1.4` models

Shared BA models should live outside generic tool payloads. The current MCP tool payload contracts are transport contracts; they are not a replacement for the BA runner's internal typed language.

### 5.4 `bd-yae.1.5` run store

The run store should be a BA subsystem concern, not something retrofitted into the current audit log or generic cache helpers. The existing MCP audit/stat/cache pieces are useful, but they solve different problems.

## 6. Test Surface Implications

The current repository already has the right testing split to extend:

- `tests/unit/test_mcp_*` for server/tools/resources/result/error/config behavior
- `tests/unit/cli/*` for CLI presentation and helper behavior
- `tests/integration/test_mcp_*` for integrated MCP behavior
- e2e and other live-service coverage under `tests/e2e/`

That existing structure supports the revised plan's recommendation to add BA-specific unit/integration suites without reorganizing the rest of the test tree.

## 7. Bottom Line

The important Phase 0 conclusion is straightforward:

1. The repository already has most of the raw NotebookLM capability the BA runner needs at the SDK layer.
2. The MCP layer is thinner and selectively exposed, which is exactly why a parity audit is necessary.
3. The clean path forward is not "grow `tools/workflows.py` again."
4. The clean path forward is a dedicated `src/notebooklm_mcp/ba/` subsystem with a capability adapter over `NotebookLMClient`, thin `ba.*` MCP entry points, and its own models/run-store/orchestration modules.
