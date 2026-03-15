"""Unit tests for the observability tracing helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import re

import pytest

from notebooklm.observability.tracing import (
    TraceContext,
    bind_trace,
    current_trace,
    generate_trace_id,
    require_trace,
)


def test_generate_trace_id_uses_trc_prefix_and_ulid_shape():
    trace_id = generate_trace_id(datetime(2026, 3, 15, tzinfo=timezone.utc))

    assert re.fullmatch(r"trc_[0-9A-HJKMNP-TV-Z]{26}", trace_id)


def test_bind_trace_generates_current_context_and_restores_after_exit():
    assert current_trace() is None

    with bind_trace(run_id="run_123") as trace:
        assert trace.trace_id.startswith("trc_")
        assert trace.run_id == "run_123"
        assert current_trace() == trace
        assert require_trace() == trace

    assert current_trace() is None


def test_bind_trace_accepts_explicit_context_and_restores_outer_trace():
    outer = TraceContext(trace_id="trc_outer", run_id="run_outer")
    inner = TraceContext(trace_id="trc_inner", run_id="run_inner")

    with bind_trace(outer):
        assert require_trace() == outer
        with bind_trace(inner):
            assert require_trace() == inner
        assert require_trace() == outer


def test_require_trace_raises_when_no_context_is_bound():
    with pytest.raises(RuntimeError, match="No active trace context"):
        require_trace()


def test_trace_context_with_run_id_keeps_trace_id_and_updates_run_id():
    trace = TraceContext(trace_id="trc_example").with_run_id("run_next")

    assert trace == TraceContext(trace_id="trc_example", run_id="run_next")
