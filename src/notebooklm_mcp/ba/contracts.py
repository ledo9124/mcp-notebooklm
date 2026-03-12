"""Provisional contract generation for FE-first BA screens."""

from __future__ import annotations

from collections.abc import Sequence
import json
import re
from typing import Any

from pydantic import Field

from .matrices import APIMatrixRow, FieldMatrixRow, ScreenMatrixBundle
from .models import (
    BAModel,
    CanonicalFact,
    CanonicalScreen,
    ContractMetadata,
    ContractStatus,
    EvidenceRef,
    MockScenario,
    QuestionRecord,
    ScreenReadiness,
    WorkflowMode,
)

MODULE_PURPOSE = "Own deterministic provisional OpenAPI and mock-data generation for FE-first screens."

OWNS = (
    "Screen-level provisional OpenAPI 3.0.3 generation from canonical/matrix/readiness state",
    "Explicit uncertainty metadata for endpoints and fields via vendor extensions",
    "Deterministic mock-data scenarios aligned to generated provisional contracts",
)

MUST_NOT_OWN = (
    "NotebookLM transport or prompt execution",
    "Filesystem persistence helpers",
    "Markdown/CSV rendering outside contract artifacts",
    "MCP tool registration",
)

_JSON_SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"
_PATH_PARAM_RE = re.compile(r"{([^{}]+)}")
_SPLIT_FIELDS_RE = re.compile(r"\s*(?:,|/|\band\b|\bor\b)\s*", re.IGNORECASE)


class ContractArtifacts(BAModel):
    """Generated provisional contract bundle for a single screen."""

    metadata: ContractMetadata
    openapi_document: dict[str, Any] = Field(default_factory=dict)
    mock_data: dict[str, Any] = Field(default_factory=dict)


def build_provisional_contract_artifacts(
    screen: CanonicalScreen,
    *,
    matrices: ScreenMatrixBundle,
    readiness: ScreenReadiness,
) -> ContractArtifacts | None:
    """Build a provisional OpenAPI contract and aligned mock data when useful."""

    endpoint_rows = _endpoint_rows(matrices.api_rows)
    if not _should_generate_contract(endpoint_rows=endpoint_rows, readiness=readiness):
        return None

    fact_index = {fact.fact_id: fact for fact in _all_facts(screen)}
    deduped_questions = _dedupe_questions(readiness.open_questions)
    questions_payload = _question_payload(deduped_questions)

    paths: dict[str, dict[str, Any]] = {}
    operations: dict[str, Any] = {}
    provisional_endpoint_ids: list[str] = []
    source_evidence = _dedupe_evidence(
        evidence
        for row in endpoint_rows
        for evidence in _fact_evidence(fact_index, row.fact_id)
    )

    for row in endpoint_rows:
        endpoint_id = _endpoint_id(row)
        request_schema = _request_schema(
            row=row,
            field_rows=matrices.field_rows,
            fact_index=fact_index,
        )
        response_schema = _response_schema(row=row)
        paths.setdefault(_path_value(row.target), {})[row.method.casefold()] = _operation_document(
            row=row,
            endpoint_id=endpoint_id,
            request_schema=request_schema,
            response_schema=response_schema,
            open_questions=questions_payload,
        )
        operations[endpoint_id] = _mock_operation(
            row=row,
            request_schema=request_schema,
            response_schema=response_schema,
        )
        provisional_endpoint_ids.append(endpoint_id)

    metadata = ContractMetadata(
        run_id=screen.run_id,
        feature_key=screen.feature_key,
        screen_id=screen.screen_id,
        contract_status=ContractStatus.PROVISIONAL,
        provisional_endpoint_ids=provisional_endpoint_ids,
        mock_scenarios=[
            MockScenario.HAPPY_PATH,
            MockScenario.VALIDATION_ERROR,
            MockScenario.EMPTY_STATE,
            MockScenario.SERVER_ERROR,
        ],
        source_evidence=source_evidence,
        open_questions=deduped_questions,
    )
    openapi_document = {
        "openapi": "3.0.3",
        "info": {
            "title": f"{screen.feature_key} / {screen.screen_id} provisional contract",
            "version": "0.1.0-provisional",
            "description": (
                "Generated for FE-first implementation. This contract is provisional and not "
                "approved backend truth."
            ),
        },
        "paths": paths,
        "components": {
            "schemas": {
                "ValidationError": _error_response_schema(code="validation_error"),
                "ServerError": _error_response_schema(code="server_error"),
            }
        },
        "x-contract-status": ContractStatus.PROVISIONAL.value,
        "x-generated-screen-id": screen.screen_id,
        "x-workflow-mode": readiness.resolved_mode.value,
        "x-source-evidence": _serialize_evidence(source_evidence),
        "x-open-questions": questions_payload,
        "x-json-schema-version": _JSON_SCHEMA_VERSION,
    }
    mock_data = {
        "run_id": screen.run_id,
        "feature_key": screen.feature_key,
        "screen_id": screen.screen_id,
        "contract_status": ContractStatus.PROVISIONAL.value,
        "operations": operations,
        "open_questions": questions_payload,
        "source_evidence": _serialize_evidence(source_evidence),
    }
    alignment_errors = validate_mock_data_alignment(
        openapi_document=openapi_document,
        mock_data=mock_data,
    )
    if alignment_errors:
        joined = "; ".join(alignment_errors)
        msg = f"generated mock data drifted from the provisional contract: {joined}"
        raise ValueError(msg)
    return ContractArtifacts(
        metadata=metadata,
        openapi_document=openapi_document,
        mock_data=mock_data,
    )


def render_contract_yaml(document: dict[str, Any]) -> str:
    """Render a provisional contract document deterministically as YAML."""

    return "\n".join(_yaml_lines(document)).rstrip() + "\n"


def render_mock_data_json(document: dict[str, Any]) -> str:
    """Render deterministic mock data as pretty JSON."""

    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def validate_mock_data_alignment(
    *,
    openapi_document: dict[str, Any],
    mock_data: dict[str, Any],
) -> list[str]:
    """Return deterministic alignment errors between a contract and its mock payloads."""

    errors: list[str] = []
    contract_status = openapi_document.get("x-contract-status")
    mock_status = mock_data.get("contract_status")
    if contract_status != mock_status:
        errors.append(
            f"mock-data contract_status `{mock_status}` does not match contract `{contract_status}`"
        )

    contract_operations = _contract_operation_index(openapi_document)
    mock_operations = mock_data.get("operations")
    if not isinstance(mock_operations, dict):
        return ["mock-data operations payload must be an object"]

    for endpoint_id in sorted(contract_operations):
        if endpoint_id not in mock_operations:
            errors.append(f"mock-data is missing operation `{endpoint_id}`")

    for endpoint_id, operation_payload in sorted(mock_operations.items()):
        contract_operation = contract_operations.get(endpoint_id)
        if contract_operation is None:
            errors.append(f"mock-data defines unknown operation `{endpoint_id}`")
            continue
        if not isinstance(operation_payload, dict):
            errors.append(f"mock-data operation `{endpoint_id}` must be an object")
            continue
        scenarios = operation_payload.get("scenarios")
        if not isinstance(scenarios, dict):
            errors.append(f"mock-data operation `{endpoint_id}` is missing a scenario object")
            continue
        expected_scenarios = {
            MockScenario.HAPPY_PATH.value,
            MockScenario.VALIDATION_ERROR.value,
            MockScenario.EMPTY_STATE.value,
            MockScenario.SERVER_ERROR.value,
        }
        missing_scenarios = sorted(expected_scenarios.difference(scenarios))
        extra_scenarios = sorted(set(scenarios).difference(expected_scenarios))
        errors.extend(
            f"mock-data operation `{endpoint_id}` is missing scenario `{scenario}`"
            for scenario in missing_scenarios
        )
        errors.extend(
            f"mock-data operation `{endpoint_id}` includes unexpected scenario `{scenario}`"
            for scenario in extra_scenarios
        )
        request_schema = _request_schema_for_operation(openapi_document, contract_operation)
        success_schema = _response_schema_for_operation(
            openapi_document=openapi_document,
            operation=contract_operation,
            status_code="200",
        )
        validation_error_schema = _response_schema_for_operation(
            openapi_document=openapi_document,
            operation=contract_operation,
            status_code="400",
        )
        server_error_schema = _response_schema_for_operation(
            openapi_document=openapi_document,
            operation=contract_operation,
            status_code="500",
        )
        for scenario_name, scenario_payload in sorted(scenarios.items()):
            if not isinstance(scenario_payload, dict):
                errors.append(
                    f"mock-data scenario `{endpoint_id}` / `{scenario_name}` must be an object"
                )
                continue
            request_payload = scenario_payload.get("request", {})
            response_payload = scenario_payload.get("response", {})
            if request_schema is not None and scenario_name != MockScenario.VALIDATION_ERROR.value:
                errors.extend(
                    _validate_payload_against_schema(
                        payload=request_payload,
                        schema=request_schema,
                        location=f"{endpoint_id} {scenario_name} request",
                    )
                )
            elif request_schema is not None:
                errors.extend(
                    _validate_payload_keys_only(
                        payload=request_payload,
                        schema=request_schema,
                        location=f"{endpoint_id} {scenario_name} request",
                    )
                )
            status_code = response_payload.get("status_code")
            body = response_payload.get("body")
            expected_status_code = {
                MockScenario.HAPPY_PATH.value: 200,
                MockScenario.EMPTY_STATE.value: 200,
                MockScenario.VALIDATION_ERROR.value: 400,
                MockScenario.SERVER_ERROR.value: 500,
            }.get(scenario_name)
            if expected_status_code is not None and status_code != expected_status_code:
                errors.append(
                    f"{endpoint_id} {scenario_name} response status `{status_code}` should be `{expected_status_code}`"
                )
            schema = {
                MockScenario.HAPPY_PATH.value: success_schema,
                MockScenario.EMPTY_STATE.value: success_schema,
                MockScenario.VALIDATION_ERROR.value: validation_error_schema,
                MockScenario.SERVER_ERROR.value: server_error_schema,
            }.get(scenario_name)
            if schema is not None:
                errors.extend(
                    _validate_payload_against_schema(
                        payload=body,
                        schema=schema,
                        location=f"{endpoint_id} {scenario_name} response",
                    )
                )
    return errors


def _should_generate_contract(
    *,
    endpoint_rows: Sequence[APIMatrixRow],
    readiness: ScreenReadiness,
) -> bool:
    if not endpoint_rows or not readiness.fe_ready:
        return False
    return readiness.resolved_mode is WorkflowMode.FE_FIRST or not readiness.be_ready


def _endpoint_rows(rows: Sequence[APIMatrixRow]) -> list[APIMatrixRow]:
    deduped: dict[tuple[str, str, str], APIMatrixRow] = {}
    for row in rows:
        if row.interaction_type != "ENDPOINT" or not row.method or not row.target:
            continue
        key = (row.method.upper(), _path_value(row.target), row.interface_name.casefold())
        deduped.setdefault(key, row)
    return [
        deduped[key]
        for key in sorted(deduped, key=lambda value: (value[1], value[0], value[2]))
    ]


def _all_facts(screen: CanonicalScreen) -> tuple[CanonicalFact, ...]:
    return tuple((*screen.shared_facts, *screen.fe_facts, *screen.be_facts))


def _operation_document(
    *,
    row: APIMatrixRow,
    endpoint_id: str,
    request_schema: dict[str, Any] | None,
    response_schema: dict[str, Any],
    open_questions: list[dict[str, Any]],
) -> dict[str, Any]:
    response_ref = _serialize_evidence_refs(row.evidence_refs)
    operation = {
        "operationId": _operation_id(row),
        "summary": row.interface_name,
        "description": "Generated provisional endpoint for FE-first delivery.",
        "tags": [row.screen_id],
        "parameters": _path_parameters(row),
        "responses": {
            "200": {
                "description": "Provisional successful response.",
                "content": {
                    "application/json": {
                        "schema": response_schema,
                    }
                },
            },
            "400": {
                "description": "Provisional validation failure response.",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ValidationError"},
                    }
                },
            },
            "500": {
                "description": "Provisional server error response.",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ServerError"},
                    }
                },
            },
        },
        "x-contract-status": ContractStatus.PROVISIONAL.value,
        "x-provisional-endpoint-id": endpoint_id,
        "x-source-evidence": response_ref,
        "x-open-questions": open_questions,
    }
    if request_schema is not None:
        operation["requestBody"] = {
            "required": bool(request_schema.get("required")),
            "content": {
                "application/json": {
                    "schema": request_schema,
                }
            },
        }
    return operation


def _request_schema(
    *,
    row: APIMatrixRow,
    field_rows: Sequence[FieldMatrixRow],
    fact_index: dict[str, CanonicalFact],
) -> dict[str, Any] | None:
    requested_names = tuple(_parse_field_names(row.request_summary))
    selected_rows = _matching_field_rows(requested_names, field_rows)
    if not selected_rows and not requested_names:
        selected_rows = tuple(sorted(field_rows, key=lambda item: (item.field_name.casefold(), item.row_id)))
    properties: dict[str, Any] = {}
    required: list[str] = []

    for field_row in selected_rows:
        property_name = _property_name(field_row.field_name)
        properties[property_name] = _field_schema_from_row(field_row)
        if field_row.required:
            required.append(property_name)

    for field_name in requested_names:
        property_name = _property_name(field_name)
        if property_name in properties:
            continue
        properties[property_name] = _generic_field_schema(
            field_name=field_name,
            field_status=row.fact_status.value,
            evidence_refs=_serialize_evidence(_fact_evidence(fact_index, row.fact_id)),
        )

    if not properties:
        return None

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {name: properties[name] for name in sorted(properties)},
        "required": sorted(set(required)),
        "x-field-status": row.fact_status.value,
        "x-source-evidence": _serialize_evidence(_fact_evidence(fact_index, row.fact_id)),
    }


def _response_schema(*, row: APIMatrixRow) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for field_name in _parse_field_names(row.response_summary):
        property_name = _property_name(field_name)
        properties[property_name] = {
            "type": _inferred_json_type(property_name, field_name),
            "description": f"Derived from provisional response summary: {field_name}.",
            "x-field-status": row.fact_status.value,
            "x-source-evidence": _serialize_evidence_refs(row.evidence_refs),
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {name: properties[name] for name in sorted(properties)},
        "x-field-status": row.fact_status.value,
        "x-source-evidence": _serialize_evidence_refs(row.evidence_refs),
    }


def _matching_field_rows(
    requested_names: Sequence[str],
    field_rows: Sequence[FieldMatrixRow],
) -> tuple[FieldMatrixRow, ...]:
    if not requested_names:
        return ()
    requested_keys = {_property_name(name) for name in requested_names}
    selected = [
        row
        for row in field_rows
        if _property_name(row.field_name) in requested_keys
    ]
    return tuple(sorted(selected, key=lambda row: (_property_name(row.field_name), row.row_id)))


def _field_schema_from_row(row: FieldMatrixRow) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": _inferred_json_type(row.field_name, row.field_type),
        "x-field-status": row.fact_status.value,
        "x-source-evidence": _serialize_evidence_refs(row.evidence_refs),
    }
    if row.field_label:
        schema["title"] = row.field_label
    if row.description:
        schema["description"] = row.description
    if row.field_type and "email" in row.field_type.casefold():
        schema["format"] = "email"
    if row.field_type and any(token in row.field_type.casefold() for token in ("date", "time")):
        schema["format"] = "date-time"
    return schema


def _generic_field_schema(
    *,
    field_name: str,
    field_status: str,
    evidence_refs: Sequence[str],
) -> dict[str, Any]:
    schema = {
        "type": _inferred_json_type(field_name, field_name),
        "description": f"Derived from provisional request summary: {field_name}.",
        "x-field-status": field_status,
        "x-source-evidence": list(evidence_refs),
    }
    if "email" in field_name.casefold():
        schema["format"] = "email"
    if any(token in field_name.casefold() for token in ("date", "time")):
        schema["format"] = "date-time"
    return schema


def _path_parameters(row: APIMatrixRow) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    for name in sorted(set(_PATH_PARAM_RE.findall(row.target or ""))):
        parameters.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {
                    "type": _inferred_json_type(name, name),
                    "x-field-status": row.fact_status.value,
                    "x-source-evidence": _serialize_evidence_refs(row.evidence_refs),
                },
            }
        )
    return parameters


def _mock_operation(
    *,
    row: APIMatrixRow,
    request_schema: dict[str, Any] | None,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    request_example = _example_object(request_schema)
    response_example = _example_object(response_schema)
    invalid_field = _first_invalid_field(request_schema)
    return {
        "method": row.method.upper(),
        "path": _path_value(row.target),
        "scenarios": {
            MockScenario.HAPPY_PATH.value: {
                "request": request_example,
                "response": {
                    "status_code": 200,
                    "body": response_example,
                },
            },
            MockScenario.VALIDATION_ERROR.value: {
                "request": _invalid_request_example(request_example, request_schema),
                "response": {
                    "status_code": 400,
                    "body": {
                        "error": "validation_error",
                        "message": f"{invalid_field} failed provisional validation",
                        "field_errors": [{"field": invalid_field, "issue": "invalid_or_missing"}],
                    },
                },
            },
            MockScenario.EMPTY_STATE.value: {
                "request": request_example,
                "response": {
                    "status_code": 200,
                    "body": {},
                },
            },
            MockScenario.SERVER_ERROR.value: {
                "request": request_example,
                "response": {
                    "status_code": 500,
                    "body": {
                        "error": "server_error",
                        "message": "Provisional backend failure",
                    },
                },
            },
        },
    }


def _example_object(schema: dict[str, Any] | None) -> dict[str, Any]:
    if schema is None:
        return {}
    properties = schema.get("properties", {})
    return {
        name: _example_value(name, property_schema)
        for name, property_schema in sorted(properties.items())
    }


def _invalid_request_example(
    request_example: dict[str, Any],
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    invalid = dict(request_example)
    field_name = _first_invalid_field(schema)
    property_schema = (schema or {}).get("properties", {}).get(field_name, {})
    invalid[field_name] = _invalid_value(property_schema)
    return invalid


def _first_invalid_field(schema: dict[str, Any] | None) -> str:
    if schema is None:
        return "request"
    required = list(schema.get("required", []))
    if required:
        return required[0]
    properties = list((schema.get("properties") or {}).keys())
    return properties[0] if properties else "request"


def _example_value(name: str, schema: dict[str, Any]) -> Any:
    value_type = schema.get("type")
    value_format = schema.get("format")
    normalized = name.casefold()
    if value_format == "email":
        return "customer@example.test"
    if value_format == "date-time":
        return "2026-01-01T00:00:00Z"
    if value_type == "boolean":
        return True
    if value_type == "integer":
        return 101 if normalized.endswith("_id") else 1
    if value_type == "number":
        return 1.0
    if normalized.endswith("_id"):
        return "cust-101"
    if "tier" in normalized:
        return "gold"
    if "name" in normalized:
        return "Example Customer"
    if "email" in normalized:
        return "customer@example.test"
    if "timestamp" in normalized or normalized.endswith("_at"):
        return "2026-01-01T00:00:00Z"
    return f"{normalized}-value"


def _invalid_value(schema: dict[str, Any]) -> Any:
    value_type = schema.get("type")
    if value_type == "boolean":
        return "invalid"
    if value_type in {"integer", "number"}:
        return None
    return ""


def _error_response_schema(*, code: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "error": {"type": "string"},
            "message": {"type": "string"},
            "field_errors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "field": {"type": "string"},
                        "issue": {"type": "string"},
                    },
                },
            },
        },
        "x-contract-status": ContractStatus.PROVISIONAL.value,
        "x-error-kind": code,
    }


def _question_payload(questions: Sequence[QuestionRecord]) -> list[dict[str, Any]]:
    return [
        {
            "question_id": question.question_id,
            "summary": question.summary,
            "owner": question.owner,
            "severity": question.severity.value,
            "blocking_workstreams": [workstream.value for workstream in question.blocking_workstreams],
        }
        for question in questions
    ]


def _dedupe_questions(questions: Sequence[QuestionRecord]) -> list[QuestionRecord]:
    deduped: dict[str, QuestionRecord] = {}
    for question in questions:
        deduped.setdefault(question.question_id, question)
    return list(deduped.values())


def _fact_evidence(
    fact_index: dict[str, CanonicalFact],
    fact_id: str,
) -> list[EvidenceRef]:
    fact = fact_index.get(fact_id)
    return list(fact.evidence) if fact is not None else []


def _dedupe_evidence(evidence_items: Sequence[EvidenceRef] | Sequence[object]) -> list[EvidenceRef]:
    deduped: dict[tuple[str, str, str, str | None], EvidenceRef] = {}
    for item in evidence_items:
        if not isinstance(item, EvidenceRef):
            continue
        key = (item.source_key, item.snapshot_id, item.locator or "", item.quote)
        deduped.setdefault(key, item)
    return list(deduped.values())


def _serialize_evidence(evidence: Sequence[EvidenceRef]) -> list[str]:
    return [
        _serialize_evidence_ref(item)
        for item in evidence
    ]


def _serialize_evidence_refs(evidence_refs: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(evidence_refs))


def _serialize_evidence_ref(item: EvidenceRef) -> str:
    locator = item.locator or (item.quote or "").replace("\n", " ").strip()
    return f"{item.source_key}@{item.snapshot_id}:{locator}" if locator else f"{item.source_key}@{item.snapshot_id}"


def _parse_field_names(summary: str | None) -> list[str]:
    if not summary:
        return []
    raw_parts = _SPLIT_FIELDS_RE.split(summary)
    deduped: dict[str, str] = {}
    for part in raw_parts:
        normalized = part.strip(" .")
        if not normalized:
            continue
        key = _property_name(normalized)
        if key:
            deduped.setdefault(key, normalized)
    return [deduped[key] for key in sorted(deduped)]


def _operation_id(row: APIMatrixRow) -> str:
    return _property_name(f"{row.screen_id}_{row.method}_{row.interface_name}")


def _endpoint_id(row: APIMatrixRow) -> str:
    return f"{row.method.upper()} {_path_value(row.target)}"


def _path_value(value: str | None) -> str:
    if not value:
        return "/"
    return value if value.startswith("/") else f"/{value}"


def _property_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").casefold()
    return normalized or "value"


def _contract_operation_index(openapi_document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    operations: dict[str, dict[str, Any]] = {}
    for path, methods in sorted((openapi_document.get("paths") or {}).items()):
        if not isinstance(methods, dict):
            continue
        for method, operation in sorted(methods.items()):
            if not isinstance(operation, dict):
                continue
            endpoint_id = operation.get("x-provisional-endpoint-id") or f"{method.upper()} {path}"
            operations[str(endpoint_id)] = operation
    return operations


def _request_schema_for_operation(
    openapi_document: dict[str, Any],
    operation: dict[str, Any],
) -> dict[str, Any] | None:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None
    schema = (
        request_body.get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    if not isinstance(schema, dict):
        return None
    return _resolve_schema(openapi_document, schema)


def _response_schema_for_operation(
    *,
    openapi_document: dict[str, Any],
    operation: dict[str, Any],
    status_code: str,
) -> dict[str, Any] | None:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    response = responses.get(status_code)
    if not isinstance(response, dict):
        return None
    schema = (
        response.get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    if not isinstance(schema, dict):
        return None
    return _resolve_schema(openapi_document, schema)


def _resolve_schema(
    openapi_document: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    reference = schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/components/schemas/"):
        return schema
    schema_name = reference.rsplit("/", maxsplit=1)[-1]
    components = openapi_document.get("components", {})
    if not isinstance(components, dict):
        return schema
    component_schemas = components.get("schemas", {})
    if not isinstance(component_schemas, dict):
        return schema
    resolved = component_schemas.get(schema_name)
    return resolved if isinstance(resolved, dict) else schema


def _validate_payload_keys_only(
    *,
    payload: Any,
    schema: dict[str, Any],
    location: str,
) -> list[str]:
    if not isinstance(payload, dict):
        return [f"{location} must be an object"]
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    allowed_keys = set(properties)
    errors: list[str] = []
    for key in sorted(payload):
        if key not in allowed_keys:
            errors.append(f"{location} includes unknown key `{key}`")
    return errors


def _validate_payload_against_schema(
    *,
    payload: Any,
    schema: dict[str, Any],
    location: str,
) -> list[str]:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(payload, dict):
            return [f"{location} must be an object"]
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict):
            return []
        errors: list[str] = []
        for key in sorted(required):
            if key not in payload:
                errors.append(f"{location} is missing required key `{key}`")
        for key in sorted(payload):
            if key not in properties:
                errors.append(f"{location} includes unknown key `{key}`")
                continue
            errors.extend(
                _validate_payload_against_schema(
                    payload=payload[key],
                    schema=properties[key],
                    location=f"{location}.{key}",
                )
            )
        return errors
    if schema_type == "array":
        if not isinstance(payload, list):
            return [f"{location} must be an array"]
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            return []
        errors: list[str] = []
        for index, item in enumerate(payload):
            errors.extend(
                _validate_payload_against_schema(
                    payload=item,
                    schema=item_schema,
                    location=f"{location}[{index}]",
                )
            )
        return errors
    if schema_type == "string":
        return [] if isinstance(payload, str) else [f"{location} must be a string"]
    if schema_type == "boolean":
        return [] if isinstance(payload, bool) else [f"{location} must be a boolean"]
    if schema_type == "integer":
        valid = isinstance(payload, int) and not isinstance(payload, bool)
        return [] if valid else [f"{location} must be an integer"]
    if schema_type == "number":
        valid = isinstance(payload, (int, float)) and not isinstance(payload, bool)
        return [] if valid else [f"{location} must be a number"]
    return []


def _inferred_json_type(name: str, raw_type: str | None) -> str:
    normalized = f"{name} {raw_type or ''}".casefold()
    if "bool" in normalized or any(token in normalized for token in ("checkbox", "toggle", "flag")):
        return "boolean"
    if "decimal" in normalized or "float" in normalized or "amount" in normalized:
        return "number"
    if "email" in normalized or "date" in normalized or "time" in normalized or "name" in normalized:
        return "string"
    if "id" in normalized or "count" in normalized or "number" in normalized:
        return "integer"
    return "string"


def _yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}{{}}"]
        lines: list[str] = []
        for key, item in value.items():
            if _is_yaml_scalar(item):
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
            elif isinstance(item, list) and not item:
                lines.append(f"{prefix}{key}: []")
            elif isinstance(item, dict) and not item:
                lines.append(f"{prefix}{key}: {{}}")
            else:
                lines.append(f"{prefix}{key}:")
                lines.extend(_yaml_lines(item, indent + 2))
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines = []
        for item in value:
            lines.extend(_yaml_list_item_lines(item, indent))
        return lines
    return [f"{prefix}{_yaml_scalar(value)}"]


def _yaml_list_item_lines(value: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if _is_yaml_scalar(value):
        return [f"{prefix}- {_yaml_scalar(value)}"]
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}- {{}}"]
        keys = list(value)
        first_key = keys[0]
        first_value = value[first_key]
        if _is_yaml_scalar(first_value):
            lines = [f"{prefix}- {first_key}: {_yaml_scalar(first_value)}"]
        elif isinstance(first_value, list) and not first_value:
            lines = [f"{prefix}- {first_key}: []"]
        elif isinstance(first_value, dict) and not first_value:
            lines = [f"{prefix}- {first_key}: {{}}"]
        else:
            lines = [f"{prefix}- {first_key}:"]
            lines.extend(_yaml_lines(first_value, indent + 4))
        child_prefix = " " * (indent + 2)
        for key in keys[1:]:
            item = value[key]
            if _is_yaml_scalar(item):
                lines.append(f"{child_prefix}{key}: {_yaml_scalar(item)}")
            elif isinstance(item, list) and not item:
                lines.append(f"{child_prefix}{key}: []")
            elif isinstance(item, dict) and not item:
                lines.append(f"{child_prefix}{key}: {{}}")
            else:
                lines.append(f"{child_prefix}{key}:")
                lines.extend(_yaml_lines(item, indent + 4))
        return lines
    lines = [f"{prefix}-"]
    lines.extend(_yaml_lines(value, indent + 2))
    return lines


def _is_yaml_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if re.fullmatch(r"[A-Za-z0-9_./-]+(?: [A-Za-z0-9_./-]+)*", value):
        return value
    return json.dumps(value)


__all__ = [
    "ContractArtifacts",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "build_provisional_contract_artifacts",
    "render_contract_yaml",
    "render_mock_data_json",
    "validate_mock_data_alignment",
]
