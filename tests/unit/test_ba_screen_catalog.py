"""Unit tests for BA screen-catalog extraction and persistence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from notebooklm_mcp.ba.extraction import (
    ScreenCatalogExtractionResult,
    StructuredParseQuality,
    extract_screen_catalog_document,
)
from notebooklm_mcp.ba.models import (
    EvidenceRef,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    SourceContentKind,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceType,
    TerminologyDocument,
    TerminologyEntry,
)
from notebooklm_mcp.ba.run_store import BARunStore


def _manifest() -> SourceManifestDocument:
    return SourceManifestDocument(
        feature_key="customer-create",
        run_id="run-012",
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


def _terminology() -> TerminologyDocument:
    return TerminologyDocument(
        run_id="run-012",
        feature_key="customer-create",
        entries=[
            TerminologyEntry(
                standard_term="Customer Service Representative",
                aliases=["CSR"],
                evidence=[
                    EvidenceRef(
                        source_key="requirements",
                        snapshot_id="requirements-abc123",
                        locator="10-20",
                    )
                ],
            ),
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
            ),
        ],
    )


def _prior_catalog() -> ScreenCatalogDocument:
    return ScreenCatalogDocument(
        run_id="run-011",
        feature_key="customer-create",
        screens=[
            ScreenCatalogEntry(
                screen_id="customer-form",
                screen_name="Customer Form",
                purpose="Create a customer record",
            )
        ],
    )


@pytest.mark.asyncio
async def test_extract_screen_catalog_document_reuses_prior_ids_and_normalizes_terms() -> None:
    async def _fake_ask(
        prompt_text: str,
        *,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        assert "Candidate screen hints: Customer Form" in prompt_text
        assert source_ids == ["src-1"]
        assert conversation_id == "conv-20"
        return SimpleNamespace(
            answer=json.dumps(
                {
                    "screens": [
                        {
                            "screen_name": "Customer Form",
                            "purpose": "Create a customer record",
                            "roles": ["CSR"],
                            "entry_points": ["New Customer"],
                            "exit_points": ["Customer Detail"],
                            "main_actions": ["Save Customer"],
                            "dependencies": ["Customer Number"],
                            "related_sources": ["src-1"],
                            "open_questions": [
                                "Should archived customers be restorable from this form?"
                            ],
                        },
                        {
                            "screen_name": "Customer Detail",
                            "purpose": "Review the saved customer profile",
                            "roles": ["CSR"],
                            "entry_points": ["Customer Form"],
                            "exit_points": ["Edit Customer"],
                            "main_actions": ["Edit Customer"],
                            "related_sources": ["Requirements PDF"],
                        },
                    ]
                }
            ),
            citations=(
                SimpleNamespace(
                    source_id="src-1",
                    quote="The flow starts on the customer form and moves to customer detail after save.",
                    location="40-80",
                ),
            ),
            conversation_id="conv-21",
            turn_number=3,
            is_follow_up=True,
        )

    result = await extract_screen_catalog_document(
        _fake_ask,
        feature_key="customer-create",
        run_id="run-012",
        manifest=_manifest(),
        source_scope="requirements/ba.pdf",
        terminology=_terminology(),
        source_ids=("src-1",),
        prior_catalog=_prior_catalog(),
        candidate_screen_hints=("Customer Form",),
        conversation_id="conv-20",
    )

    assert isinstance(result, ScreenCatalogExtractionResult)
    assert result.parse_quality is StructuredParseQuality.EXACT
    assert result.warnings == ()
    assert result.conversation_id == "conv-21"
    assert [screen.screen_id for screen in result.document.screens] == [
        "customer-detail",
        "customer-form",
    ]

    customer_form = next(
        screen for screen in result.document.screens if screen.screen_id == "customer-form"
    )
    assert customer_form.roles == ["Customer Service Representative"]
    assert customer_form.dependencies == ["Customer ID"]
    assert customer_form.related_sources == ["requirements"]
    assert customer_form.evidence[0].snapshot_id == "requirements-abc123"
    assert customer_form.open_questions[0].question_id.startswith("customer-form-q-")
    assert customer_form.open_questions[0].screen_id == "customer-form"


@pytest.mark.asyncio
async def test_extract_screen_catalog_document_assigns_new_id_for_material_screen_change() -> None:
    async def _fake_ask(
        prompt_text: str,
        *,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            answer=json.dumps(
                {
                    "screens": [
                        {
                            "screen_name": "Customer Import Wizard",
                            "purpose": "Bulk import customers from CSV",
                        }
                    ]
                }
            ),
            citations=(
                SimpleNamespace(
                    source_id="src-1",
                    quote="Admins can bulk import customers from CSV.",
                    location="81-95",
                ),
            ),
            conversation_id="conv-22",
            turn_number=1,
            is_follow_up=False,
        )

    result = await extract_screen_catalog_document(
        _fake_ask,
        feature_key="customer-create",
        run_id="run-012",
        manifest=_manifest(),
        source_scope="requirements/ba.pdf",
        prior_catalog=_prior_catalog(),
    )

    assert result.document.screens[0].screen_id == "customer-import-wizard"
    assert result.document.screens[0].screen_id != "customer-form"


def test_run_store_persists_and_loads_screen_catalog(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-012",
    )
    store.create()
    catalog = ScreenCatalogDocument(
        run_id="run-012",
        feature_key="customer-create",
        screens=[
            ScreenCatalogEntry(
                screen_id="customer-form",
                screen_name="Customer Form",
                purpose="Create a customer record",
            ),
            ScreenCatalogEntry(
                screen_id="customer-detail",
                screen_name="Customer Detail",
                purpose="Review the saved customer profile",
            ),
        ],
    )

    store.save_screen_catalog(catalog)

    loaded = store.load_screen_catalog()
    assert [screen.screen_id for screen in loaded.screens] == [
        "customer-form",
        "customer-detail",
    ]
    assert store.feature_paths.screen_catalog_json.exists()
