"""Unit tests for BA bundle assembly and feature-level rendering."""

from __future__ import annotations

import json
import os
from pathlib import Path

from notebooklm_mcp.ba.fixtures import FixtureScenario, fixture_paths
from notebooklm_mcp.ba.contracts import build_provisional_contract_artifacts, render_contract_yaml, render_mock_data_json
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
    ParseQuality,
    QuestionRecord,
    ReadinessDecision,
    RunAuditDocument,
    RunAuditEntry,
    RunStateSnapshot,
    RunStatus,
    RunStep,
    RunStepRecord,
    RunStepStatus,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    SourceContentKind,
    SourceLifecycleStatus,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceType,
    TerminologyDocument,
    TerminologyEntry,
    WorkflowMode,
)
from notebooklm_mcp.ba.readiness import evaluate_readiness
from notebooklm_mcp.ba.rendering import (
    ScreenBundleArtifact,
    build_bundle_file_map,
    render_be_spec_markdown,
    render_field_matrix_csv,
    render_fe_spec_markdown,
    render_overview_markdown,
    render_question_backlog_markdown,
    render_action_rule_matrix_csv,
    render_api_matrix_csv,
    render_readiness_summary_markdown,
    write_bundle_layout,
)
from notebooklm_mcp.ba.run_store import BARunStore

_UPDATE_BA_GOLDENS = "UPDATE_BA_GOLDENS"


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


def _scenario_signals(scenario: FixtureScenario) -> dict[str, object]:
    return json.loads((_golden_path(scenario, "scenario-signals.json")).read_text(encoding="utf-8"))


def _fixture_evidence(source_key: str, snapshot_id: str, locator: str) -> EvidenceRef:
    return EvidenceRef(source_key=source_key, snapshot_id=snapshot_id, locator=locator)


def _manifest() -> SourceManifestDocument:
    return SourceManifestDocument(
        feature_key="customer-create",
        run_id="run-012",
        warnings=["supporting glossary still pending"],
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref="requirements/ba.pdf",
                title="BA PDF",
            )
        ],
    )


def _catalog() -> ScreenCatalogDocument:
    return ScreenCatalogDocument(
        feature_key="customer-create",
        run_id="run-012",
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
            )
        ],
    )


def _terminology() -> TerminologyDocument:
    return TerminologyDocument(
        feature_key="customer-create",
        run_id="run-012",
        entries=[
            TerminologyEntry(
                standard_term="Customer Tier",
                aliases=["Plan", "Segment"],
                semantic_notes=["Controls feature access"],
                evidence=[_evidence("5-7")],
            )
        ],
    )


def _screen(*, fe_first: bool) -> CanonicalScreen:
    mode = WorkflowMode.FE_FIRST if fe_first else WorkflowMode.BALANCED
    be_status = FactStatus.PROVISIONAL if fe_first else FactStatus.CONFIRMED
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=mode,
        run_id="run-012",
        fe_facts=[
            CanonicalFact(
                fact_id="fact-name",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "name",
                    "label": "Customer Name",
                    "field_type": "text",
                    "required": True,
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence("10-12")],
            ),
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
                evidence=[_evidence("13-15")],
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
                    "request_body": "name, email",
                    "response_body": "customer id",
                },
                status=be_status,
                rationale="backend contract is still provisional" if fe_first else None,
                origin="structured_extraction" if fe_first else None,
                evidence=[_evidence("20-30")],
            )
        ],
        missing_info=[
            GapRecord(
                gap_id="gap-contract",
                kind="MISSING_BACKEND_CONTRACT",
                summary="Backend response shape is pending approval.",
                severity=GapSeverity.HIGH,
                owner="Tech Lead",
                blocking_workstreams=[FactDomain.BE],
                evidence=[_evidence("31-33")],
            )
        ]
        if fe_first
        else [],
        open_questions=[
            QuestionRecord(
                question_id="q-approval",
                summary="Who signs off the response envelope?",
                owner="Tech Lead",
                severity=GapSeverity.HIGH,
                blocking_workstreams=[FactDomain.BE],
                evidence=[_evidence("34-35")],
            )
        ]
        if fe_first
        else [],
        quality_summary=ExtractionQualitySummary(parse_quality="HIGH"),
    )


def _screen_artifact(*, fe_first: bool) -> tuple[ScreenBundleArtifact, ReadinessDecision, str]:
    screen = _screen(fe_first=fe_first)
    catalog_entry = _catalog().screens[0]
    matrices = build_screen_matrix_bundle(screen)
    review = build_gap_review_document(screen)
    readiness_summary = evaluate_readiness([screen], feature_mode=screen.mode)
    readiness = readiness_summary.screens[0]

    contract_artifacts = build_provisional_contract_artifacts(
        screen,
        matrices=matrices,
        readiness=readiness,
    )
    return (
        ScreenBundleArtifact(
            screen_id=screen.screen_id,
            canonical_json=screen.model_dump_json(indent=2),
            fe_markdown=render_fe_spec_markdown(
                catalog_entry,
                screen,
                matrices=matrices,
                review=review,
                readiness=readiness,
            ),
            be_markdown=render_be_spec_markdown(
                catalog_entry,
                screen,
                matrices=matrices,
                review=review,
                readiness=readiness,
            ),
            questions_markdown=render_question_backlog_markdown(review),
            field_matrix_csv="\n".join(["field_name", *[row.field_name for row in matrices.field_rows]]) + "\n",
            action_rule_matrix_csv="row_id\n",
            api_matrix_csv="\n".join(["interface_name", *[row.interface_name for row in matrices.api_rows]]) + "\n",
            contract_yaml=(
                render_contract_yaml(contract_artifacts.openapi_document)
                if contract_artifacts is not None
                else None
            ),
            mock_data_json=(
                render_mock_data_json(contract_artifacts.mock_data)
                if contract_artifacts is not None
                else None
            ),
        ),
        readiness_summary.decision,
        render_readiness_summary_markdown(readiness_summary),
    )


def _run_audit() -> RunAuditDocument:
    return RunAuditDocument(
        feature_key="customer-create",
        entries=[
            RunAuditEntry(
                recorded_at="2026-03-12T10:00:00+00:00",
                snapshot=RunStateSnapshot(
                    run_id="run-012",
                    feature_key="customer-create",
                    status=RunStatus.RUNNING,
                    current_step=RunStep.REGISTER_SOURCES,
                    steps=[
                        RunStepRecord(
                            step=RunStep.REGISTER_SOURCES,
                            status=RunStepStatus.RUNNING,
                            metadata={"source_count": 1},
                        )
                    ],
                ),
            ),
            RunAuditEntry(
                recorded_at="2026-03-12T10:05:00+00:00",
                snapshot=RunStateSnapshot(
                    run_id="run-012",
                    feature_key="customer-create",
                    status=RunStatus.HALTED,
                    current_step=RunStep.GENERATE_CONTRACTS,
                    halt_reason="Awaiting backend contract sign-off",
                    warnings=["contract source still provisional"],
                ),
            ),
        ],
    )


def _artifact_for_screen(
    catalog_entry: ScreenCatalogEntry,
    screen: CanonicalScreen,
    readiness,
) -> ScreenBundleArtifact:
    matrices = build_screen_matrix_bundle(screen)
    review = build_gap_review_document(screen)
    contract_artifacts = build_provisional_contract_artifacts(
        screen,
        matrices=matrices,
        readiness=readiness,
    )
    return ScreenBundleArtifact(
        screen_id=screen.screen_id,
        canonical_json=screen.model_dump_json(indent=2),
        fe_markdown=render_fe_spec_markdown(
            catalog_entry,
            screen,
            matrices=matrices,
            review=review,
            readiness=readiness,
        ),
        be_markdown=render_be_spec_markdown(
            catalog_entry,
            screen,
            matrices=matrices,
            review=review,
            readiness=readiness,
        ),
        questions_markdown=render_question_backlog_markdown(review),
        field_matrix_csv=render_field_matrix_csv(matrices.field_rows),
        action_rule_matrix_csv=render_action_rule_matrix_csv(matrices.action_rule_rows),
        api_matrix_csv=render_api_matrix_csv(matrices.api_rows),
        contract_yaml=(
            render_contract_yaml(contract_artifacts.openapi_document)
            if contract_artifacts is not None
            else None
        ),
        mock_data_json=(
            render_mock_data_json(contract_artifacts.mock_data)
            if contract_artifacts is not None
            else None
        ),
    )


def _clean_feature_manifest() -> SourceManifestDocument:
    scenario = FixtureScenario.CLEAN_FEATURE
    return SourceManifestDocument(
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
                notebook_source_id="nb-requirements",
                snapshot_id="requirements-clean-001",
                parse_quality=ParseQuality.HIGH,
                freshness="fresh",
                status=SourceLifecycleStatus.READY,
                used_in_screens=["customer-form", "customer-list"],
            ),
            SourceManifestRow(
                source_key="api-contract",
                source_type=SourceType.PRIMARY_CONTRACT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref=_fixture_ref(scenario, "sources", "api-contract.md"),
                title="Customer Create API Contract",
                notebook_source_id="nb-api-contract",
                snapshot_id="api-contract-clean-001",
                parse_quality=ParseQuality.HIGH,
                freshness="fresh",
                status=SourceLifecycleStatus.READY,
                used_in_screens=["customer-form", "customer-list"],
            ),
            SourceManifestRow(
                source_key="glossary",
                source_type=SourceType.SUPPORTING_GLOSSARY,
                priority=SourcePriority.NORMAL,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref=_fixture_ref(scenario, "sources", "glossary.md"),
                title="Customer Create Glossary",
                notebook_source_id="nb-glossary",
                snapshot_id="glossary-clean-001",
                parse_quality=ParseQuality.HIGH,
                freshness="fresh",
                status=SourceLifecycleStatus.READY,
                used_in_screens=["customer-form", "customer-list"],
            ),
        ],
    )


def _clean_feature_catalog() -> ScreenCatalogDocument:
    return ScreenCatalogDocument(
        feature_key="customer-create",
        run_id="run-clean-golden",
        screens=[
            ScreenCatalogEntry(
                screen_id="customer-form",
                screen_name="Customer Form",
                purpose="Create a customer record and capture approval-state inputs.",
                roles=["Sales"],
                entry_points=["Customer List"],
                exit_points=["Customer List"],
                main_actions=["Save customer"],
                dependencies=["Create Customer"],
                related_sources=["requirements", "api-contract", "glossary"],
            ),
            ScreenCatalogEntry(
                screen_id="customer-list",
                screen_name="Customer List",
                purpose="Review newly created customers and their approval state.",
                roles=["Sales", "Operations"],
                entry_points=["Navigation menu"],
                exit_points=["Customer Form"],
                main_actions=["Open customer"],
                dependencies=["List Customers"],
                related_sources=["requirements", "glossary"],
            ),
        ],
    )


def _clean_feature_terminology() -> TerminologyDocument:
    return TerminologyDocument(
        feature_key="customer-create",
        run_id="run-clean-golden",
        entries=[
            TerminologyEntry(
                standard_term="Loyalty Tier",
                semantic_notes=["Commercial segment attached to the customer profile."],
                evidence=[_fixture_evidence("glossary", "glossary-clean-001", "3-3")],
            ),
            TerminologyEntry(
                standard_term="Approval Flag",
                semantic_notes=["Signals whether VIP create flow still needs manager review."],
                evidence=[_fixture_evidence("glossary", "glossary-clean-001", "4-4")],
            ),
        ],
    )


def _clean_feature_screens() -> list[CanonicalScreen]:
    return [
        CanonicalScreen(
            feature_key="customer-create",
            screen_id="customer-form",
            mode=WorkflowMode.BALANCED,
            run_id="run-clean-golden",
            shared_facts=[
                CanonicalFact(
                    fact_id="form-save-rule",
                    domain=FactDomain.SHARED,
                    category="business_rule",
                    value={
                        "action_name": "Save customer",
                        "trigger": "User clicks Save",
                        "rule": "Duplicate email addresses block creation immediately.",
                        "outcome": "Show inline duplicate-email validation and keep Save disabled.",
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "10-14")],
                ),
                CanonicalFact(
                    fact_id="vip-approval-flag",
                    domain=FactDomain.SHARED,
                    category="business_rule",
                    value={
                        "action_name": "Save customer",
                        "trigger": "Requested loyalty tier is VIP",
                        "rule": "VIP customers require an approval flag before save completes.",
                        "outcome": "Return approvalFlag=pending until manager review completes.",
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "8-9")],
                ),
            ],
            fe_facts=[
                CanonicalFact(
                    fact_id="field-legal-name",
                    domain=FactDomain.FE,
                    category="field",
                    value={
                        "field_name": "legal_name",
                        "label": "Legal Name",
                        "field_type": "text",
                        "required": True,
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "7-7")],
                ),
                CanonicalFact(
                    fact_id="field-email",
                    domain=FactDomain.FE,
                    category="field",
                    value={
                        "field_name": "email",
                        "label": "Email",
                        "field_type": "email",
                        "required": True,
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "7-7")],
                ),
                CanonicalFact(
                    fact_id="field-loyalty-tier",
                    domain=FactDomain.FE,
                    category="field",
                    value={
                        "field_name": "loyalty_tier",
                        "label": "Loyalty Tier",
                        "field_type": "select",
                        "required": True,
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "7-8")],
                ),
                CanonicalFact(
                    fact_id="field-sales-owner",
                    domain=FactDomain.FE,
                    category="field",
                    value={
                        "field_name": "sales_owner_id",
                        "label": "Sales Owner",
                        "field_type": "text",
                        "required": True,
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "7-7")],
                ),
            ],
            be_facts=[
                CanonicalFact(
                    fact_id="endpoint-create-customer",
                    domain=FactDomain.BE,
                    category="endpoint",
                    value={
                        "endpoint_name": "Create Customer",
                        "method": "POST",
                        "path": "/customers",
                        "request_body": "legalName, email, loyaltyTier, salesOwnerId",
                        "response_body": "customerId, status, approvalFlag",
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("api-contract", "api-contract-clean-001", "3-18")],
                ),
            ],
            dependencies=["Create Customer"],
            quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
        ),
        CanonicalScreen(
            feature_key="customer-create",
            screen_id="customer-list",
            mode=WorkflowMode.BALANCED,
            run_id="run-clean-golden",
            shared_facts=[
                CanonicalFact(
                    fact_id="list-refresh-rule",
                    domain=FactDomain.SHARED,
                    category="business_rule",
                    value={
                        "action_name": "Open customer",
                        "trigger": "Create Customer completes successfully",
                        "rule": "Return to Customer List with an updated status chip.",
                        "outcome": "Customer List shows the latest approval state immediately.",
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "11-14")],
                )
            ],
            fe_facts=[
                CanonicalFact(
                    fact_id="list-customer-name",
                    domain=FactDomain.FE,
                    category="field",
                    value={
                        "field_name": "customer_name",
                        "label": "Customer Name",
                        "field_type": "text",
                        "required": False,
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "3-5")],
                ),
                CanonicalFact(
                    fact_id="list-loyalty-tier",
                    domain=FactDomain.FE,
                    category="field",
                    value={
                        "field_name": "loyalty_tier",
                        "label": "Loyalty Tier",
                        "field_type": "text",
                        "required": False,
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "3-5")],
                ),
                CanonicalFact(
                    fact_id="list-status",
                    domain=FactDomain.FE,
                    category="field",
                    value={
                        "field_name": "status",
                        "label": "Status",
                        "field_type": "chip",
                        "required": False,
                    },
                    status=FactStatus.CONFIRMED,
                    evidence=[_fixture_evidence("requirements", "requirements-clean-001", "3-5")],
                ),
            ],
            quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
        ),
    ]


def _missing_contract_manifest() -> SourceManifestDocument:
    scenario = FixtureScenario.MISSING_CONTRACT
    return SourceManifestDocument(
        feature_key="customer-create",
        run_id="run-missing-contract-golden",
        warnings=["backend contract detail is still missing from the authoritative BA inputs"],
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref=_fixture_ref(scenario, "sources", "requirements.md"),
                title="Customer Create Requirements",
                notebook_source_id="nb-requirements",
                snapshot_id="requirements-missing-001",
                parse_quality=ParseQuality.HIGH,
                freshness="fresh",
                status=SourceLifecycleStatus.READY,
                used_in_screens=["customer-form"],
            ),
            SourceManifestRow(
                source_key="glossary",
                source_type=SourceType.SUPPORTING_GLOSSARY,
                priority=SourcePriority.NORMAL,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref=_fixture_ref(scenario, "sources", "glossary.md"),
                title="Customer Create Glossary",
                notebook_source_id="nb-glossary",
                snapshot_id="glossary-missing-001",
                parse_quality=ParseQuality.HIGH,
                freshness="fresh",
                status=SourceLifecycleStatus.READY,
                used_in_screens=["customer-form"],
            ),
        ],
    )


def _missing_contract_catalog() -> ScreenCatalogDocument:
    return ScreenCatalogDocument(
        feature_key="customer-create",
        run_id="run-missing-contract-golden",
        screens=[
            ScreenCatalogEntry(
                screen_id="customer-form",
                screen_name="Customer Form",
                purpose="Capture customer details while backend contract details remain provisional.",
                roles=["Sales"],
                entry_points=["Customer List"],
                exit_points=["Customer List"],
                main_actions=["Save customer"],
                dependencies=["Create Customer"],
                related_sources=["requirements", "glossary"],
            )
        ],
    )


def _missing_contract_terminology() -> TerminologyDocument:
    return TerminologyDocument(
        feature_key="customer-create",
        run_id="run-missing-contract-golden",
        entries=[
            TerminologyEntry(
                standard_term="Approval Banner",
                semantic_notes=["Inline copy explaining why VIP save remains provisional."],
                evidence=[_fixture_evidence("glossary", "glossary-missing-001", "3-3")],
            )
        ],
    )


def _missing_contract_screen() -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.BALANCED,
        run_id="run-missing-contract-golden",
        shared_facts=[
            CanonicalFact(
                fact_id="approval-banner-rule",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={
                    "action_name": "Save customer",
                    "trigger": "Requested loyalty tier is VIP",
                    "rule": "Show a manager-approval banner before submission.",
                    "outcome": "FE preserves captured values while approval state stays provisional.",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_fixture_evidence("requirements", "requirements-missing-001", "4-6")],
            )
        ],
        fe_facts=[
            CanonicalFact(
                fact_id="field-legal-name",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "legal_name",
                    "label": "Legal Name",
                    "field_type": "text",
                    "required": True,
                },
                status=FactStatus.CONFIRMED,
                evidence=[_fixture_evidence("requirements", "requirements-missing-001", "4-4")],
            ),
            CanonicalFact(
                fact_id="field-email",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "email",
                    "label": "Email",
                    "field_type": "email",
                    "required": True,
                },
                status=FactStatus.CONFIRMED,
                evidence=[_fixture_evidence("requirements", "requirements-missing-001", "4-4")],
            ),
            CanonicalFact(
                fact_id="field-loyalty-tier",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "loyalty_tier",
                    "label": "Loyalty Tier",
                    "field_type": "select",
                    "required": True,
                },
                status=FactStatus.CONFIRMED,
                evidence=[_fixture_evidence("requirements", "requirements-missing-001", "4-5")],
            ),
            CanonicalFact(
                fact_id="field-sales-owner",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "sales_owner_id",
                    "label": "Sales Owner",
                    "field_type": "text",
                    "required": True,
                },
                status=FactStatus.CONFIRMED,
                evidence=[_fixture_evidence("requirements", "requirements-missing-001", "4-4")],
            ),
            CanonicalFact(
                fact_id="loading-state",
                domain=FactDomain.FE,
                category="loading_state",
                value="Persist the captured form values while the provisional create request is in flight.",
                status=FactStatus.PROVISIONAL,
                rationale="Backend payload details are still undefined in the BA source.",
                origin="structured_extraction",
            ),
        ],
        be_facts=[
            CanonicalFact(
                fact_id="endpoint-create-customer",
                domain=FactDomain.BE,
                category="endpoint",
                value={
                    "endpoint_name": "Create Customer",
                    "method": "POST",
                    "path": "/customers",
                    "request_body": "legalName, email, loyaltyTier, salesOwnerId",
                    "response_body": "customerId, approvalState",
                },
                status=FactStatus.PROVISIONAL,
                rationale="The backend payload is not yet specified in the BA source.",
                origin="structured_extraction",
                evidence=[_fixture_evidence("requirements", "requirements-missing-001", "4-6")],
            )
        ],
        dependencies=["Create Customer"],
        missing_info=[
            GapRecord(
                gap_id="missing-backend-contract",
                kind=GapKind.MISSING_BACKEND_CONTRACT,
                summary="Authoritative Create Customer response schema is still missing.",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                owner="Tech Lead",
                blocking_workstreams=[FactDomain.BE],
                evidence=[_fixture_evidence("requirements", "requirements-missing-001", "4-6")],
            ),
            GapRecord(
                gap_id="assume-customer-create-response",
                kind=GapKind.REQUIRED_ASSUMPTION,
                summary="Assume the provisional response echoes saved customer values and approval state.",
                severity=GapSeverity.MEDIUM,
                screen_id="customer-form",
                owner="Tech Lead",
                blocking_workstreams=[FactDomain.FE],
                evidence=[_fixture_evidence("requirements", "requirements-missing-001", "4-6")],
            ),
        ],
        open_questions=[
            QuestionRecord(
                question_id="customer-create-response-shape",
                summary="What response envelope should Create Customer return while approval is pending?",
                owner="Tech Lead",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                blocking_workstreams=[FactDomain.BE],
                evidence=[_fixture_evidence("requirements", "requirements-missing-001", "4-6")],
            )
        ],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
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
                summary="Email validation timing conflicts across the BA source set.",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                owner="BA",
                blocking_workstreams=[FactDomain.SHARED],
                evidence=[_fixture_evidence("requirements", "requirements-contradictory-001", "3-4")],
            ),
            GapRecord(
                gap_id="contradictory-vip-approval-threshold",
                kind=GapKind.CONTRADICTORY_REQUIREMENT_DETAIL,
                summary="VIP approval threshold is inconsistent across the BA source set.",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                owner="BA",
                blocking_workstreams=[FactDomain.SHARED],
                evidence=[_fixture_evidence("business-rules", "business-rules-contradictory-001", "6-6")],
            ),
        ],
        contradictions=[
            ContradictionRecord(
                contradiction_id="email-validation-timing",
                summary="Requirements disagree on whether duplicate-email validation happens on blur or on save.",
                severity=GapSeverity.HIGH,
                claims=[
                    ContradictionClaim(
                        claim="Validate email only when the user presses Save.",
                        evidence=[_fixture_evidence("requirements", "requirements-contradictory-001", "3-4")],
                    ),
                    ContradictionClaim(
                        claim="Validate email on blur before Save.",
                        evidence=[_fixture_evidence("business-rules", "business-rules-contradictory-001", "3-4")],
                    ),
                ],
                open_question="Should duplicate-email validation run on blur or only on submit?",
            ),
            ContradictionRecord(
                contradiction_id="vip-approval-threshold",
                summary="Requirements disagree on the yearly-spend threshold for VIP approval.",
                severity=GapSeverity.HIGH,
                claims=[
                    ContradictionClaim(
                        claim="Approval is required only above a 10000 yearly-spend threshold.",
                        evidence=[_fixture_evidence("requirements", "requirements-contradictory-001", "6-6")],
                    ),
                    ContradictionClaim(
                        claim="Approval is required above a 5000 yearly-spend threshold.",
                        evidence=[_fixture_evidence("business-rules", "business-rules-contradictory-001", "6-6")],
                    ),
                ],
                open_question="Which yearly-spend threshold is authoritative for VIP approval?",
            ),
        ],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def _garbled_pdf_screen() -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.AUTO,
        run_id="run-garbled-golden",
        missing_info=[
            GapRecord(
                gap_id="missing-required-field-rules",
                kind=GapKind.MISSING_REQUIREMENT_DETAIL,
                summary="Required field rules could not be recovered confidently from the OCR export.",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                owner="BA",
                blocking_workstreams=[FactDomain.SHARED],
                evidence=[_fixture_evidence("ocr-export", "ocr-export-garbled-001", "3-6")],
            ),
            GapRecord(
                gap_id="missing-approval-behavior",
                kind=GapKind.MISSING_REQUIREMENT_DETAIL,
                summary="VIP approval behavior is unreadable in the OCR export.",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                owner="BA",
                blocking_workstreams=[FactDomain.SHARED],
                evidence=[_fixture_evidence("ocr-export", "ocr-export-garbled-001", "7-10")],
            ),
        ],
        open_questions=[
            QuestionRecord(
                question_id="customer-form-ocr-recovery",
                summary="Can the BA team provide a cleaner source or curated note to replace the unreadable OCR sections?",
                owner="BA",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                blocking_workstreams=[FactDomain.SHARED],
                evidence=[_fixture_evidence("ocr-export", "ocr-export-garbled-001", "11-13")],
            )
        ],
        quality_summary=ExtractionQualitySummary(
            parse_quality=ParseQuality.LOW,
            notes=["OCR quality too low around the approval section."],
            degraded=True,
        ),
    )


def test_feature_level_renderers_cover_overview_and_readiness_requirements() -> None:
    manifest = _manifest()
    catalog = _catalog()
    terminology = _terminology()
    screen = _screen(fe_first=True)
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST)

    overview = render_overview_markdown(
        source_manifest=manifest,
        screen_catalog=catalog,
        readiness=readiness,
        terminology=terminology,
        run_audit=_run_audit(),
    )
    readiness_markdown = render_readiness_summary_markdown(readiness)

    assert overview.startswith("# Feature Overview\n")
    assert "## Source Health Summary" in overview
    assert "## Screen Inventory" in overview
    assert "Latest checkpoint:" in overview
    assert "Awaiting backend contract sign-off" in overview
    assert "## Terminology Highlights" in overview
    assert "## Final Decision" in overview

    assert readiness_markdown.startswith("# Readiness Summary\n")
    assert "## Screen Readiness" in readiness_markdown
    assert "## Blockers by Owner" in readiness_markdown
    assert "## Assumptions Required for FE-first Execution" in readiness_markdown
    assert "## Rerun Recommendation" in readiness_markdown


def test_write_bundle_layout_writes_expected_mode_aware_files(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-012",
    )
    store.create(mode_requested=WorkflowMode.FE_FIRST)
    artifact, decision, _ = _screen_artifact(fe_first=True)

    assert decision is ReadinessDecision.READY_FOR_FE_WITH_PROVISIONAL_CONTRACT

    written = write_bundle_layout(
        store,
        source_manifest=_manifest(),
        screen_catalog=_catalog(),
        readiness=evaluate_readiness([_screen(fe_first=True)], feature_mode=WorkflowMode.FE_FIRST),
        screen_artifacts=[artifact],
        terminology=_terminology(),
        run_audit=_run_audit(),
    )

    assert "00-overview.md" in written
    assert "03-readiness-summary.md" in written
    assert "04-terminology.md" in written
    assert "05-run-audit.json" in written
    assert "screens/customer-form/contract.provisional.yaml" in written
    assert "screens/customer-form/mock-data.json" in written
    assert store.feature_paths.overview_markdown.exists()
    assert store.feature_paths.run_audit_json.exists()
    assert store.screen_paths("customer-form").contract_yaml.exists()
    assert "Latest checkpoint:" in store.feature_paths.overview_markdown.read_text(encoding="utf-8")
    assert json.loads(store.feature_paths.run_audit_json.read_text(encoding="utf-8"))["feature_key"] == (
        "customer-create"
    )
    assert json.loads(store.screen_paths("customer-form").mock_data_json.read_text(encoding="utf-8"))[
        "contract_status"
    ] == "PROVISIONAL"


def test_build_bundle_file_map_omits_optional_artifacts_when_not_present() -> None:
    readiness = evaluate_readiness([_screen(fe_first=False)], feature_mode=WorkflowMode.BALANCED)
    artifact, decision, readiness_markdown = _screen_artifact(fe_first=False)

    assert decision is ReadinessDecision.READY_FOR_FE_AND_BE

    bundle_map = build_bundle_file_map(
        source_manifest=_manifest(),
        screen_catalog=_catalog(),
        readiness=readiness,
        screen_artifacts=[artifact.model_copy(update={"contract_yaml": None, "mock_data_json": None})],
        run_audit=_run_audit(),
    )

    assert "00-overview.md" in bundle_map
    assert "03-readiness-summary.md" in bundle_map
    assert "05-run-audit.json" in bundle_map
    assert "screens/customer-form/be.md" in bundle_map
    assert "screens/customer-form/questions.md" in bundle_map
    assert "screens/customer-form/contract.provisional.yaml" not in bundle_map
    assert "screens/customer-form/mock-data.json" not in bundle_map
    assert readiness_markdown.startswith("# Readiness Summary\n")


def test_clean_feature_bundle_outputs_match_fixture_goldens() -> None:
    scenario = FixtureScenario.CLEAN_FEATURE
    signals = _scenario_signals(scenario)
    manifest = _clean_feature_manifest()
    catalog = _clean_feature_catalog()
    terminology = _clean_feature_terminology()
    screens = _clean_feature_screens()
    readiness = evaluate_readiness(screens, feature_mode=WorkflowMode.BALANCED)

    assert readiness.decision.value == signals["expected_readiness_decision"]
    assert {screen.screen_id: screen.resolved_mode.value for screen in readiness.screens} == signals[
        "expected_resolved_modes"
    ]

    readiness_by_screen = {screen.screen_id: screen for screen in readiness.screens}
    screen_artifacts = [
        _artifact_for_screen(
            next(entry for entry in catalog.screens if entry.screen_id == screen.screen_id),
            screen,
            readiness_by_screen[screen.screen_id],
        )
        for screen in screens
    ]
    bundle_map = build_bundle_file_map(
        source_manifest=manifest,
        screen_catalog=catalog,
        readiness=readiness,
        screen_artifacts=screen_artifacts,
        terminology=terminology,
    )

    _assert_golden_text(scenario, "overview.md", bundle_map["00-overview.md"])
    _assert_golden_text(scenario, "readiness-summary.md", bundle_map["03-readiness-summary.md"])
    _assert_golden_text(
        scenario,
        "canonical.customer-form.json",
        bundle_map["screens/customer-form/canonical.json"],
    )
    _assert_golden_text(
        scenario,
        "canonical.customer-list.json",
        bundle_map["screens/customer-list/canonical.json"],
    )
    _assert_golden_text(scenario, "fe.customer-form.md", bundle_map["screens/customer-form/fe.md"])
    _assert_golden_text(scenario, "be.customer-form.md", bundle_map["screens/customer-form/be.md"])
    _assert_golden_text(
        scenario,
        "field-matrix.customer-form.csv",
        bundle_map["screens/customer-form/field-matrix.csv"],
    )
    _assert_golden_text(
        scenario,
        "action-rule-matrix.customer-form.csv",
        bundle_map["screens/customer-form/action-rule-matrix.csv"],
    )
    _assert_golden_text(
        scenario,
        "api-matrix.customer-form.csv",
        bundle_map["screens/customer-form/api-matrix.csv"],
    )


def test_missing_contract_bundle_outputs_match_fixture_goldens() -> None:
    scenario = FixtureScenario.MISSING_CONTRACT
    signals = _scenario_signals(scenario)
    manifest = _missing_contract_manifest()
    catalog = _missing_contract_catalog()
    terminology = _missing_contract_terminology()
    screen = _missing_contract_screen()
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.BALANCED)

    assert readiness.decision.value == signals["expected_readiness_decision"]
    assert {item.screen_id: item.resolved_mode.value for item in readiness.screens} == signals[
        "expected_resolved_modes"
    ]

    artifact = _artifact_for_screen(catalog.screens[0], screen, readiness.screens[0])
    assert artifact.contract_yaml is not None
    assert artifact.mock_data_json is not None

    bundle_map = build_bundle_file_map(
        source_manifest=manifest,
        screen_catalog=catalog,
        readiness=readiness,
        screen_artifacts=[artifact],
        terminology=terminology,
    )

    _assert_golden_text(scenario, "overview.md", bundle_map["00-overview.md"])
    _assert_golden_text(scenario, "readiness-summary.md", bundle_map["03-readiness-summary.md"])
    _assert_golden_text(
        scenario,
        "canonical.customer-form.json",
        bundle_map["screens/customer-form/canonical.json"],
    )
    _assert_golden_text(scenario, "fe.customer-form.md", bundle_map["screens/customer-form/fe.md"])
    _assert_golden_text(scenario, "be.customer-form.md", bundle_map["screens/customer-form/be.md"])
    _assert_golden_text(
        scenario,
        "questions.customer-form.md",
        bundle_map["screens/customer-form/questions.md"],
    )
    _assert_golden_text(
        scenario,
        "field-matrix.customer-form.csv",
        bundle_map["screens/customer-form/field-matrix.csv"],
    )
    _assert_golden_text(
        scenario,
        "action-rule-matrix.customer-form.csv",
        bundle_map["screens/customer-form/action-rule-matrix.csv"],
    )
    _assert_golden_text(
        scenario,
        "api-matrix.customer-form.csv",
        bundle_map["screens/customer-form/api-matrix.csv"],
    )
    _assert_golden_text(
        scenario,
        "contract.customer-form.yaml",
        bundle_map["screens/customer-form/contract.provisional.yaml"],
    )
    _assert_golden_text(
        scenario,
        "mock-data.customer-form.json",
        bundle_map["screens/customer-form/mock-data.json"],
    )


def test_blocked_and_degraded_readiness_summaries_match_fixture_goldens() -> None:
    for scenario, screen in (
        (FixtureScenario.CONTRADICTORY_SOURCES, _contradictory_sources_screen()),
        (FixtureScenario.GARBLED_PDF, _garbled_pdf_screen()),
    ):
        signals = _scenario_signals(scenario)
        readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.AUTO)

        assert readiness.decision.value == signals["expected_readiness_decision"]
        assert {item.screen_id: item.resolved_mode.value for item in readiness.screens} == signals[
            "expected_resolved_modes"
        ]
        if signals.get("should_degrade"):
            assert any("degraded extraction quality" in warning for warning in readiness.warnings)

        _assert_golden_text(
            scenario,
            "readiness-summary.md",
            render_readiness_summary_markdown(readiness),
        )
