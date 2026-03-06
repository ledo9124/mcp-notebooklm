
 # notebooklm-mcp: MCP Server + Tooling Plan for notebooklm-py
 **Date:** 2026-03-05  
-**Revision:** v3 (hybrid)  
+**Revision:** v4 (workflows + ops)  
 **Status:** Ready for implementation  
 
 This document upgrades the original “tool menu” into an **implementation-ready, enterprise-grade plan**:
@@ -53,6 +53,10 @@ This document upgrades the original “tool menu” into an **implementation-ready, enterprise-grade plan**:
 - **Operational safety** (gated destructive tools, rate limiting, timeouts, and strong tests).
 
+**New in v4:**
+- **Workflow macros** (one-call multi-step workflows with progress + robust summaries).
+- **Ops superpowers** (diagnose, debug stats, redacted audit trail, and optional 2-phase commit for destructive actions).
+
 ---
 
 ## 2) Success criteria (what “extreme success” means in practice)
@@ -67,6 +71,12 @@ This document upgrades the original “tool menu” into an **implementation-ready, enterprise-grade plan**:
   5) ask questions and receive citations.
 
+### 2.4 Power-user success (v4)
+- Users/agents can run common multi-step workflows with **one tool call**:
+  - bootstrap a notebook (import bundle → wait_ready → optional index note)
+  - research flow (ensure ready → ask → optional “save as note”)
+- Operators can debug issues quickly using `notebooklm_diagnose` and `notebooklm_debug_stats` without leaking secrets.
+
 ### 2.2 Engineering success
 - Tool schemas are explicit, stable, and documented.
 - Tool results are parseable (structured JSON + fallback string).
@@ -120,13 +130,31 @@ Production guidance:
 - Prefer a **stateless HTTP** configuration (`stateless_http=True`) and **JSON responses** (`json_response=True`) for scalability.
 
 ### 3.3 Lifespan + dependency injection
 Use a typed `AppContext` dataclass yielded from a lifespan context manager, and access it in tools via:
 `ctx.request_context.lifespan_context`
 
 This avoids global state spaghetti and makes tools testable (mockable context).
 
+### 3.3.1 Long-running tool calls (workflows) + progress
+Workflow macros can legitimately take tens of seconds (imports + processing waits).
+- Use bounded polling (timeout + interval).
+- Report progress (`ctx.report_progress`) when available.
+- Always return a final structured summary of what happened (added/skipped/failed, ready status).
+
 ### 3.4 ⚠️ STDIO logging rule (hard constraint)
 If you support STDIO transport:
 - **stdout is reserved for MCP JSON-RPC**.
 - Any `print()` or accidental stdout logging can corrupt the transport.
@@ -155,15 +183,33 @@ Enforcement:
 - Never log custom instructions verbatim; only log length, hashes, or redacted previews.
 
 ### 3.6 Destructive actions are gated
 Tools that delete or irreversibly modify data (remove source, delete notebook) must:
 - require an explicit `confirm: true` parameter **and**
 - be disabled by default unless `NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1`.
 
 This is “human in the loop” enforcement at the server boundary, not just a UI hope.
+
+### 3.6.1 Optional: Two-phase commit (2PC) for destructive actions (recommended for production)
+To further reduce accidental deletion, enable an optional 2-step flow:
+1) `*_prepare` returns a short-lived `confirmation_token` + a deletion summary
+2) `*_commit(confirm=true, confirmation_token=...)` performs the deletion
+
+Controls:
+- `NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1` (required)
+- `NOTEBOOKLM_MCP_DESTRUCTIVE_2PC=1` (enables prepare/commit tools; direct delete/remove tools may be hidden)
+- Tokens must be **stateless** where possible (signed payload with TTL) to support stateless HTTP deployments.
+
+### 3.8 Diagnostics + audit logging are opt-in and redacted
+Diagnostics and audit features must never leak:
+- credentials/cookies/tokens
+- full custom prompts or source content
+
+Expose only redacted metadata by default; allow operators to configure retention/caps.
 
 ### 3.7 Rate limiting, timeouts, retries
 To survive real agent behavior:
 - Add a concurrency semaphore (e.g., max N in-flight calls) to avoid API thrash.
@@ -214,6 +260,19 @@ When returning structured output:
 This ensures backward compatibility for clients that only parse text.
 
 ---
 
 ## 5) Tool surface: MVP vs optional
@@ -254,12 +313,29 @@ Production guidance:
 - `notebooklm_chat_find_quotes`
 - `notebooklm_chat_summarize_sources`
 - `notebooklm_chat_get_conversation`
+
+**Workflow macros (optional, recommended):**
+- `notebooklm_workflow_bootstrap_notebook`
+- `notebooklm_workflow_research`
+
+**Ops / diagnostics (optional, recommended for support/production):**
+- `notebooklm_diagnose`
+- `notebooklm_debug_stats`
+
+**Destructive tools (gated) — prefer 2PC variants when enabled:**
+- `notebooklm_sources_remove_prepare` / `notebooklm_sources_remove_commit`
+- `notebooklm_notebooks_delete_prepare` / `notebooklm_notebooks_delete_commit`
 
 ---
 
 ## 6) Detailed tool specifications (schema-first)
@@ -498,6 +574,16 @@ This avoids LLM-side polling loops.
 - `user: { email?: string, display_name?: string, tenant?: string }`
 
 ---
 
+## 6.6 Workflow tools (optional macros)
+Workflow tools are convenience wrappers around composable tools. They:
+- do not introduce new capabilities beyond the primitives,
+- but provide more reliable multi-step execution, progress reporting, and a single structured summary.
+
+These tools are optional but dramatically improve UX in real agent hosts.
+
+---
+
+### 6.6.1 `notebooklm_workflow_bootstrap_notebook`
+**Purpose:** One-call “getting started” workflow:
+create or reuse a notebook → import bundle → wait_ready → (optional) generate an index note source → (optional) apply chat settings.
+
+**Input**
+- `notebook_id?: string` *(if provided, reuse existing)*
+- `title?: string` *(required if notebook_id not provided; used to create a new notebook)*
+- `sources?: {`
+  - `urls?: string[]`
+  - `files?: Array<{ filename: string, mime_type: string, data_base64: string, title?: string }>`
+  - `texts?: Array<{ title: string, content: string }>`
+  - `dedup?: boolean` *(default `true`)*
+  - `concurrency?: integer` *(default `3`, min `1`, max `8`)*
+  `}`
+- `wait_ready: boolean` *(default `true`)*
+- `timeout_ms?: integer` *(default `120000`, max `300000`)*
+- `poll_interval_ms?: integer` *(default `1500`, min `250`, max `10000`)*
+- `generate_index_note: boolean` *(default `true`)*
+- `index_note_title?: string` *(default `"Notebook Index (auto)"`)*
+- `apply_settings?: {`
+  - `mode: "patch" | "set"` *(default `"patch"`)*
+  - `goal?: Goal`
+  - `response_length?: ResponseLength`
+  - `custom_prompt?: string | null`
+  - `strict?: boolean` *(default `true`; applies to patch semantics)*
+  `}`
+- `dry_run: boolean` *(default `false`)*
+
+**Output**
+- `notebook: { notebook_id: string, title: string, created: boolean }`
+- `import: { added: any[], skipped: any[], failed: any[] }`
+- `ready: boolean`
+- `statuses?: Array<{ source_id: string, status: SourceStatus }>`
+- `index_note?: { created: boolean, source_id?: string }`
+- `settings?: { applied: boolean, after?: { goal, response_length, custom_prompt_set, custom_prompt_len, fingerprint } }`
+- `warnings?: string[]`
+
+**Behavior notes**
+- If `dry_run=true`, return what would happen without applying changes.
+- “Index note” generation should be implemented by asking NotebookLM to summarize the notebook into a structured outline and saving it via `sources_add_text`. This is intentionally a note, not a canonical “index system”.
+- Never include raw credentials or full prompts in output.
+
+---
+
+### 6.6.2 `notebooklm_workflow_research`
+**Purpose:** One-call research workflow:
+ensure sources are ready → ask → optionally save the answer as a note source for future retrieval.
+
+**Input**
+- `notebook_id: string` (required)
+- `question: string` (required)
+- `ensure_ready: boolean` *(default `true`)*
+- `timeout_ms?: integer` *(default `60000`, max `300000`)*
+- `poll_interval_ms?: integer` *(default `1500`, min `250`, max `10000`)*
+- `citations: boolean` *(default `true`)*
+- `format: "markdown" | "text"` *(default `"markdown"`)*
+- `conversation_id?: string`
+- `save_as_note: boolean` *(default `false`)*
+- `note_title?: string` *(default `"Research Note (auto)"`)*
+- `note_include_question: boolean` *(default `true`)*
+- `dry_run: boolean` *(default `false`)*
+
+**Output**
+- `ready: boolean`
+- `answer?: string`
+- `citations?: Array<{ source_id: string, title?: string, quote?: string, location?: string, url?: string }>`
+- `used_settings?: { goal: Goal, response_length: ResponseLength }`
+- `conversation_id?: string`
+- `note?: { created: boolean, source_id?: string }`
+- `warnings?: string[]`
+
+**Behavior notes**
+- If `ensure_ready=true` and sources are not ready within timeout, return `ready=false` with statuses and skip asking unless `force_ask=true` is added later.
+- If `save_as_note=true`, write a text source containing the question, answer, and citations list (redacted/short quotes only).
+
+---
+
+## 6.7 Ops / diagnostics tools (optional, recommended)
+These tools are designed for operators and debugging, and should be disabled or restricted by default in shared environments.
+
+### 6.7.1 `notebooklm_diagnose`
+**Purpose:** One-call diagnosis that bundles common checks and returns actionable remediation steps.
+
+**Input**
+- `mode: "quick" | "full"` *(default `"quick"`)*
+- `notebook_id?: string` *(optional; include notebook/settings parsing check)*
+
+**Output**
+- `ok: boolean`
+- `checks: Array<{ name: string, ok: boolean, message?: string, details?: object }>`
+- `recommendations: string[]`
+
+**Checks (suggested)**
+- `health` (auth/session usable)
+- `whoami` (account identity visible)
+- `list_notebooks` (basic API call works)
+- `settings_parse` (if notebook_id provided)
+- `rate_limit_signal` (detect 429/backoff events if stats enabled)
+
+---
+
+### 6.7.2 `notebooklm_debug_stats`
+**Purpose:** Return redacted operational stats to help diagnose reliability issues.
+
+**Input**
+- `include_recent_errors: boolean` *(default `true`)*
+- `include_cache_stats: boolean` *(default `true`)*
+
+**Output**
+- `uptime_ms?: integer`
+- `inflight_requests?: integer`
+- `backoff_events_1h?: integer`
+- `requests_1h?: integer`
+- `errors_1h?: Array<{ code: string, count: integer }>`
+- `recent_errors?: Array<{ ts: string, code: string, tool?: string, message?: string }>`
+- `cache?: { enabled: boolean, hits_1h?: integer, misses_1h?: integer, hit_rate_1h?: number }`
+- `limits?: { max_inflight?: integer, timeout_ms_default?: integer }`
+
+**Safety**
+- No raw prompts, no source content, no credentials. Messages should be sanitized/truncated.
+
+---
+
+### 6.7.3 Destructive actions with optional 2-phase commit (2PC)
+When `NOTEBOOKLM_MCP_DESTRUCTIVE_2PC=1`, expose the prepare/commit variants below.
+
+#### 6.7.3.1 `notebooklm_sources_remove_prepare`
+**Purpose:** Preview a source removal and produce a short-lived confirmation token.
+
+**Input**
+- `notebook_id: string` (required)
+- `source_id: string` (required)
+
+**Output**
+- `confirmation_token: string`
+- `expires_at: string`
+- `summary: { notebook_id: string, source_id: string, source_title?: string }`
+
+#### 6.7.3.2 `notebooklm_sources_remove_commit`
+**Purpose:** Commit source removal using a valid token.
+
+**Input**
+- `confirm: boolean` (required; must be `true`)
+- `confirmation_token: string` (required)
+
+**Output**
+- `success: boolean`
+
+#### 6.7.3.3 `notebooklm_notebooks_delete_prepare`
+**Purpose:** Preview notebook deletion and produce a short-lived confirmation token.
+
+**Input**
+- `notebook_id: string` (required)
+
+**Output**
+- `confirmation_token: string`
+- `expires_at: string`
+- `summary: { notebook_id: string, title?: string, source_count?: integer }`
+
+#### 6.7.3.4 `notebooklm_notebooks_delete_commit`
+**Purpose:** Commit notebook deletion using a valid token.
+
+**Input**
+- `confirm: boolean` (required; must be `true`)
+- `confirmation_token: string` (required)
+
+**Output**
+- `success: boolean`
+
+**Token implementation (recommended)**
+- Use a signed, self-contained token (HMAC) containing `{action, notebook_id, source_id?, exp, nonce}`.
+- This keeps 2PC compatible with stateless HTTP and avoids server-side token storage.
+
+---
+
 ## 7) Resources (MCP resources, size-capped)
 
 Expose resources for lightweight “GET-like” access that agents can read into context when helpful.
@@ -519,6 +605,16 @@ Expose resources for lightweight “GET-like” access that agents can read into context when helpful.
 - `notebooklm://notebooks`
 - `notebooklm://notebooks/{notebook_id}`
 - `notebooklm://notebooks/{notebook_id}/sources/{source_id}`
+
+### 7.3 Ops resources (optional)
+- `notebooklm://audit/recent`
+  - Redacted audit entries of recent tool calls (bounded size; no secrets/prompt/source content).
+  - Useful for debugging in-host without having to inspect server logs.
+
+If audit is disabled, return a short message indicating it is not enabled.
 
 ### 7.2 Size caps (mandatory)
 Because sources can be huge, enforce:
 - `SOURCE_CONTENT_MAX_CHARS = 50_000` (default; configurable)
@@ -556,6 +652,16 @@ Recommended structure:
 ├── _mapping.py      # string↔enum mapping layer (NotebookLM enum int codes)
 ├── _fingerprint.py  # fingerprint computation utilities (opaque hash)
 ├── _errors.py       # exception→MCP error mapping
+├── _stats.py        # redacted operational counters (requests/errors/backoff/cache)
+├── _cache.py        # optional TTL cache for metadata + hit/miss tracking
+├── _audit.py        # redacted audit log ring buffer (+ optional file sink)
+├── _tokens.py       # signed confirmation tokens for 2PC destructive actions
 ├── server.py        # lifespan + entrypoint; imports tools LAST
 ├── tools/
 │   ├── __init__.py
 │   ├── chat_settings.py
 │   ├── notebooks.py
 │   ├── sources.py
 │   └── chat.py
+│   ├── workflows.py # workflow macros (bootstrap, research)
+│   └── ops.py       # diagnose, debug_stats (+ 2PC tools)
 ├── resources.py
 └── prompts.py
 ~~~
 
@@ -594,6 +700,34 @@ Use a consistent approach:
 - Upstream API failures → tool execution error with sanitized message (no secrets).
 
 ### 9.6 Logging strategy
 - No stdout logs in any code path.
 - Configure Python logging to stderr in entrypoint.
 - For per-request logs, prefer `await ctx.info(...)`, `await ctx.warning(...)`.
+
+### 9.8 Audit trail strategy (redacted)
+Maintain a bounded in-memory ring buffer of recent tool calls:
+- fields: timestamp, tool name, duration, status(ok/error), error code, redacted args summary
+- never store raw source content, full prompts, or credentials
+
+Optional:
+- write redacted audit entries to a file path (`NOTEBOOKLM_MCP_AUDIT_LOG_PATH`) for production troubleshooting.
+
+### 9.9 Stats + optional caching
+Stats are cheap counters:
+- request count, error count by code, backoff events, inflight
+
+Optional caching (off by default):
+- TTL cache for stable metadata (e.g., notebooks list, sources list, settings summary)
+- Track hit/miss for `notebooklm_debug_stats`
+
 ---
 
 ## 10) Testing strategy (targets real failure modes)
@@ -622,6 +756,22 @@ This avoids LLM-side polling loops.
 - Tool list contains expected names.
 - Resources list resolves.
 - Structured outputs include both `structuredContent` and JSON text.
 
+### 10.3.1 Workflow macro tests (no network where possible)
+- `bootstrap_notebook` dry_run returns planned steps
+- import bundle result summarization is stable (added/skipped/failed)
+- timeouts and partial readiness behave predictably
+
+### 10.3.2 Ops/diagnostics tests
+- `diagnose` returns expected checks when client is mocked to fail auth
+- `debug_stats` redaction test (no prompt text leaked)
+- audit resource size cap + redaction test
+
+### 10.3.3 2PC destructive token tests
+- token verification rejects wrong action/notebook/source
+- token expiry works
+- commit requires `confirm=true`
+
 ### 10.4 Integration tests (record/replay if possible)
 - `create → add_source → wait_ready → ask → get_settings → patch → reset`
 
@@ -660,6 +810,14 @@ This avoids LLM-side polling loops.
 ### PR7 — Docs + examples
 - tool reference (schemas)
 - Claude Desktop config example
 - OpenAI Agents SDK example
+
+### PR8 — Workflow macros (v4)
+- workflow_bootstrap_notebook
+- workflow_research
+- progress reporting + stable structured summaries
+
+### PR9 — Ops superpowers + 2PC (v4)
+- diagnose + debug_stats
+- redacted audit ring buffer + audit resource
+- signed confirmation tokens + prepare/commit destructive tools
 
 ---
 
 ## 12) Risk register + mitigations
@@ -673,6 +831,10 @@ This avoids LLM-side polling loops.
 | Destructive tool misuse | High | feature flag + confirm param |
 | Rate limiting / throttling | Medium | concurrency limits + retries/backoff |
 | Prompt leakage in logs | High | never log prompt, only length/preview |
+| Audit trail leaks sensitive content | High | redaction by default + bounded size + tests |
+| Workflow macros hide side-effects | Medium | dry_run + clear summaries + explicit tool names |
+| 2PC tokens misused/replayed | Medium | short TTL + HMAC signature + include action + nonce |
 
 ---
 
 ## 13) Definition of Done
@@ -692,6 +854,14 @@ This avoids LLM-side polling loops.
 - Docs clearly explain single-tenant constraints
 - Basic observability (stderr logs, request IDs)
+
+### v4 DoD (workflows + ops)
+- Workflow macros implemented with progress + deterministic summaries
+- Diagnose and debug stats implemented and redacted by default
+- Audit resource available when enabled (bounded + redacted)
+- Optional 2PC destructive flows available and tested (signed tokens + TTL)
