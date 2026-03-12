# BA Contributor Guide

Status: contributor/testing note for `bd-yae.8.3`  
Last updated: 2026-03-12

## Why This Exists

The BA runner now has enough moving parts that contributors should not have to
reverse-engineer the trust model from tests and implementation details.

This guide ties together the fixture strategy, golden-file workflow, canary
coverage, rerun semantics, validation rules, and metrics expectations that keep
the BA workflow honest over time.

Use it as the contributor-facing companion to:

- `docs/ba-subsystem-boundaries.md`
- `docs/ba-workflow-guide.md`
- `docs/ba-output-bundle-contract.md`

## Recommended Reading Order

Read these in order when you are new to the BA runner or about to make a
cross-cutting change:

1. `docs/ba-subsystem-boundaries.md`
2. `docs/ba-workflow-guide.md`
3. `docs/ba-output-bundle-contract.md`
4. `docs/ba-golden-file-maintenance.md`
5. `docs/ba-safe-repairs.md`
6. `docs/ba-upstream-canaries.md`
7. `docs/ba-rerun-fixture-contract.md`
8. `docs/ba-metrics-and-evaluation.md`

Then read the implementation seams most likely to be affected:

- `src/notebooklm_mcp/ba/models.py`
- `src/notebooklm_mcp/ba/run_store.py`
- `src/notebooklm_mcp/ba/rendering.py`
- `src/notebooklm_mcp/ba/validation.py`
- `src/notebooklm_mcp/ba/reruns.py`
- `src/notebooklm_mcp/ba/tools.py`

## Non-Negotiable Workflow Invariants

These rules are the reason the BA runner is useful instead of merely plausible.

- Keep BA-specific business logic under `src/notebooklm_mcp/ba/`. Generic
  NotebookLM parity work still belongs in `src/notebooklm_mcp/tools/`.
- Treat typed persisted artifacts as the authority:
  - `01-source-manifest.json`
  - `02-screen-catalog.json`
  - `04-terminology.json`
  - `screens/<screen_id>/canonical.json`
  - `05-run-audit.json`
  - `runs/<run_id>/run-state.json`
- Treat markdown, CSV, and other rendered files as deterministic views over the
  typed state, not as the primary source of truth.
- Keep the workflow evidence-first. Missing grounding, contradictory facts, and
  unresolved uncertainty must remain visible instead of being papered over.
- Preserve honest output states. `DEGRADED`, `HALTED`, provisional contracts,
  and clarification-first outcomes are correct behavior when the evidence base is
  weak.
- Keep repairs narrow and auditable. Deterministic repair may restore files only
  when the exact replacement content is already available locally, and every
  repair must remain visible in validation findings and persisted QA reports.
- Keep metrics local-first. If a number is only a proxy, say so explicitly
  instead of implying precision the repository does not actually have.

## Fixture Strategy

The fixture tree under `tests/fixtures/ba/` is the shared semantic contract for
the BA runner. Scenario names are intentionally stable because later golden,
rerun, and documentation coverage depends on them.

### Official Scenario Families

The six official representative fixture families are:

- `clean_feature/`
- `missing_contract/`
- `contradictory_sources/`
- `garbled_pdf/`
- `rerun_diff/`
- `note_clarification/`

There is also one additive support fixture:

- `rerun_cross_cutting/`

That extra fixture exists to lock the full-rerun escalation path. It is useful
for rerun testing, but it is not one of the six official `bd-yae.6.3` families.

### Expected Layout

Non-rerun scenarios keep:

- `sources/`
- `notes/`
- `expected/`
- `fixture.json`

Rerun scenarios may also keep:

- `before/`
- `after/`

`expected/scenario-signals.json` is the machine-readable contract for the
non-rerun scenarios. Renderer and bundle goldens now live directly beside it in
`expected/`.

### Fixture Rules For Contributors

- Keep `source_key` values stable across `before/` and `after/` variants.
- Prefer text fixtures unless a specific binary edge case is required.
- Update `scenario-signals.json` when the scenario's intended semantic outcome
  changes.
- Keep placeholder directories such as `notes/` when they are part of the
  frozen shape, even if the current scenario has no content there.
- Use typed loader helpers from `ba.fixtures` instead of duplicating path logic
  in new tests.

The main loader entry points are:

- `load_fixture_package(...)`
- `load_rerun_diff_fixture(...)`

Current owning tests include:

- `tests/unit/test_ba_fixture_loaders.py`
- `tests/unit/test_ba_rerun_fixtures.py`
- `tests/unit/test_ba_rendering.py`
- `tests/unit/test_ba_bundle_rendering.py`

## Golden-File Workflow

Golden files exist to make deterministic renderer drift obvious in review.

Non-rerun renderer and bundle goldens live under:

- `tests/fixtures/ba/<scenario>/expected/`

Rerun-specific expected artifacts stay separate:

- `tests/fixtures/ba/rerun_diff/expected/`
- `tests/fixtures/ba/rerun_cross_cutting/expected/`

The main owning tests are:

- `tests/unit/test_ba_rendering.py`
- `tests/unit/test_ba_bundle_rendering.py`
- `tests/unit/test_ba_rerun_fixtures.py`

Refresh renderer and bundle goldens only when deterministic behavior changed on
purpose:

```bash
UPDATE_BA_GOLDENS=1 PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q \
  tests/unit/test_ba_rendering.py \
  tests/unit/test_ba_bundle_rendering.py
```

Normal test runs should not set `UPDATE_BA_GOLDENS`. Golden diffs are evidence
for review, not output that should silently rewrite itself during validation.

Before accepting a golden diff:

1. Identify which test owns the changed file.
2. Confirm the corresponding renderer or fixture contract changed intentionally.
3. Cross-check `scenario-signals.json` so the semantic contract still matches
   the rendered output.
4. Treat unstable values such as timestamps or run-specific noise as a bug in
   determinism, not as a valid reason to refresh the golden.

See `docs/ba-golden-file-maintenance.md` for the fuller review checklist.

## Canary Expectations

The BA canaries are structural drift checks, not live NotebookLM integration
tests. They exist to catch local SDK or MCP contract movement early and cheaply.

Covered areas currently include:

- source ingest and snapshot helpers
- structured chat
- notes bridge behavior
- notebook settings and output language
- report, data-table, and mind-map helpers
- public `ba.*` tool registration
- generic MCP tool groups that BA workflows depend on

Run them with:

```bash
PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q tests/unit/test_ba_canaries.py
```

Update canaries only when the intentional capability contract changed. Do not
weaken them just to follow an accidental rename or a broken registration path.

See `docs/ba-upstream-canaries.md` for failure interpretation by capability
area.

## Validation And Repair Expectations

Validation is the guardrail that stops the bundle from looking cleaner than the
evidence base really is.

Important current behavior:

- `PASS` means the bundle is internally consistent and grounded.
- `WARN` can be a healthy outcome when the only issue is a deterministic repair
  that restored a drifted or missing presentation artifact.
- `FAIL` means the workflow found semantic, evidence, or contract-level issues
  that must remain visible.

Deterministic repair is intentionally narrow:

- it may repair only artifacts whose exact replacement content already exists in
  the current rendered inputs
- it records each repair as `deterministic-repair-applied`
- it persists the warning trail in per-screen `qa-report.json`
- it must not invent evidence, suppress contradictions, or silently change
  ungrounded facts into passing output

If you change repair or validation behavior, update both the specialized note
and the owning tests:

- `docs/ba-safe-repairs.md`
- `tests/unit/test_ba_validation.py`

## Rerun Semantics

Rerun logic is expected to be explicit about scope.

The current rerun outcomes are:

- no-op when nothing material changed
- selective rerun when impact stays narrow enough to identify concrete screens
- full rerun when the change is cross-cutting or too ambiguous to isolate safely

The current persisted rerun artifacts are:

- `docs/features/<feature_key>/runs/<run_id>/impacted-screens.json`
- `docs/features/<feature_key>/changelog.md`

Contributor expectations:

- keep rerun explanations explicit instead of hiding escalation reasons
- preserve stable `source_key` mappings across rerun fixture variants
- use stored fixtures to prove both narrow and full-rerun behavior
- keep rerun artifact shape aligned with `ba.run_store` and the output contract

See `docs/ba-rerun-fixture-contract.md` for the current landed fixture and
artifact details.

## Metrics Expectations

The metrics layer exists to measure workflow usefulness without hidden
telemetry.

Current persisted metrics artifacts are:

- `docs/features/<feature_key>/06-metrics-summary.md`
- `docs/features/<feature_key>/06-metrics-history.json`
- `docs/features/<feature_key>/runs/<run_id>/metrics.json`

Current refresh points are:

- `ba.run_pipeline`
- `ba.validate_bundle`
- `ba.rerun_impacted`

Contributor rules:

- keep new metrics file-derived and local-first
- mark proxy measurements as proxies
- allow `NOT_AVAILABLE` or `NOT_APPLICABLE` instead of fabricating a number
- update both `docs/ba-metrics-and-evaluation.md` and
  `docs/ba-output-bundle-contract.md` when metrics artifacts or pointer paths
  change

## Recommended Test Commands

Pick the narrowest useful slice for your change, then run the broader BA/MCP
slice before closing a cross-cutting bead.

Targeted suites:

```bash
PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q tests/unit/test_ba_fixture_loaders.py
PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q tests/unit/test_ba_rerun_fixtures.py
PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q tests/unit/test_ba_rendering.py tests/unit/test_ba_bundle_rendering.py
PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q tests/unit/test_ba_canaries.py
PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q tests/unit/test_ba_validation.py
PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q tests/unit/test_ba_metrics.py tests/unit/test_ba_run_store.py tests/unit/test_ba_tools.py
```

Broader regression slice used during the hardening phase:

```bash
PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q \
  tests/unit/test_ba_*.py \
  tests/unit/test_mcp_smoke.py \
  tests/unit/test_mcp_ba_tool_contracts.py \
  tests/unit/test_mcp_tools_workflows.py
```

## Contributor Checklist

Before closing a BA bead, confirm all of the following:

1. The change lives in the correct BA or generic module boundary.
2. Typed artifacts and persisted path contracts still match the documented
   workflow.
3. Fixture semantics are updated when scenario meaning changed.
4. Goldens were refreshed only when deterministic rendered output changed on
   purpose.
5. Validation still preserves evidence-first behavior and explicit uncertainty.
6. Canary coverage still protects the dependency surfaces the workflow relies
   on.
7. Metrics remain honest about whether they are exact, proxy, unavailable, or
   not applicable.
8. The relevant specialized docs and tests moved with the code.

That checklist is the fastest way to keep future BA work out of “looks fine
today, impossible to trust tomorrow” territory.
