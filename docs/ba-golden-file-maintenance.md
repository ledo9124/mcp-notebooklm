# BA Golden File Maintenance

This note explains how the BA fixture goldens are organized and how to review or refresh them without hiding regressions.

## Where The Goldens Live

The non-rerun fixture families keep reviewable expected outputs under `tests/fixtures/ba/<scenario>/expected/`.

Current scenarios with renderer and bundle goldens:

- `clean_feature`
- `missing_contract`
- `contradictory_sources`
- `garbled_pdf`
- `note_clarification`

Rerun-specific expected artifacts live separately:

- `tests/fixtures/ba/rerun_diff/expected/`
- `tests/fixtures/ba/rerun_cross_cutting/expected/`

## Which Tests Own Which Files

`tests/unit/test_ba_rendering.py` covers renderer-level outputs and compares them against scenario goldens such as:

- `source-manifest.md`
- `source-manifest-json.json`
- `questions.customer-form.md`

`tests/unit/test_ba_bundle_rendering.py` covers assembled bundle outputs and compares them against scenario goldens such as:

- `overview.md`
- `readiness-summary.md`
- `canonical.<screen_id>.json`
- `fe.<screen_id>.md`
- `be.<screen_id>.md`
- `field-matrix.<screen_id>.csv`
- `action-rule-matrix.<screen_id>.csv`
- `api-matrix.<screen_id>.csv`
- `contract.<screen_id>.yaml`
- `mock-data.<screen_id>.json`

`expected/scenario-signals.json` stays machine-readable and should be treated as the semantic contract for the scenario, not as a rendered presentation file.

`tests/unit/test_ba_rerun_fixtures.py` owns the rerun-only goldens:

- `impacted-screens.json`
- `changelog.md`

Those rerun expected files are not refreshed by the renderer golden update command below.

## Refresh Flow

The renderer and bundle golden tests already gate writes behind `UPDATE_BA_GOLDENS=1`.

Refresh only when you have intentionally changed deterministic rendering behavior:

```bash
UPDATE_BA_GOLDENS=1 PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q \
  tests/unit/test_ba_rendering.py \
  tests/unit/test_ba_bundle_rendering.py
```

Normal test runs should omit `UPDATE_BA_GOLDENS` so diffs stay visible in review.

## Review Checklist

Treat a golden diff as intentional only when you can point to the exact renderer or fixture contract change that caused it.

Use this checklist:

1. Identify which test owns the changed golden.
2. Confirm the underlying scenario inputs in `sources/`, `notes/`, `before/`, or `after/` changed intentionally, or that a deterministic renderer changed intentionally.
3. Cross-check `expected/scenario-signals.json` for the same scenario to make sure the semantic contract still matches the new rendered output.
4. Verify that readiness changes are justified by canonical facts, blockers, or question severity changes rather than unstable formatting.
5. Verify that contract or mock-data diffs come from explicit contract-generation changes, not accidental drift in field names, paths, or required operations.
6. If a diff changes run IDs, timestamps, or other unstable values, treat that as a bug in determinism rather than an expected golden update.

## Regression Signals

The safest default is to assume a golden diff is a regression until the cause is explained.

Common red flags:

- only one side of a paired artifact changed, such as `contract.*.yaml` without the matching `mock-data.*.json`
- readiness summary changes without a matching canonical or question/backlog reason
- `scenario-signals.json` still says the old scenario state while rendered docs imply a different one
- broad text churn in `overview.md` or FE/BE specs without a corresponding fixture or renderer change
- rerun `impacted-screens.json` or `changelog.md` diffs produced by renderer-only work

## Suggested Review Pattern

For a renderer change, review in this order:

1. the implementation diff
2. the owning unit test diff
3. the fixture input diff, if any
4. the golden output diff

That sequence keeps the code change as the explanation and the golden diff as evidence, instead of treating the golden files themselves as the source of truth.
