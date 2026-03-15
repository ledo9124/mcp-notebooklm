"""Observability helpers for trace-aware NotebookLM execution flows."""

from .json_output import install_trace_json_echo
from .tracing import (
    TraceContext,
    bind_trace,
    current_trace,
    generate_trace_id,
    require_trace,
)

install_trace_json_echo()

__all__ = [
    "TraceContext",
    "bind_trace",
    "current_trace",
    "generate_trace_id",
    "require_trace",
    "install_trace_json_echo",
]
