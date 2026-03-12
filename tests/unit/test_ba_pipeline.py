"""Unit tests for the internal BA pipeline orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from notebooklm_mcp.ba.adapter import (
    BAIngestWaitResult,
    BASourceOperationResult,
    BASourceReadinessState,
    BASourceSnapshot,
)
from notebooklm_mcp.ba.extraction import (
    CanonicalScreenExtractionResult,
    ScreenCatalogExtractionResult,
    StructuredParseQuality,
    TerminologyExtractionResult,
)
from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    GapKind,
    GapRecord,
    GapSeverity,
    HaltRecommendation,
    ParseQuality,
    RunStatus,
    RunStep,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    SourceContentKind,
    SourceLifecycleStatus,
    SourcePriority,
    SourceType,
    TerminologyDocument,
    TerminologyEntry,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    WorkflowMode,
)
from notebooklm_mcp.ba.pipeline import BAPipelineServices, run_pipeline
from notebooklm_mcp.ba.run_store import BARunStore, SourceRegistrationInput


def _store(tmp_path: Path, *, run_id: str) -> BARunStore:
    return BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id=run_id,
    )


def _source_input() -> SourceRegistrationInput:
    return SourceRegistrationInput(
        path_or_url_or_text="requirements/customer-create.md",
        source_key="requirements",
        source_type=SourceType.PRIMARY_REQUIREMENT,
        priority=SourcePriority.REQUIRED,
        content_kind=SourceContentKind.FILE_PATH,
        title="Customer Create Requirements",
        notes=["approved by BA lead"],
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


def _evidence(*, locator: str = "10-20") -> EvidenceRef:
    return EvidenceRef(
        source_key="requirements",
        snapshot_id="requirements-snapshot",
        locator=locator,
    )


def _gap(
    gap_id: str,
    *,
    kind: GapKind,
    workstreams: list[FactDomain],
    severity: GapSeverity = GapSeverity.HIGH,
) -> GapRecord:
    return GapRecord(
        gap_id=gap_id,
        kind=kind,
        summary=gap_id.replace("-", " "),
        severity=severity,
        screen_id="customer-form",
        owner="Backend lead",
        blocking_workstreams=workstreams,
        evidence=[_evidence(locator=f"{gap_id}-loc")],
    )


def _screen(*, missing_info: list[GapRecord] | None = None) -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        run_id="run-001",
        screen_id="customer-form",
        mode=WorkflowMode.AUTO,
        shared_facts=[
            CanonicalFact(
                fact_id="fact-save-rule",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={
                    "action_name": "Save customer",
                    "trigger": "User clicks Save",
                    "rule": "Email must be unique before customer creation completes",
                    "outcome": "Show duplicate email validation and block submit",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(locator="20-28")],
            )
        ],
        fe_facts=[
            CanonicalFact(
                fact_id="fact-email",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "email",
                    "label": "Email Address",
                    "field_type": "email",
                    "required": True,
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(locator="30-34")],
            )
        ],
        be_facts=[
            CanonicalFact(
                fact_id="fact-create-customer",
                domain=FactDomain.BE,
                category="endpoint",
                value={
                    "endpoint_name": "Create Customer",
                    "method": "POST",
                    "path": "/customers",
                    "request": "Customer payload",
                    "response": "Created customer",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(locator="40-52")],
            )
        ],
        missing_info=missing_info or [],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def _validation_report(status: ValidationStatus) -> ValidationReport:
    findings = (
        [
            ValidationFinding(
                code="missing-qa-report",
                severity=ValidationSeverity.ERROR,
                message="Bundle validation found a deterministic failure.",
                file_path="screens/customer-form/qa-report.json",
            )
        ]
        if status is ValidationStatus.FAIL
        else []
    )
    return ValidationReport(
        run_id="run-001",
        feature_key="customer-create",
        status=status,
        findings=findings,
    )


class _ServiceHarness:
    def __init__(
        self,
        *,
        canonical_screen: CanonicalScreen,
        validation_report: ValidationReport,
    ) -> None:
        self.catalog_entry = _catalog_entry()
        self.canonical_screen = canonical_screen
        self.validation_report = validation_report
        self.validate_calls = 0

    async def ingest_and_wait(
        self,
        _store: BARunStore,
        manifest,
    ) -> BAIngestWaitResult:
        updated_manifest = manifest.model_copy(
            update={
                "rows": [
                    row.model_copy(
                        update={
                            "status": SourceLifecycleStatus.READY,
                            "notebook_source_id": "src-1",
                        }
                    )
                    for row in manifest.rows
                ]
            }
        )
        return BAIngestWaitResult(
            notebook_id="nb-1",
            manifest=updated_manifest,
            source_results=(
                BASourceOperationResult(
                    source_key="requirements",
                    notebook_id="nb-1",
                    notebook_source_id="src-1",
                    title="Customer Create Requirements",
                    readiness_state=BASourceReadinessState.READY,
                    source_type="pdf",
                    status=1,
                ),
            ),
            selected_source_keys=("requirements",),
            recommendation=HaltRecommendation.PROCEED,
        )

    async def snapshot_sources(
        self,
        _store: BARunStore,
        _manifest,
        _ingest_result: BAIngestWaitResult,
    ) -> list[tuple[str, BASourceSnapshot]]:
        return [
            (
                "requirements",
                BASourceSnapshot(
                    notebook_id="nb-1",
                    source_id="src-1",
                    title="Customer Create Requirements",
                    source_type="pdf",
                    status=1,
                    is_ready=True,
                    url=None,
                    content=(
                        "# Overview\n\n"
                        "## Requirements\n\n"
                        "Customer email is required.\n\n"
                        "## Acceptance Criteria\n\n"
                        "The record saves only when the email is unique.\n"
                    ),
                    char_count=180,
                    guide_summary="Requirement source for customer create",
                    guide_keywords=("customer", "create", "email"),
                    is_fresh=True,
                ),
            )
        ]

    async def extract_terminology(
        self,
        _store: BARunStore,
        _manifest,
        _snapshots,
    ) -> TerminologyExtractionResult:
        return TerminologyExtractionResult(
            document=TerminologyDocument(
                run_id="run-001",
                feature_key="customer-create",
                entries=[
                    TerminologyEntry(
                        standard_term="Customer",
                        aliases=["Account"],
                        semantic_notes=["Primary business entity being created."],
                        evidence=[_evidence(locator="60-66")],
                    )
                ],
            ),
            raw_text="{}",
            parse_quality=StructuredParseQuality.EXACT,
        )

    async def extract_screen_catalog(
        self,
        _store: BARunStore,
        _manifest,
        _terminology,
        _snapshots,
    ) -> ScreenCatalogExtractionResult:
        return ScreenCatalogExtractionResult(
            document=ScreenCatalogDocument(
                run_id="run-001",
                feature_key="customer-create",
                screens=[self.catalog_entry],
            ),
            raw_text="{}",
            parse_quality=StructuredParseQuality.EXACT,
        )

    async def extract_canonical(
        self,
        _store: BARunStore,
        _entry: ScreenCatalogEntry,
        _manifest,
        _terminology,
        _snapshots,
        _mode_requested: WorkflowMode,
    ) -> CanonicalScreenExtractionResult:
        return CanonicalScreenExtractionResult(
            screen=self.canonical_screen,
            raw_text="{}",
            parse_quality=StructuredParseQuality.EXACT,
        )

    async def validate_bundle(
        self,
        _store: BARunStore,
        _source_manifest,
        _screen_catalog,
        _readiness,
        _screen_artifacts,
    ) -> ValidationReport:
        self.validate_calls += 1
        return self.validation_report


def _services(
    *,
    canonical_screen: CanonicalScreen,
    validation_report: ValidationReport,
) -> tuple[_ServiceHarness, BAPipelineServices]:
    harness = _ServiceHarness(
        canonical_screen=canonical_screen,
        validation_report=validation_report,
    )
    services = BAPipelineServices(
        ingest_and_wait=harness.ingest_and_wait,
        snapshot_sources=harness.snapshot_sources,
        extract_terminology=harness.extract_terminology,
        extract_screen_catalog=harness.extract_screen_catalog,
        extract_canonical=harness.extract_canonical,
        validate_bundle=harness.validate_bundle,
    )
    return harness, services


@pytest.mark.asyncio
async def test_run_pipeline_completes_full_fe_first_bundle_flow(tmp_path: Path) -> None:
    store = _store(tmp_path, run_id="run-001")
    harness, services = _services(
        canonical_screen=_screen(
            missing_info=[
                _gap(
                    "missing-backend-contract",
                    kind=GapKind.MISSING_BACKEND_CONTRACT,
                    workstreams=[FactDomain.BE],
                )
            ]
        ),
        validation_report=_validation_report(ValidationStatus.PASS),
    )

    result = await run_pipeline(
        store=store,
        services=services,
        mode_requested=WorkflowMode.AUTO,
        source_inputs=[_source_input()],
    )

    assert result.state.status is RunStatus.COMPLETED
    assert result.stop_step is None
    assert result.readiness is not None
    assert result.readiness.decision.value == "READY_FOR_FE_WITH_PROVISIONAL_CONTRACT"
    assert "00-overview.md" in result.bundle_files
    assert "screens/customer-form/contract.provisional.yaml" in result.bundle_files
    assert store.screen_paths("customer-form").contract_yaml.exists()
    assert store.screen_paths("customer-form").mock_data_json.exists()
    assert harness.validate_calls == 1
    assert result.validation_report is not None
    assert result.validation_report.status is ValidationStatus.PASS
    assert [step.step for step in result.state.steps][-1] is RunStep.VALIDATE_BUNDLE


@pytest.mark.asyncio
async def test_run_pipeline_dry_run_stops_after_readiness_assessment(tmp_path: Path) -> None:
    store = _store(tmp_path, run_id="run-001")
    harness, services = _services(
        canonical_screen=_screen(
            missing_info=[
                _gap(
                    "missing-backend-contract",
                    kind=GapKind.MISSING_BACKEND_CONTRACT,
                    workstreams=[FactDomain.BE],
                )
            ]
        ),
        validation_report=_validation_report(ValidationStatus.PASS),
    )

    result = await run_pipeline(
        store=store,
        services=services,
        mode_requested=WorkflowMode.AUTO,
        source_inputs=[_source_input()],
        dry_run=True,
    )

    assert result.state.status is RunStatus.COMPLETED
    assert result.stop_step is RunStep.EVALUATE_READINESS
    assert result.stop_reason == "dry_run"
    assert result.bundle_files == {}
    assert harness.validate_calls == 0
    assert not store.screen_paths("customer-form").contract_yaml.exists()
    assert store.feature_paths.readiness_summary_markdown.exists()
    assert RunStep.GENERATE_CONTRACTS not in {step.step for step in result.state.steps}


@pytest.mark.asyncio
async def test_run_pipeline_marks_readiness_blockers_as_degraded(tmp_path: Path) -> None:
    store = _store(tmp_path, run_id="run-001")
    harness, services = _services(
        canonical_screen=_screen(
            missing_info=[
                _gap(
                    "missing-requirement-detail",
                    kind=GapKind.MISSING_REQUIREMENT_DETAIL,
                    workstreams=[FactDomain.SHARED],
                )
            ]
        ),
        validation_report=_validation_report(ValidationStatus.PASS),
    )

    result = await run_pipeline(
        store=store,
        services=services,
        mode_requested=WorkflowMode.AUTO,
        source_inputs=[_source_input()],
    )

    assert result.state.status is RunStatus.DEGRADED
    assert result.state.current_step is RunStep.EVALUATE_READINESS
    assert result.stop_step is RunStep.EVALUATE_READINESS
    assert result.bundle_files == {}
    assert harness.validate_calls == 0
    assert RunStep.GENERATE_CONTRACTS not in {step.step for step in result.state.steps}


@pytest.mark.asyncio
async def test_run_pipeline_halts_when_validation_fails(tmp_path: Path) -> None:
    store = _store(tmp_path, run_id="run-001")
    harness, services = _services(
        canonical_screen=_screen(
            missing_info=[
                _gap(
                    "missing-backend-contract",
                    kind=GapKind.MISSING_BACKEND_CONTRACT,
                    workstreams=[FactDomain.BE],
                )
            ]
        ),
        validation_report=_validation_report(ValidationStatus.FAIL),
    )

    result = await run_pipeline(
        store=store,
        services=services,
        mode_requested=WorkflowMode.AUTO,
        source_inputs=[_source_input()],
    )

    assert result.state.status is RunStatus.HALTED
    assert result.state.current_step is RunStep.VALIDATE_BUNDLE
    assert result.stop_step is RunStep.VALIDATE_BUNDLE
    assert result.bundle_files
    assert harness.validate_calls == 1
    assert result.validation_report is not None
    assert result.validation_report.status is ValidationStatus.FAIL
