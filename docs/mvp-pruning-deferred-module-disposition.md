# Deferred Module Disposition

Decision record for `bd-27n.5.3`.

This note re-audits the modules that [PRUNING_PLAN.md](../PRUNING_PLAN.md)
previously left in `DEFER` after the client and chat pruning passes landed.
The purpose is to replace "leave it for later" with an explicit
keep/delete/archive decision grounded in surviving callsites.

## Decision Summary

- `_notes.py`: stay `DEFER`
- `_settings.py`: stay `DEFER`
- `_sharing.py`: stay `DEFER`
- `_chat_settings.py`: move from `DEFER` to `LEGACY/FROZEN`

No module moves straight to `DELETE` in this pass.

## Decision Rules

- Keep a module in `DEFER` only if it is still entangled with the mainline
  `src/notebooklm/**` package boundary through `NotebookLMClient`, live default
  test coverage, or another current compatibility hold.
- Move a module to `LEGACY/FROZEN` when it no longer has an active mainline
  caller and survives only as archival parser/reference stock or frozen-side
  test coverage.
- Do not delete a deferred module just because the front-door CLI stopped
  advertising it. Deletion still requires deliberate removal of the remaining
  compatibility boundary.

## Module Decisions

### `src/notebooklm/_notes.py`

Disposition: `DEFER`

Why it is not deletable yet:

- `src/notebooklm/client.py` still exposes `client.notes` as a lazy deferred
  compatibility property.
- Frozen MCP and BA code still calls the notes surface through
  `src/notebooklm_mcp/tools/notes.py`,
  `src/notebooklm_mcp/tools/chat.py`,
  `src/notebooklm_mcp/tools/workflows.py`, and
  `src/notebooklm_mcp/ba/adapter.py`.
- Live tests still exercise the surface directly, including
  `tests/integration/test_notes.py`,
  `tests/e2e/test_notes.py`,
  `tests/unit/test_mcp_tools_notes.py`, and
  `tests/integration/test_vcr_comprehensive.py`.

Deletion trigger:

- Remove `NotebookLMClient.notes` as a deliberate package/API break, and
- either delete or more aggressively archive the remaining notes/mind-map
  compatibility callers and tests.

### `src/notebooklm/_settings.py`

Disposition: `DEFER`

Why it is not deletable yet:

- `src/notebooklm/client.py` still exposes `client.settings` as a lazy deferred
  compatibility property.
- Frozen MCP and BA code still depends on it through
  `src/notebooklm_mcp/tools/settings.py` and
  `src/notebooklm_mcp/ba/adapter.py`.
- Live tests still exercise the surface directly, including
  `tests/integration/test_settings.py`,
  `tests/unit/test_client.py`, and
  `tests/integration/test_vcr_comprehensive.py`.

Deletion trigger:

- Remove `NotebookLMClient.settings` in the package-boundary break lane, and
- explicitly cut or re-freeze the remaining settings-specific MCP/BA/test
  expectations.

### `src/notebooklm/_sharing.py`

Disposition: `DEFER`

Why it is not deletable yet:

- `src/notebooklm/client.py` still exposes `client.sharing` as a lazy deferred
  compatibility property.
- There are no surviving active `src/notebooklm/**` runtime callers beyond that
  property, but the public SDK surface is still tested directly.
- Live tests still exercise the surface directly, including
  `tests/integration/test_sharing.py`,
  `tests/e2e/test_sharing.py`,
  `tests/unit/test_client.py`, and
  `tests/integration/test_vcr_comprehensive.py`.

Deletion trigger:

- Remove `NotebookLMClient.sharing` in the same deliberate package/API break
  lane that handles `src/notebooklm/__init__.py`, and
- retire the remaining sharing-focused tests/reference expectations in the same
  change.

### `src/notebooklm/_chat_settings.py`

Disposition: `LEGACY/FROZEN`

Why it no longer belongs in `DEFER`:

- The active `src/notebooklm/_chat.py` path is now ask-only and no longer
  imports `_chat_settings.py`.
- No active `src/notebooklm/**` caller imports `parse_chat_settings`.
- The remaining direct usage is parser-only test coverage in
  `tests/unit/test_chat_settings.py`.
- Frozen MCP and BA chat-settings surfaces are already outside the active MVP
  contract, so this parser is no longer a mainline dependency blocker.

Why it is not deleted immediately:

- The parser still has archival value as frozen implementation stock while the
  package-boundary cleanup and frozen-reference cleanup remain separate beads.
- Deleting it now would turn this decision pass into a package/test cleanup pass
  instead of a narrow disposition record.

Deletion trigger:

- Remove the remaining parser-only reference/tests, or
- fold the module into a dedicated package-compatibility cleanup once the
  archived chat-settings reference material is intentionally retired.

## Practical Outcome For Follow-Up Beads

- `bd-27n.5.4` should treat `client.notes`, `client.settings`, and
  `client.sharing` as the real public-break problem, not `_chat_settings.py`.
- Any future delete pass for `_notes.py`, `_settings.py`, or `_sharing.py`
  should cite this note and prove that the lazy client property plus the nearest
  live tests were removed in the same change.
- `_chat_settings.py` is no longer a blocker for active CLI/SDK pruning. It is
  now archival stock that can be deleted later in a deliberate cleanup.
