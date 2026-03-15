"""Unit tests for shared workflow-runtime notebook resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from notebooklm.workflows.runtime import (
    NotebookTargetCandidate,
    calculate_backoff_delay,
    poll_with_interval,
    resolve_notebook_target,
    retry_with_backoff,
    workflow_cache_updates,
    workflow_tables_touched,
)


def test_resolve_notebook_target_prefers_exact_cached_id_match():
    resolution = resolve_notebook_target(
        explicit_notebook_id="nb_pricing",
        current_notebook_id="nb_context",
        cached_candidates=[
            NotebookTargetCandidate(
                notebook_id="nb_pricing",
                title="Pricing",
                normalized_title="pricing",
            )
        ],
    )

    assert resolution.target == "nb_pricing"
    assert resolution.source == "local_cache"


def test_resolve_notebook_target_prefers_exact_cached_title_match():
    resolution = resolve_notebook_target(
        explicit_notebook_id="Pricing",
        current_notebook_id="nb_context",
        cached_candidates=[
            NotebookTargetCandidate(
                notebook_id="nb_pricing",
                title="Pricing",
                normalized_title="pricing",
            ),
            NotebookTargetCandidate(
                notebook_id="nb_notes",
                title="Notes",
                normalized_title="notes",
            ),
        ],
    )

    assert resolution.target == "nb_pricing"
    assert resolution.source == "local_cache"


def test_resolve_notebook_target_supports_unique_fuzzy_cached_title_match():
    resolution = resolve_notebook_target(
        explicit_notebook_id="renew",
        current_notebook_id="nb_context",
        cached_candidates=[
            NotebookTargetCandidate(
                notebook_id="nb_renewals",
                title="Renewals Pricing",
                normalized_title="renewals pricing",
            ),
            NotebookTargetCandidate(
                notebook_id="nb_notes",
                title="General Notes",
                normalized_title="general notes",
            ),
        ],
    )

    assert resolution.target == "nb_renewals"
    assert resolution.source == "local_cache"


def test_resolve_notebook_target_rejects_ambiguous_cached_matches():
    with pytest.raises(ValueError, match="Ambiguous notebook 'pri' matches 2 cached notebooks"):
        resolve_notebook_target(
            explicit_notebook_id="pri",
            current_notebook_id="nb_context",
            cached_candidates=[
                NotebookTargetCandidate(
                    notebook_id="nb_1",
                    title="Pricing",
                    normalized_title="pricing",
                ),
                NotebookTargetCandidate(
                    notebook_id="nb_2",
                    title="Pricing Review",
                    normalized_title="pricing review",
                ),
            ],
        )


def test_resolve_notebook_target_falls_back_to_raw_input_when_cache_has_no_match():
    resolution = resolve_notebook_target(
        explicit_notebook_id="nb_remote_only",
        current_notebook_id="nb_context",
        cached_candidates=[],
    )

    assert resolution.target == "nb_remote_only"
    assert resolution.source == "raw_input"


def test_resolve_notebook_target_falls_back_to_current_context_without_explicit_value():
    resolution = resolve_notebook_target(
        explicit_notebook_id=None,
        current_notebook_id="nb_context",
        cached_candidates=[],
    )

    assert resolution.target == "nb_context"
    assert resolution.source == "current_context"


def test_calculate_backoff_delay_caps_growth():
    assert calculate_backoff_delay(0, initial_delay=10.0) == 10.0
    assert calculate_backoff_delay(2, initial_delay=10.0) == 40.0
    assert calculate_backoff_delay(10, initial_delay=10.0, max_delay=50.0) == 50.0


def test_workflow_tables_touched_preserves_order_and_dedupes():
    assert workflow_tables_touched("query_runs", "run_events", "query_runs", "", "query_results") == [
        "query_runs",
        "run_events",
        "query_results",
    ]


def test_workflow_cache_updates_wraps_ordered_tables_and_invalidations():
    updates = workflow_cache_updates(
        "research_runs",
        "run_events",
        "research_runs",
        invalidated=("notebook_detail:nb_123", "notebook_detail:nb_123"),
    )

    assert updates.tables_touched == ["research_runs", "run_events"]
    assert updates.invalidated == ["notebook_detail:nb_123"]


def test_emit_workflow_output_prefers_json_payload():
    from notebooklm.workflows.runtime import emit_workflow_output

    payloads: list[dict[str, object]] = []
    rendered: list[str] = []

    emit_workflow_output(
        json_output=True,
        build_json=lambda: {"ok": True},
        emit_json=payloads.append,
        render_human=lambda: rendered.append("human"),
    )

    assert payloads == [{"ok": True}]
    assert rendered == []


def test_emit_workflow_output_prefers_human_renderer():
    from notebooklm.workflows.runtime import emit_workflow_output

    payloads: list[dict[str, object]] = []
    rendered: list[str] = []

    emit_workflow_output(
        json_output=False,
        build_json=lambda: {"ok": True},
        emit_json=payloads.append,
        render_human=lambda: rendered.append("human"),
    )

    assert payloads == []
    assert rendered == ["human"]


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_returns_first_non_retryable_result(self):
        operation = AsyncMock(return_value="done")
        sleep = AsyncMock()

        result = await retry_with_backoff(
            operation,
            max_retries=3,
            should_retry=lambda value: value == "retry",
            sleep=sleep,
        )

        assert result == "done"
        assert operation.await_count == 1
        sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retries_until_success(self):
        operation = AsyncMock(side_effect=["retry", "retry", "done"])
        sleep = AsyncMock()
        notices: list[tuple[int, int, float]] = []

        result = await retry_with_backoff(
            operation,
            max_retries=3,
            should_retry=lambda value: value == "retry",
            on_retry=lambda attempt, total, delay: notices.append((attempt, total, delay)),
            sleep=sleep,
        )

        assert result == "done"
        assert operation.await_count == 3
        assert notices == [(1, 4, 60.0), (2, 4, 120.0)]
        assert [call.args[0] for call in sleep.await_args_list] == [60.0, 120.0]

    @pytest.mark.asyncio
    async def test_stops_after_retry_budget_exhausted(self):
        operation = AsyncMock(return_value="retry")
        sleep = AsyncMock()

        result = await retry_with_backoff(
            operation,
            max_retries=2,
            should_retry=lambda value: value == "retry",
            sleep=sleep,
        )

        assert result == "retry"
        assert operation.await_count == 3
        assert [call.args[0] for call in sleep.await_args_list] == [60.0, 120.0]


class TestPollWithInterval:
    @pytest.mark.asyncio
    async def test_returns_completed_outcome(self):
        operation = AsyncMock(side_effect=["pending", "done"])
        sleep = AsyncMock()

        outcome = await poll_with_interval(
            operation,
            max_iterations=5,
            interval_seconds=7.0,
            is_complete=lambda value: value == "done",
            sleep=sleep,
        )

        assert outcome.result == "done"
        assert outcome.completed is True
        assert outcome.attempts == 2
        assert operation.await_count == 2
        assert [call.args[0] for call in sleep.await_args_list] == [7.0]

    @pytest.mark.asyncio
    async def test_returns_timeout_outcome_with_last_result(self):
        operation = AsyncMock(side_effect=["pending", "still_pending"])
        sleep = AsyncMock()

        outcome = await poll_with_interval(
            operation,
            max_iterations=2,
            interval_seconds=3.0,
            is_complete=lambda value: value == "done",
            sleep=sleep,
        )

        assert outcome.result == "still_pending"
        assert outcome.completed is False
        assert outcome.attempts == 2
        assert operation.await_count == 2
        assert [call.args[0] for call in sleep.await_args_list] == [3.0]
