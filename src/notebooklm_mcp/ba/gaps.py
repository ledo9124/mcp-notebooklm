"""Gap-review boundary for deterministic blocker and question classification."""

from __future__ import annotations

from collections.abc import Sequence

from .models import (
    CanonicalScreen,
    ContradictionRecord,
    FactDomain,
    GapKind,
    GapRecord,
    GapReviewDocument,
    GapSeverity,
    QuestionRecord,
)

MODULE_PURPOSE = "Own deterministic gap, blocker, contradiction, and question classification."

OWNS = (
    "Gap-review classification over canonical screen outputs",
    "Question-owner bucketing for downstream backlog rendering",
    "Deterministic blocker partitioning for readiness logic",
)

MUST_NOT_OWN = (
    "NotebookLM transport or prompt calls",
    "Filesystem persistence primitives",
    "Final FE/BE document rendering outside question backlogs",
    "MCP registration",
)

_SEVERITY_RANK = {
    GapSeverity.CRITICAL: 0,
    GapSeverity.HIGH: 1,
    GapSeverity.MEDIUM: 2,
    GapSeverity.LOW: 3,
}


def build_gap_review_document(screen: CanonicalScreen) -> GapReviewDocument:
    """Classify canonical gaps into explicit blocker and question buckets."""

    fe_blockers: list[GapRecord] = []
    be_blockers: list[GapRecord] = []
    shared_blockers: list[GapRecord] = []
    non_blockers: list[GapRecord] = []
    required_assumptions: list[GapRecord] = []
    questions_for_ba: list[QuestionRecord] = []
    questions_for_tech_lead: list[QuestionRecord] = []
    questions_for_design: list[QuestionRecord] = []
    unassigned_questions: list[QuestionRecord] = []
    warnings: list[str] = []

    for gap in _sorted_gaps(screen.missing_info):
        if gap.kind is GapKind.REQUIRED_ASSUMPTION:
            required_assumptions.append(gap)
        elif gap.kind is GapKind.DEFERRED_IMPLEMENTATION_DETAIL:
            non_blockers.append(gap)
        else:
            target = _blocker_bucket(gap)
            if target == "fe":
                fe_blockers.append(gap)
            elif target == "be":
                be_blockers.append(gap)
            else:
                shared_blockers.append(gap)
            if not gap.owner:
                warnings.append(f"gap `{gap.gap_id}` has no owner")

    for contradiction in _sorted_contradictions(screen.contradictions):
        if not contradiction.open_question:
            warnings.append(
                f"contradiction `{contradiction.contradiction_id}` is missing a resolution question"
            )

    for question in _sorted_questions(screen.open_questions):
        bucket = classify_question_owner(question)
        if bucket == "ba":
            questions_for_ba.append(question)
        elif bucket == "tech_lead":
            questions_for_tech_lead.append(question)
        elif bucket == "design":
            questions_for_design.append(question)
        else:
            unassigned_questions.append(question)
            if question.owner:
                warnings.append(
                    f"question `{question.question_id}` uses unrecognized owner `{question.owner}`"
                )
            else:
                warnings.append(f"question `{question.question_id}` has no owner")

    return GapReviewDocument(
        run_id=screen.run_id,
        feature_key=screen.feature_key,
        screen_id=screen.screen_id,
        fe_blockers=fe_blockers,
        be_blockers=be_blockers,
        shared_blockers=shared_blockers,
        non_blockers=non_blockers,
        required_assumptions=required_assumptions,
        contradiction_backlog=_sorted_contradictions(screen.contradictions),
        questions_for_ba=questions_for_ba,
        questions_for_tech_lead=questions_for_tech_lead,
        questions_for_design=questions_for_design,
        unassigned_questions=unassigned_questions,
        warnings=sorted(set(warnings)),
    )


def all_gap_review_questions(review: GapReviewDocument) -> tuple[QuestionRecord, ...]:
    """Return every question in a deterministic order."""

    return tuple(
        _sorted_questions(
            (
                *review.questions_for_ba,
                *review.questions_for_tech_lead,
                *review.questions_for_design,
                *review.unassigned_questions,
            )
        )
    )


def all_gap_review_blockers(review: GapReviewDocument) -> tuple[GapRecord, ...]:
    """Return every blocker that should influence readiness decisions."""

    return tuple(_sorted_gaps((*review.fe_blockers, *review.be_blockers, *review.shared_blockers)))


def classify_question_owner(question: QuestionRecord) -> str:
    """Map a question owner into a stable backlog bucket."""

    owner = _normalize_text(question.owner)
    if owner in {
        "ba",
        "business analyst",
        "analyst",
        "product owner",
        "product manager",
        "pm",
        "product",
    }:
        return "ba"
    if owner in {
        "tech lead",
        "engineering",
        "engineering lead",
        "backend",
        "front end",
        "frontend",
        "backend lead",
        "frontend lead",
        "architect",
    }:
        return "tech_lead"
    if owner in {"design", "designer", "ux", "ui", "ux design", "ui design"}:
        return "design"
    return "unassigned"


def _blocker_bucket(gap: GapRecord) -> str:
    workstreams = tuple(gap.blocking_workstreams) or _default_gap_workstreams(gap)
    if FactDomain.SHARED in workstreams or len(set(workstreams)) != 1:
        return "shared"
    if workstreams[0] is FactDomain.FE:
        return "fe"
    if workstreams[0] is FactDomain.BE:
        return "be"
    return "shared"


def _default_gap_workstreams(gap: GapRecord) -> tuple[FactDomain, ...]:
    if gap.kind is GapKind.MISSING_BACKEND_CONTRACT:
        return (FactDomain.BE,)
    if gap.kind is GapKind.FE_VISIBLE_BACKEND_DEPENDENCY:
        return (FactDomain.FE,)
    return (FactDomain.SHARED,)


def _sorted_gaps(gaps: Sequence[GapRecord]) -> list[GapRecord]:
    deduped: dict[str, GapRecord] = {}
    for gap in gaps:
        deduped.setdefault(gap.gap_id, gap)
    return sorted(
        deduped.values(),
        key=lambda gap: (
            _SEVERITY_RANK[gap.severity],
            gap.summary.casefold(),
            gap.gap_id,
        ),
    )


def _sorted_questions(questions: Sequence[QuestionRecord]) -> list[QuestionRecord]:
    deduped: dict[str, QuestionRecord] = {}
    for question in questions:
        deduped.setdefault(question.question_id, question)
    return sorted(
        deduped.values(),
        key=lambda question: (
            _SEVERITY_RANK[question.severity],
            _question_bucket_rank(classify_question_owner(question)),
            _normalize_text(question.owner),
            question.summary.casefold(),
            question.question_id,
        ),
    )


def _sorted_contradictions(
    contradictions: Sequence[ContradictionRecord],
) -> list[ContradictionRecord]:
    deduped: dict[str, ContradictionRecord] = {}
    for contradiction in contradictions:
        deduped.setdefault(contradiction.contradiction_id, contradiction)
    return sorted(
        deduped.values(),
        key=lambda contradiction: (
            _SEVERITY_RANK[contradiction.severity],
            contradiction.summary.casefold(),
            contradiction.contradiction_id,
        ),
    )


def _normalize_text(value: object | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _question_bucket_rank(bucket: str) -> int:
    return {
        "tech_lead": 0,
        "ba": 1,
        "design": 2,
        "unassigned": 3,
    }.get(bucket, 4)


__all__ = [
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "all_gap_review_blockers",
    "all_gap_review_questions",
    "build_gap_review_document",
    "classify_question_owner",
]
