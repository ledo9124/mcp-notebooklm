# BA Metrics And Evaluation

Status: operational metrics note for `bd-yae.6.6`  
Last updated: 2026-03-12

## Purpose

The BA runner now records a small local-first metrics layer so the workflow can
be judged by practical usefulness instead of architecture alone.

This layer is intentionally narrow:

- no network reporting
- no hidden telemetry
- no attempt to infer edits the repo cannot observe honestly

The metrics artifacts exist to answer two questions:

1. is the workflow reducing rerun scope and time-to-spec in practice?
2. when a number is only a proxy, is that proxy explicit and auditable?

## Where Metrics Live

The current metrics artifacts are:

- `docs/features/<feature_key>/06-metrics-summary.md`
- `docs/features/<feature_key>/06-metrics-history.json`
- `docs/features/<feature_key>/runs/<run_id>/metrics.json`

The current refresh points are:

- `ba.run_pipeline`
- `ba.validate_bundle`
- `ba.rerun_impacted`

`ba.status` does not recalculate metrics. It exposes the latest persisted
snapshot and the three artifact paths above.

## Exact Metrics vs Proxy Metrics

The metrics layer distinguishes between values the repo can measure exactly and
values that must remain proxies.

### Exact

- `rerun_scope_reduction_percentage`
  - derived from the latest rerun decision and impacted-screen count versus the
    current feature screen count
- `time_to_first_fe_spec_seconds`
  - derived from `run-metadata.json.created_at` and the persisted
    `RENDER_BUNDLE.completed_at` timestamp
- `ungrounded_facts_caught_by_qa`
  - counts validation findings tied to missing evidence or broken source
    grounding links
- `fe_first_without_later_contract_breakage_percentage`
  - counts FE-first provisional screens that do not later accumulate
    contract/mock breakage findings

### Proxy

- `average_manual_edits_per_screen`
  - current proxy: standalone `ba.validate_bundle` reruns divided by current
    screen count
  - rationale: the repo cannot see arbitrary editor activity, but it can see
    the explicit “recheck this bundle after changes” action
- `false_blocker_rate`
  - current proxy: degraded or halted checkpoints later cleared by a completed
    snapshot with the same source-snapshot fingerprint
  - rationale: if the source baseline did not change materially, the earlier
    blocker was likely too pessimistic

### Not Available / Not Applicable

The persisted snapshot uses explicit bases:

- `EXACT`
- `PROXY`
- `NOT_AVAILABLE`
- `NOT_APPLICABLE`

That means the runner is allowed to say “not measured yet” instead of forcing a
fake zero.

## Grounding-Related QA Findings

The current grounding metric counts validation findings with codes in these
areas:

- missing evidence on confirmed facts
- manifest rows missing snapshot or notebook-source linkage
- missing persisted snapshot metadata/fulltext
- terminology or bundle references pointing at sources absent from the manifest

This is intentionally narrower than “all validation failures.” Contract drift
and formatting repairs are still important, but they are not the same as
catching an ungrounded fact.

## History Semantics

`06-metrics-history.json` is append-only at the workflow level. A new snapshot
is appended whenever one of the refresh points above runs.

That history is what makes the proxy metrics auditable:

- manual-edit proxy depends on how many standalone validation reruns were
  recorded over time
- false-blocker proxy depends on comparing later healthy snapshots against
  earlier blocked snapshots with the same source fingerprint

## Interpretation Notes

- A repaired `WARN` validation result can still be a healthy workflow outcome if
  the warning is an explicit deterministic repair and the bundle remains
  semantically grounded.
- A `NOT_AVAILABLE` metric is preferable to a guessed value. The runner should
  stay honest about what it can and cannot observe.
- Metrics should be read with the current run state, readiness summary, and QA
  findings. None of these numbers are intended to replace the typed artifacts.

## Contributor Guidance

If you extend this metrics layer:

- keep new measurements local-first and file-derived
- add new exact metrics only when the inputs are already persisted locally
- keep proxies explicitly labeled as proxies
- update this note and `docs/ba-output-bundle-contract.md` whenever new metrics
  artifacts or pointer paths are added
