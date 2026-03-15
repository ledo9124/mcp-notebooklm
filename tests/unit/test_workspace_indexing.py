"""Unit tests for local workspace index rebuild helpers."""

from __future__ import annotations

import json

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import (
    LeaseRepository,
    NotebookRecord,
    NotebookRepository,
    QueryResultRecord,
    QueryResultRepository,
    QueryRunRecord,
    QueryRunRepository,
    SourceRecord,
    SourceRepository,
    WorkspaceIndexEntryRepository,
    WorkspaceMemberRecord,
    WorkspaceMemberRepository,
    WorkspaceRecord,
    WorkspaceRepository,
)
from notebooklm.profiles.manager import ProfileManager
from notebooklm.workspaces import build_workspace_index, search_workspace_index, select_workspace_candidates


def _seed_profile(connection) -> None:
    manager = ProfileManager(connection)
    if manager.get_profile("default") is not None:
        return
    manager.create_profile(
        profile_id="default",
        display_name="Default",
        account_email="default@example.com",
        storage_state_path="/tmp/default/storage_state.json",
        browser_profile_path="/tmp/default/browser_profile",
        is_default=True,
    )


def test_build_workspace_index_populates_materialized_rows_and_fts_hits(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(connection)
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
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id="nb_pricing",
                profile_id="default",
                title="Pricing Notebook",
                normalized_title="pricing notebook",
                summary_preview="Quarterly renewal plan and discount strategy",
            )
        )
        WorkspaceMemberRepository(connection).upsert(
            WorkspaceMemberRecord(
                id="wsm_pricing",
                workspace_id="ws_market",
                notebook_id="nb_pricing",
                priority=5,
                tags_json='["pricing","renewal"]',
                added_at="2026-03-15T05:01:00Z",
            )
        )
        SourceRepository(connection).upsert(
            SourceRecord(
                source_id="src_renewal",
                notebook_id="nb_pricing",
                profile_id="default",
                source_type="web_page",
                status="ready",
                title="Renewal Deck",
                content_preview="Discount ladder notes and renewal obligations",
            )
        )
        QueryRunRepository(connection).upsert(
            QueryRunRecord(
                id="qr_pricing_1",
                trace_id="trc_pricing_1",
                profile_id="default",
                notebook_id="nb_pricing",
                intent="ask",
                mode="answer",
                prompt_text="What changed in renewal obligations?",
                prompt_hash="hash_pricing_1",
                cache_policy="smart",
                route_reason="remote query",
                source_of_truth="remote_http",
                started_at="2026-03-15T05:02:00Z",
                ended_at="2026-03-15T05:02:02Z",
                status="completed",
            )
        )
        QueryResultRepository(connection).upsert(
            QueryResultRecord(
                query_run_id="qr_pricing_1",
                result_type="answer",
                answer_text="Renewal obligations tightened in the latest quarter.",
                citations_json='["citation-1"]',
                result_json='{"summary":"renewal obligations tightened"}',
                created_at="2026-03-15T05:02:02Z",
            )
        )

        workspace = WorkspaceRepository(connection).get("ws_market")
        assert workspace is not None

        result = build_workspace_index(
            connection,
            workspace=workspace,
            now="2026-03-15T05:10:00Z",
        )
        entries = WorkspaceIndexEntryRepository(connection).list_for_workspace("ws_market")
        hits = search_workspace_index(connection, workspace=workspace, query="renewal", limit=5)
        leases = LeaseRepository(connection).list_for_scope("workspace", "ws_market")

    assert result.workspace_id == "ws_market"
    assert result.profile_id == "default"
    assert result.entry_count == 1
    assert result.notebook_ids == ("nb_pricing",)
    assert result.lease_id.startswith("lease_")
    assert len(entries) == 1
    assert entries[0].notebook_title == "Pricing Notebook"
    assert entries[0].notebook_summary == "Quarterly renewal plan and discount strategy"
    assert entries[0].source_titles_text == "Renewal Deck"
    assert "renewal obligations" in (entries[0].source_snippets_text or "")
    assert "What changed in renewal obligations?" in (entries[0].recent_query_text or "")
    assert json.loads(entries[0].tags_json or "[]") == ["pricing", "renewal"]
    assert [hit.notebook_id for hit in hits] == ["nb_pricing"]
    assert hits[0].notebook_title == "Pricing Notebook"
    assert leases == []


def test_select_workspace_candidates_sanitizes_question_and_returns_ranked_hits(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(connection)
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
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id="nb_pricing",
                profile_id="default",
                title="Pricing Notebook",
                normalized_title="pricing notebook",
                summary_preview="Quarterly renewal plan and discount strategy",
            )
        )
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id="nb_competitor",
                profile_id="default",
                title="Competitor Notebook",
                normalized_title="competitor notebook",
                summary_preview="Competitor pricing pressure and field reactions",
            )
        )
        WorkspaceMemberRepository(connection).upsert(
            WorkspaceMemberRecord(
                id="wsm_pricing",
                workspace_id="ws_market",
                notebook_id="nb_pricing",
                priority=9,
                tags_json='["pricing","renewal"]',
                added_at="2026-03-15T05:01:00Z",
            )
        )
        WorkspaceMemberRepository(connection).upsert(
            WorkspaceMemberRecord(
                id="wsm_competitor",
                workspace_id="ws_market",
                notebook_id="nb_competitor",
                priority=3,
                tags_json='["competitors","pricing"]',
                added_at="2026-03-15T05:01:30Z",
            )
        )
        SourceRepository(connection).upsert(
            SourceRecord(
                source_id="src_renewal",
                notebook_id="nb_pricing",
                profile_id="default",
                source_type="web_page",
                status="ready",
                title="Renewal Deck",
                content_preview="Renewal obligations tightened and discount ladders changed",
            )
        )
        SourceRepository(connection).upsert(
            SourceRecord(
                source_id="src_competitor",
                notebook_id="nb_competitor",
                profile_id="default",
                source_type="web_page",
                status="ready",
                title="Competitor Matrix",
                content_preview="Competitor pricing pressure by segment",
            )
        )
        QueryRunRepository(connection).upsert(
            QueryRunRecord(
                id="qr_pricing_1",
                trace_id="trc_pricing_1",
                profile_id="default",
                notebook_id="nb_pricing",
                intent="ask",
                mode="answer",
                prompt_text="What changed in renewal obligations?",
                prompt_hash="hash_pricing_1",
                cache_policy="smart",
                route_reason="remote query",
                source_of_truth="remote_http",
                started_at="2026-03-15T05:02:00Z",
                ended_at="2026-03-15T05:02:02Z",
                status="completed",
            )
        )
        QueryResultRepository(connection).upsert(
            QueryResultRecord(
                query_run_id="qr_pricing_1",
                result_type="answer",
                answer_text="Renewal obligations tightened in the latest quarter.",
                citations_json='["citation-1"]',
                result_json='{"summary":"renewal obligations tightened"}',
                created_at="2026-03-15T05:02:02Z",
            )
        )

        workspace = WorkspaceRepository(connection).get("ws_market")
        assert workspace is not None
        build_workspace_index(connection, workspace=workspace, now="2026-03-15T05:10:00Z")

        candidates = select_workspace_candidates(
            connection,
            workspace=workspace,
            query="What's changed in renewal obligations?",
            limit=2,
        )

    assert [candidate.notebook_id for candidate in candidates] == ["nb_pricing"]
    assert candidates[0].selection_reason == "fts"
    assert candidates[0].member_priority == 9
    assert candidates[0].tags == ("pricing", "renewal")
    assert candidates[0].fts_rank is not None


def test_select_workspace_candidates_falls_back_to_priority_when_fts_misses(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _seed_profile(connection)
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
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id="nb_pricing",
                profile_id="default",
                title="Pricing Notebook",
                normalized_title="pricing notebook",
                summary_preview="Quarterly renewal plan and discount strategy",
            )
        )
        NotebookRepository(connection).upsert(
            NotebookRecord(
                notebook_id="nb_competitor",
                profile_id="default",
                title="Competitor Notebook",
                normalized_title="competitor notebook",
                summary_preview="Competitor pricing pressure and field reactions",
            )
        )
        WorkspaceMemberRepository(connection).upsert(
            WorkspaceMemberRecord(
                id="wsm_pricing",
                workspace_id="ws_market",
                notebook_id="nb_pricing",
                priority=9,
                tags_json='["pricing","renewal"]',
                added_at="2026-03-15T05:01:00Z",
            )
        )
        WorkspaceMemberRepository(connection).upsert(
            WorkspaceMemberRecord(
                id="wsm_competitor",
                workspace_id="ws_market",
                notebook_id="nb_competitor",
                priority=3,
                tags_json='["competitors","pricing"]',
                added_at="2026-03-15T05:01:30Z",
            )
        )
        SourceRepository(connection).upsert(
            SourceRecord(
                source_id="src_renewal",
                notebook_id="nb_pricing",
                profile_id="default",
                source_type="web_page",
                status="ready",
                title="Renewal Deck",
                content_preview="Renewal obligations tightened and discount ladders changed",
            )
        )
        SourceRepository(connection).upsert(
            SourceRecord(
                source_id="src_competitor",
                notebook_id="nb_competitor",
                profile_id="default",
                source_type="web_page",
                status="ready",
                title="Competitor Matrix",
                content_preview="Competitor pricing pressure by segment",
            )
        )

        workspace = WorkspaceRepository(connection).get("ws_market")
        assert workspace is not None
        build_workspace_index(connection, workspace=workspace, now="2026-03-15T05:10:00Z")

        candidates = select_workspace_candidates(
            connection,
            workspace=workspace,
            query="unmatched signal",
            limit=2,
        )

    assert [candidate.notebook_id for candidate in candidates] == ["nb_pricing", "nb_competitor"]
    assert all(candidate.selection_reason == "priority_fallback" for candidate in candidates)
    assert all(candidate.fts_rank is None for candidate in candidates)
