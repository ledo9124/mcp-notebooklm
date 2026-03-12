"""Unit tests for BA matrix generation, rendering, and persistence."""

from __future__ import annotations

from pathlib import Path

from notebooklm_mcp.ba.matrices import build_screen_matrix_bundle
from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    ParseQuality,
    WorkflowMode,
)
from notebooklm_mcp.ba.rendering import (
    render_action_rule_matrix_csv,
    render_api_matrix_csv,
    render_field_matrix_csv,
)
from notebooklm_mcp.ba.run_store import BARunStore


def _evidence(locator: str) -> EvidenceRef:
    return EvidenceRef(
        source_key="requirements",
        snapshot_id="requirements-abc123",
        locator=locator,
    )


def _screen() -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.BALANCED,
        run_id="run-015",
        shared_facts=[
            CanonicalFact(
                fact_id="fact-shared-rule",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={
                    "action_name": "Submit Customer",
                    "trigger": "User clicks Save",
                    "rule": "Customer email must be unique before creation completes",
                    "outcome": "Show duplicate-email validation and block submit",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence("12-20")],
            )
        ],
        fe_facts=[
            CanonicalFact(
                fact_id="fact-fe-field",
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
                evidence=[_evidence("22-30")],
            ),
            CanonicalFact(
                fact_id="fact-fe-note",
                domain=FactDomain.FE,
                category="field",
                value="Loyalty tier badge",
                status=FactStatus.PROVISIONAL,
                rationale="Discussed in workshop notes",
                origin="structured_extraction",
            ),
        ],
        be_facts=[
            CanonicalFact(
                fact_id="fact-be-endpoint",
                domain=FactDomain.BE,
                category="endpoint",
                value={
                    "endpoint_name": "Create Customer",
                    "method": "post",
                    "path": "/customers",
                    "request_body": "name, email, tier",
                    "response_body": "customer id and created timestamp",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence("31-40")],
            )
        ],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def test_build_screen_matrix_bundle_projects_rows_from_canonical_facts() -> None:
    bundle = build_screen_matrix_bundle(_screen())

    assert [row.field_name for row in bundle.field_rows] == ["email", "Loyalty tier badge"]
    assert bundle.field_rows[0].required is True
    assert bundle.field_rows[0].evidence_refs == ["requirements@requirements-abc123:22-30"]
    assert bundle.action_rule_rows[0].action_name == "Submit Customer"
    assert bundle.action_rule_rows[0].rule_summary.startswith("Customer email must be unique")
    assert bundle.api_rows[0].interface_name == "Create Customer"
    assert bundle.api_rows[0].interaction_type == "ENDPOINT"
    assert bundle.api_rows[0].method == "POST"
    assert bundle.api_rows[0].target == "/customers"
    assert "matrix row `fact-fe-note-field` has no evidence refs" in bundle.warnings


def test_render_matrix_csv_outputs_fixed_headers() -> None:
    bundle = build_screen_matrix_bundle(_screen())

    field_csv = render_field_matrix_csv(bundle.field_rows)
    action_csv = render_action_rule_matrix_csv(bundle.action_rule_rows)
    api_csv = render_api_matrix_csv(bundle.api_rows)

    assert field_csv.startswith(
        "row_id,screen_id,fact_id,source_domain,fact_status,field_name,field_label,field_type,required,description,evidence_count,evidence_refs\n"
    )
    assert "fact-fe-field-field,customer-form,fact-fe-field,FE,CONFIRMED,email,Email Address,email,true," in field_csv
    assert action_csv.startswith(
        "row_id,screen_id,fact_id,source_domain,fact_status,action_name,trigger,rule_summary,outcome,evidence_count,evidence_refs\n"
    )
    assert "Submit Customer,User clicks Save" in action_csv
    assert api_csv.startswith(
        "row_id,screen_id,fact_id,source_domain,fact_status,interface_name,interaction_type,method,target,request_summary,response_summary,evidence_count,evidence_refs\n"
    )
    assert ",Create Customer,ENDPOINT,POST,/customers," in api_csv


def test_run_store_persists_matrix_artifacts(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-015",
    )
    store.create()
    bundle = build_screen_matrix_bundle(_screen())

    store.save_screen_matrix_artifacts(
        "customer-form",
        field_csv=render_field_matrix_csv(bundle.field_rows),
        action_rule_csv=render_action_rule_matrix_csv(bundle.action_rule_rows),
        api_csv=render_api_matrix_csv(bundle.api_rows),
    )

    assert "fact-fe-field-field" in store.load_field_matrix_csv("customer-form")
    assert "fact-shared-rule-action" in store.load_action_rule_matrix_csv("customer-form")
    assert "fact-be-endpoint-api" in store.load_api_matrix_csv("customer-form")
