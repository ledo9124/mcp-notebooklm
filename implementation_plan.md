# Clean Source Base: Xoá MCP/BA Legacy khỏi branch `notebooklm_cli`

Mục tiêu: biến branch thành **clean product base** cho NotebookLM CLI + Python SDK, loại bỏ hoàn toàn MCP server, BA runner, docs archive, và migration papers.

## Phạm vi tổng quan

| Nhóm | Hành động | Số file ảnh hưởng |
|------|-----------|-------------------|
| Source code MCP/BA | **DELETE** toàn bộ `src/notebooklm_mcp/` | ~50 files |
| Docs MCP/BA/Pruning | **DELETE** docs legacy | ~25 files |
| Top-level migration papers | **DELETE** | 2 files |
| Tests MCP/BA | **DELETE** unit + integration tests MCP/BA | ~52 files |
| Test fixtures BA | **DELETE** `tests/fixtures/ba/` | ~18 files |
| README.md | **MODIFY** — xoá legacy sections | 1 file |
| pyproject.toml | **MODIFY** — xoá exclude rule | 1 file |
| tests/conftest.py | **MODIFY** — xoá legacy ignore patterns | 1 file |
| .env.example | **MODIFY** — xoá MCP env vars | 1 file |

---

## Vòng 1 — DELETE: Source Code MCP/BA

### [DELETE] [notebooklm_mcp/](file:///home/lemin/flywheel/projects/notebooklm-py/src/notebooklm_mcp)

Xoá toàn bộ thư mục `src/notebooklm_mcp/` bao gồm:

| Thư mục con | Nội dung | Files |
|-------------|----------|-------|
| `src/notebooklm_mcp/` (root) | MCP server, config, cache, errors, mapping, stats, tokens, prompts, resources | 14 files |
| `src/notebooklm_mcp/ba/` | BA runner: adapter, pipeline, models, rendering, extraction, metrics, contracts, v.v. | 24 files |
| `src/notebooklm_mcp/tools/` | MCP tools: artifacts, chat, notebooks, notes, ops, sources, workflows, v.v. | 12 files |

**Lệnh:**
```bash
rm -rf src/notebooklm_mcp/
```

---

## Vòng 2 — DELETE: Docs Legacy

### 2a. Docs BA (`docs/ba-*.md`)

| File | Mô tả |
|------|--------|
| [ba-contributor-guide.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-contributor-guide.md) | BA contributor workflow |
| [ba-docs-source-map.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-docs-source-map.md) | BA documentation source map |
| [ba-golden-file-maintenance.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-golden-file-maintenance.md) | BA golden file maintenance |
| [ba-metrics-and-evaluation.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-metrics-and-evaluation.md) | BA metrics and evaluation |
| [ba-output-bundle-contract.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-output-bundle-contract.md) | BA output bundle contract |
| [ba-phase0-architecture-seams.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-phase0-architecture-seams.md) | BA Phase 0 architecture seams |
| [ba-phase0-capability-parity-matrix.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-phase0-capability-parity-matrix.md) | BA Phase 0 capability parity |
| [ba-phase0-contract-seeds.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-phase0-contract-seeds.md) | BA Phase 0 contract seeds |
| [ba-phase0-run-store-seed.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-phase0-run-store-seed.md) | BA Phase 0 run store seed |
| [ba-rerun-fixture-contract.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-rerun-fixture-contract.md) | BA rerun fixture contract |
| [ba-runner-parity-audit.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-runner-parity-audit.md) | BA runner parity audit |
| [ba-safe-repairs.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-safe-repairs.md) | BA safe repairs |
| [ba-subsystem-boundaries.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-subsystem-boundaries.md) | BA subsystem boundaries |
| [ba-upstream-canaries.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-upstream-canaries.md) | BA upstream canaries |
| [ba-workflow-guide.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/ba-workflow-guide.md) | BA workflow guide |

### 2b. Docs MCP

| File | Mô tả |
|------|--------|
| [mcp-tools.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/mcp-tools.md) | MCP tool reference |
| [mcp-claude-desktop.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/mcp-claude-desktop.md) | Claude Desktop MCP setup |

### 2c. Docs MVP-Pruning (migration/transition papers)

| File | Mô tả |
|------|--------|
| [mvp-pruning-contract.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/mvp-pruning-contract.md) | MVP pruning contract |
| [mvp-pruning-deferred-module-disposition.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/mvp-pruning-deferred-module-disposition.md) | Deferred module disposition |
| [mvp-pruning-mcp-ba-boundary.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/mvp-pruning-mcp-ba-boundary.md) | MCP/BA boundary inventory |
| [mvp-pruning-package-api-strategy.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/mvp-pruning-package-api-strategy.md) | Package API strategy |
| [mvp-pruning-verification.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/mvp-pruning-verification.md) | Pruning verification |

### 2d. Docs chuyển đổi MCP→CLI

| Path | Mô tả |
|------|--------|
| [convert-from-mcp-to-cli/](file:///home/lemin/flywheel/projects/notebooklm-py/docs/features/convert-from-mcp-to-cli) | 9 migration artifacts (JSON, MD) |

### 2e. Docs Legacy khác

| File | Mô tả |
|------|--------|
| [chat-settings-manual-checklist.md](file:///home/lemin/flywheel/projects/notebooklm-py/docs/chat-settings-manual-checklist.md) | Marked "legacy/frozen" in header |

### 2f. Examples MCP/BA trong `docs/examples/`

| File | Hành động |
|------|-----------|
| [ba-runner-mcp-flow.py](file:///home/lemin/flywheel/projects/notebooklm-py/docs/examples/ba-runner-mcp-flow.py) | **DELETE** — BA/MCP example |
| [openai-agents-example.py](file:///home/lemin/flywheel/projects/notebooklm-py/docs/examples/openai-agents-example.py) | **DELETE** — MCP-based agent example |
| [claude-desktop-config.json](file:///home/lemin/flywheel/projects/notebooklm-py/docs/examples/claude-desktop-config.json) | **DELETE** — MCP config for Claude Desktop |

> [!NOTE]
> Giữ lại các example thuần CLI/SDK: `bulk-import.py`, `chat.py`, `notes.py`, `quickstart.py`, `research-to-podcast.py`, `video.py`

**Lệnh tổng hợp vòng 2:**
```bash
# BA docs
rm docs/ba-*.md

# MCP docs
rm docs/mcp-tools.md docs/mcp-claude-desktop.md

# MVP pruning docs
rm docs/mvp-pruning-*.md

# Convert feature docs
rm -rf docs/features/convert-from-mcp-to-cli/

# Legacy checklist
rm docs/chat-settings-manual-checklist.md

# MCP/BA examples
rm docs/examples/ba-runner-mcp-flow.py
rm docs/examples/openai-agents-example.py
rm docs/examples/claude-desktop-config.json
```

> [!IMPORTANT]
> Nếu `docs/features/` trở thành rỗng sau khi xoá `convert-from-mcp-to-cli/`, xoá luôn thư mục `docs/features/`.

---

## Vòng 3 — DELETE: Top-level Migration Papers

| File | Mô tả |
|------|--------|
| [PRUNING_PLAN.md](file:///home/lemin/flywheel/projects/notebooklm-py/PRUNING_PLAN.md) | Pruning roadmap |
| [notebooklm_mcp_upgrade_plan_revised.md](file:///home/lemin/flywheel/projects/notebooklm-py/notebooklm_mcp_upgrade_plan_revised.md) | MCP upgrade plan (61 KB) |

```bash
rm PRUNING_PLAN.md notebooklm_mcp_upgrade_plan_revised.md
```

---

## Vòng 4 — DELETE: Tests MCP/BA

### 4a. Unit tests BA (34 files)

Toàn bộ `tests/unit/test_ba*.py`:

```
test_ba_adapter.py          test_ba_fixture_loaders.py    test_ba_pipeline.py
test_ba_bundle_rendering.py test_ba_fixture_scenarios.py   test_ba_pipeline_contracts.py
test_ba_canaries.py         test_ba_gaps.py                test_ba_prompts.py
test_ba_canonical.py        test_ba_manifest_registration.py test_ba_readiness.py
test_ba_change_detection.py test_ba_matrices.py            test_ba_rendering.py
test_ba_contracts.py        test_ba_metrics.py             test_ba_rerun_fixtures.py
test_ba_evidence.py         test_ba_mock_data_alignment.py test_ba_reruns.py
                            test_ba_models.py              test_ba_run_store.py
                            test_ba_package_skeleton.py    test_ba_screen_catalog.py
test_ba_source_registration.py  test_ba_source_snapshots.py
test_ba_state_machine.py    test_ba_terminology.py
test_ba_tool_contracts.py   test_ba_tools.py
test_ba_traceability.py     test_ba_validation.py
```

### 4b. Unit tests MCP (17 files)

Toàn bộ `tests/unit/test_mcp*.py`:

```
test_mcp_audit.py           test_mcp_mapping.py           test_mcp_tools_artifacts.py
test_mcp_ba_tool_contracts.py test_mcp_prompts.py          test_mcp_tools_chat.py
test_mcp_cache.py           test_mcp_resources.py          test_mcp_tools_chat_settings.py
test_mcp_config.py          test_mcp_result.py             test_mcp_tools_experimental_artifacts.py
test_mcp_errors.py          test_mcp_server.py             test_mcp_tools_mind_maps.py
test_mcp_fingerprint.py     test_mcp_smoke.py              test_mcp_tools_notebooks.py
test_mcp_main.py            test_mcp_stats.py              test_mcp_tools_notes.py
                            test_mcp_tokens.py             test_mcp_tools_ops.py
                                                           test_mcp_tools_settings.py
                                                           test_mcp_tools_sources.py
                                                           test_mcp_tools_workflows.py
```

### 4c. Integration test MCP

| File | Mô tả |
|------|--------|
| [test_mcp_integration.py](file:///home/lemin/flywheel/projects/notebooklm-py/tests/integration/test_mcp_integration.py) | MCP integration test |

### 4d. Test fixtures BA

| Path | Mô tả |
|------|--------|
| [tests/fixtures/ba/](file:///home/lemin/flywheel/projects/notebooklm-py/tests/fixtures/ba) | BA fixture data: 9 files + 7 subdirs + `runs/` + `screens/` |

**Lệnh tổng hợp vòng 4:**
```bash
# BA unit tests
rm tests/unit/test_ba*.py

# MCP unit tests
rm tests/unit/test_mcp*.py

# MCP integration test
rm tests/integration/test_mcp_integration.py

# BA fixtures
rm -rf tests/fixtures/ba/
```

> [!IMPORTANT]
> Nếu `tests/fixtures/` trở thành rỗng sau khi xoá `ba/`, xoá luôn thư mục `tests/fixtures/`.

---

## Vòng 5 — MODIFY: Cập nhật các file còn lại

### [MODIFY] [README.md](file:///home/lemin/flywheel/projects/notebooklm-py/README.md)

Xoá 2 section legacy (dòng 121–175):

```diff
-## Legacy/Frozen MCP Surface
-
-`src/notebooklm_mcp/**` and `src/notebooklm_mcp/ba/**` remain in the repository ...
-...
-Legacy/frozen MCP references:
-- [MCP/BA Boundary Inventory](docs/mvp-pruning-mcp-ba-boundary.md)
-- [MCP Tool Reference](docs/mcp-tools.md)
-- [Claude Desktop MCP Setup](docs/mcp-claude-desktop.md)
-- [BA Runner MCP Flow](docs/examples/ba-runner-mcp-flow.py)
-- [OpenAI Agents SDK MCP Example](docs/examples/openai-agents-example.py)
```

Cụ thể xoá:
1. **Dòng 121–137**: Section "Legacy/Frozen MCP Surface" + AGENTS.md reference
2. **Dòng 169–175** (cuối file): Block "Legacy/frozen MCP references"

---

### [MODIFY] [pyproject.toml](file:///home/lemin/flywheel/projects/notebooklm-py/pyproject.toml)

Xoá exclude rule không còn cần thiết (dòng 78):

```diff
 [tool.setuptools.packages.find]
 where = ["src"]
 include = ["notebooklm*"]
-exclude = ["notebooklm_mcp*"]
```

---

### [MODIFY] [tests/conftest.py](file:///home/lemin/flywheel/projects/notebooklm-py/tests/conftest.py)

Xoá legacy MCP test infrastructure (dòng 10–25):

```diff
-LEGACY_MCP_TEST_PATTERNS = (
-    "tests/unit/test_mcp*.py",
-    "tests/unit/test_ba*.py",
-    "tests/integration/test_mcp_integration.py",
-    "unit/test_mcp*.py",
-    "unit/test_ba*.py",
-    "integration/test_mcp_integration.py",
-)
-
-
-def _legacy_mcp_tests_enabled() -> bool:
-    """Return True when the frozen MCP/BA test surface is explicitly enabled."""
-    return os.getenv("NOTEBOOKLM_ENABLE_LEGACY_MCP_TESTS") == "1"
-
-
-collect_ignore_glob = [] if _legacy_mcp_tests_enabled() else list(LEGACY_MCP_TEST_PATTERNS)
```

Sau khi xoá, cũng xoá `import os` nếu không còn sử dụng ở nơi khác trong file.

---

### [MODIFY] [.env.example](file:///home/lemin/flywheel/projects/notebooklm-py/.env.example)

Xoá MCP env vars (dòng 20–24):

```diff
-# MCP server HTTP bind settings (optional, used by streamable-http and sse transports)
-# Defaults: NOTEBOOKLM_MCP_HOST=127.0.0.1, NOTEBOOKLM_MCP_PORT=8764
-
-# NOTEBOOKLM_MCP_HOST=127.0.0.1
-# NOTEBOOKLM_MCP_PORT=8764
```

---

## Quyết định cần User review

> [!WARNING]
> **`src/notebooklm_py.egg-info/`** — Đây là build artifact, không phải legacy code. Nên thêm vào `.gitignore` nếu chưa có, hoặc xoá khỏi tracking.

---

## Danh sách file GIỮ LẠI (docs active)

Sau cleanup, `docs/` chỉ còn:

| File | Vai trò |
|------|---------|
| `cli-reference.md` | CLI reference cho active product |
| `configuration.md` | Configuration guide |
| `development.md` | Development guide |
| `project-overview.md` | Project overview |
| `python-api.md` | Python API reference |
| `releasing.md` | Release checklist |
| `rpc-development.md` | RPC development guide |
| `rpc-reference.md` | RPC reference |
| `stability.md` | API stability policy |
| `troubleshooting.md` | Troubleshooting guide |
| `examples/` | Active examples: `bulk-import.py`, `chat.py`, `notes.py`, `quickstart.py`, `research-to-podcast.py`, `video.py` |

---

## Verification Plan

### Automated Tests

Sau khi xoá xong, chạy test suite để đảm bảo không broken reference:

```bash
# 1. Chạy toàn bộ test suite (chỉ còn active tests)
cd /home/lemin/flywheel/projects/notebooklm-py
pytest tests/ -x --timeout=60 2>&1 | head -50

# 2. Verify rằng không còn import nào trỏ đến notebooklm_mcp
grep -r "notebooklm_mcp" src/ tests/ --include="*.py"

# 3. Verify không còn broken doc links trong README
grep -oP '\(docs/[^)]+\)' README.md | while read link; do
  path="${link:1:-1}"
  [ ! -e "$path" ] && echo "BROKEN: $path"
done

# 4. Verify package build vẫn OK
python -m build --sdist --no-isolation 2>&1 | tail -5

# 5. Verify example scripts syntax
python -m py_compile docs/examples/bulk-import.py
python -m py_compile docs/examples/chat.py
python -m py_compile docs/examples/quickstart.py
python -m py_compile docs/examples/research-to-podcast.py
python -m py_compile docs/examples/video.py
python -m py_compile docs/examples/notes.py
```

### Manual Verification

- Review `git diff --stat` để xác nhận chỉ xoá đúng các file legacy, không xoá nhầm file active
- Kiểm tra `git status` để xác nhận không còn untracked file MCP/BA
