# MVP Pruning Verification

Status: verification note for `bd-27n.5.2`  
Last updated: 2026-03-14

This note records the prune-focused quality gates run after the main MVP-pruning
doc and client cleanup landed. The goal is not to prove every historical surface
still works. The goal is to verify that the reduced CLI/SDK branch still forms a
coherent zero-to-output workflow and that any remaining fallout is explicit.

## Scope

The active branch promise validated here is:

1. `notebooklm login` / `notebooklm auth check`
2. `notebooklm create` / `notebooklm use`
3. `notebooklm source add` or `notebooklm source add-research`
4. `notebooklm source wait` or `notebooklm research wait`
5. `notebooklm ask`
6. `notebooklm generate audio|report`

Deferred compatibility surfaces such as `client.notes`, `client.settings`, and
`client.sharing` are covered only enough to confirm they still import and behave
as intentionally deferred paths.

## Quality Gates Run

### Import, Packaging, and Entry-Point Smoke

- `uv run python - <<'PY' ... PY`
  - `import_smoke=ok`
  - `client_class=NotebookLMClient`
  - `cli_name=cli`
  - `scripts=['notebooklm']`
  - `package_exclude=['notebooklm_mcp*']`

### CLI and Help Truthfulness

- `uv run python -m notebooklm.notebooklm_cli --help`
- `uv run python -m notebooklm.notebooklm_cli generate report --help`
- removed root command smoke via `CliRunner`:
  - `artifact` -> exit `2`, `No such command`
  - `download` -> exit `2`, `No such command`
  - `note` -> exit `2`, `No such command`
  - `share` -> exit `2`, `No such command`
  - `skill` -> exit `2`, `No such command`

### Passing Pytest Gates

- `uv run --extra dev python -m pytest -q tests/unit/cli` -> `263 passed`
- `uv run --extra dev python -m pytest -q tests/integration/cli_vcr tests/integration/test_notebooks.py tests/integration/test_chat.py tests/integration/test_research_api.py` -> `135 passed`
- `uv run --extra dev python -m pytest -q tests/unit/test_client.py tests/unit/test_source_selection.py tests/unit/test_artifacts_coverage.py` -> `83 passed`
- `uv run --extra dev python -m pytest -q tests/integration/test_notes.py tests/integration/test_settings.py tests/integration/test_sharing.py` -> `28 passed`
- `uv run --extra dev python -m pytest -q tests/unit/test_mcp_tools_notes.py tests/unit/test_mcp_tools_settings.py tests/unit/test_mcp_tools_workflows.py` -> `21 passed`
- `uv run --extra dev python -m pytest -q tests/unit/cli/test_grouped.py tests/unit/test_api_coverage.py` -> `21 passed`
- `uv run --extra dev python -m pytest -q tests/integration/cli_vcr` -> `12 passed`
- `uv run python -m py_compile docs/examples/quickstart.py docs/examples/research-to-podcast.py docs/examples/video.py docs/examples/notes.py` -> pass

### Active-Docs Truthfulness

- Grep over `README.md`, active docs, and active examples found no remaining
  active-looking references to removed `language`, `artifact`, `download`,
  `video`, `quiz`, `slide-deck`, `flashcards`, `infographic`, `data-table`,
  `mind-map`, or `revise-slide` CLI flows.
- Historical/reference files that still mention broader behavior are now labeled
  as deferred, legacy, or full-surface implementation references.

## Residual Risk

### 1. Broad integration artifact suite still preserves removed non-MVP behavior

- Failing gate:
  - `uv run --extra dev python -m pytest -q tests/integration/cli_vcr tests/integration/test_notebooks.py tests/integration/test_chat.py tests/integration/test_research_api.py tests/integration/test_artifacts.py`
  - result: `53 failed, 167 passed, 50 errors`
- Failure pattern:
  - stale expectations for removed video, quiz, flashcards, infographic,
    slide-deck, mind-map, and download/export flows
  - stale internal-helper expectations such as `_get_artifact_content`
  - error assertions that still assume pre-prune behavior instead of the new
    `ValidationError` MVP boundary
- Follow-up bead:
  - `bd-27n.5.5` `Prune tests/integration/test_artifacts.py to the retained MVP artifact contract`

### 2. Deferred module fate is still intentionally unresolved

- `client.notes`, `client.settings`, and `client.sharing` now survive only as
  lazy deferred-compatibility surfaces.
- `_notes.py`, `_settings.py`, `_sharing.py`, and the broader package boundary
  still need an explicit keep/delete/archive decision rather than gradual drift.
- Existing follow-up beads:
  - `bd-27n.5.3` `Decide whether deferred modules now move from DEFER to DELETE or archive`
  - `bd-27n.5.4` `Isolate the src/notebooklm/__init__.py public API break strategy`

### 3. Live-auth E2E proof was not rerun in this pass

- This verification pass intentionally used import smoke, CLI help checks, unit
  coverage, integration coverage, and VCR coverage because live-auth E2E depends
  on environment-specific secrets and notebook IDs.
- Earlier stacked-worktree runs in this environment already showed that broader
  E2E collection hits missing `NOTEBOOKLM_READ_ONLY_NOTEBOOK_ID`, which is an
  environment prerequisite issue rather than a newly discovered code regression.

## Conclusion

The reduced CLI/SDK MVP is verified well enough to move forward:

- the retained bootstrap flow has concrete automated evidence
- packaging/help/docs now match the reduced surface
- remaining uncertainty is explicit and assigned to follow-up beads instead of
  being buried in mail or tribal knowledge
