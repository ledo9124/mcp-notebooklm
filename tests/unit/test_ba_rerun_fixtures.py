"""Regression checks for seeded BA rerun fixture families."""

from __future__ import annotations

from pathlib import Path

from notebooklm_mcp.ba._change_detection import (
    analyze_rerun_impact,
    render_changelog_markdown,
    render_impacted_screens_json,
)
from notebooklm_mcp.ba.fixtures import FixtureScenario, fixture_paths, load_fixture_manifest
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


def _scenario_root(name: str) -> Path:
    return Path("tests/fixtures/ba") / name


def _snapshot(
    source_key: str,
    snapshot_id: str,
    content_hash: str,
    title: str,
    *,
    scenario: str = "rerun_diff",
) -> SourceSnapshotRecord:
    return SourceSnapshotRecord(
        source_key=source_key,
        snapshot_id=snapshot_id,
        content_hash=content_hash,
        fulltext_path=f"tests/fixtures/ba/{scenario}/{snapshot_id}/{source_key}.md",
        freshness="fresh",
        notebook_source_id=f"src-{source_key}",
        title=title,
        source_type="markdown",
        char_count=512,
    )


def _evidence(source_key: str, snapshot_id: str, locator: str) -> EvidenceRef:
    return EvidenceRef(
        source_key=source_key,
        snapshot_id=snapshot_id,
        locator=locator,
    )


def test_rerun_diff_fixture_matches_expected_change_detection_outputs() -> None:
    layout = fixture_paths(FixtureScenario.RERUN_DIFF, workspace_root=Path("."))
    manifest = load_fixture_manifest(layout.manifest_json)

    assert manifest.before_dir == "before"
    assert manifest.after_dir == "after"

    before_requirements = (layout.before_dir / "requirements.md").read_text(encoding="utf-8")
    after_requirements = (layout.after_dir / "requirements.md").read_text(encoding="utf-8")
    before_glossary = (layout.before_dir / "glossary.md").read_text(encoding="utf-8")
    after_glossary = (layout.after_dir / "glossary.md").read_text(encoding="utf-8")

    assert before_glossary == after_glossary

    report = analyze_rerun_impact(
        before_snapshots=[
            _snapshot("requirements", "requirements-before", "hash-before", "Requirements Before"),
            _snapshot("glossary", "glossary-before", "hash-glossary", "Glossary"),
        ],
        after_snapshots=[
            _snapshot("requirements", "requirements-after", "hash-after", "Requirements After"),
            _snapshot("glossary", "glossary-after", "hash-glossary", "Glossary"),
        ],
        before_text_by_source={
            "requirements": before_requirements,
            "glossary": before_glossary,
        },
        after_text_by_source={
            "requirements": after_requirements,
            "glossary": after_glossary,
        },
        screen_catalog=ScreenCatalogDocument(
            feature_key="customer-create",
            run_id="run-rerun-fixture",
            screens=[
                ScreenCatalogEntry(
                    screen_id="customer-form",
                    screen_name="Customer Form",
                    purpose="Create customers and capture Loyalty Tier details.",
                    roles=["Sales"],
                    entry_points=["Customer list"],
                    exit_points=["Customer details"],
                    main_actions=["Save customer"],
                    related_sources=["requirements"],
                ),
                ScreenCatalogEntry(
                    screen_id="customer-audit",
                    screen_name="Customer Audit",
                    purpose="Review account audit history.",
                    roles=["Ops"],
                    entry_points=["Audit workbench"],
                    exit_points=["Customer details"],
                    main_actions=["Review activity"],
                    related_sources=["glossary"],
                ),
            ],
        ),
        canonical_screens=[
            CanonicalScreen(
                feature_key="customer-create",
                screen_id="customer-form",
                mode=WorkflowMode.FE_FIRST,
                run_id="run-rerun-fixture",
                shared_facts=[
                    CanonicalFact(
                        fact_id="customer-form-tier",
                        domain=FactDomain.SHARED,
                        category="business_rule",
                        value={"description": "Customer Form shows Loyalty Tier policy details."},
                        status=FactStatus.CONFIRMED,
                        evidence=[_evidence("requirements", "requirements-before", "10-20")],
                    )
                ],
                fe_facts=[],
                be_facts=[],
                dependencies=[],
                quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
            )
        ],
        source_manifest=SourceManifestDocument(
            feature_key="customer-create",
            run_id="run-rerun-fixture",
            rows=[
                SourceManifestRow(
                    source_key="requirements",
                    source_type=SourceType.PRIMARY_REQUIREMENT,
                    priority=SourcePriority.REQUIRED,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref="tests/fixtures/ba/rerun_diff/after/requirements.md",
                    title="Requirements After",
                    used_in_screens=["customer-form"],
                ),
                SourceManifestRow(
                    source_key="glossary",
                    source_type=SourceType.SUPPORTING_GLOSSARY,
                    priority=SourcePriority.NORMAL,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref="tests/fixtures/ba/rerun_diff/after/glossary.md",
                    title="Glossary After",
                ),
            ],
        ),
        terminology=TerminologyDocument(
            feature_key="customer-create",
            run_id="run-rerun-fixture",
            entries=[
                TerminologyEntry(
                    standard_term="Loyalty Tier",
                    aliases=["VIP Tier"],
                    evidence=[_evidence("requirements", "requirements-before", "25-30")],
                )
            ],
        ),
    )

    assert render_impacted_screens_json(report) == (
        layout.expected_dir / "impacted-screens.json"
    ).read_text(encoding="utf-8")
    assert render_changelog_markdown(report) == (
        layout.expected_dir / "changelog.md"
    ).read_text(encoding="utf-8")


def test_rerun_cross_cutting_fixture_escalates_to_full_rerun() -> None:
    root = _scenario_root("rerun_cross_cutting")

    before_requirements = (root / "before/requirements.md").read_text(encoding="utf-8")
    after_requirements = (root / "after/requirements.md").read_text(encoding="utf-8")

    report = analyze_rerun_impact(
        before_snapshots=[
            _snapshot(
                "requirements",
                "requirements-before",
                "hash-before",
                "Requirements Before",
                scenario="rerun_cross_cutting",
            )
        ],
        after_snapshots=[
            _snapshot(
                "requirements",
                "requirements-after",
                "hash-after",
                "Requirements After",
                scenario="rerun_cross_cutting",
            )
        ],
        before_text_by_source={"requirements": before_requirements},
        after_text_by_source={"requirements": after_requirements},
        screen_catalog=ScreenCatalogDocument(
            feature_key="customer-create",
            run_id="run-rerun-cross-cutting",
            screens=[
                ScreenCatalogEntry(
                    screen_id="customer-form",
                    screen_name="Customer Form",
                    purpose="Create customers and capture Loyalty Tier details.",
                    roles=["Sales"],
                    entry_points=["Customer list"],
                    exit_points=["Customer details"],
                    main_actions=["Save customer"],
                    related_sources=["requirements"],
                ),
                ScreenCatalogEntry(
                    screen_id="customer-review",
                    screen_name="Customer Review",
                    purpose="Review customers and confirm Loyalty Tier changes.",
                    roles=["Ops"],
                    entry_points=["Customer queue"],
                    exit_points=["Customer details"],
                    main_actions=["Approve customer"],
                    related_sources=["requirements"],
                ),
            ],
        ),
        source_manifest=SourceManifestDocument(
            feature_key="customer-create",
            run_id="run-rerun-cross-cutting",
            rows=[
                SourceManifestRow(
                    source_key="requirements",
                    source_type=SourceType.PRIMARY_REQUIREMENT,
                    priority=SourcePriority.REQUIRED,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref="tests/fixtures/ba/rerun_cross_cutting/after/requirements.md",
                    title="Requirements After",
                    used_in_screens=["customer-form", "customer-review"],
                )
            ],
        ),
        terminology=TerminologyDocument(
            feature_key="customer-create",
            run_id="run-rerun-cross-cutting",
            entries=[
                TerminologyEntry(
                    standard_term="Loyalty Tier",
                    aliases=["VIP Tier"],
                    evidence=[_evidence("requirements", "requirements-before", "25-30")],
                )
            ],
        ),
    )

    assert report.requires_full_rerun is True
    assert report.escalation_reasons == ["changes cut across every known screen"]
    assert render_impacted_screens_json(report) == (
        root / "expected/impacted-screens.json"
    ).read_text(encoding="utf-8")
    assert render_changelog_markdown(report) == (
        root / "expected/changelog.md"
    ).read_text(encoding="utf-8")
