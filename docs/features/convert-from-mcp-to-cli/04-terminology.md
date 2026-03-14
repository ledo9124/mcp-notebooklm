# Terminology

- Feature key: `convert-from-mcp-to-cli`
- Run id: `run-20260312T141020Z-a5fc8e53`
- Schema version: `ba.terminology.v1.0`
- Term count: 15
- Alias count: 19
- Ambiguous terms: 4

## Terms

| Standard Term | Aliases | Ambiguity Flags | Evidence |
| --- | --- | --- | --- |
| `artifact async controls` | canonical reusable async control path | _none_ | `14` |
| `artifact download` | local filesystem output | _none_ | `14` |
| `artifact export` | export API | _none_ | `14` |
| `BA capability adapter` | BA adapter, capability adapter | _none_ | `14` |
| `full source text` | fulltext | _none_ | `14` |
| `global output language` | account-global settings | _none_ | `14` |
| `note export` | export_note | Explicitly unsupported in the current CLI and excluded from the note-manager scope [10, 11, 14]. | `14` |
| `note-to-source conversion` | note-to-source bridge | Not currently implemented as a first-class public code surface or CLI action [4, 10]. | `14` |
| `notebook chat settings` | chat interaction configuration | _none_ | `14` |
| `notebook note` | real note | _none_ | `14` |
| `NotebookLMClient` | main facade, SDK substrate | _none_ | `14` |
| `research primitives` | research lifecycle | _none_ | `14` |
| `source audit` | metadata audit, structural snapshot | The term 'audit' refers to structural snapshots; 'access-log' style semantics are explicitly not supported [5, 6]. | `14` |
| `source content preview` | capped preview | _none_ | `14` |
| `text source` | research note, synthesized source | The MCP workflow helper 'notebooklm_workflow_research' calls this a 'note', creating a collision with real notebook notes [4, 9, 11]. | `14` |

## Details

### `artifact async controls`

- Aliases: canonical reusable async control path
- Semantic notes: The standardized CLI contract for managing long-running artifact tasks via 'artifact poll' and 'artifact wait' [13, 14].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `artifact download`

- Aliases: local filesystem output
- Semantic notes: The process of saving artifact content directly to the user's local machine [13].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `artifact export`

- Aliases: export API
- Semantic notes: The process of sending generated artifacts (reports, data tables) to external cloud destinations, specifically Google Docs or Google Sheets [7, 13].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `BA capability adapter`

- Aliases: BA adapter, capability adapter
- Semantic notes: A dedicated subsystem located in src/notebooklm_mcp/ba/ designed to wrap the SDK directly [2, 3]. It bypasses the narrow MCP tool surface to provide full-fidelity access for the BA runner [3, 4].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `full source text`

- Aliases: fulltext
- Semantic notes: The complete, untruncated content of a source retrieved via the SDK [7, 8]. Required for deterministic BA snapshotting to avoid the truncation found in MCP [6, 8].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `global output language`

- Aliases: account-global settings
- Semantic notes: An account-wide setting (not notebook-scoped) that determines the language for newly generated artifacts [5, 7, 10].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `note export`

- Aliases: export_note
- Semantic notes: The capability to export notes to external formats or destinations [4, 11].
- Ambiguity flags: Explicitly unsupported in the current CLI and excluded from the note-manager scope [10, 11, 14].
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `note-to-source conversion`

- Aliases: note-to-source bridge
- Semantic notes: An explicit bridge where a notebook note's content is used to create a new text source [7, 10, 11].
- Ambiguity flags: Not currently implemented as a first-class public code surface or CLI action [4, 10].
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `notebook chat settings`

- Aliases: chat interaction configuration
- Semantic notes: Configurable parameters for the notebook chat, including 'goal' (style), 'response length', and 'custom prompt' [6, 7, 14].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `notebook note`

- Aliases: real note
- Semantic notes: A first-class object created within a notebook using the notes.create() SDK method [6, 7, 9].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `NotebookLMClient`

- Aliases: main facade, SDK substrate
- Semantic notes: The central programmatic interface in src/notebooklm/client.py that exposes namespaced APIs like notebooks, sources, and chat [1]. It serves as the real substrate for both the SDK and CLI [1].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `research primitives`

- Aliases: research lifecycle
- Semantic notes: The low-level SDK/CLI controls for research: start, poll (or status), and import_sources [7, 11, 12].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `source audit`

- Aliases: metadata audit, structural snapshot
- Semantic notes: A structural record of source metadata and readiness, including fields such as source_id, status, is_ready, and is_fresh [5, 6].
- Ambiguity flags: The term 'audit' refers to structural snapshots; 'access-log' style semantics are explicitly not supported [5, 6].
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `source content preview`

- Aliases: capped preview
- Semantic notes: The truncated version of source content provided by existing MCP tools and resources, typically capped at 50,000 characters [6-8].
- Ambiguity flags: _none_
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"

### `text source`

- Aliases: research note, synthesized source
- Semantic notes: A source created from raw text using sources.add_text() [7, 9, 10].
- Ambiguity flags: The MCP workflow helper 'notebooklm_workflow_research' calls this a 'note', creating a collision with real notebook notes [4, 9, 11].
- Evidence:
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `1515-1782` / "Bottom line: the SDK/CLI already contain most of the raw functionality the BA runner wants, but the MCP layer only exposes a narrow subset. The BA runner should be built around a capability adapter over NotebookLMClient , not around the current MCP tool surface as-is."
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `2633-2659` / "Recommended Priority Order"
  - `ba-runner-parity-audit-inline` / `ba-runner-parity-audit-inline-8ad4ab75796b` / `580-600` / "Architecture Summary"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `0-32` / "Phase 0 Capability Parity Matrix"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `1593-6289`
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6289-6309` / "High-Signal Findings"
  - `phase0-parity-matrix-inline` / `phase0-parity-matrix-inline-0e41b635cf12` / `6844-6956` / "src/notebooklm_mcp/tools/chat.py::notebooklm_chat_ask() can save a real notebook note via client.notes.create() ."
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `0-49` / "Resolved BA decisions for convert-from-mcp-to-cli"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `1157-1178` / "notebook-note-manager"
  - `resolved-ba-decisions-20260312` / `resolved-ba-decisions-20260312-e270f0021cfa` / `648-677` / "cli-source-management-console"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `0-63` / "Resolved repo-backed clarifications for convert-from-mcp-to-cli"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `1496-1519` / "global-account-settings"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `2195-2223` / "research-pipeline-controller"
  - `resolved-repo-backed-clarifications-20260312` / `resolved-repo-backed-clarifications-20260312-3e848131ba61` / `566-596` / "chat-interaction-configuration"
