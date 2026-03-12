# BA Fixture Skeleton

This directory is the shared landing zone for BA runner fixtures.

For the broader contributor workflow across fixtures, goldens, canaries,
reruns, validation, and metrics, start with `docs/ba-contributor-guide.md`.

Each scenario directory follows the structure frozen in `bd-yae.1.5`:

- `sources/`: primary and supporting source material for the scenario
- `notes/`: note-derived clarifications or curated note inputs
- `expected/`: golden outputs or scenario-specific assertions
- `fixture.json`: typed scenario manifest

The `rerun_diff/` scenario also carries:

- `before/`: source material before the change
- `after/`: source material after the change

The official representative fixture families are:

- `clean_feature/`: stable BA + API contract inputs that should stay ready for FE and BE
- `missing_contract/`: requirements are usable for FE work but backend contract detail is still provisional
- `contradictory_sources/`: supporting rules conflict with the primary BA source and should force clarification
- `garbled_pdf/`: OCR-poisoned source material intended to exercise degraded extraction/readiness behavior
- `rerun_diff/`: changed-source rerun case with seeded impacted-screen and changelog artifacts
- `note_clarification/`: note-derived clarification captured separately from primary requirements

The extra `rerun_cross_cutting/` fixture is an additive regression seam for the
full-rerun escalation path. It is useful for rerun testing, but it is not one
of the six official `bd-yae.6.3` families.

Scenario names are intentionally stable because later golden, rerun, and docs
tests will depend on them. `expected/scenario-signals.json` files are the
machine-readable contract for the non-rerun scenarios, while `ba.fixtures`
provides typed loaders that ignore placeholder dotfiles.

Non-rerun scenarios now also keep reviewable golden renderer outputs directly in
`expected/`. Refresh them intentionally with:

`UPDATE_BA_GOLDENS=1 PYTHONPATH=src /tmp/notebooklm-py-codex-venv/bin/pytest -q tests/unit/test_ba_rendering.py tests/unit/test_ba_bundle_rendering.py`

That flow is opt-in on purpose so golden diffs stay visible in code review
instead of silently changing during normal test runs.
