"""Execution helpers for workspace ask fan-out orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..local.repositories import WorkspaceRecord, WorkspaceRunRecord
from .indexing import WorkspaceCandidateRecord
from .planning import WorkspaceQueryPlan
from .runs import complete_workspace_run, start_workspace_run
from .synthesis import WorkspaceNotebookAnswer, WorkspaceSynthesisResult, synthesize_workspace_answer

WorkspaceAskCallable = Callable[[WorkspaceCandidateRecord, str], Awaitable[Any]]


@dataclass(frozen=True)
class WorkspaceExecutionFailure:
    """One notebook-level failure observed during workspace fan-out execution."""

    notebook_id: str
    notebook_title: str | None
    error_type: str
    message: str


@dataclass(frozen=True)
class WorkspaceExecutionResult:
    """Completed workspace fan-out execution with run persistence details."""

    run: WorkspaceRunRecord
    plan: WorkspaceQueryPlan
    answers: tuple[WorkspaceNotebookAnswer, ...]
    failures: tuple[WorkspaceExecutionFailure, ...]
    synthesis: WorkspaceSynthesisResult


def _answer_text(response: Any) -> str:
    if hasattr(response, "result") and hasattr(response.result, "answer"):
        return str(response.result.answer)
    if hasattr(response, "answer"):
        return str(response.answer)
    return str(response)


async def execute_workspace_query(
    connection,
    *,
    workspace: WorkspaceRecord,
    question: str,
    plan: WorkspaceQueryPlan,
    trace_id: str,
    ask_notebook: WorkspaceAskCallable,
    mode: str = "ask",
) -> WorkspaceExecutionResult:
    """Execute a workspace query plan and persist the workspace run lifecycle."""
    started = start_workspace_run(
        connection,
        workspace=workspace,
        trace_id=trace_id,
        query_text=question,
        plan=plan,
        mode=mode,
    )
    if not plan.selected_candidates:
        synthesis = synthesize_workspace_answer(question, [])
        completed = complete_workspace_run(
            connection,
            run_id=started.id,
            result=synthesis,
        )
        return WorkspaceExecutionResult(
            run=completed,
            plan=plan,
            answers=(),
            failures=(),
            synthesis=synthesis,
        )

    raw_responses = await asyncio.gather(
        *(ask_notebook(candidate, question) for candidate in plan.selected_candidates),
        return_exceptions=True,
    )

    answers: list[WorkspaceNotebookAnswer] = []
    failures: list[WorkspaceExecutionFailure] = []
    for candidate, response in zip(plan.selected_candidates, raw_responses, strict=False):
        if isinstance(response, Exception):
            failures.append(
                WorkspaceExecutionFailure(
                    notebook_id=candidate.notebook_id,
                    notebook_title=candidate.notebook_title,
                    error_type=type(response).__name__,
                    message=str(response),
                )
            )
            continue

        answers.append(
            WorkspaceNotebookAnswer(
                notebook_id=candidate.notebook_id,
                notebook_title=candidate.notebook_title,
                answer_text=_answer_text(response),
            )
        )

    synthesis = synthesize_workspace_answer(question, answers)
    completed = complete_workspace_run(
        connection,
        run_id=started.id,
        result=synthesis,
        status="failed" if failures else "completed",
    )
    return WorkspaceExecutionResult(
        run=completed,
        plan=plan,
        answers=tuple(answers),
        failures=tuple(failures),
        synthesis=synthesis,
    )


__all__ = [
    "WorkspaceExecutionFailure",
    "WorkspaceExecutionResult",
    "execute_workspace_query",
]
