# CLI Reference

**Status:** Active
**Last Updated:** 2026-03-14

Complete command reference for the retained `notebooklm` CLI surface.

## Command Structure

```
notebooklm [--storage PATH] [--version] <command> [OPTIONS] [ARGS]
```

**Global Options:**
- `--storage PATH` - Override the default storage location (`~/.notebooklm/storage_state.json`)
- `--version` - Show version and exit
- `--help` - Show help message

**Environment Variables:**
- `NOTEBOOKLM_HOME` - Base directory for all config files (default: `~/.notebooklm`)
- `NOTEBOOKLM_AUTH_JSON` - Inline authentication JSON (for CI/CD, no file writes needed)
- `NOTEBOOKLM_DEBUG_RPC` - Enable RPC debug logging (`1` to enable)

See [Configuration](configuration.md) for details on environment variables and CI/CD setup.

**Command Organization:**
- **Session commands** - Authentication and context management
- **Notebook commands** - CRUD operations on notebooks
- **Chat commands** - Querying with follow-up continuity
- **Grouped commands** - `source`, `generate`, `research`

---

## Quick Reference

### Session Commands

| Command | Description | Example |
|---------|-------------|---------|
| `login` | Authenticate via browser | `notebooklm login` |
| `use <id>` | Set active notebook | `notebooklm use abc123` |
| `status` | Show current context | `notebooklm status` |
| `status --paths` | Show configuration paths | `notebooklm status --paths` |
| `status --json` | Output status as JSON | `notebooklm status --json` |
| `clear` | Clear current context | `notebooklm clear` |
| `auth check` | Diagnose authentication issues | `notebooklm auth check` |
| `auth check --test` | Validate with network test | `notebooklm auth check --test` |
| `auth check --json` | Output as JSON | `notebooklm auth check --json` |

### Notebook Commands

| Command | Description | Example |
|---------|-------------|---------|
| `list` | List all notebooks | `notebooklm list` |
| `create <title>` | Create notebook | `notebooklm create "Research"` |
| `summary` | Get AI summary | `notebooklm summary` |

### Chat Commands

| Command | Description | Example |
|---------|-------------|---------|
| `ask <question>` | Ask a question | `notebooklm ask "What is this about?"` |
| `ask -s <id>` | Ask using specific sources | `notebooklm ask "Summarize" -s src1 -s src2` |
| `ask --json` | Get answer with source references | `notebooklm ask "Explain X" --json` |

### Source Commands (`notebooklm source <cmd>`)

Supported direct source types: URLs, YouTube videos, local files (PDF, text, Markdown, Word, audio, video, images), and pasted text.
For Drive-backed discovery, use `source add-research --from drive` and complete the import via `research wait --import-all`.

| Command | Arguments | Options | Example |
|---------|-----------|---------|---------|
| `list` | - | `--json` | `source list --json` |
| `add <content>` | URL/file/text | `--type [url\|text\|file\|youtube]`, `--title`, `--mime-type`, `--json` | `source add "https://..."` |
| `add-research <query>` | Search query | `--mode [fast|deep]`, `--from [web|drive]`, `--import-all`, `--no-wait` | `source add-research "AI" --mode deep --no-wait` |
| `wait <id>` | Source ID | `--timeout`, `--json` | `source wait src123 --timeout 300` |

### Research Commands (`notebooklm research <cmd>`)

| Command | Arguments | Options | Example |
|---------|-----------|---------|---------|
| `status` | - | `--json` | `research status` |
| `wait` | - | `--timeout`, `--interval`, `--import-all`, `--json` | `research wait --import-all` |

### Generate Commands (`notebooklm generate <type>`)

All generate commands support:
- `--source/-s` to select specific sources (repeatable)
- `--json` for machine-readable output (returns `task_id` and `status`)
- `--language` to override output language (defaults to config or 'en')
- `--retry N` to automatically retry on rate limits with exponential backoff

| Command | Options | Example |
|---------|---------|---------|
| `audio [description]` | `--format [deep-dive\|brief\|critique\|debate]`, `--length [short\|default\|long]`, `--wait` | `generate audio "Focus on history"` |
| `report [description]` | `--format [briefing-doc\|study-guide]`, `--append "extra instructions"`, `--wait` | `generate report --format study-guide` |

### Features Beyond the Web UI

These CLI capabilities are not available in NotebookLM's web interface:

| Feature | Command | Description |
|---------|---------|-------------|
| **Report template append** | `generate report --format study-guide --append "..."` | Append instructions to built-in templates |

---

## Detailed Command Reference

### Session: `login`

Authenticate with Google NotebookLM via browser.

```bash
notebooklm login
```

Opens a Chromium browser with a persistent profile. Log in to your Google account, then press Enter in the terminal to save the session.

### Session: `use`

Set the active notebook for subsequent commands.

```bash
notebooklm use <notebook_id>
```

Supports partial ID matching:
```bash
notebooklm use abc  # Matches abc123def456...
```

### Session: `status`

Show current context (active notebook and conversation).

```bash
notebooklm status [OPTIONS]
```

**Options:**
- `--paths` - Show resolved configuration file paths
- `--json` - Output as JSON (useful for scripts)

**Examples:**
```bash
# Basic status
notebooklm status

# Show where config files are located
notebooklm status --paths
# Output shows home_dir, storage_path, context_path, browser_profile_dir

# JSON output for scripts
notebooklm status --json
```

**With `--paths`:**
```
                Configuration Paths
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ File            ┃ Path                         ┃ Source          ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ Home Directory  │ /home/user/.notebooklm      │ default         │
│ Storage State   │ .../storage_state.json      │                 │
│ Context         │ .../context.json            │                 │
│ Browser Profile │ .../browser_profile         │                 │
└─────────────────┴──────────────────────────────┴─────────────────┘
```

### Session: `auth check`

Diagnose authentication issues by validating storage file, cookies, and optionally testing token fetch.

```bash
notebooklm auth check [OPTIONS]
```

**Options:**
- `--test` - Also test token fetch from NotebookLM (makes network request)
- `--json` - Output as JSON (useful for scripts)

**Examples:**
```bash
# Quick local validation
notebooklm auth check

# Full validation with network test
notebooklm auth check --test

# JSON output for automation
notebooklm auth check --json
```

**Checks performed:**
1. Storage file exists and is readable
2. JSON structure is valid
3. Required cookies (SID) are present
4. Cookie domains are correct (.google.com vs regional)
5. (With `--test`) Token fetch succeeds

**Output shows:**
- Authentication source (file path or environment variable)
- Which cookies were found and from which domains
- Detailed cookie breakdown by domain (highlighting key auth cookies)
- Token lengths when using `--test`

**Use cases:**
- Debug "Not logged in" errors
- Verify auth setup in CI/CD environments
- Check if cookies are from correct domain (regional vs .google.com)
- Diagnose NOTEBOOKLM_AUTH_JSON environment variable issues

### Chat: `ask`

Ask a notebook question while preserving minimal follow-up continuity.

```bash
notebooklm ask <question> [OPTIONS]
```

**Options:**
- `-n, --notebook ID` - Notebook ID (uses current if not set; supports partial IDs)
- `-c, --conversation-id ID` - Continue a specific conversation explicitly
- `-s, --source ID` - Limit the question to specific source IDs (repeatable)
- `--json` - Output structured answer data including citations and source IDs

**Behavior:**
- If local CLI context already has a conversation for the current notebook, `ask` continues it.
- If there is no local conversation, the CLI asks NotebookLM for the most recent conversation and resumes it when available.
- Supplying a different `--notebook` starts fresh local context for that notebook unless `--conversation-id` is provided explicitly.

**Examples:**
```bash
# Ask the current notebook
notebooklm ask "What is the core argument?"

# Keep a specific conversation going
notebooklm ask --conversation-id conv_123 "Continue that explanation"

# Restrict the answer to selected sources
notebooklm ask -s src_001 -s src_002 "Compare these sources"

# Return structured output for automation
notebooklm ask "Summarize the disagreement" --json
```
### Source: `add-research`

Perform AI-powered research and add discovered sources to the notebook.

```bash
notebooklm source add-research <query> [OPTIONS]
```

**Options:**
- `--mode [fast|deep]` - Research depth (default: fast)
- `--from [web|drive]` - Search source (default: web)
- `--import-all` - Automatically import all found sources (works with blocking mode)
- `--no-wait` - Start research and return immediately (non-blocking)

**Examples:**
```bash
# Fast web research (blocking)
notebooklm source add-research "Quantum computing basics"

# Deep research into Google Drive
notebooklm source add-research "Project Alpha" --from drive --mode deep

# Non-blocking deep research for agent workflows
notebooklm source add-research "AI safety papers" --mode deep --no-wait
```

### Research: `status`

Check research status for the current notebook (non-blocking).

```bash
notebooklm research status [OPTIONS]
```

**Options:**
- `-n, --notebook ID` - Notebook ID (uses current if not set)
- `--json` - Output as JSON

**Output states:**
- **No research running** - No active research session
- **Research in progress** - Deep research is still running
- **Research completed** - Shows query, found sources, and summary

**Examples:**
```bash
# Check status
notebooklm research status

# JSON output for scripts/agents
notebooklm research status --json
```

### Research: `wait`

Wait for research to complete (blocking).

```bash
notebooklm research wait [OPTIONS]
```

**Options:**
- `-n, --notebook ID` - Notebook ID (uses current if not set)
- `--timeout SECONDS` - Maximum seconds to wait (default: 300)
- `--interval SECONDS` - Seconds between status checks (default: 5)
- `--import-all` - Import all found sources when done
- `--json` - Output as JSON

**Examples:**
```bash
# Basic wait
notebooklm research wait

# Wait longer for deep research
notebooklm research wait --timeout 600

# Wait and auto-import sources
notebooklm research wait --import-all

# JSON output for agent workflows
notebooklm research wait --json --import-all
```

**Use case:** Primarily for LLM agents that need to wait for non-blocking deep research started with `source add-research --no-wait`.

### Generate: `audio`

Generate an audio overview (podcast).

```bash
notebooklm generate audio [description] [OPTIONS]
```

**Options:**
- `--format [deep-dive|brief|critique|debate]` - Podcast format (default: deep-dive)
- `--length [short|default|long]` - Duration (default: default)
- `--language LANG` - Language code (default: en)
- `-s, --source ID` - Use specific source(s) (repeatable, uses all if not specified)
- `--wait` - Wait for generation to complete
- `--json` - Output as JSON (returns `task_id` and `status`)

**Examples:**
```bash
# Basic podcast (starts async, returns immediately)
notebooklm generate audio

# Debate format with custom instructions
notebooklm generate audio "Compare the two main viewpoints" --format debate

# Generate and wait for completion
notebooklm generate audio "Focus on key points" --wait

# Generate using only specific sources
notebooklm generate audio -s src_abc -s src_def

# JSON output for scripting/automation
notebooklm generate audio --json
# Output: {"task_id": "abc123...", "status": "pending"}
```

### Generate: `report`

Generate a text report (briefing doc or study guide).

```bash
notebooklm generate report [description] [OPTIONS]
```

**Options:**
- `--format [briefing-doc|study-guide]` - Report format (default: briefing-doc)
- `--append TEXT` - Append extra instructions to the built-in prompt
- `-s, --source ID` - Use specific source(s) (repeatable, uses all if not specified)
- `--wait` - Wait for generation to complete
- `--json` - Output as JSON

**Examples:**
```bash
notebooklm generate report --format study-guide
notebooklm generate report "Executive summary for stakeholders" --format briefing-doc

# Generate report from specific sources
notebooklm generate report --format study-guide -s src_001 -s src_002

# Append instructions to a built-in format
notebooklm generate report --format study-guide --append "Target audience: beginners"
notebooklm generate report --format briefing-doc --append "Focus on AI trends, keep it under 2 pages"
```

Completed `generate ... --wait` commands print the ready URL directly.
Without `--wait`, generate commands print the task ID (or return it with `--json`) so you can track completion with the surviving artifact status helpers.

---

## Common Workflows

### Research → Podcast

Find information on a topic and create a podcast about it.

```bash
# 1. Create a notebook for this research
notebooklm create "Climate Change Research"
# Output: Created notebook: abc123

# 2. Set as active
notebooklm use abc123

# 3. Add a starting source
notebooklm source add "https://en.wikipedia.org/wiki/Climate_change"

# 4. Research more sources automatically (blocking - waits up to 5 min)
notebooklm source add-research "climate change policy 2024" --mode deep --import-all

# 5. Generate a podcast
notebooklm generate audio "Focus on policy solutions and future outlook" --format debate --wait
```

### Research → Podcast (Non-blocking with Subagent)

For LLM agents, use non-blocking mode to avoid timeout:

```bash
# 1-3. Create notebook and add initial source (same as above)
notebooklm create "Climate Change Research"
notebooklm use abc123
notebooklm source add "https://en.wikipedia.org/wiki/Climate_change"

# 4. Start deep research (non-blocking)
notebooklm source add-research "climate change policy 2024" --mode deep --no-wait
# Returns immediately

# 5. In a subagent, wait for research and import
notebooklm research wait --import-all --timeout 300
# Blocks until complete, then imports sources

# 6. Continue with podcast generation...
```

**Research commands:**
- `research status` - Check if research is in progress, completed, or not running
- `research wait --import-all` - Block until research completes, then import sources

### Document Analysis → Study Materials

Upload documents and create study materials.

```bash
# 1. Create notebook
notebooklm create "Exam Prep"
notebooklm use <id>

# 2. Add your documents
notebooklm source add "./textbook-chapter.pdf"
notebooklm source add "./lecture-notes.pdf"

# 3. Get a summary
notebooklm summary

# 4. Generate study materials
notebooklm generate report --format study-guide --wait
notebooklm generate audio "Focus on the key exam themes" --wait

# 5. Ask specific questions
notebooklm ask "Explain the key concepts in chapter 3"
notebooklm ask "What are the most likely exam topics?"
```

### YouTube → Quick Summary

Turn a YouTube video into notes.

```bash
# 1. Create notebook and add video
notebooklm create "Video Notes"
notebooklm use <id>
notebooklm source add "https://www.youtube.com/watch?v=VIDEO_ID"

# 2. Get summary
notebooklm summary

# 3. Ask questions
notebooklm ask "What are the main points?"
notebooklm ask "Create bullet point notes"

# 4. Generate a quick briefing doc
notebooklm generate report --format briefing-doc --wait
```

### Bulk Import

Add multiple sources at once.

```bash
# Set active notebook
notebooklm use <id>

# Add multiple URLs
notebooklm source add "https://example.com/article1"
notebooklm source add "https://example.com/article2"
notebooklm source add "https://example.com/article3"

# Add multiple local files (use a loop)
for f in ./papers/*.pdf; do
  notebooklm source add "$f"
done
```

---

## Tips for LLM Agents

When using this CLI programmatically:

1. **Two ways to specify notebooks**: Either use `notebooklm use <id>` to set context, OR pass `-n <id>` directly to commands. Most commands support `-n/--notebook` as an explicit override.

2. **Retained generation commands are async by default**:
   - `audio`: Returns immediately with a task ID unless you pass `--wait`
   - `report`: Returns immediately with a task ID unless you pass `--wait`

    Avoid `--wait` for LLM agents when possible. The reduced CLI does not keep a separate `artifact` follow-up command, so either let the user check back later or run the original `generate ... --wait` command only when a blocking wait is acceptable.

3. **Partial IDs work**: `notebooklm use abc` matches any notebook ID starting with "abc".

4. **Check status**: Use `notebooklm status` to see the current active notebook and conversation.

5. **Auto-detection**: `source add` auto-detects content type:
   - URLs starting with `http` → web source
   - YouTube URLs → video transcript extraction
   - File paths → file upload (PDF, text, Markdown, Word, audio, video, images)

6. **Error handling**: Commands exit with non-zero status on failure. Check stderr for error messages.

7. **Deep research**: Use `--no-wait` with `source add-research --mode deep` to avoid blocking. Then use `research wait --import-all` in a subagent to wait for completion.
