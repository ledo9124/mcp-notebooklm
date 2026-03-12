"""Unit tests for BA rerun change-detection support helpers."""

from __future__ import annotations

import json

from notebooklm_mcp.ba._change_detection import (
    SnapshotChangeKind,
    analyze_rerun_impact,
    diff_source_snapshots,
    render_changelog_markdown,
    render_impacted_screens_json,
)
from notebooklm_mcp.ba.matrices import FieldMatrixRow, ScreenMatrixBundle
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
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceSnapshotRecord,
    SourceType,
    TerminologyDocument,
    TerminologyEntry,
    WorkflowMode,
)


def _snapshot(source_key: str, snapshot_id: str, content_hash: str) -> SourceSnapshotRecord:
    return SourceSnapshotRecord(
        source_key=source_key,
        snapshot_id=snapshot_id,
        content_hash=content_hash,
        fulltext_path=f"docs/features/customer-create/runs/run-011/{source_key}/{snapshot_id}/fulltext.txt",
        freshness="fresh",
        notebook_source_id=f"src-{source_key}",
        title=f"{source_key.title()} Snapshot",
        source_type="pdf",
        char_count=1024,
    )


def _evidence(source_key: str, snapshot_id: str, locator: str) -> EvidenceRef:
    return EvidenceRef(source_key=source_key, snapshot_id=snapshot_id, locator=locator)


def _screen(
    screen_id: str,
    screen_name: str,
    *,
    purpose: str,
    related_sources: tuple[str, ...] = (),
    dependencies: tuple[str, ...] = (),
) -> ScreenCatalogEntry:
    return ScreenCatalogEntry(
        screen_id=screen_id,
        screen_name=screen_name,
        purpose=purpose,
        roles=["Sales"],
        entry_points=["Customer list"],
        exit_points=["Customer details"],
        main_actions=["Save customer"],
        dependencies=list(dependencies),
        related_sources=list(related_sources),
    )


def _canonical_screen(
    screen_id: str,
    screen_name: str,
    *,
    source_key: str,
    snapshot_id: str,
    description: str,
) -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id=screen_id,
        mode=WorkflowMode.FE_FIRST,
        run_id="run-011",
        shared_facts=[
            CanonicalFact(
                fact_id=f"{screen_id}-rule",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={"description": description},
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(source_key, snapshot_id, "10-20")],
            )
        ],
        fe_facts=[],
        be_facts=[],
        dependencies=[],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def _matrix(screen_id: str, *evidence_refs: str) -> ScreenMatrixBundle:
    return ScreenMatrixBundle(
        feature_key="customer-create",
        run_id="run-011",
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


def _terminology(snapshot_id: str, source_key: str = "requirements") -> TerminologyDocument:
    return TerminologyDocument(
        feature_key="customer-create",
        run_id="run-011",
        entries=[
            TerminologyEntry(
                standard_term="Loyalty Tier",
                aliases=["VIP Tier"],
                evidence=[_evidence(source_key, snapshot_id, "25-30")],
            )
        ],
    )


def test_diff_source_snapshots_reports_changed_headings_and_terms() -> None:
    before = [_snapshot("requirements", "requirements-old", "hash-old")]
    after = [_snapshot("requirements", "requirements-new", "hash-new")]

    deltas = diff_source_snapshots(
        before,
        after,
        before_text_by_source={
            "requirements": "# Overview\nCustomer form captures email.\n\n## Pricing\nLoyalty Tier drives discounts.\n"
        },
        after_text_by_source={
            "requirements": "# Overview\nCustomer form captures email and audit notes.\n\n## Audit Rules\nVIP Tier changes require manager approval.\n"
        },
        terminology=_terminology("requirements-old"),
    )

    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.change_kind is SnapshotChangeKind.MODIFIED
    assert delta.before_snapshot_id == "requirements-old"
    assert delta.after_snapshot_id == "requirements-new"
    assert "Overview" in delta.changed_headings
    assert "Audit Rules" in delta.changed_headings
    assert "Pricing" in delta.changed_headings
    assert delta.changed_terms == ["Loyalty Tier"]


def test_analyze_rerun_impact_stays_narrow_for_direct_source_and_term_matches() -> None:
    before = [_snapshot("requirements", "requirements-old", "hash-old")]
    after = [_snapshot("requirements", "requirements-new", "hash-new")]
    report = analyze_rerun_impact(
        before_snapshots=before,
        after_snapshots=after,
        before_text_by_source={"requirements": "# Overview\nLoyalty Tier applies to standard customers.\n"},
        after_text_by_source={
            "requirements": "# Overview\nVIP Tier rules now allow manager override on Customer Form.\n"
        },
        screen_catalog=ScreenCatalogDocument(
            feature_key="customer-create",
            run_id="run-011",
            screens=[
                _screen(
                    "customer-form",
                    "Customer Form",
                    purpose="Create customers and manage Loyalty Tier overrides.",
                    related_sources=("requirements",),
                ),
                _screen(
                    "approval-log",
                    "Approval Log",
                    purpose="Review internal audit records.",
                    related_sources=("audit-notes",),
                ),
            ],
        ),
        canonical_screens=[
            _canonical_screen(
                "customer-form",
                "Customer Form",
                source_key="requirements",
                snapshot_id="requirements-old",
                description="Customer Form captures Loyalty Tier policy details.",
            )
        ],
        source_manifest=SourceManifestDocument(
            feature_key="customer-create",
            run_id="run-011",
            rows=[
                SourceManifestRow(
                    source_key="requirements",
                    source_type=SourceType.PRIMARY_REQUIREMENT,
                    priority=SourcePriority.REQUIRED,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref="requirements/ba.pdf",
                    title="Requirements PDF",
                    used_in_screens=["customer-form"],
                )
            ],
        ),
        terminology=_terminology("requirements-old"),
    )

    assert report.changed_sources == ["requirements"]
    assert report.requires_full_rerun is False
    assert report.escalation_reasons == []
    assert [item.screen_id for item in report.impacted_screens] == ["customer-form"]
    impacted = report.impacted_screens[0]
    assert impacted.changed_sources == ["requirements"]
    assert impacted.changed_terms == ["Loyalty Tier"]
    assert {
        "canonical_evidence",
        "manifest_usage",
        "related_source",
        "terminology_match",
    } <= set(impacted.reasons)


def test_analyze_rerun_impact_propagates_dependencies_from_impacted_screens() -> None:
    before = [_snapshot("requirements", "requirements-old", "hash-old")]
    after = [_snapshot("requirements", "requirements-new", "hash-new")]
    report = analyze_rerun_impact(
        before_snapshots=before,
        after_snapshots=after,
        before_text_by_source={"requirements": "# Overview\nOld copy.\n"},
        after_text_by_source={"requirements": "# Overview\nCustomer Form now has a revised submit rule.\n"},
        screen_catalog=ScreenCatalogDocument(
            feature_key="customer-create",
            run_id="run-011",
            screens=[
                _screen(
                    "customer-form",
                    "Customer Form",
                    purpose="Create customers.",
                    related_sources=("requirements",),
                ),
                _screen(
                    "customer-review",
                    "Customer Review",
                    purpose="Review submitted customers.",
                    dependencies=("Customer Form",),
                ),
            ],
        ),
        source_manifest=SourceManifestDocument(
            feature_key="customer-create",
            run_id="run-011",
            rows=[
                SourceManifestRow(
                    source_key="requirements",
                    source_type=SourceType.PRIMARY_REQUIREMENT,
                    priority=SourcePriority.REQUIRED,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref="requirements/ba.pdf",
                    title="Requirements PDF",
                    used_in_screens=["customer-form"],
                )
            ],
        ),
    )

    assert [item.screen_id for item in report.impacted_screens] == [
        "customer-form",
        "customer-review",
    ]
    assert report.impacted_screens[1].reasons == ["depends_on_impacted_screen"]


def test_analyze_rerun_impact_escalates_when_changed_source_has_no_screen_match() -> None:
    before = [_snapshot("glossary", "glossary-old", "hash-old")]
    after = [_snapshot("glossary", "glossary-new", "hash-new")]
    report = analyze_rerun_impact(
        before_snapshots=before,
        after_snapshots=after,
        before_text_by_source={"glossary": "# Terms\nAccount\n"},
        after_text_by_source={"glossary": "# Terms\nAccount\nCustomer Segment\n"},
        screen_catalog=ScreenCatalogDocument(
            feature_key="customer-create",
            run_id="run-011",
            screens=[
                _screen(
                    "customer-form",
                    "Customer Form",
                    purpose="Create customers.",
                    related_sources=("requirements",),
                )
            ],
        ),
    )

    assert report.impacted_screens == []
    assert report.requires_full_rerun is True
    assert report.escalation_reasons == [
        "no deterministic screen match for changed sources: glossary"
    ]


def test_analyze_rerun_impact_maps_matrix_evidence_only_source_changes() -> None:
    before = [_snapshot("contract", "contract-old", "hash-old")]
    after = [_snapshot("contract", "contract-new", "hash-new")]
    report = analyze_rerun_impact(
        before_snapshots=before,
        after_snapshots=after,
        before_text_by_source={"contract": "# Rules\nCustomer edits are validated.\n"},
        after_text_by_source={"contract": "# Rules\nCustomer edits now require audit tagging.\n"},
        screen_catalog=ScreenCatalogDocument(
            feature_key="customer-create",
            run_id="run-011",
            screens=[
                _screen(
                    "customer-form",
                    "Customer Form",
                    purpose="Create customers.",
                )
            ],
        ),
        matrix_bundles=[_matrix("customer-form", "contract@contract-old:rows 10-12")],
    )

    assert report.requires_full_rerun is False
    assert report.escalation_reasons == []
    assert [item.screen_id for item in report.impacted_screens] == ["customer-form"]
    impacted = report.impacted_screens[0]
    assert impacted.changed_sources == ["contract"]
    assert impacted.reasons == ["matrix_evidence"]


def test_renderers_emit_deterministic_rerun_artifacts() -> None:
    before = [_snapshot("requirements", "requirements-old", "hash-old")]
    after = [_snapshot("requirements", "requirements-new", "hash-new")]
    report = analyze_rerun_impact(
        before_snapshots=before,
        after_snapshots=after,
        before_text_by_source={"requirements": "# Overview\nLoyalty Tier is read-only.\n"},
        after_text_by_source={"requirements": "# Overview\nVIP Tier can be edited on Customer Form.\n"},
        screen_catalog=ScreenCatalogDocument(
            feature_key="customer-create",
            run_id="run-011",
            screens=[
                _screen(
                    "customer-form",
                    "Customer Form",
                    purpose="Edit Customer Form Loyalty Tier settings.",
                    related_sources=("requirements",),
                )
            ],
        ),
        source_manifest=SourceManifestDocument(
            feature_key="customer-create",
            run_id="run-011",
            rows=[
                SourceManifestRow(
                    source_key="requirements",
                    source_type=SourceType.PRIMARY_REQUIREMENT,
                    priority=SourcePriority.REQUIRED,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref="requirements/ba.pdf",
                    title="Requirements PDF",
                    used_in_screens=["customer-form"],
                )
            ],
        ),
        terminology=_terminology("requirements-old"),
    )

    payload = json.loads(render_impacted_screens_json(report))
    changelog = render_changelog_markdown(report)

    assert payload["changed_sources"] == ["requirements"]
    assert payload["impacted_screens"][0]["screen_id"] == "customer-form"
    assert "# Changelog" in changelog
    assert "`requirements`: modified" in changelog
    assert "`customer-form` Customer Form" in changelog
    assert "`Loyalty Tier`" in changelog
    assert "Targeted rerun is sufficient." in changelog
