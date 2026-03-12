"""Unit tests for BA provisional mock-data alignment and persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from notebooklm_mcp.ba.contracts import (
    build_provisional_contract_artifacts,
    render_contract_yaml,
    render_mock_data_json,
)
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
    QuestionRecord,
    WorkflowMode,
)
from notebooklm_mcp.ba.readiness import evaluate_readiness
from notebooklm_mcp.ba.run_store import BARunStore


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


def test_mock_data_scenarios_conform_to_generated_contract_shapes() -> None:
    screen = _fe_first_screen()
    artifacts = build_provisional_contract_artifacts(
        screen,
        matrices=build_screen_matrix_bundle(screen),
        readiness=evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST).screens[0],
    )

    assert artifacts is not None

    validation_schema = artifacts.openapi_document["components"]["schemas"]["ValidationError"]
    server_schema = artifacts.openapi_document["components"]["schemas"]["ServerError"]

    assert sorted(artifacts.mock_data["operations"]) == artifacts.metadata.provisional_endpoint_ids

    for endpoint_id, mock_operation in artifacts.mock_data["operations"].items():
        contract_operation = artifacts.openapi_document["paths"][mock_operation["path"]][
            mock_operation["method"].casefold()
        ]
        request_schema = contract_operation["requestBody"]["content"]["application/json"]["schema"]
        response_schema = contract_operation["responses"]["200"]["content"]["application/json"]["schema"]

        happy_path = mock_operation["scenarios"]["happy_path"]
        validation_error = mock_operation["scenarios"]["validation_error"]
        empty_state = mock_operation["scenarios"]["empty_state"]
        server_error = mock_operation["scenarios"]["server_error"]

        _assert_matches_schema(happy_path["request"], request_schema)
        _assert_matches_schema(happy_path["response"]["body"], response_schema)
        _assert_matches_schema(empty_state["request"], request_schema)
        _assert_matches_schema(empty_state["response"]["body"], response_schema)
        _assert_matches_schema(validation_error["response"]["body"], validation_schema)
        _assert_matches_schema(server_error["response"]["body"], server_schema)

        invalid_field = validation_error["response"]["body"]["field_errors"][0]["field"]
        assert invalid_field in request_schema["properties"]
        assert validation_error["request"] != happy_path["request"]
        assert validation_error["response"]["status_code"] == 400
        assert server_error["response"]["status_code"] == 500
        assert endpoint_id == f"{mock_operation['method']} {mock_operation['path']}"


def test_run_store_persists_contract_yaml_and_mock_data_json(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-012",
    )
    store.create(mode_requested=WorkflowMode.FE_FIRST)

    screen = _fe_first_screen()
    artifacts = build_provisional_contract_artifacts(
        screen,
        matrices=build_screen_matrix_bundle(screen),
        readiness=evaluate_readiness([screen], feature_mode=WorkflowMode.FE_FIRST).screens[0],
    )
    assert artifacts is not None

    contract_yaml = render_contract_yaml(artifacts.openapi_document)
    mock_data_json = render_mock_data_json(artifacts.mock_data)

    store.save_contract_yaml(screen.screen_id, contract_yaml)
    store.save_mock_data_json(screen.screen_id, mock_data_json)

    assert store.load_contract_yaml(screen.screen_id) == contract_yaml
    assert json.loads(store.load_mock_data_json(screen.screen_id)) == artifacts.mock_data
    assert store.screen_paths(screen.screen_id).contract_yaml.exists()
    assert store.screen_paths(screen.screen_id).mock_data_json.exists()


def _assert_matches_schema(value: Any, schema: dict[str, Any]) -> None:
    schema_type = schema.get("type")
    if schema_type == "object":
        assert isinstance(value, dict)
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert set(value) <= set(properties)
        for required in schema.get("required", []):
            assert required in value
        for key, item in value.items():
            _assert_matches_schema(item, properties[key])
        return
    if schema_type == "array":
        assert isinstance(value, list)
        item_schema = schema.get("items", {})
        for item in value:
            _assert_matches_schema(item, item_schema)
        return
    if schema_type == "string":
        assert isinstance(value, str)
        return
    if schema_type == "integer":
        assert isinstance(value, int)
        assert not isinstance(value, bool)
        return
    if schema_type == "number":
        assert isinstance(value, (int, float))
        assert not isinstance(value, bool)
        return
    if schema_type == "boolean":
        assert isinstance(value, bool)
        return

    msg = f"unsupported schema type: {schema_type!r}"
    raise AssertionError(msg)
