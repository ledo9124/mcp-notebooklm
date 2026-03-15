"""Unit tests for workspace synthesis helpers."""

from notebooklm.workspaces import (
    WorkspaceNotebookAnswer,
    synthesize_workspace_answer,
)


def test_synthesize_workspace_answer_returns_empty_result_when_no_answers():
    result = synthesize_workspace_answer("What changed?", [])

    assert result.provenance == ()
    assert "No notebook answers were available" in result.answer


def test_synthesize_workspace_answer_passes_through_single_answer():
    result = synthesize_workspace_answer(
        "What changed?",
        [
            WorkspaceNotebookAnswer(
                notebook_id="nb_pricing",
                notebook_title="Pricing",
                answer_text="  Renewal objections increased in enterprise deals.  ",
            )
        ],
    )

    assert result.answer == "Renewal objections increased in enterprise deals."
    assert len(result.provenance) == 1
    assert result.provenance[0].notebook_id == "nb_pricing"
    assert result.provenance[0].contribution == "Renewal objections increased in enterprise deals."


def test_synthesize_workspace_answer_builds_transparent_multi_notebook_summary():
    result = synthesize_workspace_answer(
        "What changed in buyer objections?",
        [
            WorkspaceNotebookAnswer(
                notebook_id="nb_pricing",
                notebook_title="Pricing",
                answer_text="Buyers pushed harder on discount guardrails. A second sentence should not appear.",
            ),
            WorkspaceNotebookAnswer(
                notebook_id="nb_interviews",
                notebook_title="Customer Interviews",
                answer_text="Interviewees said procurement is slowing approvals.",
            ),
        ],
    )

    assert result.answer.startswith("Workspace synthesis:")
    assert "- Pricing: Buyers pushed harder on discount guardrails." in result.answer
    assert "- Customer Interviews: Interviewees said procurement is slowing approvals." in result.answer
    assert [item.notebook_id for item in result.provenance] == ["nb_pricing", "nb_interviews"]


def test_synthesize_workspace_answer_truncates_long_contributions():
    long_answer = (
        "This is a deliberately long first sentence that should be trimmed once it crosses the "
        "contribution limit because provenance snippets need to stay compact and readable for later displays. "
        "A second sentence is here for good measure."
    )

    result = synthesize_workspace_answer(
        "What changed?",
        [
            WorkspaceNotebookAnswer(
                notebook_id="nb_pricing",
                notebook_title="Pricing",
                answer_text=long_answer,
            ),
            WorkspaceNotebookAnswer(
                notebook_id="nb_support",
                notebook_title="Support",
                answer_text="Tickets rose in EMEA.",
            ),
        ],
    )

    first_contribution = result.provenance[0].contribution
    assert first_contribution.endswith("...")
    assert len(first_contribution) <= 160
