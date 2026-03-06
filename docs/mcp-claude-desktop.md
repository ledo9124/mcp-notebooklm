# Claude Desktop MCP Setup (NotebookLM)

**Status:** Active  
**Last Updated:** 2026-03-05

This guide shows how to connect Claude Desktop to the `notebooklm_mcp` server using STDIO transport.

## Prerequisites

1. Install runtime dependencies:

```bash
pip install "notebooklm-py[mcp,browser]"
playwright install chromium
```

2. Authenticate once:

```bash
notebooklm login
```

3. Confirm NotebookLM access works before MCP setup:

```bash
notebooklm list
```

## Configuration File

Claude Desktop config path is typically:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Use the example config in [docs/examples/claude-desktop-config.json](examples/claude-desktop-config.json).

Minimal server block:

```json
{
  "mcpServers": {
    "notebooklm": {
      "command": "python",
      "args": ["-m", "notebooklm_mcp"],
      "env": {
        "NOTEBOOKLM_HOME": "/absolute/path/to/.notebooklm",
        "NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS": "0",
        "NOTEBOOKLM_MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## Recommended Environment Variables

- `NOTEBOOKLM_HOME`: points at NotebookLM auth/storage directory.
- `NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS`:
  - `0` (recommended default): disable destructive calls
  - `1`: allow destructive tools (still requires `confirm=true` in each call)
- `NOTEBOOKLM_MCP_LOG_LEVEL`: `INFO` for normal, `DEBUG` for troubleshooting.
- `NOTEBOOKLM_MCP_MAX_INFLIGHT`: concurrency guard for tool calls.
- `NOTEBOOKLM_MCP_TIMEOUT_MS`: default timeout for MCP operations.

## Verification

After updating config:

1. Fully restart Claude Desktop.
2. Open MCP tools list and verify NotebookLM tools are present.
3. Run a safe read-only call first, for example `notebooklm_notebooks_list`.
4. If successful, run a non-destructive write call, for example `notebooklm_notebooks_create`.

## Troubleshooting

### 1) Authentication expired

Symptoms:
- tool calls fail with auth/session errors
- diagnostics indicate `auth_expired`

Fix:
```bash
notebooklm login
notebooklm list
```
Restart Claude Desktop after re-auth.

### 2) STDIO corruption / JSON-RPC parse failures

Symptoms:
- MCP connection starts then immediately fails
- host logs show invalid JSON-RPC frames

Cause:
- stdout noise from non-MCP output.

Fix:
- ensure only MCP protocol frames are written to stdout
- keep logging on stderr (default server behavior)
- remove custom startup wrappers that print to stdout

### 3) MCP runtime missing

Symptoms:
- startup error like: install optional dependency `notebooklm-py[mcp]`

Fix:
```bash
pip install "notebooklm-py[mcp]"
```
Then restart Claude Desktop.

## Related Docs

- [MCP Tool Reference](mcp-tools.md)
- [Troubleshooting](troubleshooting.md)
- [Configuration](configuration.md)
