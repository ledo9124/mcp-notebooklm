# MCP Tool Reference

**Status:** Active  
**Last Updated:** 2026-03-05  
**Server Module:** `src/notebooklm_mcp`

This document describes the NotebookLM MCP tool surface, including input/output schemas, defaults, constraints, examples, and important edge/error behavior.

## Output Contract (All Tools)

All tools return the shared structured-output envelope from `make_tool_result(...)`:

```json
{
  "structuredContent": {"...": "tool-specific payload"},
  "content": [
    {
      "type": "text",
      "text": "{\"...\":\"json-serialized structuredContent\"}"
    }
  ]
}
```

Notes:
- `structuredContent` is the primary machine-readable payload.
- `content[0].text` is a JSON fallback string for clients that only parse text.

## Error Contract (All Tools)

Tool handlers use `@handle_mcp_errors` and map runtime exceptions to structured MCP errors.

Typical error codes:
- `invalid_params`: input validation failures
- `auth_expired`: authentication/session failures
- `not_found`: notebook/source not found
- `rate_limited`: API rate-limited
- `timeout`: timeout and polling deadline failures
- `network_error`: transient network failures
- `server_error` or `internal_error`: upstream/internal failures

## Destructive Tool Gating

Destructive operations require **both**:
1. `NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1` at server runtime
2. `confirm=true` in the tool call

Affected tools:
- `notebooklm_notebooks_delete`
- `notebooklm_sources_remove`
- `notebooklm_settings_reset`

If either condition is missing, the call returns an `invalid_params` error with guidance.

## Registered Tool Categories

Current `register_tools(...)` wiring includes:
- notebooks
- sources
- chat
- chat settings
- workflows

Operational tools are implemented in `tools/ops.py` and documented below as availability notes.

---

## Notebooks

### `notebooklm_notebooks_list`
Description: list notebooks visible to the authenticated account.

Input schema:
- no parameters

Output schema:
```json
{
  "notebooks": [
    {
      "notebook_id": "string",
      "title": "string",
      "source_count": 0,
      "created_at": "ISO-8601?"
    }
  ]
}
```

Example:
```json
{"name":"notebooklm_notebooks_list","arguments":{}}
```

Edge cases:
- Empty account returns `{"notebooks": []}`.

### `notebooklm_notebooks_create`
Description: create a notebook.

Input schema:
- `title: string` (required, non-empty)

Output schema:
```json
{"notebook_id":"string","title":"string"}
```

Example:
```json
{"name":"notebooklm_notebooks_create","arguments":{"title":"AI Research"}}
```

Edge cases:
- Blank `title` returns `invalid_params`.

### `notebooklm_notebooks_rename`
Description: rename an existing notebook.

Input schema:
- `notebook_id: string` (required, non-empty)
- `title: string` (required, non-empty)

Output schema:
```json
{
  "success": true,
  "notebook": {
    "notebook_id": "string",
    "title": "string",
    "source_count": 0,
    "created_at": "ISO-8601?"
  }
}
```

Example:
```json
{"name":"notebooklm_notebooks_rename","arguments":{"notebook_id":"nb-123","title":"Q2 Planning"}}
```

Edge cases:
- Unknown `notebook_id` maps to `not_found`.

### `notebooklm_notebooks_delete`
Description: delete a notebook (destructive).

Input schema:
- `notebook_id: string` (required, non-empty)
- `confirm: boolean` (required, must be `true`)

Output schema:
```json
{"success":true}
```

Example:
```json
{"name":"notebooklm_notebooks_delete","arguments":{"notebook_id":"nb-123","confirm":true}}
```

Edge cases:
- Disabled destructive flag returns `invalid_params` with env-var guidance.
- `confirm=false` returns `invalid_params`.

### `notebooklm_notebooks_get_summary`
Description: return notebook summary and suggested discussion prompts.

Input schema:
- `notebook_id: string` (required, non-empty)

Output schema:
```json
{
  "summary": {
    "description": "string",
    "source_count": 0,
    "suggested_topics": [{"question":"string","prompt":"string"}]
  }
}
```

Example:
```json
{"name":"notebooklm_notebooks_get_summary","arguments":{"notebook_id":"nb-123"}}
```

Edge cases:
- If no sources exist, `source_count` is `0`.

---

## Sources

### `notebooklm_sources_list`
Description: list source metadata for a notebook.

Input schema:
- `notebook_id: string` (required)

Output schema:
```json
{
  "sources": [
    {
      "source_id": "string",
      "title": "string",
      "kind": "string",
      "status": "ready|processing|error|...",
      "created_at": "ISO-8601?"
    }
  ]
}
```

Example:
```json
{"name":"notebooklm_sources_list","arguments":{"notebook_id":"nb-123"}}
```

### `notebooklm_sources_add_url`
Description: add URL source with optional readiness wait.

Input schema:
- `notebook_id: string` (required)
- `url: string` (required)
- `wait: boolean` (optional, default `true`)
- `timeout_ms: integer` (optional, default `60000`, > 0)
- `poll_interval_ms: integer` (optional, default `1500`, > 0)

Output schema:
```json
{
  "source_id":"string",
  "status":"string",
  "ready":true,
  "statuses":[{"source_id":"string","status":"string", "title":"string", "kind":"string"}] 
}
```

Example:
```json
{"name":"notebooklm_sources_add_url","arguments":{"notebook_id":"nb-123","url":"https://example.com","wait":true}}
```

Edge cases:
- Timeout returns `ready=false` plus latest `statuses`.

### `notebooklm_sources_add_text`
Description: add inline text source.

Input schema:
- `notebook_id: string` (required)
- `title: string` (required)
- `content: string` (required)

Output schema:
```json
{"source_id":"string","status":"string"}
```

Example:
```json
{"name":"notebooklm_sources_add_text","arguments":{"notebook_id":"nb-123","title":"Notes","content":"Key points..."}}
```

### `notebooklm_sources_add_file`
Description: add file source from base64 payload.

Input schema:
- `notebook_id: string` (required)
- `filename: string` (required)
- `mime_type: string` (required)
- `data_base64: string` (required; valid base64)
- `title: string|null` (optional)

Output schema:
```json
{"source_id":"string","status":"string"}
```

Example:
```json
{"name":"notebooklm_sources_add_file","arguments":{"notebook_id":"nb-123","filename":"paper.pdf","mime_type":"application/pdf","data_base64":"JVBERi0xLjQ..."}}
```

Edge cases:
- Invalid base64 returns `invalid_params`.

### `notebooklm_sources_remove`
Description: remove source (destructive).

Input schema:
- `notebook_id: string` (required)
- `source_id: string` (required)
- `confirm: boolean` (required, must be `true`)

Output schema:
```json
{"success":true}
```

Example:
```json
{"name":"notebooklm_sources_remove","arguments":{"notebook_id":"nb-123","source_id":"src-9","confirm":true}}
```

Edge cases:
- Disabled destructive flag returns `invalid_params`.
- `confirm=false` returns `invalid_params`.

### `notebooklm_sources_wait_ready`
Description: poll until all sources are ready/error/timeout.

Input schema:
- `notebook_id: string` (required)
- `timeout_ms: integer` (optional, default `60000`, > 0)
- `poll_interval_ms: integer` (optional, default `1500`, > 0)

Output schema:
```json
{"ready":true,"statuses":[{"source_id":"string","status":"string","title":"string","kind":"string"}]}
```

Example:
```json
{"name":"notebooklm_sources_wait_ready","arguments":{"notebook_id":"nb-123","timeout_ms":120000}}
```

### `notebooklm_sources_get_content`
Description: return source fulltext with max-char cap.

Input schema:
- `notebook_id: string` (required)
- `source_id: string` (required)
- `max_chars: integer` (optional, > 0; hard-capped by config)

Output schema:
```json
{
  "source_id":"string",
  "content":"string",
  "truncated":true,
  "returned_chars":123,
  "total_chars":456,
  "max_chars":123
}
```

Example:
```json
{"name":"notebooklm_sources_get_content","arguments":{"notebook_id":"nb-123","source_id":"src-9","max_chars":5000}}
```

Edge cases:
- If requested `max_chars` exceeds server cap, effective cap is server cap.

---

## Chat

### `notebooklm_chat_ask`
Description: ask a question and return answer plus normalized citations.

Input schema:
- `notebook_id: string` (required)
- `question: string` (required)
- `source_ids: string[]|null` (optional)
- `conversation_id: string|null` (optional)
- `save_as_note: boolean` (optional, default `false`)
- `note_title: string|null` (optional)

Output schema:
```json
{
  "answer":"string",
  "citations":[{"source_id":"string","title":"string?","quote":"string?","location":"string?","url":"string?"}],
  "conversation_id":"string?",
  "note_saved":true,
  "note_id":"string?"
}
```

Example:
```json
{"name":"notebooklm_chat_ask","arguments":{"notebook_id":"nb-123","question":"What changed this week?","save_as_note":true}}
```

Edge cases:
- No answer text with `save_as_note=true` sets `note_saved=false`.

### `notebooklm_chat_find_quotes`
Description: retrieve deduplicated quote snippets for a query.

Input schema:
- `notebook_id: string` (required)
- `query: string` (required)
- `source_ids: string[]|null` (optional)

Output schema:
```json
{"quotes":[{"source_id":"string","text":"string","title":"string?","location":"string?","url":"string?"}]}
```

Example:
```json
{"name":"notebooklm_chat_find_quotes","arguments":{"notebook_id":"nb-123","query":"ROI evidence"}}
```

### `notebooklm_chat_summarize_sources`
Description: summarize selected/all sources with citations.

Input schema:
- `notebook_id: string` (required)
- `source_ids: string[]|null` (optional)

Output schema:
```json
{"summary":"string","citations":[{"source_id":"string"}],"conversation_id":"string?"}
```

Example:
```json
{"name":"notebooklm_chat_summarize_sources","arguments":{"notebook_id":"nb-123"}}
```

### `notebooklm_chat_get_conversation`
Description: fetch ordered conversation turns.

Input schema:
- `notebook_id: string` (required)
- `conversation_id: string|null` (optional; server resolves latest when omitted)
- `limit: integer|null` (optional, default `20`, > 0)

Output schema:
```json
{
  "turns":[{"role":"user|assistant","content":"string"}],
  "conversation_id":"string?"
}
```

Example:
```json
{"name":"notebooklm_chat_get_conversation","arguments":{"notebook_id":"nb-123","limit":10}}
```

Edge cases:
- If no conversation is available, returns `{"turns": []}`.

---

## Chat Settings

### `notebooklm_settings_get`
Description: read chat settings without exposing raw `custom_prompt` content.

Input schema:
- `notebook_id: string` (required)

Output schema:
```json
{
  "goal":"string",
  "response_length":"string",
  "custom_prompt_set":true,
  "custom_prompt_len":33,
  "fingerprint":"string"
}
```

Example:
```json
{"name":"notebooklm_settings_get","arguments":{"notebook_id":"nb-123"}}
```

### `notebooklm_settings_patch`
Description: patch or set chat settings.

Input schema:
- `notebook_id: string` (required)
- `mode: "patch"|"set"` (optional, default `"patch"`)
- `goal: string|null` (optional)
- `response_length: string|null` (optional)
- `custom_prompt: string|null` (optional)
- `strict: boolean` (optional, default `true`; patch mode)

Output schema:
```json
{"success":true,"after":{"goal":"string","response_length":"string","custom_prompt_set":true,"custom_prompt_len":10,"fingerprint":"string"}}
```

Example:
```json
{"name":"notebooklm_settings_patch","arguments":{"notebook_id":"nb-123","mode":"patch","response_length":"longer"}}
```

Edge cases:
- Invalid `mode` returns `invalid_params`.
- Raw prompt text is never returned.

### `notebooklm_settings_reset`
Description: reset settings to defaults (destructive).

Input schema:
- `notebook_id: string` (required)
- `confirm: boolean` (required, must be `true`)

Output schema:
```json
{"success":true,"after":{"goal":"string","response_length":"string","custom_prompt_set":false,"fingerprint":"string"}}
```

Example:
```json
{"name":"notebooklm_settings_reset","arguments":{"notebook_id":"nb-123","confirm":true}}
```

Edge cases:
- Disabled destructive flag returns `invalid_params`.
- `confirm=false` returns `invalid_params`.

---

## Workflows

### `notebooklm_workflow_bootstrap_notebook`
Description: one-call bootstrap macro for notebook setup.

Input schema:
- `notebook_id: string|null` (optional; reuse existing)
- `title: string|null` (required when `notebook_id` omitted)
- `sources: object` (optional)
  - `urls: string[]` (default `[]`)
  - `files: object[]` (default `[]`; `{filename,mime_type,data_base64,title?}`)
  - `texts: object[]` (default `[]`; `{title,content}`)
  - `dedup: boolean` (default `true`)
  - `concurrency: integer` (default `3`, min `1`, max `8`)
- `wait_ready: boolean` (default `true`)
- `timeout_ms: integer` (default `120000`, min `1`, max `300000`)
- `poll_interval_ms: integer` (default `1500`, min `250`, max `10000`)
- `generate_index_note: boolean` (default `true`)
- `index_note_title: string` (default `"Notebook Index (auto)"`)
- `apply_settings: object|null` (optional)
  - `mode: "patch"|"set"`
  - `goal?: string`
  - `response_length?: string`
  - `custom_prompt?: string|null`
  - `strict?: boolean`
- `dry_run: boolean` (default `false`)

Output schema:
```json
{
  "notebook":{"notebook_id":"string","title":"string","created":true},
  "import":{"added":[],"skipped":[],"failed":[]},
  "ready":true,
  "statuses":[{"source_id":"string","status":"string"}],
  "index_note":{"created":true,"source_id":"string?"},
  "settings":{"applied":true,"after":{"goal":"string","response_length":"string","custom_prompt_set":true,"custom_prompt_len":10,"fingerprint":"string"}},
  "warnings":["string"]
}
```

Example:
```json
{"name":"notebooklm_workflow_bootstrap_notebook","arguments":{"title":"Market Intel","sources":{"urls":["https://example.com/report"],"texts":[{"title":"Kickoff","content":"Scope and goals"}]},"wait_ready":true}}
```

Edge cases:
- `dry_run=true` returns plan/warnings without mutations.
- Partial source import failures are reported under `import.failed` and do not abort the entire workflow.

---

## Ops (Implemented, Optional Registration)

These tools exist in `tools/ops.py` and may be registered by server wiring in ops-enabled deployments.

### `notebooklm_diagnose`
Description: run health/auth/rate-limit diagnostic checks.

Input schema:
- `mode: "quick"|"full"` (default `"quick"`)
- `notebook_id: string|null` (optional; used by full mode checks)

Output schema:
```json
{"ok":true,"checks":[{"name":"string","ok":true,"details":{}}],"recommendations":["string"],"summary":{"notebooks_count":0}}
```

Example:
```json
{"name":"notebooklm_diagnose","arguments":{"mode":"full","notebook_id":"nb-123"}}
```

### `notebooklm_debug_stats`
Description: return redacted runtime counters and limits.

Input schema:
- `include_recent_errors: boolean` (default `true`)
- `include_cache_stats: boolean` (default `true`)

Output schema:
```json
{
  "uptime_ms":0,
  "inflight_requests":0,
  "backoff_events_1h":0,
  "requests_1h":0,
  "errors_1h":0,
  "limits":{"max_inflight":0},
  "recent_errors":[],
  "cache":{"enabled":false}
}
```

Example:
```json
{"name":"notebooklm_debug_stats","arguments":{"include_recent_errors":true,"include_cache_stats":true}}
```

---

## Compatibility Notes

- All examples assume the MCP client passes `ctx.request_context.lifespan_context` with a valid NotebookLM `AppContext`.
- Structured output is stable and intended for machine parsing from `structuredContent`.
- Use `content[0].text` JSON fallback only when host/tooling cannot consume `structuredContent` directly.
