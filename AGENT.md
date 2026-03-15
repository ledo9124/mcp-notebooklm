# AGENT.md — Canonical Workflow

This file defines **one fixed workflow** for all agent sessions. Follow the workflow in order. Tool sections below are **reference modules**, not separate workflows.

---

## 0) Global Invariants

- **Do not disturb other agents' work.** Never stash, revert, overwrite, or "clean up" unrelated changes. Treat them as if you made them.
- **Prefer one path, not many.** Use the canonical workflow below. Do not invent alternate start/end flows.
- **Never launch blocking TUIs in agent mode.**
  - `cass` → always use `--robot` or `--json`
  - `cm` → always use `--json` when machine-readable output is needed
  - `bv` → always use `--robot-*`
- **Stdout is data; stderr is diagnostics.** Prefer machine-readable flags in agent contexts.
- **Tool boundaries matter:**
  - **bv** decides **what to work on**
  - **br** records **task state**
  - **Agent Mail** coordinates **who is doing what**
  - **file reservations** protect **where edits happen**
  - **cm** supplies **memory before work**
  - **cass** supplies **historical evidence on demand**
  - **tilth** handles **code exploration/editing**

---

## 1) Canonical Session Workflow

Follow these steps in order unless the user gave a specific task that makes one step unnecessary.

### Step 1 — Identify the task

Use exactly one of these entry modes:

- **Mode A: User already gave a concrete task or issue ID**
  - Use the provided task directly.
  - If a Beads issue exists, use its ID as the canonical identifier.

- **Mode B: No task was assigned; you need to choose work**
  - Run `bv --robot-triage` first.
  - If you only need one pick, use `bv --robot-next`.
  - Confirm details with `br show <id>` before editing.

### Step 2 — Claim and coordinate

Once scope is known:

1. Start or resume your agent identity/session.
2. Check inbox / active agents.
3. Announce start in the issue thread.
4. Reserve files **before making edits**.

Canonical thread identifier:
- Use `br-###` when a Beads issue exists.
- Use the same ID in Mail `thread_id`, message subject prefix, and reservation reason.

### Step 3 — Load memory before non-trivial work

Before implementation, run:

```bash
cm context "<task description>" --json
```

Use the result to extract:
- relevant rules to follow
- anti-patterns to avoid
- useful history snippets
- suggested `cass` follow-up queries

If the task is trivial, mechanical, or purely clerical, you may skip `cm context`.

### Step 4 — Investigate code correctly

When touching code:

1. Use `tilth_search` first
2. Use `tilth_read` for targeted reading
3. Use `tilth_edit` for edits
4. Use `tilth_deps` before changing exported signatures, renaming, or deleting files

Do not use ad hoc grep/cat/find flows when tilth tools can answer the question.

### Step 5 — Use `cass` only when memory is insufficient

Use `cass` when you need raw historical evidence, examples, or prior fixes:

```bash
cass search "<query>" --robot --limit 5 --fields minimal
```

Use `cass` for:
- prior solutions
- similar bugs
- earlier design decisions
- session archaeology across agents/machines

Do **not** use `cass` as a replacement for `cm context`; use it as the deeper evidence layer.

### Step 6 — Execute and keep state aligned

During work:

- Keep Beads status accurate (`in_progress`, then `closed` when done)
- Send progress updates in-thread when scope changes or a milestone is reached
- Leave memory feedback when useful:
  - `// [cass: helpful b-xyz] - reason`
  - `// [cass: harmful b-xyz] - reason`

### Step 7 — Finish cleanly

If code changed:

1. Run relevant quality gates (tests, lint, build)
2. Close or update the Beads issue
3. Run `br sync --flush-only`
4. Release file reservations
5. Send final handoff / completion note in-thread
6. Commit and push if this session is responsible for landing the change

---

## 2) Tool Modules (Reference Only)

These sections describe **when** each tool is used. They do not replace the canonical workflow.

### tilth — Code exploration and editing

**Use for:** searching symbols, reading code, dependency-aware edits.

**Always do:**
- `tilth_search` before reading broadly
- `tilth_read` for precise sections
- `tilth_edit` for file edits
- `tilth_deps` before signature / rename / delete changes

**Do not use for:** project planning, task tracking, or agent coordination.

---

### MCP Agent Mail — Coordination

**Use for:** agent identity, inbox/outbox, threaded updates, file reservations.

**Use when:**
- starting a task
- coordinating with other agents
- reserving edit surfaces
- handing off work

**Canonical pattern:**
1. start session / register
2. check inbox
3. announce start
4. reserve files
5. post progress replies in-thread
6. send completion handoff

**Do not use for:** issue priority or memory retrieval.

---

### br (Beads) — Issue state and source of truth

**Use for:** issue lifecycle, dependencies, priority, readiness, closing work.

**Canonical commands:**
```bash
br ready --json
br show <id>
br update <id> --status=in_progress
br close <id> --reason "Completed"
br sync --flush-only
```

**Rule:** Beads is the source of truth for task state. Mail is the source of truth for conversation.

**Do not use for:** coordination messages or file reservations.

---

### bv — Triage and planning

**Use for:** deciding what to work on when scope is not already assigned.

**Canonical commands:**
```bash
bv --robot-triage
bv --robot-next
bv --robot-plan
```

**Rule:** `bv` is for **selection and planning**, not execution tracking.

**Do not use for:** claiming work, editing code, or communication.

---

### cass — Historical session retrieval

**Use for:** raw evidence from prior agent sessions.

**Canonical commands:**
```bash
cass health --json
cass search "<query>" --robot --limit 5 --fields minimal
cass view <session> -n <hit> --json
cass expand <session> -n <hit> -C 3 --json
```

**Rule:** Never run bare `cass` in agent mode.

**Best use:** after `cm context` suggests a deeper follow-up or when blocked by missing historical context.

---

### cm — Memory and lessons

**Use for:** task-specific memory before work and continuous learning from prior sessions.

**Canonical commands:**
```bash
cm context "<task>" --json
cm onboard status
cm onboard sample --fill-gaps
cm onboard read <session> --template --json
cm playbook add "<rule>" --category "<category>"
```

**Rule:** Use `cm context` before non-trivial implementation work.

**Interpretation:**
- `relevantBullets` = rules to follow
- `antiPatterns` = pitfalls to avoid
- `historySnippets` = prior examples
- `suggestedCassQueries` = deeper evidence queries for `cass`

**Do not use for:** raw session archaeology when you need direct evidence; use `cass` for that.

---

## 3) Decision Rules To Prevent Chaos

When unsure, apply these rules in order:

1. **Need to choose work?** → `bv`
2. **Need to confirm or update issue state?** → `br`
3. **Need to coordinate with other agents?** → Agent Mail
4. **Need to protect files before editing?** → file reservations
5. **Need pre-task memory?** → `cm context`
6. **Need raw historical evidence?** → `cass`
7. **Need to inspect or edit code?** → tilth

If a step is already satisfied, do not re-run earlier layers unnecessarily.

---

## 4) Minimal Agent Checklist

### Start of session

- [ ] Task is known (`user task` or `bv --robot-triage`)
- [ ] Thread / issue ID is known
- [ ] Agent session started
- [ ] Inbox checked
- [ ] Reservation acquired
- [ ] `cm context` run for non-trivial work

### End of session

- [ ] Quality gates run (if code changed)
- [ ] `br` status updated
- [ ] `br sync --flush-only` run
- [ ] Reservations released
- [ ] Final thread update sent
- [ ] Commit/push completed if applicable

---

## 5) Anti-Patterns

- Starting with multiple tools at once
- Using `br ready`, `bv --robot-triage`, `cm context`, and Mail macros as four separate "start here" commands
- Running bare `cass` or bare `bv`
- Asking what to do with unrelated working-tree changes
- Using Mail for task tracking or Beads for conversation
- Using `cass` when `cm context` would have answered first
- Skipping reservations before edits in shared files

