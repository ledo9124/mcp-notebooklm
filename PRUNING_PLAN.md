# MVP Pruning Plan

Companion contract: [docs/mvp-pruning-contract.md](docs/mvp-pruning-contract.md)

Use this file as the file-by-file map. Use the companion contract for the authoritative meaning of `KEEP`, `DELETE`, `DEFER`, and `LEGACY/FROZEN`, the retained user-complete workflows, the coupling rules, and the validation gates future pruning beads must cite.

# Status Legend

- `KEEP`: supported MVP surface that must remain truthful in code, help, docs, and tests.
- `DELETE`: confirmed mainline removal target.
- `DEFER`: not part of the intended MVP, but temporarily retained because callers or compatibility boundaries still depend on it.
- `LEGACY/FROZEN`: separate or quarantined surface outside the MVP promise. Keep isolated and clearly marked, but do not treat it as active scope.

# 0. Surface Map

- `notebooklm` entry point / `src/notebooklm/notebooklm_cli.py`: main CLI shell; PARTIAL.
- `src/notebooklm/auth.py`: auth/session bootstrap from storage state plus token extraction; KEEP.
- `src/notebooklm/_core.py` + `src/notebooklm/rpc/*`: `httpx` transport and RPC knowledge; KEEP.
- `src/notebooklm/client.py`: broad public client facade; PARTIAL.
- `src/notebooklm/cli/session.py`, `cli/notebook.py`, `cli/chat.py`, `cli/source.py`, `cli/research.py`, `cli/generate.py`: MVP-adjacent CLI surface but overgrown; PARTIAL.
- `src/notebooklm/cli/share.py`, `cli/note.py`, `cli/skill.py`, `cli/download.py`, `cli/artifact.py`: non-MVP CLI leaves; DELETE.
- `src/notebooklm/cli/language.py`: helper + command surface mixed together; PARTIAL.
- `src/notebooklm/_notebooks.py`, `_chat.py`, `_artifacts.py`: mixed MVP/non-MVP methods; PARTIAL.
- `src/notebooklm/_sources.py`, `_research.py`, `paths.py`, `cli/helpers.py`, `cli/options.py`, `cli/error_handler.py`: KEEP for now.
- `src/notebooklm/_notes.py`, `_sharing.py`, `_settings.py`, `__init__.py`: DEFER until dependent command surfaces or public compatibility holds are cut.
- `src/notebooklm/_chat_settings.py`: LEGACY/FROZEN archival parser stock after chat-settings parity removal.
- `src/notebooklm_mcp/**`: LEGACY/FROZEN.
- `src/notebooklm_mcp/ba/**`: LEGACY/FROZEN.

# 1. DELETE — Confirmed removals

## `src/notebooklm/cli/skill.py`
- Reason: Claude Code skill installer is outside target MVP.
- Evidence: wired only through CLI registration surface.
- Risk: low.

## `src/notebooklm/data/SKILL.md`
- Reason: package data only used by `cli/skill.py`.
- Evidence: consumed through `importlib.resources` by the skill command.
- Risk: low after the skill command is detached.

## `src/notebooklm/cli/share.py`
- Reason: sharing/user-permission CLI is outside MVP.
- Evidence: standalone CLI command group; not required by auth/transport.
- Risk: low-medium because sharing internals remain until later.

## `src/notebooklm/cli/note.py`
- Reason: note CRUD is outside MVP.
- Evidence: standalone CLI command group; not required by auth/transport.
- Risk: medium because chat/artifact note couplings must be removed first.

## `src/notebooklm/cli/download.py`
- Reason: standalone artifact download surface is outside MVP.
- Evidence: standalone CLI command group.
- Risk: medium.

## `src/notebooklm/cli/artifact.py`
- Reason: standalone artifact CRUD/export/poll/wait/suggestions shell is outside MVP.
- Evidence: standalone CLI command group.
- Risk: medium.

# 2. PARTIAL — Cần tỉa trong file/module

## `src/notebooklm/notebooklm_cli.py`
- Keep: root CLI group and registrations for session/notebook/chat/source/research plus reduced generate surface.
- Remove: registrations/imports for artifact, download, note, share, skill, language.

## `src/notebooklm/cli/__init__.py`
- Keep: helper reexports used by kept commands.
- Remove: reexports for removed command groups.

## `src/notebooklm/cli/chat.py`
- Keep: `ask` command core path.
- Remove: `--save-as-note`, `configure`, `history`, and all note/settings parity.

## `src/notebooklm/_chat.py`
- Keep: `ask` and only conversation helpers needed by query continuity.
- Remove: chat-settings parity methods and `_chat_settings.py` dependency.

## `src/notebooklm/cli/generate.py`
- Keep: `audio`; `report` only for briefing-doc / study-guide.
- Remove: video, slide-deck, revise-slide, quiz, flashcards, infographic, data-table, mind-map, and imports only used by them.

## `src/notebooklm/_artifacts.py`
- Keep: minimal status/wait plus audio/report/study-guide generation.
- Remove: video, quiz, flashcards, infographic, slide-deck, revise-slide, data-table, mind-map, export/download helpers tied to those modes.

## `src/notebooklm/cli/notebook.py`
- Keep: `list`, `create`, and `summary`.
- Remove: `delete`, `rename`.

## `src/notebooklm/_notebooks.py`
- Keep: `list`, `create`, `get`, `get_summary`, `get_description`, `get_raw`.
- Remove: `delete`, `rename`, `remove_from_recent`, `share`, `get_share_url`.

## `src/notebooklm/cli/source.py`
- Keep: `source list`, `source add`, `source wait`, and `source add-research`.
- Remove: get/delete/rename/refresh/add-drive/fulltext/guide/stale from the user-facing CLI surface.

## `src/notebooklm/cli/research.py`
- Keep: `status` and `wait` as the monitor/import path for `source add-research --no-wait`.
- Remove or demote: any broader research-management surface beyond that retained acquisition loop.

## `src/notebooklm/cli/session.py`
- Keep: `login`, `use`, `status`, `clear`, and `auth check`.
- Remove: server-language sync helper and its post-login call.

## `src/notebooklm/cli/language.py`
- Keep: helper constants/functions only if local default-language persistence survives.
- Remove: user-facing `language` command group.

## `src/notebooklm/client.py`
- Keep: client shell, `from_storage`, `refresh_auth`, and notebooks/sources/chat/research/reduced-artifacts subclients.
- Remove: `notes`, `settings`, `sharing` subclient construction after dependencies are gone.

## `src/notebooklm/cli/helpers.py`
- Keep: auth/context/json/notebook/source helpers.
- Remove: artifact/note-specific helper functions after their command families are gone.

# 3. DEFER / LEGACY-FROZEN — Temporarily retained or quarantined

- Follow-up decision record: [docs/mvp-pruning-deferred-module-disposition.md](docs/mvp-pruning-deferred-module-disposition.md).

## `src/notebooklm_mcp/**`
- Status: LEGACY/FROZEN.
- Reason: separate MCP entry point, outside MVP.
- Boundary note: [docs/mvp-pruning-mcp-ba-boundary.md](docs/mvp-pruning-mcp-ba-boundary.md).
- Bring back when MCP server parity returns to scope.

## `src/notebooklm_mcp/tools/**`
- Status: LEGACY/FROZEN.
- Reason: tool registry is MCP-only.
- Bring back when MCP parity returns.

## `src/notebooklm_mcp/ba/**`
- Status: LEGACY/FROZEN.
- Reason: BA runner/evaluation is explicitly out of MVP.
- Boundary note: [docs/mvp-pruning-mcp-ba-boundary.md](docs/mvp-pruning-mcp-ba-boundary.md).
- Bring back when benchmarking/regression work is scheduled.

## `src/notebooklm/_notes.py`
- Status: DEFER.
- Reason: note + mind-map domain is out-of-scope, but `client.notes`, frozen MCP/BA callers, and live tests still depend on it.
- Bring back only if note or mind-map workflows return.

## `src/notebooklm/_sharing.py`
- Status: DEFER.
- Reason: sharing domain is out-of-scope, but `client.sharing` remains part of the current SDK boundary and is still exercised by live tests.
- Bring back only if sharing re-enters scope.

## `src/notebooklm/_settings.py`
- Status: DEFER.
- Reason: global user settings are outside MVP, but `client.settings`, frozen MCP/BA callers, and live tests still depend on it.
- Bring back only if server-side settings management returns.

## `src/notebooklm/_chat_settings.py`
- Status: LEGACY/FROZEN.
- Reason: active `src/notebooklm/_chat.py` no longer depends on the parser; the file survives only as archival parser/test stock.
- Bring back only if chat settings parity returns, or delete it during a deliberate archival cleanup.

## `src/notebooklm/__init__.py`
- Status: DEFER.
- Reason: broad public SDK surface is a real package-root compatibility promise, not just internal glue.
- Strategy note: [docs/mvp-pruning-package-api-strategy.md](docs/mvp-pruning-package-api-strategy.md).
- Bring back or prune only during a deliberate package API break/release lane.

# 4. Removal Order

1. Quarantine `src/notebooklm_mcp/ba/**` behind an explicit legacy boundary.
2. Quarantine the rest of `src/notebooklm_mcp/**` and the `notebooklm-mcp` entry point behind that same boundary.
3. Remove CLI registration for `skill`; verify no remaining references.
4. Delete `src/notebooklm/cli/skill.py`; then remove `src/notebooklm/data/SKILL.md`.
5. Remove CLI registration for `share`; then delete `src/notebooklm/cli/share.py`.
6. Remove note-dependent chat branches and CLI registration for `note`; then delete `src/notebooklm/cli/note.py`.
7. Remove CLI registration for `download`; then delete `src/notebooklm/cli/download.py`.
8. Remove CLI registration for `artifact`; then delete `src/notebooklm/cli/artifact.py`.
9. Prune `generate.py` and `_artifacts.py` down to audio/report/study-guide only.
10. Prune `notebook.py` and `_notebooks.py` down to a minimal lifecycle + summary surface (`list` / `create` / `summary` plus required backend helpers).
11. Prune `source.py` user-facing surface down to add/list/wait plus `add-research`.
12. Prune `chat.py` / `_chat.py` settings and note parity.
13. Prune `session.py` language sync, then trim `cli/language.py`, then shrink `client.py`.
14. Only after step 13, decide whether `_notes.py`, `_sharing.py`, and `_settings.py` move from DEFER to DELETE in a follow-up branch.
15. Keep `src/notebooklm/__init__.py` on a separate package-API break lane; do not contract the root export surface as incidental pruning fallout.

# 5. Risk Register

- `client.py` is a central import hub; deleting `_notes.py`, `_settings.py`, or `_sharing.py` too early will break import-time initialization.
- Mind-map support crosses `_notes.py`, `_artifacts.py`, `cli/artifact.py`, and `cli/generate.py`; prune it as one mini-epic, not piecemeal.
- `cli/language.py` is both helper library and command group; deleting the whole file too early breaks `generate.py` and `session.py`.
- `cli/source.py` is much larger than MVP, but underlying source APIs are still useful for sync/research internals.
- If pruning removes notebook creation or source ingestion entirely, the CLI stops being a coherent bootstrap path for new users even if the remaining code is technically smaller.
- `__init__.py` is public package surface; pruning it is a breaking API change and should be isolated.
- Expect follow-on cleanup in tests/docs/packaging once non-MVP command groups are removed.
