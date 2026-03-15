# Kế hoạch hoàn chỉnh cho `notebooklm_cli` theo triết lý agent-first

Ngày chốt: 2026-03-14

## 1) Kết luận ngắn

Plan trước **đúng hướng nhưng chưa đủ agent-first**.

Nó đã đúng ở các điểm nền tảng:
- Browser chỉ dùng để đăng nhập và phục hồi xác thực.
- Runtime chính phải là `httpx`, không chạy NotebookLM trong browser như kênh thực thi thường xuyên.
- Cần local cache bền vững, sync engine, router, và structured JSON envelope.

Nhưng nó vẫn còn nghiêng về mô hình **CLI-first có phủ thêm router** hơn là **agent-first system**.

Để thật sự agent-first, bản kế hoạch phải nâng thêm 6 lớp mà bản cũ mới chạm một phần hoặc chưa chạm:
1. **Memory/search/tracing** cho agent.
2. **Diagnostics/doctor/support-bundle** để agent tự kiểm tra hệ thống.
3. **Safety/approval model** cho các lệnh có tác dụng phá huỷ.
4. **Manifest/contract là single source of truth** cho commands, RPC, cache entities, JSON envelopes, doctor checks.
5. **Profile isolation + concurrency discipline** để nhiều agent hoặc nhiều account chạy song song không đè nhau.
6. **Task/state model rõ ràng** cho sync, artifact, research, thay vì chỉ là vài lệnh rời rạc.

Vì vậy, kế hoạch mới dưới đây **giữ transport base hiện tại**, nhưng **điều chỉnh kiến trúc và roadmap** để phù hợp hơn với triết lý agent-first, đồng thời chỉ vay mượn những ý tưởng hữu ích từ hệ tool của Agent Flywheel thay vì kéo cả stack vào làm dependency.

---

## 2) Định nghĩa “agent-first” cho dự án này

Trong phạm vi NotebookLM CLI, “agent-first” không có nghĩa là chỉ cho phép natural language, cũng không có nghĩa là phải biến sản phẩm thành một multi-agent platform kiểu tmux swarm.

Ở đây, “agent-first” có nghĩa là:

1. **Agent là đối tượng sử dụng chính của contract**, không chỉ là người dùng terminal.
   - Mọi lệnh quan trọng phải có output JSON ổn định.
   - Route quyết định phải giải thích được.
   - Trạng thái phải truy vết được.

2. **System phải nhớ và tự quan sát được**.
   - Có durable cache.
   - Có history/search.
   - Có trace/run diagnostics.

3. **System phải ưu tiên deterministic tool use hơn prompt magic**.
   - Structured commands luôn thắng NL routing.
   - Router chỉ làm classify + resolve + freshness + execution planning.

4. **System phải an toàn cho agent**.
   - Lệnh phá huỷ phải có risk tier.
   - Có dry-run, explain, approval gate khi cần.

5. **System phải hỗ trợ external orchestrators**.
   - JSON envelopes, stable IDs, lock discipline, profile isolation.
   - Không phụ thuộc vào một host agent cụ thể.

6. **System phải tự chẩn đoán được drift**.
   - Doctor checks.
   - Auth diagnostics.
   - Support bundle có redaction.

---

## 3) Đánh giá lại plan cũ

## 3.1. Những phần đã đúng và phải giữ

### A. Giữ nguyên transport split
- Playwright/Patchright chỉ dùng cho `auth login` và auth recovery.
- Mọi notebook/source/query/generation/research operation đi qua `httpx`.
- `bl` phải trở thành một phần của session snapshot.

### B. Giữ local durable cache + sync engine + router
- Đây là trục đúng nhất của plan cũ.
- Không có durable local metadata thì không thể local-first metadata, không thể exact reuse, không thể routing tốt.

### C. Giữ semantic split giữa command explicit và command NL
- `ask`, `overview`, `summarize`, `study-guide`, `audio`, `research start|wait|import` vẫn là đúng.
- `agent` và `route --dry-run` vẫn là cần thiết.

### D. Giữ quyết định không quay về browser automation runtime
- Đây là ranh giới kiến trúc quan trọng nhất.

## 3.2. Những phần cần sửa vì chưa đủ agent-first

### A. Không nên tách package top-level `notebooklm_agent/` ở giai đoạn này
Plan cũ đề xuất thêm package mới cạnh `src/notebooklm/`.

Điều này không sai về mặt lý thuyết, nhưng với branch hiện tại thì không phải lựa chọn tốt nhất vì:
- Active product contract đã được khoanh vào `src/notebooklm/**`.
- `src/notebooklm_mcp/**` đã được định vị là legacy/frozen reference.
- Packaging hiện vẫn quét `notebooklm*`, nên thêm một package top-level mới làm boundary rối hơn trước khi boundary cũ được khoá lại.

**Quyết định mới:**
- Không tạo `src/notebooklm_agent/` ở MVP.
- Thay vào đó, mở rộng ngay trong `src/notebooklm/` với các module con cho `profiles`, `local`, `sync`, `router`, `workflows`, `observability`, `doctor`, `safety`.

### B. Không tạo home dir mới kiểu `~/.notebooklm-agent/`
Plan cũ đề xuất home directory mới.

Điều đó không phù hợp với branch hiện tại vì runtime đã chuẩn hoá quanh `NOTEBOOKLM_HOME` với `storage_state.json`, `context.json`, `config.json`, `browser_profile/`.

**Quyết định mới:**
- Giữ `NOTEBOOKLM_HOME` là root duy nhất.
- Chỉ thêm các file/dirs mới bên trong root hiện có.

### C. Plan cũ thiếu explicit observability layer
`query_runs`, `query_results`, `sync_runs` là đúng, nhưng vẫn chưa đủ nếu không có:
- `trace_id`
- event log
- route explanation
- auth refresh diagnostics
- support bundle

### D. Plan cũ thiếu safety/approval model
Agent-first mà không có guardrails cho mutation là thiếu một mảnh rất lớn.

### E. Plan cũ chưa manifest-first
Plan cũ đúng ở schema và routing, nhưng chưa có một contract file làm nguồn sự thật duy nhất cho:
- command definitions
- intent map
- RPC map
- cache entities
- JSON envelope schema
- doctor checks

Flywheel rất nhấn mạnh mô hình manifest/canonical contract; dự án này nên vay đúng ý tưởng đó.

---

## 4) Nguyên tắc thiết kế mới

## 4.1. Non-negotiables

1. **HTTP-only runtime** cho read/write/query/generate/research.
2. **Browser only for login/recovery**.
3. **`bl` là trường bắt buộc** trong session snapshot.
4. **Single active product surface = `src/notebooklm/**`**.
5. **Mọi command non-trivial phải có `--json`**.
6. **Structured command thắng NL routing**.
7. **Metadata local-first; query/generation/research remote-first**.
8. **Mutations có risk tier và support dry-run/explain/approval khi cần**.
9. **Không hard-depend vào toàn bộ Agent Flywheel stack**.
10. **Có thể tích hợp tốt với external agent hosts** qua stable JSON contracts.

## 4.2. Triết lý vay mượn từ Agent Flywheel

### Vay ý tưởng, không vay dependency
Dự án này không cần biến thành NTM, Mail, BV, BR, hay một orchestration platform.

Nhưng nó nên vay các pattern đúng:
- **Mail**: coordination-friendly state + reservations + audit mindset.
- **BV/BR**: task graph / dependency / prioritization mindset.
- **CASS/CM**: session search + procedural memory.
- **ACFS**: doctor, doctor --deep, update/dry-run, support bundle, JSON summary.
- **DCG/SLB**: destructive command guard + approval model.
- **WA**: event stream / watch mode / state transitions.
- **CAAM**: profile isolation and fast switching.
- **manifest architecture**: canonical contract drives code and diagnostics.

---

## 5) Kiến trúc đích

```text
User command / NL request
-> CLI parser
-> Intent router
-> Notebook/profile resolver
-> Freshness gate
   -> local DB (metadata when fresh)
   -> or remote HTTP executor
-> cache write-back
-> event/trace recording
-> human renderer or JSON envelope
```

## 5.1. Runtime layers

1. **Profiles/Auth layer**
   - profile registry
   - storage_state paths
   - browser_profile paths
   - session snapshot hydration
   - refresh without reopening browser when cookies still valid

2. **Transport layer**
   - `httpx.AsyncClient`
   - RPC registry
   - `QUERY_URL`
   - upload endpoint
   - auth refresh / retry / 429 handling

3. **Local layer**
   - SQLite cache
   - current context
   - notebook/source/artifact/research/query history
   - FTS search over history where useful

4. **Sync layer**
   - notebook index/detail sync
   - source reconciliation
   - artifact/research polling
   - mutation invalidation

5. **Workflow layer**
   - ask / overview / summarize / study-guide / audio / research
   - structured command resolution
   - NL agent entrypoint

6. **Observability layer**
   - run events
   - trace IDs
   - route explanations
   - diagnostics
   - support bundle

7. **Safety layer**
   - risk classification
   - dry-run
   - approvals where required
   - explicit confirmation contract for destructive commands

---

## 6) Package layout mới

```text
src/notebooklm/
  auth.py
  client.py
  _core.py
  paths.py
  notebooklm_cli.py

  contracts/
    capabilities.yaml
    envelope_schema.py
    intents.py
    rpc_map.py
    doctor_checks.py

  profiles/
    manager.py
    migration.py
    isolation.py

  local/
    db.py
    schema.py
    migrations.py
    repositories.py
    fts.py
    fingerprints.py
    state.py

  sync/
    notebooks.py
    sources.py
    artifacts.py
    research.py
    invalidation.py

  router/
    classify.py
    resolve.py
    freshness.py
    execute.py
    explain.py

  workflows/
    ask.py
    overview.py
    summarize.py
    study_guide.py
    audio.py
    research.py

  observability/
    events.py
    tracing.py
    support_bundle.py
    audit.py

  safety/
    risk.py
    approvals.py
    guards.py

  doctor/
    checks.py
    fixers.py
    report.py

  cli/
    auth.py
    notebook.py
    source.py
    sync.py
    cache.py
    research.py
    history.py
    trace.py
    doctor.py
    route.py
    agent.py
    output.py
```

### Ghi chú quan trọng
- Đây là **mở rộng active package hiện tại**, không tạo sản phẩm song song mới.
- `src/notebooklm_mcp/**` tiếp tục là legacy/frozen reference.

---

## 7) Contract-first / manifest-first

## 7.1. Thêm `capabilities.yaml` làm single source of truth

Tạo file canonical, ví dụ:

```yaml
version: 1
commands:
  ask:
    intent: QUERY
    output: answer
    remote: true
  overview:
    intent: QUERY
    output: summary
    remote: true
  summarize:
    intent: GENERATION
    output: artifact_request
    mode: briefing_doc
  study-guide:
    intent: GENERATION
    output: artifact_request
    mode: study_guide
  audio:
    intent: GENERATION
    output: artifact_request
    mode: audio
  research.start:
    intent: RESEARCH
    output: research_request
  research.wait:
    intent: RESEARCH
    output: research_status
cache_entities:
  - notebooks
  - sources
  - artifacts
  - research_runs
  - query_runs
  - query_results
  - sync_runs
  - run_events
risk_tiers:
  notebook.delete: DANGEROUS
  source.delete: DANGEROUS
  cache.prune: CAUTION
  auth.clear: CAUTION
doctor_checks:
  - auth_snapshot_present
  - auth_snapshot_fresh
  - build_label_present
  - db_openable
  - schema_current
  - write_permissions_ok
  - notebooklm_home_consistent
```

## 7.2. Tại sao manifest-first là bắt buộc
- Router, doctor, docs, JSON schema và tests phải cùng nhìn vào một contract.
- Tránh drift giữa README, CLI, schema và doctor.
- Dễ cho external agent host introspect capability.

---

## 8) Local state và file layout

Giữ nguyên root hiện tại, mở rộng như sau:

```text
$NOTEBOOKLM_HOME/
  storage_state.json          # legacy compatible
  context.json               # legacy compatible
  config.json                # legacy compatible
  browser_profile/           # legacy compatible

  cache.db
  events.jsonl
  traces/
  support/
  profiles/
    default/
      storage_state.json
      browser_profile/
    work/
      storage_state.json
      browser_profile/
  locks/
```

## 8.1. Migration strategy

### Legacy compatibility first
- Nếu root cũ đã có `storage_state.json` và `browser_profile/`, coi đó là **legacy default profile**.
- Không move file ngay ở lần đầu.
- Ghi mapping vào DB.
- Chỉ migrate vật lý khi user yêu cầu hoặc khi doctor đề xuất fix.

### SQLite mode
- Bật WAL mode.
- Dùng profile-scoped advisory locking cho các operation mutation/sync dài.

---

## 9) Session/auth lifecycle

## 9.1. Session snapshot bắt buộc

Mọi snapshot phải có:
- cookies
- `csrf_token`
- `session_id`
- `build_label`
- capture time
- validated time
- cookie fingerprint
- profile id
- source (`browser_login`, `refresh_from_homepage`, `imported`)

## 9.2. Auth data model

### `profiles`
- `profile_id`
- `display_name`
- `account_email`
- `is_default`
- `storage_state_path`
- `browser_profile_path`
- timestamps

### `auth_snapshots`
- `profile_id`
- `cookie_fingerprint`
- `csrf_token`
- `session_id`
- `build_label`
- `captured_at`
- `validated_at`
- `status`
- `source`

## 9.3. Refresh policy

1. Startup đọc latest snapshot của profile đang active.
2. Nếu snapshot cũ hoặc thiếu `build_label`, refresh bằng authenticated homepage GET.
3. Nếu 401/403 hoặc build mismatch, refresh một lần rồi retry.
4. Chỉ mở browser lại nếu cookie-based refresh thất bại.

## 9.4. Transport hardening bắt buộc

- `AuthTokens` phải mở rộng để chứa `build_label`.
- `fetch_tokens()` phải extract cả `SNlM0e`, `FdrFJe`, và `bl`.
- `_build_url()` không được tự build params rời rạc nữa; phải dùng helper chung và luôn gửi `rpcids`, `source-path`, `f.sid`, `bl`, `rt`.
- `refresh_auth()` phải refresh đủ cả ba trường động, không chỉ CSRF + session ID.

---

## 10) Schema local cache

## 10.1. Bảng cốt lõi

### `app_state`
- `active_profile_id`
- `current_notebook_id`
- `current_conversation_id`
- `schema_version`

### `notebooks`
- notebook metadata đã sync
- normalized title
- share/owner fields
- synced timestamps
- tombstone
- raw payload hash

### `sources`
- source type, title, origin URI
- status
- freshness state
- small preview only in MVP
- sync timestamps
- tombstone
- raw payload hash

### `artifacts`
- artifact/task id
- type
- submode (`briefing_doc`, `study_guide`, `audio`, ...)
- prompt hash
- status
- requested/polled/completed timestamps
- download ref
- payload hash

### `research_runs`
- research id
- notebook id
- mode
- query
- status
- counts
- timestamps
- raw payload

### `query_runs`
- intent
- mode
- prompt hash
- notebook fingerprint
- settings hash
- cache policy
- route reason
- source_of_truth
- status
- reused_from

### `query_results`
- answer text
- citations JSON
- artifact id if any
- structured result JSON

### `sync_runs`
- scope
- target id
- trigger
- stats json
- error text

## 10.2. Bảng mới để đúng agent-first hơn

### `run_events`
Mỗi run tạo event log dạng append-only:
- `event_id`
- `trace_id`
- `run_id`
- `kind`
- `ts`
- `payload_json`

Kinds ví dụ:
- `route.resolved`
- `cache.hit`
- `cache.miss`
- `sync.started`
- `sync.finished`
- `auth.refreshed`
- `artifact.polled`
- `research.imported`
- `approval.requested`
- `approval.granted`

### `approval_requests`
- `approval_id`
- `action`
- `risk_tier`
- `requested_by`
- `requested_at`
- `status`
- `reason`
- `decision_payload_json`

### `history_fts` (virtual table)
- index prompt, answer, notebook title, source titles cho `history search`

## 10.3. Indexes MVP

- `notebooks(profile_id, normalized_title)`
- `sources(notebook_id, status)`
- `sources(profile_id, source_type)`
- `artifacts(notebook_id, status)`
- `query_runs(prompt_hash, notebook_fingerprint, intent)`
- `sync_runs(profile_id, scope, started_at)`
- FTS index cho prompt/answer/source title

---

## 11) Memory, search, replay

Đây là phần plan cũ còn nhẹ tay, nhưng agent-first cần nó.

## 11.1. Memory MVP

### Episodic memory
- query history
- sync history
- artifact/research task history
- route decisions

### Searchable memory
- `history search "renewal clause"`
- `history show <run-id>`
- `trace show <trace-id>`

### Replay discipline
- exact reuse chỉ được phép nếu:
  - prompt hash khớp
  - notebook fingerprint khớp
  - settings hash khớp
  - command cho phép reuse

## 11.2. Notebook fingerprint

SHA-256 trên canonical JSON gồm:
- notebook title
- notebook-level summary metadata
- ordered source IDs + source statuses + source fingerprints
- ordered artifact IDs + statuses
- server-visible settings ảnh hưởng output

## 11.3. Không cache full source text trong MVP
- chỉ metadata + preview nhỏ
- full text vẫn on-demand
- bảo vệ privacy và size

---

## 12) Routing model

## 12.1. Intent buckets

1. `LOCAL_METADATA`
2. `REMOTE_METADATA`
3. `QUERY`
4. `GENERATION`
5. `RESEARCH`

## 12.2. Structured commands always win

Nếu user gọi:
- `notebooklm audio ...`
- `notebooklm summarize ...`
- `notebooklm research start ...`

thì router không re-classify ý định; nó chỉ resolve notebook/profile, cache mode, freshness, execution plan.

## 12.3. Notebook resolution order

1. explicit `--notebook`
2. notebook ID explicit trong request
3. exact title match
4. current notebook context
5. fuzzy title match
6. fail with ranked candidates

## 12.4. Cache modes

- `smart` (default)
- `refresh`
- `offline`
- `network`

### `smart`
- metadata local-first
- stale metadata => sync
- query/generation/research => remote
- exact reuse chỉ khi fingerprint khớp

### `refresh`
- sync remote trước khi trả metadata

### `offline`
- local metadata only
- không cho query/generation/research remote

### `network`
- luôn remote nếu command hỗ trợ

## 12.5. Route explain / dry-run

`route --dry-run` và `route explain` phải là first-class diagnostics, không phải tiện ích phụ.

---

## 13) Command surface mới

## 13.1. Canonical commands

```text
auth
  notebooklm auth login
  notebooklm auth check
  notebooklm auth inspect
  notebooklm auth refresh

metadata
  notebooklm notebook list
  notebooklm notebook show <id-or-title>
  notebooklm notebook use <id-or-title>
  notebooklm source list [--notebook X]
  notebooklm source guide <source-id>
  notebooklm sync notebooks [--all | --notebook X]
  notebooklm cache status
  notebooklm cache prune

work
  notebooklm ask "question"
  notebooklm overview [--notebook X]
  notebooklm summarize [--notebook X] [--wait]
  notebooklm study-guide [--notebook X] [--wait]
  notebooklm audio [--notebook X] [--wait]
  notebooklm research start "query" --mode fast|deep
  notebooklm research wait <research-id>
  notebooklm research import <research-id>

agent
  notebooklm agent "make an audio overview for the pricing notebook"
  notebooklm route "summarize current notebook" --dry-run
  notebooklm route explain "which notebooks have stale drive sources?"

memory/observability
  notebooklm history search "renewal"
  notebooklm history show <run-id>
  notebooklm trace show <trace-id>
  notebooklm events tail

ops
  notebooklm doctor
  notebooklm doctor --deep
  notebooklm doctor --fix --dry-run
  notebooklm support-bundle create
```

## 13.2. Alias migration

Tạm giữ alias chuyển tiếp:
- `list` -> `notebook list`
- `create` -> `notebook create`
- `summary` -> `overview`
- `generate report --format briefing-doc` -> `summarize`
- `generate report --format study-guide` -> `study-guide`
- `generate audio ...` -> `audio ...`
- `source add-research ...` -> `research start ...`

## 13.3. Semantic decision bắt buộc

- `ask` = conversational Q&A
- `overview` = quick remote summary
- `summarize` = **briefing-doc generation**
- `study-guide` = study-guide artifact
- `audio` = audio overview artifact

Không đổi nghĩa này giữa chừng.

---

## 14) Observability

## 14.1. JSON envelope chuẩn

Mọi command non-trivial phải có envelope thống nhất:

```json
{
  "ok": true,
  "trace_id": "...",
  "run_id": "...",
  "route": {
    "intent": "GENERATION",
    "mode": "briefing_doc",
    "notebook_id": "...",
    "profile_id": "default",
    "source_of_truth": "remote_http",
    "cache_mode": "smart",
    "reason": "explicit summarize command",
    "transport": {
      "kind": "httpx",
      "endpoint": "batchexecute",
      "rpcid": "..."
    }
  },
  "freshness": {
    "notebook_index_age_s": 42,
    "notebook_detail_age_s": 11,
    "used_cached_result": false
  },
  "result": {},
  "cache_updates": {
    "tables_touched": ["artifacts", "query_runs"],
    "invalidated": ["notebooks:abc"]
  },
  "diagnostics": {
    "retries": 0,
    "auth_refreshed": false,
    "elapsed_ms": 1203
  }
}
```

## 14.2. `events tail`

Một watch/event stream đơn giản lấy cảm hứng từ WA:
- không phải terminal hypervisor
- chỉ là stream local event log cho run state transitions

Ví dụ:
- artifact started
- artifact completed
- research running
- auth refreshed
- approval requested

## 14.3. `trace show`

Hiển thị đầy đủ:
- input command
- resolved intent
- notebook/profile resolution
- freshness decision
- remote calls used
- cache writes
- retries/auth refresh

---

## 15) Safety model

Lấy cảm hứng từ DCG + SLB, nhưng scale xuống cho NotebookLM CLI.

## 15.1. Risk tiers

### SAFE
- `notebook list`
- `source list`
- `ask`
- `overview`
- `history search`

### CAUTION
- `cache prune`
- `auth clear`
- `sync notebooks --all`

### DANGEROUS
- `notebook delete`
- `source delete`
- bulk mutation commands nếu có

### CRITICAL
- chỉ dùng nếu sau này có destructive bulk operations lớn

## 15.2. Guard behavior

- SAFE: chạy bình thường
- CAUTION: hỗ trợ `--dry-run`; cần explicit `--yes` nếu side effect lớn
- DANGEROUS: bắt buộc confirm/approval token trong chế độ agent hoặc non-interactive
- CRITICAL: có thể cần human approval hoặc signed approval payload

## 15.3. Approval contract

Cho agent mode non-interactive:
- `--approval-token <token>`
- hoặc `--approve <approval-id>` sau khi `route explain` sinh request

---

## 16) Diagnostics / Doctor / Support Bundle

Đây là phần plan cũ còn thiếu nhiều nhất so với phong cách flywheel.

## 16.1. `doctor`

### `notebooklm doctor`
- package integrity
- config path resolution
- auth snapshot presence
- `build_label` presence
- DB openability
- schema version
- write permissions
- profile consistency
- stale lock detection

### `notebooklm doctor --deep`
- authenticated homepage GET
- token extraction test
- DB read/write test
- notebook list remote test (optional)
- artifact/research queue sanity checks

### `notebooklm doctor --fix --dry-run`
- chỉ đề xuất fix trước
- không âm thầm mutate state
- fixers ví dụ:
  - create missing dirs
  - migrate legacy profile mapping
  - rebuild FTS index
  - clear stale locks
  - mark broken auth snapshot invalid

## 16.2. `support-bundle create`

Bundle redacted gồm:
- path info
- schema version
- doctor report
- recent traces/events
- auth metadata không chứa raw cookie
- last errors

Mục tiêu là giúp debug drift/auth/cache issues nhanh.

---

## 17) Sync engine

## 17.1. Freshness policy

### Auth snapshot
- soft stale theo thời gian
- hard stale khi 401/403 hoặc build mismatch

### Notebook index
- refresh ngắn, global list rẻ

### Notebook detail
- ngắn hơn index vì là dependency root cho sources/artifacts

### Source metadata
- `ready`: cửa sổ lâu hơn
- `processing/preparing`: poll nhanh

### Artifact / Research
- đang chạy: poll ngắn
- terminal: cache lâu hơn

### Query result
- advisory only; không là source of truth cho câu trả lời factual mới

## 17.2. Invalidation rules

### Notebook mutations
- create -> invalidate notebook index
- rename -> update row + invalidate index/detail
- delete -> tombstone + cascade

### Source mutations
- add/delete/refresh/import -> invalidate notebook detail

### Artifact mutations
- create -> insert pending row + invalidate notebook detail
- delete/revise -> invalidate detail và lineage liên quan

### Query mutations
- không destructive invalidate sau `ask`
- chỉ ghi history

---

## 18) Flywheel-inspired patterns được chấp nhận

## 18.1. Mail -> coordination-friendly discipline
**Adopt pattern, not tool dependency.**

Áp dụng thành:
- advisory lock files cho profile/cache operations dài
- stable run IDs và event IDs
- clear ownership semantics cho sync/artifact/research runs
- repo contributor workflow tiếp tục dùng `AGENT.md` riêng nếu cần

Không áp dụng thành:
- dựng mailbox/messaging layer trong sản phẩm CLI

## 18.2. BR/BV -> task graph mindset
Áp dụng thành:
- thống nhất sync/artifact/research thành task-like state machines
- có queue/status view machine-readable
- có priority heuristic cho stale work sau này

Không áp dụng thành:
- build full issue tracker vào NotebookLM CLI MVP

## 18.3. CASS/CM -> memory/search
Áp dụng thành:
- searchable local history
- notebook-fingerprint aware replay
- trace + route memory
- sau MVP có thể thêm procedural playbooks

## 18.4. ACFS -> doctor/ops UX
Áp dụng thành:
- `doctor`
- `doctor --deep`
- `doctor --fix --dry-run`
- `support-bundle`
- structured JSON summary

## 18.5. DCG/SLB -> guardrails
Áp dụng thành:
- mutation risk tiers
- approval workflow cho destructive operations
- audit log cho action nhạy cảm

## 18.6. WA -> watch mode
Áp dụng thành:
- `events tail`
- trace-based state transition feed

## 18.7. CAAM -> profile isolation
Áp dụng thành:
- nhiều profile/account trong cùng DB
- switching nhanh
- lock discipline theo profile

## 18.8. Manifest architecture -> single source of truth
Áp dụng thành:
- `capabilities.yaml`
- doctor/checks/docs/tests sinh từ contract này

---

## 19) Những gì KHÔNG nên copy từ Agent Flywheel

1. Không biến CLI thành tmux orchestration system.
2. Không phụ thuộc vào Agent Mail, NTM, WA, BV, BR để chạy sản phẩm.
3. Không nhét full multi-agent review/approval network vào MVP.
4. Không build browser automation runtime như một “agent host”.
5. Không làm command surface phình ra quá sớm chỉ vì hệ flywheel có nhiều tool.

---

## 20) Phase plan mới

## Phase 0 — Boundary, packaging, contract freeze

### Mục tiêu
Khóa boundary hiện tại để khỏi tiếp tục drift.

### Việc làm
- sửa `pyproject.toml` để URLs trỏ đúng repo hiện tại
- explicit exclude `notebooklm_mcp*` khỏi active packaging nếu release chính không cần nó
- giữ package name hiện tại trong MVP nếu cần ổn định cài đặt
- thêm `contracts/capabilities.yaml`
- thêm contract tests cho command map và JSON envelope schema

### Done when
- active product boundary rõ ràng
- docs/package metadata không còn nửa upstream nửa fork

## Phase 1 — Auth/runtime hardening

### Việc làm
- thêm `build_label` vào auth snapshot
- patch token extraction để lấy `bl`
- hợp nhất URL builder
- refresh auth đủ trường
- thêm auth inspect/auth refresh commands
- test retry/auth refresh/build mismatch

### Done when
- mọi RPC chính đều gửi `bl`
- refresh path không còn “nửa session snapshot”

## Phase 2 — SQLite + profile isolation

### Việc làm
- bootstrap DB + migrations
- tạo `profiles`, `auth_snapshots`, `app_state`
- legacy migration mapping
- WAL mode + locks
- `cache status`

### Done when
- local durable state thay được context-only mindset

## Phase 3 — Metadata sync + routeable local-first

### Việc làm
- notebook index sync
- notebook detail sync
- source reconciliation
- invalidation helpers
- `notebook show`
- `source list`
- `sync notebooks`

### Done when
- metadata requests local-first hoạt động ổn định

## Phase 4 — Agent memory + observability

### Việc làm
- `query_runs`, `query_results`, `sync_runs`, `run_events`
- `history search`, `history show`
- `trace show`
- `events tail`
- envelope có `trace_id` và `run_id`

### Done when
- agent có thể nhìn lại, tìm lại, giải thích lại run cũ

## Phase 5 — Workflow commands

### Việc làm
- `ask`
- `overview`
- `summarize`
- `study-guide`
- `audio`
- alias migration layer

### Done when
- structured commands ổn định và machine-friendly

## Phase 6 — Research reshape + router

### Việc làm
- `research start`
- `research wait`
- `research import`
- `agent`
- `route --dry-run`
- `route explain`
- ambiguity handling

### Done when
- NL requests được route có thể giải thích được

## Phase 7 — Safety + doctor + support bundle

### Việc làm
- risk tiers
- approval_requests
- `doctor`
- `doctor --deep`
- `doctor --fix --dry-run`
- `support-bundle create`

### Done when
- hệ thống an toàn và tự chẩn đoán được

---

## 21) Acceptance criteria mới

Bản phát hành được xem là đúng triết lý agent-first khi tất cả điều sau đều đúng:

1. Người dùng login một lần, sau đó tất cả read/write/query/generate/research bình thường chạy qua `httpx`.
2. Session snapshot luôn có `cookies + csrf_token + session_id + build_label`.
3. `notebook list/show`, `source list` có thể trả local-first khi cache còn fresh.
4. `ask`, `overview`, `summarize`, `study-guide`, `audio`, `research start|wait|import` đều ghi run history cục bộ.
5. Mọi command non-trivial đều hỗ trợ `--json` với envelope thống nhất.
6. `agent` phân loại được tối thiểu metadata lookup vs query vs generation vs research.
7. `route --dry-run` và `route explain` giải thích được quyết định routing.
8. `history search` và `trace show` hoạt động được cho run cũ.
9. `doctor` phát hiện được lỗi auth snapshot, DB, path, schema, stale lock.
10. Các lệnh destructive có risk tier và không thể bị agent chạy mù trong non-interactive mode.
11. Packaging/docs đã khoá boundary của active product surface.
12. Không có hard dependency vào browser runtime cho operation thường xuyên.

---

## 22) Open questions cuối cùng cần chốt trước khi code

1. `bl` có luôn extractable từ homepage hiện tại không, hay cần thêm reverse-engineering pass?
2. Có nên thêm `history.store_content=false` như default privacy setting không?
3. `research_id` có đủ ổn định để làm primary handle cho import/wait mọi case không?
4. Có cần `events tail --jsonl` ngay từ MVP không, hay text + JSON là đủ?
5. Approval flow trong non-interactive mode nên dùng token, signed payload, hay chỉ `--yes` theo risk tier?
6. FTS history có bật mặc định không, hay để feature flag cho môi trường nhạy cảm?

---

## 23) Quyết định cuối cùng

### Kết luận dứt khoát
- **Không** nên coi plan cũ là “đã hoàn toàn agent-first”.
- **Có** thể coi nó là nền rất tốt cho một hệ agent-first nếu sửa lại theo bản mới này.

### Câu chốt
Bản đúng không phải là “một CLI có thêm `agent` command”, mà là:

> một hệ NotebookLM local-first, traceable, safe-for-agents, contract-driven, memory-aware,
> trong đó explicit commands và NL routing cùng dùng chung một runtime HTTP, một local DB,
> một routing contract, và một diagnostics/safety model thống nhất.

---

## 24) References used to shape this revision

- `PLAN-CLI.md` đã upload.
- `ledo9124/mcp-notebooklm` branch `notebooklm_cli`.
- Agent Flywheel TL;DR / Flywheel pages.
- OpenAI Agents SDK docs/readme.

