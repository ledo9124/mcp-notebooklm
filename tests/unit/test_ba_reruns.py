"""Unit tests for BA rerun planning and changelog rendering."""

from __future__ import annotations

import hashlib

from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    ParseQuality,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    SourceContentKind,
    SourceLifecycleStatus,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceSnapshotRecord,
    SourceType,
    TerminologyDocument,
    TerminologyEntry,
    WorkflowMode,
)
from notebooklm_mcp.ba.readiness import evaluate_readiness
from notebooklm_mcp.ba.reruns import (
    RerunDecision,
    SourceSnapshotText,
    build_rerun_plan,
    render_rerun_changelog,
)


def _snapshot(source_key: str, snapshot_id: str, content: str) -> SourceSnapshotText:
    return SourceSnapshotText(
        record=SourceSnapshotRecord(
            source_key=source_key,
            snapshot_id=snapshot_id,
            content_hash=hashlib.sha1(content.encode("utf-8")).hexdigest(),
            char_count=len(content),
        ),
        content=content,
    )


def _manifest(feature_key: str, run_id: str, *, requirements_snapshot: str, glossary_snapshot: str) -> SourceManifestDocument:
    return SourceManifestDocument(
        feature_key=feature_key,
        run_id=run_id,
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref="requirements/ba.pdf",
                snapshot_id=requirements_snapshot,
                status=SourceLifecycleStatus.READY,
                used_in_screens=["customer-form"],
            ),
            SourceManifestRow(
                source_key="glossary",
                source_type=SourceType.SUPPORTING_GLOSSARY,
                priority=SourcePriority.NORMAL,
                content_kind=SourceContentKind.URL,
                source_ref="https://example.com/glossary",
                snapshot_id=glossary_snapshot,
                status=SourceLifecycleStatus.READY,
                used_in_screens=["customer-list"],
            ),
        ],
    )


def _catalog(feature_key: str, run_id: str, *, requirement_snapshot: str, glossary_snapshot: str) -> ScreenCatalogDocument:
    return ScreenCatalogDocument(
        feature_key=feature_key,
        run_id=run_id,
        screens=[
            ScreenCatalogEntry(
                screen_id="customer-form",
                screen_name="Customer Form",
                purpose="Create a customer record",
                related_sources=["requirements"],
                evidence=[EvidenceRef(source_key="requirements", snapshot_id=requirement_snapshot, locator="3-6")],
            ),
            ScreenCatalogEntry(
                screen_id="customer-list",
                screen_name="Customer List",
                purpose="Browse customers",
                related_sources=["glossary"],
                evidence=[EvidenceRef(source_key="glossary", snapshot_id=glossary_snapshot, locator="1-2")],
            ),
        ],
    )


def _terms(feature_key: str, run_id: str, *, requirement_snapshot: str, glossary_snapshot: str, cross_cutting: bool = False) -> TerminologyDocument:
    entries = [
        TerminologyEntry(
            standard_term="Customer",
            aliases=["Client"],
            evidence=[EvidenceRef(source_key="requirements", snapshot_id=requirement_snapshot, locator="1-2")],
        ),
        TerminologyEntry(
            standard_term="Customer Summary",
            aliases=["List Item"],
            evidence=[EvidenceRef(source_key="glossary", snapshot_id=glossary_snapshot, locator="1-2")],
        ),
    ]
    if cross_cutting:
        entries.append(
            TerminologyEntry(
                standard_term="Account",
                aliases=["Profile"],
                evidence=[EvidenceRef(source_key="requirements", snapshot_id=requirement_snapshot, locator="7-8")],
            )
        )
    return TerminologyDocument(
        feature_key=feature_key,
        run_id=run_id,
        entries=entries,
    )


def _screen(feature_key: str, run_id: str, *, screen_id: str, source_key: str, snapshot_id: str, status: FactStatus = FactStatus.CONFIRMED) -> CanonicalScreen:
    return CanonicalScreen(
        feature_key=feature_key,
        run_id=run_id,
        screen_id=screen_id,
        mode=WorkflowMode.FE_FIRST,
        shared_facts=[
            CanonicalFact(
                fact_id=f"{screen_id}-rule",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={"summary": f"{screen_id} rule"},
                status=status,
                evidence=[EvidenceRef(source_key=source_key, snapshot_id=snapshot_id, locator="7-9")] if status is FactStatus.CONFIRMED else [],
                rationale="Pending confirmation." if status is not FactStatus.CONFIRMED else None,
            )
        ],
        fe_facts=[],
        be_facts=[],
        dependencies=[],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def test_build_rerun_plan_selectively_maps_changed_source_to_one_screen() -> None:
    feature_key = "customer-create"
    run_id = "run-1"
    previous_requirements = _snapshot("requirements", "snap-old", "Customer form requirements.\nScreen: Customer Form.\n")
    current_requirements = _snapshot(
        "requirements",
        "snap-new",
        "Customer form requirements.\nScreen: Customer Form.\nRule: Email must be verified.\n",
    )
    glossary = _snapshot("glossary", "snap-glossary", "Customer list glossary.\n")

    plan = build_rerun_plan(
        feature_key=feature_key,
        run_id=run_id,
        previous_manifest=_manifest(feature_key, run_id, requirements_snapshot="snap-old", glossary_snapshot="snap-glossary"),
        current_manifest=_manifest(feature_key, run_id, requirements_snapshot="snap-new", glossary_snapshot="snap-glossary"),
        previous_screen_catalog=_catalog(feature_key, run_id, requirement_snapshot="snap-old", glossary_snapshot="snap-glossary"),
        current_screen_catalog=_catalog(feature_key, run_id, requirement_snapshot="snap-new", glossary_snapshot="snap-glossary"),
        previous_terminology=_terms(feature_key, run_id, requirement_snapshot="snap-old", glossary_snapshot="snap-glossary"),
        current_terminology=_terms(feature_key, run_id, requirement_snapshot="snap-new", glossary_snapshot="snap-glossary"),
        previous_canonical_screens={
            "customer-form": _screen(feature_key, run_id, screen_id="customer-form", source_key="requirements", snapshot_id="snap-old"),
            "customer-list": _screen(feature_key, run_id, screen_id="customer-list", source_key="glossary", snapshot_id="snap-glossary"),
        },
        previous_snapshots={
            "requirements": previous_requirements,
            "glossary": glossary,
        },
        current_snapshots={
            "requirements": current_requirements,
            "glossary": glossary,
        },
        matrix_source_links={"customer-form": ["requirements"]},
    )

    assert plan.decision is RerunDecision.SELECTIVE
    assert [item.source_key for item in plan.changed_sources] == ["requirements"]
    assert [item.screen_id for item in plan.impacted_screens] == ["customer-form"]
    assert "screens/customer-form/..." in plan.dependent_artifacts


def test_build_rerun_plan_escalates_for_cross_cutting_terminology_changes() -> None:
    feature_key = "customer-create"
    run_id = "run-2"
    previous_requirements = _snapshot("requirements", "snap-old", "Customer requirements.\nScreen: Customer Form.\n")
    current_requirements = _snapshot(
        "requirements",
        "snap-new",
        "Customer requirements.\nScreen: Customer Form.\nAccount profile terminology updated.\n",
    )
    glossary = _snapshot("glossary", "snap-glossary", "Customer list glossary.\nAccount profile overview.\n")
    catalog = ScreenCatalogDocument(
        feature_key=feature_key,
        run_id=run_id,
        screens=[
            ScreenCatalogEntry(
                screen_id="customer-form",
                screen_name="Customer Form",
                purpose="Create a customer account profile",
                related_sources=["requirements"],
                evidence=[EvidenceRef(source_key="requirements", snapshot_id="snap-old", locator="3-6")],
            ),
            ScreenCatalogEntry(
                screen_id="customer-list",
                screen_name="Customer List",
                purpose="Browse account profiles",
                related_sources=["glossary"],
                evidence=[EvidenceRef(source_key="glossary", snapshot_id="snap-glossary", locator="1-2")],
            ),
        ],
    )

    plan = build_rerun_plan(
        feature_key=feature_key,
        run_id=run_id,
        previous_manifest=_manifest(feature_key, run_id, requirements_snapshot="snap-old", glossary_snapshot="snap-glossary"),
        current_manifest=_manifest(feature_key, run_id, requirements_snapshot="snap-new", glossary_snapshot="snap-glossary"),
        previous_screen_catalog=catalog,
        current_screen_catalog=catalog,
        previous_terminology=_terms(feature_key, run_id, requirement_snapshot="snap-old", glossary_snapshot="snap-glossary"),
        current_terminology=_terms(
            feature_key,
            run_id,
            requirement_snapshot="snap-new",
            glossary_snapshot="snap-glossary",
            cross_cutting=True,
        ),
        previous_canonical_screens={
            "customer-form": _screen(feature_key, run_id, screen_id="customer-form", source_key="requirements", snapshot_id="snap-old"),
            "customer-list": _screen(feature_key, run_id, screen_id="customer-list", source_key="glossary", snapshot_id="snap-glossary"),
        },
        previous_snapshots={
            "requirements": previous_requirements,
            "glossary": glossary,
        },
        current_snapshots={
            "requirements": current_requirements,
            "glossary": glossary,
        },
    )

    assert plan.decision is RerunDecision.FULL_FEATURE
    assert "terminology changes are cross-cutting across the feature" in plan.escalation_reasons


def test_render_rerun_changelog_mentions_provisional_screens() -> None:
    feature_key = "customer-create"
    run_id = "run-3"
    screen = _screen(
        feature_key,
        run_id,
        screen_id="customer-list",
        source_key="glossary",
        snapshot_id="snap-glossary",
        status=FactStatus.PROVISIONAL,
    )
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST)
    plan = build_rerun_plan(
        feature_key=feature_key,
        run_id=run_id,
        previous_manifest=_manifest(feature_key, run_id, requirements_snapshot="snap-old", glossary_snapshot="snap-glossary"),
        current_manifest=_manifest(feature_key, run_id, requirements_snapshot="snap-new", glossary_snapshot="snap-glossary"),
        previous_screen_catalog=_catalog(feature_key, run_id, requirement_snapshot="snap-old", glossary_snapshot="snap-glossary"),
        current_screen_catalog=_catalog(feature_key, run_id, requirement_snapshot="snap-new", glossary_snapshot="snap-glossary"),
        previous_terminology=_terms(feature_key, run_id, requirement_snapshot="snap-old", glossary_snapshot="snap-glossary"),
        current_terminology=_terms(feature_key, run_id, requirement_snapshot="snap-new", glossary_snapshot="snap-glossary"),
        previous_canonical_screens={"customer-list": screen},
        previous_snapshots={
            "requirements": _snapshot("requirements", "snap-old", "Customer requirements.\n"),
            "glossary": _snapshot("glossary", "snap-glossary", "Customer list glossary.\n"),
        },
        current_snapshots={
            "requirements": _snapshot("requirements", "snap-new", "Customer requirements changed.\n"),
            "glossary": _snapshot("glossary", "snap-glossary", "Customer list glossary.\n"),
        },
    )

    changelog = render_rerun_changelog(plan, screens=[screen], readiness=readiness)

    assert "What Remains Provisional" in changelog
    assert "customer-list" in changelog
