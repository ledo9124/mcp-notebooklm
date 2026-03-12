# BA Rerun Fixture Contract

Status: contributor-facing staging note for `bd-yae.8`  
Last updated: 2026-03-12

## Why This Exists

`bd-yae.5.5` is the active rerun lane, while `bd-yae.8.3` is still blocked on the later fixture, golden, canary, and metrics leaves. The repository already contains real rerun fixtures, traceability helpers, and serialized rerun artifacts, so contributors should not need to reverse-engineer those contracts from test code alone.

This file is therefore not a user guide and not a public MCP reference. It is a contributor note that freezes the current rerun-fixture and rerun-artifact contract until the broader workflow and public docs stabilize.

## Current Landed Rerun Fixture Family

The repository currently includes one seeded rerun fixture family:

- `tests/fixtures/ba/rerun_diff/`

Its layout is:

- `before/`: source text before a change
- `after/`: source text after a change
- `expected/`: stored expected rerun outputs
- `fixture.json`: typed scenario manifest
- `notes/` and `sources/`: reserved directories kept for shape consistency with the broader BA fixture contract

The current `rerun_diff` scenario proves the narrow-impact path:

- `requirements.md` changes between `before/` and `after/`
- `glossary.md` stays unchanged
- the expected rerun output targets `customer-form` only
- the expected human-readable changelog explains that a targeted rerun is sufficient

This means later rerun work has at least one deterministic acceptance fixture for the “changed source stays narrow” case, rather than only unit-level synthetic payloads.

## Typed Loader Seam

The current contributor entry point for this fixture family is:

- `src/notebooklm_mcp/ba/fixtures.py`

Relevant helpers:

- `fixture_paths(FixtureScenario.RERUN_DIFF)`
- `load_rerun_diff_fixture(...)`

`load_rerun_diff_fixture(...)` currently returns:

- the resolved fixture layout
- the typed `fixture.json` manifest
- `before_text_by_source`
- `after_text_by_source`
- `expected_impacted_screens_json`
- `expected_changelog_markdown`

The loader intentionally ignores placeholder dotfiles such as `.gitkeep`, so rerun tests can consume stable source-keyed text maps without manual filtering.

Current regression coverage for this seam lives in:

- `tests/unit/test_ba_fixture_loaders.py`
- `tests/unit/test_ba_rerun_fixtures.py`

## Current Rerun Artifact Contract

Two persisted rerun artifacts are already part of the BA filesystem contract:

- `docs/features/<feature_key>/changelog.md`
- `docs/features/<feature_key>/runs/<run_id>/impacted-screens.json`

Those paths are defined by `src/notebooklm_mcp/ba/run_store.py`.

### `impacted-screens.json`

The current machine-readable payload is the serialized rerun impact report emitted by the private change-detection seam. Its current top-level shape is:

- `changed_sources`
- `deltas`
- `impacted_screens`
- `requires_full_rerun`
- `escalation_reasons`

The current narrow fixture demonstrates that `impacted_screens[*]` records:

- `screen_id`
- `screen_name`
- `changed_sources`
- `changed_terms`
- `reasons`

Current reasons already represented by the landed seams include:

- `manifest_usage`
- `related_source`
- `catalog_evidence`
- `canonical_evidence`
- `terminology_match`
- `depends_on_impacted_screen`
- `matrix_evidence`

The precise mix of reasons depends on which traceability signals matched the changed source.

### `changelog.md`

The current human-readable changelog renderer emits three sections:

- `## Source Changes`
- `## Impacted Screens`
- `## Rerun Recommendation`

For the current narrow rerun fixture, the recommendation is:

- `Targeted rerun is sufficient.`

Later escalation fixtures should instead demonstrate the “full rerun recommended” path with explicit reasons.

## Current Implemented Seams Behind The Contract

The current rerun contributor contract draws on these internal modules:

- `src/notebooklm_mcp/ba/_change_detection.py`
  - snapshot diffing
  - changed heading / terminology detection
  - rerun impact report rendering
- `src/notebooklm_mcp/ba/traceability.py`
  - source-to-screen mapping from catalog, canonical evidence, matrix evidence, and dependencies
- `src/notebooklm_mcp/ba/fixtures.py`
  - typed fixture loading for the landed rerun fixture family
- `src/notebooklm_mcp/ba/run_store.py`
  - reserved persisted paths for rerun artifacts

This note is intentionally scoped to those landed seams. It does not claim that the public `ba.rerun_impacted` MCP surface is finalized.

## Contributor Guidance

When adding future rerun fixture families or rerun tests:

- keep `source_key` values stable across `before/` and `after/`
- check in expected `impacted-screens.json` and `changelog.md` beside the source material
- prefer typed fixture helpers in `ba.fixtures` over raw path joins in new tests
- keep rerun fixtures deterministic and text-based unless a specific binary edge case is required
- do not update README or public MCP docs from this note alone; those should wait for the public wrapper lane to settle

## What Is Still Pending

This document should be revised once the remaining rerun and hardening work lands, especially:

- final public `ba.rerun_impacted` wrapper semantics
- cross-cutting escalation fixtures that require full reruns
- Phase 5 golden, validator, canary, and contributor-doc leaves

Until then, treat this file as a source-of-truth note for contributors working inside the rerun and fixture seams, not as end-user documentation.
