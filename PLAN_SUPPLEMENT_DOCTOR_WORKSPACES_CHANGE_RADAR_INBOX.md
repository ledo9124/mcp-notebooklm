# Kế hoạch bổ sung chi tiết cho 4 năng lực ưu tiên
## Doctor · Workspaces · Change Radar · Research Inbox

Ngày chốt: 2026-03-14

## 1) Tóm tắt điều hành

Bốn ý tưởng này không nên được triển khai như bốn feature rời rạc. Chúng hợp thành một vòng lặp agent-first hoàn chỉnh:

1. **Doctor** giữ hệ thống ở trạng thái tin cậy, tự chẩn đoán được, có thể tự sửa các lỗi đơn giản và tạo support bundle sạch để debug các lỗi khó.
2. **Workspaces** mở rộng phạm vi reasoning bằng cách tạo ra “virtual notebooks” ở tầng orchestration, bù lại giới hạn hiện tại của NotebookLM là mỗi notebook tách biệt và không truy cập đồng thời nhiều notebook.
3. **Change Radar** giữ tri thức luôn tươi vì nguồn trong NotebookLM chủ yếu là snapshot tĩnh; Google files cần re-sync thủ công và nhiều loại source khác cần xóa rồi import lại khi nội dung gốc thay đổi.
4. **Research Inbox** là cổng kiểm duyệt tri thức vào hệ thống: mọi kết quả Discover/Fast Research/Deep Research, mọi đề xuất mới từ Change Radar và mọi source do agent đề xuất đều đi qua triage + approval trước khi làm biến đổi notebook.

Nếu triển khai đúng, bốn năng lực này sẽ biến hệ thống từ “CLI gọi NotebookLM” thành một **research operating system** nhỏ gọn:
- tự quan sát được,
- có memory + approval boundary,
- mở rộng tốt cho agent,
- và đặc biệt là **giữ chất lượng tri thức tốt hơn khi quy mô notebook tăng lên**.

---

## 2) Cơ sở thiết kế

### 2.1. Điều kiện thực tế từ NotebookLM

NotebookLM hiện có ba đặc tính rất quan trọng:

- **Mỗi notebook là độc lập**; NotebookLM không truy cập đồng thời nhiều notebook cùng lúc. Đây là lý do chính để xây lớp Workspaces ở phía ngoài NotebookLM. [S1]
- **Source trong NotebookLM phần lớn là bản copy tĩnh**. Với Google Drive files, NotebookLM không tự theo dõi thay đổi; người dùng phải re-sync thủ công. Với nhiều loại source khác, phải xóa và upload/import lại. Đây là lý do mạnh nhất cho Change Radar. [S2]
- **Fast Research / Deep Research đã có mô hình review-then-import**. Người dùng xem kết quả trước, chọn gì thì import cái đó; các kết quả Deep Research không import sẽ bị bỏ đi. Đây là nền tảng hoàn hảo cho Research Inbox thay vì import thẳng. [S2][S5]

Ngoài ra:
- Chat của NotebookLM chỉ dùng dữ liệu từ sources và có khả năng include/exclude sources trong notebook khi trả lời. [S3]
- Discover Sources và Deep Research cho thấy NotebookLM đang chuyển mạnh theo hướng tìm nguồn, tổng hợp nguồn và tạo report từ nguồn. [S4][S5]
- Google cũng đang đẩy notebook thành một “context object” tái sử dụng được ở Gemini. [S6]

### 2.2. Điều kiện thực tế từ Agents SDK và Agent Flywheel

Từ Agents SDK, bốn primitive quan trọng nhất cho addendum này là:
- **sessions** để giữ working context,
- **handoffs** để biểu diễn specialist routing như tools,
- **human-in-the-loop** để pause/resume khi cần approval,
- **tracing** và **guardrails** để giải thích được hành vi và chặn các hành động nhạy cảm. [S7][S8][S9][S10][S11]

Từ Agent Flywheel, những pattern nên vay là:
- **mail/leases/audit mindset** từ Agent Mail,
- **cross-session memory/search** từ CASS,
- **profile isolation** từ CAAM,
- **destructive-action guard + two-person approval** từ DCG và SLB,
- **manifest là single source of truth** và **doctor checks** từ ACFS. [S12][S13][S14][S15][S16][S17][S18]

Điểm quan trọng: vay **pattern**, không kéo cả stack vào làm dependency.

---

## 3) Mục tiêu của addendum này

Bản bổ sung này có 5 mục tiêu:

1. Biến 4 ý tưởng trên thành một **plan có thể triển khai tuần tự**.
2. Giữ đúng triết lý agent-first đã chốt: deterministic tools > prompt magic, structured commands > NL routing.
3. Tránh thêm complexity không đáng giá:
   - không thêm background service bắt buộc ở MVP,
   - không thêm dependency nặng từ hệ flywheel,
   - không biến Workspaces thành object server-side mới trong NotebookLM.
4. Tận dụng tối đa các đường ray sẵn có của NotebookLM:
   - notebooks,
   - sources,
   - reports,
   - Discover/Fast Research,
   - Deep Research,
   - sharing/public notebooks,
   - notes → source.
5. Tạo nền tảng cho các feature sau này như publish packs, gap analysis, enterprise workflows, scheduled research.

---

## 4) Các quyết định thiết kế chốt

### 4.1. Quyết định chung

- Không tạo package top-level mới.
- Giữ nguyên triết lý: browser chỉ dùng cho login/recovery; runtime chính vẫn là HTTP.
- Giữ `NOTEBOOKLM_HOME` là gốc local state.
- Dùng **SQLite** làm local control plane.
- Mọi command quan trọng đều có `--json`.
- Mọi mutation đáng kể đều phải có:
  - `--dry-run` nếu hợp lý,
  - `explain`,
  - risk tier,
  - approval policy.

### 4.2. Các non-goal của addendum

Ở giai đoạn này, **không làm**:

- Cross-profile workspaces.
- Auto-delete source mà không có policy explicit.
- Full embedding stack bắt buộc cho workspace routing; ưu tiên SQLite FTS/BM25 trước.
- Background daemon luôn chạy. Scheduler có thể được kích bởi lệnh CLI, poll loop tùy chọn hoặc host agent.
- UI riêng kiểu web dashboard lớn. Mọi thứ phải usable từ CLI + JSON trước.

---

## 5) Cách 4 feature khớp với nhau

### 5.1. Luồng lớn

```text
User/Agent action
-> Router
-> Workspace resolution (nếu có)
-> Doctor gating (nếu health kém hoặc policy yêu cầu)
-> Execution
-> Change detected? -> Change Radar
-> Candidate inflow -> Research Inbox
-> Approval decision
-> Mutation/import/sync
-> Trace + memory write-back
```

### 5.2. Vai trò của từng feature

- **Doctor**: kiểm tra “hệ thống có đủ khỏe để tin cậy thao tác này không?”
- **Workspaces**: quyết định “nên reasoning trên tập notebook nào?”
- **Change Radar**: phát hiện “tri thức nào đã cũ hoặc đang thay đổi?”
- **Research Inbox**: quyết định “thứ gì được phép đi vào notebook/workspace?”

### 5.3. Một quy tắc quan trọng

**Không có source mới hoặc change lớn nào được nhập âm thầm vào notebook mặc định.**

Mọi thay đổi material mặc định đi vào inbox trước, trừ khi notebook/workspace policy cho phép auto-apply một số loại thay đổi low-risk.

---

## 6) Kiến trúc chung cho addendum

## 6.1. Module layout đề xuất

```text
src/notebooklm/
  doctor/
    checks.py
    engine.py
    repairs.py
    bundle.py
    schemas.py

  workspaces/
    models.py
    repository.py
    index.py
    resolver.py
    planner.py
    execute.py
    synthesize.py

  radar/
    models.py
    scheduler.py
    adapters/
      drive.py
      web.py
      local_file.py
      youtube.py
      deep_research.py
    detect.py
    diff.py
    briefings.py

  inbox/
    models.py
    repository.py
    scoring.py
    dedupe.py
    triage.py
    approvals.py
    apply.py

  approvals/
    engine.py
    policies.py
    interruptions.py

  leases/
    manager.py

  observability/
    events.py
    traces.py
    support_bundle.py

  contracts/
    capabilities.yaml
    doctor_checks.yaml
    risk_policies.yaml
```

## 6.2. Shared primitives

Bốn feature dùng chung các primitive sau:

- `trace_id`
- `approval_id`
- `lease_id`
- `profile_id`
- `notebook_fingerprint`
- `workspace_fingerprint`
- `source_revision_fingerprint`

### 6.3. Event model chung

Mọi feature cần phát event chuẩn hóa:

- `doctor.run.started`
- `doctor.check.completed`
- `doctor.repair.completed`
- `workspace.resolve.completed`
- `workspace.query.completed`
- `watch.run.completed`
- `change.detected`
- `delta.briefing.created`
- `inbox.item.created`
- `approval.requested`
- `approval.resolved`
- `inbox.item.applied`

Event này phục vụ:
- tracing,
- audit,
- memory/search,
- support bundle,
- external agent hosts.

---

## 7) Data model bổ sung

## 7.1. Doctor

### `doctor_runs`
- `id`
- `trace_id`
- `mode` (`fast`, `deep`)
- `started_at`
- `ended_at`
- `overall_status` (`healthy`, `degraded`, `broken`)
- `summary_json`

### `doctor_findings`
- `id`
- `run_id`
- `check_key`
- `severity` (`info`, `warn`, `error`, `critical`)
- `status` (`pass`, `fail`, `skipped`)
- `repairable` (`bool`)
- `message`
- `data_json`

### `doctor_repairs`
- `id`
- `finding_id`
- `repair_action`
- `status`
- `started_at`
- `ended_at`
- `result_json`

### `support_bundles`
- `id`
- `created_at`
- `path`
- `redaction_profile`
- `contents_json`

## 7.2. Workspaces

### `workspaces`
- `id`
- `profile_id`
- `name`
- `slug`
- `description`
- `kind` (`static`, `rule_based`)
- `query_policy_json`
- `approval_policy_json`
- `created_at`
- `updated_at`

### `workspace_members`
- `id`
- `workspace_id`
- `notebook_id`
- `priority`
- `tags_json`
- `enabled`
- `added_at`

### `workspace_rules`
- `id`
- `workspace_id`
- `rule_type`
- `rule_json`

### `workspace_runs`
- `id`
- `workspace_id`
- `trace_id`
- `mode` (`metadata`, `ask`, `overview`, `compare`)
- `query_text`
- `selected_notebooks_json`
- `plan_json`
- `result_json`
- `created_at`

### `workspace_index_entries`
Materialized FTS/BM25 index over notebook titles, notebook summaries, source titles, source snippets, tags.

## 7.3. Change Radar

### `watches`
- `id`
- `profile_id`
- `scope_type` (`source`, `notebook`, `workspace`, `research_query`)
- `scope_id`
- `watch_kind` (`drive_sync`, `web_diff`, `local_file_hash`, `deep_research`)
- `policy_json`
- `status`
- `schedule_json`
- `next_run_at`
- `last_run_at`

### `watch_runs`
- `id`
- `watch_id`
- `trace_id`
- `started_at`
- `ended_at`
- `status`
- `signature_before`
- `signature_after`
- `result_json`

### `source_revisions`
- `id`
- `source_id`
- `revision_key`
- `content_hash`
- `etag`
- `last_modified`
- `fetched_at`
- `metadata_json`

### `change_events`
- `id`
- `watch_id`
- `source_id`
- `notebook_id`
- `workspace_id`
- `change_kind`
- `severity`
- `state` (`new`, `briefed`, `queued_inbox`, `ignored`, `applied`)
- `created_at`
- `data_json`

### `delta_briefings`
- `id`
- `change_event_id`
- `summary_md`
- `impact_json`
- `recommended_actions_json`
- `created_at`

## 7.4. Research Inbox

### `inbox_items`
- `id`
- `profile_id`
- `notebook_id`
- `workspace_id`
- `origin` (`fast_research`, `deep_research`, `change_radar`, `manual`, `agent_proposal`)
- `kind` (`source`, `report`, `replacement`, `resync`)
- `state` (`pending`, `approved`, `rejected`, `deferred`, `applied`, `expired`)
- `priority`
- `novelty_score`
- `relevance_score`
- `trust_score`
- `approval_required`
- `title`
- `canonical_uri`
- `snippet`
- `rationale_json`
- `created_at`
- `decision_at`

### `inbox_clusters`
- `id`
- `fingerprint`
- `canonical_uri`
- `representative_item_id`

### `approval_requests`
- `id`
- `entity_type`
- `entity_id`
- `policy_name`
- `status`
- `requested_at`
- `resolved_at`
- `decision_json`

## 7.5. Shared concurrency primitive

### `leases`
- `id`
- `scope_type` (`profile`, `notebook`, `workspace`, `watch`, `inbox_item`)
- `scope_id`
- `holder`
- `purpose`
- `advisory`
- `acquired_at`
- `expires_at`

---

## 8) Feature 1 — Doctor

## 8.1. Mục tiêu

Doctor là “system health + explain + repair” của toàn bộ control plane. Nó phải trả lời được ba câu hỏi:

1. Hệ thống hiện có **đủ tin cậy để chạy** hay không?
2. Nếu có lỗi, **lỗi nằm ở đâu**?
3. Có thể **tự sửa** những gì một cách an toàn?

### Kết quả người dùng nhận được

- Chạy `doctor` ra chẩn đoán rõ, ngắn, actionable.
- Chạy `doctor --deep` ra đầy đủ trace, dependency checks, remote probes, DB integrity.
- Chạy `doctor fix` tự sửa được phần lớn lỗi đơn giản.
- Chạy `doctor bundle` tạo gói debug đã redacted.

## 8.2. Vì sao feature này đáng làm trước

Khi thêm Workspaces, Change Radar, Inbox, hệ thống sẽ có:
- nhiều state hơn,
- nhiều mutation path hơn,
- nhiều điểm thất bại hơn,
- nhiều vấn đề race/concurrency hơn.

Nếu không có Doctor, support burden sẽ tăng rất nhanh và người dùng sẽ mất niềm tin khi “thỉnh thoảng nó bị kẹt” nhưng không biết tại sao.

## 8.3. Phạm vi của Doctor

### Fast mode (`notebooklm doctor`)
Mục tiêu: hoàn thành nhanh và trả verdict rõ.

Nhóm check:
- config/schema valid,
- DB mở được,
- migrations up-to-date,
- active profile hợp lệ,
- storage paths tồn tại,
- auth snapshot có đủ trường tối thiểu,
- `bl` hiện diện,
- orphan leases,
- stuck tasks,
- pending approval quá hạn,
- backlog radar/inbox vượt ngưỡng,
- workspace definitions invalid.

### Deep mode (`notebooklm doctor --deep`)
Thêm:
- remote auth probe,
- homepage token refresh probe,
- RPC canary,
- cache integrity,
- FTS health,
- foreign key integrity,
- revision/watch drift,
- repeated 401/403/429 patterns,
- unsupported feature path detection,
- trace sampler output,
- performance anomalies.

## 8.4. Catalog check đề xuất

### Auth/transport
- cookies present
- csrf present
- `f.sid` present
- `bl` present
- homepage parse success
- remote canary success
- auth refresh works
- rate-limit state healthy

### Local DB
- schema version
- pragma integrity check
- WAL/locking health
- orphan records
- FTS index freshness
- oversized tables
- unbounded logs

### Workspaces
- unknown notebook refs
- duplicate notebook membership
- stale index entries
- invalid rules
- conflicting policies

### Radar
- due watches count
- consecutive failures
- invalid watch adapters
- signature calculation errors
- excessive diff noise

### Inbox
- duplicate pending items
- broken dedupe clusters
- approval items dangling
- apply failures
- import retries exceeded

## 8.5. Repair actions

Doctor chỉ tự sửa những thứ có thể **idempotent + low-risk**:

- refresh auth snapshot,
- rebuild workspace index,
- rebuild FTS tables,
- clear expired leases,
- retry stuck watch run,
- prune orphan approval rows,
- vacuum/analyze DB,
- mark dead pending task as failed,
- resync notebook metadata,
- rotate/redact logs for bundle.

Các repair **không nên auto-run**:
- xóa notebook,
- xóa source,
- reset profile hoàn toàn,
- auto-import candidate sources,
- auto-replace source có nội dung thay đổi material.

## 8.6. Support bundle

`doctor bundle` tạo một artifact chứa:

- manifest/capabilities version,
- OS/Python/package versions,
- config đã redacted,
- profile metadata (không chứa secret),
- auth fingerprints (không chứa cookie raw),
- recent doctor findings,
- recent traces/events,
- recent watch failures,
- recent inbox/apply failures,
- DB stats,
- selected logs.

### Redaction rules
- không bao giờ chứa raw cookies,
- không chứa source body đầy đủ mặc định,
- không chứa raw prompt nếu user đánh dấu private,
- URI/query strings có thể hash một phần.

## 8.7. Command surface

```bash
notebooklm doctor
notebooklm doctor --deep
notebooklm doctor --json
notebooklm doctor check auth
notebooklm doctor check db
notebooklm doctor fix
notebooklm doctor fix --check auth
notebooklm doctor bundle
```

## 8.8. JSON envelope đề xuất

```json
{
  "ok": false,
  "status": "degraded",
  "trace_id": "trc_...",
  "summary": {
    "passed": 18,
    "failed": 2,
    "repairable": 1
  },
  "findings": [
    {
      "check": "auth.bl_present",
      "severity": "critical",
      "status": "fail",
      "repairable": true,
      "message": "Session snapshot is missing build_label",
      "suggested_action": "doctor fix --check auth"
    }
  ],
  "repairs": [],
  "next_steps": [
    "Run doctor fix --check auth",
    "Retry notebooklm auth check --test"
  ]
}
```

## 8.9. Rollout

### D1
- `doctor` fast mode
- basic checks
- JSON output
- exit codes

### D2
- `doctor --deep`
- remote probes
- DB integrity
- workspace/radar/inbox checks

### D3
- `doctor fix`
- low-risk repairs
- repair traces

### D4
- `doctor bundle`
- redaction profiles
- support artifact

## 8.10. Acceptance criteria

- `doctor` chạy ổn định trên cold install, degraded install, stale auth và corrupted cache scenarios.
- `doctor fix` sửa được ít nhất 70% lỗi phổ biến không cần human intervention.
- `doctor bundle` không làm lộ raw secrets.
- Agent host có thể dựa vào exit code + JSON của doctor để quyết định có chạy tiếp hay không.

---

## 9) Feature 2 — Workspaces

## 9.1. Mục tiêu

Workspaces giải quyết một hạn chế nền tảng của NotebookLM: **mỗi notebook độc lập**. [S1]

Workspace là một object local/orchestrator-side, không phải object server-side của NotebookLM.

### Định nghĩa
Một workspace là:
- một tập notebook,
- cộng với policy chọn notebook nào cho từng loại query,
- cộng với memory/history riêng,
- cộng với quyền/approval/freshness policy riêng.

## 9.2. Tại sao đây là feature quan trọng bậc nhất

Người dùng thường không có đúng “một notebook cho một câu hỏi”.
Họ có:
- notebook pricing,
- notebook customer research,
- notebook product strategy,
- notebook onboarding,
- notebook competitors.

Nếu không có workspace:
- phải nhớ notebook nào chứa gì,
- phải tự chuyển context,
- agent khó handoff sạch,
- câu trả lời khó tổng hợp across projects.

Nếu có workspace:
- user có thể nói “ask the market-intel workspace”,
- agent có thể treat workspace như specialist tool,
- notebook trở thành unit storage; workspace trở thành unit reasoning.

## 9.3. Các loại workspace

### Static workspace
Danh sách notebook explicit.

Ví dụ:
- `market-intel` = pricing + competitors + customer-research
- `onboarding` = handbook + SOP + FAQ

### Rule-based workspace
Notebook membership xác định bằng rule local:
- title regex,
- tags,
- source type,
- folder-like grouping local,
- notebook metadata predicates.

MVP chỉ cần static trước; rule-based ở phase sau.

## 9.4. Các mode thực thi

### Mode A — Metadata workspace
Chỉ tổng hợp notebook/source/artifact metadata local.
Use cases:
- liệt kê notebook nào nằm trong workspace,
- source nào có trong workspace,
- artifact nào gần nhất,
- notebook nào stale nhất.

### Mode B — Query workspace
Khi user hỏi một câu, hệ thống:
1. chọn notebook candidates,
2. fan-out query,
3. tổng hợp câu trả lời cuối.

Đây là mode giá trị nhất.

### Mode C — Compare workspace
Tương tự query workspace nhưng output tối ưu cho:
- đối chiếu,
- phát hiện khác biệt,
- contradictions,
- overlap.

### Mode D — Materialized workspace (phase sau)
Tạo “workspace dossier” như một derived note/source để reuse lâu dài.
Điều này khả thi vì NotebookLM đã có cơ chế:
- gộp notes thành unified note,
- biến notes thành source. [S19]

## 9.5. Chiến lược query của workspace

### Bước 1 — Candidate selection
Dùng local index để chọn top notebooks.
MVP:
- SQLite FTS/BM25 trên:
  - notebook title,
  - notebook summary/title aliases,
  - source titles,
  - source snippets,
  - tags,
  - recent successful query history.

Không cần embeddings ngay.

### Bước 2 — Planning
Planner quyết định:
- hỏi 1 notebook,
- hỏi top 2–3 notebooks,
- hay chia câu hỏi thành sub-questions.

### Bước 3 — Fan-out execution
Mỗi notebook được hỏi bằng remote runtime như bình thường.
Mọi sub-run có:
- `trace_id`,
- notebook scope,
- freshness metadata.

### Bước 4 — Synthesis
Synthesis agent/local combiner tổng hợp final answer.
Output phải giữ provenance:
- notebook nào góp phần nào,
- source evidence nằm ở notebook nào,
- confidence level theo notebook coverage.

## 9.6. Một nguyên tắc cực quan trọng

**Workspace không được giả vờ rằng NotebookLM bản thân nó đã query across notebooks.**

Final answer phải minh bạch đây là kết quả của:
- multi-notebook planning,
- per-notebook execution,
- local synthesis.

Điều này giúp:
- tránh overclaim,
- debug dễ,
- giữ trust.

## 9.7. Workspace như tool / specialist agent

Theo Agents SDK, handoffs được biểu diễn như tools. [S11]

Vì vậy mỗi workspace nên có thể được expose như:
- tool callable,
- specialist handoff target,
- `agent.as_tool()` wrapper trong host agent.

Ví dụ:
- `ask_workspace_market_intel(question)`
- `compare_workspace_onboarding(question)`
- `overview_workspace_finance()`

## 9.8. Policy của workspace

Mỗi workspace có:
- `max_notebooks_per_run`
- `prefer_fresh_metadata`
- `allow_remote_fanout`
- `approval_policy`
- `default_output_mode`
- `max_token_budget`
- `synthesis_style`
- `conflict_strategy`

### Conflict strategy
Khi notebook trả lời mâu thuẫn:
- `show_both`
- `prefer_newer_sources`
- `prefer_notebook_priority`
- `ask_followup`

MVP nên mặc định là `show_both`.

## 9.9. Concurrency discipline

Mọi workspace mutation cần lease advisory:
- `workspace:<id>` cho reindex/update membership,
- `notebook:<id>` khi apply import thông qua inbox.

Pattern này vay từ Agent Mail: leases nhẹ, advisory, có audit. [S12]

## 9.10. Command surface

```bash
notebooklm workspace list
notebooklm workspace create market-intel
notebooklm workspace add market-intel --notebook pricing
notebooklm workspace add market-intel --notebook competitors
notebooklm workspace show market-intel
notebooklm workspace ask market-intel "How are enterprise buyers evaluating price?"
notebooklm workspace compare market-intel "Compare our positioning versus top competitors"
notebooklm workspace index market-intel
notebooklm workspace remove market-intel --notebook competitors
```

## 9.11. JSON envelope đề xuất

```json
{
  "ok": true,
  "trace_id": "trc_...",
  "workspace": {
    "id": "ws_...",
    "name": "market-intel"
  },
  "plan": {
    "mode": "fanout_synthesize",
    "selected_notebooks": [
      {"id": "nb_1", "title": "Pricing", "score": 0.92},
      {"id": "nb_2", "title": "Customer Interviews", "score": 0.78}
    ],
    "reason": "Top notebooks by lexical relevance and prior query hits"
  },
  "result": {
    "answer": "...",
    "provenance": [
      {"notebook_id": "nb_1", "contribution": "pricing objections"},
      {"notebook_id": "nb_2", "contribution": "buyer interview evidence"}
    ]
  }
}
```

## 9.12. Rollout

### W1
- workspace CRUD
- static workspaces
- local metadata views

### W2
- workspace index
- `workspace ask`
- top-k notebook selection
- basic synthesis

### W3
- `workspace compare`
- route explain
- better provenance output

### W4
- workspace as tool/handoff
- materialized dossier (optional)
- rule-based membership

## 9.13. Acceptance criteria

- User có thể dùng 1 câu lệnh để reasoning trên nhiều notebook mà không phải nhớ notebook cụ thể.
- Mọi câu trả lời workspace đều chỉ rõ notebook nào được dùng.
- Khi câu hỏi chỉ liên quan một notebook, planner có thể route về 1 notebook thay vì fan-out thừa.
- Workspace query không trộn profile khác nhau.
- Agent host có thể treat workspace như một specialist tool.

---

## 10) Feature 3 — Change Radar

## 10.1. Mục tiêu

Change Radar biến knowledge base từ trạng thái “chụp lại một lần rồi cũ dần” thành trạng thái “được theo dõi có chọn lọc”.

Feature này tồn tại vì:
- source là bản copy tĩnh,
- Drive files không auto-sync,
- nhiều source khác phải reimport thủ công khi gốc đổi. [S2]

## 10.2. Định nghĩa

Change Radar là hệ thống:
- quản lý watch policies,
- chạy source-type-specific detection,
- tạo diff/signature,
- đánh giá mức độ ảnh hưởng,
- sinh **delta briefing**,
- và đẩy thay đổi vào **Research Inbox** khi cần approval.

## 10.3. Các loại watch

### Source watch
Theo dõi một source cụ thể.

### Notebook watch
Theo dõi tập source của notebook:
- source mới,
- source mất,
- source đổi.

### Workspace watch
Theo dõi nguồn ở mức workspace:
- notebook thành viên stale,
- source cốt lõi đổi,
- query result dễ bị stale.

### Research query watch
Chạy lại một câu Deep Research / Fast Research saved query theo lịch.

## 10.4. Adapters theo loại source

### Google Drive sources
- Nếu transport đã hỗ trợ sync endpoint: dùng trực tiếp.
- Nếu chưa: ít nhất phải phát hiện khả năng stale và stage action.

### Web URL
- Dùng HEAD/GET,
- lưu `etag`, `last-modified`, canonical URL,
- fallback sang body hash/content signature.

### Local files
- mtime + size + hash.

### YouTube
- transcript fingerprint,
- unavailable/private status,
- title/description changes là signal phụ.

### Deep Research watch
- chạy lại query saved,
- diff report titles/source set,
- không auto-import.

## 10.5. Change pipeline

```text
scheduler selects due watch
-> adapter fetches fresh signature
-> compare with previous revision
-> if changed:
     create source_revision
     create change_event
     build delta_briefing
     if material -> create inbox item
-> update affected notebook/workspace fingerprints
-> mark stale cached query runs
```

## 10.6. Delta Briefing

Delta briefing phải trả lời 4 câu:

1. Cái gì đổi?
2. Mức độ nghiêm trọng ra sao?
3. Notebook/workspace/query nào có thể bị ảnh hưởng?
4. Hành động tốt nhất tiếp theo là gì?

### Ví dụ output
- “Source `Pricing FAQ` changed materially.”
- “3 pricing claims changed; 2 cached answers about annual discount policy are likely stale.”
- “Suggested action: stage a replacement import candidate and rerun workspace `market-intel` overview.”

## 10.7. Severity model

- `noise`: thay đổi nhỏ, không action.
- `minor`: log + brief, không inbox mặc định.
- `material`: tạo inbox item.
- `critical`: tạo inbox item + priority cao + stale related query runs.

## 10.8. Ảnh hưởng đến cache và memory

Khi change material:
- invalidate notebook fingerprint,
- invalidate workspace fingerprint,
- mark related query runs `stale_possible`,
- link delta briefing tới affected runs.

Điểm này rất quan trọng vì nếu không, hệ thống sẽ reuse câu trả lời cũ một cách im lặng.

## 10.9. Command surface

```bash
notebooklm watch add --source src_123 --policy daily
notebooklm watch add --workspace market-intel --policy weekly
notebooklm watch list
notebooklm watch pause watch_123
notebooklm watch run-now watch_123

notebooklm radar status
notebooklm radar list
notebooklm radar brief evt_123
notebooklm radar ignore evt_123
```

## 10.10. JSON envelope đề xuất

```json
{
  "ok": true,
  "trace_id": "trc_...",
  "watch": {
    "id": "watch_123",
    "kind": "web_diff"
  },
  "event": {
    "id": "evt_123",
    "severity": "material",
    "change_kind": "content_hash_changed"
  },
  "briefing": {
    "summary": "Pricing policy page changed materially",
    "affected": {
      "notebooks": ["nb_pricing"],
      "workspaces": ["ws_market_intel"],
      "query_runs": 2
    },
    "recommended_action": "create inbox replacement candidate"
  }
}
```

## 10.11. Rollout

### R1
- watch CRUD
- URL + local file adapters
- simple diff/signature

### R2
- notebook/workspace watch
- Drive source stale detection
- delta briefings

### R3
- saved research query watches
- impact linking to query history
- inbox integration by default

### R4
- smarter severity scoring
- better replacement recommendations
- optional scheduled automation host hooks

## 10.12. Acceptance criteria

- User có thể theo dõi source quan trọng và nhận được delta briefing có ích, không chỉ là “hash changed”.
- Change material phải tự động làm stale relevant cache/history.
- Không có auto-import ngầm cho source external trừ policy explicit.
- Deep Research watch không spam notebook; mặc định chỉ vào inbox.

---

## 11) Feature 4 — Research Inbox with approval-first triage

## 11.1. Mục tiêu

Research Inbox là **intake valve** của tri thức mới.

NotebookLM hiện đã có hành vi review kết quả trước rồi mới import cho Fast Research/Deep Research. [S2][S5]
Ta mở rộng hành vi đó thành một lớp local bền vững hơn, giải thích tốt hơn và phù hợp hơn cho agent workflows.

## 11.2. Nguồn candidate đi vào inbox

- Fast Research results
- Deep Research reports
- Deep Research cited/uncited sources
- Discover Sources results
- Change Radar replacement/resync candidates
- Manual agent proposals
- “gap fill” proposals sinh ra từ workspace compare / contradiction detection về sau

## 11.3. Inbox item phải chứa gì

Mỗi item cần tối thiểu:
- candidate title
- canonical URI
- source/report/replacement/resync kind
- notebook/workspace đích
- origin
- lý do đề xuất
- novelty/relevance/trust score
- dedupe cluster
- approval requirement
- suggested action

## 11.4. Nguyên tắc triage

### Approval-first mặc định
- external sources mới: cần approval
- report import: cần approval
- Drive resync low-risk: có thể auto nếu policy cho phép
- duplicate/near-duplicate: ưu tiên merge hoặc reject

### Dedupe trước, approve sau
Không bắt user duyệt 8 bài gần như giống nhau.

### Explainability bắt buộc
Mỗi item phải trả lời được:
- “vì sao nó được đề xuất?”
- “nó thêm gì mới?”
- “nó trùng gì với cái đã có?”
- “nếu import thì nó thay đổi cái gì?”

## 11.5. Hệ chấm điểm pragmatic

### Relevance score
- query-match,
- workspace/notebook topical match,
- source-title/source-summary match.

### Novelty score
- khác title/url/canonical URI,
- khác cluster nội dung,
- khác so với source hiện có.

### Trust score
MVP không cần hệ domain trust phức tạp.
Chỉ cần heuristic:
- official docs / docs domains / well-known owned domain,
- cited by deep research report,
- repeated agreement across results,
- parseability/accessibility.

LLM explanation có thể dùng để bổ sung rationale, nhưng scoring nền phải deterministic.

## 11.6. Dedupe/cluster strategy

Dùng các tín hiệu:
- canonical URL
- normalized title
- content hash nếu có
- domain + slug similarity
- same report citation provenance

Cluster output:
- representative item
- variants
- best recommended action

## 11.7. Approval flow

Theo tinh thần HITL của Agents SDK, tool call nhạy cảm phải có thể:
- pause,
- surface approval request,
- resume sau khi quyết định. [S8]

Trong CLI này, thay vì phụ thuộc SDK runtime hoàn toàn, ta mô phỏng cùng pattern bằng local interruption state:

```text
agent run
-> creates inbox item(s)
-> approval required
-> run paused with resume_token
-> user approves/rejects
-> run resumed or closed
```

### Lợi ích
- hợp với agent hosts,
- hợp với batch runs,
- không cần interactive TUI phức tạp ở MVP.

## 11.8. Apply actions

Các action nên hỗ trợ:

- approve import source
- approve import report only
- approve cited-only sources
- approve top-N items in cluster
- reject
- defer/snooze
- bulk apply filter
- convert to saved watch
- ask for follow-up research

## 11.9. Command surface

```bash
notebooklm inbox list
notebooklm inbox view item_123
notebooklm inbox why item_123
notebooklm inbox approve item_123
notebooklm inbox reject item_123
notebooklm inbox defer item_123 --until 2026-03-21
notebooklm inbox import item_123
notebooklm inbox apply-batch --filter pending:high
```

## 11.10. JSON envelope đề xuất

```json
{
  "ok": true,
  "trace_id": "trc_...",
  "item": {
    "id": "item_123",
    "origin": "deep_research",
    "kind": "source",
    "state": "pending",
    "approval_required": true
  },
  "scores": {
    "relevance": 0.93,
    "novelty": 0.71,
    "trust": 0.84
  },
  "explanation": {
    "why_recommended": "Appears in Deep Research report and adds a missing enterprise pricing angle",
    "overlap": "Low overlap with existing sources in notebook",
    "suggested_action": "approve_import"
  }
}
```

## 11.11. Rollout

### I1
- inbox tables
- list/view/approve/reject/defer
- manual candidate insertion
- apply import path

### I2
- Fast Research / Deep Research results land in inbox
- dedupe clusters
- explanations
- bulk actions

### I3
- approval interruptions + resume token
- change radar integration
- saved filters / priority queues

### I4
- stronger scoring
- follow-up research requests
- agent policy hooks

## 11.12. Acceptance criteria

- Deep Research result không bị “biến mất” khỏi workflow nếu chưa import ngay; nó vẫn nằm trong inbox để xử lý sau.
- User/agent có thể triage nhiều candidate nhanh hơn nhờ cluster + reason + batch actions.
- External source mới không tự chui vào notebook nếu chưa có policy rõ.
- Inbox decisions có thể search/reuse như memory để tránh lặp lại các import tệ.

---

## 12) Cách 4 feature phối hợp trong thực tế

## 12.1. Flow A — Hỏi một workspace

```text
workspace ask "What changed in how enterprise buyers talk about pricing?"
-> workspace resolver picks pricing + customer interviews notebooks
-> doctor gate sees system healthy
-> remote fanout asks top 2 notebooks
-> local synthesis combines answers
-> trace recorded
```

## 12.2. Flow B — Source gốc thay đổi

```text
watch run
-> source signature changed
-> delta briefing created
-> severity = material
-> inbox replacement candidate created
-> user approves
-> source sync/reimport executed
-> notebook and workspace fingerprints updated
-> affected cached answers marked stale
```

## 12.3. Flow C — Deep Research

```text
research start "emerging competitors in EU market"
-> Deep Research returns report + sources
-> results stored in inbox (not imported immediately)
-> user approves top cited items only
-> imports applied
-> workspace index updated
```

## 12.4. Flow D — Doctor before batch automation

```text
nightly automation
-> doctor --deep --json
-> status = degraded (expired auth + stale workspace index)
-> doctor fix
-> rerun doctor
-> status = healthy
-> scheduled watches continue
```

---

## 13) Shared risk model và approval model

## 13.1. Risk tiers

### Tier 0 — read-only
- list
- show
- doctor
- workspace ask
- radar brief
- inbox view

Không cần approval.

### Tier 1 — low-risk mutation
- rebuild local index
- clear stale leases
- refresh auth snapshot
- resync metadata

Có thể auto-apply nếu policy cho phép.

### Tier 2 — external knowledge mutation
- import source
- import report
- replace changed source
- apply deep research results

Approval mặc định.

### Tier 3 — destructive mutation
- delete source
- delete notebook
- purge cache aggressively
- reset profile

Approval mạnh hơn; có thể cần hai bước hoặc explicit policy.
Pattern này chịu ảnh hưởng trực tiếp từ DCG/SLB: command nguy hiểm không được “vô tình chạy qua”. [S15][S16]

## 13.2. Approval policy sources

Policy có thể định nghĩa ở:
- profile,
- notebook,
- workspace,
- command override.

Thứ tự ưu tiên:
`command override > workspace policy > notebook policy > profile policy`.

---

## 14) Tracing, memory và search

Bốn feature này chỉ thật sự agent-first nếu truy vết và nhớ được.

## 14.1. Tracing

Trace phải ghi:
- planner decisions,
- selected notebooks,
- watch adapter path,
- inbox scoring explanation,
- approvals,
- doctor repairs.

Điều này bám sát tinh thần tracing của Agents SDK. [S10]

## 14.2. Memory/search

Tối thiểu nên index:
- doctor findings gần đây,
- inbox decisions,
- workspace query plans,
- radar delta briefings.

Đây là adaptation nhỏ nhưng rất hiệu quả của pattern CASS: agent không phải “quên sạch” mọi lần triage và sửa lỗi trước đó. [S13]

---

## 15) Manifest / contract updates

Bốn feature này phải được mô tả trong `contracts/capabilities.yaml` hoặc file tương đương.

Ví dụ:

```yaml
doctor:
  commands:
    - doctor
    - doctor --deep
    - doctor fix
    - doctor bundle
  checks:
    - auth.bl_present
    - db.integrity
    - workspace.index_fresh
    - inbox.approval_backlog
    - radar.watch_failures

workspace:
  commands:
    - workspace list
    - workspace create
    - workspace ask
    - workspace compare

radar:
  commands:
    - watch add
    - watch list
    - radar status
    - radar brief

inbox:
  commands:
    - inbox list
    - inbox approve
    - inbox reject
    - inbox import
```

Lý do phải làm vậy là để:
- CLI help,
- JSON schemas,
- doctor checks,
- docs,
- tests
cùng bám một nguồn sự thật. Đây là một bài học cực đáng lấy từ ACFS manifest architecture. [S17]

---

## 16) Trình tự triển khai khuyến nghị

## Phase A — Shared foundations
Mục tiêu:
- thêm tables,
- thêm leases,
- thêm approval engine,
- thêm trace events,
- thêm capability manifest entries.

Không ship feature lớn cho user ở phase này; đây là đường ray.

## Phase B — Doctor MVP
Ship:
- `doctor`
- `doctor --json`
- fast checks
- exit codes
- basic repairs

Lý do làm trước:
- giảm support burden cho các phase sau.

## Phase C — Research Inbox MVP
Ship:
- inbox tables
- manual candidate insertion
- approve/reject/defer
- apply import path
- batch basics

Lý do làm sớm:
- trở thành shared approval substrate cho Radar và future research.

## Phase D — Workspaces MVP
Ship:
- static workspaces
- workspace metadata views
- workspace ask
- top-k notebook selection
- synthesis with provenance

## Phase E — Change Radar MVP
Ship:
- watch CRUD
- URL/local-file adapters
- basic diff + delta briefing
- create inbox item on material changes

## Phase F — Deep integration
Ship:
- Deep Research -> inbox
- workspace compare
- doctor --deep
- support bundle
- saved research query watches

## Phase G — Hardening
Ship:
- smarter scoring
- better repair coverage
- resume tokens for approvals
- better policy inheritance
- performance tuning

---

## 17) Thứ tự ưu tiên nếu cần tối đa hóa value / effort

Nếu phải chọn thứ tự thuần pragmatic:

1. **Doctor MVP**
2. **Research Inbox MVP**
3. **Workspaces MVP**
4. **Change Radar MVP**
5. Deep integration / advanced variants

Lý do:
- Doctor làm hệ thống đáng tin hơn ngay.
- Inbox cho approval boundary ngay.
- Workspaces là value unlock lớn nhất cho user.
- Radar mạnh nhất khi đã có Inbox để đổ candidate vào.

---

## 18) Những quyết định giúp tránh complexity bùng nổ

1. Không embeddings bắt buộc ở workspace MVP.
2. Không background daemon bắt buộc.
3. Không cross-profile workspace.
4. Không auto-import source external mặc định.
5. Không auto-delete/rewrite source.
6. Không fake cross-notebook provenance.
7. Không kéo dependency trực tiếp từ flywheel tools.
8. Không làm UI mới trước khi CLI + JSON ổn.

---

## 19) Kết luận chốt

Bốn năng lực này là **bổ sung đúng nhất** cho plan agent-first hiện tại vì chúng tác động vào bốn điểm yếu thực tế nhất của hệ NotebookLM automation:

- **Doctor** giải quyết độ tin cậy vận hành.
- **Workspaces** giải quyết độ rộng của reasoning.
- **Change Radar** giải quyết freshness của tri thức.
- **Research Inbox** giải quyết chất lượng và trust boundary của tri thức đi vào hệ thống.

Nếu chỉ thêm một hay hai trong số này, hệ thống vẫn mạnh hơn hiện tại nhưng chưa “khóa vòng”.
Khi làm đủ cả bốn, ta có một loop đầy đủ:

```text
Health -> Reasoning Surface -> Freshness Detection -> Approved Knowledge Inflow
```

Đó mới là bước chuyển rõ rệt từ “CLI wrapper” sang “agent-first knowledge system”.

---

## 20) Phụ lục: command sketch hoàn chỉnh

```bash
# Doctor
notebooklm doctor
notebooklm doctor --deep
notebooklm doctor fix
notebooklm doctor bundle

# Workspaces
notebooklm workspace list
notebooklm workspace create market-intel
notebooklm workspace add market-intel --notebook pricing
notebooklm workspace ask market-intel "What changed in buyer objections?"
notebooklm workspace compare market-intel "Compare us vs competitors"

# Change Radar
notebooklm watch add --source src_123 --policy daily
notebooklm watch add --workspace market-intel --policy weekly
notebooklm watch list
notebooklm watch run-now watch_123
notebooklm radar status
notebooklm radar brief evt_123

# Research Inbox
notebooklm inbox list
notebooklm inbox view item_123
notebooklm inbox why item_123
notebooklm inbox approve item_123
notebooklm inbox reject item_123
notebooklm inbox defer item_123 --until 2026-03-21
notebooklm inbox import item_123
```

---

## 21) Research basis

[S1] Google Help — Create a notebook in NotebookLM  
https://support.google.com/notebooklm/answer/16206563?hl=en

[S2] Google Help — Add or discover new sources for your notebook  
https://support.google.com/notebooklm/answer/16215270?co=GENIE.Platform%3DDesktop&hl=en

[S3] Google Help — Use chat in NotebookLM  
https://support.google.com/notebooklm/answer/16179559?hl=en

[S4] Google Workspace Updates — Updates to sources for NotebookLM  
https://workspaceupdates.googleblog.com/2025/04/updates-to-sources-for-NotebookLM-and-NotebookLMPlus.html

[S5] Google Blog — NotebookLM adds Deep Research and support for more source types  
https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-deep-research-file-types/

[S6] Google Workspace Updates — Add NotebookLM as a source in Gemini  
https://workspaceupdates.googleblog.com/2026/01/take-notebooks-further-notebooklm-gemini.html

[S7] OpenAI Agents SDK overview  
https://openai.github.io/openai-agents-python/

[S8] OpenAI Agents SDK — Human in the loop  
https://openai.github.io/openai-agents-python/human_in_the_loop/

[S9] OpenAI Agents SDK — Guardrails  
https://openai.github.io/openai-agents-python/guardrails/

[S10] OpenAI Agents SDK — Tracing  
https://openai.github.io/openai-agents-python/tracing/

[S11] OpenAI Agents SDK — Handoffs  
https://openai.github.io/openai-agents-python/handoffs/

[S12] Agent Mail / mcp_agent_mail_rust  
https://github.com/Dicklesworthstone/mcp_agent_mail_rust

[S13] Cass Memory System  
https://github.com/Dicklesworthstone/cass_memory_system

[S14] Coding Agent Account Manager  
https://github.com/Dicklesworthstone/coding_agent_account_manager

[S15] Destructive Command Guard  
https://github.com/Dicklesworthstone/destructive_command_guard

[S16] Simultaneous Launch Button  
https://github.com/Dicklesworthstone/slb

[S17] ACFS — Single Source of Truth Manifest Architecture  
https://github.com/Dicklesworthstone/agentic_coding_flywheel_setup/blob/main/PLAN_TO_HAVE_SINGLE_SOURCE_OF_TRUTH_MANIFEST.md

[S18] CASS skill/docs snippets showing health/doctor patterns  
https://github.com/Dicklesworthstone/agent_flywheel_clawdbot_skills_and_integrations/blob/main/skills/cass/SKILL.md

[S19] Google Help — Create & add notes in NotebookLM  
https://support.google.com/notebooklm/answer/16262519?hl=en
