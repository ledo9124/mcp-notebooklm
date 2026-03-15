"""Focused tests for router execution planning and dispatch."""

from __future__ import annotations

import asyncio

import pytest

from notebooklm.contracts import Intent
from notebooklm.router import IntentClassification, NotebookResolution
from notebooklm.router.execute import AgentExecutionPlan, build_execution_plan, dispatch_execution


def _classification(intent: Intent) -> IntentClassification:
    return IntentClassification(intent=intent, confidence=0.9, matched_terms=("term",), rationale="test")


def _resolution(
    *,
    notebook_id: str | None,
    source: str = "exact_title",
    status: str = "resolved",
    rationale: str = "resolved for test",
) -> NotebookResolution:
    return NotebookResolution(
        notebook_id=notebook_id,
        source=source,
        status=status,
        matched_text=None,
        rationale=rationale,
        candidates=(),
    )


@pytest.mark.parametrize(
    ("request_text", "intent", "resolution", "command_name", "mode", "requires_notebook", "argument_key"),
    [
        (
            "list notebooks",
            Intent.LOCAL_METADATA,
            _resolution(notebook_id=None, source="none", status="none"),
            "notebook.list",
            "notebook_list",
            False,
            "request",
        ),
        (
            "which notebooks have PDF sources?",
            Intent.LOCAL_METADATA,
            _resolution(notebook_id=None, source="none", status="none"),
            "metadata.query",
            "metadata_query",
            False,
            "request",
        ),
        (
            "what do the pricing sources say about renewals?",
            Intent.QUERY,
            _resolution(notebook_id="nb_pricing"),
            "ask",
            "ask",
            True,
            "question",
        ),
        (
            "quick overview of current notebook",
            Intent.QUERY,
            _resolution(notebook_id="nb_context", source="current_context"),
            "overview",
            "overview",
            True,
            "request",
        ),
        (
            "summarize current notebook",
            Intent.GENERATION,
            _resolution(notebook_id="nb_context", source="current_context"),
            "summarize",
            "briefing_doc",
            True,
            "description",
        ),
        (
            "make me a study guide for the onboarding notebook",
            Intent.GENERATION,
            _resolution(notebook_id="nb_onboarding"),
            "study-guide",
            "study_guide",
            True,
            "description",
        ),
        (
            "make an audio overview for the pricing notebook",
            Intent.GENERATION,
            _resolution(notebook_id="nb_pricing"),
            "audio",
            "audio",
            True,
            "description",
        ),
        (
            "sync stale drive sources",
            Intent.REMOTE_METADATA,
            _resolution(notebook_id=None, source="none", status="none"),
            "sync.notebooks",
            "sync_notebooks",
            False,
            "sync_all",
        ),
        (
            "start deep research on AI safety",
            Intent.RESEARCH,
            _resolution(notebook_id="nb_context", source="current_context"),
            "research.start",
            "deep",
            True,
            "query",
        ),
        (
            "wait for research run r_123",
            Intent.RESEARCH,
            _resolution(notebook_id=None, source="none", status="none"),
            "research.wait",
            "research_wait",
            False,
            "request",
        ),
        (
            "import research results",
            Intent.RESEARCH,
            _resolution(notebook_id=None, source="none", status="none"),
            "research.import",
            "research_import",
            False,
            "request",
        ),
    ],
)
def test_build_execution_plan_routes_examples_to_expected_workflows(
    request_text,
    intent,
    resolution,
    command_name,
    mode,
    requires_notebook,
    argument_key,
):
    plan = build_execution_plan(
        request=request_text,
        classification=_classification(intent),
        resolution=resolution,
    )

    assert isinstance(plan, AgentExecutionPlan)
    assert plan.intent is intent
    assert plan.command_name == command_name
    assert plan.mode == mode
    assert plan.requires_notebook is requires_notebook
    assert plan.resolution_source == resolution.source
    assert argument_key in plan.arguments


def test_build_execution_plan_requires_notebook_for_notebook_scoped_workflows():
    with pytest.raises(ValueError, match="requires a resolved notebook target"):
        build_execution_plan(
            request="summarize current notebook",
            classification=_classification(Intent.GENERATION),
            resolution=_resolution(notebook_id=None, source="none", status="none"),
        )


def test_build_execution_plan_allows_partial_resolution_for_diagnostics():
    plan = build_execution_plan(
        request="summarize current notebook",
        classification=_classification(Intent.GENERATION),
        resolution=_resolution(
            notebook_id=None,
            source="none",
            status="ambiguous",
            rationale="Multiple cached notebook titles appear in the request.",
        ),
        allow_partial_resolution=True,
    )

    assert plan.command_name == "summarize"
    assert plan.mode == "briefing_doc"
    assert plan.notebook_id is None
    assert plan.requires_notebook is True


def test_build_execution_plan_rejects_ambiguous_resolution():
    with pytest.raises(ValueError, match="ambiguous notebook resolution"):
        build_execution_plan(
            request="what do the pricing sources say about renewals?",
            classification=_classification(Intent.QUERY),
            resolution=_resolution(
                notebook_id=None,
                source="none",
                status="ambiguous",
                rationale="Multiple cached notebook titles appear in the request.",
            ),
        )


def test_dispatch_execution_invokes_registered_handler():
    plan = build_execution_plan(
        request="make an audio overview for the pricing notebook",
        classification=_classification(Intent.GENERATION),
        resolution=_resolution(notebook_id="nb_pricing"),
    )
    called: list[str] = []

    async def _audio_handler(received_plan: AgentExecutionPlan):
        called.append(received_plan.command_name)
        return {"ok": True, "mode": received_plan.mode}

    result = asyncio.run(dispatch_execution(plan, handlers={"audio": _audio_handler}))

    assert result == {"ok": True, "mode": "audio"}
    assert called == ["audio"]


def test_dispatch_execution_rejects_missing_handler():
    plan = build_execution_plan(
        request="quick overview of current notebook",
        classification=_classification(Intent.QUERY),
        resolution=_resolution(notebook_id="nb_context", source="current_context"),
    )

    with pytest.raises(KeyError, match="No execution handler registered"):
        asyncio.run(dispatch_execution(plan, handlers={}))
