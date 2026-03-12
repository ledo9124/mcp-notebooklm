# BA Phase 0 Run-Store Seed

Status: support artifact for likely next bead `bd-yae.1.5`  
Last updated: 2026-03-12

## Why This Exists

`bd-yae.1.5` is the next obvious Phase 0 follow-on once shared models land. This note distills the revised plan into concrete run-store and fixture-scaffolding expectations so the implementation can move quickly without re-reading the whole plan.

## P0 Storage Rules

- Default storage is local filesystem only.
- The run store owns persistence for snapshots, raw responses, normalized evidence, rendered outputs, audit events, and changed-screen mappings.
- The run store should expose stable helper APIs rather than making later beads assemble paths ad hoc.
- Future remote/pluggable storage is explicitly not P0.

## Expected Output Tree

The plan’s durable bundle contract is:

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

`bd-yae.1.5` does not need every later artifact writer, but it should establish the directory roots and path helpers that make this layout non-negotiable.

## Suggested P0 Run-Store Responsibilities

The run-store bead should probably stand up helpers for:

- create/load run roots from `feature_key` and `run_id`
- resolve canonical bundle paths for:
  - feature-level bundle files
  - per-screen outputs
  - run-scoped artifact directories
- persist/load typed metadata files once `bd-yae.1.4` lands
- keep room for audit events and step-level state even if the full state machine is a later bead
- avoid coupling path logic to NotebookLM-specific transport or extraction code

## Minimum File/Directory Affordances Worth Freezing Early

Even before later phases fill them with real content, these storage seams are worth making explicit:

- `runs/<run_id>/snapshots/`
  - snapshot payloads and snapshot metadata
- `runs/<run_id>/prompts/`
  - exact prompt text/inputs for reproducibility
- `runs/<run_id>/raw_responses/`
  - raw NotebookLM outputs before normalization
- `runs/<run_id>/normalized_evidence/`
  - evidence objects linked to snapshots
- `runs/<run_id>/impacted-screens.json`
  - placeholder target for rerun/change-detection output

## Typed Metadata Pressure From Downstream Beads

`bd-yae.1.5` is blocked on `bd-yae.1.4`, so storage helpers should assume typed models will arrive for at least:

- source manifest rows
- source snapshots and quality assessments
- screen catalog entries
- canonical screen payloads
- readiness summaries
- validator outputs
- run-state or audit-event records

That means the run store should prefer typed JSON read/write helpers over generic “dump arbitrary dict to file” utilities.

## Fixture Families Required By The Plan

The revised plan explicitly calls for these fixture sets:

1. clean BA PDF with stable API contract
2. BA PDF with no backend contract
3. contradictory BA + rule source
4. scanned/garbled PDF
5. changed-source rerun case
6. note-derived clarification case

It also sketches the fixture directory root as:

```text
tests/fixtures/ba/
  clean_feature/
  missing_contract/
  contradictory_sources/
  garbled_pdf/
  rerun_diff/
  note_clarification/
```

## Suggested Fixture-Scaffolding Conventions

To keep later tests sane, the fixture bead should likely freeze a small amount of structure now:

- each fixture family gets a dedicated directory under `tests/fixtures/ba/`
- fixture loaders should return typed metadata rather than bare file paths
- fixture names should describe the scenario, not the test that happens to use them
- note-derived clarification fixtures should stay visibly distinct from primary requirement sources
- rerun fixtures should preserve before/after source material in a way that future diff tests can load directly

## Non-Goals For The Seed

- no live NotebookLM calls
- no state-machine implementation
- no renderer logic
- no snapshot diffing logic yet

The main job of `bd-yae.1.5` is to prevent later persistence and fixture code from inventing incompatible conventions in parallel.
