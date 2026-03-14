# MVP Pruning MCP/BA Boundary Inventory

Status: legacy-boundary note for `bd-27n.2.1` and staging note for `bd-27n.2.2`

This note inventories the current repository surfaces that still make MCP and the BA runner look like active product promises. The point is not to delete those systems immediately. The point is to define a clean legacy boundary so MVP CLI/SDK pruning can proceed without treating MCP and BA parity as hidden acceptance criteria.

Historical note: parts of the packaging/README cleanup described below have
already landed on the current branch. Treat this file primarily as the boundary
definition and historical rationale, not as a literal checklist of everything
that is still live today.

## Architectural Snapshot

- Core product surface lives under `src/notebooklm/`: async SDK modules plus the `notebooklm` CLI.
- `src/notebooklm/client.py` is the central SDK facade over `ClientCore`. It now eagerly builds notebooks, sources, artifacts, chat, and research, while notes/settings/sharing remain lazy deferred-compatibility surfaces.
- `src/notebooklm/notebooklm_cli.py` is the main CLI shell and currently registers both MVP-adjacent commands and several larger historical command groups.
- `src/notebooklm_mcp/server.py` builds a separate FastMCP server around a shared `AppContext` that holds a connected `NotebookLMClient`.
- `src/notebooklm_mcp/tools/__init__.py` registers the public MCP surface, including the workflow-native BA tools through `register_ba_tools(...)`.
- `src/notebooklm_mcp/ba/` is not a tiny helper folder. It is a dedicated subsystem with adapter, run-store, extraction, rendering, validation, rerun, and state-machine modules.

## Why The Legacy Boundary Is Safe

- The dependency direction is one-way: `src/notebooklm_mcp/**` depends on the core SDK in `src/notebooklm/**`, but `src/notebooklm/**` does not import `notebooklm_mcp`.
- That means phase-1 does not need a deep runtime disentangling pass before it can freeze MCP and BA from the active MVP contract.
- The real coupling today is promise-level coupling:
  - packaging and entry points
  - README and docs
  - examples
  - MCP and BA-focused tests and fixtures

## Historical Active Promise Inventory

### Packaging And Runtime Entry Points

This section records the inventory that made the MCP/BA boundary necessary.
Some of these items have since been removed from the packaged mainline product.

- `pyproject.toml` still presents MCP as part of the shipped package:
  - optional dependency group `mcp`
  - `project.scripts.notebooklm-mcp = "notebooklm_mcp:main"`
  - package discovery includes `notebooklm_mcp*`
  - project keywords still include `mcp`
- `src/notebooklm_mcp/__main__.py` exposes `notebooklm-mcp serve` plus stdio / HTTP / SSE transport flags.
- `src/notebooklm_mcp/server.py` creates the FastMCP server, loads config, and opens a real `NotebookLMClient` from browser storage.
- `src/notebooklm_mcp/tools/__init__.py` wires the generic MCP tool families plus the BA runner into the same public server surface.
- Repository inventory at the time of this note:
  - `src/notebooklm_mcp/ba/`: 24 Python modules
  - `src/notebooklm_mcp/tools/`: 12 Python modules

### BA Runner Specific Surface

- `src/notebooklm_mcp/ba/__init__.py` declares BA as a first-class subsystem with explicit module boundaries and dependency rules.
- `src/notebooklm_mcp/ba/tools.py` registers public `ba.*` handlers such as:
  - `ba.start_run`
  - `ba.register_sources`
  - `ba.status`
  - `ba.validate_bundle`
  - `ba.run_pipeline`
  - `ba.rerun_impacted`
- `src/notebooklm_mcp/ba/adapter.py` is the seam between the BA subsystem and `NotebookLMClient`, which confirms that BA is not just documentation or tests. It is implemented code with a real runtime boundary.
- The BA runner also owns persisted run-store and fixture contracts under `docs/features/<feature_key>/`, which means the repository already carries BA-specific output vocabulary and maintenance weight.

### Docs And User-Facing Promises

- `README.md` currently markets MCP as a shipped product surface:
  - install instructions for `pip install "notebooklm-py[mcp,browser]"`
  - `notebooklm-mcp serve` quickstart
  - transport mode table
  - HTTP config details
  - Claude Desktop config example
  - BA Runner Quickstart with `ba.run_pipeline`
- `docs/mcp-tools.md` is marked `Status: Active` and documents both generic `notebooklm_*` tools and the `ba.*` tool family as active server behavior.
- `docs/mcp-claude-desktop.md` is an active setup guide for connecting Claude Desktop to `notebooklm_mcp`.
- Runnable examples currently reinforce MCP as a live surface:
  - `docs/examples/ba-runner-mcp-flow.py`
  - `docs/examples/openai-agents-example.py`
  - `docs/examples/claude-desktop-config.json`
- There is also a wider BA documentation footprint under `docs/ba-*.md` describing BA workflow behavior, subsystem boundaries, rerun fixtures, and output contracts. Even if some of that material becomes historical or contributor-only, it should move under the same legacy boundary instead of continuing to read like active MVP product truth.
- BA evaluation and hardening docs already exist as first-class artifacts too, for example:
  - `docs/ba-metrics-and-evaluation.md`
  - `docs/ba-upstream-canaries.md`

### Tests And Fixtures That Still Encode Active Support

- Current inventory:
  - `tests/unit/test_mcp*.py`: 26 files
  - `tests/unit/test_ba*.py`: 33 files
  - `tests/integration/test_mcp_integration.py`: 1 integration flow
  - `tests/fixtures/ba/**`: 61 fixture files
- Those suites are valuable, but they also mean the repo still treats MCP and BA as first-class maintained surfaces unless phase-1 explicitly narrows default expectations.
- `tests/integration/test_mcp_integration.py` exercises real MCP handler flows against VCR/live NotebookLM traffic, which is much stronger than a dormant code path.
- The BA unit inventory already includes canary and metrics expectations, so the frozen surface is not just feature code. It also carries evaluation and regression machinery.

## Recommended Legacy Boundary

### Mainline MVP Statement

- Mainline MVP work should not promise `notebooklm-mcp`, `src/notebooklm_mcp/**`, or `ba.*` behavior as part of the active CLI/SDK contract.
- MCP and BA code may remain in-tree as legacy or frozen implementation stock, but later CLI/SDK pruning beads should not be blocked on preserving that separate product surface.
- This note is the canonical boundary reference for the `LEGACY/FROZEN` MCP and BA rows in the pruning contract and pruning plan.

### What Phase-1 Should Freeze

- BA runner semantics, docs, examples, and tests should be treated as belonging to a legacy MCP branch of the product story, not to the active MVP CLI/SDK story.
- The generic MCP server, resources, prompts, tool registry, and `notebooklm-mcp` entry point should follow the same rule immediately after the BA-specific boundary is stated.

### What Phase-1 Should Not Do

- Do not delete MCP or BA code just because it is out of MVP scope.
- Do not silently leave packaging, README copy, examples, or tests advertising those surfaces as active.
- Do not force phase-2 or phase-3 beads to preserve MCP/BA parity implicitly while the mainline product is being shrunk elsewhere.

## Ownership And Re-Entry Notes

### Ownership While Frozen

- Mainline MVP pruning beads own only the boundary management work:
  - freeze labels
  - doc links
  - package/help/test truthfulness
  - import-preserving safety fixes if the legacy surface would otherwise break unrelated work
- Mainline MVP pruning beads do not own new BA workflow scope, BA parity expansion, or BA redesign.
- Any behavior-changing BA work should be tracked in a dedicated MCP/BA lane, not piggybacked into the CLI/SDK pruning stream. The existing `bd-yae.*` lineage is the obvious historical anchor unless a successor epic replaces it.

### Re-Entry Criteria

- Re-entry must happen through an explicit follow-up bead or epic that says MCP or BA is back in active scope.
- Re-entry is not complete until all of the following are true again:
  - packaging and entry points intentionally ship the surface
  - README and docs describe it as active product behavior
  - examples are restored or refreshed
  - tests and fixtures return to the default maintained expectation set
  - the owning workstream states what regression bar now applies
- Until those conditions are met, code may remain in-tree, but it should still be treated as `LEGACY/FROZEN` rather than silently half-supported.

## Sequencing Implications For The Existing Beads

- `bd-27n.2.1`: freeze the BA subsystem and BA-facing docs/tests as a documented legacy surface.
- `bd-27n.2.2`: freeze the remaining generic MCP surface and `notebooklm-mcp` entry point behind the same boundary.
- `bd-27n.2.3`: align `pyproject.toml`, README, docs, examples, and test expectations so the branch stops advertising MCP and BA as active MVP behavior.

## Immediate Implementation Targets For Phase-1

The items below are now explicit fallout for `bd-27n.2.3`, not hidden acceptance criteria that later CLI/SDK pruning beads should rediscover by accident.

### Packaging

- `pyproject.toml`
  - `project.scripts.notebooklm-mcp`
  - `project.optional-dependencies.mcp`
  - package discovery for `notebooklm_mcp*`
  - keywords or metadata that still imply active MCP scope

### Docs

- `README.md`
- `docs/mcp-tools.md`
- `docs/mcp-claude-desktop.md`
- `docs/examples/ba-runner-mcp-flow.py`
- `docs/examples/openai-agents-example.py`
- BA workflow and contributor docs under `docs/ba-*.md`

### Tests

- `tests/unit/test_mcp*.py`
- `tests/unit/test_ba*.py`
- `tests/integration/test_mcp_integration.py`
- `tests/fixtures/ba/**`

## Bottom Line

The repository is already structurally split in the right direction: core CLI/SDK in `src/notebooklm/**`, optional MCP server in `src/notebooklm_mcp/**`, and a larger BA runner nested under `src/notebooklm_mcp/ba/**`. The missing step is not another architectural invention. It is making the product boundary honest everywhere the repo currently says MCP and BA are active.
