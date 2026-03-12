# BA Phase 0 Contract Seeds

Status: support artifact for active `bd-yae.1.3` and `bd-yae.1.4` owners  
Last updated: 2026-03-12

## Why This Exists

`bd-yae.1.3` and `bd-yae.1.4` are the only real ready Phase 0 implementation beads, and both are already actively claimed by other agents. This note captures the highest-signal downstream contract requirements from the revised plan and dependent bead graph so those owners can freeze useful interfaces without rediscovering later needs.

This is intentionally additive. It is not meant to replace the parity audit or the subsystem-boundary note.

## Adapter Contract Requirements for `bd-yae.1.3`

The adapter does not need to implement the whole workflow. It does need to make later workflow steps independent from raw `NotebookLMClient` naming, missing MCP parity, and inconsistent upstream failure shapes.

### Minimum seam rules

- Later BA modules should depend on one BA-facing adapter surface, not directly on `NotebookLMClient`.
- Unsupported or unstable upstream features should return explicit typed states, not `None` guessing or call-site-specific exception handling.
- Degraded outcomes must be first-class payloads because later beads explicitly depend on source-level timeout, parse, readiness, and optional-artifact policy.

### Capability groups the adapter must make obvious

#### Source substrate

Needed by `bd-yae.2.1`, `bd-yae.2.2`, `bd-yae.2.3`, and `bd-yae.7.1`.

- registration/lookup primitives over source add/list/get/rename/delete
- ingest primitives that preserve `source_key -> notebook_source_id` linkage
- wait/readiness primitives that can report per-source degraded timeout states
- source-intelligence primitives for fulltext, guide, freshness, and refresh

The important point is not only transport wrapping. The adapter needs to normalize the per-source result envelope that later source-manifest and snapshot code will persist.

#### Structured-ask substrate

Needed by `bd-yae.3.1`.

- ask/history/conversation access
- stable citation carriage
- conversation ID visibility
- notebook chat-setting access without exposing raw SDK details everywhere

The structured JSON parsing ladder belongs in `bd-yae.3.1`, but the adapter should already preserve raw answer text, citations, and conversation identifiers so the structured-ask layer is not forced back into raw SDK objects.

#### Settings and parity helpers

Needed by `bd-yae.7.2`, `bd-yae.7.3`, and `bd-yae.7.4`.

- output-language get/set as a separate capability family from notebook chat settings
- report/data-table helpers
- mind-map helpers marked as non-core

The parity audit already established that these are SDK-backed but MCP-missing. The adapter should expose them as direct BA capability seams rather than making later `ba.*` code call generic MCP handlers.

### Result-envelope requirements

The following normalized outcomes show up repeatedly in downstream beads and should not be improvised later:

- capability availability:
  - `SUPPORTED`
  - `DEGRADED`
  - `UNSUPPORTED`
  - optionally `EXPERIMENTAL` for non-core artifact helpers
- per-source ingest/readiness outcomes:
  - `source_key`
  - `notebook_source_id`
  - readiness state
  - degraded reason or timeout reason
- snapshot-oriented source reads:
  - fulltext payload
  - guide payload when available
  - freshness payload when available
  - explicit unavailable reason when upstream data is absent

## Model And Schema Requirements for `bd-yae.1.4`

The plan is already specific enough to define strict shared models without guessing every later rendering detail.

### Must-have enums with plan-defined values

These values are explicit in the plan and should not remain free-form strings:

- `SourceType`
  - `PRIMARY_REQUIREMENT`
  - `PRIMARY_CONTRACT`
  - `SUPPORTING_GLOSSARY`
  - `SUPPORTING_RULE`
  - `SUPPORTING_DESIGN`
  - `SUPPORTING_TECH`
  - `SUPPORTING_CLARIFICATION`
  - `SUPPORTING_DECISION`
  - `OPTIONAL_CONTEXT`
- `ParseQuality`
  - `HIGH`
  - `MEDIUM`
  - `LOW`
  - `FAILED`
- `FactDomain`
  - `SHARED`
  - `FE`
  - `BE`
- `FactStatus`
  - `CONFIRMED`
  - `PROVISIONAL`
  - `MISSING`
  - `CONTRADICTED`
  - `INFERRED`
- `ReadinessDecision`
  - `READY_FOR_FE_AND_BE`
  - `READY_FOR_FE_WITH_PROVISIONAL_CONTRACT`
  - `PARTIAL_READY_NEEDS_CLARIFICATION`
  - `NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS`

### Must-have shared objects

The following object families are directly implied by the plan and bead dependencies:

- `SourceManifestRow`
  - must cover `source_key`, `source_type`, `priority`, `notebook_source_id`, `snapshot_id`, `parse_quality`, `freshness`, `status`, `notes`, `used_in_screens`
- `SourceSnapshot`
  - must carry snapshot identity, stored locations, and stable content hash metadata
- `SourceQualityAssessment`
  - must carry deterministic diagnostics and halt/degrade recommendation
- `TerminologyEntry`
  - standard term, aliases, semantic notes, source evidence, ambiguity flags
- `ScreenCatalogEntry`
  - `screen_id`, name/purpose/roles/entry/exit/actions/dependencies/related_sources/evidence/open_questions`
- `EvidenceObject`
  - `source_key`, `snapshot_id`, `locator`, `quote`
- `CanonicalFact`
  - `fact_id`, `domain`, `category`, `value`, `status`, `confidence`, `evidence`, `note`
- `CanonicalScreen`
  - `schema_version`, `feature_key`, `screen_id`, `mode`, `run_id`, `shared_facts`, `fe_facts`, `be_facts`, `dependencies`, `contradictions`, `missing_info`, `open_questions`, `quality_summary`
- `BlockerOrQuestion`
  - enough structure for `bd-yae.3.6`, `bd-yae.4.2`, and `bd-yae.5.1` to avoid inventing new ad hoc backlog shapes
- `ReadinessSummary`
  - per-screen FE readiness, per-screen BE readiness, overall feature readiness, and final decision enum
- `ContractMetadata`
  - enough room for provisional status and evidence/question metadata referenced by later contract generation
- `ValidatorOutput`
  - enough structure for `qa-report.json` findings, severity, and machine-readable outcomes
- `RunState` and step/event enums
  - `bd-yae.5.1` depends on `bd-yae.1.4`, so execution-state vocabulary should not be deferred until the state-machine bead

### Integrity rules that should live in models, not only docs

- `source_key`, `screen_id`, `snapshot_id`, and `fact_id` should be stable identifiers, not presentation text.
- Confirmed facts should require non-empty evidence.
- Provisional or inferred facts should require explanatory rationale fields.
- Evidence objects should link to snapshots, not only live NotebookLM source IDs.
- Canonical/readiness/validator models should share enums instead of duplicating independent string sets.

## Schema-Family Suggestions

The output tree and downstream beads suggest independent schema families rather than one giant version number:

- `source-manifest`
- `screen-catalog`
- `canonical-screen`
- `readiness-summary`
- `contract-metadata`
- `qa-report`
- `run-state`

This keeps additive evolution local. A validator-only change should not necessarily force a canonical-schema bump.

## Version-Bump Rule

The rule should be explicit enough that reviewers can tell when a schema change is intentional.

- bump major when:
  - a required field is added, removed, or renamed
  - an enum meaning changes incompatibly
  - a serialized structure changes such that older readers would misread it
- bump minor when:
  - an optional field is added
  - a backward-compatible enum value is added
  - metadata is added that older readers can safely ignore
- do not bump for:
  - internal refactors with identical serialized output
  - doc-only clarifications

## Known Unresolved Items

These are real gaps in the plan and should either stay deliberately unresolved or be documented as local Phase 0 choices:

- `priority` exists for source manifest rows, but the plan does not define its enum values
- blocker/question severity taxonomy is implied but not fully enumerated
- exact run-state enum values are not specified yet, only the need for explicit state, halt reason, retry, and degraded tracking

The main risk here is overfitting invented detail into the first shared schema and then forcing later beads to route around it.
