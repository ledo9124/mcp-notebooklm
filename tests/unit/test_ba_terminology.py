"""Unit tests for BA terminology extraction, rendering, and persistence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from notebooklm_mcp.ba.extraction import (
    StructuredParseQuality,
    build_terminology_lookup,
    canonicalize_term,
    extract_terminology_document,
)
from notebooklm_mcp.ba.models import (
    EvidenceRef,
    SourceContentKind,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceType,
    TerminologyDocument,
    TerminologyEntry,
)
from notebooklm_mcp.ba.rendering import (
    render_terminology_json,
    render_terminology_markdown,
)
from notebooklm_mcp.ba.run_store import BARunStore


def _manifest() -> SourceManifestDocument:
    return SourceManifestDocument(
        feature_key="customer-create",
        run_id="run-011",
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref="requirements/ba.pdf",
                notebook_source_id="src-1",
                snapshot_id="requirements-abc123",
                title="Requirements PDF",
            )
        ],
    )


@pytest.mark.asyncio
async def test_extract_terminology_document_merges_duplicates_and_preserves_collisions() -> None:
    async def _fake_ask(
        prompt_text: str,
        *,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        assert "customer-create" in prompt_text
        assert source_ids == ["src-1"]
        assert conversation_id == "conv-11"
        return SimpleNamespace(
            answer=json.dumps(
                {
                    "entries": [
                        {
                            "term": "Customer ID",
                            "aliases": ["Customer Number", "ID"],
                            "notes": ["Displayed in onboarding"],
                        },
                        {
                            "standard_term": "customer id",
                            "aliases": ["Cust ID"],
                            "semantic_notes": ["Stable external identifier"],
                        },
                        {
                            "canonical_term": "Account ID",
                            "aliases": ["ID"],
                            "ambiguity_flags": ["Could refer to billing account number"],
                        },
                    ]
                }
            ),
            citations=(
                SimpleNamespace(
                    source_id="src-1",
                    quote="Customer ID and Customer Number refer to the same identifier.",
                    location="12-30",
                ),
            ),
            conversation_id="conv-12",
            turn_number=2,
            is_follow_up=False,
        )

    result = await extract_terminology_document(
        _fake_ask,
        feature_key="customer-create",
        run_id="run-011",
        manifest=_manifest(),
        source_scope="requirements/ba.pdf",
        source_ids=("src-1",),
        conversation_id="conv-11",
    )

    assert result.parse_quality is StructuredParseQuality.EXACT
    assert result.warnings == ()
    assert result.conversation_id == "conv-12"
    assert [entry.standard_term for entry in result.document.entries] == [
        "Account ID",
        "Customer ID",
    ]

    account_id, customer_id = result.document.entries
    assert account_id.ambiguity_flags == [
        "alias_collision:ID",
        "Could refer to billing account number",
    ]
    assert customer_id.aliases == ["Cust ID", "Customer Number", "ID"]
    assert customer_id.semantic_notes == [
        "Displayed in onboarding",
        "Stable external identifier",
    ]
    assert customer_id.ambiguity_flags == ["alias_collision:ID"]
    assert customer_id.evidence[0].snapshot_id == "requirements-abc123"

    lookup = build_terminology_lookup(result.document)
    assert lookup["customer number"] == "Customer ID"
    assert lookup["cust id"] == "Customer ID"
    assert "id" not in lookup
    assert canonicalize_term("Customer Number", result.document) == "Customer ID"
    assert canonicalize_term("ID", result.document) is None


@pytest.mark.asyncio
async def test_extract_terminology_document_downgrades_alias_merges_without_evidence() -> None:
    async def _fake_ask(
        prompt_text: str,
        *,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            answer=json.dumps(
                {
                    "entries": [
                        {
                            "term": "Customer ID",
                            "aliases": ["Customer Number"],
                        }
                    ]
                }
            ),
            citations=(),
            conversation_id="conv-13",
            turn_number=1,
            is_follow_up=False,
        )

    result = await extract_terminology_document(
        _fake_ask,
        feature_key="customer-create",
        run_id="run-011",
        manifest=_manifest(),
        source_scope="requirements/ba.pdf",
    )

    assert result.document.entries[0].aliases == []
    assert result.document.entries[0].ambiguity_flags == [
        "alias_requires_evidence:Customer Number"
    ]
    assert result.warnings == (
        "one or more alias merges were downgraded to ambiguity flags because no normalized evidence was available",
    )
    assert canonicalize_term("Customer Number", result.document) is None


def test_render_and_persist_terminology_artifacts(tmp_path: Path) -> None:
    document = TerminologyDocument(
        run_id="run-011",
        feature_key="customer-create",
        entries=[
            TerminologyEntry(
                standard_term="Customer ID",
                aliases=["Customer Number"],
                semantic_notes=["Stable external identifier"],
                ambiguity_flags=["legacy term still appears in older BA notes"],
                evidence=[
                    EvidenceRef(
                        source_key="requirements",
                        snapshot_id="requirements-abc123",
                        locator="12-30",
                        quote="Customer Number refers to the same field as Customer ID.",
                    )
                ],
            )
        ],
    )

    markdown = render_terminology_markdown(document)
    payload = json.loads(render_terminology_json(document))

    assert markdown.startswith("# Terminology\n")
    assert "## Terms" in markdown
    assert "| `Customer ID` | Customer Number | legacy term still appears in older BA notes | `1` |" in markdown
    assert "`requirements` / `requirements-abc123` / `12-30`" in markdown
    assert payload["entries"][0]["standard_term"] == "Customer ID"
    assert payload["entries"][0]["aliases"] == ["Customer Number"]

    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-011",
    )
    store.create()
    store.save_terminology_artifacts(document, markdown=markdown)

    assert store.load_terminology().entries[0].standard_term == "Customer ID"
    assert store.load_terminology_markdown() == markdown
    assert store.feature_paths.terminology_json.exists()
    assert store.feature_paths.terminology_markdown.exists()
