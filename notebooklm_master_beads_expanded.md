# NotebookLM Agent-First CLI — Expanded Master Bead Plan

> **Generated from**: `notebooklm_master_beads.md`
> **Authority**: CONTRACT_NORMALIZATION.md > PLAN_NOTEBOOKLM_AGENT_FIRST_REVISED.md > PLAN_SUPPLEMENT_DOCTOR_WORKSPACES_CHANGE_RADAR_INBOX.md > PLAN-CLI.md
> **Purpose**: Make the concise bead DAG fully self-contained, future-readable, and directly materialized in `br`.

## Program Summary

This companion document elaborates the canonical `B-xxx` roadmap into a detailed execution plan that explains what each bead is for, why it exists, how it relates to current repo reality, and how the dependency graph is materialized in `br`.

- Root epic: `AF-ROOT` -> `bd-hl2s`
- Phase epics: `14`
- Top-level B-series tasks: `79`
- Child implementation tasks: `172`
- MVP tasks: `45`
- Post-MVP tasks: `34`

## Current Repo Audit Snapshot

The plan is not abstract architecture theater. It is anchored to the repo as it exists today so future work can see the gap between the current package and the target agent-first CLI.

- **Packaging metadata** (`pyproject.toml`): The package is still published as `notebooklm-py` with the description `Unofficial async Python API + CLI for Google NotebookLM.` and package discovery still includes `notebooklm*` broadly. That matches the legacy API/client framing, not the forked agent-first CLI boundary.
- **CLI surface** (`src/notebooklm/notebooklm_cli.py`): The root CLI still advertises the older `login/list/create/ask/generate/research` workflow. There is no manifest-driven command registration, no `doctor`, no `route`, no `history`, and no agent-first command grammar.
- **Auth model** (`src/notebooklm/auth.py`): Auth state is still cookie + CSRF + session ID only. There is no `build_label` field on `AuthTokens`, and token fetch still returns only CSRF/session. The `fetch_tokens()` contract is still a two-value tuple.
- **Transport core** (`src/notebooklm/_core.py`): The RPC URL builder currently sends `rpcids`, `source-path`, `f.sid`, and `rt`, but not `bl`. The transport already knows how to refresh once on auth errors and classify 429s, but it does not integrate with run tracing, durable snapshots, or the manifest/risk model.
- **Local state** (`src/notebooklm/paths.py`): State already respects `NOTEBOOKLM_HOME`, but it is still file-based (`storage_state.json`, `context.json`, `browser_profile/`) rather than SQLite/profile-scoped.
- **Durable cache and memory** (`src/notebooklm/`): There is no SQLite cache layer, schema migration system, history index, run event log, or profile manager in the current package.
- **Contract layer** (`src/notebooklm/`): There is no manifest-first contract package yet: no `capabilities.yaml`, no envelope schema module, no intent/risk enums, and no central RPC map.

## Planning Conventions

- `external_ref` in `br` preserves the stable conceptual key (`AF-ROOT`, `PHASE-n`, `B-xxx`, `B-xxxa`).
- Phase epics group work by architectural milestone; top-level B-series issues are the real deliverables.
- Child tasks represent implementation slices already implied by the master plan's subtasks.
- Cross-bead dependency edges are applied at the B-series level so `br ready` reflects real sequencing.
- The expanded plan is intentionally verbose so a future contributor can recover intent without re-reading all four upstream plan documents.

## Materialized Issue Index

| Key | Actual bead | Type | Parent | Depends on |
|---|---|---|---|---|
| AF-ROOT | bd-hl2s | epic | - | - |
| PHASE-0 | bd-hl2s.1 | epic | bd-hl2s | - |
| B-001 | bd-hl2s.1.1 | feature | bd-hl2s.1 | - |
| B-001a | bd-hl2s.1.1.1 | task | bd-hl2s.1.1 | - |
| B-001b | bd-hl2s.1.1.2 | task | bd-hl2s.1.1 | - |
| B-001c | bd-hl2s.1.1.3 | task | bd-hl2s.1.1 | - |
| B-002 | bd-hl2s.1.2 | feature | bd-hl2s.1 | bd-hl2s.1.1 |
| B-002a | bd-hl2s.1.2.1 | task | bd-hl2s.1.2 | - |
| B-002b | bd-hl2s.1.2.2 | task | bd-hl2s.1.2 | - |
| B-002c | bd-hl2s.1.2.3 | task | bd-hl2s.1.2 | - |
| B-003 | bd-hl2s.1.3 | feature | bd-hl2s.1 | bd-hl2s.1.1 |
| B-003a | bd-hl2s.1.3.1 | task | bd-hl2s.1.3 | - |
| B-003b | bd-hl2s.1.3.2 | task | bd-hl2s.1.3 | - |
| B-003c | bd-hl2s.1.3.3 | task | bd-hl2s.1.3 | - |
| B-003d | bd-hl2s.1.3.4 | task | bd-hl2s.1.3 | - |
| B-003e | bd-hl2s.1.3.5 | task | bd-hl2s.1.3 | - |
| B-004 | bd-hl2s.1.4 | feature | bd-hl2s.1 | bd-hl2s.1.3 |
| B-004a | bd-hl2s.1.4.1 | task | bd-hl2s.1.4 | - |
| B-004b | bd-hl2s.1.4.2 | task | bd-hl2s.1.4 | - |
| B-004c | bd-hl2s.1.4.3 | task | bd-hl2s.1.4 | - |
| B-004d | bd-hl2s.1.4.4 | task | bd-hl2s.1.4 | - |
| B-005 | bd-hl2s.1.5 | feature | bd-hl2s.1 | bd-hl2s.1.3 |
| B-005a | bd-hl2s.1.5.1 | task | bd-hl2s.1.5 | - |
| B-005b | bd-hl2s.1.5.2 | task | bd-hl2s.1.5 | - |
| B-005c | bd-hl2s.1.5.3 | task | bd-hl2s.1.5 | - |
| B-005d | bd-hl2s.1.5.4 | task | bd-hl2s.1.5 | - |
| B-005e | bd-hl2s.1.5.5 | task | bd-hl2s.1.5 | - |
| B-005f | bd-hl2s.1.5.6 | task | bd-hl2s.1.5 | - |
| PHASE-1 | bd-hl2s.2 | epic | bd-hl2s | bd-hl2s.1 |
| B-010 | bd-hl2s.2.1 | feature | bd-hl2s.2 | bd-hl2s.1.1 |
| B-010a | bd-hl2s.2.1.1 | task | bd-hl2s.2.1 | - |
| B-010b | bd-hl2s.2.1.2 | task | bd-hl2s.2.1 | - |
| B-010c | bd-hl2s.2.1.3 | task | bd-hl2s.2.1 | - |
| B-010d | bd-hl2s.2.1.4 | task | bd-hl2s.2.1 | - |
| B-011 | bd-hl2s.2.2 | feature | bd-hl2s.2 | bd-hl2s.2.1 |
| B-011a | bd-hl2s.2.2.1 | task | bd-hl2s.2.2 | - |
| B-011b | bd-hl2s.2.2.2 | task | bd-hl2s.2.2 | - |
| B-011c | bd-hl2s.2.2.3 | task | bd-hl2s.2.2 | - |
| B-011d | bd-hl2s.2.2.4 | task | bd-hl2s.2.2 | - |
| B-012 | bd-hl2s.2.3 | feature | bd-hl2s.2 | bd-hl2s.2.1, bd-hl2s.2.2 |
| B-012a | bd-hl2s.2.3.1 | task | bd-hl2s.2.3 | - |
| B-012b | bd-hl2s.2.3.2 | task | bd-hl2s.2.3 | - |
| B-012c | bd-hl2s.2.3.3 | task | bd-hl2s.2.3 | - |
| B-012d | bd-hl2s.2.3.4 | task | bd-hl2s.2.3 | - |
| B-013 | bd-hl2s.2.4 | feature | bd-hl2s.2 | bd-hl2s.2.3, bd-hl2s.1.5 |
| B-013a | bd-hl2s.2.4.1 | task | bd-hl2s.2.4 | - |
| B-013b | bd-hl2s.2.4.2 | task | bd-hl2s.2.4 | - |
| B-013c | bd-hl2s.2.4.3 | task | bd-hl2s.2.4 | - |
| B-014 | bd-hl2s.2.5 | feature | bd-hl2s.2 | bd-hl2s.2.3 |
| B-014a | bd-hl2s.2.5.1 | task | bd-hl2s.2.5 | - |
| B-014b | bd-hl2s.2.5.2 | task | bd-hl2s.2.5 | - |
| B-014c | bd-hl2s.2.5.3 | task | bd-hl2s.2.5 | - |
| B-014d | bd-hl2s.2.5.4 | task | bd-hl2s.2.5 | - |
| PHASE-2 | bd-hl2s.3 | epic | bd-hl2s | bd-hl2s.1 |
| B-020 | bd-hl2s.3.1 | feature | bd-hl2s.3 | bd-hl2s.1.3 |
| B-020a | bd-hl2s.3.1.1 | task | bd-hl2s.3.1 | - |
| B-020b | bd-hl2s.3.1.2 | task | bd-hl2s.3.1 | - |
| B-020c | bd-hl2s.3.1.3 | task | bd-hl2s.3.1 | - |
| B-020d | bd-hl2s.3.1.4 | task | bd-hl2s.3.1 | - |
| B-021 | bd-hl2s.3.2 | feature | bd-hl2s.3 | bd-hl2s.3.1 |
| B-021a | bd-hl2s.3.2.1 | task | bd-hl2s.3.2 | - |
| B-021b | bd-hl2s.3.2.2 | task | bd-hl2s.3.2 | - |
| B-021c | bd-hl2s.3.2.3 | task | bd-hl2s.3.2 | - |
| B-021d | bd-hl2s.3.2.4 | task | bd-hl2s.3.2 | - |
| B-022 | bd-hl2s.3.3 | feature | bd-hl2s.3 | bd-hl2s.3.2 |
| B-022a | bd-hl2s.3.3.1 | task | bd-hl2s.3.3 | - |
| B-022b | bd-hl2s.3.3.2 | task | bd-hl2s.3.3 | - |
| B-022c | bd-hl2s.3.3.3 | task | bd-hl2s.3.3 | - |
| B-022d | bd-hl2s.3.3.4 | task | bd-hl2s.3.3 | - |
| B-022e | bd-hl2s.3.3.5 | task | bd-hl2s.3.3 | - |
| B-023 | bd-hl2s.3.4 | feature | bd-hl2s.3 | bd-hl2s.3.1 |
| B-023a | bd-hl2s.3.4.1 | task | bd-hl2s.3.4 | - |
| B-023b | bd-hl2s.3.4.2 | task | bd-hl2s.3.4 | - |
| B-023c | bd-hl2s.3.4.3 | task | bd-hl2s.3.4 | - |
| B-023d | bd-hl2s.3.4.4 | task | bd-hl2s.3.4 | - |
| B-023e | bd-hl2s.3.4.5 | task | bd-hl2s.3.4 | - |
| B-024 | bd-hl2s.3.5 | feature | bd-hl2s.3 | bd-hl2s.3.1 |
| B-024a | bd-hl2s.3.5.1 | task | bd-hl2s.3.5 | - |
| B-024b | bd-hl2s.3.5.2 | task | bd-hl2s.3.5 | - |
| B-024c | bd-hl2s.3.5.3 | task | bd-hl2s.3.5 | - |
| B-024d | bd-hl2s.3.5.4 | task | bd-hl2s.3.5 | - |
| B-025 | bd-hl2s.3.6 | feature | bd-hl2s.3 | bd-hl2s.3.1 |
| B-025a | bd-hl2s.3.6.1 | task | bd-hl2s.3.6 | - |
| B-025b | bd-hl2s.3.6.2 | task | bd-hl2s.3.6 | - |
| B-025c | bd-hl2s.3.6.3 | task | bd-hl2s.3.6 | - |
| B-025d | bd-hl2s.3.6.4 | task | bd-hl2s.3.6 | - |
| B-026 | bd-hl2s.3.7 | feature | bd-hl2s.3 | bd-hl2s.3.4, bd-hl2s.3.5 |
| B-026a | bd-hl2s.3.7.1 | task | bd-hl2s.3.7 | - |
| B-026b | bd-hl2s.3.7.2 | task | bd-hl2s.3.7 | - |
| B-026c | bd-hl2s.3.7.3 | task | bd-hl2s.3.7 | - |
| B-026d | bd-hl2s.3.7.4 | task | bd-hl2s.3.7 | - |
| B-026e | bd-hl2s.3.7.5 | task | bd-hl2s.3.7 | - |
| B-027 | bd-hl2s.3.8 | feature | bd-hl2s.3 | bd-hl2s.3.4, bd-hl2s.1.5 |
| B-027a | bd-hl2s.3.8.1 | task | bd-hl2s.3.8 | - |
| B-027b | bd-hl2s.3.8.2 | task | bd-hl2s.3.8 | - |
| B-027c | bd-hl2s.3.8.3 | task | bd-hl2s.3.8 | - |
| B-027d | bd-hl2s.3.8.4 | task | bd-hl2s.3.8 | - |
| B-028 | bd-hl2s.3.9 | feature | bd-hl2s.3 | bd-hl2s.3.4 |
| B-028a | bd-hl2s.3.9.1 | task | bd-hl2s.3.9 | - |
| B-028b | bd-hl2s.3.9.2 | task | bd-hl2s.3.9 | - |
| B-028c | bd-hl2s.3.9.3 | task | bd-hl2s.3.9 | - |
| B-028d | bd-hl2s.3.9.4 | task | bd-hl2s.3.9 | - |
| PHASE-3 | bd-hl2s.4 | epic | bd-hl2s | bd-hl2s.3, bd-hl2s.2, bd-hl2s.1 |
| B-030 | bd-hl2s.4.1 | feature | bd-hl2s.4 | bd-hl2s.3.4, bd-hl2s.2.3 |
| B-030a | bd-hl2s.4.1.1 | task | bd-hl2s.4.1 | - |
| B-030b | bd-hl2s.4.1.2 | task | bd-hl2s.4.1 | - |
| B-030c | bd-hl2s.4.1.3 | task | bd-hl2s.4.1 | - |
| B-030d | bd-hl2s.4.1.4 | task | bd-hl2s.4.1 | - |
| B-030e | bd-hl2s.4.1.5 | task | bd-hl2s.4.1 | - |
| B-031 | bd-hl2s.4.2 | feature | bd-hl2s.4 | bd-hl2s.4.1 |
| B-031a | bd-hl2s.4.2.1 | task | bd-hl2s.4.2 | - |
| B-031b | bd-hl2s.4.2.2 | task | bd-hl2s.4.2 | - |
| B-031c | bd-hl2s.4.2.3 | task | bd-hl2s.4.2 | - |
| B-031d | bd-hl2s.4.2.4 | task | bd-hl2s.4.2 | - |
| B-031e | bd-hl2s.4.2.5 | task | bd-hl2s.4.2 | - |
| B-032 | bd-hl2s.4.3 | feature | bd-hl2s.4 | bd-hl2s.4.2 |
| B-032a | bd-hl2s.4.3.1 | task | bd-hl2s.4.3 | - |
| B-032b | bd-hl2s.4.3.2 | task | bd-hl2s.4.3 | - |
| B-032c | bd-hl2s.4.3.3 | task | bd-hl2s.4.3 | - |
| B-033 | bd-hl2s.4.4 | feature | bd-hl2s.4 | bd-hl2s.4.1, bd-hl2s.4.2 |
| B-033a | bd-hl2s.4.4.1 | task | bd-hl2s.4.4 | - |
| B-033b | bd-hl2s.4.4.2 | task | bd-hl2s.4.4 | - |
| B-033c | bd-hl2s.4.4.3 | task | bd-hl2s.4.4 | - |
| B-033d | bd-hl2s.4.4.4 | task | bd-hl2s.4.4 | - |
| B-033e | bd-hl2s.4.4.5 | task | bd-hl2s.4.4 | - |
| B-034 | bd-hl2s.4.5 | feature | bd-hl2s.4 | bd-hl2s.4.1, bd-hl2s.4.2, bd-hl2s.1.5 |
| B-034a | bd-hl2s.4.5.1 | task | bd-hl2s.4.5 | - |
| B-034b | bd-hl2s.4.5.2 | task | bd-hl2s.4.5 | - |
| B-034c | bd-hl2s.4.5.3 | task | bd-hl2s.4.5 | - |
| B-034d | bd-hl2s.4.5.4 | task | bd-hl2s.4.5 | - |
| B-035 | bd-hl2s.4.6 | feature | bd-hl2s.4 | bd-hl2s.4.3, bd-hl2s.4.5 |
| B-035a | bd-hl2s.4.6.1 | task | bd-hl2s.4.6 | - |
| B-035b | bd-hl2s.4.6.2 | task | bd-hl2s.4.6 | - |
| B-035c | bd-hl2s.4.6.3 | task | bd-hl2s.4.6 | - |
| PHASE-4 | bd-hl2s.5 | epic | bd-hl2s | bd-hl2s.3, bd-hl2s.1 |
| B-040 | bd-hl2s.5.1 | feature | bd-hl2s.5 | bd-hl2s.3.6 |
| B-040a | bd-hl2s.5.1.1 | task | bd-hl2s.5.1 | - |
| B-040b | bd-hl2s.5.1.2 | task | bd-hl2s.5.1 | - |
| B-040c | bd-hl2s.5.1.3 | task | bd-hl2s.5.1 | - |
| B-040d | bd-hl2s.5.1.4 | task | bd-hl2s.5.1 | - |
| B-041 | bd-hl2s.5.2 | feature | bd-hl2s.5 | bd-hl2s.3.5, bd-hl2s.5.1 |
| B-041a | bd-hl2s.5.2.1 | task | bd-hl2s.5.2 | - |
| B-041b | bd-hl2s.5.2.2 | task | bd-hl2s.5.2 | - |
| B-041c | bd-hl2s.5.2.3 | task | bd-hl2s.5.2 | - |
| B-041d | bd-hl2s.5.2.4 | task | bd-hl2s.5.2 | - |
| B-042 | bd-hl2s.5.3 | feature | bd-hl2s.5 | bd-hl2s.5.1, bd-hl2s.3.6 |
| B-042a | bd-hl2s.5.3.1 | task | bd-hl2s.5.3 | - |
| B-042b | bd-hl2s.5.3.2 | task | bd-hl2s.5.3 | - |
| B-042c | bd-hl2s.5.3.3 | task | bd-hl2s.5.3 | - |
| B-043 | bd-hl2s.5.4 | feature | bd-hl2s.5 | bd-hl2s.1.5, bd-hl2s.5.1 |
| PHASE-5 | bd-hl2s.6 | epic | bd-hl2s | bd-hl2s.4, bd-hl2s.2, bd-hl2s.5, bd-hl2s.3, bd-hl2s.1, bd-hl2s.8 |
| B-049 | bd-hl2s.6.1 | feature | bd-hl2s.6 | bd-hl2s.4.5, bd-hl2s.2.5, bd-hl2s.5.4, bd-hl2s.3.9 |
| B-049a | bd-hl2s.6.1.1 | task | bd-hl2s.6.1 | - |
| B-049b | bd-hl2s.6.1.2 | task | bd-hl2s.6.1 | - |
| B-049c | bd-hl2s.6.1.3 | task | bd-hl2s.6.1 | - |
| B-049d | bd-hl2s.6.1.4 | task | bd-hl2s.6.1 | - |
| B-049e | bd-hl2s.6.1.5 | task | bd-hl2s.6.1 | - |
| B-050 | bd-hl2s.6.2 | feature | bd-hl2s.6 | bd-hl2s.3.5, bd-hl2s.6.1 |
| B-050a | bd-hl2s.6.2.1 | task | bd-hl2s.6.2 | - |
| B-050b | bd-hl2s.6.2.2 | task | bd-hl2s.6.2 | - |
| B-050c | bd-hl2s.6.2.3 | task | bd-hl2s.6.2 | - |
| B-050d | bd-hl2s.6.2.4 | task | bd-hl2s.6.2 | - |
| B-050e | bd-hl2s.6.2.5 | task | bd-hl2s.6.2 | - |
| B-050f | bd-hl2s.6.2.6 | task | bd-hl2s.6.2 | - |
| B-050g | bd-hl2s.6.2.7 | task | bd-hl2s.6.2 | - |
| B-051 | bd-hl2s.6.3 | feature | bd-hl2s.6 | bd-hl2s.6.1 |
| B-052 | bd-hl2s.6.4 | feature | bd-hl2s.6 | bd-hl2s.6.1 |
| B-052a | bd-hl2s.6.4.1 | task | bd-hl2s.6.4 | - |
| B-052b | bd-hl2s.6.4.2 | task | bd-hl2s.6.4 | - |
| B-052c | bd-hl2s.6.4.3 | task | bd-hl2s.6.4 | - |
| B-052d | bd-hl2s.6.4.4 | task | bd-hl2s.6.4 | - |
| B-053 | bd-hl2s.6.5 | feature | bd-hl2s.6 | bd-hl2s.6.4 |
| B-054 | bd-hl2s.6.6 | feature | bd-hl2s.6 | bd-hl2s.1.2, bd-hl2s.6.2, bd-hl2s.6.3, bd-hl2s.6.4, bd-hl2s.6.5 |
| B-055 | bd-hl2s.6.7 | feature | bd-hl2s.6 | bd-hl2s.4.4, bd-hl2s.4.6, bd-hl2s.8.1, bd-hl2s.8.2 |
| B-055a | bd-hl2s.6.7.1 | task | bd-hl2s.6.7 | - |
| B-055b | bd-hl2s.6.7.2 | task | bd-hl2s.6.7 | - |
| B-055c | bd-hl2s.6.7.3 | task | bd-hl2s.6.7 | - |
| B-055d | bd-hl2s.6.7.4 | task | bd-hl2s.6.7 | - |
| PHASE-6 | bd-hl2s.7 | epic | bd-hl2s | bd-hl2s.3, bd-hl2s.6, bd-hl2s.4, bd-hl2s.8, bd-hl2s.1 |
| B-060 | bd-hl2s.7.1 | feature | bd-hl2s.7 | bd-hl2s.3.4, bd-hl2s.6.1 |
| B-060a | bd-hl2s.7.1.1 | task | bd-hl2s.7.1 | - |
| B-060b | bd-hl2s.7.1.2 | task | bd-hl2s.7.1 | - |
| B-060c | bd-hl2s.7.1.3 | task | bd-hl2s.7.1 | - |
| B-060d | bd-hl2s.7.1.4 | task | bd-hl2s.7.1 | - |
| B-063 | bd-hl2s.7.2 | feature | bd-hl2s.7 | bd-hl2s.4.4, bd-hl2s.7.1, bd-hl2s.8.1, bd-hl2s.8.2 |
| B-063a | bd-hl2s.7.2.1 | task | bd-hl2s.7.2 | - |
| B-063b | bd-hl2s.7.2.2 | task | bd-hl2s.7.2 | - |
| B-063c | bd-hl2s.7.2.3 | task | bd-hl2s.7.2 | - |
| B-063d | bd-hl2s.7.2.4 | task | bd-hl2s.7.2 | - |
| B-061 | bd-hl2s.7.3 | feature | bd-hl2s.7 | bd-hl2s.6.2, bd-hl2s.6.3, bd-hl2s.6.4, bd-hl2s.6.5, bd-hl2s.7.1, bd-hl2s.7.2, bd-hl2s.1.5 |
| B-061a | bd-hl2s.7.3.1 | task | bd-hl2s.7.3 | - |
| B-061b | bd-hl2s.7.3.2 | task | bd-hl2s.7.3 | - |
| B-061c | bd-hl2s.7.3.3 | task | bd-hl2s.7.3 | - |
| B-061d | bd-hl2s.7.3.4 | task | bd-hl2s.7.3 | - |
| B-061e | bd-hl2s.7.3.5 | task | bd-hl2s.7.3 | - |
| B-062 | bd-hl2s.7.4 | feature | bd-hl2s.7 | bd-hl2s.7.3 |
| B-062a | bd-hl2s.7.4.1 | task | bd-hl2s.7.4 | - |
| B-062b | bd-hl2s.7.4.2 | task | bd-hl2s.7.4 | - |
| B-062c | bd-hl2s.7.4.3 | task | bd-hl2s.7.4 | - |
| PHASE-7 | bd-hl2s.8 | epic | bd-hl2s | bd-hl2s.1, bd-hl2s.3 |
| B-070 | bd-hl2s.8.1 | feature | bd-hl2s.8 | bd-hl2s.1.3, bd-hl2s.1.5 |
| B-070a | bd-hl2s.8.1.1 | task | bd-hl2s.8.1 | - |
| B-070b | bd-hl2s.8.1.2 | task | bd-hl2s.8.1 | - |
| B-070c | bd-hl2s.8.1.3 | task | bd-hl2s.8.1 | - |
| B-070d | bd-hl2s.8.1.4 | task | bd-hl2s.8.1 | - |
| B-070e | bd-hl2s.8.1.5 | task | bd-hl2s.8.1 | - |
| B-070f | bd-hl2s.8.1.6 | task | bd-hl2s.8.1 | - |
| B-071 | bd-hl2s.8.2 | feature | bd-hl2s.8 | bd-hl2s.3.1 |
| B-072 | bd-hl2s.8.3 | feature | bd-hl2s.8 | bd-hl2s.3.1, bd-hl2s.3.2, bd-hl2s.1.3 |
| B-072a | bd-hl2s.8.3.1 | task | bd-hl2s.8.3 | - |
| B-072b | bd-hl2s.8.3.2 | task | bd-hl2s.8.3 | - |
| B-072c | bd-hl2s.8.3.3 | task | bd-hl2s.8.3 | - |
| B-072d | bd-hl2s.8.3.4 | task | bd-hl2s.8.3 | - |
| B-072e | bd-hl2s.8.3.5 | task | bd-hl2s.8.3 | - |
| B-073 | bd-hl2s.8.4 | feature | bd-hl2s.8 | bd-hl2s.8.3 |
| B-073a | bd-hl2s.8.4.1 | task | bd-hl2s.8.4 | - |
| B-073b | bd-hl2s.8.4.2 | task | bd-hl2s.8.4 | - |
| B-073c | bd-hl2s.8.4.3 | task | bd-hl2s.8.4 | - |
| B-073d | bd-hl2s.8.4.4 | task | bd-hl2s.8.4 | - |
| B-073e | bd-hl2s.8.4.5 | task | bd-hl2s.8.4 | - |
| B-074 | bd-hl2s.8.5 | feature | bd-hl2s.8 | bd-hl2s.8.3 |
| PHASE-8 | bd-hl2s.9 | epic | bd-hl2s | bd-hl2s.3, bd-hl2s.1 |
| B-080 | bd-hl2s.9.1 | feature | bd-hl2s.9 | bd-hl2s.3.1 |
| B-081 | bd-hl2s.9.2 | feature | bd-hl2s.9 | bd-hl2s.1.3 |
| B-082 | bd-hl2s.9.3 | feature | bd-hl2s.9 | bd-hl2s.3.1 |
| B-083 | bd-hl2s.9.4 | feature | bd-hl2s.9 | bd-hl2s.3.6 |
| PHASE-9 | bd-hl2s.10 | epic | bd-hl2s | bd-hl2s.8, bd-hl2s.9 |
| B-090 | bd-hl2s.10.1 | feature | bd-hl2s.10 | bd-hl2s.8.3, bd-hl2s.9.1 |
| B-091 | bd-hl2s.10.2 | feature | bd-hl2s.10 | bd-hl2s.10.1 |
| B-092 | bd-hl2s.10.3 | feature | bd-hl2s.10 | bd-hl2s.8.4, bd-hl2s.10.1 |
| PHASE-10 | bd-hl2s.11 | epic | bd-hl2s | bd-hl2s.3, bd-hl2s.8, bd-hl2s.9, bd-hl2s.7 |
| B-100 | bd-hl2s.11.1 | feature | bd-hl2s.11 | bd-hl2s.3.1, bd-hl2s.8.2 |
| B-101 | bd-hl2s.11.2 | feature | bd-hl2s.11 | bd-hl2s.11.1, bd-hl2s.9.2 |
| B-102 | bd-hl2s.11.3 | feature | bd-hl2s.11 | bd-hl2s.11.1 |
| B-103 | bd-hl2s.11.4 | feature | bd-hl2s.11 | bd-hl2s.11.1 |
| B-104 | bd-hl2s.11.5 | feature | bd-hl2s.11 | bd-hl2s.11.1, bd-hl2s.7.1, bd-hl2s.7.2 |
| B-105 | bd-hl2s.11.6 | feature | bd-hl2s.11 | bd-hl2s.11.2 |
| B-106 | bd-hl2s.11.7 | feature | bd-hl2s.11 | bd-hl2s.8.2, bd-hl2s.11.2 |
| PHASE-11 | bd-hl2s.12 | epic | bd-hl2s | bd-hl2s.3, bd-hl2s.9, bd-hl2s.6 |
| B-110 | bd-hl2s.12.1 | feature | bd-hl2s.12 | bd-hl2s.3.1 |
| B-111 | bd-hl2s.12.2 | feature | bd-hl2s.12 | bd-hl2s.12.1, bd-hl2s.9.2 |
| B-112 | bd-hl2s.12.3 | feature | bd-hl2s.12 | bd-hl2s.12.1, bd-hl2s.3.4 |
| B-113 | bd-hl2s.12.4 | feature | bd-hl2s.12 | bd-hl2s.12.3, bd-hl2s.6.2 |
| B-113a | bd-hl2s.12.4.1 | task | bd-hl2s.12.4 | - |
| B-113b | bd-hl2s.12.4.2 | task | bd-hl2s.12.4 | - |
| B-113c | bd-hl2s.12.4.3 | task | bd-hl2s.12.4 | - |
| B-113d | bd-hl2s.12.4.4 | task | bd-hl2s.12.4 | - |
| B-113e | bd-hl2s.12.4.5 | task | bd-hl2s.12.4 | - |
| B-114 | bd-hl2s.12.5 | feature | bd-hl2s.12 | bd-hl2s.12.4 |
| B-115 | bd-hl2s.12.6 | feature | bd-hl2s.12 | bd-hl2s.12.4 |
| PHASE-12 | bd-hl2s.13 | epic | bd-hl2s | bd-hl2s.3, bd-hl2s.9, bd-hl2s.4, bd-hl2s.11, bd-hl2s.7 |
| B-120 | bd-hl2s.13.1 | feature | bd-hl2s.13 | bd-hl2s.3.1 |
| B-121 | bd-hl2s.13.2 | feature | bd-hl2s.13 | bd-hl2s.13.1, bd-hl2s.9.2 |
| B-122 | bd-hl2s.13.3 | feature | bd-hl2s.13 | bd-hl2s.13.1 |
| B-123 | bd-hl2s.13.4 | feature | bd-hl2s.13 | bd-hl2s.13.3, bd-hl2s.4.4 |
| B-124 | bd-hl2s.13.5 | feature | bd-hl2s.13 | bd-hl2s.13.4 |
| B-125 | bd-hl2s.13.6 | feature | bd-hl2s.13 | bd-hl2s.13.4, bd-hl2s.13.5 |
| B-126 | bd-hl2s.13.7 | feature | bd-hl2s.13 | bd-hl2s.13.4, bd-hl2s.11.1 |
| B-127 | bd-hl2s.13.8 | feature | bd-hl2s.13 | bd-hl2s.13.3 |
| B-128 | bd-hl2s.13.9 | feature | bd-hl2s.13 | bd-hl2s.13.4, bd-hl2s.7.1 |
| PHASE-13 | bd-hl2s.14 | epic | bd-hl2s | bd-hl2s.11, bd-hl2s.12, bd-hl2s.8 |
| B-130 | bd-hl2s.14.1 | feature | bd-hl2s.14 | bd-hl2s.11.5, bd-hl2s.11.4 |
| B-131 | bd-hl2s.14.2 | feature | bd-hl2s.14 | bd-hl2s.12.5 |
| B-132 | bd-hl2s.14.3 | feature | bd-hl2s.14 | bd-hl2s.11.3 |
| B-133 | bd-hl2s.14.4 | feature | bd-hl2s.14 | bd-hl2s.8.1, bd-hl2s.8.2 |
| B-134 | bd-hl2s.14.5 | feature | bd-hl2s.14 | - |

## PHASE-0 — Phase 0: Boundary, Packaging, Contract Freeze

- **Actual bead**: `bd-hl2s.1`
- **Scope**: `MVP`
- **Goal**: Lock the active product boundary so nothing drifts further. Establish the manifest contract that all subsequent phases build against.
- **Rationale**: The repo is already a CLI/SDK-only codebase, but its product story is still split between the legacy direct-command surface and the planned agent-first grammar. Without freezing the boundary, compatibility policy, and command contract first, later phases will duplicate logic and surprise users.
- **Depends on phases**: none

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-001: Tighten packaging metadata and product story

- **Actual bead**: `bd-hl2s.1.1`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-0`
- **Depends on**: nothing

**Intent**

Make `pyproject.toml`, README positioning, and install-time metadata tell the same truth about the product: this repo is the active `notebooklm` CLI/SDK base that is evolving toward an agent-first contract.

**Why This Exists**

The current repo still reflects the legacy package/API boundary, so these tasks freeze the product surface before more architecture is layered on top.

**Phase Context**

- Goal link: Lock the active product boundary so nothing drifts further. Establish the manifest contract that all subsequent phases build against.
- Rationale link: The repo is already a CLI/SDK-only codebase, but its product story is still split between the legacy direct-command surface and the planned agent-first grammar. Without freezing the boundary, compatibility policy, and command contract first, later phases will duplicate logic and surprise users.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- Notes: This bead is about truthfulness and migration safety, not just URL cleanup.

**Acceptance**

- `pip install -e .` works; `pip show` metadata is correct; README/help text no longer contradict the active product boundary
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-001a` -> `bd-hl2s.1.1.1`: Verify `[project]` metadata, entry points, and package discovery match the active CLI/SDK boundary
- `B-001b` -> `bd-hl2s.1.1.2`: Ensure README/install docs describe the current supported surface and the planned agent-first direction without promising removed legacy components
- `B-001c` -> `bd-hl2s.1.1.3`: Keep package/install names stable for `pip install` / `uv` usage even if command grammar changes

### B-002: Freeze CLI grammar, compatibility, and output contract

- **Actual bead**: `bd-hl2s.1.2`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-0`
- **Depends on**: bd-hl2s.1.1

**Intent**

Define the canonical command tree, context-resolution rules, alias/deprecation behavior, human-output expectations, and JSON/error contract before new command families proliferate.

**Why This Exists**

The current repo still reflects the legacy package/API boundary, so these tasks freeze the product surface before more architecture is layered on top.

**Phase Context**

- Goal link: Lock the active product boundary so nothing drifts further. Establish the manifest contract that all subsequent phases build against.
- Rationale link: The repo is already a CLI/SDK-only codebase, but its product story is still split between the legacy direct-command surface and the planned agent-first grammar. Without freezing the boundary, compatibility policy, and command contract first, later phases will duplicate logic and surprise users.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- Notes: This is the user-facing contract freeze bead for the whole program.

**Acceptance**

- There is one documented command/output contract that manifest, help text, docs, and implementation can all point to; backward compatibility is explicit instead of accidental
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-002a` -> `bd-hl2s.1.2.1`: Freeze the canonical command grammar (`auth`, `notebook`, `source`, `sync`, workflow roots, maintenance commands)
- `B-002b` -> `bd-hl2s.1.2.2`: Document notebook/context resolution precedence, interactive vs non-interactive exit behavior, and human vs JSON output expectations
- `B-002c` -> `bd-hl2s.1.2.3`: Explicitly decide which legacy commands remain as aliases, what warning copy they emit, and which old forms are intentionally unsupported

### B-003: Create `contracts/capabilities.yaml` manifest

- **Actual bead**: `bd-hl2s.1.3`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-0`
- **Depends on**: bd-hl2s.1.1

**Intent**

Create the canonical manifest file that defines all commands, intents, risk tiers, cache entities, and doctor checks. This is the **single source of truth** the entire system builds against.

**Why This Exists**

The current repo still reflects the legacy package/API boundary, so these tasks freeze the product surface before more architecture is layered on top.

**Phase Context**

- Goal link: Lock the active product boundary so nothing drifts further. Establish the manifest contract that all subsequent phases build against.
- Rationale link: The repo is already a CLI/SDK-only codebase, but its product story is still split between the legacy direct-command surface and the planned agent-first grammar. Without freezing the boundary, compatibility policy, and command contract first, later phases will duplicate logic and surprise users.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- Rationale: Revised §7 — "Router, doctor, docs, JSON schema và tests phải cùng nhìn vào một contract." ACFS manifest pattern. Without this, we get drift between CLI help, router logic, doctor checks, and documentation.

**Acceptance**

- YAML parses cleanly; a Python loader can read it; all MVP commands are present with correct intents/tiers
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-003a` -> `bd-hl2s.1.3.1`: Create `src/notebooklm/contracts/capabilities.yaml` with MVP commands (ask, overview, summarize, study-guide, audio, research.start, research.wait, notebook.delete, source.delete, cache.prune)
- `B-003b` -> `bd-hl2s.1.3.2`: Add command metadata for aliases/deprecation state and whether each command is read-only, waitable, destructive, or approval-gated
- `B-003c` -> `bd-hl2s.1.3.3`: Add `cache_entities` list (notebooks, sources, artifacts, research_runs, query_runs, query_results, sync_runs, run_events, approval_requests)
- `B-003d` -> `bd-hl2s.1.3.4`: Add `doctor_checks` list (auth_snapshot_present, auth_snapshot_fresh, build_label_present, db_openable, schema_current, write_permissions_ok, notebooklm_home_consistent)
- `B-003e` -> `bd-hl2s.1.3.5`: Add risk_tier mapping per CONTRACT_NORMALIZATION §1 (T0_READ through T3_DESTRUCTIVE)

### B-004: Create contract test suite for capabilities manifest

- **Actual bead**: `bd-hl2s.1.4`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-0`
- **Depends on**: bd-hl2s.1.3

**Intent**

Write tests that validate the manifest against actual registered CLI commands and JSON envelope schemas. These tests **break** if someone adds a command without updating the manifest.

**Why This Exists**

The current repo still reflects the legacy package/API boundary, so these tasks freeze the product surface before more architecture is layered on top.

**Phase Context**

- Goal link: Lock the active product boundary so nothing drifts further. Establish the manifest contract that all subsequent phases build against.
- Rationale link: The repo is already a CLI/SDK-only codebase, but its product story is still split between the legacy direct-command surface and the planned agent-first grammar. Without freezing the boundary, compatibility policy, and command contract first, later phases will duplicate logic and surprise users.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Tests pass; adding an unregistered command or undocumented alias fails the test
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-004a` -> `bd-hl2s.1.4.1`: Test that every registered Click/Typer command maps to a manifest entry
- `B-004b` -> `bd-hl2s.1.4.2`: Test that every manifest command has a valid intent and risk tier
- `B-004c` -> `bd-hl2s.1.4.3`: Test that alias/deprecation metadata matches the implemented compatibility layer
- `B-004d` -> `bd-hl2s.1.4.4`: Test that JSON envelope schema matches CONTRACT_NORMALIZATION §3

### B-005: Create `src/notebooklm/contracts/` Python package

- **Actual bead**: `bd-hl2s.1.5`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-0`
- **Depends on**: bd-hl2s.1.3

**Intent**

Create the contracts package with loaders for capabilities.yaml, envelope schema definitions, intent enums, and RPC map.

**Why This Exists**

The current repo still reflects the legacy package/API boundary, so these tasks freeze the product surface before more architecture is layered on top.

**Phase Context**

- Goal link: Lock the active product boundary so nothing drifts further. Establish the manifest contract that all subsequent phases build against.
- Rationale link: The repo is already a CLI/SDK-only codebase, but its product story is still split between the legacy direct-command surface and the planned agent-first grammar. Without freezing the boundary, compatibility policy, and command contract first, later phases will duplicate logic and surprise users.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `from notebooklm.contracts import load_capabilities, RiskTier, Intent, Envelope, CommandSpec` works
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-005a` -> `bd-hl2s.1.5.1`: `__init__.py` with manifest loader
- `B-005b` -> `bd-hl2s.1.5.2`: `envelope_schema.py` — Pydantic/dataclass models for canonical JSON envelope
- `B-005c` -> `bd-hl2s.1.5.3`: `intents.py` — Intent enum (LOCAL_METADATA, REMOTE_METADATA, QUERY, GENERATION, RESEARCH, DOCTOR, WORKSPACE_QUERY, WORKSPACE_COMPARE, RADAR_STATUS, RADAR_BRIEF, INBOX_TRIAGE, INBOX_APPLY)
- `B-005d` -> `bd-hl2s.1.5.4`: `rpc_map.py` — mapping from intent+mode to RPC method/endpoint
- `B-005e` -> `bd-hl2s.1.5.5`: `command_specs.py` — typed command/alias metadata for help text, routing, and compatibility checks
- `B-005f` -> `bd-hl2s.1.5.6`: `risk.py` — risk tier enum and guard decorator

## PHASE-1 — Phase 1: Auth/Runtime Hardening

- **Actual bead**: `bd-hl2s.2`
- **Scope**: `MVP`
- **Goal**: Make the transport layer fully agent-ready by ensuring `build_label` is first-class, auth refresh is complete, and URL building is unified.
- **Rationale**: `bl` is the biggest transport gap. Without it, RPC calls may silently fail or return stale responses. The current code has `bl` as optional; the new design makes it mandatory.
- **Depends on phases**: bd-hl2s.1

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-010: Add `build_label` to `AuthTokens` and session snapshot

- **Actual bead**: `bd-hl2s.2.1`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-1`
- **Depends on**: bd-hl2s.1.1

**Intent**

Extend `AuthTokens` dataclass to include `build_label` as a mandatory field. Update `fetch_tokens()` to extract `bl` from the NotebookLM homepage alongside `SNlM0e` and `FdrFJe`.

**Why This Exists**

Auth/runtime already exists, but it still lacks `build_label` as a first-class field and the transport contract remains narrower than the revised plan requires.

**Phase Context**

- Goal link: Make the transport layer fully agent-ready by ensuring `build_label` is first-class, auth refresh is complete, and URL building is unified.
- Rationale link: `bl` is the biggest transport gap. Without it, RPC calls may silently fail or return stale responses. The current code has `bl` as optional; the new design makes it mandatory.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- Risk note: `bl` extraction depends on NotebookLM homepage HTML structure. May need reverse-engineering pass (Open Question #1 from Revised §22).

**Acceptance**

- `AuthTokens.from_storage()` returns object with non-empty `build_label`
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-010a` -> `bd-hl2s.2.1.1`: Add `build_label: str` field to `AuthTokens`
- `B-010b` -> `bd-hl2s.2.1.2`: Update homepage HTML parser to extract `bl` value
- `B-010c` -> `bd-hl2s.2.1.3`: Validate `bl` is non-empty on every snapshot creation
- `B-010d` -> `bd-hl2s.2.1.4`: Add `bl` to `storage_state.json` persistence if not already

### B-011: Unify URL builder to always send `bl`

- **Actual bead**: `bd-hl2s.2.2`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-1`
- **Depends on**: bd-hl2s.2.1

**Intent**

Patch `ClientCore._build_url()` to use a unified helper that always includes `rpcids`, `source-path`, `f.sid`, `bl`, and `rt` parameters.

**Why This Exists**

Auth/runtime already exists, but it still lacks `build_label` as a first-class field and the transport contract remains narrower than the revised plan requires.

**Phase Context**

- Goal link: Make the transport layer fully agent-ready by ensuring `build_label` is first-class, auth refresh is complete, and URL building is unified.
- Rationale link: `bl` is the biggest transport gap. Without it, RPC calls may silently fail or return stale responses. The current code has `bl` as optional; the new design makes it mandatory.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Every outgoing RPC URL includes `bl`; no code path skips it
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-011a` -> `bd-hl2s.2.2.1`: Create `_build_rpc_params()` helper that constructs the full param dict
- `B-011b` -> `bd-hl2s.2.2.2`: Refactor `_build_url()` to use the helper
- `B-011c` -> `bd-hl2s.2.2.3`: Ensure `QUERY_URL` and `BATCHEXECUTE_URL` both receive `bl`
- `B-011d` -> `bd-hl2s.2.2.4`: Add test that URL always contains `bl=` parameter

### B-012: Complete auth refresh to update all three dynamic fields

- **Actual bead**: `bd-hl2s.2.3`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-1`
- **Depends on**: bd-hl2s.2.1, bd-hl2s.2.2

**Intent**

Current `refresh_auth()` only refreshes CSRF + session ID. Must also refresh `bl`.

**Why This Exists**

Auth/runtime already exists, but it still lacks `build_label` as a first-class field and the transport contract remains narrower than the revised plan requires.

**Phase Context**

- Goal link: Make the transport layer fully agent-ready by ensuring `build_label` is first-class, auth refresh is complete, and URL building is unified.
- Rationale link: `bl` is the biggest transport gap. Without it, RPC calls may silently fail or return stale responses. The current code has `bl` as optional; the new design makes it mandatory.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- After `bl` rotation on Google's side, CLI auto-recovers without browser
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-012a` -> `bd-hl2s.2.3.1`: Update `refresh_auth()` to re-extract `bl` from homepage
- `B-012b` -> `bd-hl2s.2.3.2`: Add retry logic: on 401/403 or build mismatch, refresh once then retry
- `B-012c` -> `bd-hl2s.2.3.3`: Only reopen browser if cookie-based refresh fails
- `B-012d` -> `bd-hl2s.2.3.4`: Write auth snapshot to DB after successful refresh

### B-013: Add `auth inspect` and `auth refresh` CLI commands

- **Actual bead**: `bd-hl2s.2.4`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-1`
- **Depends on**: bd-hl2s.2.3, bd-hl2s.1.5

**Intent**

New commands for agent diagnostics. `auth inspect` shows snapshot fields (redacted). `auth refresh` forces a refresh cycle.

**Why This Exists**

Auth/runtime already exists, but it still lacks `build_label` as a first-class field and the transport contract remains narrower than the revised plan requires.

**Phase Context**

- Goal link: Make the transport layer fully agent-ready by ensuring `build_label` is first-class, auth refresh is complete, and URL building is unified.
- Rationale link: `bl` is the biggest transport gap. Without it, RPC calls may silently fail or return stale responses. The current code has `bl` as optional; the new design makes it mandatory.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Agent can check auth health programmatically
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-013a` -> `bd-hl2s.2.4.1`: `notebooklm auth inspect` — shows profile, snapshot age, bl presence, csrf presence, cookie fingerprint (not raw cookies)
- `B-013b` -> `bd-hl2s.2.4.2`: `notebooklm auth refresh` — forces homepage GET refresh, writes new snapshot
- `B-013c` -> `bd-hl2s.2.4.3`: Both support `--json` with canonical envelope

### B-014: Add auth refresh + retry + 429 handling to transport

- **Actual bead**: `bd-hl2s.2.5`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-1`
- **Depends on**: bd-hl2s.2.3

**Intent**

Production-grade transport hardening: retry on transient errors, auth refresh on 401/403, backoff on 429.

**Why This Exists**

Auth/runtime already exists, but it still lacks `build_label` as a first-class field and the transport contract remains narrower than the revised plan requires.

**Phase Context**

- Goal link: Make the transport layer fully agent-ready by ensuring `build_label` is first-class, auth refresh is complete, and URL building is unified.
- Rationale link: `bl` is the biggest transport gap. Without it, RPC calls may silently fail or return stale responses. The current code has `bl` as optional; the new design makes it mandatory.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- CLI survives transient auth expiry and rate limiting without user intervention
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-014a` -> `bd-hl2s.2.5.1`: Implement retry decorator with configurable max retries
- `B-014b` -> `bd-hl2s.2.5.2`: Auto-refresh auth on 401/403 (once per request chain)
- `B-014c` -> `bd-hl2s.2.5.3`: Exponential backoff on 429 with jitter
- `B-014d` -> `bd-hl2s.2.5.4`: Record retry/refresh events in run_events (links to Phase 4)

## PHASE-2 — Phase 2: SQLite + Profile Isolation

- **Actual bead**: `bd-hl2s.3`
- **Scope**: `MVP`
- **Goal**: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- **Rationale**: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.
- **Depends on phases**: bd-hl2s.1

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-020: Bootstrap SQLite database with migration framework

- **Actual bead**: `bd-hl2s.3.1`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-2`
- **Depends on**: bd-hl2s.1.3

**Intent**

Create `cache.db` in `NOTEBOOKLM_HOME` with a migration system (simple version-table approach).

**Why This Exists**

Current state is still file-backed and ephemeral. This phase introduces durable, inspectable, profile-scoped local state.

**Phase Context**

- Goal link: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- Rationale link: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `db.py` creates/opens DB, runs migrations idempotently, WAL mode active
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-020a` -> `bd-hl2s.3.1.1`: Create `src/notebooklm/local/db.py` — connection factory, WAL mode, journal settings
- `B-020b` -> `bd-hl2s.3.1.2`: Create `src/notebooklm/local/migrations.py` — version-tracked migration runner
- `B-020c` -> `bd-hl2s.3.1.3`: Create initial migration (v1) with all MVP tables
- `B-020d` -> `bd-hl2s.3.1.4`: Add `schema_version` to `app_state` table

### B-021: Create `profiles` and `auth_snapshots` tables

- **Actual bead**: `bd-hl2s.3.2`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-2`
- **Depends on**: bd-hl2s.3.1

**Intent**

Per Revised §9.2 and CONTRACT_NORMALIZATION. Profile isolation is foundational — every subsequent table is profile-scoped.

**Why This Exists**

Current state is still file-backed and ephemeral. This phase introduces durable, inspectable, profile-scoped local state.

**Phase Context**

- Goal link: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- Rationale link: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Can create/switch profiles; auth snapshots persist across restarts
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-021a` -> `bd-hl2s.3.2.1`: Create `profiles` table (profile_id PK, display_name, account_email, is_default, storage_state_path, browser_profile_path, timestamps)
- `B-021b` -> `bd-hl2s.3.2.2`: Create `auth_snapshots` table (profile_id FK, cookie_fingerprint, csrf_token, session_id, build_label, captured_at, validated_at, status, source)
- `B-021c` -> `bd-hl2s.3.2.3`: Create `app_state` table (active_profile_id, current_notebook_id, current_conversation_id, schema_version)
- `B-021d` -> `bd-hl2s.3.2.4`: Create `profiles/manager.py` — CRUD + switching logic

### B-022: Legacy profile migration

- **Actual bead**: `bd-hl2s.3.3`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-2`
- **Depends on**: bd-hl2s.3.2

**Intent**

If `NOTEBOOKLM_HOME` already has `storage_state.json` and `browser_profile/`, treat as legacy default profile. Don't move files — just map them in DB.

**Why This Exists**

Current state is still file-backed and ephemeral. This phase introduces durable, inspectable, profile-scoped local state.

**Phase Context**

- Goal link: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- Rationale link: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Existing users lose no state on upgrade
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-022a` -> `bd-hl2s.3.3.1`: Detect legacy layout on first DB creation
- `B-022b` -> `bd-hl2s.3.3.2`: Create `default` profile row pointing to existing paths
- `B-022c` -> `bd-hl2s.3.3.3`: Import existing auth state into `auth_snapshots`
- `B-022d` -> `bd-hl2s.3.3.4`: Import legacy `context.json` notebook/conversation selections into `app_state`
- `B-022e` -> `bd-hl2s.3.3.5`: Only physically migrate when user requests or doctor suggests

### B-023: Create core metadata cache tables

- **Actual bead**: `bd-hl2s.3.4`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-2`
- **Depends on**: bd-hl2s.3.1

**Intent**

Create `notebooks`, `sources`, `artifacts`, `research_runs` tables per Original §3.5 / Revised §10.1.

**Why This Exists**

Current state is still file-backed and ephemeral. This phase introduces durable, inspectable, profile-scoped local state.

**Phase Context**

- Goal link: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- Rationale link: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Full CRUD on all four tables; profile-scoped queries work
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-023a` -> `bd-hl2s.3.4.1`: `notebooks` — all columns from Original §3.5B including normalized_title, tombstoned_at, raw_json
- `B-023b` -> `bd-hl2s.3.4.2`: `sources` — source_type, title, origin_uri, status, freshness_state, synced_at, tombstoned_at
- `B-023c` -> `bd-hl2s.3.4.3`: `artifacts` — artifact_type, submode, prompt_hash, status, download_ref, timestamps
- `B-023d` -> `bd-hl2s.3.4.4`: `research_runs` — mode, query_text, status, discovered/imported counts
- `B-023e` -> `bd-hl2s.3.4.5`: Create `src/notebooklm/local/repositories.py` — repository classes for each table

### B-024: Create execution/history tables

- **Actual bead**: `bd-hl2s.3.5`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-2`
- **Depends on**: bd-hl2s.3.1

**Intent**

`query_runs`, `query_results`, `sync_runs` per Original §3.5C and Revised §10.1.

**Why This Exists**

Current state is still file-backed and ephemeral. This phase introduces durable, inspectable, profile-scoped local state.

**Phase Context**

- Goal link: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- Rationale link: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Run history persists and is queryable
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-024a` -> `bd-hl2s.3.5.1`: `query_runs` with all columns per CONTRACT_NORMALIZATION §5 (id prefix `qr_`, trace_id, profile_id, status column pattern)
- `B-024b` -> `bd-hl2s.3.5.2`: `query_results` — one-to-one with query_runs
- `B-024c` -> `bd-hl2s.3.5.3`: `sync_runs` with prefix `sr_` per CONTRACT_NORMALIZATION §5
- `B-024d` -> `bd-hl2s.3.5.4`: Repository methods for insert/update/query

### B-025: Create `run_events` unified event log

- **Actual bead**: `bd-hl2s.3.6`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-2`
- **Depends on**: bd-hl2s.3.1

**Intent**

Append-only event log per Revised §10.2 and CONTRACT_NORMALIZATION §5. All subsystems emit events here.

**Why This Exists**

Current state is still file-backed and ephemeral. This phase introduces durable, inspectable, profile-scoped local state.

**Phase Context**

- Goal link: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- Rationale link: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Events can be appended and queried by trace_id
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-025a` -> `bd-hl2s.3.6.1`: `run_events` table (event_id PK `evt_<ulid>`, trace_id indexed, run_id nullable, kind, ts, payload_json)
- `B-025b` -> `bd-hl2s.3.6.2`: Canonical event kinds from CONTRACT_NORMALIZATION §5 (route.resolved, cache.hit, cache.miss, sync.started, sync.finished, auth.refreshed, etc.)
- `B-025c` -> `bd-hl2s.3.6.3`: Event emitter helper that auto-generates event_id and timestamp
- `B-025d` -> `bd-hl2s.3.6.4`: Index on trace_id for fast lookups

### B-026: Create MVP indexes

- **Actual bead**: `bd-hl2s.3.7`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-2`
- **Depends on**: bd-hl2s.3.4, bd-hl2s.3.5

**Intent**

Per Original §3.6 / Revised §10.3 — indexes critical for routing and query performance.

**Why This Exists**

Current state is still file-backed and ephemeral. This phase introduces durable, inspectable, profile-scoped local state.

**Phase Context**

- Goal link: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- Rationale link: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Explain query plans show index usage
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-026a` -> `bd-hl2s.3.7.1`: `notebooks(profile_id, normalized_title)`
- `B-026b` -> `bd-hl2s.3.7.2`: `sources(notebook_id, status)` and `sources(profile_id, source_type)`
- `B-026c` -> `bd-hl2s.3.7.3`: `artifacts(notebook_id, status)`
- `B-026d` -> `bd-hl2s.3.7.4`: `query_runs(prompt_hash, notebook_fingerprint, intent)`
- `B-026e` -> `bd-hl2s.3.7.5`: `sync_runs(profile_id, scope, started_at)`

### B-027: Implement `cache status` and `cache prune` commands

- **Actual bead**: `bd-hl2s.3.8`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `MVP`
- **Parent**: `PHASE-2`
- **Depends on**: bd-hl2s.3.4, bd-hl2s.1.5

**Intent**

Basic cache diagnostics and maintenance.

**Why This Exists**

Current state is still file-backed and ephemeral. This phase introduces durable, inspectable, profile-scoped local state.

**Phase Context**

- Goal link: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- Rationale link: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Agent can inspect and maintain cache health
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-027a` -> `bd-hl2s.3.8.1`: `notebooklm cache status` — shows table row counts, DB size, WAL size, oldest/newest sync timestamps
- `B-027b` -> `bd-hl2s.3.8.2`: `notebooklm cache prune` — removes tombstoned rows older than threshold, vacuums DB
- `B-027c` -> `bd-hl2s.3.8.3`: `cache prune` is `T1_LOCAL_MUTATION` — supports `--dry-run`
- `B-027d` -> `bd-hl2s.3.8.4`: Both support `--json`

### B-028: Notebook fingerprint implementation

- **Actual bead**: `bd-hl2s.3.9`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-2`
- **Depends on**: bd-hl2s.3.4

**Intent**

Per Original §3.8 / Revised §11.2 — SHA-256 over canonical notebook state for cache reuse decisions.

**Why This Exists**

Current state is still file-backed and ephemeral. This phase introduces durable, inspectable, profile-scoped local state.

**Phase Context**

- Goal link: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
- Rationale link: Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Same notebook state → same fingerprint; source add/remove → different fingerprint
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-028a` -> `bd-hl2s.3.9.1`: Create `src/notebooklm/local/fingerprints.py`
- `B-028b` -> `bd-hl2s.3.9.2`: Compute fingerprint from: notebook title + summary + ordered source IDs/statuses/fingerprints + ordered artifact IDs/statuses + settings
- `B-028c` -> `bd-hl2s.3.9.3`: Store fingerprint in `notebooks.remote_fingerprint`
- `B-028d` -> `bd-hl2s.3.9.4`: Recompute on every notebook detail sync

## PHASE-3 — Phase 3: Metadata Sync + Local-First

- **Actual bead**: `bd-hl2s.4`
- **Scope**: `MVP`
- **Goal**: Make metadata commands local-first with automatic freshness-gated remote sync.
- **Rationale**: This is what makes the CLI feel instant for metadata lookups while staying accurate.
- **Depends on phases**: bd-hl2s.3, bd-hl2s.2, bd-hl2s.1

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-030: Notebook index sync

- **Actual bead**: `bd-hl2s.4.1`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-3`
- **Depends on**: bd-hl2s.3.4, bd-hl2s.2.3

**Intent**

Sync the notebook list from remote via `LIST_NOTEBOOKS` RPC, upsert into local cache.

**Why This Exists**

The package can talk to remote NotebookLM today, but it does not have a sync engine or local-first metadata UX.

**Phase Context**

- Goal link: Make metadata commands local-first with automatic freshness-gated remote sync.
- Rationale link: This is what makes the CLI feel instant for metadata lookups while staying accurate.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `notebook list` returns from cache when fresh, syncs when stale
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-030a` -> `bd-hl2s.4.1.1`: Create `src/notebooklm/sync/notebooks.py`
- `B-030b` -> `bd-hl2s.4.1.2`: Parse `LIST_NOTEBOOKS` response, upsert `notebooks` rows
- `B-030c` -> `bd-hl2s.4.1.3`: Tombstone notebooks that disappeared from remote
- `B-030d` -> `bd-hl2s.4.1.4`: Record sync_run with stats
- `B-030e` -> `bd-hl2s.4.1.5`: Freshness window: 5 minutes (configurable)

### B-031: Notebook detail sync

- **Actual bead**: `bd-hl2s.4.2`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-3`
- **Depends on**: bd-hl2s.4.1

**Intent**

Sync individual notebook details via `GET_NOTEBOOK` — sources, artifacts, counts.

**Why This Exists**

The package can talk to remote NotebookLM today, but it does not have a sync engine or local-first metadata UX.

**Phase Context**

- Goal link: Make metadata commands local-first with automatic freshness-gated remote sync.
- Rationale link: This is what makes the CLI feel instant for metadata lookups while staying accurate.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Source list for a notebook is available locally after sync
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-031a` -> `bd-hl2s.4.2.1`: Parse notebook detail response
- `B-031b` -> `bd-hl2s.4.2.2`: Upsert sources from notebook detail
- `B-031c` -> `bd-hl2s.4.2.3`: Upsert artifact summaries
- `B-031d` -> `bd-hl2s.4.2.4`: Update notebook fingerprint
- `B-031e` -> `bd-hl2s.4.2.5`: Freshness window: 2 minutes

### B-032: Source metadata reconciliation

- **Actual bead**: `bd-hl2s.4.3`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-3`
- **Depends on**: bd-hl2s.4.2

**Intent**

Keep source rows in sync with reality — handle status transitions (preparing→processing→ready), tombstone deletions.

**Why This Exists**

The package can talk to remote NotebookLM today, but it does not have a sync engine or local-first metadata UX.

**Phase Context**

- Goal link: Make metadata commands local-first with automatic freshness-gated remote sync.
- Rationale link: This is what makes the CLI feel instant for metadata lookups while staying accurate.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Source statuses accurately reflect remote state
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-032a` -> `bd-hl2s.4.3.1`: Create `src/notebooklm/sync/sources.py`
- `B-032b` -> `bd-hl2s.4.3.2`: Status-aware freshness: `ready` sources → 10min; `processing/preparing` → 15sec poll
- `B-032c` -> `bd-hl2s.4.3.3`: Tombstone sources missing from notebook detail

### B-033: Invalidation helpers

- **Actual bead**: `bd-hl2s.4.4`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-3`
- **Depends on**: bd-hl2s.4.1, bd-hl2s.4.2

**Intent**

Per Original §3.7 — mutation-triggered cache invalidation rules.

**Why This Exists**

The package can talk to remote NotebookLM today, but it does not have a sync engine or local-first metadata UX.

**Phase Context**

- Goal link: Make metadata commands local-first with automatic freshness-gated remote sync.
- Rationale link: This is what makes the CLI feel instant for metadata lookups while staying accurate.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- After mutation, next metadata read triggers fresh sync
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-033a` -> `bd-hl2s.4.4.1`: Create `src/notebooklm/sync/invalidation.py`
- `B-033b` -> `bd-hl2s.4.4.2`: Notebook create → invalidate notebook index
- `B-033c` -> `bd-hl2s.4.4.3`: Source add/delete/refresh → invalidate notebook detail
- `B-033d` -> `bd-hl2s.4.4.4`: Artifact create → insert pending + invalidate notebook detail
- `B-033e` -> `bd-hl2s.4.4.5`: Research import → invalidate notebook detail + source list

### B-034: Implement `notebook list`, `notebook show`, `notebook use` commands

- **Actual bead**: `bd-hl2s.4.5`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-3`
- **Depends on**: bd-hl2s.4.1, bd-hl2s.4.2, bd-hl2s.1.5

**Intent**

Core metadata CLI commands using local-first pattern.

**Why This Exists**

The package can talk to remote NotebookLM today, but it does not have a sync engine or local-first metadata UX.

**Phase Context**

- Goal link: Make metadata commands local-first with automatic freshness-gated remote sync.
- Rationale link: This is what makes the CLI feel instant for metadata lookups while staying accurate.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Fast local responses; stale cache auto-refreshes
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-034a` -> `bd-hl2s.4.5.1`: `notebooklm notebook list` — local-first, sync if stale, support `--refresh` / offline-safe behavior
- `B-034b` -> `bd-hl2s.4.5.2`: `notebooklm notebook show <id-or-title>` — resolves by ID or title (exact/fuzzy), shows detail, and surfaces freshness/provenance
- `B-034c` -> `bd-hl2s.4.5.3`: `notebooklm notebook use <id-or-title>` — sets current context
- `B-034d` -> `bd-hl2s.4.5.4`: All use canonical envelope when `--json`, including whether data came from cache vs remote

### B-035: Implement `source list` and `sync notebooks` commands

- **Actual bead**: `bd-hl2s.4.6`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-3`
- **Depends on**: bd-hl2s.4.3, bd-hl2s.4.5

**Intent**



**Why This Exists**

The package can talk to remote NotebookLM today, but it does not have a sync engine or local-first metadata UX.

**Phase Context**

- Goal link: Make metadata commands local-first with automatic freshness-gated remote sync.
- Rationale link: This is what makes the CLI feel instant for metadata lookups while staying accurate.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Full metadata browsing works locally and users can tell when they are looking at cached vs freshly synced data
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-035a` -> `bd-hl2s.4.6.1`: `notebooklm source list [--notebook X]` — profile-scoped, filterable
- `B-035b` -> `bd-hl2s.4.6.2`: `notebooklm source guide <source-id>` — remote required, cache result, and expose freshness metadata
- `B-035c` -> `bd-hl2s.4.6.3`: `notebooklm sync notebooks [--all | --notebook X]` — explicit sync trigger with scoped stats in human and JSON modes

## PHASE-4 — Phase 4: Agent Memory + Observability

- **Actual bead**: `bd-hl2s.5`
- **Scope**: `MVP`
- **Goal**: Give the agent the ability to look back, search, and explain past decisions.
- **Rationale**: "Agent-first" means the system must remember and self-observe. Without trace/history, debugging routing decisions is impossible.
- **Depends on phases**: bd-hl2s.3, bd-hl2s.1

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-040: Tracing infrastructure

- **Actual bead**: `bd-hl2s.5.1`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-4`
- **Depends on**: bd-hl2s.3.6

**Intent**

Every command execution generates a `trace_id`. All events, run table rows, and envelope outputs reference it.

**Why This Exists**

There is no explicit run history, trace view, or event log today, which makes agent-grade replay and diagnosis impossible.

**Phase Context**

- Goal link: Give the agent the ability to look back, search, and explain past decisions.
- Rationale link: "Agent-first" means the system must remember and self-observe. Without trace/history, debugging routing decisions is impossible.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Every `--json` output has a `trace_id`; `run_events` filtered by trace_id shows full execution story
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-040a` -> `bd-hl2s.5.1.1`: Create `src/notebooklm/observability/tracing.py` — trace context manager
- `B-040b` -> `bd-hl2s.5.1.2`: Generate `trc_<ulid>` on command entry
- `B-040c` -> `bd-hl2s.5.1.3`: Thread trace_id through sync, router, transport calls
- `B-040d` -> `bd-hl2s.5.1.4`: Include trace_id in JSON envelope output

### B-041: Implement `history search` and `history show`

- **Actual bead**: `bd-hl2s.5.2`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `MVP`
- **Parent**: `PHASE-4`
- **Depends on**: bd-hl2s.3.5, bd-hl2s.5.1

**Intent**

Searchable query history with FTS.

**Why This Exists**

There is no explicit run history, trace view, or event log today, which makes agent-grade replay and diagnosis impossible.

**Phase Context**

- Goal link: Give the agent the ability to look back, search, and explain past decisions.
- Rationale link: "Agent-first" means the system must remember and self-observe. Without trace/history, debugging routing decisions is impossible.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Agent can find past runs by keyword
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-041a` -> `bd-hl2s.5.2.1`: Create `history_fts` virtual table indexing prompt, answer, notebook title, source titles
- `B-041b` -> `bd-hl2s.5.2.2`: `notebooklm history search "term"` — FTS search over past runs
- `B-041c` -> `bd-hl2s.5.2.3`: `notebooklm history show <run-id>` — full run detail with route decision, result, timing
- `B-041d` -> `bd-hl2s.5.2.4`: Both support `--json`

### B-042: Implement `trace show` and `events tail`

- **Actual bead**: `bd-hl2s.5.3`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `MVP`
- **Parent**: `PHASE-4`
- **Depends on**: bd-hl2s.5.1, bd-hl2s.3.6

**Intent**



**Why This Exists**

There is no explicit run history, trace view, or event log today, which makes agent-grade replay and diagnosis impossible.

**Phase Context**

- Goal link: Give the agent the ability to look back, search, and explain past decisions.
- Rationale link: "Agent-first" means the system must remember and self-observe. Without trace/history, debugging routing decisions is impossible.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Full observability into system behavior
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-042a` -> `bd-hl2s.5.3.1`: `notebooklm trace show <trace-id>` — full event timeline for a trace
- `B-042b` -> `bd-hl2s.5.3.2`: `notebooklm events tail` — stream recent events, optionally `--follow`
- `B-042c` -> `bd-hl2s.5.3.3`: Both support `--json`

### B-043: Wire envelope with trace_id and run_id

- **Actual bead**: `bd-hl2s.5.4`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-4`
- **Depends on**: bd-hl2s.1.5, bd-hl2s.5.1

**Intent**

Every command output includes the canonical envelope with trace_id, run_id, route info, freshness, cache_updates, diagnostics.

**Why This Exists**

There is no explicit run history, trace view, or event log today, which makes agent-grade replay and diagnosis impossible.

**Phase Context**

- Goal link: Give the agent the ability to look back, search, and explain past decisions.
- Rationale link: "Agent-first" means the system must remember and self-observe. Without trace/history, debugging routing decisions is impossible.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `--json` output on any command matches CONTRACT_NORMALIZATION §3 schema
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

## PHASE-5 — Phase 5: Workflow Commands

- **Actual bead**: `bd-hl2s.6`
- **Scope**: `MVP`
- **Goal**: Ship the core work commands that make the CLI useful: ask, overview, summarize, study-guide, audio.
- **Rationale**: These are the "product" — everything else is infrastructure. Without these, there's nothing for users to do.
- **Depends on phases**: bd-hl2s.4, bd-hl2s.2, bd-hl2s.5, bd-hl2s.3, bd-hl2s.1, bd-hl2s.8

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-049: Build shared workflow runtime helpers

- **Actual bead**: `bd-hl2s.6.1`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-5`
- **Depends on**: bd-hl2s.4.5, bd-hl2s.2.5, bd-hl2s.5.4, bd-hl2s.3.9

**Intent**

Create the common runtime that all workflow commands share: notebook/context resolution, polling, cache-writeback hooks, and human/JSON output shaping.

**Why This Exists**

The legacy command surface exposes direct operations, but not the cohesive workflow commands the new CLI is supposed to present.

**Phase Context**

- Goal link: Ship the core work commands that make the CLI useful: ask, overview, summarize, study-guide, audio.
- Rationale link: These are the "product" — everything else is infrastructure. Without these, there's nothing for users to do.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Ask, overview, summarize, study-guide, audio, and research commands can all build on one workflow runtime instead of duplicating control flow
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-049a` -> `bd-hl2s.6.1.1`: Create `src/notebooklm/workflows/runtime.py`
- `B-049b` -> `bd-hl2s.6.1.2`: Centralize notebook resolution and current-context fallback using the contract precedence rules
- `B-049c` -> `bd-hl2s.6.1.3`: Add shared polling/wait helpers for long-running operations and retry-aware progress reporting
- `B-049d` -> `bd-hl2s.6.1.4`: Add shared result rendering helpers so human output and JSON envelope stay aligned across commands
- `B-049e` -> `bd-hl2s.6.1.5`: Add common cache-writeback and run-event hooks for workflow commands

### B-050: Implement `ask` command

- **Actual bead**: `bd-hl2s.6.2`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-5`
- **Depends on**: bd-hl2s.3.5, bd-hl2s.6.1

**Intent**

Conversational Q&A against a notebook via `QUERY_URL` free-form query endpoint.

**Why This Exists**

The legacy command surface exposes direct operations, but not the cohesive workflow commands the new CLI is supposed to present.

**Phase Context**

- Goal link: Ship the core work commands that make the CLI useful: ask, overview, summarize, study-guide, audio.
- Rationale link: These are the "product" — everything else is infrastructure. Without these, there's nothing for users to do.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `notebooklm ask "question"` returns grounded answer, records history
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-050a` -> `bd-hl2s.6.2.1`: Create `src/notebooklm/workflows/ask.py`
- `B-050b` -> `bd-hl2s.6.2.2`: Resolve notebook (resolution order from CONTRACT_NORMALIZATION §4)
- `B-050c` -> `bd-hl2s.6.2.3`: Send query via `httpx` to `QUERY_URL`
- `B-050d` -> `bd-hl2s.6.2.4`: Record query_run + query_result
- `B-050e` -> `bd-hl2s.6.2.5`: Emit run_events (route.resolved, cache.miss/hit)
- `B-050f` -> `bd-hl2s.6.2.6`: Support exact-reuse when fingerprint matches (advisory)
- `B-050g` -> `bd-hl2s.6.2.7`: Human-readable output + `--json` envelope

### B-051: Implement `overview` command

- **Actual bead**: `bd-hl2s.6.3`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-5`
- **Depends on**: bd-hl2s.6.1

**Intent**

Quick remote summary via `SUMMARIZE` RPC — lightweight, not a full report.

**Why This Exists**

The legacy command surface exposes direct operations, but not the cohesive workflow commands the new CLI is supposed to present.

**Phase Context**

- Goal link: Ship the core work commands that make the CLI useful: ask, overview, summarize, study-guide, audio.
- Rationale link: These are the "product" — everything else is infrastructure. Without these, there's nothing for users to do.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Returns concise summary, cached with notebook fingerprint
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-052: Implement `summarize` (briefing doc) command

- **Actual bead**: `bd-hl2s.6.4`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-5`
- **Depends on**: bd-hl2s.6.1

**Intent**

`CREATE_ARTIFACT` with `briefing_doc` mode. Supports `--wait` for polling.

**Why This Exists**

The legacy command surface exposes direct operations, but not the cohesive workflow commands the new CLI is supposed to present.

**Phase Context**

- Goal link: Ship the core work commands that make the CLI useful: ask, overview, summarize, study-guide, audio.
- Rationale link: These are the "product" — everything else is infrastructure. Without these, there's nothing for users to do.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Briefing doc generation works end-to-end
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-052a` -> `bd-hl2s.6.4.1`: Create `src/notebooklm/workflows/summarize.py`
- `B-052b` -> `bd-hl2s.6.4.2`: Insert artifact row as `pending`
- `B-052c` -> `bd-hl2s.6.4.3`: If `--wait`, poll until terminal status
- `B-052d` -> `bd-hl2s.6.4.4`: Invalidate notebook detail after creation

### B-053: Implement `study-guide` and `audio` commands

- **Actual bead**: `bd-hl2s.6.5`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-5`
- **Depends on**: bd-hl2s.6.4

**Intent**

Same pattern as summarize but with `study_guide` and `audio` modes.

**Why This Exists**

The legacy command surface exposes direct operations, but not the cohesive workflow commands the new CLI is supposed to present.

**Phase Context**

- Goal link: Ship the core work commands that make the CLI useful: ask, overview, summarize, study-guide, audio.
- Rationale link: These are the "product" — everything else is infrastructure. Without these, there's nothing for users to do.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Both artifact types generate successfully
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-054: Alias migration layer

- **Actual bead**: `bd-hl2s.6.6`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `MVP`
- **Parent**: `PHASE-5`
- **Depends on**: bd-hl2s.1.2, bd-hl2s.6.2, bd-hl2s.6.3, bd-hl2s.6.4, bd-hl2s.6.5

**Intent**

Per Revised §13.2 — transitional aliases from old command names.

**Why This Exists**

The legacy command surface exposes direct operations, but not the cohesive workflow commands the new CLI is supposed to present.

**Phase Context**

- Goal link: Ship the core work commands that make the CLI useful: ask, overview, summarize, study-guide, audio.
- Rationale link: These are the "product" — everything else is infrastructure. Without these, there's nothing for users to do.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Old-style commands produce deprecation warning + work
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-055: Implement `source delete` and `notebook delete` commands

- **Actual bead**: `bd-hl2s.6.7`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-5`
- **Depends on**: bd-hl2s.4.4, bd-hl2s.4.6, bd-hl2s.8.1, bd-hl2s.8.2

**Intent**

Add the missing destructive management commands promised by the manifest, with preview, confirmation, approval, and cache reconciliation built in from the start.

**Why This Exists**

The legacy command surface exposes direct operations, but not the cohesive workflow commands the new CLI is supposed to present.

**Phase Context**

- Goal link: Ship the core work commands that make the CLI useful: ask, overview, summarize, study-guide, audio.
- Rationale link: These are the "product" — everything else is infrastructure. Without these, there's nothing for users to do.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- The CLI can safely delete sources and notebooks without silent destructive behavior, and local cache state stays truthful after success or refusal
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-055a` -> `bd-hl2s.6.7.1`: `notebooklm source delete <id>` — resolve source, show impact, enforce risk guard, and tombstone local cache on success
- `B-055b` -> `bd-hl2s.6.7.2`: `notebooklm notebook delete <id-or-title>` — resolve notebook, enforce destructive confirmation/approval flow, and invalidate related cache state
- `B-055c` -> `bd-hl2s.6.7.3`: Both commands return canonical refusal/resume envelopes in non-interactive mode
- `B-055d` -> `bd-hl2s.6.7.4`: Both commands emit run_events and update local metadata so subsequent reads reflect the deletion

## PHASE-6 — Phase 6: Research + Router

- **Actual bead**: `bd-hl2s.7`
- **Scope**: `MVP`
- **Goal**: Complete the research workflow and build the NL routing layer that classifies `agent` requests.
- **Rationale**: Research is the highest-latency workflow in the MVP, and the router is the force multiplier that turns many explicit commands into one request surface. Both have to stay explicit about freshness, provenance, and mutation risk.
- **Depends on phases**: bd-hl2s.3, bd-hl2s.6, bd-hl2s.4, bd-hl2s.8, bd-hl2s.1

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-060: Implement `research start` and `research wait`

- **Actual bead**: `bd-hl2s.7.1`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `MVP`
- **Parent**: `PHASE-6`
- **Depends on**: bd-hl2s.3.4, bd-hl2s.6.1

**Intent**

Safe read-side research lifecycle: start a research run, persist it, and wait/poll for completion without importing anything into notebook state yet.

**Why This Exists**

Research and routing exist only in fragments today; they need to be normalized into the same manifest/routing/runtime model as the rest of the CLI.

**Phase Context**

- Goal link: Complete the research workflow and build the NL routing layer that classifies `agent` requests.
- Rationale link: Research is the highest-latency workflow in the MVP, and the router is the force multiplier that turns many explicit commands into one request surface. Both have to stay explicit about freshness, provenance, and mutation risk.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Users can start and observe research runs programmatically, with durable history, before any knowledge mutation occurs
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-060a` -> `bd-hl2s.7.1.1`: `research start "query" --mode fast|deep` — starts research, inserts research_run row
- `B-060b` -> `bd-hl2s.7.1.2`: `research wait <id>` — bounded polling loop, updates research_run status
- `B-060c` -> `bd-hl2s.7.1.3`: Persist discovered-source metadata and summary so the user can inspect a run before import
- `B-060d` -> `bd-hl2s.7.1.4`: All record run_events

### B-063: Implement approval-aware `research import` flow

- **Actual bead**: `bd-hl2s.7.2`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-6`
- **Depends on**: bd-hl2s.4.4, bd-hl2s.7.1, bd-hl2s.8.1, bd-hl2s.8.2

**Intent**

Import discovered research sources only through an explicit preview/approval path so MVP already honors the approval-first rule without waiting for the full post-MVP inbox.

**Why This Exists**

Research and routing exist only in fragments today; they need to be normalized into the same manifest/routing/runtime model as the rest of the CLI.

**Phase Context**

- Goal link: Complete the research workflow and build the NL routing layer that classifies `agent` requests.
- Rationale link: Research is the highest-latency workflow in the MVP, and the router is the force multiplier that turns many explicit commands into one request surface. Both have to stay explicit about freshness, provenance, and mutation risk.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Research imports cannot happen silently; the CLI supports preview, refusal, approval, and resume for research mutations
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-063a` -> `bd-hl2s.7.2.1`: `research import <id>` builds a deterministic candidate list with title, URL, and dedupe/provenance summary
- `B-063b` -> `bd-hl2s.7.2.2`: Add `--dry-run` / preview output so humans and agents can inspect exactly what would change
- `B-063c` -> `bd-hl2s.7.2.3`: In non-interactive mode, create an approval request and resume token instead of silently importing
- `B-063d` -> `bd-hl2s.7.2.4`: On approval, import sources and invalidate notebook detail + source list

### B-061: Implement `agent` NL routing command

- **Actual bead**: `bd-hl2s.7.3`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-6`
- **Depends on**: bd-hl2s.6.2, bd-hl2s.6.3, bd-hl2s.6.4, bd-hl2s.6.5, bd-hl2s.7.1, bd-hl2s.7.2, bd-hl2s.1.5

**Intent**

`notebooklm agent "natural language request"` — classifies into intent bucket, resolves target, executes.

**Why This Exists**

Research and routing exist only in fragments today; they need to be normalized into the same manifest/routing/runtime model as the rest of the CLI.

**Phase Context**

- Goal link: Complete the research workflow and build the NL routing layer that classifies `agent` requests.
- Rationale link: Research is the highest-latency workflow in the MVP, and the router is the force multiplier that turns many explicit commands into one request surface. Both have to stay explicit about freshness, provenance, and mutation risk.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `agent "summarize the current notebook"` → routes to summarize workflow
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-061a` -> `bd-hl2s.7.3.1`: Create `src/notebooklm/router/classify.py` — intent classification into LOCAL_METADATA, REMOTE_METADATA, QUERY, GENERATION, RESEARCH
- `B-061b` -> `bd-hl2s.7.3.2`: Create `src/notebooklm/router/resolve.py` — notebook resolution (6-step cascade from Revised §12.3)
- `B-061c` -> `bd-hl2s.7.3.3`: Create `src/notebooklm/router/freshness.py` — cache mode enforcement
- `B-061d` -> `bd-hl2s.7.3.4`: Create `src/notebooklm/router/execute.py` — dispatch to appropriate workflow
- `B-061e` -> `bd-hl2s.7.3.5`: Structured commands always win (Revised §12.2)

### B-062: Implement `route --dry-run` and `route explain`

- **Actual bead**: `bd-hl2s.7.4`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-6`
- **Depends on**: bd-hl2s.7.3

**Intent**

Diagnostic commands that show what the router would do without executing.

**Why This Exists**

Research and routing exist only in fragments today; they need to be normalized into the same manifest/routing/runtime model as the rest of the CLI.

**Phase Context**

- Goal link: Complete the research workflow and build the NL routing layer that classifies `agent` requests.
- Rationale link: Research is the highest-latency workflow in the MVP, and the router is the force multiplier that turns many explicit commands into one request surface. Both have to stay explicit about freshness, provenance, and mutation risk.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Agent can preview and verify routing decisions before execution
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-062a` -> `bd-hl2s.7.4.1`: `notebooklm route "request" --dry-run` — shows intent, target notebook, mode, transport, freshness decision
- `B-062b` -> `bd-hl2s.7.4.2`: `notebooklm route explain "request"` — verbose explanation of routing logic
- `B-062c` -> `bd-hl2s.7.4.3`: Both support `--json`

## PHASE-7 — Phase 7: Safety + Doctor + Support Bundle (MVP)

- **Actual bead**: `bd-hl2s.8`
- **Scope**: `MVP`
- **Goal**: Add the safety guardrails and basic diagnostics that make the system trustworthy for agent use.
- **Rationale**: Agent-first without guardrails for mutations is dangerous. Doctor without safety is incomplete.
- **Depends on phases**: bd-hl2s.1, bd-hl2s.3

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-070: Implement risk tier classification and guards

- **Actual bead**: `bd-hl2s.8.1`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-7`
- **Depends on**: bd-hl2s.1.3, bd-hl2s.1.5

**Intent**

Per CONTRACT_NORMALIZATION §1 — every command has a risk tier; guards enforce approval/confirmation based on tier.

**Why This Exists**

There is no central risk model or doctor workflow yet, so mutations and diagnostics are still under-specified.

**Phase Context**

- Goal link: Add the safety guardrails and basic diagnostics that make the system trustworthy for agent use.
- Rationale link: Agent-first without guardrails for mutations is dangerous. Doctor without safety is incomplete.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `source delete` without `--yes` or approval token is rejected in non-interactive mode and tells the user exactly how to proceed
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-070a` -> `bd-hl2s.8.1.1`: `T0_READ` — no guard
- `B-070b` -> `bd-hl2s.8.1.2`: `T1_LOCAL_MUTATION` — `--dry-run` supported; `--yes` if side effect large
- `B-070c` -> `bd-hl2s.8.1.3`: `T2_KNOWLEDGE_MUTATION` — approval required by default
- `B-070d` -> `bd-hl2s.8.1.4`: `T3_DESTRUCTIVE` — explicit confirm/approval token; two-step in non-interactive
- `B-070e` -> `bd-hl2s.8.1.5`: Create guard decorator that reads risk_tier from capabilities.yaml
- `B-070f` -> `bd-hl2s.8.1.6`: Guard failures return canonical refusal output with the exact next step (`--yes`, approval token, resume token, or dry-run)

### B-071: Create `approval_requests` table

- **Actual bead**: `bd-hl2s.8.2`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-7`
- **Depends on**: bd-hl2s.3.1

**Intent**

Per CONTRACT_NORMALIZATION §2 — unified approval schema.

**Why This Exists**

There is no central risk model or doctor workflow yet, so mutations and diagnostics are still under-specified.

**Phase Context**

- Goal link: Add the safety guardrails and basic diagnostics that make the system trustworthy for agent use.
- Rationale link: Agent-first without guardrails for mutations is dangerous. Doctor without safety is incomplete.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Approval requests can be created, queried, and resolved
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-072: Implement `doctor` fast mode

- **Actual bead**: `bd-hl2s.8.3`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `MVP`
- **Parent**: `PHASE-7`
- **Depends on**: bd-hl2s.3.1, bd-hl2s.3.2, bd-hl2s.1.3

**Intent**

Per Supplement §8.3 — quick health check with JSON output and meaningful exit codes.

**Why This Exists**

There is no central risk model or doctor workflow yet, so mutations and diagnostics are still under-specified.

**Phase Context**

- Goal link: Add the safety guardrails and basic diagnostics that make the system trustworthy for agent use.
- Rationale link: Agent-first without guardrails for mutations is dangerous. Doctor without safety is incomplete.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `doctor` correctly diagnoses cold install, degraded auth, corrupted DB
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-072a` -> `bd-hl2s.8.3.1`: Auth checks (snapshot present, fresh, bl present)
- `B-072b` -> `bd-hl2s.8.3.2`: DB checks (openable, schema current, write permissions)
- `B-072c` -> `bd-hl2s.8.3.3`: Path checks (NOTEBOOKLM_HOME consistent)
- `B-072d` -> `bd-hl2s.8.3.4`: Exit code: 0=healthy, 1=degraded, 2=broken
- `B-072e` -> `bd-hl2s.8.3.5`: JSON output per CONTRACT_NORMALIZATION §3 (wrapped in canonical envelope `.result`)

### B-073: Implement `doctor fix --dry-run`

- **Actual bead**: `bd-hl2s.8.4`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `MVP`
- **Parent**: `PHASE-7`
- **Depends on**: bd-hl2s.8.3

**Intent**

Low-risk idempotent repairs.

**Why This Exists**

There is no central risk model or doctor workflow yet, so mutations and diagnostics are still under-specified.

**Phase Context**

- Goal link: Add the safety guardrails and basic diagnostics that make the system trustworthy for agent use.
- Rationale link: Agent-first without guardrails for mutations is dangerous. Doctor without safety is incomplete.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Fixes 70%+ of common issues without human intervention
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-073a` -> `bd-hl2s.8.4.1`: Create missing dirs
- `B-073b` -> `bd-hl2s.8.4.2`: Migrate legacy profile mapping
- `B-073c` -> `bd-hl2s.8.4.3`: Clear stale locks/leases
- `B-073d` -> `bd-hl2s.8.4.4`: Mark broken auth snapshot invalid
- `B-073e` -> `bd-hl2s.8.4.5`: `--dry-run` shows what would be fixed without doing it

### B-074: Implement `support-bundle create`

- **Actual bead**: `bd-hl2s.8.5`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `MVP`
- **Parent**: `PHASE-7`
- **Depends on**: bd-hl2s.8.3

**Intent**

Redacted diagnostic bundle for debugging.

**Why This Exists**

There is no central risk model or doctor workflow yet, so mutations and diagnostics are still under-specified.

**Phase Context**

- Goal link: Add the safety guardrails and basic diagnostics that make the system trustworthy for agent use.
- Rationale link: Agent-first without guardrails for mutations is dangerous. Doctor without safety is incomplete.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Bundle never contains raw secrets; useful for remote debugging
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

## PHASE-8 — Phase 8: Post-MVP: Shared Foundations for Advanced Features

- **Actual bead**: `bd-hl2s.9`
- **Scope**: `POST`
- **Goal**: Lay the shared infrastructure (tables, leases, extended approval engine, trace events) that Doctor deep mode, Workspaces, Change Radar, and Research Inbox all need.
- **Rationale**: These four features share primitives. Building them once prevents duplication.
- **Depends on phases**: bd-hl2s.3, bd-hl2s.1

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-080: Create `leases` table

- **Actual bead**: `bd-hl2s.9.1`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-8`
- **Depends on**: bd-hl2s.3.1

**Intent**

Per CONTRACT_NORMALIZATION §6 — DB-based advisory locks for concurrency safety.

**Why This Exists**

Post-MVP foundations are where shared primitives are intentionally centralized to avoid duplicate implementations across Doctor, Workspace, Radar, and Inbox.

**Phase Context**

- Goal link: Lay the shared infrastructure (tables, leases, extended approval engine, trace events) that Doctor deep mode, Workspaces, Change Radar, and Research Inbox all need.
- Rationale link: These four features share primitives. Building them once prevents duplication.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Leases can be acquired, released, expired; stale leases detectable
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-081: Extend `capabilities.yaml` with post-MVP commands

- **Actual bead**: `bd-hl2s.9.2`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-8`
- **Depends on**: bd-hl2s.1.3

**Intent**

Add doctor.fix, doctor.bundle, workspace.*, watch.*, radar.*, inbox.* commands with intents and risk tiers per CONTRACT_NORMALIZATION §7.

**Why This Exists**

Post-MVP foundations are where shared primitives are intentionally centralized to avoid duplicate implementations across Doctor, Workspace, Radar, and Inbox.

**Phase Context**

- Goal link: Lay the shared infrastructure (tables, leases, extended approval engine, trace events) that Doctor deep mode, Workspaces, Change Radar, and Research Inbox all need.
- Rationale link: These four features share primitives. Building them once prevents duplication.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- All post-MVP commands are manifest-described
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-082: Create post-MVP run tables

- **Actual bead**: `bd-hl2s.9.3`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-8`
- **Depends on**: bd-hl2s.3.1

**Intent**

Per CONTRACT_NORMALIZATION §5 — `workspace_runs` (prefix `wr_`), `watch_runs` (`wtr_`), `doctor_runs` (`dr_`).

**Why This Exists**

Post-MVP foundations are where shared primitives are intentionally centralized to avoid duplicate implementations across Doctor, Workspace, Radar, and Inbox.

**Phase Context**

- Goal link: Lay the shared infrastructure (tables, leases, extended approval engine, trace events) that Doctor deep mode, Workspaces, Change Radar, and Research Inbox all need.
- Rationale link: These four features share primitives. Building them once prevents duplication.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- All follow typed run table pattern with trace_id linkage
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-083: Extend `run_events` with post-MVP event kinds

- **Actual bead**: `bd-hl2s.9.4`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-8`
- **Depends on**: bd-hl2s.3.6

**Intent**

Add event kinds from Supplement §6.3 (doctor.*, workspace.*, watch.*, inbox.*, approval.resolved).

**Why This Exists**

Post-MVP foundations are where shared primitives are intentionally centralized to avoid duplicate implementations across Doctor, Workspace, Radar, and Inbox.

**Phase Context**

- Goal link: Lay the shared infrastructure (tables, leases, extended approval engine, trace events) that Doctor deep mode, Workspaces, Change Radar, and Research Inbox all need.
- Rationale link: These four features share primitives. Building them once prevents duplication.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- All subsystems emit to unified event log
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

## PHASE-9 — Phase 9: Post-MVP: Doctor Deep + Advanced Repairs

- **Actual bead**: `bd-hl2s.10`
- **Scope**: `POST`
- **Goal**: 
- **Rationale**: 
- **Depends on phases**: bd-hl2s.8, bd-hl2s.9

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-090: Doctor deep mode

- **Actual bead**: `bd-hl2s.10.1`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-9`
- **Depends on**: bd-hl2s.8.3, bd-hl2s.9.1

**Intent**

Per Supplement §8.3 — remote auth probe, RPC canary, cache integrity, FTS health, foreign key checks.

**Why This Exists**

Doctor fast mode can exist without the full deep-repair model, but deep mode needs additional schema, leases, and repair coverage.

**Phase Context**

- Goal link: 
- Rationale link: 

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `doctor --deep` catches issues that fast mode misses
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-091: Doctor category checks

- **Actual bead**: `bd-hl2s.10.2`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-9`
- **Depends on**: bd-hl2s.10.1

**Intent**

`doctor check auth`, `doctor check db`, `doctor check workspace`, `doctor check radar`, `doctor check inbox`.

**Why This Exists**

Doctor fast mode can exist without the full deep-repair model, but deep mode needs additional schema, leases, and repair coverage.

**Phase Context**

- Goal link: 
- Rationale link: 

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Targeted diagnostics for specific subsystems
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-092: Advanced repair coverage

- **Actual bead**: `bd-hl2s.10.3`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-9`
- **Depends on**: bd-hl2s.8.4, bd-hl2s.10.1

**Intent**

Rebuild FTS, retry stuck watch, vacuum/analyze, resync notebook metadata.

**Why This Exists**

Doctor fast mode can exist without the full deep-repair model, but deep mode needs additional schema, leases, and repair coverage.

**Phase Context**

- Goal link: 
- Rationale link: 

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

## PHASE-10 — Phase 10: Post-MVP: Research Inbox

- **Actual bead**: `bd-hl2s.11`
- **Scope**: `POST`
- **Goal**: The knowledge intake valve — no source enters a notebook without passing through triage.
- **Rationale**: NotebookLM's existing review-then-import model for research is the perfect foundation. We extend it with persistence, scoring, dedupe, and approval.
- **Depends on phases**: bd-hl2s.3, bd-hl2s.8, bd-hl2s.9, bd-hl2s.7

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-100: Create inbox tables

- **Actual bead**: `bd-hl2s.11.1`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-10`
- **Depends on**: bd-hl2s.3.1, bd-hl2s.8.2

**Intent**

`inbox_items`, `inbox_clusters` per Supplement §7.4.

**Why This Exists**

Inbox is the approval-first intake valve for knowledge mutations; without it, import flows remain too implicit for agent use.

**Phase Context**

- Goal link: The knowledge intake valve — no source enters a notebook without passing through triage.
- Rationale link: NotebookLM's existing review-then-import model for research is the perfect foundation. We extend it with persistence, scoring, dedupe, and approval.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Items can be created, queried, clustered
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-101: Inbox CRUD commands

- **Actual bead**: `bd-hl2s.11.2`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-10`
- **Depends on**: bd-hl2s.11.1, bd-hl2s.9.2

**Intent**

`inbox list`, `inbox view`, `inbox approve`, `inbox reject`, `inbox defer`, `inbox import`.

**Why This Exists**

Inbox is the approval-first intake valve for knowledge mutations; without it, import flows remain too implicit for agent use.

**Phase Context**

- Goal link: The knowledge intake valve — no source enters a notebook without passing through triage.
- Rationale link: NotebookLM's existing review-then-import model for research is the perfect foundation. We extend it with persistence, scoring, dedupe, and approval.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Full triage workflow from CLI
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-102: Inbox scoring engine

- **Actual bead**: `bd-hl2s.11.3`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-10`
- **Depends on**: bd-hl2s.11.1

**Intent**

Relevance, novelty, trust scores per Supplement §11.5. Deterministic base with optional LLM rationale.

**Why This Exists**

Inbox is the approval-first intake valve for knowledge mutations; without it, import flows remain too implicit for agent use.

**Phase Context**

- Goal link: The knowledge intake valve — no source enters a notebook without passing through triage.
- Rationale link: NotebookLM's existing review-then-import model for research is the perfect foundation. We extend it with persistence, scoring, dedupe, and approval.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-103: Dedupe/cluster engine

- **Actual bead**: `bd-hl2s.11.4`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-10`
- **Depends on**: bd-hl2s.11.1

**Intent**

Canonical URL, normalized title, content hash, domain similarity. Per Supplement §11.6.

**Why This Exists**

Inbox is the approval-first intake valve for knowledge mutations; without it, import flows remain too implicit for agent use.

**Phase Context**

- Goal link: The knowledge intake valve — no source enters a notebook without passing through triage.
- Rationale link: NotebookLM's existing review-then-import model for research is the perfect foundation. We extend it with persistence, scoring, dedupe, and approval.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-104: Research results → inbox pipeline

- **Actual bead**: `bd-hl2s.11.5`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-10`
- **Depends on**: bd-hl2s.11.1, bd-hl2s.7.1, bd-hl2s.7.2

**Intent**

Fast/Deep Research results land in inbox instead of direct import.

**Why This Exists**

Inbox is the approval-first intake valve for knowledge mutations; without it, import flows remain too implicit for agent use.

**Phase Context**

- Goal link: The knowledge intake valve — no source enters a notebook without passing through triage.
- Rationale link: NotebookLM's existing review-then-import model for research is the perfect foundation. We extend it with persistence, scoring, dedupe, and approval.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `research import` routes through inbox approval
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-105: Inbox apply with `--batch` and `--filter`

- **Actual bead**: `bd-hl2s.11.6`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-10`
- **Depends on**: bd-hl2s.11.2

**Intent**

Bulk triage for efficiency.

**Why This Exists**

Inbox is the approval-first intake valve for knowledge mutations; without it, import flows remain too implicit for agent use.

**Phase Context**

- Goal link: The knowledge intake valve — no source enters a notebook without passing through triage.
- Rationale link: NotebookLM's existing review-then-import model for research is the perfect foundation. We extend it with persistence, scoring, dedupe, and approval.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-106: Approval interruption + resume token

- **Actual bead**: `bd-hl2s.11.7`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-10`
- **Depends on**: bd-hl2s.8.2, bd-hl2s.11.2

**Intent**

Per Supplement §11.7 — agent pause/resume pattern for HITL.

**Why This Exists**

Inbox is the approval-first intake valve for knowledge mutations; without it, import flows remain too implicit for agent use.

**Phase Context**

- Goal link: The knowledge intake valve — no source enters a notebook without passing through triage.
- Rationale link: NotebookLM's existing review-then-import model for research is the perfect foundation. We extend it with persistence, scoring, dedupe, and approval.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

## PHASE-11 — Phase 11: Post-MVP: Workspaces

- **Actual bead**: `bd-hl2s.12`
- **Scope**: `POST`
- **Goal**: Cross-notebook reasoning via local orchestration.
- **Rationale**: NotebookLM notebooks are isolated. Workspace = virtual grouping for multi-notebook queries with transparent provenance.
- **Depends on phases**: bd-hl2s.3, bd-hl2s.9, bd-hl2s.6

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-110: Create workspace tables

- **Actual bead**: `bd-hl2s.12.1`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-11`
- **Depends on**: bd-hl2s.3.1

**Intent**

`workspaces`, `workspace_members`, `workspace_rules`, `workspace_index_entries` per Supplement §7.2.

**Why This Exists**

Workspace work is what turns single-notebook operations into higher-level reasoning, but it must stay explicit about local orchestration and provenance.

**Phase Context**

- Goal link: Cross-notebook reasoning via local orchestration.
- Rationale link: NotebookLM notebooks are isolated. Workspace = virtual grouping for multi-notebook queries with transparent provenance.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-111: Workspace CRUD commands

- **Actual bead**: `bd-hl2s.12.2`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-11`
- **Depends on**: bd-hl2s.12.1, bd-hl2s.9.2

**Intent**

`workspace list/create/add/remove/show`.

**Why This Exists**

Workspace work is what turns single-notebook operations into higher-level reasoning, but it must stay explicit about local orchestration and provenance.

**Phase Context**

- Goal link: Cross-notebook reasoning via local orchestration.
- Rationale link: NotebookLM notebooks are isolated. Workspace = virtual grouping for multi-notebook queries with transparent provenance.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- Static workspaces can be managed
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-112: Workspace index (FTS/BM25)

- **Actual bead**: `bd-hl2s.12.3`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-11`
- **Depends on**: bd-hl2s.12.1, bd-hl2s.3.4

**Intent**

Materialized FTS index over notebook titles, summaries, source titles, tags. Per Supplement §9.5 step 1.

**Why This Exists**

Workspace work is what turns single-notebook operations into higher-level reasoning, but it must stay explicit about local orchestration and provenance.

**Phase Context**

- Goal link: Cross-notebook reasoning via local orchestration.
- Rationale link: NotebookLM notebooks are isolated. Workspace = virtual grouping for multi-notebook queries with transparent provenance.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- `workspace index <name>` builds searchable index
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-113: Workspace `ask` with fan-out + synthesis

- **Actual bead**: `bd-hl2s.12.4`
- **Type**: `feature`
- **Priority**: `P0`
- **Scope**: `POST`
- **Parent**: `PHASE-11`
- **Depends on**: bd-hl2s.12.3, bd-hl2s.6.2

**Intent**

The crown jewel — multi-notebook query with transparent provenance.

**Why This Exists**

Workspace work is what turns single-notebook operations into higher-level reasoning, but it must stay explicit about local orchestration and provenance.

**Phase Context**

- Goal link: Cross-notebook reasoning via local orchestration.
- Rationale link: NotebookLM notebooks are isolated. Workspace = virtual grouping for multi-notebook queries with transparent provenance.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- Critical rule: Output must be transparent that this is multi-notebook planning + per-notebook execution + local synthesis — never imply NotebookLM itself did cross-notebook reasoning (Supplement §9.6)

**Acceptance**

- `workspace ask market-intel "question"` returns synthesized answer with notebook attribution
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- `B-113a` -> `bd-hl2s.12.4.1`: Candidate selection via FTS/BM25
- `B-113b` -> `bd-hl2s.12.4.2`: Planning (1 notebook vs fan-out to top 2-3)
- `B-113c` -> `bd-hl2s.12.4.3`: Fan-out execution (parallel `ask` per notebook)
- `B-113d` -> `bd-hl2s.12.4.4`: Synthesis with provenance (which notebook contributed what)
- `B-113e` -> `bd-hl2s.12.4.5`: Record workspace_run

### B-114: Workspace `compare` mode

- **Actual bead**: `bd-hl2s.12.5`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-11`
- **Depends on**: bd-hl2s.12.4

**Intent**

Optimized for contradictions, overlap, differences across notebooks.

**Why This Exists**

Workspace work is what turns single-notebook operations into higher-level reasoning, but it must stay explicit about local orchestration and provenance.

**Phase Context**

- Goal link: Cross-notebook reasoning via local orchestration.
- Rationale link: NotebookLM notebooks are isolated. Workspace = virtual grouping for multi-notebook queries with transparent provenance.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-115: Workspace as tool / specialist handoff

- **Actual bead**: `bd-hl2s.12.6`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-11`
- **Depends on**: bd-hl2s.12.4

**Intent**

Expose workspace as callable tool for external agent hosts. Per Supplement §9.7 and Agents SDK handoff pattern.

**Why This Exists**

Workspace work is what turns single-notebook operations into higher-level reasoning, but it must stay explicit about local orchestration and provenance.

**Phase Context**

- Goal link: Cross-notebook reasoning via local orchestration.
- Rationale link: NotebookLM notebooks are isolated. Workspace = virtual grouping for multi-notebook queries with transparent provenance.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

## PHASE-12 — Phase 12: Post-MVP: Change Radar

- **Actual bead**: `bd-hl2s.13`
- **Scope**: `POST`
- **Goal**: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- **Rationale**: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.
- **Depends on phases**: bd-hl2s.3, bd-hl2s.9, bd-hl2s.4, bd-hl2s.11, bd-hl2s.7

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-120: Create radar tables

- **Actual bead**: `bd-hl2s.13.1`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-12`
- **Depends on**: bd-hl2s.3.1

**Intent**

`watches`, `watch_runs`, `source_revisions`, `change_events`, `delta_briefings` per Supplement §7.3.

**Why This Exists**

Change Radar only makes sense once cached knowledge can be monitored, diffed, and fed back into the approval-first workflow.

**Phase Context**

- Goal link: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- Rationale link: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-121: Watch CRUD commands

- **Actual bead**: `bd-hl2s.13.2`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-12`
- **Depends on**: bd-hl2s.13.1, bd-hl2s.9.2

**Intent**

`watch add/list/pause/run-now`.

**Why This Exists**

Change Radar only makes sense once cached knowledge can be monitored, diffed, and fed back into the approval-first workflow.

**Phase Context**

- Goal link: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- Rationale link: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-122: URL and local-file adapters

- **Actual bead**: `bd-hl2s.13.3`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-12`
- **Depends on**: bd-hl2s.13.1

**Intent**

HEAD/GET with etag/last-modified/body-hash for web URLs; mtime+size+hash for local files. Per Supplement §10.4.

**Why This Exists**

Change Radar only makes sense once cached knowledge can be monitored, diffed, and fed back into the approval-first workflow.

**Phase Context**

- Goal link: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- Rationale link: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-123: Change detection pipeline

- **Actual bead**: `bd-hl2s.13.4`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-12`
- **Depends on**: bd-hl2s.13.3, bd-hl2s.4.4

**Intent**

Per Supplement §10.5 — scheduler → adapter → compare → change_event → delta_briefing → inbox item if material.

**Why This Exists**

Change Radar only makes sense once cached knowledge can be monitored, diffed, and fed back into the approval-first workflow.

**Phase Context**

- Goal link: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- Rationale link: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- Impact: Material changes invalidate notebook/workspace fingerprints and mark related query_runs as potentially stale.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-124: Delta briefing generation

- **Actual bead**: `bd-hl2s.13.5`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-12`
- **Depends on**: bd-hl2s.13.4

**Intent**

Must answer: what changed, severity, affected notebooks/workspaces/queries, recommended action. Per Supplement §10.6.

**Why This Exists**

Change Radar only makes sense once cached knowledge can be monitored, diffed, and fed back into the approval-first workflow.

**Phase Context**

- Goal link: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- Rationale link: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-125: `radar status/list/brief/ignore` commands

- **Actual bead**: `bd-hl2s.13.6`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-12`
- **Depends on**: bd-hl2s.13.4, bd-hl2s.13.5

**Intent**

CLI surface for reviewing radar events.

**Why This Exists**

Change Radar only makes sense once cached knowledge can be monitored, diffed, and fed back into the approval-first workflow.

**Phase Context**

- Goal link: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- Rationale link: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-126: Radar → Inbox integration

- **Actual bead**: `bd-hl2s.13.7`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-12`
- **Depends on**: bd-hl2s.13.4, bd-hl2s.11.1

**Intent**

Material changes create inbox items for approval before import/replacement.

**Why This Exists**

Change Radar only makes sense once cached knowledge can be monitored, diffed, and fed back into the approval-first workflow.

**Phase Context**

- Goal link: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- Rationale link: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- No silent source replacement without policy/approval (Supplement §5.3)
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-127: Drive source stale detection

- **Actual bead**: `bd-hl2s.13.8`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-12`
- **Depends on**: bd-hl2s.13.3

**Intent**

Detect if Drive-synced sources may be stale; stage action in inbox.

**Why This Exists**

Change Radar only makes sense once cached knowledge can be monitored, diffed, and fed back into the approval-first workflow.

**Phase Context**

- Goal link: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- Rationale link: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-128: Research query watch

- **Actual bead**: `bd-hl2s.13.9`
- **Type**: `feature`
- **Priority**: `P3`
- **Scope**: `POST`
- **Parent**: `PHASE-12`
- **Depends on**: bd-hl2s.13.4, bd-hl2s.7.1

**Intent**

Re-run saved Deep Research queries on schedule; diff results; route to inbox.

**Why This Exists**

Change Radar only makes sense once cached knowledge can be monitored, diffed, and fed back into the approval-first workflow.

**Phase Context**

- Goal link: Transform knowledge from "snapshot once, decay" to "selectively monitored."
- Rationale link: Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

## PHASE-13 — Phase 13: Deep Integration + Hardening

- **Actual bead**: `bd-hl2s.14`
- **Scope**: `POST`
- **Goal**: 
- **Rationale**: 
- **Depends on phases**: bd-hl2s.11, bd-hl2s.12, bd-hl2s.8

This phase epic exists to cluster a coherent architectural milestone. It should be used as the review surface for asking whether the codebase has crossed the intended boundary, not merely whether tickets were burned down.

### B-130: Deep Research → Inbox full pipeline

- **Actual bead**: `bd-hl2s.14.1`
- **Type**: `feature`
- **Priority**: `P1`
- **Scope**: `POST`
- **Parent**: `PHASE-13`
- **Depends on**: bd-hl2s.11.5, bd-hl2s.11.4

**Intent**

Full pipeline: research completes → results scored → deduped → clustered → land in inbox with explanations.

**Why This Exists**

The final hardening phase exists to integrate the post-MVP primitives into a coherent system rather than a pile of adjacent features.

**Phase Context**

- Goal link: 
- Rationale link: 

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-131: Workspace compare + contradiction detection

- **Actual bead**: `bd-hl2s.14.2`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-13`
- **Depends on**: bd-hl2s.12.5

**Intent**

Generate "gap fill" proposals from contradictions, route to inbox.

**Why This Exists**

The final hardening phase exists to integrate the post-MVP primitives into a coherent system rather than a pile of adjacent features.

**Phase Context**

- Goal link: 
- Rationale link: 

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-132: Smarter scoring with context

- **Actual bead**: `bd-hl2s.14.3`
- **Type**: `feature`
- **Priority**: `P3`
- **Scope**: `POST`
- **Parent**: `PHASE-13`
- **Depends on**: bd-hl2s.11.3

**Intent**

Scoring considers workspace context, prior inbox decisions, query history.

**Why This Exists**

The final hardening phase exists to integrate the post-MVP primitives into a coherent system rather than a pile of adjacent features.

**Phase Context**

- Goal link: 
- Rationale link: 

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-133: Policy inheritance model

- **Actual bead**: `bd-hl2s.14.4`
- **Type**: `feature`
- **Priority**: `P2`
- **Scope**: `POST`
- **Parent**: `PHASE-13`
- **Depends on**: bd-hl2s.8.1, bd-hl2s.8.2

**Intent**

Per Supplement §13.2 — command override > workspace policy > notebook policy > profile policy.

**Why This Exists**

The final hardening phase exists to integrate the post-MVP primitives into a coherent system rather than a pile of adjacent features.

**Phase Context**

- Goal link: 
- Rationale link: 

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

### B-134: Performance tuning

- **Actual bead**: `bd-hl2s.14.5`
- **Type**: `feature`
- **Priority**: `P3`
- **Scope**: `POST`
- **Parent**: `PHASE-13`
- **Depends on**: nothing

**Intent**

DB vacuum scheduling, FTS rebuild heuristics, fan-out concurrency limits, event log rotation.

**Why This Exists**

The final hardening phase exists to integrate the post-MVP primitives into a coherent system rather than a pile of adjacent features.

**Phase Context**

- Goal link: 
- Rationale link: 

**Implementation Considerations**

- Keep the work aligned with the contract normalization rules and command grammar decisions.
- Use the child tasks as the intended implementation checklist, not as optional suggestions.
- No extra notes were carried in the concise plan beyond the main description and acceptance contract.

**Acceptance**

- 
- All child tasks for this bead are complete.
- Downstream beads can now start without hidden prerequisites left behind.

**Child Tasks**

- None.

## Dependency and Execution Notes

The main dependency graph still comes from the concise master plan. This document simply makes the intent behind those edges explicit and records the actual `br` issue IDs that implement them.

- Use `br ready` for the actionable frontier.
- Use `br dep tree <phase-epic-or-task>` to inspect local dependency shape.
- Use `external_ref` as the stable lookup handle when discussing beads across docs, commits, and messages.

