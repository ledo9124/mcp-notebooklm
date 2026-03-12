# BA Docs Source Map

Status: preparatory source map for `bd-yae.8`  
Last updated: 2026-03-12

## Why This Exists

The docs epic `bd-yae.8` is now active, but its child leaves are not all ready for closure yet:

- `bd-yae.8.1` still depends on the end-to-end pipeline and rerun semantics
- `bd-yae.8.2` still depends on a real public `ba.*` MCP surface
- `bd-yae.8.3` still depends on fixture, golden, canary, and metrics leaves

This file is therefore not a user guide. It is a contributor-facing source map that records what the repository already implements today so later doc beads do not need to reverse-engineer the BA runner from scratch.

## Public-Surface Reality Today

- `src/notebooklm_mcp/ba/tools.py` exists, but `register_ba_tools(...)` still returns an empty mapping.
- `src/notebooklm_mcp/tools/__init__.py` registers the generic NotebookLM MCP tools, not a public `ba.*` tool family yet.
- `src/notebooklm_mcp/ba/prompts.py` already exposes five internal BA prompt templates:
  - `screen_catalog_extract`
  - `terminology_extract`
  - `canonical_screen_extract`
  - `contradiction_review`
  - `readiness_review`
- Current README and MCP docs should therefore not claim a finished BA public tool surface yet.

One adjacent nuance matters for later doc work: the generic MCP registry has already widened beyond the older README narrative and now includes generic notes, artifacts, mind-map, experimental-artifact, and settings tool modules. That is generic NotebookLM parity work, not the same thing as a workflow-native BA runner surface.

## Current BA Module Map

| Module | Current state | What later docs should do with it |
| --- | --- | --- |
| `ba.adapter` | Implemented internal capability adapter over `NotebookLMClient`, including source, note, settings, research, and artifact helpers | Use as architecture evidence in `8.1`; do not present it as a public MCP contract in `8.2` until `ba.tools` is real |
| `ba.models` | Implemented typed workflow models for sources, canonical facts, gaps, readiness, validation, run state, and run audit | Main source for workflow terminology and payload semantics in `8.1` and `8.3` |
| `ba.schema_version` | Implemented schema-family/version policy | Use in contributor docs when explaining compatibility and additive vs breaking changes |
| `ba.run_store` | Implemented run/workspace persistence layout and typed save/load helpers | Primary source of truth for the output bundle contract in `8.1` |
| `ba.fixtures` | Implemented deterministic fixture skeletons and manifests | Input to `8.3` once fixture/golden leaves land |
| `ba.prompts` | Implemented internal prompt registry with five BA prompt templates | Mention in contributor docs; keep out of public quickstarts unless prompt APIs become public |
| `ba.extraction` | Implemented structured ask parsing, terminology extraction, screen catalog extraction, canonical extraction, and citation normalization | Core workflow-stage evidence for `8.1` |
| `ba.gaps` | Implemented gap/contradiction/question classification seams | Document as part of readiness and degraded-state interpretation |
| `ba.readiness` | Implemented mode selection and per-screen readiness evaluation | Document in `8.1` as the current readiness decision layer |
| `ba.matrices` | Implemented field, action-rule, and API matrix projection | Include in bundle-contract docs and golden-test docs later |
| `ba.contracts` | Implemented provisional OpenAPI generation and deterministic mock-data generation/alignment | Document as FE-first support output, not authoritative backend truth |
| `ba.rendering` | Implemented deterministic rendering for manifest, terminology, question backlog, FE spec, BE spec, overview, readiness summary, run-audit rendering, and bundle layout assembly | Main evidence for bundle-output documentation in `8.1` |
| `ba.validation` | Partially implemented: deterministic source-quality heuristics exist, but bundle-validator and `qa-report.json` generation are still blocked on `bd-yae.6.1` | `8.1` can describe current quality heuristics; `8.3` must wait before documenting final QA-report behavior |
| `ba.reruns` | Placeholder boundary only | `8.1` and `8.3` must treat rerun semantics as pending `bd-yae.5.5` |
| `ba.tools` | Placeholder boundary only | `8.2` must wait before README/tool-reference updates claim a BA MCP surface |

## Persisted Output Contract Encoded Today

`src/notebooklm_mcp/ba/run_store.py` is the current contract source for the filesystem layout under `docs/features/<feature_key>/`.

### Feature-Level Files

| Path | Current producer | Notes |
| --- | --- | --- |
| `00-overview.md` | `ba.rendering.render_overview_markdown(...)` / `write_bundle_layout(...)` | Implemented in Phase 3 bundle assembly |
| `01-source-manifest.md` | source-manifest rendering + run-store save helpers | Implemented |
| `01-source-manifest.json` | source-manifest document persistence | Implemented |
| `02-screen-catalog.json` | screen-catalog extraction + run-store save helper | Implemented |
| `03-readiness-summary.md` | readiness-summary rendering + bundle writer | Implemented |
| `04-terminology.md` | terminology rendering + run-store save helpers | Implemented |
| `04-terminology.json` | terminology extraction + persistence | Implemented |
| `05-run-audit.json` | run-store audit persistence from run-state snapshots | Implemented and now hardened for missing-or-empty audit backfill |
| `changelog.md` | reserved by run-store path contract | Still pending rerun/changelog work in `bd-yae.5.5` |

### Per-Run Files

| Path | Current state |
| --- | --- |
| `runs/<run_id>/run-metadata.json` | Implemented |
| `runs/<run_id>/run-state.json` | Implemented |
| `runs/<run_id>/source-registration.json` | Implemented |
| `runs/<run_id>/impacted-screens.json` | Path reserved; later rerun work owns it |
| `runs/<run_id>/snapshots/...` | Implemented for persisted fulltext, guide, and quality metadata |
| `runs/<run_id>/prompts/` | Directory reserved for prompt captures |
| `runs/<run_id>/raw_responses/` | Directory reserved for raw model responses |
| `runs/<run_id>/normalized_evidence/` | Directory reserved for normalized evidence payloads |

### Per-Screen Files

| Path | Current producer | Notes |
| --- | --- | --- |
| `screens/<screen_id>/canonical.json` | canonical extraction + run-store save helper | Implemented |
| `screens/<screen_id>/field-matrix.csv` | matrix generation/rendering | Implemented |
| `screens/<screen_id>/action-rule-matrix.csv` | matrix generation/rendering | Implemented |
| `screens/<screen_id>/api-matrix.csv` | matrix generation/rendering | Implemented |
| `screens/<screen_id>/fe.md` | FE renderer + run-store save helper | Implemented |
| `screens/<screen_id>/be.md` | BE renderer + run-store save helper | Implemented |
| `screens/<screen_id>/questions.md` | question-backlog renderer + run-store save helper | Implemented |
| `screens/<screen_id>/contract.provisional.yaml` | provisional contract generation + run-store save helper | Implemented for FE-first paths |
| `screens/<screen_id>/mock-data.json` | deterministic mock-data generation + run-store save helper | Implemented |
| `screens/<screen_id>/qa-report.json` | reserved by run-store path contract | Still pending `bd-yae.6.1` |

## What Later Doc Leaves Still Need

### `bd-yae.8.1`: Workflow Guide And Output-Bundle Contract

This leaf can already draw on:

- the module boundary map in `src/notebooklm_mcp/ba/__init__.py`
- the typed workflow contracts in `ba.models`
- the persisted path contract in `ba.run_store`
- the implemented rendering/readiness/contracts seams

It should still wait for:

- `bd-yae.5.1` for final run-state-machine semantics
- `bd-yae.5.3` for a real end-to-end pipeline entry point
- `bd-yae.5.5` for accurate rerun/changelog behavior

### `bd-yae.8.2`: README, MCP Tool Reference, And Runnable Examples

This leaf should not claim a public BA MCP surface until:

- `ba.tools` registers real handlers
- those handlers are wired into the server/tool-registration path
- there is a stable invocation flow worth documenting as the primary happy path

It should also keep the distinction clear between:

- generic NotebookLM parity tools already in `src/notebooklm_mcp/tools/`
- future workflow-native `ba.*` tools that orchestrate the BA runner

### `bd-yae.8.3`: Fixtures, Canaries, Reruns, And Contributor Expectations

This leaf should wait for the hardening and rerun beads that define:

- representative fixture suites
- golden-output coverage
- upstream canary semantics
- rerun invalidation/changelog behavior
- operational metrics and evaluation reporting

Until those land, this file should be treated as the staging inventory for contributor docs rather than the final maintenance guide.

## Recommended Documentation Sequence

1. Use this file plus `docs/ba-subsystem-boundaries.md` as the current evidence base for the later workflow guide.
2. After `bd-yae.5.1`, `bd-yae.5.3`, and `bd-yae.5.5` land, write the end-to-end BA workflow narrative in `8.1`.
3. After real `ba.*` MCP handlers exist, update README and MCP tool docs in `8.2`.
4. After validation, fixtures, canaries, and metrics land, finish contributor/testing docs in `8.3`.
