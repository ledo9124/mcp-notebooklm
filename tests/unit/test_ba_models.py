"""Unit tests for BA shared models and schema version policy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    ContradictionClaim,
    ContradictionRecord,
    ContractMetadata,
    ContractStatus,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    GapReviewDocument,
    HaltRecommendation,
    ParseQuality,
    ReadinessDecision,
    ReadinessSummary,
    RunAuditDocument,
    RunAuditEntry,
    RunEventRecord,
    RunEventType,
    RunStateSnapshot,
    RunStatus,
    RunStep,
    RunStepRecord,
    RunStepStatus,
    ScreenCatalogDocument,
    SourceContentKind,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceQualityAssessment,
    SourceRegistrationResult,
    SourceRegistrationWarning,
    SourceRegistrationWarningCode,
    SourceType,
    TerminologyDocument,
    ValidationReport,
    ValidationStatus,
    WorkflowMode,
)
from notebooklm_mcp.ba.schema_version import (
    CURRENT_SCHEMA_VERSIONS,
    SchemaChangeKind,
    SchemaFamily,
    SchemaVersion,
    classify_change,
    is_compatible,
)


def _evidence() -> EvidenceRef:
    return EvidenceRef(source_key="ba-pdf", snapshot_id="snap-1", locator="p.3")


def test_document_models_default_to_current_schema_tokens() -> None:
    manifest = SourceManifestDocument(run_id="run-1", feature_key="customer-create")
    terminology = TerminologyDocument(run_id="run-1", feature_key="customer-create")
    catalog = ScreenCatalogDocument(run_id="run-1", feature_key="customer-create")
    readiness = ReadinessSummary(
        run_id="run-1",
        feature_key="customer-create",
        feature_mode=WorkflowMode.FE_FIRST,
        decision=ReadinessDecision.PARTIAL_READY_NEEDS_CLARIFICATION,
    )
    gap_review = GapReviewDocument(
        run_id="run-1",
        feature_key="customer-create",
        screen_id="customer-form",
    )
    contract = ContractMetadata(
        run_id="run-1",
        feature_key="customer-create",
        contract_status=ContractStatus.PROVISIONAL,
    )
    report = ValidationReport(
        run_id="run-1",
        feature_key="customer-create",
        status=ValidationStatus.PASS,
    )

    assert manifest.schema_version == CURRENT_SCHEMA_VERSIONS[SchemaFamily.SOURCE_MANIFEST].token
    assert terminology.schema_version == CURRENT_SCHEMA_VERSIONS[SchemaFamily.TERMINOLOGY].token
    assert catalog.schema_version == CURRENT_SCHEMA_VERSIONS[SchemaFamily.SCREEN_CATALOG].token
    assert gap_review.schema_version == CURRENT_SCHEMA_VERSIONS[SchemaFamily.GAP_REVIEW].token
    assert readiness.schema_version == CURRENT_SCHEMA_VERSIONS[SchemaFamily.READINESS_SUMMARY].token
    assert contract.schema_version == CURRENT_SCHEMA_VERSIONS[SchemaFamily.CONTRACT_METADATA].token
    assert report.schema_version == CURRENT_SCHEMA_VERSIONS[SchemaFamily.VALIDATION_REPORT].token


def test_run_state_snapshot_defaults_schema_version() -> None:
    state = RunStateSnapshot(
        run_id="run-1",
        feature_key="customer-create",
        status=RunStatus.RUNNING,
        current_step=RunStep.REGISTER_SOURCES,
        steps=[
            RunStepRecord(
                step=RunStep.START_RUN,
                status=RunStepStatus.COMPLETED,
                metadata={"source_count": 3},
            )
        ],
        events=[
            RunEventRecord(
                event_type=RunEventType.STARTED,
                step=RunStep.REGISTER_SOURCES,
                message="Registered sources started",
                details={"source_keys": ["ba-pdf"]},
            )
        ],
    )

    assert state.schema_version == CURRENT_SCHEMA_VERSIONS[SchemaFamily.RUN_STATE].token
    assert state.steps[0].metadata == {"source_count": 3}
    assert state.events[0].details == {"source_keys": ["ba-pdf"]}


def test_run_audit_document_requires_matching_feature_keys() -> None:
    state = RunStateSnapshot(
        run_id="run-1",
        feature_key="customer-create",
        status=RunStatus.DEGRADED,
    )

    audit = RunAuditDocument(
        feature_key="customer-create",
        entries=[RunAuditEntry(recorded_at="2026-03-12T10:00:00+00:00", snapshot=state)],
    )

    assert audit.entries[0].snapshot.status is RunStatus.DEGRADED

    with pytest.raises(ValidationError):
        RunAuditDocument(
            feature_key="orders",
            entries=[RunAuditEntry(recorded_at="2026-03-12T10:00:00+00:00", snapshot=state)],
        )


def test_confirmed_fact_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        CanonicalFact(
            fact_id="fact-1",
            domain=FactDomain.FE,
            category="field",
            value="name",
            status=FactStatus.CONFIRMED,
        )


def test_provisional_fact_requires_rationale() -> None:
    with pytest.raises(ValidationError):
        CanonicalFact(
            fact_id="fact-2",
            domain=FactDomain.BE,
            category="endpoint",
            value="/customers",
            status=FactStatus.PROVISIONAL,
        )


def test_canonical_screen_accepts_valid_fact_and_defaults_schema() -> None:
    fact = CanonicalFact(
        fact_id="fact-3",
        domain=FactDomain.SHARED,
        category="business_rule",
        value="Customer email must be unique",
        status=FactStatus.CONFIRMED,
        confidence=0.92,
        evidence=[_evidence()],
    )

    screen = CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.BALANCED,
        run_id="run-1",
        shared_facts=[fact],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )

    assert screen.shared_facts[0].fact_id == "fact-3"
    assert screen.schema_version == CURRENT_SCHEMA_VERSIONS[SchemaFamily.CANONICAL_SCREEN].token


def test_contradiction_requires_at_least_two_claims() -> None:
    with pytest.raises(ValidationError):
        ContradictionRecord(
            contradiction_id="ctr-1",
            summary="Two payload formats conflict",
            claims=[ContradictionClaim(claim="Response uses snake_case", evidence=[_evidence()])],
        )


def test_schema_change_policy_classifies_and_bumps_versions() -> None:
    base = SchemaVersion(family=SchemaFamily.CANONICAL_SCREEN, major=1, minor=2)

    assert classify_change(added_optional_fields=True) is SchemaChangeKind.ADDITIVE
    assert classify_change(renamed_fields=True) is SchemaChangeKind.BREAKING
    assert base.bump(SchemaChangeKind.ADDITIVE).token == "ba.canonical_screen.v1.3"
    assert base.bump(SchemaChangeKind.BREAKING).token == "ba.canonical_screen.v2.0"


def test_schema_compatibility_is_same_family_same_major() -> None:
    compatible = SchemaVersion(family=SchemaFamily.SOURCE_MANIFEST, major=1, minor=4)
    incompatible_major = SchemaVersion(family=SchemaFamily.SOURCE_MANIFEST, major=2, minor=0)
    incompatible_family = SchemaVersion(family=SchemaFamily.TERMINOLOGY, major=1, minor=0)

    assert is_compatible(compatible, SchemaFamily.SOURCE_MANIFEST) is True
    assert is_compatible(incompatible_major, SchemaFamily.SOURCE_MANIFEST) is False
    assert is_compatible(incompatible_family, SchemaFamily.SOURCE_MANIFEST) is False


def test_source_manifest_row_is_strict_but_allows_pre_ingest_shape() -> None:
    row = SourceManifestRow(
        source_key="ba-pdf",
        source_type=SourceType.PRIMARY_REQUIREMENT,
        priority=SourcePriority.REQUIRED,
        content_kind=SourceContentKind.FILE_PATH,
        source_ref="requirements/ba.pdf",
        title="ba.pdf",
        notes=["uploaded by analyst"],
    )

    assert row.status.value == "REGISTERED"
    assert row.snapshot_id is None
    assert row.content_kind is SourceContentKind.FILE_PATH


def test_source_registration_result_carries_typed_warning_metadata() -> None:
    result = SourceRegistrationResult(
        manifest=SourceManifestDocument(
            run_id="run-1",
            feature_key="customer-create",
        ),
        warnings=[
            SourceRegistrationWarning(
                code=SourceRegistrationWarningCode.MISSING_CRITICAL_SOURCE_TYPE,
                message="PRIMARY_REQUIREMENT missing",
            )
        ],
        missing_critical_source_types=[SourceType.PRIMARY_REQUIREMENT],
    )

    assert result.warnings[0].code is SourceRegistrationWarningCode.MISSING_CRITICAL_SOURCE_TYPE
    assert result.missing_critical_source_types == [SourceType.PRIMARY_REQUIREMENT]


def test_source_quality_assessment_carries_deterministic_diagnostics() -> None:
    assessment = SourceQualityAssessment(
        source_key="ba-pdf",
        snapshot_id="snap-1",
        parse_quality=ParseQuality.LOW,
        character_count=1200,
        heading_count=1,
        table_density=0.0,
        suspected_scan_indicators=["ocr_garble"],
        recommendation=HaltRecommendation.CLARIFICATION_FIRST,
    )

    assert assessment.recommendation is HaltRecommendation.CLARIFICATION_FIRST
