# NotebookLM MCP Upgrade — Evidence-First BA Implementation Pack Runner

**Version:** 2.0  
**Date:** 2026-03-07  
**Scope:** Upgrade the MCP from a generic NotebookLM chat surface into a workflow-native, evidence-first BA-to-implementation runner that can reliably turn BA PDFs and supporting sources into implementation bundles for FE, BE, and clarification.

---

## 1. Executive Summary

The right upgrade is **not** to build another generic NotebookLM wrapper. `notebooklm-py` already provides a broad programmatic surface across notebooks, sources, chat, research, notes, artifacts, downloads, and multiple interfaces (async Python API, CLI, agent skills). Official NotebookLM already provides grounded answers with citations, source selection, output language, notes, and Studio artifacts such as mind maps, video overviews, slide decks, and more. The real gap for the BA-PDF workflow is the absence of a **workflow-native orchestration layer** that can transform those primitives into a deterministic, evidence-first implementation pack. citeturn4view2turn6search5turn3search1turn3search3

The target state is a single-user, non-sharing MCP that behaves like a **BA Implementation Pack Runner**. It takes a feature’s BA PDF and supporting sources, chooses the correct delivery mode, extracts grounded facts into a canonical model, generates FE and BE implementation docs, produces provisional contracts and mock data where appropriate, validates the output, and supports incremental reruns when sources change.

This revised plan adopts the strongest ideas from all three competing proposals while correcting their weaknesses:

- It keeps the **strategic realism** that the foundation already exists and the missing piece is orchestration.
- It keeps the **engineering rigor** of typed schemas, state machines, tests, risks, and acceptance criteria.
- It keeps the **operational simplicity** of pushing waiting, parse-quality checks, and structured evidence extraction into the MCP so agents do less manual glue work.
- It avoids **surface-area sprawl** by separating a small set of P0 workflow tools from a broader parity/expert layer instead of turning every helper into a first-class public tool.
- It explicitly optimizes for **real-world FE-first delivery** while still supporting balanced and clarification-first execution.

---

## 2. Reality Check: What Already Exists vs. What Is Missing

### 2.1 What already exists

`notebooklm-py` is already a substantial toolkit, not a toy wrapper. The public repository describes it as a comprehensive Python API for Google NotebookLM with full programmatic access, including async workflows, CLI automation, agent skills, source ingest, chat, research, downloads/export, note handling, source fulltext access, and broad Studio artifact generation. The README also claims complete content generation coverage across Audio Overview, Video Overview, Slide Deck, Infographic, Quiz, Flashcards, Report, Data Table, and Mind Map, plus extra capabilities beyond the web UI such as batch downloads, mind map JSON extraction, data-table export, and save-chat-to-notes. citeturn1view0turn2view2turn2view4turn4view3turn4view5

Official NotebookLM already provides the product primitives the workflow needs:
- grounded chat with inline citations and source filtering,
- static-copy source semantics with explicit resync behavior for Drive and manual re-upload for other file types,
- notes, including the ability to create a new source from existing notes,
- output language settings,
- Studio artifacts such as mind maps, video overviews, slide decks, infographics, and audio overviews. citeturn6search5turn5search0turn6search2turn3search1turn3search3turn6search9turn5search14

The current `notebooklm-mcp` repository visible on GitHub, however, appears much narrower in its documented tool surface. Its README prominently shows a small set of chat/notebook tools rather than the full breadth described in `notebooklm-py`. That makes a **parity audit** a first-order task rather than an assumption. citeturn8view0turn8view2

### 2.2 What is actually missing for the BA-PDF workflow

The missing piece is a **deterministic orchestration layer** that enforces the following workflow contract:

1. sources are typed, prioritized, snapshotted, and quality-assessed;
2. facts are extracted into a canonical schema with evidence and status;
3. FE and BE documents are rendered from the same canonical layer;
4. readiness, blockers, contradictions, and open questions are computed explicitly;
5. FE-first runs emit provisional contracts and mock data;
6. QA checks catch incompleteness, inconsistency, and drift;
7. changed-source reruns target only impacted screens.

That orchestration layer should treat NotebookLM as the grounding and generation engine, but it should **not** let raw NotebookLM prose become the final source of truth.

---

## 3. Goals, Non-Goals, and Design Position

### 3.1 Goals

1. **Minimize manual steps for the agent.**  
   Waiting, polling, quality checks, source typing, structured extraction, and bundle rendering should happen in the MCP rather than in agent prompt glue.

2. **Preserve evidence-first traceability.**  
   Every important confirmed fact must carry source, locator, status, and confidence. No final FE or BE spec may exist without a canonical layer behind it.

3. **Enable safe FE-first execution.**  
   FE must be able to start when BE is incomplete, provided the system can explicitly mark provisional contracts, assumptions, blockers, and unresolved questions.

4. **Support real-world change.**  
   BA documents change. The workflow must support snapshots, diffs, impacted-screen reruns, and changelogs.

5. **Keep the MCP practical to maintain.**  
   Expose a clean workflow surface for agents while still closing parity gaps with the underlying SDK.

### 3.2 Non-goals

1. Sharing, multi-user collaboration, permission workflows, or public-notebook workflows.
2. Generic web research filling requirement gaps by default.
3. Treating provisional contracts as official contracts.
4. Writing final FE or BE docs directly from raw NotebookLM chat answers.
5. Building a heavy UI or desktop product as part of this effort.
6. OCR-first workflows; OCR remains a last resort, not the happy path.

### 3.3 Design position

The MCP should be upgraded in **two coordinated tracks**:

- **Track A — Parity and hardening:** expose the non-sharing `notebooklm-py` capabilities required by the workflow and make them reliable to call.
- **Track B — BA workflow engine:** implement the evidence-first pipeline that turns NotebookLM primitives into implementation packs.

This is the correct middle path between “just expose more chat tools” and “build an entirely separate product that ignores the underlying capabilities already present.”

---

## 4. Core Principles

### 4.1 Evidence-first
No important fact is accepted without explicit evidence. For confirmed facts, evidence is mandatory. For inferred or provisional facts, the inference basis and risk must be explicit.

### 4.2 Canonical-first
`fe.md`, `be.md`, contracts, mock data, readiness summaries, and question backlogs are rendered from canonical data structures, not from ad hoc LLM prose.

### 4.3 Workflow-native
The MCP should represent the BA workflow as a first-class product surface. Agents should not need to manually remember step order, halt conditions, or prompt templates.

### 4.4 FE-first but mode-aware
The system should support:
- `BALANCED`
- `FE_FIRST`
- `CLARIFICATION_FIRST`
- `AUTO`

`AUTO` should default with an FE-first bias when backend contracts are missing or unstable, but it must record the selected mode explicitly in every run output.

### 4.5 Narrow-context extraction
The system should use source subsets and screen-scoped extraction wherever possible. This lowers hallucination risk and aligns with NotebookLM’s own source-selection and retrieval model. citeturn6search5turn6search6

### 4.6 Deterministic rendering
LLM output may help extract facts or draft intermediates, but final bundle rendering must be deterministic and schema-driven.

### 4.7 Graceful degradation
When NotebookLM output is partially parseable, the system should return degraded structured outputs plus the raw answer, not crash or silently invent structure.

### 4.8 Real-world maintainability
Prefer a moderate, semantically meaningful public tool surface. Keep low-level helpers internal unless exposing them materially reduces agent complexity.

---

## 5. Target Product Definition

The upgraded MCP should behave like a **BA Implementation Pack Runner**.

### 5.1 Input
- one primary BA PDF or equivalent primary requirement source;
- zero or more supporting sources such as glossary, business rules, design, technical notes, API drafts, or clarifications;
- optional mode override;
- optional notebook lifecycle policy and output location.

### 5.2 Output
A run should generate a consistent bundle under:

```text
docs/features/<feature_key>/
  00-overview.md
  01-source-manifest.md
  01-source-manifest.json
  02-screen-catalog.json
  03-readiness-summary.md
  04-terminology.md
  05-run-audit.json
  changelog.md
  screens/
    <screen_id>/
      canonical.json
      fe.md
      be.md
      questions.md
      field-matrix.csv
      action-rule-matrix.csv
      api-matrix.csv
      contract.provisional.yaml
      mock-data.json
      qa-report.json
  runs/
    <run_id>/
      snapshots/
      prompts/
      raw_responses/
      normalized_evidence/
      impacted-screens.json
```

### 5.3 Success definition
A single run should be able to produce the full output tree, with every final document traceable back to canonical data and every confirmed fact traceable to evidence.

---

## 6. Recommended Public MCP Surface

The public MCP surface should be split into **two tiers**.

## 6.1 Tier A — P0 workflow tools (small, high-value, workflow-native)

These are the tools most agents should use most of the time.

### Run lifecycle
- `ba.start_run`
- `ba.status`
- `ba.run_pipeline`
- `ba.rerun_impacted`

### Source intelligence
- `ba.register_sources`
- `ba.ingest_and_wait`
- `ba.snapshot_sources`
- `ba.assess_source_quality`
- `ba.build_source_manifest`

### Extraction and synthesis
- `ba.normalize_terminology`
- `ba.build_screen_catalog`
- `ba.extract_canonical`
- `ba.review_gaps`
- `ba.evaluate_readiness`
- `ba.generate_matrices`

### Contracts and rendering
- `ba.generate_contracts`
- `ba.render_bundle`
- `ba.validate_bundle`

These tools should map closely to the workflow contract instead of forcing agents to manually orchestrate low-level NotebookLM operations.

## 6.2 Tier B — parity / expert tools (broader access, not the default happy path)

These include:
- notebook CRUD;
- source add/list/get/delete/refresh/fulltext/guide/freshness;
- structured ask helpers;
- note creation/export/source conversion;
- research controls;
- settings and output language;
- artifact generation/download/export across reports, data tables, quizzes, flashcards, mind maps, slide decks, infographics, audio, and video.

This tier exists for completeness and power use, but it should not distract from the main workflow.

---

## 7. Detailed Tool Design

## 7.1 `ba.start_run`

**Purpose:** bootstrap a feature-level run with explicit metadata and defaults.

**Input**
- `feature_key`
- `mode`: `AUTO | BALANCED | FE_FIRST | CLARIFICATION_FIRST`
- `output_dir`
- `notebook_lifecycle`: `REUSE_FEATURE_NOTEBOOK | EPHEMERAL_RUN_NOTEBOOK`
- `assumption_profile`: optional freeform assumptions such as `backend_exists`, `contract_stability`, `target_platforms`

**Output**
- `run_id`
- `resolved_output_dir`
- `mode_requested`
- `notebook_lifecycle`
- `run_metadata_path`

**Rules**
- Create run root structure.
- Persist all mode assumptions.
- Do not ingest sources yet.

---

## 7.2 `ba.register_sources`

**Purpose:** ingest the user’s source intent into a typed manifest before the pipeline runs.

**Input**
- list of `{path_or_url_or_text, source_key, source_type, priority, notes}`
- allowed `source_type` values:
  - `PRIMARY_REQUIREMENT`
  - `PRIMARY_CONTRACT`
  - `SUPPORTING_GLOSSARY`
  - `SUPPORTING_RULE`
  - `SUPPORTING_DESIGN`
  - `SUPPORTING_TECH`
  - `SUPPORTING_CLARIFICATION`
  - `SUPPORTING_DECISION`
  - `OPTIONAL_CONTEXT`

**Output**
- normalized source manifest rows
- validation warnings
- missing-critical-source warnings

**Rules**
- Require at least one `PRIMARY_REQUIREMENT` unless the run is explicitly marked as update-only.
- Preserve stable `source_key` values across reruns.

---

## 7.3 `ba.ingest_and_wait`

**Purpose:** collapse upload + polling + readiness into one MCP call.

**Input**
- `run_id`
- source selection or all un-ingested sources
- `poll_budget_seconds`
- `ready_timeout_policy`: `FAIL | DEGRADE`

**Output**
- notebook source IDs
- ingestion statuses
- readiness status per source
- elapsed polling details

**Rules**
- Poll until sources are usable or the budget is exhausted.
- On timeout, return explicit source-level degraded states rather than silently proceeding.

This directly eliminates one of the most annoying manual burdens in current agent workflows.

---

## 7.4 `ba.snapshot_sources`

**Purpose:** create versioned, auditable source snapshots.

**Input**
- `run_id`
- `include_fulltext`: bool
- `include_guide`: bool
- `include_freshness`: bool

**Output**
- `snapshot_id` per source
- snapshot metadata
- stored locations

**Rules**
- Capture the fulltext used for extraction, not just current live source references.
- Persist source guide/freshness when available.
- Compute content hash for later diffing.

---

## 7.5 `ba.assess_source_quality`

**Purpose:** determine whether a source is safe to build implementation facts from.

**Input**
- `run_id`
- source selection or all current snapshots

**Output**
- `parse_quality`: `HIGH | MEDIUM | LOW | FAILED`
- diagnostics:
  - character count
  - heading count
  - table density
  - encoding issues
  - suspected scan/garble indicators
  - missing sections
- halt recommendation

**Rules**
- Primary requirement sources with `LOW` or `FAILED` quality should force either `CLARIFICATION_FIRST` or an explicit degraded run path.
- Quality logic should be lightweight, deterministic, and testable.

---

## 7.6 `ba.build_source_manifest`

**Purpose:** generate the authoritative source manifest for the run.

**Output artifacts**
- `01-source-manifest.md`
- `01-source-manifest.json`

**Manifest fields**
- `source_key`
- `source_type`
- `priority`
- `notebook_source_id`
- `snapshot_id`
- `parse_quality`
- `freshness`
- `status`
- `notes`
- `used_in_screens`

This tool should be authoritative for later audits.

---

## 7.7 `ba.normalize_terminology`

**Purpose:** stabilize vocabulary before screen extraction begins.

**Input**
- relevant source subset
- optional existing glossary

**Output**
- `04-terminology.md`
- `terminology.json`

**Fields**
- standard term
- aliases
- semantic notes
- source evidence
- ambiguity flags

**Rules**
- Terms should not be normalized without evidence.
- Conflicting business terms should generate an explicit ambiguity item.

---

## 7.8 `ba.build_screen_catalog`

**Purpose:** identify the screens, flows, roles, entry points, exits, and major actions for the feature.

**Input**
- `run_id`
- source subset
- optional candidate screen hints

**Output**
- `02-screen-catalog.json`

**Screen object**
- `screen_id`
- `screen_name`
- `purpose`
- `roles`
- `entry_points`
- `exit_points`
- `main_actions`
- `dependencies`
- `related_sources`
- `evidence`
- `open_questions`

**Rules**
- Use stable `screen_id` generation.
- Preserve catalog history so reruns can diff screen-level change.
- Do not treat vague mentions as definitive screens without evidence.

---

## 7.9 `ba.extract_canonical`

**Purpose:** create the canonical per-screen truth layer.

**Input**
- `run_id`
- `screen_id`
- source subset
- mode
- optional per-screen override

**Output**
- `screens/<screen_id>/canonical.json`

**Canonical schema**
- `schema_version`
- `feature_key`
- `screen_id`
- `mode`
- `run_id`
- `shared_facts`
- `fe_facts`
- `be_facts`
- `dependencies`
- `contradictions`
- `missing_info`
- `open_questions`
- `quality_summary`

**Fact schema**
- `fact_id`
- `domain`: `SHARED | FE | BE`
- `category`
- `value`
- `status`: `CONFIRMED | PROVISIONAL | MISSING | CONTRADICTED | INFERRED`
- `confidence`
- `evidence`: list of
  - `source_key`
  - `snapshot_id`
  - `locator`
  - `quote`
- `note`

**Rules**
- `CONFIRMED` facts require evidence.
- `PROVISIONAL` facts require rationale and origin.
- `INFERRED` facts must never masquerade as confirmed requirements.
- Contradictions should preserve both conflicting claims, not collapse them prematurely.

This tool is the heart of the system.

---

## 7.10 `ba.review_gaps`

**Purpose:** classify blockers, questions, contradictions, and assumptions.

**Output**
- FE blockers
- BE blockers
- shared blockers
- non-blockers
- required assumptions
- contradiction backlog
- question backlog with owner and severity

**Rules**
- Do not collapse everything into “not enough info.”
- Separate:
  - missing requirement detail,
  - contradictory requirement detail,
  - missing backend contract,
  - FE-visible BE dependency,
  - implementation detail deferred by design.

---

## 7.11 `ba.generate_matrices`

**Purpose:** generate structured matrices without making the agent hand-assemble them.

**Outputs**
- `field-matrix.csv`
- `action-rule-matrix.csv`
- `api-matrix.csv`

**Rules**
- Prefer structured generation from canonical + focused extraction, optionally assisted by NotebookLM data-table generation.
- Matrix rows must remain traceable to evidence.
- Data-table artifact usage is allowed as a draft mechanism, but the saved CSVs should pass schema validation before publish.

---

## 7.12 `ba.evaluate_readiness`

**Purpose:** convert extracted facts and gap analysis into explicit execution readiness.

**Output**
- per-screen FE readiness
- per-screen BE readiness
- overall feature readiness
- final decision enum:
  - `READY_FOR_FE_AND_BE`
  - `READY_FOR_FE_WITH_PROVISIONAL_CONTRACT`
  - `PARTIAL_READY_NEEDS_CLARIFICATION`
  - `NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS`

**Rules**
- Mode must be explicit in the summary.
- The feature-level mode may be overridden per screen if reality differs across screens.
- That means the system can support a **hybrid run** where some screens are balanced and others FE-first, while the feature-level decision still remains coherent.

This per-screen override mechanism is a practical upgrade over all three competing plans.

---

## 7.13 `ba.generate_contracts`

**Purpose:** emit provisional contracts and mock payloads where FE-first execution requires them.

**Output**
- `contract.provisional.yaml`
- `mock-data.json`

**Contract rules**
- OpenAPI 3.0.3
- provisional endpoints/fields marked explicitly
- preserve uncertainty via vendor extensions, for example:
  - `x-contract-status`
  - `x-field-status`
  - `x-source-evidence`
  - `x-open-questions`

**Mock-data rules**
- deterministic fixture generation
- include at least:
  - `happy_path`
  - `validation_error`
  - `empty_state`
  - `server_error`
- align strictly with the provisional contract

**Important**
- provisional contracts are generated only when useful;
- they are never mislabeled as approved backend contracts.

---

## 7.14 `ba.render_bundle`

**Purpose:** deterministically render the output docs from canonical data.

**Rendered files**
- `00-overview.md`
- `03-readiness-summary.md`
- per-screen `fe.md`
- per-screen `be.md`
- per-screen `questions.md`

**Rendering rules**
- final docs are rendered only from:
  - canonical JSON,
  - matrices,
  - readiness output,
  - question backlog,
  - terminology map,
  - source manifest
- raw NotebookLM prose can appear only inside clearly marked draft or evidence excerpts, never as unvetted final requirement text

---

## 7.15 `ba.validate_bundle`

**Purpose:** perform bundle QA and self-correction before publish.

**Checks**
1. no `fe.md` without `canonical.json`
2. no `be.md` without `canonical.json`
3. every confirmed fact has evidence
4. contradiction statuses are consistent
5. FE doc facts match FE canonical facts
6. BE doc facts match BE canonical facts
7. provisional contract aligns with mock data
8. blockers match final readiness decision
9. unanswered critical questions prevent overconfident “ready” outcomes
10. changed-source rerun metadata is recorded
11. terminology use is internally consistent
12. source manifest coverage is complete
13. output files exist where mode requires them

**Output**
- `qa-report.json`
- pass/fail/warning summary

**Rules**
- validation failures should block publish unless explicitly overridden.
- self-correction may repair formatting or deterministic consistency errors, but may not invent missing evidence.

---

## 7.16 `ba.run_pipeline`

**Purpose:** one-call workflow entry point.

This macro should execute:
1. `start_run`
2. `register_sources`
3. `ingest_and_wait`
4. `snapshot_sources`
5. `assess_source_quality`
6. `build_source_manifest`
7. `normalize_terminology`
8. `build_screen_catalog`
9. per-screen `extract_canonical`
10. `review_gaps`
11. `generate_matrices`
12. `evaluate_readiness`
13. `generate_contracts`
14. `render_bundle`
15. `validate_bundle`

**Rules**
- return step-level progress and state
- expose halt reason if interrupted
- support dry-run mode that stops after readiness assessment

---

## 7.17 `ba.rerun_impacted`

**Purpose:** update only what changed after source updates.

**Mechanism**
- compare old and new source snapshots;
- identify changed sections and terms;
- map them to candidate screens using screen catalog, terminology map, and previous evidence links;
- rerun only impacted screens plus any dependent summaries.

**Outputs**
- `impacted-screens.json`
- `changelog.md`
- rerun report

---

## 8. Internal Architecture

The revised architecture should contain the following components.

### 8.1 Capability Adapter
A thin semantic adapter that maps workflow intent to whichever exact SDK/CLI/MCP methods exist in the current host.

Examples:
- `source_add`
- `source_fulltext`
- `source_guide`
- `source_freshness`
- `ask`
- `generate_report`
- `generate_data_table`
- `create_note`
- `save_chat_to_note`
- `download_mind_map`

This isolates the workflow layer from upstream naming or transport changes.

### 8.2 Schema Layer
Shared Pydantic models for:
- source manifest rows,
- terminology entries,
- screen catalog objects,
- evidence objects,
- canonical fact envelopes,
- blockers,
- readiness summaries,
- matrix rows,
- contract metadata.

All renderers and validators must consume the same models.

### 8.3 Run Store
A persistent store for:
- source snapshots,
- raw NotebookLM responses,
- normalized evidence,
- rendered outputs,
- audit events,
- changed-screen mappings.

Default storage: local filesystem + lightweight index.  
Future extension: pluggable remote storage, but not P0.

### 8.4 Prompt Registry / Preset Library
Named templates for high-repeat workflow tasks, such as:
- `extract_screen_facts`
- `extract_fe_facts`
- `extract_be_facts`
- `check_contradictions`
- `review_readiness`
- `render_fe_spec_draft`
- `render_be_spec_draft`
- `self_check_bundle`

This preserves reproducibility and reduces prompt sprawl.

### 8.5 Orchestrator / State Machine
A step-based execution engine with:
- explicit states,
- halt conditions,
- degraded states,
- retries,
- resumability.

### 8.6 Renderer
A deterministic renderer for markdown, YAML, JSON, and CSV outputs.

### 8.7 QA Engine
A validator and consistency checker that can repair deterministic issues without inventing facts.

### 8.8 Change Detector
A diff engine over snapshots plus evidence links for incremental reruns.

---

## 9. Mode Logic

### 9.1 Supported modes
- `BALANCED`
- `FE_FIRST`
- `CLARIFICATION_FIRST`
- `AUTO`

### 9.2 Auto-selection logic
If mode is `AUTO`, resolve in this order:

1. if any primary requirement source is `LOW` or `FAILED` parse quality, or if contradictions are severe and central:
   - choose `CLARIFICATION_FIRST`
2. else if backend existence is unknown, contract sources are absent, or key FE-visible BE interactions are underspecified:
   - choose `FE_FIRST`
3. else:
   - choose `BALANCED`

### 9.3 Per-screen override
Even when the feature-level mode is chosen, the system may downgrade or upgrade specific screens. This is useful in real product delivery where:
- Account Summary might be balanced,
- Create Customer might be FE-first,
- Approval Screen might be clarification-first.

The feature summary should report both:
- feature default mode,
- screen-level deviations.

This improves delivery realism substantially.

---

## 10. Notebook Lifecycle and Storage Policy

### 10.1 Default policy
Default to **one notebook per feature_key**, reused across runs, because:
- it preserves source continuity,
- reduces redundant upload overhead,
- supports change-aware iteration.

### 10.2 Optional isolation policy
Support `EPHEMERAL_RUN_NOTEBOOK` for:
- test fixtures,
- debugging,
- highly sensitive change isolation,
- reproducibility investigations.

### 10.3 Source of truth
Local output files and run-store snapshots are the authoritative source of truth for the workflow. Notebook notes may be used as a convenient collaboration/curation layer, but they are **not** the authoritative published artifact set.

This resolves the ambiguity in the competing plans around whether final documents should live in NotebookLM or only on disk.

---

## 11. Notes as a Curated Source Loop

Notes are too valuable to ignore, but too risky to leave informal.

Official NotebookLM notes can capture synthesis and even be turned into a new source. That should be used as a **controlled curation loop**: clarifications, tech-lead decisions, BA answers, and manual overrides can be captured as notes and then reintroduced as typed supporting sources such as `SUPPORTING_CLARIFICATION` or `SUPPORTING_DECISION`. citeturn6search2turn4view4

Rules:
1. no undocumented memory in the pipeline;
2. every manual override becomes a source-backed artifact;
3. note-derived sources are tagged distinctly from original BA requirements;
4. note-derived sources may resolve ambiguity but must not silently overwrite primary-source contradictions.

This is one of the highest-leverage real-world workflow improvements.

---

## 12. Artifact Strategy

Artifacts should not all be treated equally.

### 12.1 P0 workflow artifacts
- notes
- reports (drafting assistance only)
- data tables

These directly help the BA-to-implementation workflow.

### 12.2 P1 helpful but non-blocking artifacts
- mind maps

Mind maps can be useful for topic coverage checks or onboarding, but are not core to implementation-pack generation.

### 12.3 P2 parity / experimental artifacts
- video overviews
- audio overviews
- slide decks
- infographics

These should be exposed for parity and completeness, but they should remain off the critical path for the BA implementation workflow. Video overviews in particular can be long-running and are explicitly background-generated in NotebookLM help documentation, which makes them poor critical-path dependencies. citeturn3search0turn6search9turn5search14turn3search15

### 12.4 Experimental flagging
Any parity feature that depends on unstable or poorly documented upstream behavior should be marked `experimental` until proven reliable in this repo.

---

## 13. Structured Ask Strategy

Structured extraction is necessary, but the system should not assume NotebookLM will always emit perfect JSON.

### 13.1 Public structured ask surface
Add:
- `nlm.ask_structured`
- `nlm.ask_multi`

### 13.2 Robust parsing sequence
For structured responses:
1. parse as-is
2. extract fenced JSON if present
3. extract first valid JSON object/array span
4. if still invalid, return degraded output:
   - `quality = DEGRADED`
   - `raw_text`
   - best-effort partial parse if safe

### 13.3 Citation handling
Keep citations in machine-readable form whenever available. Where NotebookLM only returns human-facing citations, normalize them into a stable evidence object linked to the current snapshot.

### 13.4 Narrow-question discipline
Prefer multiple smaller structured asks scoped to:
- screen,
- concern area,
- source subset,
rather than one giant prompt that asks for everything at once.

This combines the strongest parts of the Claude and Gemini plans.

---

## 14. Output Contracts and Rendering Rules

### 14.1 `fe.md`
Must include:
- screen purpose and user intent
- states
- fields and validations
- actions
- visible business rules
- API dependencies or provisional contract references
- loading/error/empty states
- open FE questions
- explicit provisional markers where applicable

### 14.2 `be.md`
Must include:
- entities and relationships
- workflow/state transitions
- endpoints/events/jobs
- permissions/authz if available
- data validation and rules
- non-functional notes if evidenced
- open BE questions
- contradictions and provisional areas

### 14.3 `questions.md`
Must aggregate:
- `MISSING`
- `CONTRADICTED`
- `QUESTION_FOR_BA`
- `QUESTION_FOR_TECH_LEAD`
- `QUESTION_FOR_DESIGN`

### 14.4 `00-overview.md`
Must include:
- feature metadata
- selected mode and why
- source health summary
- screen inventory
- run history summary
- terminology highlights
- final decision

### 14.5 `03-readiness-summary.md`
Must explain:
- feature-level decision,
- screen-level readiness,
- blockers by owner,
- assumptions required for FE-first execution,
- rerun recommendation if degraded.

---

## 15. Incremental Reruns

This workflow will only be pleasant in practice if reruns are cheap.

### 15.1 Snapshot diffing
Each rerun should compare:
- content hashes,
- section headings,
- changed spans,
- terminology changes.

### 15.2 Impact mapping
Map diffs to screens using:
- screen catalog references,
- prior evidence links,
- matrix references,
- terminology matches.

### 15.3 Selective rerun policy
Rerun:
- impacted screens,
- feature readiness summary,
- overview,
- any contracts or matrices for impacted screens.

Avoid rerunning the whole feature unless:
- source quality degraded,
- screen catalog changed materially,
- terminology changes are cross-cutting,
- a primary requirement source was replaced wholesale.

### 15.4 Changelog
Emit a human-readable changelog summarizing:
- which sources changed,
- which screens changed,
- what decisions changed,
- what remains provisional.

---

## 16. Testing Strategy

The strongest engineering idea in the competing plans is that this project needs real test scaffolding, not just hopeful prompting. That should stay.

### 16.1 Test layers

**Unit tests**
- quality heuristics
- diff logic
- schema validation
- renderer correctness
- contract/mock alignment

**Fixture-driven integration tests**
- realistic synthetic BA PDFs
- supporting sources with known contradictions
- FE-first and balanced scenarios
- degraded parse cases

**Golden-file tests**
- canonical JSON
- rendered FE/BE docs
- readiness summaries
- changelogs

**Upstream canary tests**
- smoke tests against the current `notebooklm-py` + NotebookLM path to detect API drift early

### 16.2 Required fixtures

Create fixture sets for:
1. clean BA PDF with stable API contract
2. BA PDF with no backend contract
3. contradictory BA + rule source
4. scanned/garbled PDF
5. changed-source rerun case
6. note-derived clarification case

### 16.3 Acceptance criteria

The upgrade is successful when all of the following are true:

1. one pipeline run can produce the full output tree;
2. no final FE or BE doc is published without canonical data;
3. every confirmed fact is evidence-backed;
4. FE-first runs always produce a provisional contract and aligned mock data when backend interaction is present;
5. contradictory or degraded inputs automatically lower readiness outcomes;
6. incremental reruns touch only impacted screens unless escalation criteria are met;
7. the bundle validator passes with zero failures for gold fixtures;
8. manual post-editing effort is materially reduced versus the current workflow.

### 16.4 Operational success metrics

In addition to technical tests, track:
- average manual edits per screen,
- false blocker rate,
- rerun scope reduction percentage,
- time-to-first-FE-spec,
- number of ungrounded facts caught by QA,
- percentage of screens delivered in FE-first mode without later contract breakage.

This operational layer is necessary for real-world success, not just repository cleanliness.

---

## 17. Risk Register

| Risk | Why it matters | Mitigation |
|---|---|---|
| Upstream NotebookLM / undocumented API drift | Both `notebooklm-py` and MCP integrations depend on unofficial or changing surfaces. | Capability adapter, version pinning where possible, upstream canary tests, graceful degradation. |
| JSON extraction unreliability | Structured extraction is the heart of the workflow. | Multi-step parsing fallback, degraded responses, raw-text retention, schema validation. |
| Poor BA PDF parse quality | Garbled sources can poison the whole run. | Mandatory source quality checks, halt/downgrade rules, clarification-first fallback. |
| Over-tooling / surface sprawl | Too many thin tools increase maintenance and confuse agents. | Two-tier tool model; keep P0 public surface small and semantically meaningful. |
| Overconfidence in provisional contracts | FE may treat placeholders as approved backend truth. | Strong provisional labeling, explicit readiness language, contract status extensions, questions backlog. |
| Long-running artifact generation | Some Studio artifacts are background and slow. | Keep non-core artifacts off the critical path; mark experimental or optional. |
| Notebook drift across long-lived feature notebooks | Reused notebooks can accumulate stale context. | Snapshot every run; persist exact source set; optional ephemeral notebook mode. |
| Storage growth from snapshots | Fulltext snapshots can grow quickly. | Retention policy, compression, cleanup command, content-hash dedupe. |
| Sensitive business documents | BA PDFs may contain sensitive information. | Local-first storage, non-sharing default, explicit no-collab scope, audit logs. |

The upstream instability concern is not hypothetical; the `notebooklm-py` README explicitly warns that it uses undocumented Google APIs that can change without notice. citeturn1view0turn2view2

---

## 18. Implementation Phases

### Phase 0 — Capability audit and foundation
Before building new workflow tools, audit current MCP parity against the actual `notebooklm-py` surface used by the BA workflow:
- source fulltext / guide / freshness,
- notes and notes-to-source behavior,
- output language,
- data table export,
- mind map export,
- report generation,
- research controls.

Deliverables:
- parity matrix,
- capability adapter skeleton,
- schema module skeleton,
- run-store skeleton.

### Phase 1 — Source intelligence
Implement:
- source registration,
- ingest-and-wait,
- snapshotting,
- parse quality,
- source manifest.

This is the minimum safe foundation for the workflow.

### Phase 2 — Canonical extraction core
Implement:
- terminology normalization,
- screen catalog,
- canonical extraction,
- contradiction and gap review,
- structured ask helpers.

This is where the MCP stops being “generic NotebookLM access” and becomes workflow-aware.

### Phase 3 — Deterministic rendering and FE-first delivery
Implement:
- matrices,
- FE/BE renderers,
- questions backlog,
- readiness summary,
- provisional contracts,
- mock data.

This directly unlocks the FE-first business value.

### Phase 4 — Orchestration and incremental reruns
Implement:
- pipeline macro,
- status/state machine,
- impacted-screen reruns,
- changelog generation.

### Phase 5 — QA, evaluation, and hardening
Implement:
- bundle validator,
- self-correction loop,
- fixture suite,
- canary suite,
- operational metrics instrumentation.

### Phase 6 — Parity completion and optional artifacts
Expose remaining non-sharing parity features and mark non-core or unstable ones as optional/experimental rather than blocking the workflow.

This phase ordering preserves both practicality and value delivery.

---

## 19. Work Breakdown Summary

### 19.1 Foundation
- create shared schemas
- implement run-store and audit model
- build capability adapter
- publish parity matrix

### 19.2 Source intelligence
- typed source registration
- ingest-and-wait orchestration
- fulltext/guide/freshness snapshotting
- parse-quality heuristics
- manifest rendering

### 19.3 Extraction
- prompt registry
- screen catalog extraction
- canonical extraction
- contradiction detection
- readiness precursor logic

### 19.4 Rendering
- FE renderer
- BE renderer
- question backlog renderer
- contract generator
- mock-data generator
- matrix emitters

### 19.5 Orchestration
- pipeline macro
- state machine
- progress/status surface
- rerun impact analyzer
- changelog writer

### 19.6 QA
- bundle validator
- consistency repair
- test fixtures
- canary tests
- golden-file tests

### 19.7 Optional parity
- notes/source conversion helpers
- output language control
- report/data-table helpers
- mind map export
- optional video/audio/slide/infographic tools

---

## 20. Explicit Decisions That Close Open Questions

The competing plans raised several open questions. The revised plan resolves them as follows:

### 20.1 Notebook lifecycle
**Decision:** default to one feature notebook reused across runs, with optional ephemeral notebooks for isolation.

### 20.2 Storage backend
**Decision:** local-first run store is P0; remote backends are deferred behind an abstraction.

### 20.3 Final artifact location
**Decision:** filesystem outputs are authoritative; NotebookLM notes are optional mirrors or curated sources, not the publication source of truth.

### 20.4 Mind map / artifact stability
**Decision:** parity exposure is fine, but any feature that depends on unstable or hard-to-parse upstream behavior is marked experimental and kept off the critical path.

### 20.5 Extraction granularity
**Decision:** prefer narrow, screen-scoped, concern-scoped extraction over single giant asks; reserve larger composite asks for convenience only where empirically reliable.

These decisions make the plan immediately actionable.

---

## 21. Why This Hybrid Plan Is Better

This revised plan is stronger because it combines:
- the **strategic accuracy** of recognizing that NotebookLM access itself is not the main missing piece,
- the **architectural rigor** of schema-first extraction, renderers, state machines, QA, and risk management,
- the **practical workflow focus** of source ingest orchestration, parse quality checks, and structured evidence extraction,
- the **operational realism** of notebook lifecycle choices, note-to-source curation, incremental reruns, and measurable success metrics,
- and the **maintenance discipline** of a two-tier tool surface that avoids turning the MCP into an incoherent pile of micro-tools.

In one sentence, the target is:

> **full non-sharing NotebookLM MCP parity where it matters, plus a workflow-native BA engine that turns sources → snapshots → terminology → screen catalog → canonical → readiness → FE/BE bundle → QA → impacted rerun.**

That is the upgrade most likely to succeed in real implementation work.

---

## 22. Final Recommendation

Proceed with this as a **full-file replacement of the original upgrade plan**.

The sequence should be:
1. audit and adapter first,
2. source intelligence second,
3. canonical extraction third,
4. deterministic rendering and FE-first contracts fourth,
5. orchestration and reruns fifth,
6. QA and operational hardening sixth,
7. optional parity completion last.

That ordering gets the enterprise to useful output fastest while also reducing long-term rework.