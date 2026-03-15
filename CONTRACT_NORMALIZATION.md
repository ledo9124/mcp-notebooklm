# Contract Normalization — Unified Decisions

Ngày chốt: 2026-03-15

**Scope:** This document resolves the four contract conflicts between PLAN-CLI.md (Original), PLAN_NOTEBOOKLM_AGENT_FIRST_REVISED.md (Revised), and PLAN_SUPPLEMENT_DOCTOR_WORKSPACES_CHANGE_RADAR_INBOX.md (Supplement). It supersedes the conflicting sections in all three documents.

**Authority hierarchy:** Revised plan > Supplement > Original plan. This normalization merges where needed.

---

## 1) Unified Risk Tier Taxonomy

### The conflict

- **Revised plan (§15.1)** defines: `SAFE`, `CAUTION`, `DANGEROUS`, `CRITICAL`
- **Supplement (§13.1)** defines: `Tier 0 read-only`, `Tier 1 low-risk mutation`, `Tier 2 external knowledge mutation`, `Tier 3 destructive mutation`

### Resolution

Keep the Supplement's numeric tiers as the canonical taxonomy because they are more precise and carry semantic meaning about *what kind* of mutation is involved. Map the Revised plan's names as aliases for readability.

| Canonical Tier | Alias | Scope | Guard behavior |
|---|---|---|---|
| `T0_READ` | SAFE | Read-only operations: list, show, doctor, ask, history, trace, events, workspace ask, radar brief, inbox view | No approval needed |
| `T1_LOCAL_MUTATION` | CAUTION | Low-risk local mutations: rebuild index, clear stale leases, refresh auth, resync metadata, cache prune | `--dry-run` supported; `--yes` needed if side effect is large |
| `T2_KNOWLEDGE_MUTATION` | DANGEROUS | External knowledge mutations: import source, import report, replace changed source, apply research results | Approval required by default; policy can auto-approve specific patterns |
| `T3_DESTRUCTIVE` | CRITICAL | Destructive mutations: delete source, delete notebook, purge cache, reset profile, bulk deletes | Explicit confirm/approval token required; two-step in non-interactive mode |

**Rules:**
- Code uses the canonical tier names (`T0_READ`, `T1_LOCAL_MUTATION`, `T2_KNOWLEDGE_MUTATION`, `T3_DESTRUCTIVE`)
- CLI output and docs may use the aliases for readability
- `capabilities.yaml` maps every command to its tier
- The four-tier taxonomy replaces both the Revised and Supplement tier lists

---

## 2) Unified Approval Schema

### The conflict

- **Revised plan (§10.2)** defines `approval_requests` with: `approval_id`, `action`, `risk_tier`, `requested_by`, `requested_at`, `status`, `reason`, `decision_payload_json`
- **Supplement (§7.4)** defines `approval_requests` with: `id`, `entity_type`, `entity_id`, `policy_name`, `status`, `requested_at`, `resolved_at`, `decision_json`

### Resolution

Merge both schemas into one table that serves the Revised plan's risk-tier model and the Supplement's entity-centric model.

### `approval_requests` — unified schema

| Column | Type | Source | Notes |
|---|---|---|---|
| `id` | text PK | Supplement | Use `id` as column name; generate as `appr_<ulid>` |
| `trace_id` | text | New | Links to the run that triggered the approval |
| `entity_type` | text | Supplement | What is being approved: `inbox_item`, `source_delete`, `notebook_delete`, `cache_prune`, `source_import`, `doctor_repair`, etc. |
| `entity_id` | text | Supplement | FK to the entity row (inbox item id, source id, etc.) |
| `action` | text | Revised | The specific action: `import`, `delete`, `replace`, `prune`, `repair`, etc. |
| `risk_tier` | text | Revised | `T0_READ`, `T1_LOCAL_MUTATION`, `T2_KNOWLEDGE_MUTATION`, `T3_DESTRUCTIVE` |
| `policy_name` | text nullable | Supplement | Which policy triggered this: `default`, workspace policy name, profile policy name |
| `requested_by` | text | Revised | Who/what requested: `cli_user`, `agent`, `radar`, `inbox_triage`, etc. |
| `requested_at` | datetime | Both | When the approval was created |
| `resolved_at` | datetime nullable | Supplement | When the decision was made |
| `status` | text | Both | `pending`, `approved`, `rejected`, `expired`, `cancelled` |
| `reason` | text nullable | Revised | Human/agent-readable reason for the request |
| `resume_token` | text nullable | New (from Supplement §11.7) | For pause/resume agent workflows |
| `decision_json` | text nullable | Both | Merged name; structured decision payload |

**Design notes:**
- The Revised plan's `decision_payload_json` and the Supplement's `decision_json` merge into `decision_json`.
- The Revised plan's `approval_id` becomes just `id`.
- `entity_type` + `entity_id` lets the Supplement's inbox/radar/doctor features reference their specific entities.
- `risk_tier` + `action` + `requested_by` let the Revised plan's safety model classify and guard.
- `resume_token` supports the Supplement's HITL pause/resume pattern (§11.7).
- `trace_id` connects to `run_events` for full observability.

---

## 3) Unified JSON Envelope Contract

### The conflict

- **Revised plan (§14.1)** defines a comprehensive standard envelope with `ok`, `trace_id`, `run_id`, `route`, `freshness`, `result`, `cache_updates`, `diagnostics`
- **Original plan (§3.11)** defines essentially the same envelope (minus `trace_id`, `run_id`)
- **Supplement** defines four bespoke envelopes for Doctor (§8.8), Workspace (§9.11), Radar (§10.10), Inbox (§11.10) that each use flat structures and omit standard fields

### Resolution

The Revised plan's envelope (§14.1) is the **single canonical envelope**. All Supplement features must wrap their feature-specific data inside the `result` field of this envelope. Optional top-level fields may be omitted when not applicable (e.g., `freshness` for doctor commands), but the structure must not be contradicted.

### Canonical envelope — all commands

```json
{
  "ok": true,
  "trace_id": "trc_...",
  "run_id": "run_...",
  "route": {
    "intent": "DOCTOR | WORKSPACE_QUERY | RADAR_BRIEF | INBOX_TRIAGE | QUERY | GENERATION | RESEARCH | LOCAL_METADATA | REMOTE_METADATA",
    "mode": "...",
    "notebook_id": "... | null",
    "profile_id": "default",
    "source_of_truth": "local_cache | remote_http | mixed",
    "cache_mode": "smart | refresh | offline | network",
    "reason": "...",
    "transport": {
      "kind": "httpx | local",
      "endpoint": "... | null",
      "rpcid": "... | null"
    }
  },
  "freshness": {
    "notebook_index_age_s": null,
    "notebook_detail_age_s": null,
    "used_cached_result": false
  },
  "result": {},
  "cache_updates": {
    "tables_touched": [],
    "invalidated": []
  },
  "diagnostics": {
    "retries": 0,
    "auth_refreshed": false,
    "elapsed_ms": 0
  }
}
```

### Feature-specific `result` payloads

#### Doctor

```json
"result": {
  "status": "healthy | degraded | broken",
  "summary": {
    "passed": 18,
    "failed": 2,
    "repairable": 1
  },
  "findings": [
    {
      "check": "auth.bl_present",
      "severity": "critical",
      "status": "fail",
      "repairable": true,
      "message": "Session snapshot is missing build_label",
      "suggested_action": "doctor fix --check auth"
    }
  ],
  "repairs": [],
  "next_steps": []
}
```

#### Workspace

```json
"result": {
  "workspace": {
    "id": "ws_...",
    "name": "market-intel"
  },
  "plan": {
    "mode": "fanout_synthesize",
    "selected_notebooks": [
      {"id": "nb_1", "title": "Pricing", "score": 0.92}
    ],
    "reason": "..."
  },
  "answer": "...",
  "provenance": [
    {"notebook_id": "nb_1", "contribution": "pricing objections"}
  ]
}
```

#### Change Radar

```json
"result": {
  "watch": {
    "id": "watch_123",
    "kind": "web_diff"
  },
  "event": {
    "id": "evt_123",
    "severity": "material",
    "change_kind": "content_hash_changed"
  },
  "briefing": {
    "summary": "Pricing policy page changed materially",
    "affected": {
      "notebooks": ["nb_pricing"],
      "workspaces": ["ws_market_intel"],
      "query_runs": 2
    },
    "recommended_action": "create inbox replacement candidate"
  }
}
```

#### Research Inbox

```json
"result": {
  "item": {
    "id": "item_123",
    "origin": "deep_research",
    "kind": "source",
    "state": "pending",
    "approval_required": true
  },
  "scores": {
    "relevance": 0.93,
    "novelty": 0.71,
    "trust": 0.84
  },
  "explanation": {
    "why_recommended": "...",
    "overlap": "...",
    "suggested_action": "approve_import"
  }
}
```

**Rules:**
- Every `--json` output uses the canonical envelope
- `route.intent` is extended with: `DOCTOR`, `WORKSPACE_QUERY`, `WORKSPACE_COMPARE`, `RADAR_STATUS`, `RADAR_BRIEF`, `INBOX_TRIAGE`, `INBOX_APPLY`
- `route.source_of_truth` adds `"mixed"` for workspace fan-out queries
- `freshness` may be `null` for commands that don't involve cache decisions (e.g., doctor, inbox approve)
- `cache_updates` and `diagnostics` are always present even if empty

---

## 4) Unified Command Grammar

### The conflict

- **Original plan** uses `cli` as root command prefix: `cli notebook list`, `cli agent "..."`, `cli source list`
- **Revised plan (§13.1)** uses `notebooklm` as root command: `notebooklm auth login`, `notebooklm doctor`
- **Supplement** uses `notebooklm` and agrees with Revised, but conflicts on doctor subcommand grammar:
  - Revised says `notebooklm doctor --fix --dry-run` (flags)
  - Supplement says `notebooklm doctor fix` and `notebooklm doctor bundle` (subcommands)

### Resolution

#### Root command

`notebooklm` is the canonical root command. The Original plan's `cli` prefix is **superseded**.

#### Doctor grammar

Use the **Supplement's subcommand style** (`doctor fix`, `doctor bundle`) because it is more composable and follows the noun-verb pattern used everywhere else. The Revised plan's `--fix` flag style is superseded.

#### Canonical command surface — complete

```text
auth
  notebooklm auth login
  notebooklm auth check
  notebooklm auth inspect
  notebooklm auth refresh

metadata
  notebooklm notebook list
  notebooklm notebook show <id-or-title>
  notebooklm notebook use <id-or-title>
  notebooklm source list [--notebook X]
  notebooklm source guide <source-id>
  notebooklm sync notebooks [--all | --notebook X]
  notebooklm cache status
  notebooklm cache prune

work
  notebooklm ask "question"
  notebooklm overview [--notebook X]
  notebooklm summarize [--notebook X] [--wait]
  notebooklm study-guide [--notebook X] [--wait]
  notebooklm audio [--notebook X] [--wait]
  notebooklm research start "query" --mode fast|deep
  notebooklm research wait <research-id>
  notebooklm research import <research-id>

agent/routing
  notebooklm agent "natural language request"
  notebooklm route "request" --dry-run
  notebooklm route explain "request"

memory/observability
  notebooklm history search "term"
  notebooklm history show <run-id>
  notebooklm trace show <trace-id>
  notebooklm events tail

ops/doctor
  notebooklm doctor                          # fast mode
  notebooklm doctor --deep                   # deep mode
  notebooklm doctor check <category>         # run specific check category
  notebooklm doctor fix [--check <category>] [--dry-run]
  notebooklm doctor bundle
  notebooklm support-bundle create           # alias for doctor bundle

workspaces (post-MVP)
  notebooklm workspace list
  notebooklm workspace create <name>
  notebooklm workspace add <name> --notebook <id-or-title>
  notebooklm workspace remove <name> --notebook <id-or-title>
  notebooklm workspace show <name>
  notebooklm workspace ask <name> "question"
  notebooklm workspace compare <name> "question"   # may stage local gap-fill proposals in inbox
  notebooklm workspace index <name>

change radar (post-MVP)
  notebooklm watch add --source <id> --policy <schedule>
  notebooklm watch add --workspace <name> --policy <schedule>
  notebooklm watch list
  notebooklm watch pause <watch-id>
  notebooklm watch run-now <watch-id>
  notebooklm radar status
  notebooklm radar list
  notebooklm radar brief <event-id>
  notebooklm radar ignore <event-id>

research inbox (post-MVP)
  notebooklm inbox list
  notebooklm inbox view <item-id>
  notebooklm inbox why <item-id>
  notebooklm inbox approve <item-id>
  notebooklm inbox reject <item-id>
  notebooklm inbox defer <item-id> --until <date>
  notebooklm inbox import <item-id>
  notebooklm inbox apply-batch --filter <filter>
```

**Rules:**
- Root command is always `notebooklm`
- The Original plan's `cli` prefix references should be read as `notebooklm`
- Doctor uses subcommands (`fix`, `bundle`, `check`) not flags (`--fix`)
- `doctor fix` supports `--dry-run` and `--check <category>` as flags (combining both plans)
- `support-bundle create` is kept as alias for `doctor bundle` for backward compatibility with Revised plan §13.1

---

## 5) Unified Run Model

### The conflict

- **Revised plan (§10.2)** defines `run_events` as a single append-only event log with `event_id`, `trace_id`, `run_id`, `kind`, `ts`, `payload_json`
- **Revised plan (§10.1)** defines `query_runs`, `sync_runs` as typed run tables
- **Supplement (§7.2)** introduces `workspace_runs` and **Supplement (§7.3)** introduces `watch_runs` with their own structures

### Resolution

#### Principle: typed run tables + unified event log

Every subsystem gets its own **typed run table** for structured queries (what workspace was queried? what watch was executed?). All run tables share a common `trace_id` column that links them to the **unified `run_events` log**.

#### Typed run table pattern

All run tables follow this common column pattern:

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | Prefixed by subsystem: `qr_`, `sr_`, `wr_`, `wtr_`, `dr_` |
| `trace_id` | text | Links to `run_events`; every event for this run shares this trace_id |
| `profile_id` | text FK | Profile that owns this run |
| `status` | text | `pending`, `running`, `completed`, `failed`, `cancelled` |
| `started_at` | datetime | When the run began |
| `ended_at` | datetime nullable | When the run finished |
| *(subsystem-specific columns)* | | |

#### Run table inventory

| Table | Prefix | Source | Subsystem-specific columns |
|---|---|---|---|
| `query_runs` | `qr_` | Revised §10.1 | `intent`, `mode`, `prompt_hash`, `notebook_fingerprint`, `settings_hash`, `cache_policy`, `route_reason`, `source_of_truth`, `reused_from` |
| `sync_runs` | `sr_` | Revised §10.1 | `scope`, `target_id`, `trigger`, `stats_json`, `error_text` |
| `workspace_runs` | `wr_` | Supplement §7.2 | `workspace_id`, `mode`, `query_text`, `selected_notebooks_json`, `plan_json`, `result_json` |
| `watch_runs` | `wtr_` | Supplement §7.3 | `watch_id`, `signature_before`, `signature_after`, `result_json` |
| `doctor_runs` | `dr_` | Supplement §7.1 | `mode`, `overall_status`, `summary_json` |

#### `run_events` — unified event log (unchanged from Revised §10.2)

| Column | Type | Notes |
|---|---|---|
| `event_id` | text PK | `evt_<ulid>` |
| `trace_id` | text indexed | Links to any run table's `trace_id` |
| `run_id` | text nullable | Optional FK to the specific run table row |
| `kind` | text | Event type (see below) |
| `ts` | datetime | Event timestamp |
| `payload_json` | text nullable | Structured event data |

#### Canonical event kinds

From Revised plan (§10.2):
- `route.resolved`, `cache.hit`, `cache.miss`, `sync.started`, `sync.finished`, `auth.refreshed`, `artifact.polled`, `research.imported`, `approval.requested`, `approval.granted`

From Supplement (§6.3):
- `doctor.run.started`, `doctor.check.completed`, `doctor.repair.completed`
- `workspace.resolve.completed`, `workspace.query.completed`
- `watch.run.completed`, `change.detected`, `delta.briefing.created`
- `inbox.item.created`, `approval.requested`, `approval.resolved`, `inbox.item.applied`

Merged — deduplicated:
- `approval.requested` appears in both; keep once
- `approval.granted` (Revised) and `approval.resolved` (Supplement) → use `approval.resolved` as canonical (covers approved + rejected)

#### How they connect

```text
trace_id "trc_abc123"
  ├── workspace_runs row (wr_xyz, trace_id=trc_abc123)
  ├── run_events: workspace.resolve.completed
  ├── run_events: route.resolved
  ├── query_runs row (qr_111, trace_id=trc_abc123)  ← sub-run for notebook 1
  ├── run_events: cache.miss
  ├── query_runs row (qr_222, trace_id=trc_abc123)  ← sub-run for notebook 2
  ├── run_events: cache.miss
  ├── run_events: workspace.query.completed
  └── run_events: approval.requested (if needed)
```

**Rules:**
- A single top-level operation gets one `trace_id`
- Sub-operations (e.g., per-notebook queries within a workspace query) share the same `trace_id` but get separate typed run table rows
- `run_events.run_id` may point to any typed run table row for detailed linking
- All new subsystems (workspaces, radar, inbox, doctor) follow the same typed-run-table + event-log pattern established by `query_runs`/`sync_runs`

---

## 6) Leases table

The Supplement (§7.5) introduces a `leases` table that is not in the Revised plan. This is **accepted as new shared infrastructure**.

### `leases`

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | `lease_<ulid>` |
| `scope_type` | text | `profile`, `notebook`, `workspace`, `watch`, `inbox_item` |
| `scope_id` | text | FK to the scoped entity |
| `holder` | text | Who holds: agent name, CLI pid, etc. |
| `purpose` | text | Human-readable reason |
| `advisory` | bool default true | Advisory (not enforced) vs strict |
| `acquired_at` | datetime | |
| `expires_at` | datetime | Auto-expire for crash safety |

This replaces the Revised plan's mention of "advisory lock files" (§18.1) with a DB-based equivalent.

---

## 7) Updated `capabilities.yaml` manifest entries

The Supplement (§15) adds feature-specific entries. Here is the merged manifest shape:

```yaml
version: 1

commands:
  # --- MVP (from Revised §7.1) ---
  ask:
    intent: QUERY
    risk_tier: T0_READ
    output: answer
    remote: true
  overview:
    intent: QUERY
    risk_tier: T0_READ
    output: summary
    remote: true
  summarize:
    intent: GENERATION
    risk_tier: T0_READ
    output: artifact_request
    mode: briefing_doc
  study-guide:
    intent: GENERATION
    risk_tier: T0_READ
    output: artifact_request
    mode: study_guide
  audio:
    intent: GENERATION
    risk_tier: T0_READ
    output: artifact_request
    mode: audio
  research.start:
    intent: RESEARCH
    risk_tier: T0_READ
    output: research_request
  research.wait:
    intent: RESEARCH
    risk_tier: T0_READ
    output: research_status
  notebook.delete:
    intent: MUTATION
    risk_tier: T3_DESTRUCTIVE
  source.delete:
    intent: MUTATION
    risk_tier: T3_DESTRUCTIVE
  cache.prune:
    intent: LOCAL_MUTATION
    risk_tier: T1_LOCAL_MUTATION

  # --- Post-MVP: Doctor (from Supplement §15) ---
  doctor:
    intent: DOCTOR
    risk_tier: T0_READ
  doctor.fix:
    intent: DOCTOR
    risk_tier: T1_LOCAL_MUTATION
  doctor.bundle:
    intent: DOCTOR
    risk_tier: T0_READ

  # --- Post-MVP: Workspaces ---
  workspace.list:
    intent: LOCAL_METADATA
    risk_tier: T0_READ
  workspace.create:
    intent: LOCAL_MUTATION
    risk_tier: T1_LOCAL_MUTATION
  workspace.ask:
    intent: WORKSPACE_QUERY
    risk_tier: T0_READ
    remote: true
  workspace.compare:
    intent: WORKSPACE_COMPARE
    risk_tier: T1_LOCAL_MUTATION
    remote: true

  # --- Post-MVP: Radar ---
  watch.add:
    intent: LOCAL_MUTATION
    risk_tier: T1_LOCAL_MUTATION
  watch.list:
    intent: LOCAL_METADATA
    risk_tier: T0_READ
  radar.status:
    intent: LOCAL_METADATA
    risk_tier: T0_READ
  radar.brief:
    intent: LOCAL_METADATA
    risk_tier: T0_READ

  # --- Post-MVP: Inbox ---
  inbox.list:
    intent: LOCAL_METADATA
    risk_tier: T0_READ
  inbox.approve:
    intent: INBOX_APPLY
    risk_tier: T2_KNOWLEDGE_MUTATION
  inbox.reject:
    intent: INBOX_TRIAGE
    risk_tier: T0_READ
  inbox.import:
    intent: INBOX_APPLY
    risk_tier: T2_KNOWLEDGE_MUTATION

cache_entities:
  - notebooks
  - sources
  - artifacts
  - research_runs
  - query_runs
  - query_results
  - sync_runs
  - run_events
  - approval_requests
  # post-MVP
  - workspaces
  - workspace_members
  - workspace_runs
  - watches
  - watch_runs
  - change_events
  - delta_briefings
  - inbox_items
  - inbox_clusters
  - doctor_runs
  - doctor_findings
  - doctor_repairs
  - support_bundles
  - leases

doctor_checks:
  # MVP (from Revised §7.1)
  - auth_snapshot_present
  - auth_snapshot_fresh
  - build_label_present
  - db_openable
  - schema_current
  - write_permissions_ok
  - notebooklm_home_consistent
  # Post-MVP (from Supplement §15)
  - auth.bl_present
  - db.integrity
  - workspace.index_fresh
  - inbox.approval_backlog
  - radar.watch_failures
```

---

## 8) Cross-reference: what this supersedes

| Document | Section | Superseded by |
|---|---|---|
| Original (PLAN-CLI.md) | §3.2 package layout (`notebooklm_agent/`) | Revised §6 — extend `src/notebooklm/` in place |
| Original (PLAN-CLI.md) | §3.4 file layout (`~/.notebooklm-agent/`) | Revised §8 — keep `NOTEBOOKLM_HOME` |
| Original (PLAN-CLI.md) | §3.11 envelope | This doc §3 — canonical envelope |
| Original (PLAN-CLI.md) | MVP acceptance `cli` prefix | This doc §4 — `notebooklm` root command |
| Revised (§10.2) | `approval_requests` schema | This doc §2 — unified schema |
| Revised (§14.1) | Envelope (kept as base) | This doc §3 — extended with Supplement intents |
| Revised (§15.1) | Risk tiers `SAFE/CAUTION/DANGEROUS/CRITICAL` | This doc §1 — unified tier taxonomy |
| Revised (§13.1, §16.1) | Doctor grammar `--fix --dry-run` | This doc §4 — `doctor fix --dry-run` subcommand style |
| Supplement (§7.4) | `approval_requests` schema | This doc §2 — unified schema |
| Supplement (§8.8) | Doctor envelope | This doc §3 — wrapped in canonical envelope `.result` |
| Supplement (§9.11) | Workspace envelope | This doc §3 — wrapped in canonical envelope `.result` |
| Supplement (§10.10) | Radar envelope | This doc §3 — wrapped in canonical envelope `.result` |
| Supplement (§11.10) | Inbox envelope | This doc §3 — wrapped in canonical envelope `.result` |
| Supplement (§13.1) | Risk tiers `Tier 0–3` | This doc §1 — unified tier taxonomy |

---

## 9) What remains unchanged

Everything not listed in §8 above remains as specified in its source document:

- Transport split (browser for auth only, httpx for everything else)
- `NOTEBOOKLM_HOME` as root
- Package layout in `src/notebooklm/` (Revised §6, Supplement §6.1)
- Auth/session lifecycle (Revised §9)
- Core cache tables: profiles, auth_snapshots, app_state, notebooks, sources, artifacts, research_runs, query_runs, query_results, sync_runs (Revised §10.1)
- Supplement data model tables: doctor_runs, doctor_findings, doctor_repairs, support_bundles, workspaces, workspace_members, workspace_rules, workspace_runs, workspace_index_entries, watches, watch_runs, source_revisions, change_events, delta_briefings, inbox_items, inbox_clusters (Supplement §7)
- Routing model and cache modes (Revised §12)
- Sync engine and freshness policy (Revised §17)
- Phase plans (Revised §20, Supplement §16)
- All acceptance criteria (Revised §21, Supplement per-feature)
