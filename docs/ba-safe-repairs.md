# BA Safe Deterministic Repairs

`bd-yae.6.2` adds a narrow repair policy inside BA bundle validation.

The policy is intentionally small:

- repair only files whose exact replacement content already exists in local rendered inputs
- record every repair as a warning finding with code `deterministic-repair-applied`
- keep semantic or evidence-related failures as hard validation errors

## What Can Be Repaired

Feature-level files can be restored when the validator already has the typed bundle inputs:

- `00-overview.md`
- `01-source-manifest.md`
- `01-source-manifest.json`
- `02-screen-catalog.json`
- `03-readiness-summary.md`
- `04-terminology.md`
- `04-terminology.json`

Screen-level files can be restored only when `validate_bundle_artifacts(...)` receives the matching in-memory `ScreenBundleArtifact` objects from the same run:

- `screens/<screen_id>/canonical.json`
- `screens/<screen_id>/fe.md`
- `screens/<screen_id>/be.md`
- `screens/<screen_id>/questions.md`
- `screens/<screen_id>/field-matrix.csv`
- `screens/<screen_id>/action-rule-matrix.csv`
- `screens/<screen_id>/api-matrix.csv`
- `screens/<screen_id>/contract.provisional.yaml`
- `screens/<screen_id>/mock-data.json`

## What Stays A Hard Failure

The validator does not repair:

- missing evidence
- terminology/source-reference gaps
- contradictory canonical facts
- overconfident readiness outcomes
- rerun metadata that cannot be derived from current rendered inputs
- missing or fabricated audit history

Those cases still fail validation because repairing them would require inventing facts, suppressing uncertainty, or rewriting history.

## Audit Behavior

Repairs are not silent.

Each applied repair becomes a warning finding in:

- the returned `ValidationReport`
- the persisted per-screen `qa-report.json`

That keeps repaired bundles usable while preserving a review trail that the validator had to restore deterministic output files.
