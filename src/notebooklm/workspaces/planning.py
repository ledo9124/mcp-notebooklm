"""Planning helpers for workspace ask/compare orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from .indexing import WorkspaceCandidateRecord

_MAX_FANOUT = 3
_CLEAR_FTS_GAP = 1.0


@dataclass(frozen=True)
class WorkspaceQueryPlan:
    """Local execution plan derived from a workspace candidate shortlist."""

    workspace_id: str
    profile_id: str
    query_text: str
    mode: str
    selected_candidates: tuple[WorkspaceCandidateRecord, ...]
    reason: str
    candidate_count: int
    used_fallback: bool = False

    @property
    def selected_notebook_ids(self) -> tuple[str, ...]:
        return tuple(candidate.notebook_id for candidate in self.selected_candidates)


def _bounded_fanout(max_fanout: int) -> int:
    return min(_MAX_FANOUT, max(2, max_fanout))


def _rank_gap(
    first: WorkspaceCandidateRecord,
    second: WorkspaceCandidateRecord,
) -> float | None:
    if first.fts_rank is None or second.fts_rank is None:
        return None
    return second.fts_rank - first.fts_rank


def _fts_fanout_selection(
    candidates: tuple[WorkspaceCandidateRecord, ...],
    *,
    max_fanout: int,
) -> tuple[int, bool]:
    selected_count = min(len(candidates), _bounded_fanout(max_fanout))
    if selected_count < 3:
        return selected_count, False

    second = candidates[1]
    third = candidates[2]
    gap = _rank_gap(second, third)
    if (
        second.selection_reason == "fts"
        and third.selection_reason == "fts"
        and gap is not None
        and gap >= _CLEAR_FTS_GAP
    ):
        return 2, True

    return selected_count, False


def plan_workspace_query(
    *,
    query: str,
    candidates: list[WorkspaceCandidateRecord],
    max_fanout: int = _MAX_FANOUT,
) -> WorkspaceQueryPlan:
    """Choose a single-notebook route or a bounded fan-out from ranked candidates."""
    if not candidates:
        return WorkspaceQueryPlan(
            workspace_id="",
            profile_id="",
            query_text=query,
            mode="no_match",
            selected_candidates=(),
            reason="No workspace candidates were available for planning.",
            candidate_count=0,
            used_fallback=False,
        )

    ordered_candidates = tuple(candidates)
    first = ordered_candidates[0]
    workspace_id = first.workspace_id
    profile_id = first.profile_id
    used_fallback = all(candidate.selection_reason == "priority_fallback" for candidate in ordered_candidates)

    if len(ordered_candidates) == 1:
        return WorkspaceQueryPlan(
            workspace_id=workspace_id,
            profile_id=profile_id,
            query_text=query,
            mode="single_notebook",
            selected_candidates=(first,),
            reason="Only one notebook candidate remained after workspace selection.",
            candidate_count=1,
            used_fallback=used_fallback,
        )

    second = ordered_candidates[1]
    gap = _rank_gap(first, second)
    if (
        first.selection_reason == "fts"
        and second.selection_reason == "fts"
        and gap is not None
        and gap >= _CLEAR_FTS_GAP
    ):
        return WorkspaceQueryPlan(
            workspace_id=workspace_id,
            profile_id=profile_id,
            query_text=query,
            mode="single_notebook",
            selected_candidates=(first,),
            reason="The top notebook had a clear FTS lead over the next candidate.",
            candidate_count=len(ordered_candidates),
            used_fallback=False,
        )

    narrowed_by_gap = False
    if used_fallback:
        selected_count = min(len(ordered_candidates), _bounded_fanout(max_fanout))
        reason = (
            "FTS did not isolate a clear winner, so the plan fans out to the top workspace members by priority."
        )
    else:
        selected_count, narrowed_by_gap = _fts_fanout_selection(
            ordered_candidates,
            max_fanout=max_fanout,
        )
        reason = (
            "The top two notebooks remained plausible after FTS selection, but lower-ranked candidates trailed behind."
            if narrowed_by_gap
            else "Multiple notebooks remain plausible after FTS selection, so the plan fans out to the top candidates."
        )
    return WorkspaceQueryPlan(
        workspace_id=workspace_id,
        profile_id=profile_id,
        query_text=query,
        mode="fan_out",
        selected_candidates=ordered_candidates[:selected_count],
        reason=reason,
        candidate_count=len(ordered_candidates),
        used_fallback=used_fallback,
    )


__all__ = ["WorkspaceQueryPlan", "plan_workspace_query"]
