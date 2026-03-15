"""Unit tests for deterministic inbox scoring heuristics."""

from __future__ import annotations

from notebooklm.inbox import (
    InboxScoringContext,
    InboxScoringSignals,
    collect_inbox_scoring_context,
    score_inbox_candidate,
)
from notebooklm.local.db import connect_db
from notebooklm.local.repositories import (
    InboxItemRecord,
    InboxItemRepository,
    NotebookRecord,
    NotebookRepository,
    QueryRunRecord,
    QueryRunRepository,
    WorkspaceMemberRecord,
    WorkspaceMemberRepository,
    WorkspaceRecord,
    WorkspaceRepository,
    WorkspaceRunRecord,
    WorkspaceRunRepository,
)


def _insert_profile(connection, profile_id: str) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO profiles (
                profile_id,
                display_name,
                account_email,
                is_default,
                storage_state_path,
                browser_profile_path,
                created_at,
                updated_at,
                last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                f"Profile {profile_id}",
                f"{profile_id}@example.com",
                1,
                f"/tmp/{profile_id}/storage_state.json",
                f"/tmp/{profile_id}/browser_profile",
                "2026-03-15T00:00:00Z",
                "2026-03-15T00:00:00Z",
                None,
            ),
        )


def _seed_notebook(connection, profile_id: str, notebook_id: str = "nb_1") -> None:
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id=notebook_id,
            profile_id=profile_id,
            title="Research Notebook",
            normalized_title="research notebook",
        )
    )


def test_score_inbox_candidate_boosts_strong_research_match_and_trust():
    score = score_inbox_candidate(
        InboxScoringSignals(
            origin="deep_research",
            kind="source",
            title="NotebookLM safety guide",
            snippet="Safe import workflow for NotebookLM notebooks.",
            canonical_uri="https://docs.google.com/document/d/guide/edit",
            context_text="NotebookLM safety guide",
            cited_by_research=True,
            repeated_agreement_count=2,
            parseable=True,
        )
    )

    assert score.relevance == 0.95
    assert score.novelty == 0.85
    assert score.trust == 0.98


def test_score_inbox_candidate_penalizes_existing_resync_items_for_novelty():
    score = score_inbox_candidate(
        InboxScoringSignals(
            origin="change_radar",
            kind="resync",
            title="Quarterly plan",
            snippet="Drive-backed source looks newer than the cache.",
            canonical_uri="https://docs.google.com/document/d/doc-1/edit",
            context_text="Research notebook",
            existing_canonical_uris=("https://docs.google.com/document/d/doc-1/edit",),
            existing_titles=("Quarterly plan",),
            parseable=True,
        )
    )

    assert score.relevance == 0.75
    assert score.novelty == 0.2
    assert score.trust == 0.9


def test_score_inbox_candidate_keeps_unknown_manual_item_low_trust():
    score = score_inbox_candidate(
        InboxScoringSignals(
            origin="manual",
            kind="source",
            title="Loose note",
            snippet=None,
            canonical_uri=None,
            context_text=None,
            parseable=False,
        )
    )

    assert score.relevance == 0.45
    assert score.novelty == 0.85
    assert score.trust == 0.45


def test_score_inbox_candidate_uses_contextual_matches_and_prior_acceptance():
    score = score_inbox_candidate(
        InboxScoringSignals(
            origin="manual",
            kind="source",
            title="Pricing renewal notes",
            snippet="Enterprise buyers mention renewal pressure.",
            canonical_uri="https://example.com/renewals",
            parseable=True,
            context=InboxScoringContext(
                workspace_match_count=2,
                query_history_match_count=1,
                prior_approved_count=1,
            ),
        )
    )

    assert score.relevance == 0.69
    assert score.novelty == 0.79
    assert score.trust == 0.7


def test_collect_inbox_scoring_context_reads_workspace_query_and_prior_decisions(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "default")
        _seed_notebook(connection, "default", notebook_id="nb_1")
        WorkspaceRepository(connection).upsert(
            WorkspaceRecord(
                id="ws_market",
                profile_id="default",
                name="Market Intel",
                slug="market-intel",
                kind="static",
                created_at="2026-03-15T05:00:00Z",
                updated_at="2026-03-15T05:00:00Z",
            )
        )
        WorkspaceMemberRepository(connection).upsert(
            WorkspaceMemberRecord(
                id="wsm_market_nb_1",
                workspace_id="ws_market",
                notebook_id="nb_1",
                priority=9,
                added_at="2026-03-15T05:00:00Z",
            )
        )
        WorkspaceRunRepository(connection).upsert(
            WorkspaceRunRecord(
                id="wr_1",
                trace_id="trc_wr_1",
                profile_id="default",
                started_at="2026-03-15T05:05:00Z",
                ended_at="2026-03-15T05:05:03Z",
                status="completed",
                workspace_id="ws_market",
                mode="compare",
                query_text="AI research roadmap",
                selected_notebooks_json='["nb_1"]',
                plan_json='{"mode":"compare"}',
                result_json='{"status":"completed"}',
            )
        )
        QueryRunRepository(connection).upsert(
            QueryRunRecord(
                id="qr_1",
                trace_id="trc_qr_1",
                profile_id="default",
                notebook_id="nb_1",
                intent="ask",
                mode="answer",
                prompt_text="AI research roadmap",
                prompt_hash="hash_qr_1",
                cache_policy="smart",
                route_reason="remote query",
                source_of_truth="remote_http",
                started_at="2026-03-15T05:10:00Z",
                ended_at="2026-03-15T05:10:02Z",
                status="completed",
            )
        )
        InboxItemRepository(connection).upsert(
            InboxItemRecord(
                id="inb_approved",
                profile_id="default",
                notebook_id="nb_1",
                origin="deep_research",
                kind="source",
                state="approved",
                title="Archived source",
                created_at="2026-03-15T05:11:00Z",
                canonical_uri="https://example.com/roadmap-launch",
            )
        )
        InboxItemRepository(connection).upsert(
            InboxItemRecord(
                id="inb_rejected",
                profile_id="default",
                notebook_id="nb_1",
                origin="deep_research",
                kind="source",
                state="rejected",
                title="Roadmap launch update",
                created_at="2026-03-15T05:12:00Z",
                canonical_uri="https://example.com/another-roadmap",
            )
        )

        context = collect_inbox_scoring_context(
            connection,
            profile_id="default",
            notebook_id="nb_1",
            title="Roadmap launch update",
            snippet="AI research notes",
            canonical_uri="https://example.com/roadmap-launch",
        )

    assert context.to_dict() == {
        "workspace_match_count": 1,
        "query_history_match_count": 1,
        "prior_approved_count": 1,
        "prior_rejected_count": 1,
    }
