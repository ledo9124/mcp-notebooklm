"""Unit tests for BA gap review classification and question backlog rendering."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from notebooklm_mcp.ba.extraction import extract_canonical_screen
from notebooklm_mcp.ba.gaps import all_gap_review_blockers, all_gap_review_questions, build_gap_review_document
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
    ScreenCatalogEntry,
    SourceContentKind,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceType,
    WorkflowMode,
)
from notebooklm_mcp.ba.rendering import render_gap_review_json, render_question_backlog_markdown


def _screen() -> ScreenCatalogEntry:
    return ScreenCatalogEntry(
        screen_id="customer-form",
        screen_name="Customer Form",
        purpose="Create a customer record",
    )


def _manifest() -> SourceManifestDocument:
    return SourceManifestDocument(
        feature_key="customer-create",
        run_id="run-014",
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref="requirements/ba.pdf",
                notebook_source_id="src-1",
                snapshot_id="requirements-abc123",
                title="Requirements PDF",
            )
        ],
    )


def _canonical_screen() -> CanonicalScreen:
    evidence = [
        EvidenceRef(
            source_key="requirements",
            snapshot_id="requirements-abc123",
            locator="12-30",
        )
    ]
    return CanonicalScreen(
        feature_key="customer-create",
        screen_id="customer-form",
        mode=WorkflowMode.FE_FIRST,
        run_id="run-014",
        missing_info=[
            GapRecord(
                gap_id="gap-be-contract",
                kind=GapKind.MISSING_BACKEND_CONTRACT,
                summary="Duplicate-email response body shape is missing",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                owner="Backend lead",
                evidence=evidence,
            ),
            GapRecord(
                gap_id="gap-fe-dependency",
                kind=GapKind.FE_VISIBLE_BACKEND_DEPENDENCY,
                summary="FE cannot finalize inline validation until backend latency budget is known",
                severity=GapSeverity.MEDIUM,
                screen_id="customer-form",
                owner="Tech lead",
                blocking_workstreams=[FactDomain.FE],
                evidence=evidence,
            ),
            GapRecord(
                gap_id="gap-shared",
                kind=GapKind.MISSING_REQUIREMENT_DETAIL,
                summary="Customer archival rules remain unspecified",
                severity=GapSeverity.CRITICAL,
                screen_id="customer-form",
                evidence=evidence,
            ),
            GapRecord(
                gap_id="gap-assumption",
                kind=GapKind.REQUIRED_ASSUMPTION,
                summary="Assume provisional duplicate-email error code until contract is approved",
                severity=GapSeverity.MEDIUM,
                screen_id="customer-form",
                owner="BA",
                blocking_workstreams=[FactDomain.FE],
                evidence=evidence,
            ),
            GapRecord(
                gap_id="gap-deferred",
                kind=GapKind.DEFERRED_IMPLEMENTATION_DETAIL,
                summary="Audit-log export columns can be specified in a follow-up slice",
                severity=GapSeverity.LOW,
                screen_id="customer-form",
                owner="Design",
                evidence=evidence,
            ),
        ],
        contradictions=[
            ContradictionRecord(
                contradiction_id="contr-email-01",
                summary="Email uniqueness timing conflicts between BA PDF and workshop notes",
                severity=GapSeverity.HIGH,
                claims=[
                    ContradictionClaim(claim="Validate uniqueness on every keystroke", evidence=evidence),
                    ContradictionClaim(claim="Validate uniqueness only on submit", evidence=evidence),
                ],
                open_question="Which behavior is authoritative for v1?",
            )
        ],
        open_questions=[
            QuestionRecord(
                question_id="q-ba",
                summary="Should draft customers be autosaved?",
                owner="Business Analyst",
                severity=GapSeverity.HIGH,
                screen_id="customer-form",
                evidence=evidence,
            ),
            QuestionRecord(
                question_id="q-tech",
                summary="Which duplicate-email error envelope should FE expect?",
                owner="Engineering lead",
                severity=GapSeverity.CRITICAL,
                screen_id="customer-form",
                blocking_workstreams=[FactDomain.FE, FactDomain.BE],
                evidence=evidence,
            ),
            QuestionRecord(
                question_id="q-design",
                summary="What empty-state copy should appear after archive?",
                owner="UX",
                severity=GapSeverity.MEDIUM,
                screen_id="customer-form",
                evidence=evidence,
            ),
            QuestionRecord(
                question_id="q-unassigned",
                summary="Is customer-number formatting locale-specific?",
                severity=GapSeverity.MEDIUM,
                screen_id="customer-form",
                evidence=evidence,
            ),
        ],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def test_build_gap_review_document_partitions_blockers_and_questions() -> None:
    review = build_gap_review_document(_canonical_screen())

    assert [gap.gap_id for gap in review.fe_blockers] == ["gap-fe-dependency"]
    assert [gap.gap_id for gap in review.be_blockers] == ["gap-be-contract"]
    assert [gap.gap_id for gap in review.shared_blockers] == ["gap-shared"]
    assert [gap.gap_id for gap in review.required_assumptions] == ["gap-assumption"]
    assert [gap.gap_id for gap in review.non_blockers] == ["gap-deferred"]
    assert [question.question_id for question in review.questions_for_ba] == ["q-ba"]
    assert [question.question_id for question in review.questions_for_tech_lead] == ["q-tech"]
    assert [question.question_id for question in review.questions_for_design] == ["q-design"]
    assert [question.question_id for question in review.unassigned_questions] == ["q-unassigned"]
    assert review.contradiction_backlog[0].contradiction_id == "contr-email-01"
    assert "gap `gap-shared` has no owner" in review.warnings
    assert "question `q-unassigned` has no owner" in review.warnings
    assert [gap.gap_id for gap in all_gap_review_blockers(review)] == [
        "gap-shared",
        "gap-be-contract",
        "gap-fe-dependency",
    ]
    assert [question.question_id for question in all_gap_review_questions(review)] == [
        "q-tech",
        "q-ba",
        "q-design",
        "q-unassigned",
    ]


@pytest.mark.asyncio
async def test_extract_canonical_screen_normalizes_gap_aliases_for_review() -> None:
    async def _fake_ask(
        prompt_text: str,
        *,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            answer=json.dumps(
                {
                    "missing_info": [
                        {
                            "kind": "backend contract gap",
                            "summary": "Duplicate-email response shape is undefined",
                            "severity": "blocker",
                            "owner_role": "Engineering lead",
                            "workstream": "front end / back end",
                        },
                        {
                            "kind": "non-blocking detail",
                            "summary": "Tooltip animation timing can be settled later",
                            "severity": "minor",
                            "owner": "Design",
                        },
                    ],
                    "open_questions": [
                        {
                            "summary": "What inline error tone should appear?",
                            "target_owner": "UX",
                            "severity": "p2",
                            "blocked_workstreams": "frontend",
                        }
                    ],
                    "quality_summary": {"parse_quality": "HIGH"},
                }
            ),
            citations=(),
            conversation_id="conv-40",
            turn_number=3,
            is_follow_up=False,
        )

    result = await extract_canonical_screen(
        _fake_ask,
        feature_key="customer-create",
        run_id="run-014",
        screen=_screen(),
        manifest=_manifest(),
        mode=WorkflowMode.FE_FIRST,
        source_scope="requirements/ba.pdf",
    )
    review = build_gap_review_document(result.screen)

    assert result.screen.missing_info[0].kind is GapKind.MISSING_BACKEND_CONTRACT
    assert result.screen.missing_info[0].severity is GapSeverity.CRITICAL
    assert result.screen.missing_info[0].blocking_workstreams == [FactDomain.FE, FactDomain.BE]
    assert result.screen.missing_info[1].kind is GapKind.DEFERRED_IMPLEMENTATION_DETAIL
    assert review.shared_blockers[0].gap_id.startswith("customer-form-missing_backend_contract-")
    assert review.non_blockers[0].kind is GapKind.DEFERRED_IMPLEMENTATION_DETAIL
    assert review.questions_for_design[0].question_id.startswith("customer-form-q-")


def test_render_question_backlog_markdown_and_json() -> None:
    review = build_gap_review_document(_canonical_screen())

    markdown = render_question_backlog_markdown(review)
    payload = json.loads(render_gap_review_json(review))

    assert markdown.startswith("# Questions Backlog\n")
    assert "## MISSING" in markdown
    assert "## CONTRADICTED" in markdown
    assert "## QUESTION_FOR_BA" in markdown
    assert "## QUESTION_FOR_TECH_LEAD" in markdown
    assert "## QUESTION_FOR_DESIGN" in markdown
    assert "## UNASSIGNED" in markdown
    assert "[HIGH] `MISSING_BACKEND_CONTRACT` Duplicate-email response body shape is missing" in markdown
    assert payload["screen_id"] == "customer-form"
    assert payload["fe_blockers"][0]["gap_id"] == "gap-fe-dependency"
    assert payload["questions_for_tech_lead"][0]["question_id"] == "q-tech"
