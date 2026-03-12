"""Unit tests for BA source-to-screen traceability helpers."""

from __future__ import annotations

from notebooklm_mcp.ba.matrices import FieldMatrixRow, ScreenMatrixBundle
from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    GapSeverity,
    QuestionRecord,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    WorkflowMode,
)
from notebooklm_mcp.ba.traceability import (
    build_screen_traceability_index,
    build_source_to_screen_index,
    map_changed_sources_to_screens,
    parse_matrix_evidence_ref,
)


def _evidence(source_key: str, snapshot_id: str, locator: str) -> EvidenceRef:
    return EvidenceRef(
        source_key=source_key,
        snapshot_id=snapshot_id,
        locator=locator,
    )


def _catalog(*screens: ScreenCatalogEntry) -> ScreenCatalogDocument:
    return ScreenCatalogDocument(
        feature_key="customer-create",
        run_id="run-001",
        screens=list(screens),
    )


def _screen(
    screen_id: str,
    *,
    dependencies: list[str] | None = None,
    evidence: list[EvidenceRef] | None = None,
    question_evidence: list[EvidenceRef] | None = None,
) -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        run_id="run-001",
        screen_id=screen_id,
        mode=WorkflowMode.AUTO,
        shared_facts=[
            CanonicalFact(
                fact_id=f"{screen_id}-fact",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={"rule": f"{screen_id} rule"},
                status=FactStatus.CONFIRMED,
                evidence=list(evidence or []),
            )
        ],
        dependencies=list(dependencies or []),
        open_questions=[
            QuestionRecord(
                question_id=f"{screen_id}-question",
                summary=f"{screen_id} needs a confirmation",
                severity=GapSeverity.MEDIUM,
                screen_id=screen_id,
                evidence=list(question_evidence or []),
            )
        ],
        quality_summary=ExtractionQualitySummary(parse_quality="HIGH"),
    )


def _matrix(screen_id: str, *evidence_refs: str) -> ScreenMatrixBundle:
    return ScreenMatrixBundle(
        feature_key="customer-create",
        run_id="run-001",
        screen_id=screen_id,
        field_rows=[
            FieldMatrixRow(
                row_id=f"{screen_id}-field",
                screen_id=screen_id,
                fact_id=f"{screen_id}-fact",
                source_domain=FactDomain.FE,
                fact_status=FactStatus.CONFIRMED,
                field_name="email",
                evidence_count=len(evidence_refs),
                evidence_refs=list(evidence_refs),
            )
        ],
    )


def test_parse_matrix_evidence_ref_supports_locator_and_missing_locator() -> None:
    parsed = parse_matrix_evidence_ref("requirements@req-v2:10-20")
    assert parsed is not None
    assert parsed.source_key == "requirements"
    assert parsed.snapshot_id == "req-v2"
    assert parsed.locator == "10-20"

    without_locator = parse_matrix_evidence_ref("glossary@glo-v1")
    assert without_locator is not None
    assert without_locator.source_key == "glossary"
    assert without_locator.snapshot_id == "glo-v1"
    assert without_locator.locator is None


def test_build_screen_traceability_index_collects_sources_and_dependents() -> None:
    catalog = _catalog(
        ScreenCatalogEntry(
            screen_id="customer-form",
            screen_name="Customer Form",
            purpose="Create a customer",
            related_sources=["requirements"],
            dependencies=["Customer Summary"],
            evidence=[_evidence("requirements", "req-v1", "10-20")],
        ),
        ScreenCatalogEntry(
            screen_id="customer-summary",
            screen_name="Customer Summary",
            purpose="Review the created customer",
        ),
    )
    canonical_screen = _screen(
        "customer-form",
        evidence=[_evidence("glossary", "glo-v1", "aliases")],
        question_evidence=[_evidence("design", "design-v1", "hero-panel")],
    )
    matrix_bundle = _matrix("customer-form", "contract@contract-v2:rows 10-12")

    traceability = build_screen_traceability_index(
        screen_catalog=catalog,
        canonical_screens=[canonical_screen],
        matrix_bundles=[matrix_bundle],
    )

    customer_form = traceability["customer-form"]
    assert customer_form.source_keys == ["contract", "design", "glossary", "requirements"]
    assert customer_form.depends_on == ["customer-summary"]
    assert "contract@contract-v2:rows 10-12" in customer_form.evidence_refs
    assert traceability["customer-summary"].dependent_screens == ["customer-form"]

    source_index = build_source_to_screen_index(traceability)
    assert source_index["requirements"] == ["customer-form"]
    assert source_index["glossary"] == ["customer-form"]


def test_map_changed_sources_to_screens_stays_narrow_without_dependents() -> None:
    catalog = _catalog(
        ScreenCatalogEntry(
            screen_id="customer-form",
            screen_name="Customer Form",
            purpose="Create a customer",
            related_sources=["requirements"],
        ),
        ScreenCatalogEntry(
            screen_id="customer-audit",
            screen_name="Customer Audit",
            purpose="Inspect customer history",
            related_sources=["audit-rules"],
        ),
    )

    impacted = map_changed_sources_to_screens(
        ["requirements"],
        screen_catalog=catalog,
        include_dependents=False,
    )

    assert impacted == ["customer-form"]


def test_map_changed_sources_to_screens_expands_downstream_dependents() -> None:
    catalog = _catalog(
        ScreenCatalogEntry(
            screen_id="customer-form",
            screen_name="Customer Form",
            purpose="Create a customer",
            related_sources=["requirements"],
        ),
        ScreenCatalogEntry(
            screen_id="customer-summary",
            screen_name="Customer Summary",
            purpose="Review the created customer",
            dependencies=["Customer Form"],
        ),
    )

    impacted = map_changed_sources_to_screens(
        ["requirements"],
        screen_catalog=catalog,
        include_dependents=True,
    )

    assert impacted == ["customer-form", "customer-summary"]
