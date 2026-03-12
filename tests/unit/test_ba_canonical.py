"""Unit tests for BA canonical screen extraction and persistence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from notebooklm_mcp.ba.extraction import (
    CanonicalScreenExtractionResult,
    StructuredParseQuality,
    extract_canonical_screen,
)
from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    GapKind,
    ParseQuality,
    ScreenCatalogEntry,
    SourceContentKind,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceType,
    TerminologyDocument,
    TerminologyEntry,
    WorkflowMode,
)
from notebooklm_mcp.ba.run_store import BARunStore


def _manifest() -> SourceManifestDocument:
    return SourceManifestDocument(
        feature_key="customer-create",
        run_id="run-013",
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


def _screen() -> ScreenCatalogEntry:
    return ScreenCatalogEntry(
        screen_id="customer-form",
        screen_name="Customer Form",
        purpose="Create a customer record",
        dependencies=["Customer Number"],
    )


def _terminology() -> TerminologyDocument:
    return TerminologyDocument(
        run_id="run-013",
        feature_key="customer-create",
        entries=[
            TerminologyEntry(
                standard_term="Customer ID",
                aliases=["Customer Number"],
                evidence=[
                    EvidenceRef(
                        source_key="requirements",
                        snapshot_id="requirements-abc123",
                        locator="10-20",
                    )
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_extract_canonical_screen_normalizes_fact_sets_and_quality() -> None:
    async def _fake_ask(
        prompt_text: str,
        *,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        assert "customer-form" in prompt_text
        assert source_ids == ["src-1"]
        assert conversation_id == "conv-30"
        return SimpleNamespace(
            answer=json.dumps(
                {
                    "shared_facts": [
                        {
                            "category": "business_rule",
                            "value": "Customer email must be unique",
                            "status": "CONFIRMED",
                            "confidence": 0.92,
                        }
                    ],
                    "fe_facts": [
                        {
                            "category": "field",
                            "value": "Show loyalty tier badge",
                            "status": "PROVISIONAL",
                            "note": "Mentioned in workshop notes",
                        }
                    ],
                    "be_facts": [
                        {
                            "category": "endpoint",
                            "value": "/customers",
                            "status": "CONFIRMED",
                        }
                    ],
                    "dependencies": ["Customer Number"],
                    "contradictions": [
                        {
                            "summary": "Email uniqueness timing is unclear",
                            "claims": [
                                {"claim": "Validate on every keystroke"},
                                {"claim": "Validate only on submit"},
                            ],
                            "open_question": "When should uniqueness be enforced?",
                        }
                    ],
                    "missing_info": [
                        {
                            "kind": "MISSING_BACKEND_CONTRACT",
                            "summary": "Duplicate-email response body shape is missing",
                            "severity": "HIGH",
                            "workstreams": ["BE", "FE"],
                        }
                    ],
                    "open_questions": ["Should draft customers be autosaved?"],
                    "quality_summary": {
                        "parse_quality": "HIGH",
                        "notes": ["Grounded in the primary requirement"],
                        "degraded": False,
                    },
                }
            ),
            citations=(
                SimpleNamespace(
                    source_id="src-1",
                    quote="Customer creation requires a unique email and persists a customer record.",
                    location="12-30",
                ),
            ),
            conversation_id="conv-31",
            turn_number=4,
            is_follow_up=True,
        )

    result = await extract_canonical_screen(
        _fake_ask,
        feature_key="customer-create",
        run_id="run-013",
        screen=_screen(),
        manifest=_manifest(),
        mode=WorkflowMode.BALANCED,
        source_scope="requirements/ba.pdf",
        terminology=_terminology(),
        source_ids=("src-1",),
        conversation_id="conv-30",
    )

    assert isinstance(result, CanonicalScreenExtractionResult)
    assert result.parse_quality is StructuredParseQuality.EXACT
    assert result.conversation_id == "conv-31"

    canonical = result.screen
    assert canonical.mode is WorkflowMode.BALANCED
    assert canonical.shared_facts[0].status is FactStatus.CONFIRMED
    assert canonical.shared_facts[0].evidence[0].snapshot_id == "requirements-abc123"
    assert canonical.fe_facts[0].status is FactStatus.PROVISIONAL
    assert canonical.fe_facts[0].rationale == "Mentioned in workshop notes"
    assert canonical.fe_facts[0].origin == "structured_extraction"
    assert canonical.dependencies == ["Customer ID"]
    assert len(canonical.contradictions[0].claims) == 2
    assert canonical.missing_info[0].kind is GapKind.MISSING_BACKEND_CONTRACT
    assert canonical.quality_summary.parse_quality is ParseQuality.HIGH
    assert canonical.open_questions[0].question_id.startswith("customer-form-q-")
    assert any("fallback rationale" in warning for warning in result.warnings)
    assert any("fallback origin" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_extract_canonical_screen_downgrades_confirmed_facts_without_evidence() -> None:
    async def _fake_ask(
        prompt_text: str,
        *,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            answer=json.dumps(
                {
                    "shared_facts": [
                        {
                            "category": "business_rule",
                            "value": "Customer tax ID must be validated against the upstream registry",
                            "status": "CONFIRMED",
                        }
                    ]
                }
            ),
            citations=(),
            conversation_id="conv-32",
            turn_number=1,
            is_follow_up=False,
        )

    result = await extract_canonical_screen(
        _fake_ask,
        feature_key="customer-create",
        run_id="run-013",
        screen=_screen(),
        manifest=_manifest(),
        mode=WorkflowMode.BALANCED,
        source_scope="requirements/ba.pdf",
    )

    fact = result.screen.shared_facts[0]
    assert fact.status is FactStatus.PROVISIONAL
    assert fact.rationale == "missing normalized evidence for confirmation"
    assert fact.origin == "structured_extraction"
    assert any("downgraded to PROVISIONAL" in warning for warning in result.warnings)


def test_run_store_persists_and_loads_canonical_screen(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-013",
    )
    store.create()
    screen = CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.BALANCED,
        run_id="run-013",
        shared_facts=[
            CanonicalFact(
                fact_id="customer-form-shared-business-rule-abc123",
                domain=FactDomain.SHARED,
                category="business_rule",
                value="Customer email must be unique",
                status=FactStatus.CONFIRMED,
                evidence=[
                    EvidenceRef(
                        source_key="requirements",
                        snapshot_id="requirements-abc123",
                        locator="12-30",
                    )
                ],
            )
        ],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )

    store.save_canonical_screen(screen)

    loaded = store.load_canonical_screen("customer-form")
    assert loaded.shared_facts[0].fact_id == "customer-form-shared-business-rule-abc123"
    assert store.screen_paths("customer-form").canonical_json.exists()
