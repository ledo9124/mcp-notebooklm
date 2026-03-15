"""Unit tests for the local execution/history repositories."""

from __future__ import annotations

from notebooklm.local.db import connect_db
from notebooklm.local.repositories import (
    NotebookRecord,
    NotebookRepository,
    QueryResultRecord,
    QueryResultRepository,
    QueryRunRecord,
    QueryRunRepository,
    SyncRunRecord,
    SyncRunRepository,
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


def _seed_notebook(connection, profile_id: str, notebook_id: str = "nb_history") -> None:
    NotebookRepository(connection).upsert(
        NotebookRecord(
            notebook_id=notebook_id,
            profile_id=profile_id,
            title="History Notebook",
            normalized_title="history-notebook",
        )
    )


def test_query_run_repository_supports_upsert_get_and_scope_filters(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        _seed_notebook(connection, "profile_b", notebook_id="nb_b")
        repository = QueryRunRepository(connection)

        run = QueryRunRecord(
            id="qr_1",
            trace_id="trace_qr_1",
            profile_id="profile_a",
            notebook_id="nb_a",
            intent="ask",
            mode="remote",
            prompt_text="What changed?",
            prompt_hash="hash-1",
            cache_policy="smart",
            route_reason="cache miss",
            source_of_truth="remote_http",
            started_at="2026-03-15T01:00:00Z",
            status="running",
        )
        other = QueryRunRecord(
            id="qr_2",
            trace_id="trace_qr_2",
            profile_id="profile_b",
            notebook_id="nb_b",
            intent="overview",
            mode="local",
            prompt_text="Summarize",
            prompt_hash="hash-2",
            cache_policy="refresh",
            route_reason="explicit refresh",
            source_of_truth="local_cache",
            started_at="2026-03-15T02:00:00Z",
            status="completed",
        )

        repository.upsert(run)
        repository.upsert(other)
        repository.upsert(
            QueryRunRecord(
                id="qr_1",
                trace_id="trace_qr_1",
                profile_id="profile_a",
                notebook_id="nb_a",
                intent="ask",
                mode="remote",
                prompt_text="What changed recently?",
                prompt_hash="hash-1",
                settings_hash="settings-1",
                notebook_fingerprint="fp-1",
                cache_policy="network",
                route_reason="forced refresh",
                source_of_truth="remote_http",
                started_at="2026-03-15T01:00:00Z",
                ended_at="2026-03-15T01:00:05Z",
                status="completed",
            )
        )

        fetched = repository.get("qr_1")
        profile_rows = repository.list_for_profile("profile_a")
        notebook_rows = repository.list_for_notebook("nb_a")

        repository.delete("qr_2")

    assert fetched is not None
    assert fetched.prompt_text == "What changed recently?"
    assert fetched.ended_at == "2026-03-15T01:00:05Z"
    assert profile_rows == [fetched]
    assert notebook_rows == [fetched]

    with connect_db(db_path) as connection:
        assert QueryRunRepository(connection).get("qr_2") is None


def test_query_result_repository_supports_upsert_get_and_delete(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        QueryRunRepository(connection).upsert(
            QueryRunRecord(
                id="qr_1",
                trace_id="trace_qr_1",
                profile_id="profile_a",
                notebook_id="nb_a",
                intent="ask",
                mode="remote",
                prompt_text="Answer this",
                prompt_hash="hash-1",
                cache_policy="smart",
                route_reason="remote",
                source_of_truth="remote_http",
                started_at="2026-03-15T01:00:00Z",
                status="completed",
            )
        )

        repository = QueryResultRepository(connection)
        repository.upsert(
            QueryResultRecord(
                query_run_id="qr_1",
                result_type="answer",
                answer_text="Initial answer",
                citations_json='["c1"]',
                result_json='{"ok": true}',
                created_at="2026-03-15T01:00:01Z",
            )
        )
        repository.upsert(
            QueryResultRecord(
                query_run_id="qr_1",
                result_type="answer",
                answer_text="Updated answer",
                citations_json='["c1","c2"]',
                result_json='{"ok": true, "updated": true}',
                created_at="2026-03-15T01:00:02Z",
            )
        )

        fetched = repository.get("qr_1")
        repository.delete("qr_1")

    assert fetched is not None
    assert fetched.answer_text == "Updated answer"
    assert fetched.created_at == "2026-03-15T01:00:02Z"

    with connect_db(db_path) as connection:
        assert QueryResultRepository(connection).get("qr_1") is None


def test_query_run_repository_search_history_and_detail_join_fts_and_result_rows(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        _seed_notebook(connection, "profile_a", notebook_id="nb_a")
        _seed_notebook(connection, "profile_b", notebook_id="nb_b")
        run_repository = QueryRunRepository(connection)
        result_repository = QueryResultRepository(connection)

        run_repository.upsert(
            QueryRunRecord(
                id="qr_history_1",
                trace_id="trc_history_1",
                profile_id="profile_a",
                notebook_id="nb_a",
                intent="ask",
                mode="answer",
                prompt_text="find the renewal clause",
                prompt_hash="hash-history-1",
                cache_policy="smart",
                route_reason="remote query",
                source_of_truth="remote_http",
                started_at="2026-03-15T03:00:00Z",
                ended_at="2026-03-15T03:00:02Z",
                status="completed",
            )
        )
        result_repository.upsert(
            QueryResultRecord(
                query_run_id="qr_history_1",
                result_type="answer",
                answer_text="The renewal clause appears in section 4.",
                citations_json='["citation-1"]',
                result_json='{"summary": "renewal clause"}',
                created_at="2026-03-15T03:00:02Z",
            )
        )
        run_repository.upsert(
            QueryRunRecord(
                id="qr_history_2",
                trace_id="trc_history_2",
                profile_id="profile_b",
                notebook_id="nb_b",
                intent="ask",
                mode="answer",
                prompt_text="find the renewal clause in another profile",
                prompt_hash="hash-history-2",
                cache_policy="smart",
                route_reason="remote query",
                source_of_truth="remote_http",
                started_at="2026-03-15T04:00:00Z",
                ended_at="2026-03-15T04:00:02Z",
                status="completed",
            )
        )
        with connection:
            connection.execute(
                """
                INSERT INTO history_fts (
                    run_id,
                    trace_id,
                    profile_id,
                    prompt_text,
                    answer_text,
                    notebook_title,
                    source_titles
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "qr_history_1",
                    "trc_history_1",
                    "profile_a",
                    "find the renewal clause",
                    "The renewal clause appears in section 4.",
                    "History Notebook",
                    "Master Service Agreement Renewal Addendum",
                ),
            )
            connection.execute(
                """
                INSERT INTO history_fts (
                    run_id,
                    trace_id,
                    profile_id,
                    prompt_text,
                    answer_text,
                    notebook_title,
                    source_titles
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "qr_history_2",
                    "trc_history_2",
                    "profile_b",
                    "find the renewal clause in another profile",
                    "Another answer",
                    "Other Notebook",
                    "Other Source",
                ),
            )

        hits = run_repository.search_history("renewal", profile_id="profile_a", limit=5)
        detail = run_repository.get_history_detail("qr_history_1")

    assert [hit.run_id for hit in hits] == ["qr_history_1"]
    assert hits[0].notebook_title == "History Notebook"
    assert hits[0].answer_text == "The renewal clause appears in section 4."
    assert detail is not None
    assert detail.query_run.id == "qr_history_1"
    assert detail.query_run.route_reason == "remote query"
    assert detail.query_result is not None
    assert detail.query_result.result_type == "answer"
    assert detail.query_result.result_json == '{"summary": "renewal clause"}'
    assert detail.notebook_title == "History Notebook"
    assert detail.source_titles == "Master Service Agreement Renewal Addendum"


def test_sync_run_repository_supports_upsert_get_list_and_delete(tmp_path):
    db_path = tmp_path / "cache.db"

    with connect_db(db_path) as connection:
        _insert_profile(connection, "profile_a")
        _insert_profile(connection, "profile_b")
        repository = SyncRunRepository(connection)

        sync = SyncRunRecord(
            id="sr_1",
            trace_id="trace_sr_1",
            profile_id="profile_a",
            scope="notebook_index",
            target_id="nb_a",
            trigger="manual",
            started_at="2026-03-15T01:30:00Z",
            status="running",
            stats_json='{"inserted": 3}',
        )
        other = SyncRunRecord(
            id="sr_2",
            trace_id="trace_sr_2",
            profile_id="profile_b",
            scope="artifact_poll",
            trigger="startup",
            started_at="2026-03-15T02:30:00Z",
            status="failed",
            error_text="timeout",
        )

        repository.upsert(sync)
        repository.upsert(other)
        repository.upsert(
            SyncRunRecord(
                id="sr_1",
                trace_id="trace_sr_1",
                profile_id="profile_a",
                scope="notebook_index",
                target_id="nb_a",
                trigger="mutation",
                started_at="2026-03-15T01:30:00Z",
                ended_at="2026-03-15T01:31:00Z",
                status="completed",
                stats_json='{"inserted": 3, "updated": 1}',
            )
        )

        fetched = repository.get("sr_1")
        profile_rows = repository.list_for_profile("profile_a")

        repository.delete("sr_2")

    assert fetched is not None
    assert fetched.trigger == "mutation"
    assert fetched.ended_at == "2026-03-15T01:31:00Z"
    assert profile_rows == [fetched]

    with connect_db(db_path) as connection:
        assert SyncRunRepository(connection).get("sr_2") is None
