"""Shared workspace query helpers for CLI and host-callable tools."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Literal

from ..contracts import Diagnostics, Envelope, Intent, Route, Transport
from ..inbox import InboxScoringSignals, collect_inbox_scoring_context, score_inbox_candidate
from ..local.events import append_run_event
from ..local.repositories import InboxItemRecord, InboxItemRepository, WorkspaceRecord, WorkspaceRepository
from ..profiles.manager import ProfileManager
from .execution import (
    WorkspaceAskCallable,
    WorkspaceExecutionFailure,
    WorkspaceExecutionResult,
    execute_workspace_query,
)
from .planning import plan_workspace_query
from .synthesis import (
    WorkspaceContradictionRecord,
    WorkspaceNotebookAnswer,
    WorkspaceProvenanceRecord,
    detect_workspace_contradictions,
)
from .indexing import select_workspace_candidates

WorkspaceQueryMode = Literal["ask", "compare"]

_QUERY_REASON_BY_MODE: dict[WorkspaceQueryMode, str] = {
    "ask": "Use the local workspace index to select notebook candidates, then ask the selected notebooks live and synthesize the result.",
    "compare": "Use the local workspace index to select notebook candidates, then compare the live notebook answers without merging away differences.",
}


def _slugify_workspace_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or value.casefold()


def _resolve_profile_id(connection, explicit_profile_id: str | None) -> str:
    manager = ProfileManager(connection)
    if explicit_profile_id is not None:
        if manager.get_profile(explicit_profile_id) is None:
            raise LookupError(f"Profile not found in cache.db: {explicit_profile_id}")
        return explicit_profile_id

    active_profile = manager.get_active_profile()
    if active_profile is not None:
        return active_profile.profile_id

    profiles = manager.list_profiles()
    if len(profiles) == 1:
        return profiles[0].profile_id

    raise LookupError("No active local profile found in cache.db.")


def _resolve_workspace(
    connection,
    *,
    profile_id: str,
    name_or_slug: str,
) -> WorkspaceRecord:
    repository = WorkspaceRepository(connection)
    workspace = repository.get_by_slug(profile_id, _slugify_workspace_name(name_or_slug))
    if workspace is not None:
        return workspace

    matches = [
        row
        for row in repository.list_for_profile(profile_id)
        if row.name.casefold() == name_or_slug.casefold()
    ]
    if matches:
        return sorted(matches, key=lambda row: (row.slug, row.id))[0]
    raise LookupError(f"Workspace not found in cache.db: {name_or_slug}")


def _record_workspace_events(
    connection,
    *,
    trace_id: str,
    workspace_row: WorkspaceRecord,
    question: str,
    execution: WorkspaceExecutionResult,
    comparison: dict[str, object] | None = None,
) -> None:
    try:
        append_run_event(
            connection,
            trace_id,
            "workspace.resolve.completed",
            run_id=execution.run.id,
            payload={
                "workspace_id": workspace_row.id,
                "workspace_slug": workspace_row.slug,
                "mode": execution.run.mode,
                "query_text": question,
                "plan_mode": execution.plan.mode,
                "candidate_count": execution.plan.candidate_count,
                "selected_notebook_ids": [
                    candidate.notebook_id for candidate in execution.plan.selected_candidates
                ],
                "used_fallback": execution.plan.used_fallback,
            },
        )
        append_run_event(
            connection,
            trace_id,
            "workspace.query.completed",
            run_id=execution.run.id,
            payload=(
                {
                "workspace_id": workspace_row.id,
                "workspace_slug": workspace_row.slug,
                "mode": execution.run.mode,
                "status": execution.run.status,
                "answer_count": len(execution.answers),
                "failure_count": len(execution.failures),
                "provenance_count": len(execution.synthesis.provenance),
                }
                | (
                    {
                        "contradiction_count": len(
                            comparison.get("contradictions", [])
                            if isinstance(comparison.get("contradictions"), list)
                            else []
                        ),
                        "gap_fill_staged": int(
                            comparison.get("gap_fill_proposals", {}).get("staged", 0)
                            if isinstance(comparison.get("gap_fill_proposals"), dict)
                            else 0
                        ),
                        "gap_fill_existing": int(
                            comparison.get("gap_fill_proposals", {}).get(
                                "existing_inbox_count",
                                0,
                            )
                            if isinstance(comparison.get("gap_fill_proposals"), dict)
                            else 0
                        ),
                    }
                    if comparison is not None
                    else {}
                )
            ),
        )
    except Exception:
        return


@dataclass(frozen=True)
class WorkspaceQueryInvocation:
    """One completed workspace query invocation."""

    workspace: WorkspaceRecord
    question: str
    execution: WorkspaceExecutionResult
    comparison: dict[str, object] | None = None


def _workspace_payload(workspace_row: WorkspaceRecord) -> dict[str, object]:
    return {
        "id": workspace_row.id,
        "name": workspace_row.name,
        "slug": workspace_row.slug,
        "kind": workspace_row.kind,
        "description": workspace_row.description,
        "query_policy_json": workspace_row.query_policy_json,
        "approval_policy_json": workspace_row.approval_policy_json,
        "created_at": workspace_row.created_at,
        "updated_at": workspace_row.updated_at,
    }


def _workspace_plan_payload(plan) -> dict[str, object]:
    return {
        "mode": plan.mode,
        "reason": plan.reason,
        "candidate_count": plan.candidate_count,
        "used_fallback": plan.used_fallback,
        "selected_notebooks": [
            {
                "id": candidate.notebook_id,
                "title": candidate.notebook_title,
                "selection_reason": candidate.selection_reason,
                "member_priority": candidate.member_priority,
                "fts_rank": candidate.fts_rank,
            }
            for candidate in plan.selected_candidates
        ],
    }


def _workspace_answer_payload(answer: WorkspaceNotebookAnswer) -> dict[str, object]:
    return {
        "notebook_id": answer.notebook_id,
        "notebook_title": answer.notebook_title,
        "answer": answer.answer_text,
    }


def _workspace_failure_payload(failure: WorkspaceExecutionFailure) -> dict[str, object]:
    return {
        "notebook_id": failure.notebook_id,
        "notebook_title": failure.notebook_title,
        "error_type": failure.error_type,
        "message": failure.message,
    }


def _workspace_provenance_payload(item: WorkspaceProvenanceRecord) -> dict[str, object]:
    return {
        "notebook_id": item.notebook_id,
        "notebook_title": item.notebook_title,
        "contribution": item.contribution,
    }


def _workspace_run_payload(run) -> dict[str, object]:
    return {
        "id": run.id,
        "trace_id": run.trace_id,
        "status": run.status,
        "mode": run.mode,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
    }


def _workspace_contradiction_payload(
    contradiction: WorkspaceContradictionRecord,
) -> dict[str, object]:
    return {
        "id": contradiction.id,
        "topic": contradiction.topic,
        "shared_terms": list(contradiction.shared_terms),
        "explanation": contradiction.explanation,
        "left": {
            "notebook_id": contradiction.left_notebook_id,
            "notebook_title": contradiction.left_notebook_title,
            "position": contradiction.left_position,
        },
        "right": {
            "notebook_id": contradiction.right_notebook_id,
            "notebook_title": contradiction.right_notebook_title,
            "position": contradiction.right_position,
        },
    }


def _workspace_inbox_item_payload(item: InboxItemRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": item.id,
        "profile_id": item.profile_id,
        "notebook_id": item.notebook_id,
        "workspace_id": item.workspace_id,
        "origin": item.origin,
        "kind": item.kind,
        "state": item.state,
        "priority": item.priority,
        "novelty_score": item.novelty_score,
        "relevance_score": item.relevance_score,
        "trust_score": item.trust_score,
        "approval_required": item.approval_required,
        "title": item.title,
        "canonical_uri": item.canonical_uri,
        "snippet": item.snippet,
        "created_at": item.created_at,
        "decision_at": item.decision_at,
        "cluster_id": item.cluster_id,
    }
    if item.rationale_json:
        try:
            payload["rationale"] = json.loads(item.rationale_json)
        except json.JSONDecodeError:
            pass
    return payload


def _workspace_gap_fill_priority(relevance: float, trust: float) -> int:
    if relevance >= 0.75 or trust >= 0.8:
        return 4
    if relevance >= 0.6 or trust >= 0.65:
        return 3
    return 2


def _workspace_gap_fill_fingerprint(
    workspace_row: WorkspaceRecord,
    *,
    question: str,
    contradiction: WorkspaceContradictionRecord,
) -> str:
    encoded = json.dumps(
        {
            "question": " ".join(question.casefold().split()),
            "workspace_id": workspace_row.id,
            "contradiction_id": contradiction.id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _workspace_gap_fill_item_id(fingerprint: str) -> str:
    return f"inb_{fingerprint}"


def _workspace_gap_fill_uri(workspace_row: WorkspaceRecord, *, fingerprint: str) -> str:
    return f"workspace://gap-fill/{workspace_row.slug}/{fingerprint}"


def _workspace_gap_fill_title(contradiction: WorkspaceContradictionRecord) -> str:
    left_title = contradiction.left_notebook_title or contradiction.left_notebook_id
    right_title = contradiction.right_notebook_title or contradiction.right_notebook_id
    return f"Gap fill: clarify {contradiction.topic} between {left_title} and {right_title}"


def _workspace_gap_fill_snippet(
    question: str,
    contradiction: WorkspaceContradictionRecord,
) -> str:
    left_title = contradiction.left_notebook_title or contradiction.left_notebook_id
    right_title = contradiction.right_notebook_title or contradiction.right_notebook_id
    return (
        f'Workspace compare on "{question}" found conflicting positions about '
        f"{contradiction.topic}. {left_title}: {contradiction.left_position} "
        f"{right_title}: {contradiction.right_position}"
    )


def _workspace_gap_fill_rationale_json(
    *,
    workspace_row: WorkspaceRecord,
    question: str,
    execution: WorkspaceExecutionResult,
    contradiction: WorkspaceContradictionRecord,
    scores,
    scoring_context,
) -> str:
    payload = {
        "workspace_id": workspace_row.id,
        "workspace_slug": workspace_row.slug,
        "workspace_run_id": execution.run.id,
        "question": question,
        "contradiction": _workspace_contradiction_payload(contradiction),
        "scores": {
            "relevance": scores.relevance,
            "novelty": scores.novelty,
            "trust": scores.trust,
        },
        "scoring_context": scoring_context.to_dict(),
        "suggested_action": "review_gap_fill_proposal",
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _stage_workspace_compare_gap_fill_proposals(
    connection,
    *,
    workspace_row: WorkspaceRecord,
    question: str,
    execution: WorkspaceExecutionResult,
    contradictions: tuple[WorkspaceContradictionRecord, ...],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    item_repository = InboxItemRepository(connection)
    profile_items = item_repository.list_for_profile(workspace_row.profile_id)
    existing_canonical_uris = tuple(
        item.canonical_uri for item in profile_items if item.canonical_uri
    )
    existing_titles = tuple(item.title for item in profile_items if item.title)

    staged_items: list[InboxItemRecord] = []
    existing_items: list[InboxItemRecord] = []
    event_payloads: list[dict[str, object]] = []
    created_at = execution.run.ended_at or execution.run.started_at

    for contradiction in contradictions:
        fingerprint = _workspace_gap_fill_fingerprint(
            workspace_row,
            question=question,
            contradiction=contradiction,
        )
        item_id = _workspace_gap_fill_item_id(fingerprint)
        existing_item = item_repository.get(item_id)
        if existing_item is not None:
            existing_items.append(existing_item)
            continue

        title = _workspace_gap_fill_title(contradiction)
        canonical_uri = _workspace_gap_fill_uri(workspace_row, fingerprint=fingerprint)
        snippet = _workspace_gap_fill_snippet(question, contradiction)
        scoring_context = collect_inbox_scoring_context(
            connection,
            profile_id=workspace_row.profile_id,
            workspace_id=workspace_row.id,
            title=title,
            snippet=snippet,
            canonical_uri=canonical_uri,
        )
        scores = score_inbox_candidate(
            InboxScoringSignals(
                origin="agent_proposal",
                kind="report",
                title=title,
                snippet=snippet,
                canonical_uri=canonical_uri,
                context_text=question,
                existing_canonical_uris=existing_canonical_uris,
                existing_titles=existing_titles,
                parseable=False,
                context=scoring_context,
            )
        )
        item = InboxItemRecord(
            id=item_id,
            profile_id=workspace_row.profile_id,
            notebook_id=None,
            workspace_id=workspace_row.id,
            origin="agent_proposal",
            kind="report",
            state="pending",
            title=title,
            created_at=created_at,
            priority=_workspace_gap_fill_priority(scores.relevance, scores.trust),
            novelty_score=scores.novelty,
            relevance_score=scores.relevance,
            trust_score=scores.trust,
            approval_required=False,
            canonical_uri=canonical_uri,
            snippet=snippet,
            rationale_json=_workspace_gap_fill_rationale_json(
                workspace_row=workspace_row,
                question=question,
                execution=execution,
                contradiction=contradiction,
                scores=scores,
                scoring_context=scoring_context,
            ),
        )
        item_repository.upsert(item)
        staged_items.append(item)
        event_payloads.append(
            {
                "item_id": item.id,
                "workspace_id": workspace_row.id,
                "workspace_run_id": execution.run.id,
                "contradiction_id": contradiction.id,
                "topic": contradiction.topic,
            }
        )

    items = [*staged_items, *existing_items]
    message: str | None = None
    if staged_items:
        message = f"Staged {len(staged_items)} workspace gap-fill proposal(s) in inbox."
        if existing_items:
            message = (
                f"{message} {len(existing_items)} matching proposal(s) already existed."
            )
    elif existing_items:
        message = "Matching workspace gap-fill proposals already exist in inbox."

    return (
        {
            "staged": len(staged_items),
            "existing_inbox_count": len(existing_items),
            "inbox_item_ids": [item.id for item in items],
            "inbox_items": [_workspace_inbox_item_payload(item) for item in items],
            "message": message,
        },
        event_payloads,
    )


def build_workspace_compare_payload(
    execution: WorkspaceExecutionResult,
    *,
    contradictions: tuple[WorkspaceContradictionRecord, ...] | None = None,
    gap_fill_proposals: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return the compare-mode summary block used by CLI and host tools."""
    contradictions = contradictions or detect_workspace_contradictions(execution.answers)
    contradiction_payloads = [
        _workspace_contradiction_payload(item) for item in contradictions
    ]
    differences = [
        {
            "notebook_id": item.notebook_id,
            "notebook_title": item.notebook_title,
            "position": item.contribution,
        }
        for item in execution.synthesis.provenance
    ]
    gap_fill_staged = int((gap_fill_proposals or {}).get("staged", 0))
    gap_fill_existing = int((gap_fill_proposals or {}).get("existing_inbox_count", 0))
    if not differences:
        summary = (
            "No notebook answers were available for this workspace comparison."
            if not execution.failures
            else "No notebook answers were returned; review the notebook failures below."
        )
        overlap: list[str] = []
    elif len(differences) == 1:
        summary = (
            "Only one notebook answered, so compare mode fell back to a "
            "single-notebook perspective."
        )
        overlap = []
    else:
        unique_positions = {row["position"].casefold() for row in differences}
        if len(unique_positions) == 1:
            summary = "Workspace compare found strong overlap across the selected notebooks."
            overlap = ["Selected notebooks returned materially similar positions."]
        elif contradiction_payloads:
            if gap_fill_staged:
                summary = (
                    "Workspace compare found notebook contradictions and staged "
                    "gap-fill proposals in the inbox."
                )
            elif gap_fill_existing:
                summary = (
                    "Workspace compare found notebook contradictions; matching "
                    "gap-fill proposals already exist in the inbox."
                )
            else:
                summary = (
                    "Workspace compare found notebook contradictions that may "
                    "need a gap-fill follow-up."
                )
            overlap = [
                "Local compare mode keeps notebook-specific positions visible so "
                "contradictions can be reviewed without implying cross-notebook reasoning."
            ]
        else:
            summary = (
                "Workspace compare keeps the notebook-specific positions separate "
                "so differences and contradictions remain visible."
            )
            overlap = [
                "Local compare mode exposes notebook-specific positions directly "
                "instead of implying NotebookLM performed cross-notebook reasoning."
            ]

    return {
        "summary": summary,
        "single_notebook_fallback": len(differences) <= 1,
        "overlap": overlap,
        "differences": differences,
        "contradictions": contradiction_payloads,
        **({"gap_fill_proposals": gap_fill_proposals} if gap_fill_proposals is not None else {}),
    }


def _workspace_query_result_payload(invocation: WorkspaceQueryInvocation) -> dict[str, object]:
    execution = invocation.execution
    result: dict[str, object] = {
        "workspace": _workspace_payload(invocation.workspace),
        "question": invocation.question,
        "plan": _workspace_plan_payload(execution.plan),
        "workspace_run": _workspace_run_payload(execution.run),
        "answers": [_workspace_answer_payload(answer) for answer in execution.answers],
        "failures": [_workspace_failure_payload(failure) for failure in execution.failures],
    }
    if execution.run.mode == "compare":
        result["comparison"] = invocation.comparison or build_workspace_compare_payload(execution)
        return result

    result["answer"] = execution.synthesis.answer
    result["provenance"] = [
        _workspace_provenance_payload(item) for item in execution.synthesis.provenance
    ]
    return result


async def invoke_workspace_query(
    connection,
    *,
    profile_id: str | None,
    name_or_slug: str,
    question: str,
    trace_id: str,
    ask_notebook: WorkspaceAskCallable,
    mode: WorkspaceQueryMode = "ask",
) -> WorkspaceQueryInvocation:
    """Resolve, plan, execute, and persist one workspace query flow."""
    if mode not in _QUERY_REASON_BY_MODE:
        raise ValueError(f"Unsupported workspace query mode: {mode}")

    resolved_profile_id = _resolve_profile_id(connection, profile_id)
    workspace_row = _resolve_workspace(
        connection,
        profile_id=resolved_profile_id,
        name_or_slug=name_or_slug,
    )
    candidates = select_workspace_candidates(
        connection,
        workspace=workspace_row,
        query=question,
    )
    plan = plan_workspace_query(query=question, candidates=candidates)
    execution = await execute_workspace_query(
        connection,
        workspace=workspace_row,
        question=question,
        plan=plan,
        trace_id=trace_id,
        ask_notebook=ask_notebook,
        mode=mode,
    )
    comparison: dict[str, object] | None = None
    inbox_event_payloads: list[dict[str, object]] = []
    if mode == "compare":
        contradictions = detect_workspace_contradictions(execution.answers)
        gap_fill_proposals, inbox_event_payloads = _stage_workspace_compare_gap_fill_proposals(
            connection,
            workspace_row=workspace_row,
            question=question,
            execution=execution,
            contradictions=contradictions,
        )
        comparison = build_workspace_compare_payload(
            execution,
            contradictions=contradictions,
            gap_fill_proposals=gap_fill_proposals,
        )
    _record_workspace_events(
        connection,
        trace_id=trace_id,
        workspace_row=workspace_row,
        question=question,
        execution=execution,
        comparison=comparison,
    )
    for payload in inbox_event_payloads:
        try:
            append_run_event(
                connection,
                trace_id,
                "inbox.item.created",
                run_id=execution.run.id,
                payload=payload,
            )
        except Exception:
            continue
    return WorkspaceQueryInvocation(
        workspace=workspace_row,
        question=question,
        execution=execution,
        comparison=comparison,
    )


def build_workspace_query_envelope(
    *,
    trace_id: str,
    elapsed_ms: int,
    invocation: WorkspaceQueryInvocation,
    intent: Intent,
    route_mode: str,
    transport_kind: Literal["httpx", "local"] = "local",
) -> dict[str, object]:
    """Return the canonical JSON envelope for one workspace ask/compare result."""
    execution = invocation.execution
    return Envelope(
        ok=not execution.failures,
        trace_id=trace_id,
        run_id=execution.run.id,
        route=Route(
            intent=intent,
            mode=route_mode,
            notebook_id=None,
            profile_id=invocation.workspace.profile_id,
            source_of_truth="mixed",
            cache_mode="network",
            reason=_QUERY_REASON_BY_MODE[execution.run.mode],
            transport=Transport(kind=transport_kind),
        ),
        freshness=None,
        result=_workspace_query_result_payload(invocation),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


__all__ = [
    "WorkspaceQueryInvocation",
    "WorkspaceQueryMode",
    "build_workspace_compare_payload",
    "build_workspace_query_envelope",
    "invoke_workspace_query",
]
