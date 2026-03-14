# Chat Settings Manual Verification Checklist

Status: legacy/frozen manual checklist.

Manual checklist for validating chat settings parity between `notebooklm-py` and the NotebookLM Web UI.

This document is retained as historical reference only. The standalone
`notebooklm configure ...` surface it validates is no longer part of the active
mainline CLI MVP on this branch.

## Preconditions

- You are authenticated (`notebooklm login` completed).
- You have a disposable notebook ID available.
- You can open the same notebook in NotebookLM Web.

## Smoke Lifecycle (CLI + Python)

1. Create a temporary notebook:
   ```bash
   notebooklm create "Chat Settings Smoke"
   ```
2. Set custom style + instructions + length:
   ```bash
   notebooklm configure -n <NOTEBOOK_ID> \
     --style custom \
     --custom-instructions "Teach with short steps and one example." \
     --length longer
   ```
3. Verify current state from CLI:
   ```bash
   notebooklm configure -n <NOTEBOOK_ID> --show --json
   ```
   Expected:
   - `goal = "custom"`
   - `response_length = "longer"`
   - `custom_prompt_len > 0`
4. Change only length (PATCH semantics):
   ```bash
   notebooklm configure -n <NOTEBOOK_ID> --length shorter
   notebooklm configure -n <NOTEBOOK_ID> --show --json
   ```
   Expected:
   - `goal` remains `"custom"`
   - `response_length = "shorter"`
5. Reset settings:
   ```bash
   notebooklm configure -n <NOTEBOOK_ID> --reset
   notebooklm configure -n <NOTEBOOK_ID> --show --json
   ```
   Expected:
   - `goal = "default"`
   - `response_length = "default"`
   - `custom_prompt = null`

## Web UI Parity Checks

- Open the same notebook in NotebookLM Web.
- Confirm style selection matches CLI/Python actions:
  - Custom after step 2.
  - Still Custom after step 4 (length-only update).
  - Default after step 5 reset.
- Confirm response length matches CLI/Python actions:
  - Longer after step 2.
  - Shorter after step 4.
  - Default after step 5.
- Confirm custom instructions visibility:
  - Present after step 2.
  - Still present after step 4.
  - Cleared after step 5.

## Known Safety Rules to Validate

- `--show` and `--reset` together should fail.
- `--custom-instructions` with `--style default` or `--style learning-guide` should fail.
- `--mode learning-guide --length shorter` should apply both values (no early return bug).

## Cleanup

```bash
notebooklm delete -n <NOTEBOOK_ID> --yes
```
