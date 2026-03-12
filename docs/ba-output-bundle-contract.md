# BA Output Bundle Contract

Status: filesystem contract note for `bd-yae.8.1`  
Last updated: 2026-03-12

## Root Shape

The current BA run-store contract writes feature output under:

```text
docs/features/<feature_key>/
```

Within that feature root, the important directories are:

- `screens/`: per-screen canonical, matrix, spec, question, contract, mock, and QA artifacts
- `runs/`: per-run state, source-registration, rerun, and snapshot artifacts

Not every file exists at the start of a run. Some appear only after the
workflow reaches the corresponding stage.

## Feature-Level Files

These files live directly under `docs/features/<feature_key>/`.

| Path | Meaning | Typical producer |
| --- | --- | --- |
| `00-overview.md` | high-level bundle overview | rendering pipeline |
| `01-source-manifest.md` | human-readable source inventory | source-manifest rendering |
| `01-source-manifest.json` | typed source inventory | run-store persistence |
| `02-screen-catalog.json` | extracted screen catalog | screen-catalog extraction |
| `03-readiness-summary.md` | feature-level readiness decision and warnings | readiness rendering |
| `04-terminology.md` | human-readable terminology sheet | terminology rendering |
| `04-terminology.json` | typed terminology document | terminology extraction |
| `05-run-audit.json` | historical snapshots of run-state transitions | run-store audit trail |
| `06-metrics-summary.md` | human-readable operational metrics summary | metrics reporting |
| `06-metrics-history.json` | append-only metrics snapshot history for the feature | metrics reporting |
| `changelog.md` | rerun changelog across baseline updates | rerun path |

## Run-Level Files

These files live under:

```text
docs/features/<feature_key>/runs/<run_id>/
```

| Path | Meaning |
| --- | --- |
| `run-metadata.json` | stable metadata for the run, including pointer sets |
| `run-state.json` | current run-state snapshot |
| `source-registration.json` | normalized source registration result |
| `impacted-screens.json` | machine-readable rerun plan/report |
| `metrics.json` | latest typed operational metrics snapshot for the run |
| `prompts/` | captured prompt payloads when a step records them |
| `raw_responses/` | raw model responses when persisted |
| `normalized_evidence/` | normalized evidence payload captures |
| `snapshots/` | per-source snapshot history |

## Snapshot Subtree

Each persisted source snapshot lives under:

```text
docs/features/<feature_key>/runs/<run_id>/snapshots/<source_key>/<snapshot_id>/
```

The current snapshot contract includes:

- `metadata.json`: typed snapshot metadata
- `fulltext.txt`: persisted fulltext used for extraction and reruns
- `guide.json`: source guide/freshness guidance
- `quality.json`: source-quality assessment

This is the baseline that rerun planning compares against when deciding whether
to stay selective or escalate.

## Per-Screen Files

Each screen gets its own bundle directory:

```text
docs/features/<feature_key>/screens/<screen_id>/
```

| Path | Meaning | Notes |
| --- | --- | --- |
| `canonical.json` | canonical extracted facts, gaps, questions, contradictions | one of the main typed source-of-truth files |
| `field-matrix.csv` | field mapping matrix | derived screen artifact |
| `action-rule-matrix.csv` | action/rule matrix | derived screen artifact |
| `api-matrix.csv` | API interaction matrix | derived screen artifact |
| `fe.md` | FE implementation spec | rendered output |
| `be.md` | BE implementation spec | rendered output |
| `questions.md` | unresolved questions backlog for the screen | rendered output |
| `contract.provisional.yaml` | provisional contract output | intentionally provisional, not final backend truth |
| `mock-data.json` | deterministic mock payloads | support artifact for FE and QA |
| `qa-report.json` | per-screen validation findings | appears after validation runs |

## Which Files Are Authoritative vs Provisional

The current contract is not “everything in the bundle is equally authoritative.”

Treat these as the primary typed references:

- `01-source-manifest.json`
- `02-screen-catalog.json`
- `04-terminology.json`
- `screens/<screen_id>/canonical.json`
- `05-run-audit.json`
- `runs/<run_id>/run-state.json`

Treat these as rendered or derived views over that typed state:

- `00-overview.md`
- `01-source-manifest.md`
- `03-readiness-summary.md`
- `04-terminology.md`
- `fe.md`
- `be.md`
- `questions.md`
- matrix CSVs

Treat these as explicitly provisional or conditional:

- `contract.provisional.yaml`
- `mock-data.json`
- `qa-report.json`
- `impacted-screens.json`
- `changelog.md`

The important rule is that provisional or rerun-specific files should not be
mistaken for immutable product truth.

## State And Audit Contract

Two files answer different questions and should both be preserved:

- `runs/<run_id>/run-state.json`: “what is the current state right now?”
- `05-run-audit.json`: “how did this run get here over time?”

The status tool depends on the current state file, while contributor debugging
and workflow forensics depend on the audit trail.

## Validation And Rerun Artifacts

Validation and rerun outputs extend the base bundle instead of replacing it.

Validation currently contributes:

- `screens/<screen_id>/qa-report.json`

Reruns currently contribute:

- `runs/<run_id>/impacted-screens.json`
- `changelog.md`

Metrics currently contribute:

- `06-metrics-summary.md`
- `06-metrics-history.json`
- `runs/<run_id>/metrics.json`

These files should be interpreted together with the current run state and not in
isolation.

## Pointer Contract In `run-metadata.json`

`run-metadata.json` includes pointer sets back to the important feature-level and
run-level paths. That means callers do not need to reconstruct locations by hand
after starting or resuming a run.

The current feature pointers include:

- overview markdown
- source-manifest markdown and JSON
- screen-catalog JSON
- readiness-summary markdown
- terminology markdown and JSON
- run-audit JSON
- metrics summary markdown
- metrics history JSON
- changelog markdown

The current run pointers include:

- snapshots directory
- prompts directory
- raw-responses directory
- normalized-evidence directory
- source-registration JSON
- impacted-screens JSON
- metrics JSON
- run-metadata JSON
- run-state JSON

## Stability Expectations

This contract is intended to be additive by default:

- new files may appear as later beads land
- existing paths should stay stable unless there is a deliberate breaking change
- workflow docs and tests should treat this file as the current path contract

If a future change wants to rename or remove one of these paths, it should be
treated as a compatibility decision, not an incidental refactor.
