"""Unit tests for the local core-metadata repositories."""

from __future__ import annotations

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import (
    ArtifactRecord,
    ArtifactRepository,
    DoctorRunRecord,
    DoctorRunRepository,
    LeaseRecord,
    LeaseRepository,
    NotebookRecord,
    NotebookRepository,
    ResearchRunRecord,
    ResearchRunRepository,
    SourceRecord,
    SourceRepository,
    WorkspaceIndexEntryRecord,
    WorkspaceIndexEntryRepository,
    WorkspaceMemberRecord,
    WorkspaceMemberRepository,
    WorkspaceRecord,
    WorkspaceRepository,
    WorkspaceRuleRecord,
    WorkspaceRuleRepository,
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
                0,
                f"/tmp/{profile_id}/storage_state.json",
                f"/tmp/{profile_id}/browser_profile",
                "2026-03-15T00:00:00Z",
                "2026-03-15T00:00:00Z",
                None,
            ),
        )


def _seed_notebook(connection, profile_id: str, notebook_id: str = "nb_1") -> NotebookRecord:
    record = NotebookRecord(
        notebook_id=notebook_id,
        profile_id=profile_id,
        title="Notebook",
        normalized_title="notebook",
        is_owner=True,
        share_visibility="restricted",
        created_at_remote="2026-03-15T00:00:00Z",
        source_count=1,
        artifact_count=0,
        note_count=0,
        summary_preview="preview",
        index_synced_at="2026-03-15T00:05:00Z",
        detail_synced_at="2026-03-15T00:06:00Z",
        remote_fingerprint="nb-fp",
        raw_json='{"id":"nb_1"}',
    )
    NotebookRepository(connection).upsert(record)
    return record


def _seed_workspace(
    connection,
    profile_id: str,
    workspace_id: str = "ws_1",
) -> WorkspaceRecord:
    record = WorkspaceRecord(
        id=workspace_id,
        profile_id=profile_id,
        name=f"Workspace {workspace_id}",
        slug=workspace_id.replace("_", "-"),
        description="seeded workspace",
        kind="static",
        query_policy_json='{"top_k":3}',
        approval_policy_json='{"default":"manual"}',
        created_at="2026-03-15T00:00:00Z",
        updated_at="2026-03-15T00:00:00Z",
    )
    WorkspaceRepository(connection).upsert(record)
    return record


def test_notebook_repository_supports_upsert_get_list_and_delete(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        repository = NotebookRepository(connection)

        first = NotebookRecord(
            notebook_id="nb_1",
            profile_id="profile_a",
            title="First Notebook",
            normalized_title="first-notebook",
            is_owner=True,
            source_count=2,
            artifact_count=1,
            note_count=3,
            summary_preview="draft",
            approval_policy_json='{"name":"notebook-default","default":"manual"}',
            raw_json='{"id":"nb_1"}',
        )
        second = NotebookRecord(
            notebook_id="nb_2",
            profile_id="profile_b",
            title="Second Notebook",
            normalized_title="second-notebook",
        )

        repository.upsert(first)
        repository.upsert(second)
        repository.upsert(
            NotebookRecord(
                notebook_id="nb_1",
                profile_id="profile_a",
                title="First Notebook Updated",
                normalized_title="first-notebook",
                is_owner=False,
                artifact_count=4,
                note_count=5,
                summary_preview="updated",
                approval_policy_json='{"name":"notebook-auto","default":"auto"}',
            )
        )

        fetched = repository.get("nb_1")
        listed = repository.list_for_profile("profile_a")

        repository.delete("nb_2")

    assert fetched is not None
    assert fetched.title == "First Notebook Updated"
    assert fetched.is_owner is False
    assert fetched.artifact_count == 4
    assert fetched.approval_policy_json == '{"name":"notebook-auto","default":"auto"}'
    assert listed == [fetched]

    with connect_db(db_path) as connection:
        assert NotebookRepository(connection).get("nb_2") is None


def test_source_repository_supports_crud_and_scope_filters(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        _seed_notebook(connection, "profile_b", notebook_id="nb_b")
        repository = SourceRepository(connection)

        source = SourceRecord(
            source_id="src_1",
            notebook_id="nb_a",
            profile_id="profile_a",
            source_type="url",
            title="Example Source",
            origin_uri="https://example.com",
            status="ready",
            freshness_state="fresh",
            drive_syncable=False,
            content_preview="preview",
            synced_at="2026-03-15T01:00:00Z",
            remote_fingerprint="src-fp",
            raw_json='{"id":"src_1"}',
        )
        other = SourceRecord(
            source_id="src_2",
            notebook_id="nb_b",
            profile_id="profile_b",
            source_type="file",
            status="processing",
        )

        repository.upsert(source)
        repository.upsert(other)
        repository.upsert(
            SourceRecord(
                source_id="src_1",
                notebook_id="nb_a",
                profile_id="profile_a",
                source_type="url",
                title="Example Source Updated",
                origin_uri="https://example.com/updated",
                status="processing",
                freshness_state="stale",
                drive_syncable=True,
            )
        )

        fetched = repository.get("src_1")
        profile_rows = repository.list_for_profile("profile_a")
        notebook_rows = repository.list_for_notebook("nb_a")

        repository.delete("src_2")

    assert fetched is not None
    assert fetched.title == "Example Source Updated"
    assert fetched.drive_syncable is True
    assert profile_rows == [fetched]
    assert notebook_rows == [fetched]

    with connect_db(db_path) as connection:
        assert SourceRepository(connection).get("src_2") is None


def test_artifact_repository_supports_crud_and_scope_filters(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        _seed_notebook(connection, "profile_b", notebook_id="nb_b")
        repository = ArtifactRepository(connection)

        artifact = ArtifactRecord(
            artifact_id="art_1",
            notebook_id="nb_a",
            profile_id="profile_a",
            artifact_type="report",
            submode="study_guide",
            title="Study Guide",
            prompt_hash="prompt-1",
            status="completed",
            requested_at="2026-03-15T01:00:00Z",
            completed_at="2026-03-15T01:05:00Z",
            download_ref="https://example.com/download",
            remote_fingerprint="art-fp",
            raw_json='{"id":"art_1"}',
        )
        other = ArtifactRecord(
            artifact_id="art_2",
            notebook_id="nb_b",
            profile_id="profile_b",
            artifact_type="audio",
            status="pending",
            requested_at="2026-03-15T01:10:00Z",
        )

        repository.upsert(artifact)
        repository.upsert(other)
        repository.upsert(
            ArtifactRecord(
                artifact_id="art_1",
                notebook_id="nb_a",
                profile_id="profile_a",
                artifact_type="report",
                submode="briefing_doc",
                title="Briefing Doc",
                prompt_hash="prompt-2",
                status="in_progress",
                requested_at="2026-03-15T01:00:00Z",
                last_polled_at="2026-03-15T01:03:00Z",
            )
        )

        fetched = repository.get("art_1")
        profile_rows = repository.list_for_profile("profile_a")
        notebook_rows = repository.list_for_notebook("nb_a")

        repository.delete("art_2")

    assert fetched is not None
    assert fetched.submode == "briefing_doc"
    assert fetched.status == "in_progress"
    assert profile_rows == [fetched]
    assert notebook_rows == [fetched]

    with connect_db(db_path) as connection:
        assert ArtifactRepository(connection).get("art_2") is None


def test_research_run_repository_supports_crud_and_scope_filters(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        _seed_notebook(connection, "profile_b", notebook_id="nb_b")
        repository = ResearchRunRepository(connection)

        research = ResearchRunRecord(
            research_id="res_1",
            notebook_id="nb_a",
            profile_id="profile_a",
            mode="deep",
            query_text="AI safety",
            status="completed",
            discovered_count=8,
            imported_count=3,
            started_at="2026-03-15T01:00:00Z",
            updated_at="2026-03-15T01:07:00Z",
            raw_json='{"id":"res_1"}',
        )
        other = ResearchRunRecord(
            research_id="res_2",
            notebook_id="nb_b",
            profile_id="profile_b",
            mode="fast",
            query_text="ML ops",
            status="running",
            started_at="2026-03-15T02:00:00Z",
            updated_at="2026-03-15T02:00:30Z",
        )

        repository.upsert(research)
        repository.upsert(other)
        repository.upsert(
            ResearchRunRecord(
                research_id="res_1",
                notebook_id="nb_a",
                profile_id="profile_a",
                mode="deep",
                query_text="AI safety updated",
                status="imported",
                discovered_count=9,
                imported_count=4,
                started_at="2026-03-15T01:00:00Z",
                updated_at="2026-03-15T01:10:00Z",
            )
        )

        fetched = repository.get("res_1")
        profile_rows = repository.list_for_profile("profile_a")
        notebook_rows = repository.list_for_notebook("nb_a")

        repository.delete("res_2")

    assert fetched is not None
    assert fetched.query_text == "AI safety updated"
    assert fetched.status == "imported"
    assert fetched.imported_count == 4
    assert profile_rows == [fetched]
    assert notebook_rows == [fetched]

    with connect_db(db_path) as connection:
        assert ResearchRunRepository(connection).get("res_2") is None


def test_workspace_repository_supports_crud_profile_listing_and_slug_lookup(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        repository = WorkspaceRepository(connection)

        primary = WorkspaceRecord(
            id="ws_1",
            profile_id="profile_a",
            name="Market Intel",
            slug="market-intel",
            description="pricing and competitors",
            kind="static",
            query_policy_json='{"top_k":3}',
            approval_policy_json='{"default":"manual"}',
            created_at="2026-03-15T01:00:00Z",
            updated_at="2026-03-15T01:00:00Z",
        )
        other = WorkspaceRecord(
            id="ws_2",
            profile_id="profile_b",
            name="Legal Review",
            slug="legal-review",
            kind="rule_based",
            created_at="2026-03-15T02:00:00Z",
            updated_at="2026-03-15T02:00:00Z",
        )

        repository.upsert(primary)
        repository.upsert(other)
        repository.upsert(
            WorkspaceRecord(
                id="ws_1",
                profile_id="profile_a",
                name="Market Intelligence",
                slug="market-intel",
                description="pricing, competitors, and renewal terms",
                kind="static",
                query_policy_json='{"top_k":5}',
                approval_policy_json='{"default":"manual"}',
                created_at="2026-03-15T01:00:00Z",
                updated_at="2026-03-15T01:30:00Z",
            )
        )

        fetched = repository.get("ws_1")
        by_slug = repository.get_by_slug("profile_a", "market-intel")
        profile_rows = repository.list_for_profile("profile_a")

        repository.delete("ws_2")

    assert fetched is not None
    assert fetched.name == "Market Intelligence"
    assert fetched.updated_at == "2026-03-15T01:30:00Z"
    assert fetched.query_policy_json == '{"top_k":5}'
    assert by_slug == fetched
    assert profile_rows == [fetched]

    with connect_db(db_path) as connection:
        assert WorkspaceRepository(connection).get("ws_2") is None


def test_workspace_member_repository_supports_crud_and_scope_filters(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        _seed_notebook(connection, "profile_b", notebook_id="nb_b")
        _seed_workspace(connection, "profile_a", workspace_id="ws_a")
        _seed_workspace(connection, "profile_b", workspace_id="ws_b")
        repository = WorkspaceMemberRepository(connection)

        primary = WorkspaceMemberRecord(
            id="wsm_1",
            workspace_id="ws_a",
            notebook_id="nb_a",
            priority=5,
            tags_json='["pricing"]',
            enabled=True,
            added_at="2026-03-15T03:00:00Z",
        )
        other = WorkspaceMemberRecord(
            id="wsm_2",
            workspace_id="ws_b",
            notebook_id="nb_b",
            priority=1,
            added_at="2026-03-15T03:05:00Z",
        )

        repository.upsert(primary)
        repository.upsert(other)
        repository.upsert(
            WorkspaceMemberRecord(
                id="wsm_1",
                workspace_id="ws_a",
                notebook_id="nb_a",
                priority=9,
                tags_json='["pricing","quarterly"]',
                enabled=False,
                added_at="2026-03-15T03:00:00Z",
            )
        )

        fetched = repository.get("wsm_1")
        workspace_rows = repository.list_for_workspace("ws_a")
        notebook_rows = repository.list_for_notebook("nb_a")

        repository.delete("wsm_2")

    assert fetched is not None
    assert fetched.priority == 9
    assert fetched.enabled is False
    assert fetched.tags_json == '["pricing","quarterly"]'
    assert workspace_rows == [fetched]
    assert notebook_rows == [fetched]

    with connect_db(db_path) as connection:
        assert WorkspaceMemberRepository(connection).get("wsm_2") is None


def test_workspace_rule_repository_supports_crud_and_workspace_filters(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        _seed_workspace(connection, "profile_a", workspace_id="ws_a")
        _seed_workspace(connection, "profile_b", workspace_id="ws_b")
        repository = WorkspaceRuleRepository(connection)

        primary = WorkspaceRuleRecord(
            id="wsr_1",
            workspace_id="ws_a",
            rule_type="tag_match",
            rule_json='{"tags":["pricing"]}',
        )
        other = WorkspaceRuleRecord(
            id="wsr_2",
            workspace_id="ws_b",
            rule_type="title_match",
            rule_json='{"contains":"legal"}',
        )

        repository.upsert(primary)
        repository.upsert(other)
        repository.upsert(
            WorkspaceRuleRecord(
                id="wsr_1",
                workspace_id="ws_a",
                rule_type="title_match",
                rule_json='{"contains":"market"}',
            )
        )

        fetched = repository.get("wsr_1")
        workspace_rows = repository.list_for_workspace("ws_a")

        repository.delete("wsr_2")

    assert fetched is not None
    assert fetched.rule_type == "title_match"
    assert fetched.rule_json == '{"contains":"market"}'
    assert workspace_rows == [fetched]

    with connect_db(db_path) as connection:
        assert WorkspaceRuleRepository(connection).get("wsr_2") is None


def test_workspace_index_entry_repository_supports_crud_and_scope_filters(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        _seed_notebook(connection, "profile_b", notebook_id="nb_b")
        _seed_workspace(connection, "profile_a", workspace_id="ws_a")
        _seed_workspace(connection, "profile_b", workspace_id="ws_b")
        repository = WorkspaceIndexEntryRepository(connection)

        primary = WorkspaceIndexEntryRecord(
            id="wsi_1",
            workspace_id="ws_a",
            profile_id="profile_a",
            notebook_id="nb_a",
            notebook_title="Pricing Notebook",
            notebook_summary="Quarterly pricing strategy",
            title_aliases_text="pricing;quarterly pricing",
            source_titles_text="Pricing Deck",
            source_snippets_text="Price elasticity notes",
            tags_json='["pricing","q1"]',
            recent_query_text="How did prices change last quarter?",
            content_text="Pricing Notebook Quarterly pricing strategy Pricing Deck",
            updated_at="2026-03-15T04:00:00Z",
        )
        other = WorkspaceIndexEntryRecord(
            id="wsi_2",
            workspace_id="ws_b",
            profile_id="profile_b",
            notebook_id="nb_b",
            notebook_title="Legal Notebook",
            content_text="Legal Notebook contract review",
            updated_at="2026-03-15T05:00:00Z",
        )

        repository.upsert(primary)
        repository.upsert(other)
        repository.upsert(
            WorkspaceIndexEntryRecord(
                id="wsi_1",
                workspace_id="ws_a",
                profile_id="profile_a",
                notebook_id="nb_a",
                notebook_title="Pricing Notebook Updated",
                notebook_summary="Renewal and discount strategy",
                title_aliases_text="pricing;discounts",
                source_titles_text="Pricing Deck, Renewal Memo",
                source_snippets_text="Discount ladder and renewal terms",
                tags_json='["pricing","renewal"]',
                recent_query_text="Summarize discount changes",
                content_text="Pricing Notebook Updated Renewal and discount strategy",
                updated_at="2026-03-15T04:30:00Z",
            )
        )

        fetched = repository.get("wsi_1")
        profile_rows = repository.list_for_profile("profile_a")
        workspace_rows = repository.list_for_workspace("ws_a")
        notebook_rows = repository.list_for_notebook("nb_a")

        repository.delete("wsi_2")

    assert fetched is not None
    assert fetched.notebook_title == "Pricing Notebook Updated"
    assert fetched.updated_at == "2026-03-15T04:30:00Z"
    assert fetched.tags_json == '["pricing","renewal"]'
    assert profile_rows == [fetched]
    assert workspace_rows == [fetched]
    assert notebook_rows == [fetched]

    with connect_db(db_path) as connection:
        assert WorkspaceIndexEntryRepository(connection).get("wsi_2") is None


def test_workspace_index_entry_repository_replaces_workspace_fts_rows_and_searches(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        _seed_notebook(connection, "profile_a", notebook_id="nb_b")
        _seed_workspace(connection, "profile_a", workspace_id="ws_a")
        repository = WorkspaceIndexEntryRepository(connection)

        repository.replace_for_workspace(
            "ws_a",
            [
                WorkspaceIndexEntryRecord(
                    id="wsi_old",
                    workspace_id="ws_a",
                    profile_id="profile_a",
                    notebook_id="nb_a",
                    notebook_title="Pricing Notebook",
                    notebook_summary="Quarterly renewal plan",
                    source_titles_text="Renewal Deck",
                    source_snippets_text="Discount ladder notes",
                    tags_json='["pricing","renewal"]',
                    recent_query_text="How did renewals change last quarter?",
                    content_text="Pricing Notebook Quarterly renewal plan Renewal Deck",
                    updated_at="2026-03-15T04:00:00Z",
                )
            ],
        )
        initial_hits = repository.search(
            "renewal",
            workspace_id="ws_a",
            profile_id="profile_a",
            limit=5,
        )

        repository.replace_for_workspace(
            "ws_a",
            [
                WorkspaceIndexEntryRecord(
                    id="wsi_new",
                    workspace_id="ws_a",
                    profile_id="profile_a",
                    notebook_id="nb_b",
                    notebook_title="Forecast Notebook",
                    notebook_summary="Pipeline forecast and expansion plan",
                    source_titles_text="Forecast Review",
                    source_snippets_text="Pipeline expansion notes",
                    tags_json='["forecast"]',
                    recent_query_text="What changed in the pipeline forecast?",
                    content_text="Forecast Notebook Pipeline forecast and expansion plan Forecast Review",
                    updated_at="2026-03-15T05:00:00Z",
                )
            ],
        )
        replaced_hits = repository.search(
            "renewal",
            workspace_id="ws_a",
            profile_id="profile_a",
            limit=5,
        )
        forecast_hits = repository.search(
            "forecast",
            workspace_id="ws_a",
            profile_id="profile_a",
            limit=5,
        )

    assert [hit.entry_id for hit in initial_hits] == ["wsi_old"]
    assert replaced_hits == []
    assert [hit.entry_id for hit in forecast_hits] == ["wsi_new"]
    assert forecast_hits[0].notebook_title == "Forecast Notebook"


def test_lease_repository_supports_acquire_release_and_stale_detection(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        repository = LeaseRepository(connection)

        repository.acquire(
            LeaseRecord(
                id="lease_active",
                scope_type="workspace",
                scope_id="ws_1",
                holder="agent-a",
                purpose="build workspace index",
                advisory=True,
                acquired_at="2026-03-15T01:00:00Z",
                expires_at="2026-03-15T01:10:00Z",
            )
        )
        repository.acquire(
            LeaseRecord(
                id="lease_stale",
                scope_type="watch",
                scope_id="watch_1",
                holder="agent-b",
                purpose="run watch poll",
                advisory=False,
                acquired_at="2026-03-15T00:00:00Z",
                expires_at="2026-03-15T00:10:00Z",
            )
        )
        repository.acquire(
            LeaseRecord(
                id="lease_replacement",
                scope_type="workspace",
                scope_id="ws_1",
                holder="agent-a",
                purpose="renew workspace index",
                advisory=False,
                acquired_at="2026-03-15T01:05:00Z",
                expires_at="2026-03-15T01:15:00Z",
            )
        )

        refreshed = repository.get("lease_active")
        active = repository.list_active(active_at="2026-03-15T01:00:01Z")
        stale = repository.list_stale(active_at="2026-03-15T01:00:01Z")
        holder_rows = repository.list_for_holder("agent-a", active_at="2026-03-15T01:00:01Z")
        scope_rows = repository.list_for_scope("workspace", "ws_1", active_at="2026-03-15T01:00:01Z")
        expired = repository.expire_stale(active_at="2026-03-15T01:00:01Z")
        repository.release("lease_active")

    assert refreshed is not None
    assert refreshed.id == "lease_active"
    assert refreshed.purpose == "renew workspace index"
    assert refreshed.advisory is False
    assert refreshed.expires_at == "2026-03-15T01:15:00Z"
    assert repository.get("lease_replacement") is None
    assert [row.id for row in active] == ["lease_active"]
    assert [row.id for row in stale] == ["lease_stale"]
    assert holder_rows == [refreshed]
    assert scope_rows == [refreshed]
    assert expired == 1

    with connect_db(db_path) as connection:
        repository = LeaseRepository(connection)
        assert repository.get("lease_active") is None
        assert repository.get("lease_stale") is None


def test_workspace_run_repository_supports_crud_and_scope_filters(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        repository = WorkspaceRunRepository(connection)

        primary = WorkspaceRunRecord(
            id="wr_1",
            trace_id="trc_wr_1",
            profile_id="profile_a",
            started_at="2026-03-15T04:00:00Z",
            status="completed",
            workspace_id="ws_a",
            mode="ask",
            ended_at="2026-03-15T04:00:05Z",
            query_text="summarize my notebooks",
            selected_notebooks_json='["nb_1","nb_2"]',
            plan_json='{"steps":["fanout","synthesize"]}',
            result_json='{"answer":"ready"}',
        )
        other = WorkspaceRunRecord(
            id="wr_2",
            trace_id="trc_wr_2",
            profile_id="profile_b",
            started_at="2026-03-15T05:00:00Z",
            status="running",
            workspace_id="ws_b",
            mode="metadata",
        )

        repository.upsert(primary)
        repository.upsert(other)
        repository.upsert(
            WorkspaceRunRecord(
                id="wr_1",
                trace_id="trc_wr_1",
                profile_id="profile_a",
                started_at="2026-03-15T04:00:00Z",
                status="completed",
                workspace_id="ws_a",
                mode="compare",
                ended_at="2026-03-15T04:00:30Z",
                query_text="compare notebook clusters",
                selected_notebooks_json='["nb_3"]',
                plan_json='{"steps":["select","compare"]}',
                result_json='{"summary":"updated"}',
            )
        )

        fetched = repository.get("wr_1")
        profile_rows = repository.list_for_profile("profile_a")
        workspace_rows = repository.list_for_workspace("ws_a")

        repository.delete("wr_2")

    assert fetched is not None
    assert fetched.mode == "compare"
    assert fetched.ended_at == "2026-03-15T04:00:30Z"
    assert fetched.query_text == "compare notebook clusters"
    assert profile_rows == [fetched]
    assert workspace_rows == [fetched]

    with connect_db(db_path) as connection:
        assert WorkspaceRunRepository(connection).get("wr_2") is None


def test_doctor_run_repository_supports_crud_and_profile_filters(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        repository = DoctorRunRepository(connection)

        primary = DoctorRunRecord(
            id="dr_1",
            trace_id="trc_dr_1",
            profile_id="profile_a",
            started_at="2026-03-15T06:00:00Z",
            status="completed",
            mode="fast",
            ended_at="2026-03-15T06:00:10Z",
            overall_status="healthy",
            summary_json='{"checks":[{"key":"auth","status":"passed"}]}',
        )
        other = DoctorRunRecord(
            id="dr_2",
            trace_id="trc_dr_2",
            profile_id="profile_b",
            started_at="2026-03-15T07:00:00Z",
            status="running",
            mode="deep",
        )

        repository.upsert(primary)
        repository.upsert(other)
        repository.upsert(
            DoctorRunRecord(
                id="dr_1",
                trace_id="trc_dr_1",
                profile_id="profile_a",
                started_at="2026-03-15T06:00:00Z",
                status="completed",
                mode="deep",
                ended_at="2026-03-15T06:01:00Z",
                overall_status="degraded",
                summary_json='{"checks":[{"key":"db","status":"failed"}]}',
            )
        )

        fetched = repository.get("dr_1")
        profile_rows = repository.list_for_profile("profile_a")

        repository.delete("dr_2")

    assert fetched is not None
    assert fetched.mode == "deep"
    assert fetched.overall_status == "degraded"
    assert fetched.summary_json == '{"checks":[{"key":"db","status":"failed"}]}'
    assert profile_rows == [fetched]

    with connect_db(db_path) as connection:
        assert DoctorRunRepository(connection).get("dr_2") is None
