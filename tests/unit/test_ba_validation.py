"""Unit tests for deterministic BA source-quality and bundle validation rules."""

from __future__ import annotations

import json
from pathlib import Path

from notebooklm_mcp.ba.contracts import (
    build_provisional_contract_artifacts,
    render_contract_yaml,
    render_mock_data_json,
)
from notebooklm_mcp.ba.gaps import build_gap_review_document
from notebooklm_mcp.ba.matrices import build_screen_matrix_bundle
from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    HaltRecommendation,
    ParseQuality,
    ReadinessSummary,
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
    ValidationStatus,
    WorkflowMode,
)
from notebooklm_mcp.ba.readiness import evaluate_readiness
from notebooklm_mcp.ba.rendering import (
    ScreenBundleArtifact,
    render_action_rule_matrix_csv,
    render_api_matrix_csv,
    render_be_spec_markdown,
    render_fe_spec_markdown,
    render_field_matrix_csv,
    render_question_backlog_markdown,
    render_readiness_summary_markdown,
    render_source_manifest_markdown,
    render_terminology_markdown,
    write_bundle_layout,
)
from notebooklm_mcp.ba.run_store import BARunStore
from notebooklm_mcp.ba.validation import assess_source_quality, validate_bundle_artifacts


def _manifest_row(source_type: SourceType = SourceType.PRIMARY_REQUIREMENT) -> SourceManifestRow:
    return SourceManifestRow(
        source_key="requirements",
        source_type=source_type,
        priority=SourcePriority.REQUIRED,
        content_kind=SourceContentKind.FILE_PATH,
        source_ref="requirements.pdf",
        title="Requirements PDF",
    )


def _snapshot_record(char_count: int) -> SourceSnapshotRecord:
    return SourceSnapshotRecord(
        source_key="requirements",
        snapshot_id="requirements-abc123",
        content_hash="abc123",
        fulltext_path="docs/features/customer-create/runs/run-008/snapshots/requirements/requirements-abc123/fulltext.txt",
        char_count=char_count,
    )


def _evidence(snapshot_id: str, locator: str) -> EvidenceRef:
    return EvidenceRef(
        source_key="requirements",
        snapshot_id=snapshot_id,
        locator=locator,
    )


def _catalog() -> ScreenCatalogDocument:
    return ScreenCatalogDocument(
        run_id="run-008",
        feature_key="customer-create",
        screens=[
            ScreenCatalogEntry(
                screen_id="customer-form",
                screen_name="Customer Form",
                purpose="Create a customer record",
                roles=["Sales"],
                entry_points=["Customer list"],
                exit_points=["Customer detail"],
                main_actions=["Save customer"],
                dependencies=["Create Customer"],
                related_sources=["requirements"],
                evidence=[_evidence("requirements-abc123", "1-3")],
            )
        ],
    )


def _screen(snapshot_id: str) -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        run_id="run-008",
        screen_id="customer-form",
        mode=WorkflowMode.FE_FIRST,
        shared_facts=[
            CanonicalFact(
                fact_id="customer-save-rule",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={
                    "action_name": "Save customer",
                    "rule": "Customer email must be unique",
                    "outcome": "Reject duplicate email submissions",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(snapshot_id, "7-10")],
            )
        ],
        fe_facts=[
            CanonicalFact(
                fact_id="customer-email-field",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "email",
                    "label": "Email Address",
                    "field_type": "email",
                    "required": True,
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(snapshot_id, "11-14")],
            )
        ],
        be_facts=[
            CanonicalFact(
                fact_id="create-customer-endpoint",
                domain=FactDomain.BE,
                category="endpoint",
                value={
                    "endpoint_name": "Create Customer",
                    "method": "POST",
                    "path": "/customers",
                    "request_body": "customer payload",
                    "response_body": "created customer",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(snapshot_id, "15-19")],
            )
        ],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def _seed_valid_bundle(
    tmp_path: Path,
) -> tuple[
    BARunStore,
    SourceManifestDocument,
    ScreenCatalogDocument,
    ReadinessSummary,
    ScreenBundleArtifact,
]:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-008",
    )
    store.create(mode_requested=WorkflowMode.FE_FIRST)

    content = """
    # Overview
    Customer create requirements for the sales workflow.

    ## Requirements
    - Users can create a customer from the customer form.
    - Email Address is required and must be unique.
    - Saving the form calls POST /customers.

    ## Acceptance Criteria
    - Duplicate email submissions are rejected.
    """.strip()
    record = store.persist_source_snapshot(
        source_key="requirements",
        notebook_source_id="src-1",
        title="Requirements PDF",
        source_type="pdf",
        content=content,
        char_count=len(content),
    )
    manifest = SourceManifestDocument(
        run_id="run-008",
        feature_key="customer-create",
        rows=[
            _manifest_row().model_copy(
                update={
                    "snapshot_id": record.snapshot_id,
                    "notebook_source_id": "src-1",
                    "parse_quality": ParseQuality.HIGH,
                    "status": SourceLifecycleStatus.READY,
                    "used_in_screens": ["customer-form"],
                }
            )
        ],
    )
    store.save_source_manifest_artifacts(
        manifest,
        markdown=render_source_manifest_markdown(manifest),
    )

    terminology = TerminologyDocument(
        run_id="run-008",
        feature_key="customer-create",
        entries=[
            TerminologyEntry(
                standard_term="Customer",
                aliases=["Client"],
                evidence=[_evidence(record.snapshot_id, "1-2")],
            )
        ],
    )
    store.save_terminology_artifacts(
        terminology,
        markdown=render_terminology_markdown(terminology),
    )

    catalog = _catalog()
    store.save_screen_catalog(catalog)
    screen = _screen(record.snapshot_id)
    store.save_canonical_screen(screen)

    matrices = build_screen_matrix_bundle(screen)
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST)
    review = build_gap_review_document(screen)
    contract_artifacts = build_provisional_contract_artifacts(
        screen,
        matrices=matrices,
        readiness=readiness.screens[0],
    )
    assert contract_artifacts is not None

    screen_artifact = ScreenBundleArtifact(
        screen_id=screen.screen_id,
        canonical_json=screen.model_dump_json(indent=2),
        fe_markdown=render_fe_spec_markdown(
            catalog.screens[0],
            screen,
            matrices=matrices,
            review=review,
            readiness=readiness.screens[0],
        ),
        be_markdown=render_be_spec_markdown(
            catalog.screens[0],
            screen,
            matrices=matrices,
            review=review,
            readiness=readiness.screens[0],
        ),
        questions_markdown=render_question_backlog_markdown(review),
        field_matrix_csv=render_field_matrix_csv(matrices.field_rows),
        action_rule_matrix_csv=render_action_rule_matrix_csv(matrices.action_rule_rows),
        api_matrix_csv=render_api_matrix_csv(matrices.api_rows),
        contract_yaml=render_contract_yaml(contract_artifacts.openapi_document),
        mock_data_json=render_mock_data_json(contract_artifacts.mock_data),
    )
    write_bundle_layout(
        store,
        source_manifest=manifest,
        screen_catalog=catalog,
        readiness=readiness,
        screen_artifacts=[screen_artifact],
        terminology=terminology,
        run_audit=store.load_run_audit(),
    )
    return store, manifest, catalog, readiness, screen_artifact


def test_assess_source_quality_marks_structured_requirement_as_high_quality() -> None:
    content = """
    # Overview
    This feature lets analysts register customer requirements, ingest typed sources, and review
    generated implementation packs before they are handed to engineering.
    The workflow must stay evidence-first and preserve enough audit detail to explain every
    downstream extraction and rendering decision.

    ## Requirements
    - The workflow must ingest typed sources before extraction begins.
    - The workflow must preserve source keys across reruns for audit continuity.
    - The workflow must snapshot source text before canonical extraction so rerun detection
      can compare stable source versions instead of moving live notebook state.
    - The workflow must persist parse-quality diagnostics for each current snapshot.

    ## Acceptance Criteria
    - Analysts can inspect readiness before canonical extraction.
    - Snapshot evidence is persisted before bundle generation.
    - Low-quality primary inputs are surfaced before they contaminate extraction.
    - The audit trail keeps enough detail to explain why the workflow proceeded or stopped.
    """.strip()

    assessment = assess_source_quality(_manifest_row(), _snapshot_record(len(content)), content)

    assert assessment.parse_quality is ParseQuality.HIGH
    assert assessment.recommendation is HaltRecommendation.PROCEED
    assert assessment.heading_count >= 3
    assert assessment.missing_sections == []


def test_assess_source_quality_halts_on_failed_primary_snapshot() -> None:
    content = "� � � I l 1 | ocr ocr"

    assessment = assess_source_quality(_manifest_row(), _snapshot_record(len(content)), content)

    assert assessment.parse_quality is ParseQuality.FAILED
    assert assessment.recommendation is HaltRecommendation.HALT
    assert "replacement_character" in assessment.encoding_issues
    assert assessment.suspected_scan_indicators


def test_run_store_persists_and_loads_source_quality_assessment(tmp_path: Path) -> None:
    content = """
    # Overview
    Requirement summary for bundle generation.

    ## Requirements
    - Persist snapshots before extraction.

    ## Acceptance Criteria
    - Hashes are stable across reruns.
    """.strip()
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-008",
    )
    store.create()
    record = store.persist_source_snapshot(
        source_key="requirements",
        notebook_source_id="src-1",
        title="Requirements PDF",
        source_type="pdf",
        content=content,
        char_count=len(content),
    )

    assessment = assess_source_quality(
        _manifest_row(),
        record,
        store.load_source_snapshot_text("requirements", record.snapshot_id),
    )
    store.save_source_quality_assessment("requirements", record.snapshot_id, assessment)
    loaded = store.load_source_quality_assessment(
        "requirements",
        record.snapshot_id,
        type(assessment),
    )

    assert loaded.parse_quality is ParseQuality.HIGH
    assert loaded.snapshot_id == record.snapshot_id


def test_validate_bundle_artifacts_persists_screen_qa_report_for_valid_bundle(
    tmp_path: Path,
) -> None:
    store, manifest, catalog, readiness, _screen_artifact = _seed_valid_bundle(tmp_path)

    report = validate_bundle_artifacts(store, manifest, catalog, readiness)

    assert report.status is ValidationStatus.PASS
    assert report.findings == []
    qa_report = json.loads(store.load_qa_report_json("customer-form"))
    assert qa_report["screen_id"] == "customer-form"
    assert qa_report["status"] == "PASS"
    assert qa_report["bundle_status"] == "PASS"
    assert qa_report["findings"] == []


def test_validate_bundle_artifacts_fails_on_contract_mock_misalignment(tmp_path: Path) -> None:
    store, manifest, catalog, readiness, _screen_artifact = _seed_valid_bundle(tmp_path)
    store.save_mock_data_json(
        "customer-form",
        json.dumps(
            {
                "contract_status": "PROVISIONAL",
                "feature_key": "customer-create",
                "run_id": "run-008",
                "screen_id": "customer-form",
                "operations": {},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    report = validate_bundle_artifacts(store, manifest, catalog, readiness)

    assert report.status is ValidationStatus.FAIL
    assert any(finding.code == "contract-mock-misalignment" for finding in report.findings)
    qa_report = json.loads(store.load_qa_report_json("customer-form"))
    assert qa_report["status"] == "FAIL"
    assert any(finding["code"] == "contract-mock-misalignment" for finding in qa_report["findings"])


def test_validate_bundle_artifacts_repairs_missing_feature_artifact(tmp_path: Path) -> None:
    store, manifest, catalog, readiness, screen_artifact = _seed_valid_bundle(tmp_path)
    store.feature_paths.readiness_summary_markdown.unlink()

    report = validate_bundle_artifacts(
        store,
        manifest,
        catalog,
        readiness,
        screen_artifacts=[screen_artifact],
    )

    assert report.status is ValidationStatus.WARN
    assert store.feature_paths.readiness_summary_markdown.read_text(encoding="utf-8") == (
        render_readiness_summary_markdown(readiness)
    )
    repair_finding = next(
        finding
        for finding in report.findings
        if finding.code == "deterministic-repair-applied"
        and finding.file_path == "03-readiness-summary.md"
    )
    assert repair_finding.details["previous_state"] == "missing"
    qa_report = json.loads(store.load_qa_report_json("customer-form"))
    assert qa_report["status"] == "WARN"
    assert any(
        finding["code"] == "deterministic-repair-applied"
        and finding["file_path"] == "03-readiness-summary.md"
        for finding in qa_report["findings"]
    )


def test_validate_bundle_artifacts_repairs_contract_mock_drift_when_rendered_copy_exists(
    tmp_path: Path,
) -> None:
    store, manifest, catalog, readiness, screen_artifact = _seed_valid_bundle(tmp_path)
    assert screen_artifact.mock_data_json is not None
    store.save_mock_data_json(
        "customer-form",
        json.dumps(
            {
                "contract_status": "PROVISIONAL",
                "feature_key": "customer-create",
                "run_id": "run-008",
                "screen_id": "customer-form",
                "operations": {},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    report = validate_bundle_artifacts(
        store,
        manifest,
        catalog,
        readiness,
        screen_artifacts=[screen_artifact],
    )

    assert report.status is ValidationStatus.WARN
    assert store.load_mock_data_json("customer-form") == screen_artifact.mock_data_json
    assert not any(finding.code == "contract-mock-misalignment" for finding in report.findings)
    repair_finding = next(
        finding
        for finding in report.findings
        if finding.code == "deterministic-repair-applied"
        and finding.file_path == "screens/customer-form/mock-data.json"
    )
    assert repair_finding.details["previous_state"] == "drifted"


def test_validate_bundle_artifacts_does_not_repair_missing_evidence_semantics(
    tmp_path: Path,
) -> None:
    store, manifest, catalog, readiness, screen_artifact = _seed_valid_bundle(tmp_path)
    bad_terminology = TerminologyDocument(
        run_id="run-008",
        feature_key="customer-create",
        entries=[
            TerminologyEntry(
                standard_term="Customer",
                aliases=["Client"],
                evidence=[
                    EvidenceRef(
                        source_key="clarification-note",
                        snapshot_id="clarification-note-1",
                        locator="1-2",
                    )
                ],
            )
        ],
    )
    store.save_terminology_artifacts(
        bad_terminology,
        markdown=render_terminology_markdown(bad_terminology),
    )

    report = validate_bundle_artifacts(
        store,
        manifest,
        catalog,
        readiness,
        screen_artifacts=[screen_artifact],
        terminology=bad_terminology,
    )

    assert report.status is ValidationStatus.FAIL
    assert any(finding.code == "terminology-missing-source" for finding in report.findings)
    assert all(finding.code != "deterministic-repair-applied" for finding in report.findings)
