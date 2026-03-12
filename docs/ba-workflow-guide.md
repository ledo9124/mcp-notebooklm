# BA Workflow Guide

Status: workflow guide for `bd-yae.8.1`  
Last updated: 2026-03-12

## What The BA Runner Does

The BA runner is the workflow-native layer inside `notebooklm_mcp` for turning
BA requirements and supporting evidence into a deterministic implementation
bundle. It is intentionally separate from the generic NotebookLM parity tools.

The current public BA tool surface is:

- `ba.start_run`
- `ba.register_sources`
- `ba.status`
- `ba.validate_bundle`
- `ba.run_pipeline`
- `ba.rerun_impacted`

Those tools are thin wrappers over the dedicated `src/notebooklm_mcp/ba/`
subsystem. The important split is:

- generic NotebookLM parity stays in `notebooklm_mcp.tools.*`
- BA-specific orchestration, persistence, extraction, rendering, validation, and
  rerun logic stays in `notebooklm_mcp.ba`

## Inputs

A BA run is identified by:

- `feature_key`: stable feature identifier such as `customer-create`
- `run_id`: concrete execution instance under that feature
- `output_dir`: workspace root where `docs/features/<feature_key>/...` is stored

Source registration normalizes the source list into a typed manifest. The
current workflow expects at least one primary requirement source and may also
take supporting inputs such as:

- glossary sources
- contract drafts
- business rules
- note-derived clarifications or decisions

## Workflow Modes

The workflow currently uses four mode labels:

- `AUTO`: let readiness resolve the safest mode from current evidence
- `BALANCED`: aim for FE and BE implementation together when evidence supports it
- `FE_FIRST`: allow FE work to continue with provisional backend contract output
- `CLARIFICATION_FIRST`: stop and surface blockers instead of pretending the
  source set is implementation-ready

`EVALUATE_READINESS` is the stage that may downgrade a requested mode based on
missing evidence, contradictions, or degraded extraction quality.

## Public Tool Flow

There are two practical ways to drive the workflow.

### Explicit Flow

Use this when you want step-by-step control and explicit persisted state:

1. `ba.start_run`
2. `ba.register_sources`
3. `ba.status`
4. `ba.run_pipeline`
5. `ba.status`
6. `ba.rerun_impacted` after upstream source changes
7. `ba.validate_bundle` when you want to rerun QA checks against the current bundle

### Macro Flow

Use `ba.run_pipeline` when you already know the source list and want one command
to drive the run from bootstrap through validation. The macro still persists the
same run metadata, run state, audit trail, and bundle files as the explicit flow.

## Pipeline Stages

The persisted status surface exposes the current planned stage order:

1. `START_RUN`
2. `REGISTER_SOURCES`
3. `INGEST_AND_WAIT`
4. `SNAPSHOT_SOURCES`
5. `ASSESS_SOURCE_QUALITY`
6. `BUILD_SOURCE_MANIFEST`
7. `NORMALIZE_TERMINOLOGY`
8. `BUILD_SCREEN_CATALOG`
9. `EXTRACT_CANONICAL`
10. `REVIEW_GAPS`
11. `GENERATE_MATRICES`
12. `EVALUATE_READINESS`
13. `GENERATE_CONTRACTS`
14. `RENDER_BUNDLE`
15. `VALIDATE_BUNDLE`

`ba.status` reports:

- current run status
- current and next step
- completed and not-started steps
- resumability hints
- halt/degraded reasons when present
- the latest persisted operational metrics snapshot and its artifact paths when available

## Run States And What They Mean

The current run-state layer uses these top-level statuses:

- `PENDING`: run metadata exists but execution has not started meaningfully
- `RUNNING`: workflow is active
- `DEGRADED`: the workflow continued only partially because quality or evidence
  confidence dropped
- `HALTED`: execution stopped intentionally at a specific step
- `FAILED`: an unhandled failure stopped the run
- `COMPLETED`: the pipeline reached the current terminal step successfully

Two other state vocabularies matter for interpretation:

- readiness decisions:
  - `READY_FOR_FE_AND_BE`
  - `READY_FOR_FE_WITH_PROVISIONAL_CONTRACT`
  - `PARTIAL_READY_NEEDS_CLARIFICATION`
  - `NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS`
- validation outcomes:
  - `PASS`
  - `WARN`
  - `FAIL`

In practice:

- degraded or blocked states are product output, not incidental failures
- contradictions and low-quality OCR should stay visible
- provisional FE-first output is allowed, but it must remain explicitly
  provisional rather than being presented as authoritative backend truth

## Core Artifacts Produced By A Successful Run

The main bundle assembly is rendered under `docs/features/<feature_key>/` and
its per-run subdirectories. The important outputs are:

- source manifest markdown and JSON
- screen catalog JSON
- readiness summary markdown
- terminology markdown and JSON
- per-screen canonical JSON
- field/action-rule/API matrices
- per-screen FE and BE specs
- per-screen questions backlog
- provisional contract YAML and mock data when applicable
- run state and audit artifacts
- metrics summary, metrics history, and per-run metrics snapshots
- per-screen QA reports after validation

The companion document [docs/ba-output-bundle-contract.md](/home/lemin/flywheel/projects/notebooklm-py/docs/ba-output-bundle-contract.md)
freezes the current path contract in more detail.

## Rerun Behavior

`ba.rerun_impacted` exists for incremental updates after source changes. It
compares fresh source snapshots with the persisted baseline and then decides
between:

- no-op rerun because nothing material changed
- selective rerun of only the impacted screens
- full-feature rerun when changes are too broad or too ambiguous

Current rerun artifacts are:

- `docs/features/<feature_key>/runs/<run_id>/impacted-screens.json`
- `docs/features/<feature_key>/changelog.md`

Selective reruns update only the necessary screens. Escalated reruns keep the
explanation explicit so operators can see why the workflow stopped being narrow.

## How To Read Degraded And Provisional Output

The BA runner is designed to be honest about uncertainty.

- If source quality is degraded, expect warnings and possibly a
  `CLARIFICATION_FIRST` resolution.
- If requirements are good enough for FE but not strong enough for final backend
  commitments, expect FE-first or provisional-contract output rather than a hard
  failure.
- If contradictions remain unresolved, expect blockers and open questions rather
  than a false merged answer.

That honesty is part of the product contract. A bundle that says “provisional”
or “blocked” is behaving correctly when the source material is incomplete.

## Recommended Contributor Reading Order

If you need to extend the BA runner safely, the fastest path is:

1. [docs/ba-subsystem-boundaries.md](/home/lemin/flywheel/projects/notebooklm-py/docs/ba-subsystem-boundaries.md)
2. [docs/ba-output-bundle-contract.md](/home/lemin/flywheel/projects/notebooklm-py/docs/ba-output-bundle-contract.md)
3. [docs/ba-contributor-guide.md](/home/lemin/flywheel/projects/notebooklm-py/docs/ba-contributor-guide.md)
4. `src/notebooklm_mcp/ba/models.py`
5. `src/notebooklm_mcp/ba/run_store.py`
6. `src/notebooklm_mcp/ba/tools.py`

That sequence explains the package boundaries, the persisted filesystem shape,
the maintenance expectations, the core vocabulary, and the current public tool
surface without having to reverse-engineer the whole subsystem from tests
alone.
