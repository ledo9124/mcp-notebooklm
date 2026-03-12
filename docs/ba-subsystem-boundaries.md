# BA Subsystem Boundaries

Status: architecture note for `bd-yae.1.2`  
Last updated: 2026-03-12

## Why This Package Exists

The current MCP code already has sizable generic modules, especially `src/notebooklm_mcp/tools/workflows.py`. The BA runner should not become another pile of workflow-specific helpers inside those generic files.

The dedicated `src/notebooklm_mcp/ba/` package creates stable landing zones for later phase work:

- generic NotebookLM parity remains in existing `notebooklm_mcp.tools.*`, `resources.py`, and `prompts.py`
- BA-specific orchestration, storage, extraction, rendering, validation, and rerun logic land under `notebooklm_mcp.ba`
- future `ba.*` MCP handlers stay thin wrappers over BA package services instead of owning business logic directly

## Package Layout

| Module | Owns | Must not own |
| --- | --- | --- |
| `ba.models` | canonical BA models, enums, shared payload shapes | SDK calls, persistence, prompt text, MCP registration |
| `ba.schema_version` | schema family/version identifiers and compatibility helpers | extraction logic, rendering, transport glue |
| `ba.adapter` | normalized capability access over `NotebookLMClient` | MCP handlers, persistence, rendering, prompt text |
| `ba.run_store` | run directory layout and stored artifact IO | SDK access, prompt composition, transport glue |
| `ba.fixtures` | deterministic BA fixtures and loaders | production workflow logic or live NotebookLM calls |
| `ba.prompts` | BA-specific prompt templates and registry helpers | SDK parity logic, persistence, rendering |
| `ba.extraction` | evidence-to-fact extraction and canonicalization | transport glue, raw persistence, final rendering |
| `ba.rendering` | deterministic bundle rendering and output layout | SDK access, prompt selection, validation policy |
| `ba.validation` | bundle validation, invariants, QA reporting hooks | NotebookLM access, prompt generation, rerun planning |
| `ba.reruns` | impact analysis and selective rerun planning | prompt text, raw persistence mechanics, MCP glue |
| `ba.tools` | future `ba.*` MCP registrations and thin wrappers | business logic that belongs in adapter/extraction/rendering/etc. |

## Dependency Rules

1. `ba.tools` and any later BA transport layer may depend inward on the rest of `notebooklm_mcp.ba`; the inner modules should not depend outward on MCP handler modules.
2. `ba.adapter` may depend on the `notebooklm` SDK surface and generic shared helpers, but it should not import `notebooklm_mcp.tools.*` handlers.
3. `ba.run_store` owns local persistence concerns for BA runs. Other BA modules should use it rather than inventing their own storage layout.
4. `ba.prompts` owns BA prompt text. Extraction and rendering code should consume prompt registries or prompt outputs, not hard-code prompt strings inline.
5. Generic NotebookLM parity additions that are not BA-specific still belong in the existing generic MCP modules.

## Fill-In Order

- `bd-yae.1.3`: fill in `ba.adapter`
- `bd-yae.1.4`: fill in `ba.models` and `ba.schema_version`
- `bd-yae.1.5`: fill in `ba.run_store` and `ba.fixtures`
- later extraction/rendering/validation/rerun beads: fill in the remaining BA workflow modules
- later public-surface bead: wire `ba.tools` into a real `ba.*` MCP surface

## Intentional Non-Goals For This Bead

- No new BA workflow behavior is wired into the existing server yet.
- No generic MCP modules are expanded just to host BA placeholders.
- No attempt is made to pre-implement the capability adapter, schema rules, or run store before their dedicated beads.
