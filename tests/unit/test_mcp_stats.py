"""Unit tests for notebooklm_mcp._stats."""

from __future__ import annotations

import asyncio

import pytest

from notebooklm_mcp._stats import Stats


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_stats_counters_and_snapshot_fields() -> None:
    clock = _FakeClock(start=1000.0)
    stats = Stats(time_fn=clock.now)

    stats.record_request("notebooklm_notebooks_list")
    stats.record_request("notebooklm_notebooks_list")
    stats.record_backoff()
    stats.record_error("notebooklm_notebooks_list", "rate_limited", "token=abc123")

    snapshot = stats.snapshot()
    assert snapshot["requests_total"] == 2
    assert snapshot["requests_1h"] == 2
    assert snapshot["errors_total"] == 1
    assert snapshot["errors_by_code"] == {"rate_limited": 1}
    assert snapshot["backoff_events_1h"] == 1
    assert snapshot["inflight"] == 0
    assert snapshot["start_time"] == "1970-01-01T00:16:40+00:00"
    assert snapshot["errors_1h"][0]["code"] == "rate_limited"
    assert "[REDACTED]" in snapshot["errors_1h"][0]["message"]


def test_error_message_is_truncated_to_200_chars() -> None:
    stats = Stats()
    stats.record_error("tool_x", "server_error", "x" * 500)

    snapshot = stats.snapshot()
    message = snapshot["errors_1h"][0]["message"]
    assert message is not None
    assert len(message) == 200
    assert message.endswith("…")


def test_rolling_window_prunes_old_events() -> None:
    clock = _FakeClock(start=0.0)
    stats = Stats(time_fn=clock.now, window_seconds=10.0)

    stats.record_request("tool_a")
    stats.record_backoff()
    stats.record_error("tool_a", "network_error", "timeout")

    clock.advance(11.0)
    snapshot = stats.snapshot()

    assert snapshot["requests_total"] == 1
    assert snapshot["requests_1h"] == 0
    assert snapshot["backoff_events_1h"] == 0
    assert snapshot["errors_total"] == 1
    assert snapshot["errors_1h"] == []


def test_errors_window_is_bounded_by_max_error_events() -> None:
    clock = _FakeClock(start=0.0)
    stats = Stats(time_fn=clock.now, max_error_events=2)

    stats.record_error("tool_a", "one", "m1")
    clock.advance(1.0)
    stats.record_error("tool_b", "two", "m2")
    clock.advance(1.0)
    stats.record_error("tool_c", "three", "m3")

    snapshot = stats.snapshot()
    assert snapshot["errors_total"] == 3
    assert snapshot["errors_by_code"] == {"one": 1, "two": 1, "three": 1}
    assert [event["code"] for event in snapshot["errors_1h"]] == ["three", "two"]


def test_inflight_guard_balances_on_success_and_exception() -> None:
    clock = _FakeClock(start=100.0)
    stats = Stats(time_fn=clock.now)

    with stats.enter_inflight():
        assert stats.snapshot()["inflight"] == 1
    assert stats.snapshot()["inflight"] == 0

    with pytest.raises(RuntimeError):
        with stats.enter_inflight():
            assert stats.snapshot()["inflight"] == 1
            raise RuntimeError("boom")

    assert stats.snapshot()["inflight"] == 0


@pytest.mark.asyncio
async def test_inflight_guard_supports_async_context_manager() -> None:
    clock = _FakeClock(start=10.0)
    stats = Stats(time_fn=clock.now)

    async with stats.enter_inflight():
        assert stats.snapshot()["inflight"] == 1
        await asyncio.sleep(0)

    assert stats.snapshot()["inflight"] == 0
