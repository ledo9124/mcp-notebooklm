"""Readiness evaluation for BA screens and feature bundles."""

from __future__ import annotations

from collections.abc import Sequence

from .gaps import all_gap_review_blockers, all_gap_review_questions, build_gap_review_document
from .models import (
    CanonicalScreen,
    ContradictionRecord,
    EvidenceRef,
    FactDomain,
    GapKind,
    GapRecord,
    ParseQuality,
    QuestionRecord,
    ReadinessDecision,
    ReadinessSummary,
    ScreenReadiness,
    WorkflowMode,
)

MODULE_PURPOSE = "Own feature and screen readiness evaluation over canonical BA outputs."

OWNS = (
    "Per-screen mode resolution from canonical facts and gap review data",
    "Feature-level readiness decisions and blocker aggregation",
    "Deterministic readiness warnings that explain downgraded outcomes",
)

MUST_NOT_OWN = (
    "NotebookLM prompt execution",
    "Canonical extraction and evidence normalization",
    "Filesystem persistence",
    "Final markdown rendering",
)

_DEGRADED_PARSE_QUALITIES = {ParseQuality.LOW, ParseQuality.FAILED}


def evaluate_readiness(
    screens: Sequence[CanonicalScreen],
    *,
    feature_mode: WorkflowMode,
) -> ReadinessSummary:
    """Evaluate screen and feature readiness from canonical screens."""

    if not screens:
        return ReadinessSummary(
            run_id="unknown-run",
            feature_key="unknown-feature",
            feature_mode=feature_mode,
            decision=ReadinessDecision.NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS,
            warnings=["no canonical screens were supplied for readiness evaluation"],
        )

    screen_results: list[ScreenReadiness] = []
    blockers: list[GapRecord] = []
    required_assumptions: list[GapRecord] = []
    warnings: list[str] = []

    for screen in screens:
        screen_readiness, screen_assumptions, screen_warnings = _evaluate_screen_readiness(
            screen,
            feature_mode=feature_mode,
        )
        screen_results.append(screen_readiness)
        blockers.extend(screen_readiness.blockers)
        required_assumptions.extend(screen_assumptions)
        warnings.extend(screen_warnings)

    return ReadinessSummary(
        run_id=screens[0].run_id,
        feature_key=screens[0].feature_key,
        feature_mode=feature_mode,
        decision=_overall_decision(screen_results),
        screens=screen_results,
        blockers=_dedupe_gaps(blockers),
        required_assumptions=_dedupe_gaps(required_assumptions),
        warnings=_dedupe_texts(warnings),
    )


def _evaluate_screen_readiness(
    screen: CanonicalScreen,
    *,
    feature_mode: WorkflowMode,
) -> tuple[ScreenReadiness, list[GapRecord], list[str]]:
    review = build_gap_review_document(screen)
    degraded = _is_degraded(screen)
    resolved_mode, reasons = _resolve_screen_mode(
        screen=screen,
        feature_mode=feature_mode,
        degraded=degraded,
        review=review,
    )
    contradiction_blockers = _contradiction_blockers(screen.screen_id, review.contradiction_backlog)
    contradiction_questions = _contradiction_questions(screen.screen_id, review.contradiction_backlog)
    blockers = _dedupe_gaps((*all_gap_review_blockers(review), *contradiction_blockers))
    open_questions = _dedupe_questions((*all_gap_review_questions(review), *contradiction_questions))

    fe_ready = resolved_mode is not WorkflowMode.CLARIFICATION_FIRST and not any(
        (
            degraded,
            review.shared_blockers,
            review.fe_blockers,
            review.contradiction_backlog,
        )
    )
    be_ready = resolved_mode is not WorkflowMode.CLARIFICATION_FIRST and not any(
        (
            degraded,
            review.shared_blockers,
            review.be_blockers,
            review.contradiction_backlog,
        )
    )

    warnings = [f"{screen.screen_id}: {warning}" for warning in review.warnings]
    if degraded:
        warnings.append(
            f"{screen.screen_id}: degraded extraction quality ({screen.quality_summary.parse_quality.value}) lowered readiness"
        )
    if resolved_mode is not feature_mode:
        reason_text = "; ".join(reasons)
        warnings.append(
            f"{screen.screen_id}: resolved mode {resolved_mode.value} instead of {feature_mode.value} because {reason_text}"
        )
    elif reasons:
        warnings.append(f"{screen.screen_id}: {resolved_mode.value} because {'; '.join(reasons)}")

    return (
        ScreenReadiness(
            screen_id=screen.screen_id,
            resolved_mode=resolved_mode,
            fe_ready=fe_ready,
            be_ready=be_ready,
            blockers=blockers,
            open_questions=open_questions,
        ),
        list(review.required_assumptions),
        warnings,
    )


def _resolve_screen_mode(
    *,
    screen: CanonicalScreen,
    feature_mode: WorkflowMode,
    degraded: bool,
    review,
) -> tuple[WorkflowMode, list[str]]:
    if feature_mode is WorkflowMode.CLARIFICATION_FIRST:
        return WorkflowMode.CLARIFICATION_FIRST, ["feature requested CLARIFICATION_FIRST"]

    reasons: list[str] = []
    if degraded:
        reasons.append("extraction quality is degraded")
    if review.contradiction_backlog:
        reasons.append("contradictions remain unresolved")
    if review.shared_blockers:
        reasons.append("shared blockers remain")
    if review.fe_blockers:
        reasons.append("FE blockers remain")
    if reasons:
        return WorkflowMode.CLARIFICATION_FIRST, reasons

    if feature_mode is WorkflowMode.FE_FIRST:
        return WorkflowMode.FE_FIRST, ["feature requested FE_FIRST"]

    if review.be_blockers or review.required_assumptions:
        if feature_mode is WorkflowMode.BALANCED:
            return WorkflowMode.FE_FIRST, ["backend blockers or required assumptions prevent balanced execution"]
        if feature_mode is WorkflowMode.AUTO:
            return WorkflowMode.FE_FIRST, ["backend blockers or required assumptions favor FE-first execution"]

    if feature_mode is WorkflowMode.AUTO:
        return WorkflowMode.BALANCED, ["no contradictions or backend blockers require downgrade"]

    return feature_mode, [f"feature requested {feature_mode.value}"]


def _overall_decision(screens: Sequence[ScreenReadiness]) -> ReadinessDecision:
    if screens and all(screen.fe_ready and screen.be_ready for screen in screens):
        return ReadinessDecision.READY_FOR_FE_AND_BE
    if screens and all(screen.fe_ready for screen in screens) and any(
        not screen.be_ready for screen in screens
    ):
        return ReadinessDecision.READY_FOR_FE_WITH_PROVISIONAL_CONTRACT
    if any(screen.fe_ready or screen.be_ready for screen in screens):
        return ReadinessDecision.PARTIAL_READY_NEEDS_CLARIFICATION
    return ReadinessDecision.NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS


def _contradiction_blockers(
    screen_id: str,
    contradictions: Sequence[ContradictionRecord],
) -> list[GapRecord]:
    blockers: list[GapRecord] = []
    for contradiction in contradictions:
        blockers.append(
            GapRecord(
                gap_id=f"{contradiction.contradiction_id}-blocker",
                kind=GapKind.CONTRADICTORY_REQUIREMENT_DETAIL,
                summary=contradiction.summary,
                severity=contradiction.severity,
                screen_id=screen_id,
                blocking_workstreams=[FactDomain.SHARED],
                evidence=_dedupe_evidence(
                    evidence
                    for claim in contradiction.claims
                    for evidence in claim.evidence
                ),
            )
        )
    return blockers


def _contradiction_questions(
    screen_id: str,
    contradictions: Sequence[ContradictionRecord],
) -> list[QuestionRecord]:
    questions: list[QuestionRecord] = []
    for contradiction in contradictions:
        if not contradiction.open_question:
            continue
        questions.append(
            QuestionRecord(
                question_id=f"{contradiction.contradiction_id}-resolution",
                summary=contradiction.open_question,
                owner="BA",
                severity=contradiction.severity,
                screen_id=screen_id,
                blocking_workstreams=[FactDomain.SHARED],
                evidence=_dedupe_evidence(
                    evidence
                    for claim in contradiction.claims
                    for evidence in claim.evidence
                ),
            )
        )
    return questions


def _is_degraded(screen: CanonicalScreen) -> bool:
    return screen.quality_summary.degraded or screen.quality_summary.parse_quality in _DEGRADED_PARSE_QUALITIES


def _dedupe_gaps(gaps: Sequence[GapRecord]) -> list[GapRecord]:
    deduped: dict[str, GapRecord] = {}
    for gap in gaps:
        deduped.setdefault(gap.gap_id, gap)
    return list(deduped.values())


def _dedupe_questions(questions: Sequence[QuestionRecord]) -> list[QuestionRecord]:
    deduped: dict[str, QuestionRecord] = {}
    for question in questions:
        deduped.setdefault(question.question_id, question)
    return list(deduped.values())


def _dedupe_texts(values: Sequence[str]) -> list[str]:
    deduped: dict[str, str] = {}
    for value in values:
        deduped.setdefault(value, value)
    return list(deduped.values())


def _dedupe_evidence(evidence_items: Sequence[EvidenceRef] | Sequence[object]) -> list[EvidenceRef]:
    deduped: dict[tuple[str, str, str, str | None], EvidenceRef] = {}
    for item in evidence_items:
        if not isinstance(item, EvidenceRef):
            continue
        key = (item.source_key, item.snapshot_id, item.locator or "", item.quote)
        deduped.setdefault(key, item)
    return list(deduped.values())


__all__ = [
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "evaluate_readiness",
]
