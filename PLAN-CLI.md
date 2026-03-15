# 1. Current State

## Audit summary of `ledo9124/mcp-notebooklm`

### What the repo already gets right

`ledo9124/mcp-notebooklm` is already much closer to the desired transport model than most NotebookLM community projects. It is not fundamentally a browser-automation runtime. It is a Python package with an async `httpx` transport layer, a CLI, and an MCP server built on top of that transport.

The current codebase already has:

- A broad NotebookLM capability surface in `src/notebooklm/`: notebooks, sources, chat, research, artifacts, sharing, settings, notes, and CLI wiring.
- A central async client (`NotebookLMClient`) with a lower-level `ClientCore` that owns HTTP lifecycle, authentication headers, URL building, retries, and RPC execution.
- A reverse-engineered RPC registry for batchexecute plus a separate free-form query endpoint.
- A browser login path that saves Playwright storage state, then reuses those saved cookies for future HTTP calls.

### Transport split: auth layer vs transport layer

This split is the single most important design fact to preserve.

#### Auth layer (browser optional)

The current repo uses Playwright only for `notebooklm login`.

Responsibilities of the browser step today:

- Open NotebookLM in a real browser for one-time Google login.
- Save browser state to `storage_state.json`.
- Persist a browser profile directory for future re-use.

This is exactly the correct place to use Playwright/Patchright in the new design: authentication bootstrap only.

#### Transport layer (must remain `httpx`)

After login, the repo already pivots to direct HTTP:

- `AuthTokens.from_storage()` loads cookies from the saved Playwright storage state.
- `fetch_tokens()` makes an authenticated `httpx` GET to `https://notebooklm.google.com/` to extract CSRF (`SNlM0e`) and session ID (`FdrFJe`).
- `ClientCore` opens an `httpx.AsyncClient`, builds batchexecute URLs, encodes RPC payloads, and POSTs directly to NotebookLM endpoints.
- Known endpoints and method IDs live under `src/notebooklm/rpc/`.

That means the repo already supports the correct mental model:

> NotebookLM web is the source of reverse-engineered RPC specs.
> The CLI/runtime is an HTTP client that replays them.
> The browser is not the primary execution path.

### Known transport details already present

The current repo already exposes a usable reverse-engineered transport registry:

- `BATCHEXECUTE_URL`
- `QUERY_URL` (`GenerateFreeFormStreamed`)
- `UPLOAD_URL`
- `RPCMethod` values for notebook CRUD, source CRUD, summarize, source guide, research, artifacts, sharing, and settings

This is a strong base for the new CLI because it avoids re-discovering the entire RPC surface from scratch.

### Existing command surface

The current CLI is command-driven and already covers a lot of product area. In practice, the surface is organized around:

- auth/session commands: login, use, status, clear, auth check
- notebook commands
- source commands
- ask/chat commands
- generate/download commands
- note commands
- research commands
- share commands
- language/skill commands

This is a good transport-and-operations base, but it is not yet an agent-first cache router.

## What is missing relative to the target architecture

### 1. No durable local metadata cache

The repo currently persists:

- browser auth state (`storage_state.json`)
- browser profile
- a lightweight CLI context file with selected notebook/conversation

But it does **not** provide a durable local cache/database for:

- notebook index snapshots
- per-notebook source metadata snapshots
- query history with replay metadata
- artifact/research task history
- cache invalidation/freshness policy

There is an `_cache.py` in `src/notebooklm_mcp/`, but that is an optional in-memory TTL helper, not a durable local cache. It is also disabled by default, and the current server lifespan yields `cache=None`, so it is not the system-of-record for local metadata.

### 2. No explicit sync engine

Today, reads mostly hit the remote service on demand. The repo does not yet model sync as a first-class subsystem with:

- notebook index sync
- notebook detail sync
- source metadata reconciliation
- dependency-aware invalidation after mutations
- task polling with cache write-back

### 3. No smart router / agent layer

The current CLI is explicit-command oriented. That is useful, but the target project requires a layer that can take a request such as:

- “summarize this notebook”
- “make a study guide”
- “which notebook has pricing PDFs?”
- “research cloud marketplace trends and import sources”

and then decide:

- whether the answer can be served from the local cache
- whether an HTTP call is required
- which NotebookLM mode/RPC to invoke
- what structured response envelope to return

### 4. Build label (`bl`) is not yet first-class in the runtime core

This is the biggest transport gap between the current repo and the requested spec.

The current repo already has helper support for an optional `bl` query parameter in the RPC encoder utilities, but the main runtime URL builder in `ClientCore` does not currently send `bl`. The new CLI should treat `bl` as part of the session snapshot alongside cookies, CSRF, and session ID.

### 5. Query history exists conceptually, not as a reusable routing primitive

The current code already caches some conversation state in memory, but it does not yet persist query history in a way that supports:

- exact-result reuse
- notebook-fingerprint aware replay
- offline history browsing
- router decisions based on identical recent runs

## Bottom-line audit conclusion

Use `ledo9124/mcp-notebooklm` as the **runtime transport base**.

Do **not** replace it with browser-driven automation.

Instead:

- keep direct `httpx` replay as the only runtime path for read/write/query/generate operations
- extend auth/session hydration to persist `bl`
- add a durable SQLite cache and sync engine
- add an agent-first routing layer above the transport

# 2. Base Selection

## Comparison of CLI/UX candidates

| Candidate | Strengths | Weaknesses vs this project | Transport compatibility | Decision |
|---|---|---|---|---|
| `jacob-bd/notebooklm-mcp-cli` | Richest CLI taxonomy among candidates; dual noun-first / verb-first command model; setup/doctor/skill/alias/tag/pipeline ergonomics; already frames NotebookLM as internal APIs + browser cookie extraction; useful examples for auth profiles and structured commands | Surface is much larger than the MVP; includes many commands we should not copy wholesale in week 1–2; not built around a mandatory local metadata cache | Compatible enough for **CLI shell/UX** inspiration because it still uses internal APIs and browser auth rather than browser-as-runtime | **Choose as the UX/base-shell reference** |
| `m4yk3ldev/notebooklm-mcp` | Clean MCP-oriented capability list; good coverage of notebooks, sources, research, and studio generation; auth story is CDP-based cookie extraction with internal endpoints | More MCP-tool centric than CLI centric; does not provide the local-cache-centric, agent-router CLI shape we want; command taxonomy is thinner | Compatible as a transport-adjacent reference, but not the best CLI shell to fork | Reference only |
| `PleasePrompto/notebooklm-mcp` | Very strong “agent-first” product framing; saved notebook library, auto notebook selection, tool profiles, and natural-language examples are useful product inspiration | Architecture and README explicitly lean on Chrome/browser automation as the runtime interaction model; this conflicts with the transport rule for this project | **Not transport-compatible** as a base because browser automation is part of the core runtime model | Reject as fork base; borrow only UX ideas |

## Decision

### Fork choice

Fork the **CLI skeleton / command taxonomy / operator ergonomics** from `jacob-bd/notebooklm-mcp-cli`.

### Keep transport from `ledo9124/mcp-notebooklm`

The actual runtime stack should still come from the audited `ledo9124/mcp-notebooklm` transport core, because it already separates browser login from `httpx` replay.

### What to copy vs not copy

#### Copy from `jacob-bd`

- command grouping ideas
- auth profile ergonomics
- setup/doctor style diagnostics
- alias-oriented UX patterns
- clean “resource commands + action commands” mental model

#### Do not copy from `jacob-bd`

- its entire command sprawl for MVP
- any transport assumptions that bypass the simpler `ledo` transport core
- multi-style CLI aliases in MVP unless they come nearly for free

#### Borrow conceptually from `PleasePrompto`

- local notebook library feel
- auto-selection / smart targeting behavior
- natural-language entrypoint examples

#### Explicitly do not borrow from `PleasePrompto`

- browser automation as runtime transport
- “show the browser” / browser orchestration for regular query execution

## Forking stance for implementation

The cleanest implementation path is:

1. Treat `ledo9124/mcp-notebooklm` as the **code/runtime base**.
2. Add a new package for cache/router/CLI above it.
3. Use `jacob-bd` as the **UX contract reference**, not the transport base.

# 3. Architecture

## 3.1 System boundary and request flow

### Non-negotiable rule

**Playwright/Patchright is allowed only for `auth login` and related auth-recovery flows.**

All notebook/source/query/generation/research operations must go through direct `httpx` calls to known NotebookLM endpoints.

### High-level flow

```text
User command / NL request
    -> CLI parser
    -> Router
    -> Target resolver (local DB)
    -> Freshness gate
        -> local return (if metadata request and cache is fresh enough)
        -> or HTTP executor (if remote call is required)
    -> cache write-back
    -> structured renderer (text/table/json)
```

### Runtime components

1. **Auth/Profile Manager**
   - owns profiles, `storage_state.json`, browser profiles
   - hydrates cookies + CSRF + session ID + build label (`bl`)
   - refreshes session snapshot without reopening browser when cookies are still valid

2. **HTTP Query Agent**
   - async `httpx` client
   - batchexecute/query/upload endpoints
   - RPC registry and request encoding/decoding
   - retry/auth-refresh/rate-limit behavior

3. **Local Manager**
   - SQLite cache
   - notebook/source/artifact/query history tables
   - local context (current notebook/profile)
   - alias/selection metadata later

4. **Sync Engine**
   - read-through sync for notebook index/detail
   - mutation-triggered invalidation
   - task polling for artifacts/research
   - tombstoning of deleted remote objects

5. **Workflow Layer**
   - structured commands (`ask`, `summarize`, `audio`, `research`)
   - NL shorthand (`agent`, `route --dry-run`)
   - structured JSON envelope for downstream agents/scripts

## 3.2 Suggested package/module layout

Add a new package alongside existing `src/notebooklm` transport code:

```text
src/
  notebooklm/                 # keep as transport/reference core
  notebooklm_mcp/             # existing MCP server
  notebooklm_agent/           # new CLI cache+router layer
    auth/
      profiles.py
      session_snapshot.py
      token_hydrator.py
    cache/
      db.py
      schema.py
      repositories.py
      invalidation.py
    sync/
      notebooks.py
      sources.py
      artifacts.py
      research.py
    router/
      intents.py
      target_resolution.py
      freshness.py
      execution.py
      explain.py
    workflows/
      ask.py
      overview.py
      summarize.py
      study_guide.py
      audio.py
      research.py
    cli/
      main.py
      auth.py
      notebook.py
      source.py
      sync.py
      cache.py
      agent.py
```

## 3.3 Local data model (durable cache)

Use **SQLite** as the default local store.

Reason:

- zero extra service dependency
- portable for a CLI
- easy to inspect/debug
- good enough for metadata, history, and structured JSON payloads
- can use WAL mode later if concurrent readers appear

## 3.4 File layout on disk

```text
~/.notebooklm-agent/
  config.toml
  cache.db
  logs/
  profiles/
    default/
      storage_state.json
      browser_profile/
    work/
      storage_state.json
      browser_profile/
```

## 3.5 Schema

### A. Auth and profile tables

#### `profiles`

| Column | Type | Notes |
|---|---|---|
| `profile_id` | text PK | stable local ID, e.g. `default`, `work` |
| `display_name` | text | user-visible name |
| `account_email` | text nullable | populated after validation if discoverable |
| `is_default` | bool | one active profile |
| `storage_state_path` | text | path to Playwright storage state |
| `browser_profile_path` | text | path to browser user-data-dir |
| `created_at` | datetime | local creation time |
| `updated_at` | datetime | local update time |
| `last_login_at` | datetime nullable | last successful browser login |

#### `auth_snapshots`

| Column | Type | Notes |
|---|---|---|
| `profile_id` | text FK | references `profiles` |
| `cookie_fingerprint` | text | hash of effective auth cookies |
| `csrf_token` | text | `SNlM0e` |
| `session_id` | text | `FdrFJe` / `f.sid` |
| `build_label` | text | `bl`; mandatory in the new design |
| `captured_at` | datetime | when snapshot was created |
| `validated_at` | datetime nullable | last successful use |
| `status` | text | `fresh`, `stale`, `invalid` |
| `source` | text | `browser_login`, `refresh_from_homepage`, `imported` |

### B. Remote metadata cache tables

#### `notebooks`

| Column | Type | Notes |
|---|---|---|
| `notebook_id` | text PK | remote UUID |
| `profile_id` | text FK | owner profile |
| `title` | text | cached display title |
| `normalized_title` | text indexed | for router lookup/fuzzy matching |
| `is_owner` | bool | owner/shared |
| `share_visibility` | text nullable | restricted / public / unknown |
| `created_at_remote` | datetime nullable | remote timestamp if available |
| `source_count` | int default 0 | cached count |
| `artifact_count` | int default 0 | cached count |
| `note_count` | int default 0 | cached count |
| `summary_preview` | text nullable | optional short summary |
| `index_synced_at` | datetime nullable | last list-level sync |
| `detail_synced_at` | datetime nullable | last full notebook pull |
| `remote_fingerprint` | text nullable | hash of canonical notebook payload |
| `tombstoned_at` | datetime nullable | set when remote delete observed |
| `raw_json` | text nullable | canonical raw payload snapshot |

#### `sources`

| Column | Type | Notes |
|---|---|---|
| `source_id` | text PK | remote ID |
| `notebook_id` | text FK | parent notebook |
| `profile_id` | text FK | convenience filter |
| `source_type` | text | url / file / text / youtube / drive |
| `title` | text nullable | cached title |
| `origin_uri` | text nullable | URL/file/drive identifier |
| `status` | text | preparing / processing / ready / error |
| `freshness_state` | text nullable | fresh / stale / unknown |
| `drive_syncable` | bool nullable | only for drive sources |
| `content_preview` | text nullable | small preview only in MVP |
| `added_at_remote` | datetime nullable | remote timestamp if available |
| `updated_at_remote` | datetime nullable | remote timestamp if available |
| `synced_at` | datetime nullable | last detail sync |
| `remote_fingerprint` | text nullable | hash of canonical source payload |
| `tombstoned_at` | datetime nullable | for deletes |
| `raw_json` | text nullable | canonical raw payload snapshot |

#### `artifacts`

| Column | Type | Notes |
|---|---|---|
| `artifact_id` | text PK | remote task/artifact id |
| `notebook_id` | text FK | parent notebook |
| `profile_id` | text FK | convenience filter |
| `artifact_type` | text | audio, report, slide_deck, infographic, quiz, etc. |
| `submode` | text nullable | e.g. `briefing_doc`, `study_guide`, `deep_dive` |
| `title` | text nullable | cached remote title |
| `prompt_hash` | text nullable | hash of generation prompt |
| `status` | text | pending / in_progress / completed / failed |
| `requested_at` | datetime | local request start |
| `last_polled_at` | datetime nullable | status polling |
| `completed_at` | datetime nullable | terminal completion |
| `download_ref` | text nullable | URL or export token; refresh on access if expired |
| `remote_fingerprint` | text nullable | canonical payload hash |
| `raw_json` | text nullable | artifact metadata snapshot |

#### `research_runs`

| Column | Type | Notes |
|---|---|---|
| `research_id` | text PK | remote task id |
| `notebook_id` | text FK | parent notebook |
| `profile_id` | text FK | convenience filter |
| `mode` | text | `fast` / `deep` / later `drive` |
| `query_text` | text | research prompt |
| `status` | text | running / completed / failed / imported |
| `discovered_count` | int default 0 | discovered sources count |
| `imported_count` | int default 0 | imported sources count |
| `started_at` | datetime | local start time |
| `updated_at` | datetime | last status poll |
| `raw_json` | text nullable | canonical research payload |

### C. Execution and sync history tables

#### `query_runs`

| Column | Type | Notes |
|---|---|---|
| `query_run_id` | text PK | local UUID |
| `profile_id` | text FK | active profile |
| `notebook_id` | text nullable | resolved target notebook |
| `intent` | text | ask / overview / summarize / study_guide / audio / research / metadata_lookup |
| `mode` | text | internal router mode |
| `prompt_text` | text | raw user request |
| `prompt_hash` | text indexed | normalized prompt hash |
| `settings_hash` | text nullable | chat/generation config hash |
| `notebook_fingerprint` | text nullable | notebook fingerprint at run time |
| `cache_policy` | text | smart / refresh / offline / network |
| `route_reason` | text | why this mode was chosen |
| `source_of_truth` | text | local_cache / remote_http |
| `started_at` | datetime | execution start |
| `completed_at` | datetime nullable | completion |
| `status` | text | success / failed / reused |
| `reused_from_query_run_id` | text nullable | if exact reuse occurred |

#### `query_results`

| Column | Type | Notes |
|---|---|---|
| `query_run_id` | text PK/FK | one-to-one with `query_runs` |
| `result_type` | text | answer / artifact_request / sync_report |
| `answer_text` | text nullable | textual answer for `ask` / overview |
| `citations_json` | text nullable | structured citations if available |
| `artifact_id` | text nullable | if a generation command created one |
| `result_json` | text nullable | full structured result envelope |
| `created_at` | datetime | local write time |

#### `sync_runs`

| Column | Type | Notes |
|---|---|---|
| `sync_run_id` | text PK | local UUID |
| `profile_id` | text FK | active profile |
| `scope` | text | notebook_index / notebook_detail / source_detail / artifact_poll / research_poll |
| `target_id` | text nullable | notebook/source/task id |
| `trigger` | text | manual / read_through / mutation / startup |
| `started_at` | datetime | sync start |
| `finished_at` | datetime nullable | sync end |
| `status` | text | success / partial / failed |
| `stats_json` | text nullable | inserted/updated/deleted counts |
| `error_text` | text nullable | failure summary |

## 3.6 Indexes that matter in MVP

Add indexes for:

- `notebooks(profile_id, normalized_title)`
- `sources(notebook_id, status)`
- `sources(profile_id, source_type)`
- `artifacts(notebook_id, status)`
- `query_runs(prompt_hash, notebook_fingerprint, mode)`
- `sync_runs(profile_id, scope, started_at)`

## 3.7 Cache freshness and invalidation policy

### Policy table

| Object | Freshness window | Invalidate when | Refresh method | Notes |
|---|---|---|---|---|
| Auth snapshot | soft: 20 min; hard: on 401/403 or explicit auth failure | cookies rotate, auth failure, build mismatch | GET NotebookLM homepage with stored cookies; reopen browser only if cookies invalid | `bl` refresh belongs here |
| Notebook index | 5 min | notebook create/delete/rename/share, explicit sync | `LIST_NOTEBOOKS` | global list is cheap and should be the default sync unit |
| Notebook detail | 2 min | any source mutation, artifact mutation, notes mutation, research import, share update | `GET_NOTEBOOK` | notebook detail is the dependency root for source/artifact counts |
| Source metadata | ready: 10 min; processing/preparing: 15 sec | add/delete/refresh/sync drive, notebook detail refresh | notebook detail pull or `GET_SOURCE` | processing sources need tighter polling |
| Source freshness | 5 min | explicit freshness check or drive sync | `CHECK_SOURCE_FRESHNESS` / `REFRESH_SOURCE` | only meaningful for syncable sources |
| Query result | advisory only; reusable up to 24 h only when prompt hash + notebook fingerprint + settings hash match | notebook fingerprint changes, prompt/settings differ, explicit no-cache | `QUERY_URL` / streamed query | history is not the source of truth for new factual answers |
| Artifact status | pending/in_progress: 10 sec; terminal: 24 h | create/delete/revise/download failure | `LIST_ARTIFACTS` or direct status poll | keep polling cheap and bounded |
| Research run | running: 10 sec; terminal: 1 h | import completed or explicit refresh | `POLL_RESEARCH` | importing sources should invalidate notebook detail |
| User settings | 1 h | setting change, profile switch | get/set user settings RPC | keep local defaults in sync with server |

### Invalidation rules by mutation

#### Notebook mutations

- create notebook -> invalidate notebook index
- rename notebook -> update local row + invalidate notebook index/detail
- delete notebook -> tombstone notebook + cascade tombstone to sources/artifacts/research runs
- share change -> invalidate notebook detail and share fields

#### Source mutations

- add source -> invalidate notebook detail immediately
- delete source -> tombstone source + invalidate notebook detail
- refresh/sync source -> mark source stale until remote confirms new status
- research import -> invalidate notebook detail and source list

#### Artifact mutations

- create artifact -> insert artifact row as `pending`, invalidate notebook detail
- revise slide deck -> insert new artifact row, keep lineage in `submode`/metadata
- delete artifact -> tombstone artifact, invalidate notebook detail

#### Query mutations

- no destructive invalidation on normal `ask`
- update `query_runs` and `query_results`
- optionally reuse only when notebook fingerprint matches exactly

## 3.8 Notebook fingerprint strategy

A query result should never be reused just because the prompt matches. It should also match the **state of the notebook**.

Define `notebook_fingerprint` in MVP as a SHA-256 over canonical JSON built from:

- notebook title
- notebook-level summary metadata
- ordered source IDs + source statuses + source fingerprints
- ordered artifact IDs + statuses
- any server-visible settings that change answer behavior

Use that fingerprint to decide whether a cached query result is reusable.

## 3.9 RPC mode map

### Canonical command-to-mode mapping

| CLI command | Router intent | Transport | Endpoint / RPC | Wait model | Cache behavior |
|---|---|---|---|---|---|
| `cli notebook list` | metadata list | local-first | `LIST_NOTEBOOKS` if refresh needed | no wait | serve local when fresh; sync on demand |
| `cli notebook show <id>` | notebook detail | local-first | `GET_NOTEBOOK` when stale/missing | no wait | upsert notebook + sources/artifacts summary |
| `cli source list [--notebook X]` | source metadata list | local-first | notebook detail pull if stale | no wait | driven by notebook detail cache |
| `cli source guide <source>` | source-specific synthesis | remote required | `GET_SOURCE_GUIDE` | no wait | store guide payload for later reuse |
| `cli ask "..."` | Q&A | remote required | free-form query endpoint (`QUERY_URL`) | streamed or buffered | persist query history only |
| `cli overview` | fast notebook summary | remote preferred | `SUMMARIZE` | no wait | cache textual summary with notebook fingerprint |
| `cli summarize` | report artifact: briefing doc | remote required | `CREATE_ARTIFACT` with report=`briefing_doc` | optional poll | insert artifact row and poll if `--wait` |
| `cli briefing` | alias of `summarize` | remote required | same as above | optional poll | same as above |
| `cli study-guide` | report artifact: study guide | remote required | `CREATE_ARTIFACT` with report=`study_guide` | optional poll | same pattern as briefing |
| `cli audio` | audio overview | remote required | `CREATE_ARTIFACT` with type=`audio` | optional poll | cache task + final download ref |
| `cli slides` | slide deck generation | remote required | `CREATE_ARTIFACT` with type=`slide_deck` | optional poll | cache task state |
| `cli infographic` | infographic generation | remote required | `CREATE_ARTIFACT` with type=`infographic` | optional poll | cache task state |
| `cli quiz` / `cli flashcards` | study artifact generation | remote required | `CREATE_ARTIFACT` with quiz/flashcard params | optional poll | cache task state |
| `cli research start --mode fast` | fast research | remote required | `START_FAST_RESEARCH` | poll later | insert research row |
| `cli research start --mode deep` | deep research | remote required | `START_DEEP_RESEARCH` | poll later | insert research row |
| `cli research wait/status` | research poll | remote required | `POLL_RESEARCH` | bounded poll loop | update research row |
| `cli research import` | import discovered sources | remote required | `IMPORT_RESEARCH` | no wait or short wait | invalidate notebook detail + source rows |
| `cli sync notebooks` | explicit sync | remote required | `LIST_NOTEBOOKS` then selected `GET_NOTEBOOK` calls | bounded fan-out | writes index/detail cache |
| `cli cache status` | local diagnostics | local only | no remote | no wait | read cache stats only |

### Important semantic decision

To match the target examples:

- `cli ask` = conversational Q&A mode
- `cli summarize` = **briefing document generation**, not just a short answer
- `cli overview` = the quick summary mode for users who want a lightweight remote summary instead of a report artifact

This avoids ambiguity and gives the router a stable contract.

## 3.10 Agent-first UX

## Canonical CLI surface (MVP)

### Metadata / cache commands

```text
cli auth login
cli auth check
cli notebook list
cli notebook show <id-or-title>
cli notebook use <id-or-title>
cli source list [--notebook X]
cli sync notebooks [--all | --notebook X]
cli cache status
cli cache prune
```

### Work commands

```text
cli ask "question"
cli overview [--notebook X]
cli summarize [--notebook X] [--wait]
cli study-guide [--notebook X] [--wait]
cli audio [--notebook X] [--wait]
cli research start "query" --mode fast|deep
cli research wait <research-id>
cli research import <research-id>
```

### Agent/NL commands

```text
cli agent "summarize the current notebook into a briefing doc"
cli agent "which notebooks have stale drive sources?"
cli agent "make an audio overview for the pricing notebook"
cli route "make me a study guide for the onboarding notebook" --dry-run
```

## Routing rules

### Rule 1: explicit structured commands always win

If the user typed `cli audio ...`, the router does not re-classify intent. It only resolves target notebook, freshness policy, and execution options.

### Rule 2: NL routing classifies into one of five buckets

1. `LOCAL_METADATA`
   - list/show/find/filter notebooks/sources using cached metadata

2. `REMOTE_METADATA`
   - freshness checks, syncs, notebook/source detail refreshes

3. `QUERY`
   - grounded Q&A, comparison, explanation, evidence lookup

4. `GENERATION`
   - briefing doc, study guide, audio, slides, infographic, quiz, etc.

5. `RESEARCH`
   - discovery, polling, importing sources

### Rule 3: notebook resolution order

Resolve notebook target in this order:

1. explicit `--notebook`
2. explicit notebook ID in the NL request
3. exact title match in local cache
4. current notebook context (`cli notebook use`)
5. fuzzy title match against local cache
6. fail with ranked candidates if still ambiguous

### Rule 4: freshness gate decides offline vs remote

Support a global cache mode flag:

- `--cache-mode smart` (default)
- `--cache-mode refresh`
- `--cache-mode offline`
- `--cache-mode network`

Behavior:

#### `smart`

- metadata requests use local cache when fresh
- stale metadata triggers remote sync
- query/generation/research always use remote transport
- query history may be reused only on exact fingerprint match and only when command permits reuse

#### `refresh`

- force remote sync before serving metadata
- still write local cache after response

#### `offline`

- local metadata only
- no remote Q&A/generation/research
- useful for scripts/diagnostics/travel/offline work

#### `network`

- always hit remote for supported commands
- update local cache after response

## Examples of routing behavior

| Request | Router result |
|---|---|
| `cli agent "list notebooks"` | `LOCAL_METADATA` -> local DB unless notebook index is stale in `smart` mode |
| `cli agent "which notebooks have PDF sources?"` | local SQL over cached source metadata |
| `cli agent "what do the pricing sources say about renewals?"` | resolve notebook from cache -> `QUERY` -> remote ask |
| `cli agent "summarize current notebook"` | `GENERATION` -> briefing doc artifact |
| `cli agent "quick overview of current notebook"` | `QUERY` or `overview` path -> remote lightweight summary |
| `cli agent "sync stale drive sources"` | `REMOTE_METADATA` -> freshness check + sync |

## 3.11 Structured output envelope

Every non-trivial command should support `--json` and return a consistent envelope.

### Proposed envelope

```text
{
  ok: boolean,
  route: {
    intent: string,
    mode: string,
    notebook_id: string | null,
    source_of_truth: "local_cache" | "remote_http",
    cache_mode: "smart" | "refresh" | "offline" | "network",
    reason: string,
    transport: {
      kind: "httpx",
      endpoint: string,
      rpcid: string | null
    }
  },
  freshness: {
    notebook_index_age_s: number | null,
    notebook_detail_age_s: number | null,
    used_cached_result: boolean
  },
  result: {...},
  cache_updates: {
    tables_touched: string[],
    invalidated: string[]
  },
  diagnostics: {
    retries: number,
    auth_refreshed: boolean,
    elapsed_ms: number
  }
}
```

Default human output can be concise, but the JSON envelope is what makes the CLI agent-first and scriptable.

## 3.12 Auth/session lifecycle in the new design

### Required session snapshot

A session snapshot must contain:

- cookies
- CSRF token
- session ID (`f.sid`)
- build label (`bl`)
- capture time
- cookie fingerprint

### Refresh policy

1. On startup, read the latest auth snapshot for the selected profile.
2. If snapshot is too old, refresh it with a single authenticated homepage GET.
3. On 401/403 or build mismatch, refresh snapshot once and retry.
4. Only reopen a browser if cookie-based refresh fails.

### Non-goals

The new system must **not**:

- intercept browser traffic during normal operations
- run queries inside a Playwright browser page
- use a browser context as the transport channel for notebook reads or generation

# 4. Feature Roadmap

## MVP goal

Ship a usable CLI in **1–2 weeks** that proves the architecture:

- durable local cache
- notebook/source sync
- `ask`
- `summarize` (briefing doc)
- `audio`
- `research start/wait/import`
- `agent` + `route --dry-run`
- strict `httpx` runtime

## Module roadmap

## A. Local Manager

### MVP

- Add SQLite database and migration bootstrap.
- Implement `profiles`, `auth_snapshots`, `notebooks`, `sources`, `artifacts`, `research_runs`, `query_runs`, `query_results`, `sync_runs`.
- Implement current notebook/profile context storage in the DB or a small config file.
- Add `cache status` and `cache prune` commands.
- Add title normalization and lookup indexes for routing.

### Post-MVP

- notebook aliases and tags
- saved notebook collections
- optional raw payload blob store
- export/import cache snapshots
- multi-machine sync or shared cache

## B. Query Agent (`httpx` transport)

### MVP

- Reuse/adapt `ledo` transport core.
- Extend auth/session snapshot to include `bl`.
- Centralize endpoint + RPC registry in one module.
- Add retry policy for auth refresh and 429 handling.
- Implement structured result envelope for all remote commands.
- Keep all reads/writes/generation on `httpx` only.

### Post-MVP

- streaming response renderer for `ask`
- more studio modes: video, infographic, data table, flashcards, slides revise
- transport drift detection + auto diagnostics
- request tracing / structured audit logs

## C. Sync Engine

### MVP

- `sync notebooks` for index refresh.
- `sync notebook <id>` implicit inside `notebook show`, `source list`, and router resolution when needed.
- Source metadata reconciliation from notebook detail pulls.
- Artifact status polling and research status polling.
- Mutation-driven invalidation helpers.
- Tombstone handling for deleted notebooks/sources/artifacts.

### Post-MVP

- background daemon / scheduled sync
- selective sync by tag/profile/recency
- source fulltext sync on demand
- remote diff summaries between sync runs
- partial notebook sync heuristics based on change likelihood

## D. Workflow Layer

### MVP

- canonical commands:
  - `ask`
  - `overview`
  - `summarize`
  - `study-guide`
  - `audio`
  - `research start|wait|import`
  - `agent`
  - `route --dry-run`
- notebook resolution rules
- cache-mode rules (`smart`, `refresh`, `offline`, `network`)
- human and JSON renderers

### Post-MVP

- extra artifact commands (slides, infographic, quiz, flashcards, data table, video)
- multi-step macro commands (`research-and-brief`, `ingest-and-audio`)
- cross-notebook query mode
- notebook aliases/tags for smarter selection
- policy packs for different agent hosts

## Delivery sequencing

### Phase 1 — Transport hardening (day 1–2)

- add `build_label` to session snapshot
- patch URL building to send `bl`
- add auth-refresh logic and tests

### Phase 2 — Durable cache (day 2–4)

- create SQLite schema
- implement repository layer
- implement notebook index/detail sync

### Phase 3 — Basic commands (day 4–6)

- `notebook list/show/use`
- `source list`
- `sync notebooks`
- `cache status`

### Phase 4 — Agent work modes (day 6–9)

- `ask`
- `overview`
- `summarize`
- `audio`
- structured JSON envelope

### Phase 5 — Research + router (day 9–12)

- `research start/wait/import`
- `agent`
- `route --dry-run`
- ambiguity/freshness handling

## MVP acceptance criteria

A release is MVP-complete when all of the following are true:

1. A user can log in once, then close the browser and perform all normal operations via `httpx`.
2. `cli notebook list` and `cli source list` can return from the local cache without re-hitting NotebookLM when cache is fresh.
3. `cli ask`, `cli summarize`, and `cli audio` work against the HTTP transport and write query/task history locally.
4. `cli agent` can classify at least metadata lookup vs ask vs summarize vs audio vs research.
5. Cache invalidation after source/artifact/research mutations is correct enough to avoid obviously stale notebook views.
6. `--json` returns the structured route/result envelope.

# 5. Open Questions

1. **Exact `bl` extraction source:**
   - Is `bl` always derivable from the NotebookLM homepage HTML, or does the project need a one-time DevTools capture to seed it for all RPC families?
   - Implementation should assume `bl` is mandatory in the session snapshot, but exact extraction may need one more reverse-engineering pass.

2. **Which RPCs truly require `bl` today?**
   - The new design should send it consistently.
   - Still worth confirming whether every batchexecute path rejects missing `bl`, or only a subset.

3. **Quick summary vs briefing doc semantics:**
   - This plan defines `summarize` as briefing doc generation and `overview` as quick summary.
   - Confirm this naming before coding to avoid a breaking CLI rename later.

4. **Source-scoped Q&A support:**
   - Does the current query endpoint support explicit source subsets cleanly, or should MVP keep queries notebook-scoped and use source titles/guides for source-specific workflows?

5. **How much source content to cache locally in MVP?**
   - Current recommendation: metadata + preview only.
   - Full source text sync should likely remain on-demand until size/privacy constraints are clearer.

6. **Download/export URL expiry policy:**
   - Should artifact download refs be treated as ephemeral and refreshed on access, or persisted as long-lived values when present?

7. **Multiple profiles in one working directory:**
   - Confirm whether a single DB should contain many profiles or whether each profile gets an isolated DB file.
   - My recommendation is one DB with `profile_id` columns in MVP for simplicity.

8. **Research mode taxonomy:**
   - The audited repo clearly supports fast/deep research.
   - Confirm whether Drive-focused research should be a first-class MVP flag or deferred until post-MVP.

9. **How much of `jacob-bd` UX to adopt immediately?**
   - My recommendation: borrow naming and diagnostics, but keep only one canonical command style in MVP.
   - Verb-first aliases can wait until after the router and cache model are stable.

10. **Local metadata privacy defaults:**
    - Decide whether the cache DB should store raw query answers and source previews by default, or require an explicit `history.store_content=true` setting for more sensitive environments.

