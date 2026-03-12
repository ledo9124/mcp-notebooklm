"""Unit tests for provisional BA contract generation."""

from __future__ import annotations

from copy import deepcopy
import json

from notebooklm_mcp.ba.matrices import build_screen_matrix_bundle
from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    GapRecord,
    GapSeverity,
    MockScenario,
    QuestionRecord,
    ReadinessDecision,
    WorkflowMode,
)
from notebooklm_mcp.ba.contracts import (
    build_provisional_contract_artifacts,
    render_contract_yaml,
    render_mock_data_json,
    validate_mock_data_alignment,
)
from notebooklm_mcp.ba.readiness import evaluate_readiness


def _evidence(locator: str) -> EvidenceRef:
    return EvidenceRef(
        source_key="requirements",
        snapshot_id="requirements-abc123",
        locator=locator,
    )


def _fe_first_screen() -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.FE_FIRST,
        run_id="run-010",
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
                evidence=[_evidence("13-16")],
            ),
            CanonicalFact(
                fact_id="fact-tier",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "tier",
                    "label": "Tier",
                    "field_type": "select",
                    "required": False,
                },
                status=FactStatus.PROVISIONAL,
                rationale="Tier options are still provisional.",
                origin="structured_extraction",
                evidence=[_evidence("17-18")],
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
                rationale="Backend contract is still under review.",
                origin="structured_extraction",
                evidence=[_evidence("20-30")],
            )
        ],
        missing_info=[
            GapRecord(
                gap_id="gap-backend-contract",
                summary="Backend response envelope is not approved yet.",
                kind="MISSING_BACKEND_CONTRACT",
                severity=GapSeverity.HIGH,
                blocking_workstreams=[FactDomain.BE],
                owner="Tech Lead",
                evidence=[_evidence("31-34")],
            )
        ],
        open_questions=[
            QuestionRecord(
                question_id="q-contract-owner",
                summary="Who approves the final response envelope?",
                owner="Tech Lead",
                severity=GapSeverity.HIGH,
                blocking_workstreams=[FactDomain.BE],
                evidence=[_evidence("35-36")],
            )
        ],
        quality_summary=ExtractionQualitySummary(parse_quality="HIGH"),
    )


def _balanced_ready_screen() -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.BALANCED,
        run_id="run-011",
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
                evidence=[_evidence("40-45")],
            )
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
                    "request_body": "email",
                    "response_body": "customer id",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence("46-55")],
            )
        ],
        quality_summary=ExtractionQualitySummary(parse_quality="HIGH"),
    )


def test_build_provisional_contract_artifacts_emits_openapi_and_mock_data() -> None:
    screen = _fe_first_screen()
    matrices = build_screen_matrix_bundle(screen)
    readiness_summary = evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST)
    readiness = readiness_summary.screens[0]

    artifacts = build_provisional_contract_artifacts(
        screen,
        matrices=matrices,
        readiness=readiness,
    )

    assert artifacts is not None
    assert readiness_summary.decision is ReadinessDecision.READY_FOR_FE_WITH_PROVISIONAL_CONTRACT
    assert artifacts.metadata.contract_status.value == "PROVISIONAL"
    assert artifacts.metadata.provisional_endpoint_ids == ["POST /customers"]
    assert artifacts.metadata.mock_scenarios == [
        MockScenario.HAPPY_PATH,
        MockScenario.VALIDATION_ERROR,
        MockScenario.EMPTY_STATE,
        MockScenario.SERVER_ERROR,
    ]

    document = artifacts.openapi_document
    post_operation = document["paths"]["/customers"]["post"]
    request_schema = post_operation["requestBody"]["content"]["application/json"]["schema"]
    response_schema = post_operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert document["openapi"] == "3.0.3"
    assert document["x-contract-status"] == "PROVISIONAL"
    assert post_operation["x-contract-status"] == "PROVISIONAL"
    assert post_operation["x-open-questions"][0]["question_id"] == "q-contract-owner"
    assert request_schema["properties"]["email"]["x-field-status"] == "CONFIRMED"
    assert request_schema["properties"]["tier"]["x-field-status"] == "PROVISIONAL"
    assert response_schema["properties"]["customer_id"]["x-field-status"] == "PROVISIONAL"

    mock_operation = artifacts.mock_data["operations"]["POST /customers"]
    assert set(mock_operation["scenarios"]) == {
        "empty_state",
        "happy_path",
        "server_error",
        "validation_error",
    }
    assert mock_operation["scenarios"]["happy_path"]["request"]["email"] == "customer@example.test"
    assert mock_operation["scenarios"]["server_error"]["response"]["status_code"] == 500
    assert validate_mock_data_alignment(
        openapi_document=artifacts.openapi_document,
        mock_data=artifacts.mock_data,
    ) == []


def test_renderers_emit_deterministic_yaml_and_json() -> None:
    screen = _fe_first_screen()
    matrices = build_screen_matrix_bundle(screen)
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST).screens[0]
    artifacts = build_provisional_contract_artifacts(
        screen,
        matrices=matrices,
        readiness=readiness,
    )
    assert artifacts is not None

    yaml_text = render_contract_yaml(artifacts.openapi_document)
    json_payload = json.loads(render_mock_data_json(artifacts.mock_data))

    assert yaml_text.startswith("openapi: 3.0.3\n")
    assert "x-contract-status: PROVISIONAL" in yaml_text
    assert "customer_id:" in yaml_text
    assert json_payload["contract_status"] == "PROVISIONAL"
    assert json_payload["operations"]["POST /customers"]["scenarios"]["validation_error"]["response"][
        "status_code"
    ] == 400


def test_build_provisional_contract_artifacts_returns_none_when_not_needed() -> None:
    screen = _balanced_ready_screen()
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.BALANCED).screens[0]

    artifacts = build_provisional_contract_artifacts(
        screen,
        matrices=build_screen_matrix_bundle(screen),
        readiness=readiness,
    )

    assert readiness.be_ready is True
    assert readiness.fe_ready is True
    assert readiness.resolved_mode is WorkflowMode.BALANCED
    assert artifacts is None


def test_validate_mock_data_alignment_detects_contract_drift() -> None:
    screen = _fe_first_screen()
    readiness = evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST).screens[0]
    artifacts = build_provisional_contract_artifacts(
        screen,
        matrices=build_screen_matrix_bundle(screen),
        readiness=readiness,
    )
    assert artifacts is not None

    drifted = deepcopy(artifacts.mock_data)
    drifted["operations"]["POST /customers"]["scenarios"]["happy_path"]["request"].pop("email")
    drifted["operations"]["POST /customers"]["scenarios"]["server_error"]["response"]["status_code"] = 502

    errors = validate_mock_data_alignment(
        openapi_document=artifacts.openapi_document,
        mock_data=drifted,
    )

    assert any("missing required key `email`" in error for error in errors)
    assert any("response status `502` should be `500`" in error for error in errors)
