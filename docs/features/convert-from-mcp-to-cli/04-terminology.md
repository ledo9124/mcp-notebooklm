# Terminology

- Feature key: `convert-from-mcp-to-cli`
- Run id: `run-20260312T141020Z-a5fc8e53`
- Schema version: `ba.terminology.v1.0`
- Term count: 11
- Alias count: 0
- Ambiguous terms: 11

## Terms

| Standard Term | Aliases | Ambiguity Flags | Evidence |
| --- | --- | --- | --- |
| `Artifact` | _none_ | alias_requires_evidence:Data-table, alias_requires_evidence:Mind-map, alias_requires_evidence:Report, The entire artifact lifecycle is present in the SDK and CLI but is currently unregistered in the MCP server [7], [11]. | `0` |
| `BA runner` | _none_ | alias_requires_evidence:BA, alias_requires_evidence:BA-runner | `0` |
| `Capability adapter` | _none_ | alias_requires_evidence:BA adapter, alias_requires_evidence:BA capability adapter | `0` |
| `CLI` | _none_ | alias_requires_evidence:CLI-native entry points, alias_requires_evidence:src/notebooklm/cli/ | `0` |
| `MCP` | _none_ | alias_requires_evidence:MCP layer, alias_requires_evidence:MCP-oriented surfaces, alias_requires_evidence:src/notebooklm_mcp/ | `0` |
| `Note` | _none_ | alias_requires_evidence:Notebook note, alias_requires_evidence:Real notebook note, Current MCP implementation is inconsistent; the workflow macro creates 'text sources' while labeling them as notes [6], [7], [9]. | `0` |
| `Output language` | _none_ | alias_requires_evidence:Account-global setting, alias_requires_evidence:Global output language, This capability is fully supported in the SDK and CLI but is entirely absent from the MCP surface [6], [7]. | `0` |
| `Research` | _none_ | alias_requires_evidence:Direct research controls, alias_requires_evidence:Research primitives, MCP only exposes a high-level 'macro' workflow, whereas the CLI provides raw access to underlying primitives [7], [10]. | `0` |
| `SDK` | _none_ | alias_requires_evidence:notebooklm-py, alias_requires_evidence:NotebookLMClient, alias_requires_evidence:SDK substrate | `0` |
| `Source` | _none_ | alias_requires_evidence:notebooklm_sources, alias_requires_evidence:Source intelligence, MCP content access is 'preview-capped' (truncated), whereas the CLI and SDK provide 'fulltext' access required for high-fidelity snapshotting [7], [8]. | `0` |
| `Text source` | _none_ | alias_requires_evidence:Research note, The term 'research note' is used in MCP workflow tools to describe what is technically a text source, colliding with the 'note' entity semantics [6], [9]. | `0` |

## Details

### `Artifact`

- Aliases: _none_
- Semantic notes: Generated outputs such as reports, data tables, and mind maps derived from notebook data [6], [7], [11].
- Ambiguity flags: alias_requires_evidence:Data-table, alias_requires_evidence:Mind-map, alias_requires_evidence:Report, The entire artifact lifecycle is present in the SDK and CLI but is currently unregistered in the MCP server [7], [11].
- Evidence: _none_

### `BA runner`

- Aliases: _none_
- Semantic notes: A planned subsystem (src/notebooklm_mcp/ba/) designed to automate analyst workflows by leveraging the NotebookLM SDK substrate [1], [2].
- Ambiguity flags: alias_requires_evidence:BA, alias_requires_evidence:BA-runner
- Evidence: _none_

### `Capability adapter`

- Aliases: _none_
- Semantic notes: A proposed architectural layer that wraps the NotebookLMClient directly to provide capabilities missing from the generic MCP tool set [1], [3], [2].
- Ambiguity flags: alias_requires_evidence:BA adapter, alias_requires_evidence:BA capability adapter
- Evidence: _none_

### `CLI`

- Aliases: _none_
- Semantic notes: A Click-based wrapper over the SDK that currently exposes significantly more functionality than the MCP layer [4], [5].
- Ambiguity flags: alias_requires_evidence:CLI-native entry points, alias_requires_evidence:src/notebooklm/cli/
- Evidence: _none_

### `MCP`

- Aliases: _none_
- Semantic notes: The FastMCP server implementation that exposes a narrow subset of SDK functionality via tools, resources, and prompts [4], [5], [2].
- Ambiguity flags: alias_requires_evidence:MCP layer, alias_requires_evidence:MCP-oriented surfaces, alias_requires_evidence:src/notebooklm_mcp/
- Evidence: _none_

### `Note`

- Aliases: _none_
- Semantic notes: First-class CRUD objects within a notebook, distinct from source content [6], [7].
- Ambiguity flags: alias_requires_evidence:Notebook note, alias_requires_evidence:Real notebook note, Current MCP implementation is inconsistent; the workflow macro creates 'text sources' while labeling them as notes [6], [7], [9].
- Evidence: _none_

### `Output language`

- Aliases: _none_
- Semantic notes: A global user setting that determines the language used for generated content [6], [7], [10].
- Ambiguity flags: alias_requires_evidence:Account-global setting, alias_requires_evidence:Global output language, This capability is fully supported in the SDK and CLI but is entirely absent from the MCP surface [6], [7].
- Evidence: _none_

### `Research`

- Aliases: _none_
- Semantic notes: Granular controls for starting discovery, polling status, and importing results [7], [10].
- Ambiguity flags: alias_requires_evidence:Direct research controls, alias_requires_evidence:Research primitives, MCP only exposes a high-level 'macro' workflow, whereas the CLI provides raw access to underlying primitives [7], [10].
- Evidence: _none_

### `SDK`

- Aliases: _none_
- Semantic notes: The core implementation layer (src/notebooklm/) that provides the real substrate for both the CLI and MCP interfaces [4], [2].
- Ambiguity flags: alias_requires_evidence:notebooklm-py, alias_requires_evidence:NotebookLMClient, alias_requires_evidence:SDK substrate
- Evidence: _none_

### `Source`

- Aliases: _none_
- Semantic notes: Grounding data entities, including operations for Drive ingestion, refreshing, and freshness checking [6], [7].
- Ambiguity flags: alias_requires_evidence:notebooklm_sources, alias_requires_evidence:Source intelligence, MCP content access is 'preview-capped' (truncated), whereas the CLI and SDK provide 'fulltext' access required for high-fidelity snapshotting [7], [8].
- Evidence: _none_

### `Text source`

- Aliases: _none_
- Semantic notes: A source created from synthesized text via the add_text() method [7], [9].
- Ambiguity flags: alias_requires_evidence:Research note, The term 'research note' is used in MCP workflow tools to describe what is technically a text source, colliding with the 'note' entity semantics [6], [9].
- Evidence: _none_
