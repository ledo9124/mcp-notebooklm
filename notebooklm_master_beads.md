# NotebookLM Agent-First CLI — Master Bead Plan

## Key Principles (from plans)

1. **HTTP-only runtime** — Playwright/Patchright only for `auth login`; all operations via `httpx`
2. **`notebooklm` root command** — supersedes Original plan's `cli` prefix
3. **Canonical risk tiers** — `T0_READ`, `T1_LOCAL_MUTATION`, `T2_KNOWLEDGE_MUTATION`, `T3_DESTRUCTIVE`
4. **Unified JSON envelope** — all `--json` output uses the canonical envelope from CONTRACT_NORMALIZATION §3
5. **Manifest-first** — `capabilities.yaml` is single source of truth for commands, intents, risk tiers, doctor checks
6. **Extend `src/notebooklm/`** — no separate `notebooklm_agent/` package (Revised §3.2 decision)
7. **`NOTEBOOKLM_HOME`** — single root for all local state (Revised §8 decision)
8. **Approval-first for knowledge mutations** — no silent imports (Supplement §5.3)
9. **Read-first delivery** — ship read/diagnostic value before mutation-heavy orchestration whenever possible
10. **Compatibility is explicit** — aliases, deprecations, exit codes, and JSON shape are product contract, not incidental behavior

---

## Dependency Legend

| Symbol | Meaning |
|--------|---------|
| `→` | "depends on / blocked by" |
| `P0`–`P4` | Priority (0=critical, 4=backlog) |
| `[MVP]` | Required for MVP release |
| `[POST]` | Post-MVP feature |
| `T0`–`T3` | Risk tier of the command/feature being built |

---

## Phase 0 — Boundary, Packaging, Contract Freeze

> **Goal**: Lock the active product boundary so nothing drifts further. Establish the manifest contract that all subsequent phases build against.
> **Rationale** (Revised §20 Phase 0): The repo is already a CLI/SDK-only codebase, but its product story is still split between the legacy direct-command surface and the planned agent-first grammar. Without freezing the boundary, compatibility policy, and command contract first, later phases will duplicate logic and surprise users.

### B-001: Tighten packaging metadata and product story `[MVP]` `P0`
- **Depends on**: nothing
- **Description**: Make `pyproject.toml`, README positioning, and install-time metadata tell the same truth about the product: this repo is the active `notebooklm` CLI/SDK base that is evolving toward an agent-first contract.
- **Subtasks**:
  - B-001a: Verify `[project]` metadata, entry points, and package discovery match the active CLI/SDK boundary
  - B-001b: Ensure README/install docs describe the current supported surface and the planned agent-first direction without promising removed legacy components
  - B-001c: Keep package/install names stable for `pip install` / `uv` usage even if command grammar changes
- **Acceptance**: `pip install -e .` works; `pip show` metadata is correct; README/help text no longer contradict the active product boundary
- **Notes**: This bead is about truthfulness and migration safety, not just URL cleanup.

### B-002: Freeze CLI grammar, compatibility, and output contract `[MVP]` `P0`
- **Depends on**: B-001
- **Description**: Define the canonical command tree, context-resolution rules, alias/deprecation behavior, human-output expectations, and JSON/error contract before new command families proliferate.
- **Subtasks**:
  - B-002a: Freeze the canonical command grammar (`auth`, `notebook`, `source`, `sync`, workflow roots, maintenance commands)
  - B-002b: Document notebook/context resolution precedence, interactive vs non-interactive exit behavior, and human vs JSON output expectations
  - B-002c: Explicitly decide which legacy commands remain as aliases, what warning copy they emit, and which old forms are intentionally unsupported
- **Acceptance**: There is one documented command/output contract that manifest, help text, docs, and implementation can all point to; backward compatibility is explicit instead of accidental
- **Notes**: This is the user-facing contract freeze bead for the whole program.

### B-003: Create `contracts/capabilities.yaml` manifest `[MVP]` `P0`
- **Depends on**: B-001
- **Description**: Create the canonical manifest file that defines all commands, intents, risk tiers, cache entities, and doctor checks. This is the **single source of truth** the entire system builds against.
- **Subtasks**:
  - B-003a: Create `src/notebooklm/contracts/capabilities.yaml` with MVP commands (ask, overview, summarize, study-guide, audio, research.start, research.wait, notebook.delete, source.delete, cache.prune)
  - B-003b: Add command metadata for aliases/deprecation state and whether each command is read-only, waitable, destructive, or approval-gated
  - B-003c: Add `cache_entities` list (notebooks, sources, artifacts, research_runs, query_runs, query_results, sync_runs, run_events, approval_requests)
  - B-003d: Add `doctor_checks` list (auth_snapshot_present, auth_snapshot_fresh, build_label_present, db_openable, schema_current, write_permissions_ok, notebooklm_home_consistent)
  - B-003e: Add risk_tier mapping per CONTRACT_NORMALIZATION §1 (T0_READ through T3_DESTRUCTIVE)
- **Acceptance**: YAML parses cleanly; a Python loader can read it; all MVP commands are present with correct intents/tiers
- **Rationale**: Revised §7 — "Router, doctor, docs, JSON schema và tests phải cùng nhìn vào một contract." ACFS manifest pattern. Without this, we get drift between CLI help, router logic, doctor checks, and documentation.

### B-004: Create contract test suite for capabilities manifest `[MVP]` `P1`
- **Depends on**: B-003
- **Description**: Write tests that validate the manifest against actual registered CLI commands and JSON envelope schemas. These tests **break** if someone adds a command without updating the manifest.
- **Subtasks**:
  - B-004a: Test that every registered Click/Typer command maps to a manifest entry
  - B-004b: Test that every manifest command has a valid intent and risk tier
  - B-004c: Test that alias/deprecation metadata matches the implemented compatibility layer
  - B-004d: Test that JSON envelope schema matches CONTRACT_NORMALIZATION §3
- **Acceptance**: Tests pass; adding an unregistered command or undocumented alias fails the test

### B-005: Create `src/notebooklm/contracts/` Python package `[MVP]` `P1`
- **Depends on**: B-003
- **Description**: Create the contracts package with loaders for capabilities.yaml, envelope schema definitions, intent enums, and RPC map.
- **Subtasks**:
  - B-005a: `__init__.py` with manifest loader
  - B-005b: `envelope_schema.py` — Pydantic/dataclass models for canonical JSON envelope
  - B-005c: `intents.py` — Intent enum (LOCAL_METADATA, REMOTE_METADATA, QUERY, GENERATION, RESEARCH, DOCTOR, WORKSPACE_QUERY, WORKSPACE_COMPARE, RADAR_STATUS, RADAR_BRIEF, INBOX_TRIAGE, INBOX_APPLY)
  - B-005d: `rpc_map.py` — mapping from intent+mode to RPC method/endpoint
  - B-005e: `command_specs.py` — typed command/alias metadata for help text, routing, and compatibility checks
  - B-005f: `risk.py` — risk tier enum and guard decorator
- **Acceptance**: `from notebooklm.contracts import load_capabilities, RiskTier, Intent, Envelope, CommandSpec` works

---

## Phase 1 — Auth/Runtime Hardening

> **Goal**: Make the transport layer fully agent-ready by ensuring `build_label` is first-class, auth refresh is complete, and URL building is unified.
> **Rationale** (Revised §9, Original §3.12): `bl` is the biggest transport gap. Without it, RPC calls may silently fail or return stale responses. The current code has `bl` as optional; the new design makes it mandatory.

### B-010: Add `build_label` to `AuthTokens` and session snapshot `[MVP]` `P0`
- **Depends on**: B-001
- **Description**: Extend `AuthTokens` dataclass to include `build_label` as a mandatory field. Update `fetch_tokens()` to extract `bl` from the NotebookLM homepage alongside `SNlM0e` and `FdrFJe`.
- **Subtasks**:
  - B-010a: Add `build_label: str` field to `AuthTokens`
  - B-010b: Update homepage HTML parser to extract `bl` value
  - B-010c: Validate `bl` is non-empty on every snapshot creation
  - B-010d: Add `bl` to `storage_state.json` persistence if not already
- **Acceptance**: `AuthTokens.from_storage()` returns object with non-empty `build_label`
- **Risk note**: `bl` extraction depends on NotebookLM homepage HTML structure. May need reverse-engineering pass (Open Question #1 from Revised §22).

### B-011: Unify URL builder to always send `bl` `[MVP]` `P0`
- **Depends on**: B-010
- **Description**: Patch `ClientCore._build_url()` to use a unified helper that always includes `rpcids`, `source-path`, `f.sid`, `bl`, and `rt` parameters.
- **Subtasks**:
  - B-011a: Create `_build_rpc_params()` helper that constructs the full param dict
  - B-011b: Refactor `_build_url()` to use the helper
  - B-011c: Ensure `QUERY_URL` and `BATCHEXECUTE_URL` both receive `bl`
  - B-011d: Add test that URL always contains `bl=` parameter
- **Acceptance**: Every outgoing RPC URL includes `bl`; no code path skips it

### B-012: Complete auth refresh to update all three dynamic fields `[MVP]` `P0`
- **Depends on**: B-010, B-011
- **Description**: Current `refresh_auth()` only refreshes CSRF + session ID. Must also refresh `bl`.
- **Subtasks**:
  - B-012a: Update `refresh_auth()` to re-extract `bl` from homepage
  - B-012b: Add retry logic: on 401/403 or build mismatch, refresh once then retry
  - B-012c: Only reopen browser if cookie-based refresh fails
  - B-012d: Write auth snapshot to DB after successful refresh
- **Acceptance**: After `bl` rotation on Google's side, CLI auto-recovers without browser

### B-013: Add `auth inspect` and `auth refresh` CLI commands `[MVP]` `P1`
- **Depends on**: B-012, B-005
- **Description**: New commands for agent diagnostics. `auth inspect` shows snapshot fields (redacted). `auth refresh` forces a refresh cycle.
- **Subtasks**:
  - B-013a: `notebooklm auth inspect` — shows profile, snapshot age, bl presence, csrf presence, cookie fingerprint (not raw cookies)
  - B-013b: `notebooklm auth refresh` — forces homepage GET refresh, writes new snapshot
  - B-013c: Both support `--json` with canonical envelope
- **Acceptance**: Agent can check auth health programmatically

### B-014: Add auth refresh + retry + 429 handling to transport `[MVP]` `P1`
- **Depends on**: B-012
- **Description**: Production-grade transport hardening: retry on transient errors, auth refresh on 401/403, backoff on 429.
- **Subtasks**:
  - B-014a: Implement retry decorator with configurable max retries
  - B-014b: Auto-refresh auth on 401/403 (once per request chain)
  - B-014c: Exponential backoff on 429 with jitter
  - B-014d: Record retry/refresh events in run_events (links to Phase 4)
- **Acceptance**: CLI survives transient auth expiry and rate limiting without user intervention

---

## Phase 2 — SQLite + Profile Isolation

> **Goal**: Replace the ephemeral context-file approach with a durable SQLite cache that supports multiple profiles.
> **Rationale** (Revised §10, Original §3.3): Without durable local state, there's no local-first metadata, no exact query reuse, no routing memory. SQLite is zero-dependency, portable, inspectable.

### B-020: Bootstrap SQLite database with migration framework `[MVP]` `P0`
- **Depends on**: B-003
- **Description**: Create `cache.db` in `NOTEBOOKLM_HOME` with a migration system (simple version-table approach).
- **Subtasks**:
  - B-020a: Create `src/notebooklm/local/db.py` — connection factory, WAL mode, journal settings
  - B-020b: Create `src/notebooklm/local/migrations.py` — version-tracked migration runner
  - B-020c: Create initial migration (v1) with all MVP tables
  - B-020d: Add `schema_version` to `app_state` table
- **Acceptance**: `db.py` creates/opens DB, runs migrations idempotently, WAL mode active

### B-021: Create `profiles` and `auth_snapshots` tables `[MVP]` `P0`
- **Depends on**: B-020
- **Description**: Per Revised §9.2 and CONTRACT_NORMALIZATION. Profile isolation is foundational — every subsequent table is profile-scoped.
- **Subtasks**:
  - B-021a: Create `profiles` table (profile_id PK, display_name, account_email, is_default, storage_state_path, browser_profile_path, timestamps)
  - B-021b: Create `auth_snapshots` table (profile_id FK, cookie_fingerprint, csrf_token, session_id, build_label, captured_at, validated_at, status, source)
  - B-021c: Create `app_state` table (active_profile_id, current_notebook_id, current_conversation_id, schema_version)
  - B-021d: Create `profiles/manager.py` — CRUD + switching logic
- **Acceptance**: Can create/switch profiles; auth snapshots persist across restarts

### B-022: Legacy profile migration `[MVP]` `P1`
- **Depends on**: B-021
- **Description**: If `NOTEBOOKLM_HOME` already has `storage_state.json` and `browser_profile/`, treat as legacy default profile. Don't move files — just map them in DB.
- **Subtasks**:
  - B-022a: Detect legacy layout on first DB creation
  - B-022b: Create `default` profile row pointing to existing paths
  - B-022c: Import existing auth state into `auth_snapshots`
  - B-022d: Import legacy `context.json` notebook/conversation selections into `app_state`
  - B-022e: Only physically migrate when user requests or doctor suggests
- **Acceptance**: Existing users lose no state on upgrade

### B-023: Create core metadata cache tables `[MVP]` `P0`
- **Depends on**: B-020
- **Description**: Create `notebooks`, `sources`, `artifacts`, `research_runs` tables per Original §3.5 / Revised §10.1.
- **Subtasks**:
  - B-023a: `notebooks` — all columns from Original §3.5B including normalized_title, tombstoned_at, raw_json
  - B-023b: `sources` — source_type, title, origin_uri, status, freshness_state, synced_at, tombstoned_at
  - B-023c: `artifacts` — artifact_type, submode, prompt_hash, status, download_ref, timestamps
  - B-023d: `research_runs` — mode, query_text, status, discovered/imported counts
  - B-023e: Create `src/notebooklm/local/repositories.py` — repository classes for each table
- **Acceptance**: Full CRUD on all four tables; profile-scoped queries work

### B-024: Create execution/history tables `[MVP]` `P1`
- **Depends on**: B-020
- **Description**: `query_runs`, `query_results`, `sync_runs` per Original §3.5C and Revised §10.1.
- **Subtasks**:
  - B-024a: `query_runs` with all columns per CONTRACT_NORMALIZATION §5 (id prefix `qr_`, trace_id, profile_id, status column pattern)
  - B-024b: `query_results` — one-to-one with query_runs
  - B-024c: `sync_runs` with prefix `sr_` per CONTRACT_NORMALIZATION §5
  - B-024d: Repository methods for insert/update/query
- **Acceptance**: Run history persists and is queryable

### B-025: Create `run_events` unified event log `[MVP]` `P1`
- **Depends on**: B-020
- **Description**: Append-only event log per Revised §10.2 and CONTRACT_NORMALIZATION §5. All subsystems emit events here.
- **Subtasks**:
  - B-025a: `run_events` table (event_id PK `evt_<ulid>`, trace_id indexed, run_id nullable, kind, ts, payload_json)
  - B-025b: Canonical event kinds from CONTRACT_NORMALIZATION §5 (route.resolved, cache.hit, cache.miss, sync.started, sync.finished, auth.refreshed, etc.)
  - B-025c: Event emitter helper that auto-generates event_id and timestamp
  - B-025d: Index on trace_id for fast lookups
- **Acceptance**: Events can be appended and queried by trace_id

### B-026: Create MVP indexes `[MVP]` `P1`
- **Depends on**: B-023, B-024
- **Description**: Per Original §3.6 / Revised §10.3 — indexes critical for routing and query performance.
- **Subtasks**:
  - B-026a: `notebooks(profile_id, normalized_title)`
  - B-026b: `sources(notebook_id, status)` and `sources(profile_id, source_type)`
  - B-026c: `artifacts(notebook_id, status)`
  - B-026d: `query_runs(prompt_hash, notebook_fingerprint, intent)`
  - B-026e: `sync_runs(profile_id, scope, started_at)`
- **Acceptance**: Explain query plans show index usage

### B-027: Implement `cache status` and `cache prune` commands `[MVP]` `P2`
- **Depends on**: B-023, B-005
- **Description**: Basic cache diagnostics and maintenance.
- **Subtasks**:
  - B-027a: `notebooklm cache status` — shows table row counts, DB size, WAL size, oldest/newest sync timestamps
  - B-027b: `notebooklm cache prune` — removes tombstoned rows older than threshold, vacuums DB
  - B-027c: `cache prune` is `T1_LOCAL_MUTATION` — supports `--dry-run`
  - B-027d: Both support `--json`
- **Acceptance**: Agent can inspect and maintain cache health

### B-028: Notebook fingerprint implementation `[MVP]` `P1`
- **Depends on**: B-023
- **Description**: Per Original §3.8 / Revised §11.2 — SHA-256 over canonical notebook state for cache reuse decisions.
- **Subtasks**:
  - B-028a: Create `src/notebooklm/local/fingerprints.py`
  - B-028b: Compute fingerprint from: notebook title + summary + ordered source IDs/statuses/fingerprints + ordered artifact IDs/statuses + settings
  - B-028c: Store fingerprint in `notebooks.remote_fingerprint`
  - B-028d: Recompute on every notebook detail sync
- **Acceptance**: Same notebook state → same fingerprint; source add/remove → different fingerprint

---

## Phase 3 — Metadata Sync + Local-First

> **Goal**: Make metadata commands local-first with automatic freshness-gated remote sync.
> **Rationale** (Revised §17, Original §3.7): This is what makes the CLI feel instant for metadata lookups while staying accurate.

### B-030: Notebook index sync `[MVP]` `P0`
- **Depends on**: B-023, B-012
- **Description**: Sync the notebook list from remote via `LIST_NOTEBOOKS` RPC, upsert into local cache.
- **Subtasks**:
  - B-030a: Create `src/notebooklm/sync/notebooks.py`
  - B-030b: Parse `LIST_NOTEBOOKS` response, upsert `notebooks` rows
  - B-030c: Tombstone notebooks that disappeared from remote
  - B-030d: Record sync_run with stats
  - B-030e: Freshness window: 5 minutes (configurable)
- **Acceptance**: `notebook list` returns from cache when fresh, syncs when stale

### B-031: Notebook detail sync `[MVP]` `P0`
- **Depends on**: B-030
- **Description**: Sync individual notebook details via `GET_NOTEBOOK` — sources, artifacts, counts.
- **Subtasks**:
  - B-031a: Parse notebook detail response
  - B-031b: Upsert sources from notebook detail
  - B-031c: Upsert artifact summaries
  - B-031d: Update notebook fingerprint
  - B-031e: Freshness window: 2 minutes
- **Acceptance**: Source list for a notebook is available locally after sync

### B-032: Source metadata reconciliation `[MVP]` `P1`
- **Depends on**: B-031
- **Description**: Keep source rows in sync with reality — handle status transitions (preparing→processing→ready), tombstone deletions.
- **Subtasks**:
  - B-032a: Create `src/notebooklm/sync/sources.py`
  - B-032b: Status-aware freshness: `ready` sources → 10min; `processing/preparing` → 15sec poll
  - B-032c: Tombstone sources missing from notebook detail
- **Acceptance**: Source statuses accurately reflect remote state

### B-033: Invalidation helpers `[MVP]` `P1`
- **Depends on**: B-030, B-031
- **Description**: Per Original §3.7 — mutation-triggered cache invalidation rules.
- **Subtasks**:
  - B-033a: Create `src/notebooklm/sync/invalidation.py`
  - B-033b: Notebook create → invalidate notebook index
  - B-033c: Source add/delete/refresh → invalidate notebook detail
  - B-033d: Artifact create → insert pending + invalidate notebook detail
  - B-033e: Research import → invalidate notebook detail + source list
- **Acceptance**: After mutation, next metadata read triggers fresh sync

### B-034: Implement `notebook list`, `notebook show`, `notebook use` commands `[MVP]` `P0`
- **Depends on**: B-030, B-031, B-005
- **Description**: Core metadata CLI commands using local-first pattern.
- **Subtasks**:
  - B-034a: `notebooklm notebook list` — local-first, sync if stale, support `--refresh` / offline-safe behavior
  - B-034b: `notebooklm notebook show <id-or-title>` — resolves by ID or title (exact/fuzzy), shows detail, and surfaces freshness/provenance
  - B-034c: `notebooklm notebook use <id-or-title>` — sets current context
  - B-034d: All use canonical envelope when `--json`, including whether data came from cache vs remote
- **Acceptance**: Fast local responses; stale cache auto-refreshes

### B-035: Implement `source list` and `sync notebooks` commands `[MVP]` `P1`
- **Depends on**: B-032, B-034
- **Subtasks**:
  - B-035a: `notebooklm source list [--notebook X]` — profile-scoped, filterable
  - B-035b: `notebooklm source guide <source-id>` — remote required, cache result, and expose freshness metadata
  - B-035c: `notebooklm sync notebooks [--all | --notebook X]` — explicit sync trigger with scoped stats in human and JSON modes
- **Acceptance**: Full metadata browsing works locally and users can tell when they are looking at cached vs freshly synced data

---

## Phase 4 — Agent Memory + Observability

> **Goal**: Give the agent the ability to look back, search, and explain past decisions.
> **Rationale** (Revised §11, §14): "Agent-first" means the system must remember and self-observe. Without trace/history, debugging routing decisions is impossible.

### B-040: Tracing infrastructure `[MVP]` `P1`
- **Depends on**: B-025
- **Description**: Every command execution generates a `trace_id`. All events, run table rows, and envelope outputs reference it.
- **Subtasks**:
  - B-040a: Create `src/notebooklm/observability/tracing.py` — trace context manager
  - B-040b: Generate `trc_<ulid>` on command entry
  - B-040c: Thread trace_id through sync, router, transport calls
  - B-040d: Include trace_id in JSON envelope output
- **Acceptance**: Every `--json` output has a `trace_id`; `run_events` filtered by trace_id shows full execution story

### B-041: Implement `history search` and `history show` `[MVP]` `P2`
- **Depends on**: B-024, B-040
- **Description**: Searchable query history with FTS.
- **Subtasks**:
  - B-041a: Create `history_fts` virtual table indexing prompt, answer, notebook title, source titles
  - B-041b: `notebooklm history search "term"` — FTS search over past runs
  - B-041c: `notebooklm history show <run-id>` — full run detail with route decision, result, timing
  - B-041d: Both support `--json`
- **Acceptance**: Agent can find past runs by keyword

### B-042: Implement `trace show` and `events tail` `[MVP]` `P2`
- **Depends on**: B-040, B-025
- **Subtasks**:
  - B-042a: `notebooklm trace show <trace-id>` — full event timeline for a trace
  - B-042b: `notebooklm events tail` — stream recent events, optionally `--follow`
  - B-042c: Both support `--json`
- **Acceptance**: Full observability into system behavior

### B-043: Wire envelope with trace_id and run_id `[MVP]` `P1`
- **Depends on**: B-005, B-040
- **Description**: Every command output includes the canonical envelope with trace_id, run_id, route info, freshness, cache_updates, diagnostics.
- **Acceptance**: `--json` output on any command matches CONTRACT_NORMALIZATION §3 schema

---

## Phase 5 — Workflow Commands

> **Goal**: Ship the core work commands that make the CLI useful: ask, overview, summarize, study-guide, audio.
> **Rationale**: These are the "product" — everything else is infrastructure. Without these, there's nothing for users to do.

### B-049: Build shared workflow runtime helpers `[MVP]` `P0`
- **Depends on**: B-034, B-014, B-043, B-028
- **Description**: Create the common runtime that all workflow commands share: notebook/context resolution, polling, cache-writeback hooks, and human/JSON output shaping.
- **Subtasks**:
  - B-049a: Create `src/notebooklm/workflows/runtime.py`
  - B-049b: Centralize notebook resolution and current-context fallback using the contract precedence rules
  - B-049c: Add shared polling/wait helpers for long-running operations and retry-aware progress reporting
  - B-049d: Add shared result rendering helpers so human output and JSON envelope stay aligned across commands
  - B-049e: Add common cache-writeback and run-event hooks for workflow commands
- **Acceptance**: Ask, overview, summarize, study-guide, audio, and research commands can all build on one workflow runtime instead of duplicating control flow

### B-050: Implement `ask` command `[MVP]` `P0`
- **Depends on**: B-024, B-049
- **Description**: Conversational Q&A against a notebook via `QUERY_URL` free-form query endpoint.
- **Subtasks**:
  - B-050a: Create `src/notebooklm/workflows/ask.py`
  - B-050b: Resolve notebook (resolution order from CONTRACT_NORMALIZATION §4)
  - B-050c: Send query via `httpx` to `QUERY_URL`
  - B-050d: Record query_run + query_result
  - B-050e: Emit run_events (route.resolved, cache.miss/hit)
  - B-050f: Support exact-reuse when fingerprint matches (advisory)
  - B-050g: Human-readable output + `--json` envelope
- **Acceptance**: `notebooklm ask "question"` returns grounded answer, records history

### B-051: Implement `overview` command `[MVP]` `P1`
- **Depends on**: B-049
- **Description**: Quick remote summary via `SUMMARIZE` RPC — lightweight, not a full report.
- **Acceptance**: Returns concise summary, cached with notebook fingerprint

### B-052: Implement `summarize` (briefing doc) command `[MVP]` `P0`
- **Depends on**: B-049
- **Description**: `CREATE_ARTIFACT` with `briefing_doc` mode. Supports `--wait` for polling.
- **Subtasks**:
  - B-052a: Create `src/notebooklm/workflows/summarize.py`
  - B-052b: Insert artifact row as `pending`
  - B-052c: If `--wait`, poll until terminal status
  - B-052d: Invalidate notebook detail after creation
- **Acceptance**: Briefing doc generation works end-to-end

### B-053: Implement `study-guide` and `audio` commands `[MVP]` `P1`
- **Depends on**: B-052
- **Description**: Same pattern as summarize but with `study_guide` and `audio` modes.
- **Acceptance**: Both artifact types generate successfully

### B-054: Alias migration layer `[MVP]` `P2`
- **Depends on**: B-002, B-050, B-051, B-052, B-053
- **Description**: Per Revised §13.2 — transitional aliases from old command names.
- **Acceptance**: Old-style commands produce deprecation warning + work

### B-055: Implement `source delete` and `notebook delete` commands `[MVP]` `P1`
- **Depends on**: B-033, B-035, B-070, B-071
- **Description**: Add the missing destructive management commands promised by the manifest, with preview, confirmation, approval, and cache reconciliation built in from the start.
- **Subtasks**:
  - B-055a: `notebooklm source delete <id>` — resolve source, show impact, enforce risk guard, and tombstone local cache on success
  - B-055b: `notebooklm notebook delete <id-or-title>` — resolve notebook, enforce destructive confirmation/approval flow, and invalidate related cache state
  - B-055c: Both commands return canonical refusal/resume envelopes in non-interactive mode
  - B-055d: Both commands emit run_events and update local metadata so subsequent reads reflect the deletion
- **Acceptance**: The CLI can safely delete sources and notebooks without silent destructive behavior, and local cache state stays truthful after success or refusal

---

## Phase 6 — Research + Router

> **Goal**: Complete the research workflow and build the NL routing layer that classifies `agent` requests.
> **Rationale**: Research is the highest-latency workflow in the MVP, and the router is the force multiplier that turns many explicit commands into one request surface. Both have to stay explicit about freshness, provenance, and mutation risk.

### B-060: Implement `research start` and `research wait` `[MVP]` `P0`
- **Depends on**: B-023, B-049
- **Description**: Safe read-side research lifecycle: start a research run, persist it, and wait/poll for completion without importing anything into notebook state yet.
- **Subtasks**:
  - B-060a: `research start "query" --mode fast|deep` — starts research, inserts research_run row
  - B-060b: `research wait <id>` — bounded polling loop, updates research_run status
  - B-060c: Persist discovered-source metadata and summary so the user can inspect a run before import
  - B-060d: All record run_events
- **Acceptance**: Users can start and observe research runs programmatically, with durable history, before any knowledge mutation occurs

### B-063: Implement approval-aware `research import` flow `[MVP]` `P1`
- **Depends on**: B-033, B-060, B-070, B-071
- **Description**: Import discovered research sources only through an explicit preview/approval path so MVP already honors the approval-first rule without waiting for the full post-MVP inbox.
- **Subtasks**:
  - B-063a: `research import <id>` builds a deterministic candidate list with title, URL, and dedupe/provenance summary
  - B-063b: Add `--dry-run` / preview output so humans and agents can inspect exactly what would change
  - B-063c: In non-interactive mode, create an approval request and resume token instead of silently importing
  - B-063d: On approval, import sources and invalidate notebook detail + source list
- **Acceptance**: Research imports cannot happen silently; the CLI supports preview, refusal, approval, and resume for research mutations

### B-061: Implement `agent` NL routing command `[MVP]` `P1`
- **Depends on**: B-050, B-051, B-052, B-053, B-060, B-063, B-005
- **Description**: `notebooklm agent "natural language request"` — classifies into intent bucket, resolves target, executes.
- **Subtasks**:
  - B-061a: Create `src/notebooklm/router/classify.py` — intent classification into LOCAL_METADATA, REMOTE_METADATA, QUERY, GENERATION, RESEARCH
  - B-061b: Create `src/notebooklm/router/resolve.py` — notebook resolution (6-step cascade from Revised §12.3)
  - B-061c: Create `src/notebooklm/router/freshness.py` — cache mode enforcement
  - B-061d: Create `src/notebooklm/router/execute.py` — dispatch to appropriate workflow
  - B-061e: Structured commands always win (Revised §12.2)
- **Acceptance**: `agent "summarize the current notebook"` → routes to summarize workflow

### B-062: Implement `route --dry-run` and `route explain` `[MVP]` `P1`
- **Depends on**: B-061
- **Description**: Diagnostic commands that show what the router would do without executing.
- **Subtasks**:
  - B-062a: `notebooklm route "request" --dry-run` — shows intent, target notebook, mode, transport, freshness decision
  - B-062b: `notebooklm route explain "request"` — verbose explanation of routing logic
  - B-062c: Both support `--json`
- **Acceptance**: Agent can preview and verify routing decisions before execution

---

## Phase 7 — Safety + Doctor + Support Bundle (MVP)

> **Goal**: Add the safety guardrails and basic diagnostics that make the system trustworthy for agent use.
> **Rationale** (Revised §15-16): Agent-first without guardrails for mutations is dangerous. Doctor without safety is incomplete.

### B-070: Implement risk tier classification and guards `[MVP]` `P1`
- **Depends on**: B-003, B-005
- **Description**: Per CONTRACT_NORMALIZATION §1 — every command has a risk tier; guards enforce approval/confirmation based on tier.
- **Subtasks**:
  - B-070a: `T0_READ` — no guard
  - B-070b: `T1_LOCAL_MUTATION` — `--dry-run` supported; `--yes` if side effect large
  - B-070c: `T2_KNOWLEDGE_MUTATION` — approval required by default
  - B-070d: `T3_DESTRUCTIVE` — explicit confirm/approval token; two-step in non-interactive
  - B-070e: Create guard decorator that reads risk_tier from capabilities.yaml
  - B-070f: Guard failures return canonical refusal output with the exact next step (`--yes`, approval token, resume token, or dry-run)
- **Acceptance**: `source delete` without `--yes` or approval token is rejected in non-interactive mode and tells the user exactly how to proceed

### B-071: Create `approval_requests` table `[MVP]` `P1`
- **Depends on**: B-020
- **Description**: Per CONTRACT_NORMALIZATION §2 — unified approval schema.
- **Subtasks**: Create table with all columns from §2 (id, trace_id, entity_type, entity_id, action, risk_tier, policy_name, requested_by, requested_at, resolved_at, status, reason, resume_token, decision_json)
- **Acceptance**: Approval requests can be created, queried, and resolved

### B-072: Implement `doctor` fast mode `[MVP]` `P1`
- **Depends on**: B-020, B-021, B-003
- **Description**: Per Supplement §8.3 — quick health check with JSON output and meaningful exit codes.
- **Subtasks**:
  - B-072a: Auth checks (snapshot present, fresh, bl present)
  - B-072b: DB checks (openable, schema current, write permissions)
  - B-072c: Path checks (NOTEBOOKLM_HOME consistent)
  - B-072d: Exit code: 0=healthy, 1=degraded, 2=broken
  - B-072e: JSON output per CONTRACT_NORMALIZATION §3 (wrapped in canonical envelope `.result`)
- **Acceptance**: `doctor` correctly diagnoses cold install, degraded auth, corrupted DB

### B-073: Implement `doctor fix --dry-run` `[MVP]` `P2`
- **Depends on**: B-072
- **Description**: Low-risk idempotent repairs.
- **Subtasks**:
  - B-073a: Create missing dirs
  - B-073b: Migrate legacy profile mapping
  - B-073c: Clear stale locks/leases
  - B-073d: Mark broken auth snapshot invalid
  - B-073e: `--dry-run` shows what would be fixed without doing it
- **Acceptance**: Fixes 70%+ of common issues without human intervention

### B-074: Implement `support-bundle create` `[MVP]` `P2`
- **Depends on**: B-072
- **Description**: Redacted diagnostic bundle for debugging.
- **Subtasks**: Bundle includes manifest version, OS/Python versions, redacted config, auth fingerprints (no raw cookies), recent doctor findings, recent traces, DB stats
- **Acceptance**: Bundle never contains raw secrets; useful for remote debugging

---

## Phase 8 — Post-MVP: Shared Foundations for Advanced Features `[POST]`

> **Goal**: Lay the shared infrastructure (tables, leases, extended approval engine, trace events) that Doctor deep mode, Workspaces, Change Radar, and Research Inbox all need.
> **Rationale** (Supplement §16 Phase A): These four features share primitives. Building them once prevents duplication.

### B-080: Create `leases` table `[POST]` `P1`
- **Depends on**: B-020
- **Description**: Per CONTRACT_NORMALIZATION §6 — DB-based advisory locks for concurrency safety.
- **Acceptance**: Leases can be acquired, released, expired; stale leases detectable

### B-081: Extend `capabilities.yaml` with post-MVP commands `[POST]` `P1`
- **Depends on**: B-003
- **Description**: Add doctor.fix, doctor.bundle, workspace.*, watch.*, radar.*, inbox.* commands with intents and risk tiers per CONTRACT_NORMALIZATION §7.
- **Acceptance**: All post-MVP commands are manifest-described

### B-082: Create post-MVP run tables `[POST]` `P1`
- **Depends on**: B-020
- **Description**: Per CONTRACT_NORMALIZATION §5 — `workspace_runs` (prefix `wr_`), `watch_runs` (`wtr_`), `doctor_runs` (`dr_`).
- **Acceptance**: All follow typed run table pattern with trace_id linkage

### B-083: Extend `run_events` with post-MVP event kinds `[POST]` `P1`
- **Depends on**: B-025
- **Description**: Add event kinds from Supplement §6.3 (doctor.*, workspace.*, watch.*, inbox.*, approval.resolved).
- **Acceptance**: All subsystems emit to unified event log

---

## Phase 9 — Post-MVP: Doctor Deep + Advanced Repairs `[POST]`

### B-090: Doctor deep mode `[POST]` `P1`
- **Depends on**: B-072, B-080
- **Description**: Per Supplement §8.3 — remote auth probe, RPC canary, cache integrity, FTS health, foreign key checks.
- **Acceptance**: `doctor --deep` catches issues that fast mode misses

### B-091: Doctor category checks `[POST]` `P2`
- **Depends on**: B-090
- **Description**: `doctor check auth`, `doctor check db`, `doctor check workspace`, `doctor check radar`, `doctor check inbox`.
- **Acceptance**: Targeted diagnostics for specific subsystems

### B-092: Advanced repair coverage `[POST]` `P2`
- **Depends on**: B-073, B-090
- **Description**: Rebuild FTS, retry stuck watch, vacuum/analyze, resync notebook metadata.

---

## Phase 10 — Post-MVP: Research Inbox `[POST]`

> **Goal**: The knowledge intake valve — no source enters a notebook without passing through triage.
> **Rationale** (Supplement §11): NotebookLM's existing review-then-import model for research is the perfect foundation. We extend it with persistence, scoring, dedupe, and approval.

### B-100: Create inbox tables `[POST]` `P1`
- **Depends on**: B-020, B-071
- **Description**: `inbox_items`, `inbox_clusters` per Supplement §7.4.
- **Acceptance**: Items can be created, queried, clustered

### B-101: Inbox CRUD commands `[POST]` `P1`
- **Depends on**: B-100, B-081
- **Description**: `inbox list`, `inbox view`, `inbox approve`, `inbox reject`, `inbox defer`, `inbox import`.
- **Acceptance**: Full triage workflow from CLI

### B-102: Inbox scoring engine `[POST]` `P2`
- **Depends on**: B-100
- **Description**: Relevance, novelty, trust scores per Supplement §11.5. Deterministic base with optional LLM rationale.

### B-103: Dedupe/cluster engine `[POST]` `P2`
- **Depends on**: B-100
- **Description**: Canonical URL, normalized title, content hash, domain similarity. Per Supplement §11.6.

### B-104: Research results → inbox pipeline `[POST]` `P1`
- **Depends on**: B-100, B-060, B-063
- **Description**: Fast/Deep Research results land in inbox instead of direct import.
- **Acceptance**: `research import` routes through inbox approval

### B-105: Inbox apply with `--batch` and `--filter` `[POST]` `P2`
- **Depends on**: B-101
- **Description**: Bulk triage for efficiency.

### B-106: Approval interruption + resume token `[POST]` `P2`
- **Depends on**: B-071, B-101
- **Description**: Per Supplement §11.7 — agent pause/resume pattern for HITL.

---

## Phase 11 — Post-MVP: Workspaces `[POST]`

> **Goal**: Cross-notebook reasoning via local orchestration.
> **Rationale** (Supplement §9): NotebookLM notebooks are isolated. Workspace = virtual grouping for multi-notebook queries with transparent provenance.

### B-110: Create workspace tables `[POST]` `P1`
- **Depends on**: B-020
- **Description**: `workspaces`, `workspace_members`, `workspace_rules`, `workspace_index_entries` per Supplement §7.2.

### B-111: Workspace CRUD commands `[POST]` `P1`
- **Depends on**: B-110, B-081
- **Description**: `workspace list/create/add/remove/show`.
- **Acceptance**: Static workspaces can be managed

### B-112: Workspace index (FTS/BM25) `[POST]` `P1`
- **Depends on**: B-110, B-023
- **Description**: Materialized FTS index over notebook titles, summaries, source titles, tags. Per Supplement §9.5 step 1.
- **Acceptance**: `workspace index <name>` builds searchable index

### B-113: Workspace `ask` with fan-out + synthesis `[POST]` `P0`
- **Depends on**: B-112, B-050
- **Description**: The crown jewel — multi-notebook query with transparent provenance.
- **Subtasks**:
  - B-113a: Candidate selection via FTS/BM25
  - B-113b: Planning (1 notebook vs fan-out to top 2-3)
  - B-113c: Fan-out execution (parallel `ask` per notebook)
  - B-113d: Synthesis with provenance (which notebook contributed what)
  - B-113e: Record workspace_run
- **Acceptance**: `workspace ask market-intel "question"` returns synthesized answer with notebook attribution
- **Critical rule**: Output must be transparent that this is multi-notebook planning + per-notebook execution + local synthesis — never imply NotebookLM itself did cross-notebook reasoning (Supplement §9.6)

### B-114: Workspace `compare` mode `[POST]` `P2`
- **Depends on**: B-113
- **Description**: Optimized for contradictions, overlap, differences across notebooks.

### B-115: Workspace as tool / specialist handoff `[POST]` `P2`
- **Depends on**: B-113
- **Description**: Expose workspace as callable tool for external agent hosts. Per Supplement §9.7 and Agents SDK handoff pattern.

---

## Phase 12 — Post-MVP: Change Radar `[POST]`

> **Goal**: Transform knowledge from "snapshot once, decay" to "selectively monitored."
> **Rationale** (Supplement §10): Sources are static copies. Drive files don't auto-sync. Without monitoring, notebooks silently go stale.

### B-120: Create radar tables `[POST]` `P1`
- **Depends on**: B-020
- **Description**: `watches`, `watch_runs`, `source_revisions`, `change_events`, `delta_briefings` per Supplement §7.3.

### B-121: Watch CRUD commands `[POST]` `P1`
- **Depends on**: B-120, B-081
- **Description**: `watch add/list/pause/run-now`.

### B-122: URL and local-file adapters `[POST]` `P1`
- **Depends on**: B-120
- **Description**: HEAD/GET with etag/last-modified/body-hash for web URLs; mtime+size+hash for local files. Per Supplement §10.4.

### B-123: Change detection pipeline `[POST]` `P1`
- **Depends on**: B-122, B-033
- **Description**: Per Supplement §10.5 — scheduler → adapter → compare → change_event → delta_briefing → inbox item if material.
- **Impact**: Material changes invalidate notebook/workspace fingerprints and mark related query_runs as potentially stale.

### B-124: Delta briefing generation `[POST]` `P1`
- **Depends on**: B-123
- **Description**: Must answer: what changed, severity, affected notebooks/workspaces/queries, recommended action. Per Supplement §10.6.

### B-125: `radar status/list/brief/ignore` commands `[POST]` `P1`
- **Depends on**: B-123, B-124
- **Description**: CLI surface for reviewing radar events.

### B-126: Radar → Inbox integration `[POST]` `P1`
- **Depends on**: B-123, B-100
- **Description**: Material changes create inbox items for approval before import/replacement.
- **Acceptance**: No silent source replacement without policy/approval (Supplement §5.3)

### B-127: Drive source stale detection `[POST]` `P2`
- **Depends on**: B-122
- **Description**: Detect if Drive-synced sources may be stale; stage action in inbox.

### B-128: Research query watch `[POST]` `P3`
- **Depends on**: B-123, B-060
- **Description**: Re-run saved Deep Research queries on schedule; diff results; route to inbox.

---

## Phase 13 — Deep Integration + Hardening `[POST]`

### B-130: Deep Research → Inbox full pipeline `[POST]` `P1`
- **Depends on**: B-104, B-103
- **Description**: Full pipeline: research completes → results scored → deduped → clustered → land in inbox with explanations.

### B-131: Workspace compare + contradiction detection `[POST]` `P2`
- **Depends on**: B-114
- **Description**: Generate "gap fill" proposals from contradictions, route to inbox.

### B-132: Smarter scoring with context `[POST]` `P3`
- **Depends on**: B-102
- **Description**: Scoring considers workspace context, prior inbox decisions, query history.

### B-133: Policy inheritance model `[POST]` `P2`
- **Depends on**: B-070, B-071
- **Description**: Per Supplement §13.2 — command override > workspace policy > notebook policy > profile policy.

### B-134: Performance tuning `[POST]` `P3`
- **Depends on**: all prior phases
- **Description**: DB vacuum scheduling, FTS rebuild heuristics, fan-out concurrency limits, event log rotation.

---

## Dependency Graph Summary

```
Phase 0 (Boundary)
  B-001 → B-002, B-003, B-010
  B-002 → B-054
  B-003 → B-004, B-005, B-070, B-081

Phase 1 (Auth)
  B-010 → B-011 → B-012 → B-013, B-014
  
Phase 2 (DB)
  B-020 → B-021, B-023, B-024, B-025, B-071, B-080, B-082, B-100, B-110, B-120
  B-021 → B-022
  B-023 → B-026, B-028

Phase 3 (Sync)
  B-023 + B-012 → B-030 → B-031 → B-032
  B-030 + B-031 → B-033, B-034 → B-035

Phase 4 (Observability)
  B-025 → B-040 → B-041, B-042
  B-005 + B-040 → B-043

Phase 5 (Workflows)
  B-034 + B-014 + B-043 + B-028 → B-049
  B-024 + B-049 → B-050
  B-049 → B-051, B-052
  B-052 → B-053
  B-002 + B-050 + B-051 + B-052 + B-053 → B-054
  B-033 + B-035 + B-070 + B-071 → B-055
    
Phase 6 (Router)
  B-023 + B-049 → B-060
  B-033 + B-060 + B-070 + B-071 → B-063
  B-050 + B-051 + B-052 + B-053 + B-060 + B-063 → B-061 → B-062

Phase 7 (Safety)
  B-003 + B-005 → B-070
  B-020 → B-071
  B-020 + B-021 + B-003 → B-072 → B-073, B-074

Phase 8+ (Post-MVP)
  B-071 + B-100 → B-101 → B-105, B-106
  B-100 + B-060 + B-063 → B-104
  B-110 → B-111, B-112 → B-113 → B-114, B-115
  B-120 → B-121, B-122 → B-123 → B-124, B-125, B-126
```

---

## MVP Critical Path

The shortest path to a usable MVP release:

```
B-001 → B-003 → B-005
B-010 → B-011 → B-012 → B-014
B-020 → B-021 → B-023 → B-030 → B-031 → B-034
B-025 → B-040 → B-043
B-028 + B-034 + B-014 + B-043 → B-049
B-024 + B-049 → B-050
B-049 → B-052 → B-053
B-023 + B-049 → B-060 → B-063
B-050 + B-051 + B-052 + B-053 + B-060 + B-063 → B-061 → B-062
B-033 + B-035 + B-070 + B-071 → B-055
B-072 (parallel with Phase 5-6)
B-070 + B-071 (parallel with Phase 5-6, but required before destructive or knowledge-mutation commands)
```

**Estimated MVP beads**: ~45 tasks across Phases 0-7
**Post-MVP beads**: ~30 tasks across Phases 8-13

---

## Cross-Cutting Concerns (apply to all beads)

1. **Every command must support `--json`** returning the canonical envelope
2. **Every mutation must emit `run_events`** for tracing
3. **Every table must be profile-scoped** via `profile_id` column
4. **Every new command must be registered in `capabilities.yaml`** (enforced by B-004 contract tests)
5. **Risk tier guards apply globally** — no mutation bypasses the safety decorator
6. **Tombstoning over deletion** — remote objects are tombstoned, not deleted from cache
7. **Every read-path JSON response should surface freshness/provenance** so users can tell cache from remote
8. **Compatibility behavior must be explicit** — aliases and deprecation warnings belong in the contract, not just implementation
