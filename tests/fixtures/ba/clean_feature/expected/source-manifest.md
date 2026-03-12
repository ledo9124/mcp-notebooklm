# Source Manifest

- Feature key: `customer-create`
- Run id: `run-clean-golden`
- Schema version: `ba.source_manifest.v1.0`
- Source count: 3
- Status counts: `REGISTERED`=3
- Parse quality counts: `HIGH`=3

## Sources

| Source Key | Title | Type | Priority | Status | Quality | Freshness | Snapshot |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `requirements` | Customer Create Requirements | `PRIMARY_REQUIREMENT` | `REQUIRED` | `REGISTERED` | `HIGH` | `fresh` | `requirements-clean-001` |
| `api-contract` | Customer Create API Contract | `PRIMARY_CONTRACT` | `REQUIRED` | `REGISTERED` | `HIGH` | `fresh` | `api-contract-clean-001` |
| `glossary` | Customer Create Glossary | `SUPPORTING_GLOSSARY` | `NORMAL` | `REGISTERED` | `HIGH` | `fresh` | `glossary-clean-001` |

## Details

### `requirements`

- Title: Customer Create Requirements
- Source ref: `tests/fixtures/ba/clean_feature/sources/requirements.md`
- Content kind: `FILE_PATH`
- Source type: `PRIMARY_REQUIREMENT`
- Priority: `REQUIRED`
- Status: `REGISTERED`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `requirements-clean-001`
- Notebook source id: `nb-requirements`
- Notes: _none_
- Used in screens: `customer-form`, `customer-list`

### `api-contract`

- Title: Customer Create API Contract
- Source ref: `tests/fixtures/ba/clean_feature/sources/api-contract.md`
- Content kind: `FILE_PATH`
- Source type: `PRIMARY_CONTRACT`
- Priority: `REQUIRED`
- Status: `REGISTERED`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `api-contract-clean-001`
- Notebook source id: `nb-api-contract`
- Notes: _none_
- Used in screens: `customer-form`, `customer-list`

### `glossary`

- Title: Customer Create Glossary
- Source ref: `tests/fixtures/ba/clean_feature/sources/glossary.md`
- Content kind: `FILE_PATH`
- Source type: `SUPPORTING_GLOSSARY`
- Priority: `NORMAL`
- Status: `REGISTERED`
- Parse quality: `HIGH`
- Freshness: `fresh`
- Snapshot id: `glossary-clean-001`
- Notebook source id: `nb-glossary`
- Notes: _none_
- Used in screens: `customer-form`, `customer-list`
