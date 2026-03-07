# PLAN-HTTP-TRANSPORT: Add Streamable HTTP Transport to notebooklm-mcp

**Date:** 2026-03-06  
**Status:** Proposed  
**Scope:** Close the HTTP transport gap so agents can connect to `notebooklm-mcp` over HTTP  
**Estimated effort:** M (1–3h for code + unit tests)

---

## 1) Problem Statement

`notebooklm-mcp` currently only works via `stdio` transport. Running `python -m notebooklm_mcp` starts STDIO, and port 8764 has no HTTP listener. Agents that need to connect over HTTP (streamable-http or SSE) cannot reach the server.

**Goal:** make this work reliably:

```bash
python -m notebooklm_mcp --transport streamable-http --port 8764
```

with agents connecting to:

```
http://127.0.0.1:8764/mcp
```

---

## 2) Root Cause Analysis

### 2.1 FastMCP network settings are constructor params, not `run()` params

For `mcp==1.26.0`, the API shape is:

```python
# Constructor accepts host, port, streamable_http_path, json_response, stateless_http
FastMCP.__init__(..., host='127.0.0.1', port=8000, streamable_http_path='/mcp',
                 json_response=False, stateless_http=False, ...)

# run() only accepts transport and mount_path
FastMCP.run(transport='stdio', mount_path=None)
```

Current `_run_server()` in `__main__.py` tries to pass `host`/`port` to `run()` — **they are silently ignored** because `run()` doesn't accept them.

### 2.2 `_build_fastmcp_kwargs()` is partially correct but incomplete

It already correctly passes as constructor args:
- ✅ `stateless_http=True`
- ✅ `json_response=True`

But it does **not** forward:
- ❌ `host`
- ❌ `port`

### 2.3 CLI is missing `streamable-http` transport choice

`__main__.py` only offers `stdio` and `sse`. The recommended modern transport `streamable-http` is absent.

### 2.4 Server creation happens before CLI args are known

The package creates a module-level server at import time:

```python
# __init__.py
server = create_server(CONFIG)
```

HTTP constructor settings are fixed before `main()` parses `--host`, `--port`, or `--transport`.

---

## 3) Solution Design

### Chosen approach: Recreate server after CLI parsing (Option B)

Keep the existing package-level `server` export for backward compatibility, but have the CLI path create a **fresh server instance** after argument parsing with the correct `host`/`port` constructor args.

**Why this approach:**
- Smallest change surface
- No breaking change to `notebooklm_mcp.server` export
- Fixes both `sse` and `streamable-http`
- Aligns with FastMCP's constructor requirements
- Follows the pattern used by Qdrant MCP server and official SDK examples

**Deferred for later:**
- Full lazy-init refactor of `__init__.py`
- Auth/TLS layer
- Custom `streamable_http_path` flag
- Reverse proxy integration

### Runtime precedence for HTTP bind settings

1. CLI `--host` / `--port` (highest priority)
2. `NOTEBOOKLM_MCP_HOST` / `NOTEBOOKLM_MCP_PORT` env vars
3. Defaults: `127.0.0.1` / `8764`

### Endpoint path

Use FastMCP's default `streamable_http_path='/mcp'`. No custom path flag in this first pass.

---

## 4) Implementation Steps

### Step 1: Extend `_config.py` with HTTP bind settings

Add to `MCPConfig`:
- `host: str = "127.0.0.1"`
- `port: int = 8764`

Add env var constants:
- `NOTEBOOKLM_MCP_HOST`
- `NOTEBOOKLM_MCP_PORT`

Validation: host must be non-empty, `1 <= port <= 65535`.

### Step 2: Update `server.py` — pass host/port to FastMCP constructor

Change `_build_fastmcp_kwargs()` to accept `config: MCPConfig` and forward `host`/`port`:

```python
def _build_fastmcp_kwargs(config: MCPConfig) -> dict[str, Any]:
    kwargs = {
        "name": "notebooklm-mcp",
        "lifespan": app_lifespan,
    }
    params = inspect.signature(FastMCP).parameters
    if "version" in params:
        kwargs["version"] = _package_version()
    if "stateless_http" in params:
        kwargs["stateless_http"] = True
    if "json_response" in params:
        kwargs["json_response"] = True
    if "host" in params:
        kwargs["host"] = config.host
    if "port" in params:
        kwargs["port"] = config.port
    return kwargs
```

Update `create_server()` to pass config through to `_build_fastmcp_kwargs(config)`.

### Step 3: Update `__main__.py` — add `streamable-http`, fix startup

1. Add `streamable-http` to `--transport` choices
2. Set `--host`/`--port` defaults to `None` (resolve after config load)
3. In `main()`: load config → apply CLI overrides via `dataclasses.replace()` → create fresh server → run with transport only
4. Simplify `_run_server()` to only pass `transport` to `run()`

```python
def _run_server(server_instance: Any, transport: str) -> None:
    run = getattr(server_instance, "run", None)
    if not callable(run):
        raise AttributeError("Server has no callable run() method.")
    run(transport=transport)
```

### Step 4: Update docs and examples

- README: document `streamable-http` transport
- Add connection URL example (`http://127.0.0.1:8764/mcp`)
- Document new env vars

### Step 5: Add tests

- Config parsing for `host`/`port`
- FastMCP constructor kwargs verification
- CLI transport choices
- Startup smoke tests for all transports

---

## 5) File Changes Summary

| File | Changes |
|------|---------|
| `_config.py` | Add `host`/`port` fields, env vars, parsing, validation |
| `server.py` | `_build_fastmcp_kwargs(config)` forwards `host`/`port` to constructor |
| `__main__.py` | Add `streamable-http`, fix host/port resolution, recreate server after CLI parse |
| `__init__.py` | No breaking changes; optional comment clarifying CLI creates its own server |
| Tests | Config, server construction, CLI, smoke tests |
| README.md | Document HTTP transport, port 8764, connection URL |

---

## 6) Configuration Reference

### New environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTEBOOKLM_MCP_HOST` | `127.0.0.1` | Bind address for HTTP transports |
| `NOTEBOOKLM_MCP_PORT` | `8764` | Bind port for HTTP transports |

### CLI flags

```
--transport {stdio,sse,streamable-http}   Transport mode (default: stdio)
--host HOST                                Host for HTTP transports (default: env or 127.0.0.1)
--port PORT                                Port for HTTP transports (default: env or 8764)
```

---

## 7) Testing Plan

### Unit tests

| Area | Test |
|------|------|
| Config | `load_config()` defaults to `127.0.0.1:8764` |
| Config | Respects `NOTEBOOKLM_MCP_HOST` / `NOTEBOOKLM_MCP_PORT` env vars |
| Config | Rejects invalid port values |
| Server | `_build_fastmcp_kwargs()` includes `host`/`port` |
| Server | Preserves `stateless_http=True` and `json_response=True` |
| CLI | Parser accepts `streamable-http` |
| CLI | `stdio` remains default |
| CLI | `_run_server()` only passes `transport` to `run()` |

### Smoke tests

| Transport | Command | Verify |
|-----------|---------|--------|
| streamable-http | `python -m notebooklm_mcp --transport streamable-http --port 8764` | Port 8764 listening, `/mcp` responds |
| sse | `python -m notebooklm_mcp --transport sse --port 8765` | Port 8765 listening |
| stdio | `python -m notebooklm_mcp` | No HTTP listener, STDIO works |

### Manual acceptance checklist

- [ ] `--help` shows `streamable-http`
- [ ] HTTP defaults documented as `127.0.0.1:8764`
- [ ] `--host` and `--port` work for both `sse` and `streamable-http`
- [ ] `/mcp` endpoint works for streamable HTTP
- [ ] Tools/resources/prompts behave identically over HTTP
- [ ] `stdio` still works without transport flags

---

## 8) Security Considerations

1. **Default bind is loopback-only** (`127.0.0.1`) — do NOT default to `0.0.0.0`
2. **MCP SDK auto-enables DNS rebinding protection** for localhost — this change must not bypass it
3. **Destructive tool gating unchanged** — HTTP transport does not alter safety checks
4. **Audit logging continues to work** for HTTP-delivered requests
5. **Non-localhost binding is explicit risk acceptance** — document that `0.0.0.0` increases exposure

---

## 9) Rollback Strategy

Rollback is low-risk because changes are isolated to startup/bootstrap code:

1. Remove `streamable-http` from CLI choices
2. Revert host/port constructor forwarding in `server.py`
3. Revert env var additions in `_config.py`
4. Restore previous CLI startup behavior

**Blast radius:** CLI parsing, server construction, transport startup only. No changes to tool implementations, resources, prompts, lifespan, or client logic.

---

## 10) Follow-up (Deferred)

| Item | Priority | Reason to defer |
|------|----------|-----------------|
| Lazy server init in `__init__.py` | Low | Current approach works, cleaner but broader refactor |
| `--streamable-http-path` flag | Low | Default `/mcp` is sufficient |
| Auth/TLS for HTTP transport | Medium | Needed only for non-localhost deployment |
| Custom `TransportSecuritySettings` | Low | Auto-enabled for localhost by SDK |
| Reverse proxy / ASGI mount guide | Low | Separate ops documentation |
