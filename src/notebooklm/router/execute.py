"""Execution planning and dispatch helpers for experimental NL routing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from notebooklm.contracts import Intent

from .classify import IntentClassification
from .resolve import NotebookResolution

WorkflowHandler = Callable[["AgentExecutionPlan"], Awaitable[Any]]


@dataclass(frozen=True)
class AgentExecutionPlan:
    """Pure execution plan for one routed natural-language request."""

    intent: Intent
    command_name: str
    mode: str
    request_text: str
    notebook_id: str | None
    resolution_source: str
    requires_notebook: bool
    waitable: bool
    rationale: str
    arguments: dict[str, object]


def build_execution_plan(
    *,
    request: str,
    classification: IntentClassification,
    resolution: NotebookResolution,
    allow_partial_resolution: bool = False,
) -> AgentExecutionPlan:
    """Map a routed request onto the canonical workflow/command target.

    `allow_partial_resolution=True` is reserved for diagnostics such as
    `route --dry-run`, where we still want to preview the target command/mode
    even if notebook resolution is not yet executable.
    """
    normalized_request = _normalize_text(request)
    if not normalized_request:
        raise ValueError("Request must not be blank.")
    if not allow_partial_resolution and resolution.status in {"ambiguous", "unresolved"}:
        raise ValueError(f"Cannot dispatch with {resolution.status} notebook resolution: {resolution.rationale}")

    if classification.intent is Intent.LOCAL_METADATA:
        plan = _plan_local_metadata(request, normalized_request, resolution)
    elif classification.intent is Intent.REMOTE_METADATA:
        plan = _plan_remote_metadata(request, normalized_request, resolution)
    elif classification.intent is Intent.QUERY:
        plan = _plan_query(request, normalized_request, resolution)
    elif classification.intent is Intent.GENERATION:
        plan = _plan_generation(request, normalized_request, resolution)
    elif classification.intent is Intent.RESEARCH:
        plan = _plan_research(request, normalized_request, resolution)
    else:
        raise ValueError(f"Unsupported router intent: {classification.intent.value}")

    if not allow_partial_resolution and plan.requires_notebook and plan.notebook_id is None:
        raise ValueError(
            f"Execution plan '{plan.command_name}' requires a resolved notebook target."
        )

    return plan


async def dispatch_execution(
    plan: AgentExecutionPlan,
    *,
    handlers: Mapping[str, WorkflowHandler],
) -> Any:
    """Dispatch one execution plan through the supplied handler registry."""
    handler = handlers.get(plan.command_name)
    if handler is None:
        raise KeyError(f"No execution handler registered for '{plan.command_name}'.")
    return await handler(plan)


def _plan_local_metadata(
    request: str,
    normalized_request: str,
    resolution: NotebookResolution,
) -> AgentExecutionPlan:
    if _contains_phrase(normalized_request, "list notebooks"):
        return AgentExecutionPlan(
            intent=Intent.LOCAL_METADATA,
            command_name="notebook.list",
            mode="notebook_list",
            request_text=request,
            notebook_id=None,
            resolution_source=resolution.source,
            requires_notebook=False,
            waitable=False,
            rationale="Local metadata request maps to the cached notebook listing workflow.",
            arguments={"request": request},
        )
    if _contains_phrase(normalized_request, "list sources"):
        return AgentExecutionPlan(
            intent=Intent.LOCAL_METADATA,
            command_name="source.list",
            mode="source_list",
            request_text=request,
            notebook_id=resolution.notebook_id,
            resolution_source=resolution.source,
            requires_notebook=True,
            waitable=False,
            rationale="Local metadata request maps to the cached source listing workflow.",
            arguments={"request": request},
        )
    return AgentExecutionPlan(
        intent=Intent.LOCAL_METADATA,
        command_name="metadata.query",
        mode="metadata_query",
        request_text=request,
        notebook_id=resolution.notebook_id,
        resolution_source=resolution.source,
        requires_notebook=False,
        waitable=False,
        rationale="Local metadata request needs an indexed metadata query rather than a fixed leaf command.",
        arguments={"request": request},
    )


def _plan_remote_metadata(
    request: str,
    normalized_request: str,
    resolution: NotebookResolution,
) -> AgentExecutionPlan:
    sync_all = resolution.notebook_id is None or "notebooks" in normalized_request
    rationale = "Remote metadata request maps to notebook sync/refresh work."
    if "stale" in normalized_request:
        rationale = "Remote metadata request mentions stale content, so the sync workflow is the correct refresh path."
    return AgentExecutionPlan(
        intent=Intent.REMOTE_METADATA,
        command_name="sync.notebooks",
        mode="sync_notebooks",
        request_text=request,
        notebook_id=None if sync_all else resolution.notebook_id,
        resolution_source=resolution.source,
        requires_notebook=False,
        waitable=False,
        rationale=rationale,
        arguments={
            "request": request,
            "sync_all": sync_all,
            "notebook_id": None if sync_all else resolution.notebook_id,
        },
    )


def _plan_query(
    request: str,
    normalized_request: str,
    resolution: NotebookResolution,
) -> AgentExecutionPlan:
    if "overview" in normalized_request and "audio overview" not in normalized_request:
        return AgentExecutionPlan(
            intent=Intent.QUERY,
            command_name="overview",
            mode="overview",
            request_text=request,
            notebook_id=resolution.notebook_id,
            resolution_source=resolution.source,
            requires_notebook=True,
            waitable=False,
            rationale="QUERY request asks for an overview, so it maps to the overview workflow instead of ask.",
            arguments={"request": request},
        )
    return AgentExecutionPlan(
        intent=Intent.QUERY,
        command_name="ask",
        mode="ask",
        request_text=request,
        notebook_id=resolution.notebook_id,
        resolution_source=resolution.source,
        requires_notebook=True,
        waitable=False,
        rationale="QUERY request maps to the grounded ask workflow.",
        arguments={"question": request},
    )


def _plan_generation(
    request: str,
    normalized_request: str,
    resolution: NotebookResolution,
) -> AgentExecutionPlan:
    if "study guide" in normalized_request:
        return AgentExecutionPlan(
            intent=Intent.GENERATION,
            command_name="study-guide",
            mode="study_guide",
            request_text=request,
            notebook_id=resolution.notebook_id,
            resolution_source=resolution.source,
            requires_notebook=True,
            waitable=True,
            rationale="GENERATION request explicitly asks for a study guide artifact.",
            arguments={"description": request, "report_format": "study_guide"},
        )
    if "audio overview" in normalized_request or "audio" in normalized_request or "podcast" in normalized_request:
        return AgentExecutionPlan(
            intent=Intent.GENERATION,
            command_name="audio",
            mode="audio",
            request_text=request,
            notebook_id=resolution.notebook_id,
            resolution_source=resolution.source,
            requires_notebook=True,
            waitable=True,
            rationale="GENERATION request asks for audio output, so it maps to the audio workflow.",
            arguments={"description": request},
        )
    return AgentExecutionPlan(
        intent=Intent.GENERATION,
        command_name="summarize",
        mode="briefing_doc",
        request_text=request,
        notebook_id=resolution.notebook_id,
        resolution_source=resolution.source,
        requires_notebook=True,
        waitable=True,
        rationale="GENERATION request defaults to the briefing-doc summarize workflow.",
        arguments={"description": request, "report_format": "briefing_doc"},
    )


def _plan_research(
    request: str,
    normalized_request: str,
    resolution: NotebookResolution,
) -> AgentExecutionPlan:
    if any(term in normalized_request for term in ("wait", "poll", "status")):
        return AgentExecutionPlan(
            intent=Intent.RESEARCH,
            command_name="research.wait",
            mode="research_wait",
            request_text=request,
            notebook_id=resolution.notebook_id,
            resolution_source=resolution.source,
            requires_notebook=False,
            waitable=True,
            rationale="RESEARCH request asks to poll or wait on an existing research run.",
            arguments={"request": request},
        )
    if "import" in normalized_request:
        return AgentExecutionPlan(
            intent=Intent.RESEARCH,
            command_name="research.import",
            mode="research_import",
            request_text=request,
            notebook_id=resolution.notebook_id,
            resolution_source=resolution.source,
            requires_notebook=False,
            waitable=False,
            rationale="RESEARCH request asks to import discovered results.",
            arguments={"request": request},
        )

    search_source = "drive" if "drive" in normalized_request else "web"
    research_mode = "deep" if "deep" in normalized_request else "fast"
    return AgentExecutionPlan(
        intent=Intent.RESEARCH,
        command_name="research.start",
        mode=research_mode,
        request_text=request,
        notebook_id=resolution.notebook_id,
        resolution_source=resolution.source,
        requires_notebook=True,
        waitable=False,
        rationale=f"RESEARCH request maps to research.start in {research_mode} mode over {search_source}.",
        arguments={
            "query": request,
            "mode": research_mode,
            "search_source": search_source,
        },
    )


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {normalized_text} "


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


__all__ = ["AgentExecutionPlan", "build_execution_plan", "dispatch_execution"]
