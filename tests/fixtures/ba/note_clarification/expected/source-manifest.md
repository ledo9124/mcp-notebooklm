# Source Manifest

- Feature key: `customer-create`
- Run id: `run-note-golden`
- Schema version: `ba.source_manifest.v1.0`
- Source count: 3
- Status counts: `REGISTERED`=3
- Parse quality counts: `HIGH`=3

## Sources

| Source Key | Title | Type | Priority | Status | Quality | Freshness | Snapshot |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `requirements` | Customer Create Requirements | `PRIMARY_REQUIREMENT` | `REQUIRED` | `REGISTERED` | `HIGH` | `fresh` | `requirements-note-001` |
| `glossary` | Customer Create Glossary | `SUPPORTING_GLOSSARY` | `NORMAL` | `REGISTERED` | `HIGH` | `fresh` | `glossary-note-001` |
| `clarification-note` | Supporting Clarification Note | `SUPPORTING_CLARIFICATION` | `HIGH` | `REGISTERED` | `HIGH` | `fresh` | `clarification-note-001` |

## Warnings

- supporting clarification remains subordinate to contradictory future primary evidence

## Details

### `requirements`

- Title: Customer Create Requirements
- Source ref: `tests/fixtures/ba/note_clarification/sources/requirements.md`
- Content kind: `FILE_PATH`
- Source type: `PRIMARY_REQUIREMENT`
- Priority: `REQUIRED`
- Status: `REGISTERED`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `requirements-note-001`
- Notebook source id: `nb-requirements`
- Notes: _none_
- Used in screens: `customer-form`, `customer-review`

### `glossary`

- Title: Customer Create Glossary
- Source ref: `tests/fixtures/ba/note_clarification/sources/glossary.md`
- Content kind: `FILE_PATH`
- Source type: `SUPPORTING_GLOSSARY`
- Priority: `NORMAL`
- Status: `REGISTERED`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `glossary-note-001`
- Notebook source id: `nb-glossary`
- Notes: _none_
- Used in screens: `customer-form`, `customer-review`

### `clarification-note`

- Title: Supporting Clarification Note
- Source ref: `tests/fixtures/ba/note_clarification/notes/clarification-note.md`
- Content kind: `FILE_PATH`
- Source type: `SUPPORTING_CLARIFICATION`
- Priority: `HIGH`
- Status: `REGISTERED`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `clarification-note-001`
- Notebook source id: `nb-clarification-note`
- Notes: Curated from NotebookLM note review.
- Used in screens: `customer-form`, `customer-review`
