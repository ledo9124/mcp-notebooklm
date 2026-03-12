"""Matrix-generation boundary for deterministic screen-level BA artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field

from .models import BAModel, CanonicalFact, CanonicalScreen, EvidenceRef, FactDomain, FactStatus

MODULE_PURPOSE = "Own deterministic field/action/API matrix generation from canonical screens."

OWNS = (
    "Matrix row contracts for screen-level CSV artifacts",
    "Deterministic canonical-fact to matrix-row projection rules",
    "Traceability helpers that preserve fact and evidence links per row",
)

MUST_NOT_OWN = (
    "NotebookLM prompt or transport logic",
    "Filesystem persistence primitives",
    "Readiness or contract policy outside matrix rows",
    "MCP registration",
)


class FieldMatrixRow(BAModel):
    row_id: str
    screen_id: str
    fact_id: str
    source_domain: FactDomain
    fact_status: FactStatus
    field_name: str
    field_label: str | None = None
    field_type: str | None = None
    required: bool | None = None
    description: str | None = None
    evidence_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)


class ActionRuleMatrixRow(BAModel):
    row_id: str
    screen_id: str
    fact_id: str
    source_domain: FactDomain
    fact_status: FactStatus
    action_name: str
    trigger: str | None = None
    rule_summary: str
    outcome: str | None = None
    evidence_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)


class APIMatrixRow(BAModel):
    row_id: str
    screen_id: str
    fact_id: str
    source_domain: FactDomain
    fact_status: FactStatus
    interface_name: str
    interaction_type: str
    method: str | None = None
    target: str | None = None
    request_summary: str | None = None
    response_summary: str | None = None
    evidence_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)


class ScreenMatrixBundle(BAModel):
    feature_key: str
    run_id: str
    screen_id: str
    field_rows: list[FieldMatrixRow] = Field(default_factory=list)
    action_rule_rows: list[ActionRuleMatrixRow] = Field(default_factory=list)
    api_rows: list[APIMatrixRow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def build_screen_matrix_bundle(screen: CanonicalScreen) -> ScreenMatrixBundle:
    """Build deterministic screen-level matrices from canonical facts."""

    field_rows: list[FieldMatrixRow] = []
    action_rule_rows: list[ActionRuleMatrixRow] = []
    api_rows: list[APIMatrixRow] = []
    warnings: list[str] = []

    for fact in _all_facts(screen):
        field_row = _field_row_from_fact(screen, fact)
        if field_row is not None:
            field_rows.append(field_row)
            warnings.extend(_traceability_warnings(field_row.row_id, field_row.evidence_count))

        action_row = _action_rule_row_from_fact(screen, fact)
        if action_row is not None:
            action_rule_rows.append(action_row)
            warnings.extend(_traceability_warnings(action_row.row_id, action_row.evidence_count))

        api_row = _api_row_from_fact(screen, fact)
        if api_row is not None:
            api_rows.append(api_row)
            warnings.extend(_traceability_warnings(api_row.row_id, api_row.evidence_count))

    return ScreenMatrixBundle(
        feature_key=screen.feature_key,
        run_id=screen.run_id,
        screen_id=screen.screen_id,
        field_rows=sorted(field_rows, key=lambda row: (row.field_name.casefold(), row.row_id)),
        action_rule_rows=sorted(
            action_rule_rows,
            key=lambda row: (row.action_name.casefold(), row.rule_summary.casefold(), row.row_id),
        ),
        api_rows=sorted(
            api_rows,
            key=lambda row: (row.interaction_type.casefold(), row.interface_name.casefold(), row.row_id),
        ),
        warnings=sorted(set(warnings)),
    )


def _all_facts(screen: CanonicalScreen) -> tuple[CanonicalFact, ...]:
    return tuple((*screen.shared_facts, *screen.fe_facts, *screen.be_facts))


def _field_row_from_fact(
    screen: CanonicalScreen,
    fact: CanonicalFact,
) -> FieldMatrixRow | None:
    payload = _as_mapping(fact.value)
    category = _normalize_text(fact.category)
    if not (
        any(token in category for token in ("field", "input", "control", "widget"))
        or any(key in payload for key in ("field_name", "field", "label", "ui_label"))
    ):
        return None

    field_name = _first_text(payload, "field_name", "field", "name", "key", "id", "label")
    if not field_name:
        field_name = _string_value(fact.value)
    if not field_name:
        return None

    return FieldMatrixRow(
        row_id=f"{fact.fact_id}-field",
        screen_id=screen.screen_id,
        fact_id=fact.fact_id,
        source_domain=fact.domain,
        fact_status=fact.status,
        field_name=field_name,
        field_label=_first_text(payload, "label", "ui_label", "display_name", "title") or None,
        field_type=_first_text(payload, "field_type", "type", "data_type", "input_type") or None,
        required=_coerce_optional_bool(
            payload.get("required", payload.get("mandatory", payload.get("is_required")))
        ),
        description=(
            _first_text(payload, "description", "summary", "behavior", "help_text")
            or fact.note
            or (_string_value(fact.value) if not isinstance(fact.value, Mapping) else None)
        ),
        evidence_count=len(fact.evidence),
        evidence_refs=_serialize_evidence_refs(fact.evidence),
    )


def _action_rule_row_from_fact(
    screen: CanonicalScreen,
    fact: CanonicalFact,
) -> ActionRuleMatrixRow | None:
    payload = _as_mapping(fact.value)
    category = _normalize_text(fact.category)
    if not (
        any(
            token in category
            for token in (
                "business rule",
                "rule",
                "validation",
                "workflow",
                "permission",
                "action",
                "state transition",
                "transition",
            )
        )
        or any(key in payload for key in ("action_name", "action", "trigger", "rule", "outcome"))
    ):
        return None

    rule_summary = (
        _first_text(payload, "rule", "summary", "description", "value")
        or _string_value(fact.value)
        or fact.note
    )
    if not rule_summary:
        return None

    action_name = _first_text(payload, "action_name", "action", "name", "event")
    if not action_name:
        action_name = fact.category.replace("_", " ").title()

    return ActionRuleMatrixRow(
        row_id=f"{fact.fact_id}-action",
        screen_id=screen.screen_id,
        fact_id=fact.fact_id,
        source_domain=fact.domain,
        fact_status=fact.status,
        action_name=action_name,
        trigger=_first_text(payload, "trigger", "when", "condition", "event") or None,
        rule_summary=rule_summary,
        outcome=_first_text(payload, "outcome", "effect", "result", "then") or None,
        evidence_count=len(fact.evidence),
        evidence_refs=_serialize_evidence_refs(fact.evidence),
    )


def _api_row_from_fact(
    screen: CanonicalScreen,
    fact: CanonicalFact,
) -> APIMatrixRow | None:
    payload = _as_mapping(fact.value)
    category = _normalize_text(fact.category)
    if not (
        any(token in category for token in ("endpoint", "api", "event", "job", "integration", "webhook"))
        or any(
            key in payload
            for key in (
                "method",
                "http_method",
                "path",
                "route",
                "endpoint",
                "event_name",
                "queue",
                "topic",
            )
        )
    ):
        return None

    string_value = _string_value(fact.value)
    target = _first_text(payload, "path", "route", "endpoint", "event", "queue", "topic", "target")
    if not target and string_value.startswith("/"):
        target = string_value

    interface_name = _first_text(
        payload,
        "interface_name",
        "endpoint_name",
        "event_name",
        "job_name",
        "operation_id",
        "name",
    )
    if not interface_name:
        interface_name = target or string_value or fact.category.replace("_", " ").title()
    if not interface_name:
        return None

    return APIMatrixRow(
        row_id=f"{fact.fact_id}-api",
        screen_id=screen.screen_id,
        fact_id=fact.fact_id,
        source_domain=fact.domain,
        fact_status=fact.status,
        interface_name=interface_name,
        interaction_type=_interaction_type(category, payload),
        method=_uppercase_text(_first_text(payload, "method", "http_method", "verb")) or None,
        target=target,
        request_summary=_first_text(payload, "request", "request_body", "payload", "input") or None,
        response_summary=_first_text(payload, "response", "response_body", "output", "result") or None,
        evidence_count=len(fact.evidence),
        evidence_refs=_serialize_evidence_refs(fact.evidence),
    )


def _traceability_warnings(row_id: str, evidence_count: int) -> list[str]:
    if evidence_count > 0:
        return []
    return [f"matrix row `{row_id}` has no evidence refs"]


def _interaction_type(category: str, payload: Mapping[str, Any]) -> str:
    if "event" in category or any(key in payload for key in ("event_name", "topic")):
        return "EVENT"
    if "job" in category or "queue" in payload:
        return "JOB"
    if "webhook" in category:
        return "WEBHOOK"
    if "integration" in category:
        return "INTEGRATION"
    return "ENDPOINT"


def _serialize_evidence_refs(evidence: Sequence[EvidenceRef]) -> list[str]:
    items: list[str] = []
    for item in evidence:
        locator = item.locator or (item.quote or "").replace("\n", " ").strip()
        if locator:
            items.append(f"{item.source_key}@{item.snapshot_id}:{locator}")
        else:
            items.append(f"{item.source_key}@{item.snapshot_id}")
    return items


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_text(payload: Mapping[str, Any], *field_names: str) -> str:
    for field_name in field_names:
        value = payload.get(field_name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _string_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return ""
    text = str(value).strip()
    return text if text and text != "None" else ""


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _normalize_text(value)
    if normalized in {"true", "yes", "required", "mandatory"}:
        return True
    if normalized in {"false", "no", "optional"}:
        return False
    return None


def _uppercase_text(value: str) -> str:
    return value.strip().upper() if value.strip() else ""


def _normalize_text(value: Any) -> str:
    return " ".join(str(value).replace("_", " ").strip().casefold().split())


__all__ = [
    "APIMatrixRow",
    "ActionRuleMatrixRow",
    "FieldMatrixRow",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "ScreenMatrixBundle",
    "build_screen_matrix_bundle",
]
