# Operational Metrics

- Feature key: `convert-from-mcp-to-cli`
- Run id: `run-20260312T141020Z-a5fc8e53`
- Generated at: `2026-03-12T14:49:23.684764+00:00`
- Captured from: `RUN_PIPELINE`
- Run status: `HALTED`
- Current step: `none`
- Screen count: 6
- Registered source count: 6
- Validation status: `n/a`
- Metrics history entries: 2

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

- screen[1] 'CLI Source Management Console' has no normalized evidence; catalog entry remains provisional
- screen[2] 'Chat Interaction Configuration' has no normalized evidence; catalog entry remains provisional
- screen[3] 'Notebook Note Manager' has no normalized evidence; catalog entry remains provisional
- screen[4] 'Global Account Settings' has no normalized evidence; catalog entry remains provisional
- screen[5] 'Research Pipeline Controller' has no normalized evidence; catalog entry remains provisional
- screen[6] 'Artifact Export Hub' has no normalized evidence; catalog entry remains provisional
- SHARED fact[1] downgraded to PROVISIONAL because no normalized evidence was available
- SHARED fact[2] downgraded to PROVISIONAL because no normalized evidence was available
- SHARED fact[3] downgraded to PROVISIONAL because no normalized evidence was available
- SHARED fact[4] downgraded to PROVISIONAL because no normalized evidence was available
- FE fact[1] downgraded to PROVISIONAL because no normalized evidence was available
- FE fact[2] downgraded to PROVISIONAL because no normalized evidence was available
- FE fact[3] downgraded to PROVISIONAL because no normalized evidence was available
- FE fact[4] downgraded to PROVISIONAL because no normalized evidence was available
- BE fact[1] downgraded to PROVISIONAL because no normalized evidence was available
- BE fact[2] downgraded to PROVISIONAL because no normalized evidence was available
- BE fact[3] downgraded to PROVISIONAL because no normalized evidence was available
- BE fact[4] downgraded to PROVISIONAL because no normalized evidence was available
- SHARED fact[5] downgraded to PROVISIONAL because no normalized evidence was available
- FE fact[5] downgraded to PROVISIONAL because no normalized evidence was available

## Recent History

- `2026-03-12T14:13:32.028789+00:00` source=`RUN_PIPELINE` status=`HALTED` validation=`n/a`
- `2026-03-12T14:49:23.684764+00:00` source=`RUN_PIPELINE` status=`HALTED` validation=`n/a`
