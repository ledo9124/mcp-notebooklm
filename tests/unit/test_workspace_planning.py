"""Unit tests for local workspace planning helpers."""

from notebooklm.workspaces import WorkspaceCandidateRecord, WorkspaceQueryPlan, plan_workspace_query


def _candidate(
    notebook_id: str,
    *,
    member_priority: int,
    fts_rank: float | None,
    selection_reason: str = "fts",
) -> WorkspaceCandidateRecord:
    return WorkspaceCandidateRecord(
        entry_id=f"wsi_{notebook_id}",
        workspace_id="ws_market",
        profile_id="default",
        notebook_id=notebook_id,
        notebook_title=notebook_id.replace("_", " ").title(),
        notebook_summary=f"Summary for {notebook_id}",
        member_priority=member_priority,
        tags=("pricing",),
        recent_query_text=None,
        fts_rank=fts_rank,
        selection_reason=selection_reason,
    )


def test_plan_workspace_query_returns_no_match_when_candidates_empty():
    plan = plan_workspace_query(query="pricing changes", candidates=[])

    assert isinstance(plan, WorkspaceQueryPlan)
    assert plan.mode == "no_match"
    assert plan.selected_notebook_ids == ()
    assert plan.candidate_count == 0


def test_plan_workspace_query_routes_single_when_only_one_candidate():
    plan = plan_workspace_query(
        query="renewal obligations",
        candidates=[_candidate("nb_pricing", member_priority=9, fts_rank=-2.4)],
    )

    assert plan.mode == "single_notebook"
    assert plan.selected_notebook_ids == ("nb_pricing",)
    assert plan.used_fallback is False


def test_plan_workspace_query_routes_single_when_top_fts_gap_is_clear():
    plan = plan_workspace_query(
        query="renewal obligations",
        candidates=[
            _candidate("nb_pricing", member_priority=9, fts_rank=-2.5),
            _candidate("nb_competitor", member_priority=5, fts_rank=-0.8),
        ],
    )

    assert plan.mode == "single_notebook"
    assert plan.selected_notebook_ids == ("nb_pricing",)
    assert "clear FTS lead" in plan.reason


def test_plan_workspace_query_fans_out_top_three_when_multiple_candidates_plausible():
    plan = plan_workspace_query(
        query="pricing pressure",
        candidates=[
            _candidate("nb_pricing", member_priority=9, fts_rank=-1.2),
            _candidate("nb_competitor", member_priority=5, fts_rank=-0.9),
            _candidate("nb_support", member_priority=2, fts_rank=-0.8),
            _candidate("nb_field", member_priority=1, fts_rank=-0.7),
        ],
    )

    assert plan.mode == "fan_out"
    assert plan.selected_notebook_ids == ("nb_pricing", "nb_competitor", "nb_support")
    assert plan.used_fallback is False


def test_plan_workspace_query_limits_fts_fanout_when_third_candidate_trails():
    plan = plan_workspace_query(
        query="pricing pressure",
        candidates=[
            _candidate("nb_pricing", member_priority=9, fts_rank=-1.2),
            _candidate("nb_competitor", member_priority=5, fts_rank=-0.9),
            _candidate("nb_support", member_priority=2, fts_rank=0.4),
            _candidate("nb_field", member_priority=1, fts_rank=0.5),
        ],
    )

    assert plan.mode == "fan_out"
    assert plan.selected_notebook_ids == ("nb_pricing", "nb_competitor")
    assert "trailed behind" in plan.reason
    assert plan.used_fallback is False


def test_plan_workspace_query_fans_out_priority_fallback_candidates():
    plan = plan_workspace_query(
        query="unknown signal",
        candidates=[
            _candidate(
                "nb_pricing",
                member_priority=9,
                fts_rank=None,
                selection_reason="priority_fallback",
            ),
            _candidate(
                "nb_competitor",
                member_priority=5,
                fts_rank=None,
                selection_reason="priority_fallback",
            ),
            _candidate(
                "nb_support",
                member_priority=2,
                fts_rank=None,
                selection_reason="priority_fallback",
            ),
        ],
    )

    assert plan.mode == "fan_out"
    assert plan.selected_notebook_ids == ("nb_pricing", "nb_competitor", "nb_support")
    assert plan.used_fallback is True
    assert "priority" in plan.reason
