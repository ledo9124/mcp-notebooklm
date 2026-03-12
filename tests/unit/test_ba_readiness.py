"""Unit tests for BA readiness evaluation."""

from __future__ import annotations

from notebooklm_mcp.ba.models import (
    CanonicalScreen,
    ContradictionClaim,
    ContradictionRecord,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    GapKind,
    GapRecord,
    GapSeverity,
    ParseQuality,
    QuestionRecord,
    ReadinessDecision,
    WorkflowMode,
)
from notebooklm_mcp.ba.readiness import evaluate_readiness


def _evidence() -> list[EvidenceRef]:
    return [
        EvidenceRef(
            source_key="requirements",
            snapshot_id="requirements-abc123",
            locator="12-30",
        )
    ]


def _screen(
    screen_id: str,
    *,
    missing_info: list[GapRecord] | None = None,
    contradictions: list[ContradictionRecord] | None = None,
    open_questions: list[QuestionRecord] | None = None,
    parse_quality: ParseQuality = ParseQuality.HIGH,
    degraded: bool = False,
) -> CanonicalScreen:
    return CanonicalScreen(
        feature_key="customer-create",
        run_id="run-015",
        screen_id=screen_id,
        mode=WorkflowMode.BALANCED,
        missing_info=missing_info or [],
        contradictions=contradictions or [],
        open_questions=open_questions or [],
        quality_summary=ExtractionQualitySummary(
            parse_quality=parse_quality,
            degraded=degraded,
        ),
    )


def _gap(
    gap_id: str,
    *,
    kind: GapKind,
    severity: GapSeverity = GapSeverity.HIGH,
    workstreams: list[FactDomain] | None = None,
) -> GapRecord:
    return GapRecord(
        gap_id=gap_id,
        kind=kind,
        summary=gap_id.replace("-", " "),
        severity=severity,
        screen_id="customer-form",
        owner="Backend lead",
        blocking_workstreams=list(workstreams or []),
        evidence=_evidence(),
    )


def test_evaluate_readiness_downgrades_balanced_feature_to_fe_first_per_screen() -> None:
    summary = evaluate_readiness(
        [
            _screen(
                "customer-form",
                missing_info=[
                    _gap("missing-backend-contract", kind=GapKind.MISSING_BACKEND_CONTRACT),
                    _gap(
                        "assume-error-envelope",
                        kind=GapKind.REQUIRED_ASSUMPTION,
                        severity=GapSeverity.MEDIUM,
                        workstreams=[FactDomain.FE],
                    ),
                ],
            ),
            _screen("customer-list"),
        ],
        feature_mode=WorkflowMode.BALANCED,
    )

    assert summary.feature_mode is WorkflowMode.BALANCED
    assert summary.decision is ReadinessDecision.READY_FOR_FE_WITH_PROVISIONAL_CONTRACT
    assert summary.screens[0].resolved_mode is WorkflowMode.FE_FIRST
    assert summary.screens[0].fe_ready is True
    assert summary.screens[0].be_ready is False
    assert [gap.gap_id for gap in summary.required_assumptions] == ["assume-error-envelope"]
    assert any("resolved mode FE_FIRST instead of BALANCED" in warning for warning in summary.warnings)


def test_evaluate_readiness_forces_clarification_when_quality_or_contradictions_drop() -> None:
    contradiction = ContradictionRecord(
        contradiction_id="email-rule",
        summary="Email validation timing conflicts",
        claims=[
            ContradictionClaim(claim="Validate on blur", evidence=_evidence()),
            ContradictionClaim(claim="Validate on submit", evidence=_evidence()),
        ],
        open_question="Which interaction is authoritative?",
    )

    summary = evaluate_readiness(
        [
            _screen(
                "customer-form",
                contradictions=[contradiction],
                parse_quality=ParseQuality.LOW,
                degraded=True,
            )
        ],
        feature_mode=WorkflowMode.AUTO,
    )

    assert summary.decision is ReadinessDecision.NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS
    assert summary.screens[0].resolved_mode is WorkflowMode.CLARIFICATION_FIRST
    assert summary.screens[0].fe_ready is False
    assert summary.screens[0].be_ready is False
    assert any(gap.kind is GapKind.CONTRADICTORY_REQUIREMENT_DETAIL for gap in summary.blockers)
    assert any(question.question_id == "email-rule-resolution" for question in summary.screens[0].open_questions)
    assert any("degraded extraction quality" in warning for warning in summary.warnings)


def test_evaluate_readiness_keeps_partial_ready_features_honest() -> None:
    summary = evaluate_readiness(
        [
            _screen("customer-list"),
            _screen(
                "customer-form",
                missing_info=[
                    _gap(
                        "missing-shared-rule",
                        kind=GapKind.MISSING_REQUIREMENT_DETAIL,
                        workstreams=[FactDomain.SHARED],
                    )
                ],
                open_questions=[
                    QuestionRecord(
                        question_id="q-design",
                        summary="What empty-state copy should we use?",
                        owner="Design",
                        screen_id="customer-form",
                        evidence=_evidence(),
                    )
                ],
            ),
        ],
        feature_mode=WorkflowMode.AUTO,
    )

    assert summary.decision is ReadinessDecision.PARTIAL_READY_NEEDS_CLARIFICATION
    assert summary.screens[0].resolved_mode is WorkflowMode.BALANCED
    assert summary.screens[0].fe_ready is True
    assert summary.screens[0].be_ready is True
    assert summary.screens[1].resolved_mode is WorkflowMode.CLARIFICATION_FIRST
    assert summary.screens[1].fe_ready is False
    assert summary.screens[1].be_ready is False
    assert [gap.gap_id for gap in summary.blockers] == ["missing-shared-rule"]
