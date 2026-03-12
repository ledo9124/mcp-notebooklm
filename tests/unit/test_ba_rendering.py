"""Unit tests for BA source-manifest rendering and persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path

from notebooklm_mcp.ba.fixtures import FixtureScenario, fixture_paths
from notebooklm_mcp.ba.gaps import build_gap_review_document
from notebooklm_mcp.ba.matrices import build_screen_matrix_bundle
from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    ContradictionClaim,
    ContradictionRecord,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    GapKind,
    GapRecord,
    GapSeverity,
    HaltRecommendation,
    ParseQuality,
    QuestionRecord,
    ScreenCatalogEntry,
    SourceContentKind,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceQualityAssessment,
    SourceSnapshotRecord,
    SourceType,
    WorkflowMode,
)
from notebooklm_mcp.ba.readiness import evaluate_readiness
from notebooklm_mcp.ba.rendering import (
    build_source_manifest_document,
    render_be_spec_markdown,
    render_fe_spec_markdown,
    render_question_backlog_markdown,
    render_source_manifest_json,
    render_source_manifest_markdown,
)
from notebooklm_mcp.ba.run_store import BARunStore

_UPDATE_BA_GOLDENS = "UPDATE_BA_GOLDENS"


def _base_manifest() -> SourceManifestDocument:
    return SourceManifestDocument(
        feature_key="customer-create",
        run_id="run-009",
        warnings=["supporting glossary source is still missing"],
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref="requirements/ba.pdf",
                title="Requirements PDF",
                notes=["approved by BA lead"],
                used_in_screens=["SCR-001", "SCR-002"],
            ),
            SourceManifestRow(
                source_key="glossary",
                source_type=SourceType.SUPPORTING_GLOSSARY,
                priority=SourcePriority.NORMAL,
                content_kind=SourceContentKind.URL,
                source_ref="https://example.com/glossary",
                title="Legacy Glossary",
            ),
        ],
    )


def _snapshot(source_key: str, snapshot_id: str, *, freshness: str = "fresh") -> SourceSnapshotRecord:
    return SourceSnapshotRecord(
        source_key=source_key,
        snapshot_id=snapshot_id,
        content_hash=f"{snapshot_id}-hash",
        fulltext_path=(
            "docs/features/customer-create/runs/run-009/snapshots/"
            f"{source_key}/{snapshot_id}/fulltext.txt"
        ),
        freshness=freshness,
        notebook_source_id=f"nb-{source_key}",
        title=f"{source_key.title()} snapshot",
        source_type="pdf",
        char_count=2048,
    )


def _assessment(source_key: str, snapshot_id: str, quality: ParseQuality) -> SourceQualityAssessment:
    return SourceQualityAssessment(
        source_key=source_key,
        snapshot_id=snapshot_id,
        parse_quality=quality,
        character_count=2048,
        heading_count=5,
        table_density=0.15,
        recommendation=HaltRecommendation.PROCEED,
    )


def _evidence(locator: str) -> EvidenceRef:
    return EvidenceRef(
        source_key="requirements",
        snapshot_id="requirements-abc123",
        locator=locator,
    )


def _fixture_ref(scenario: FixtureScenario, *parts: str) -> str:
    return (Path("tests/fixtures/ba") / scenario.value).joinpath(*parts).as_posix()


def _golden_path(scenario: FixtureScenario, name: str) -> Path:
    return fixture_paths(scenario, workspace_root=Path(".")).expected_dir / name


def _assert_golden_text(scenario: FixtureScenario, name: str, actual: str) -> None:
    golden_path = _golden_path(scenario, name)
    if os.getenv(_UPDATE_BA_GOLDENS) == "1":
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual, encoding="utf-8")
    assert golden_path.exists(), (
        f"Missing golden {golden_path}. Re-run with {_UPDATE_BA_GOLDENS}=1 to write fixture goldens."
    )
    assert actual == golden_path.read_text(encoding="utf-8")


def _scenario_evidence(source_key: str, snapshot_id: str, locator: str) -> EvidenceRef:
    return EvidenceRef(
        source_key=source_key,
        snapshot_id=snapshot_id,
        locator=locator,
    )


def _catalog_entry() -> ScreenCatalogEntry:
    return ScreenCatalogEntry(
        screen_id="customer-form",
        screen_name="Customer Form",
        purpose="Create a customer record",
        roles=["Sales"],
        entry_points=["Customer list"],
        exit_points=["Customer details"],
        main_actions=["Save customer"],
        dependencies=["Create Customer"],
    )


def _canonical_screen() -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.FE_FIRST,
        run_id="run-009",
        shared_facts=[
            CanonicalFact(
                fact_id="fact-rule",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={
                    "action_name": "Save customer",
                    "trigger": "User clicks Save",
                    "rule": "Customer email must be unique before creation completes",
                    "outcome": "Show duplicate-email validation and block submit",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence("10-20")],
            )
        ],
        fe_facts=[
            CanonicalFact(
                fact_id="fact-field",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "email",
                    "label": "Email Address",
                    "field_type": "email",
                    "required": True,
                    "description": "Primary login identifier for the customer.",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence("21-30")],
            ),
            CanonicalFact(
                fact_id="fact-loading",
                domain=FactDomain.FE,
                category="loading_state",
                value="Show inline saving spinner while the customer record is being created",
                status=FactStatus.PROVISIONAL,
                rationale="Workshop notes",
                origin="structured_extraction",
            ),
        ],
        be_facts=[
            CanonicalFact(
                fact_id="fact-endpoint",
                domain=FactDomain.BE,
                category="endpoint",
                value={
                    "endpoint_name": "Create Customer",
                    "method": "post",
                    "path": "/customers",
                    "request_body": "name, email, tier",
                    "response_body": "customer id and created timestamp",
                },
                status=FactStatus.PROVISIONAL,
                rationale="contract not yet approved",
                origin="structured_extraction",
                evidence=[_evidence("31-40")],
            )
        ],
        dependencies=["Create Customer"],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def _clean_feature_manifest() -> SourceManifestDocument:
    scenario = FixtureScenario.CLEAN_FEATURE
    return build_source_manifest_document(
        SourceManifestDocument(
            feature_key="customer-create",
            run_id="run-clean-golden",
            rows=[
                SourceManifestRow(
                    source_key="requirements",
                    source_type=SourceType.PRIMARY_REQUIREMENT,
                    priority=SourcePriority.REQUIRED,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref=_fixture_ref(scenario, "sources", "requirements.md"),
                    title="Customer Create Requirements",
                    used_in_screens=["customer-form", "customer-list"],
                ),
                SourceManifestRow(
                    source_key="api-contract",
                    source_type=SourceType.PRIMARY_CONTRACT,
                    priority=SourcePriority.REQUIRED,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref=_fixture_ref(scenario, "sources", "api-contract.md"),
                    title="Customer Create API Contract",
                    used_in_screens=["customer-form", "customer-list"],
                ),
                SourceManifestRow(
                    source_key="glossary",
                    source_type=SourceType.SUPPORTING_GLOSSARY,
                    priority=SourcePriority.NORMAL,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref=_fixture_ref(scenario, "sources", "glossary.md"),
                    title="Customer Create Glossary",
                    used_in_screens=["customer-form", "customer-list"],
                ),
            ],
        ),
        snapshots=[
            _snapshot("requirements", "requirements-clean-001"),
            _snapshot("api-contract", "api-contract-clean-001"),
            _snapshot("glossary", "glossary-clean-001"),
        ],
        quality_assessments=[
            _assessment("requirements", "requirements-clean-001", ParseQuality.HIGH),
            _assessment("api-contract", "api-contract-clean-001", ParseQuality.HIGH),
            _assessment("glossary", "glossary-clean-001", ParseQuality.HIGH),
        ],
    )


def _note_clarification_manifest() -> SourceManifestDocument:
    scenario = FixtureScenario.NOTE_CLARIFICATION
    return build_source_manifest_document(
        SourceManifestDocument(
            feature_key="customer-create",
            run_id="run-note-golden",
            warnings=[
                "supporting clarification remains subordinate to contradictory future primary evidence",
            ],
            rows=[
                SourceManifestRow(
                    source_key="requirements",
                    source_type=SourceType.PRIMARY_REQUIREMENT,
                    priority=SourcePriority.REQUIRED,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref=_fixture_ref(scenario, "sources", "requirements.md"),
                    title="Customer Create Requirements",
                    used_in_screens=["customer-form", "customer-review"],
                ),
                SourceManifestRow(
                    source_key="glossary",
                    source_type=SourceType.SUPPORTING_GLOSSARY,
                    priority=SourcePriority.NORMAL,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref=_fixture_ref(scenario, "sources", "glossary.md"),
                    title="Customer Create Glossary",
                    used_in_screens=["customer-form", "customer-review"],
                ),
                SourceManifestRow(
                    source_key="clarification-note",
                    source_type=SourceType.SUPPORTING_CLARIFICATION,
                    priority=SourcePriority.HIGH,
                    content_kind=SourceContentKind.FILE_PATH,
                    source_ref=_fixture_ref(scenario, "notes", "clarification-note.md"),
                    title="Supporting Clarification Note",
                    notes=["Curated from NotebookLM note review."],
                    used_in_screens=["customer-form", "customer-review"],
                ),
            ],
        ),
        snapshots=[
            _snapshot("requirements", "requirements-note-001"),
            _snapshot("glossary", "glossary-note-001"),
            _snapshot("clarification-note", "clarification-note-001"),
        ],
        quality_assessments=[
            _assessment("requirements", "requirements-note-001", ParseQuality.HIGH),
            _assessment("glossary", "glossary-note-001", ParseQuality.HIGH),
            _assessment("clarification-note", "clarification-note-001", ParseQuality.HIGH),
        ],
    )


def _contradictory_sources_screen() -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.AUTO,
        run_id="run-contradictory-golden",
        missing_info=[
            GapRecord(
                gap_id="contradictory-email-validation",
                kind=GapKind.CONTRADICTORY_REQUIREMENT_DETAIL,
                summary="Email validation timing is inconsistent across the BA sources.",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                owner="BA",
                blocking_workstreams=[FactDomain.SHARED],
                evidence=[
                    _scenario_evidence("requirements", "requirements-contradictory-001", "3-4"),
                    _scenario_evidence("business-rules", "business-rules-contradictory-001", "3-4"),
                ],
            ),
            GapRecord(
                gap_id="contradictory-vip-approval-threshold",
                kind=GapKind.CONTRADICTORY_REQUIREMENT_DETAIL,
                summary="VIP approval threshold differs between the BA PDF and the rules addendum.",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                owner="BA",
                blocking_workstreams=[FactDomain.SHARED],
                evidence=[
                    _scenario_evidence("requirements", "requirements-contradictory-001", "6-6"),
                    _scenario_evidence("business-rules", "business-rules-contradictory-001", "6-6"),
                ],
            ),
        ],
        contradictions=[
            ContradictionRecord(
                contradiction_id="email-validation-timing",
                summary="Requirements disagree on when duplicate-email validation runs.",
                severity=GapSeverity.HIGH,
                claims=[
                    ContradictionClaim(
                        claim="Validate email only when the user presses Save.",
                        evidence=[_scenario_evidence("requirements", "requirements-contradictory-001", "3-4")],
                    ),
                    ContradictionClaim(
                        claim="Validate email on blur before Save.",
                        evidence=[_scenario_evidence("business-rules", "business-rules-contradictory-001", "3-4")],
                    ),
                ],
                open_question="Should duplicate-email validation run on blur or only on submit?",
            ),
            ContradictionRecord(
                contradiction_id="vip-approval-threshold",
                summary="The spend threshold for VIP approval is inconsistent across the sources.",
                severity=GapSeverity.HIGH,
                claims=[
                    ContradictionClaim(
                        claim="Manager approval is required only above a 10000 yearly-spend threshold.",
                        evidence=[_scenario_evidence("requirements", "requirements-contradictory-001", "6-6")],
                    ),
                    ContradictionClaim(
                        claim="Manager approval is required above a 5000 yearly-spend threshold.",
                        evidence=[_scenario_evidence("business-rules", "business-rules-contradictory-001", "6-6")],
                    ),
                ],
                open_question="Which yearly-spend threshold is authoritative for VIP approval?",
            ),
        ],
        open_questions=[
            QuestionRecord(
                question_id="email-validation-timing-resolution",
                summary="Should duplicate-email validation run on blur or only on submit?",
                owner="BA",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                blocking_workstreams=[FactDomain.SHARED],
                evidence=[_scenario_evidence("requirements", "requirements-contradictory-001", "3-4")],
            ),
            QuestionRecord(
                question_id="vip-approval-threshold-resolution",
                summary="Which yearly-spend threshold is authoritative for VIP approval?",
                owner="BA",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                blocking_workstreams=[FactDomain.SHARED],
                evidence=[_scenario_evidence("business-rules", "business-rules-contradictory-001", "6-6")],
            ),
        ],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def _canonical_screen_with_be_uncertainty() -> CanonicalScreen:
    base = _canonical_screen()
    return base.model_copy(
        update={
            "shared_facts": [
                *base.shared_facts,
                CanonicalFact(
                    fact_id="fact-permission",
                    domain=FactDomain.SHARED,
                    category="permission_rule",
                    value={
                        "action_name": "Save customer",
                        "rule": "Only sales managers can override duplicate-email blocks",
                        "outcome": "Reject overrides for non-manager roles",
                    },
                    status=FactStatus.PROVISIONAL,
                    rationale="Approval path is still under review",
                    origin="structured_extraction",
                    evidence=[_evidence("41-50")],
                ),
            ],
            "be_facts": [
                *base.be_facts,
                CanonicalFact(
                    fact_id="fact-event",
                    domain=FactDomain.BE,
                    category="event",
                    value={
                        "event_name": "CustomerCreated",
                        "topic": "crm.customer.created",
                        "response_body": "downstream consumers receive the created customer payload",
                    },
                    status=FactStatus.PROVISIONAL,
                    rationale="Async integration contract is still provisional",
                    origin="structured_extraction",
                    evidence=[_evidence("51-60")],
                ),
            ],
            "missing_info": [
                GapRecord(
                    gap_id="gap-response-shape",
                    kind=GapKind.MISSING_BACKEND_CONTRACT,
                    summary="Create Customer response schema omits the loyalty tier payload",
                    severity=GapSeverity.HIGH,
                    screen_id="customer-form",
                    owner="Tech Lead",
                    blocking_workstreams=[FactDomain.BE],
                    evidence=[_evidence("61-70")],
                ),
                GapRecord(
                    gap_id="gap-override-approval",
                    kind=GapKind.MISSING_REQUIREMENT_DETAIL,
                    summary="Duplicate override approval workflow is unspecified",
                    severity=GapSeverity.HIGH,
                    screen_id="customer-form",
                    owner="BA",
                    blocking_workstreams=[FactDomain.SHARED],
                    evidence=[_evidence("71-80")],
                ),
            ],
            "open_questions": [
                QuestionRecord(
                    question_id="q-sync-event",
                    summary="Should Create Customer publish a CRM sync event after persistence?",
                    owner="Tech Lead",
                    severity=GapSeverity.HIGH,
                    screen_id="customer-form",
                    blocking_workstreams=[FactDomain.BE],
                    evidence=[_evidence("81-90")],
                ),
                QuestionRecord(
                    question_id="q-copy",
                    summary="Should the duplicate warning reuse the glossary copy?",
                    owner="Design",
                    severity=GapSeverity.MEDIUM,
                    screen_id="customer-form",
                    blocking_workstreams=[FactDomain.FE],
                    evidence=[_evidence("91-100")],
                ),
            ],
            "contradictions": [
                ContradictionRecord(
                    contradiction_id="contradiction-duplicate-policy",
                    summary="Requirements disagree on whether duplicate emails are rejected or merged",
                    severity=GapSeverity.HIGH,
                    claims=[
                        ContradictionClaim(
                            claim="Reject duplicate emails and block customer creation",
                            evidence=[_evidence("101-110")],
                        ),
                        ContradictionClaim(
                            claim="Merge duplicate emails into the existing customer record",
                            evidence=[_evidence("111-120")],
                        ),
                    ],
                    open_question="Should duplicate-email collisions hard-fail or trigger a merge workflow?",
                )
            ],
        }
    )


def test_build_source_manifest_document_merges_snapshot_and_quality_metadata() -> None:
    manifest = build_source_manifest_document(
        _base_manifest(),
        snapshots=[
            _snapshot("requirements", "requirements-abc123"),
            _snapshot("glossary", "glossary-def456", freshness="stale"),
        ],
        quality_assessments=[
            _assessment("requirements", "requirements-abc123", ParseQuality.HIGH),
            _assessment("glossary", "glossary-def456", ParseQuality.MEDIUM),
        ],
    )

    requirements = manifest.rows[0]
    glossary = manifest.rows[1]

    assert requirements.snapshot_id == "requirements-abc123"
    assert requirements.parse_quality is ParseQuality.HIGH
    assert requirements.freshness == "fresh"
    assert requirements.notebook_source_id == "nb-requirements"
    assert requirements.title == "Requirements PDF"

    assert glossary.snapshot_id == "glossary-def456"
    assert glossary.parse_quality is ParseQuality.MEDIUM
    assert glossary.freshness == "stale"
    assert glossary.notebook_source_id == "nb-glossary"


def test_render_source_manifest_outputs_readable_markdown_and_json() -> None:
    manifest = build_source_manifest_document(
        _base_manifest(),
        snapshots=[
            _snapshot("requirements", "requirements-abc123"),
            _snapshot("glossary", "glossary-def456", freshness="stale"),
        ],
        quality_assessments=[
            _assessment("requirements", "requirements-abc123", ParseQuality.HIGH),
            _assessment("glossary", "glossary-def456", ParseQuality.MEDIUM),
        ],
    )

    markdown = render_source_manifest_markdown(manifest)
    payload = json.loads(render_source_manifest_json(manifest))

    assert markdown.startswith("# Source Manifest\n")
    assert "## Sources" in markdown
    assert "## Warnings" in markdown
    assert "| `requirements` | Requirements PDF | `PRIMARY_REQUIREMENT` | `REQUIRED` |" in markdown
    assert "- Used in screens: `SCR-001`, `SCR-002`" in markdown
    assert payload["feature_key"] == "customer-create"
    assert payload["rows"][0]["snapshot_id"] == "requirements-abc123"
    assert payload["rows"][1]["parse_quality"] == "MEDIUM"


def test_run_store_persists_source_manifest_artifacts(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-009",
    )
    store.create()
    manifest = build_source_manifest_document(
        _base_manifest(),
        snapshots=[_snapshot("requirements", "requirements-abc123")],
        quality_assessments=[_assessment("requirements", "requirements-abc123", ParseQuality.HIGH)],
    )
    markdown = render_source_manifest_markdown(manifest)

    store.save_source_manifest_artifacts(manifest, markdown=markdown)

    assert store.load_source_manifest().rows[0].snapshot_id == "requirements-abc123"
    assert store.load_source_manifest_markdown() == markdown
    assert store.feature_paths.source_manifest_json.exists()
    assert store.feature_paths.source_manifest_markdown.exists()


def test_render_fe_spec_markdown_outputs_expected_sections() -> None:
    screen = _canonical_screen()
    matrices = build_screen_matrix_bundle(screen)
    review = build_gap_review_document(screen)
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST).screens[0]

    markdown = render_fe_spec_markdown(
        _catalog_entry(),
        screen,
        matrices=matrices,
        review=review,
        readiness=readiness,
    )

    assert markdown.startswith("# FE Spec: Customer Form\n")
    assert "## User Intent" in markdown
    assert "## Fields and Validations" in markdown
    assert "## Actions" in markdown
    assert "## Visible Business Rules" in markdown
    assert "## API Dependencies or Provisional Contracts" in markdown
    assert "## Loading/Error/Empty States" in markdown
    assert "## Open FE Questions" in markdown
    assert "## Provisional Markers" in markdown
    assert "Email Address" in markdown
    assert "`POST` `/customers` for Create Customer" in markdown
    assert "Show inline saving spinner" in markdown


def test_run_store_persists_fe_spec_markdown(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-009",
    )
    store.create()
    screen = _canonical_screen()
    markdown = render_fe_spec_markdown(
        _catalog_entry(),
        screen,
        matrices=build_screen_matrix_bundle(screen),
        review=build_gap_review_document(screen),
        readiness=evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST).screens[0],
    )

    store.save_fe_spec_markdown("customer-form", markdown)

    assert store.load_fe_spec_markdown("customer-form") == markdown
    assert store.screen_paths("customer-form").fe_markdown.exists()


def test_render_be_spec_markdown_outputs_expected_sections() -> None:
    screen = _canonical_screen_with_be_uncertainty()
    matrices = build_screen_matrix_bundle(screen)
    review = build_gap_review_document(screen)
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST).screens[0]

    markdown = render_be_spec_markdown(
        _catalog_entry(),
        screen,
        matrices=matrices,
        review=review,
        readiness=readiness,
    )

    assert markdown.startswith("# BE Spec: Customer Form\n")
    assert "## Entities and Data Contracts" in markdown
    assert "## Workflows and Business Rules" in markdown
    assert "## Endpoints, Events, and Jobs" in markdown
    assert "## Validation Rules and Permissions" in markdown
    assert "## Contradictions" in markdown
    assert "## Open BE Questions" in markdown
    assert "CustomerCreated" in markdown
    assert "Only sales managers can override duplicate-email blocks" in markdown
    assert "Create Customer response schema omits the loyalty tier payload" in markdown
    assert "Should Create Customer publish a CRM sync event after persistence?" in markdown


def test_render_question_backlog_markdown_groups_missing_contradictions_and_owners() -> None:
    review = build_gap_review_document(_canonical_screen_with_be_uncertainty())

    markdown = render_question_backlog_markdown(review)

    assert markdown.startswith("# Questions Backlog\n")
    assert "## MISSING" in markdown
    assert "## CONTRADICTED" in markdown
    assert "## QUESTION_FOR_BA" in markdown
    assert "## QUESTION_FOR_TECH_LEAD" in markdown
    assert "## QUESTION_FOR_DESIGN" in markdown
    assert "Create Customer response schema omits the loyalty tier payload" in markdown
    assert "Requirements disagree on whether duplicate emails are rejected or merged" in markdown
    assert "Should Create Customer publish a CRM sync event after persistence?" in markdown


def test_run_store_persists_be_spec_and_question_backlog(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-009",
    )
    store.create()
    screen = _canonical_screen_with_be_uncertainty()
    review = build_gap_review_document(screen)
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST).screens[0]

    be_markdown = render_be_spec_markdown(
        _catalog_entry(),
        screen,
        matrices=build_screen_matrix_bundle(screen),
        review=review,
        readiness=readiness,
    )
    questions_markdown = render_question_backlog_markdown(review)

    store.save_be_spec_markdown("customer-form", be_markdown)
    store.save_questions_markdown("customer-form", questions_markdown)

    assert store.load_be_spec_markdown("customer-form") == be_markdown
    assert store.load_questions_markdown("customer-form") == questions_markdown
    assert store.screen_paths("customer-form").be_markdown.exists()
    assert store.screen_paths("customer-form").questions_markdown.exists()


def test_clean_feature_source_manifest_matches_fixture_goldens() -> None:
    manifest = _clean_feature_manifest()

    _assert_golden_text(
        FixtureScenario.CLEAN_FEATURE,
        "source-manifest.md",
        render_source_manifest_markdown(manifest),
    )
    _assert_golden_text(
        FixtureScenario.CLEAN_FEATURE,
        "source-manifest-json.json",
        render_source_manifest_json(manifest),
    )


def test_note_clarification_source_manifest_matches_fixture_goldens() -> None:
    manifest = _note_clarification_manifest()

    _assert_golden_text(
        FixtureScenario.NOTE_CLARIFICATION,
        "source-manifest.md",
        render_source_manifest_markdown(manifest),
    )
    _assert_golden_text(
        FixtureScenario.NOTE_CLARIFICATION,
        "source-manifest-json.json",
        render_source_manifest_json(manifest),
    )


def test_contradictory_sources_question_backlog_matches_fixture_golden() -> None:
    review = build_gap_review_document(_contradictory_sources_screen())

    _assert_golden_text(
        FixtureScenario.CONTRADICTORY_SOURCES,
        "questions.customer-form.md",
        render_question_backlog_markdown(review),
    )
