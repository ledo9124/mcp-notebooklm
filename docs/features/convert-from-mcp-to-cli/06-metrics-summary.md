# Operational Metrics

- Feature key: `convert-from-mcp-to-cli`
- Run id: `run-20260312T141020Z-a5fc8e53`
- Generated at: `2026-03-12T14:13:32.028789+00:00`
- Captured from: `RUN_PIPELINE`
- Run status: `HALTED`
- Current step: `none`
- Screen count: 6
- Registered source count: 4
- Validation status: `n/a`
- Metrics history entries: 1

## Metrics

- Average manual edits per screen: 0.0 (`PROXY`)
  Uses standalone `ba.validate_bundle` refreshes as the local-first proxy for manual touch cycles per screen.
- False blocker rate: 0.00% (`PROXY`)
  Treats degraded or halted checkpoints later cleared by a completed run with the same source snapshot fingerprint as false-blocker candidates.
- Rerun scope reduction percentage: n/a (`NOT_APPLICABLE`)
  No incremental rerun decision has been recorded yet.
- Time to first FE spec: n/a (`NOT_AVAILABLE`)
  The bundle has not reached `RENDER_BUNDLE`, so no FE spec has been emitted yet.
- Ungrounded facts caught by QA: n/a (`NOT_AVAILABLE`)
  Validation findings are required before grounding catches can be counted.
- FE-first without later contract breakage percentage: n/a (`NOT_APPLICABLE`)
  No screens are currently being delivered in FE-first provisional mode.

## QA Breakdown

- Findings: 0
- Warnings: 0
- Findings by code: none recorded.

## Notes

- artifact-export-hub: gap `artifact-export-hub-missing_requirement_detail-polling-and-wait-tim-ef3034` has no owner
- artifact-export-hub: gap `artifact-export-hub-missing_requirement_detail-specific-external-ex-e8aa0b` has no owner
- artifact-export-hub: question `artifact-export-hub-q-should-the-cli-artifact--5548dc` has no owner
- artifact-export-hub: question `artifact-export-hub-q-whether-the-cli-should-e-a96970` has no owner
- artifact-export-hub: question `artifact-export-hub-q-will-the-cli-hub-include-f0c9aa` has no owner
- artifact-export-hub: resolved mode CLARIFICATION_FIRST instead of AUTO because shared blockers remain
- chat-interaction-configuration: gap `chat-interaction-configuration-missing_requirement_detail-definition-of-valid--cb1660` has no owner
- chat-interaction-configuration: gap `chat-interaction-configuration-missing_requirement_detail-whether-the-history--b22301` has no owner
- chat-interaction-configuration: question `chat-interaction-configuration-q-does-the-cli-configure-c-a37a42` has no owner
- chat-interaction-configuration: question `chat-interaction-configuration-q-is-note-export-or-note-t-45ebef` has no owner
- chat-interaction-configuration: resolved mode CLARIFICATION_FIRST instead of AUTO because contradictions remain unresolved; shared blockers remain
- cli-source-management-console: gap `cli-source-management-console-missing_requirement_detail-specific-output-form-7dcf09` has no owner
- cli-source-management-console: question `cli-source-management-console-q-does-the-metadata-audit--391d69` has no owner
- cli-source-management-console: question `cli-source-management-console-q-how-to-resolve-the-gap-b-f16f01` has no owner
- cli-source-management-console: question `cli-source-management-console-q-what-is-the-specific-val-4d165d` has no owner
- cli-source-management-console: resolved mode CLARIFICATION_FIRST instead of AUTO because contradictions remain unresolved; shared blockers remain
- global-account-settings: gap `global-account-settings-missing_requirement_detail-information-on-wheth-6c3b62` has no owner
- global-account-settings: gap `global-account-settings-missing_requirement_detail-list-of-specific-lan-1be34e` has no owner
- global-account-settings: question `global-account-settings-q-does-changing-the-global-01942a` has no owner
- global-account-settings: question `global-account-settings-q-what-is-the-default-syst-b3bc35` has no owner
- global-account-settings: resolved mode CLARIFICATION_FIRST instead of AUTO because shared blockers remain
- notebook-note-manager: gap `notebook-note-manager-missing_requirement_detail-current-cli-support--7edaff` has no owner
- notebook-note-manager: gap `notebook-note-manager-missing_requirement_detail-the-full-set-of-crud-1ac2ff` has no owner
- notebook-note-manager: question `notebook-note-manager-q-implementation-status-of-9042d5` has no owner
- notebook-note-manager: question `notebook-note-manager-q-is-note-export-functiona-fd08db` has no owner
- notebook-note-manager: question `notebook-note-manager-q-normalization-of-inconsi-ed09a7` has no owner
- notebook-note-manager: question `notebook-note-manager-q-will-the-ba-adapter-prio-e11e53` has no owner
- notebook-note-manager: resolved mode CLARIFICATION_FIRST instead of AUTO because contradictions remain unresolved; shared blockers remain
- research-pipeline-controller: gap `research-pipeline-controller-missing_requirement_detail-specific-cli-flags-a-201a87` has no owner
- research-pipeline-controller: question `research-pipeline-controller-q-how-to-bridge-the-gap-be-bade94` has no owner
- research-pipeline-controller: question `research-pipeline-controller-q-will-the-cli-implementat-f1136a` has no owner
- research-pipeline-controller: resolved mode CLARIFICATION_FIRST instead of AUTO because contradictions remain unresolved; shared blockers remain

## Recent History

- `2026-03-12T14:13:32.028789+00:00` source=`RUN_PIPELINE` status=`HALTED` validation=`n/a`
