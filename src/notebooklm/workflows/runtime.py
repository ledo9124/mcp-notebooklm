"""Shared workflow runtime primitives.

This module holds the small pieces of workflow control flow that are meant to
be reused across ask/overview/summarize/research-style commands as the shared
runtime fills in.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import sqlite3
from typing import Any, Literal

from ..contracts import CacheUpdates
from ..local.events import append_run_event


ResolveNotebookId = Callable[[Any, str], Awaitable[str]]
ResolveSourceIds = Callable[[Any, str, tuple[str, ...]], Awaitable[list[str] | None]]
LookupCurrentValue = Callable[[], str | None]
NoticeCallback = Callable[[str], None]
SleepFn = Callable[[float], Awaitable[None]]
RetryPredicate = Callable[[Any], bool]
RetryNoticeCallback = Callable[[int, int, float], None]
PollPredicate = Callable[[Any], bool]
JsonPayloadBuilder = Callable[[], dict[str, Any]]
JsonEmitter = Callable[[dict[str, Any]], None]
HumanRenderer = Callable[[], None]

RETRY_INITIAL_DELAY = 60.0
RETRY_MAX_DELAY = 300.0
RETRY_BACKOFF_MULTIPLIER = 2.0


@dataclass(frozen=True)
class NotebookTargetCandidate:
    """One cached notebook candidate for workflow target resolution."""

    notebook_id: str
    title: str
    normalized_title: str


@dataclass(frozen=True)
class NotebookTargetResolution:
    """Resolved notebook target plus the source used to resolve it."""

    target: str | None
    source: Literal["local_cache", "current_context", "raw_input", "none"]


@dataclass(frozen=True)
class PollOutcome:
    """Result of an async poll loop."""

    result: Any
    completed: bool
    attempts: int


def workflow_tables_touched(*names: str) -> list[str]:
    """Return ordered unique cache table names, dropping blanks."""

    ordered: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def workflow_cache_updates(
    *tables_touched: str,
    invalidated: tuple[str, ...] = (),
) -> CacheUpdates:
    """Build a canonical cache-update summary with stable ordering."""

    return CacheUpdates(
        tables_touched=workflow_tables_touched(*tables_touched),
        invalidated=workflow_tables_touched(*invalidated),
    )


def _normalize_notebook_handle(value: str) -> str:
    return " ".join(value.split()).casefold()


def calculate_backoff_delay(
    attempt: int,
    initial_delay: float = RETRY_INITIAL_DELAY,
    max_delay: float = RETRY_MAX_DELAY,
    multiplier: float = RETRY_BACKOFF_MULTIPLIER,
) -> float:
    """Calculate exponential backoff delay for one retry attempt."""

    delay = initial_delay * (multiplier**attempt)
    return min(delay, max_delay)


def _ambiguous_resolution_error(
    explicit_notebook_id: str,
    matches: list[NotebookTargetCandidate],
) -> ValueError:
    lines = [f"Ambiguous notebook '{explicit_notebook_id}' matches {len(matches)} cached notebooks:"]
    for candidate in matches[:5]:
        lines.append(f"  {candidate.notebook_id} {candidate.title}")
    if len(matches) > 5:
        lines.append(f"  ... and {len(matches) - 5} more")
    lines.append("Specify a full notebook ID or an exact title.")
    return ValueError("\n".join(lines))


def resolve_notebook_target(
    *,
    explicit_notebook_id: str | None,
    current_notebook_id: str | None,
    cached_candidates: list[NotebookTargetCandidate],
) -> NotebookTargetResolution:
    """Resolve a workflow notebook target using the contract-first ordering."""
    if explicit_notebook_id:
        if any(candidate.notebook_id == explicit_notebook_id for candidate in cached_candidates):
            return NotebookTargetResolution(
                target=explicit_notebook_id,
                source="local_cache",
            )

        normalized_target = _normalize_notebook_handle(explicit_notebook_id)
        exact_title_matches = [
            candidate
            for candidate in cached_candidates
            if candidate.normalized_title == normalized_target
        ]
        if len(exact_title_matches) == 1:
            return NotebookTargetResolution(
                target=exact_title_matches[0].notebook_id,
                source="local_cache",
            )
        if len(exact_title_matches) > 1:
            raise _ambiguous_resolution_error(explicit_notebook_id, exact_title_matches)

        fuzzy_matches = [
            candidate
            for candidate in cached_candidates
            if candidate.normalized_title.startswith(normalized_target)
        ]
        if not fuzzy_matches:
            fuzzy_matches = [
                candidate
                for candidate in cached_candidates
                if normalized_target in candidate.normalized_title
            ]
        if len(fuzzy_matches) == 1:
            return NotebookTargetResolution(
                target=fuzzy_matches[0].notebook_id,
                source="local_cache",
            )
        if len(fuzzy_matches) > 1:
            raise _ambiguous_resolution_error(explicit_notebook_id, fuzzy_matches)

        return NotebookTargetResolution(target=explicit_notebook_id, source="raw_input")

    if current_notebook_id:
        return NotebookTargetResolution(target=current_notebook_id, source="current_context")

    return NotebookTargetResolution(target=None, source="none")


async def retry_with_backoff(
    operation: Callable[[], Awaitable[Any]],
    *,
    max_retries: int,
    should_retry: RetryPredicate,
    on_retry: RetryNoticeCallback | None = None,
    sleep: SleepFn = asyncio.sleep,
) -> Any:
    """Run an async operation with retry/backoff for retryable results."""

    for attempt in range(max_retries + 1):
        result = await operation()
        if not should_retry(result) or attempt >= max_retries:
            return result

        delay = calculate_backoff_delay(attempt)
        if on_retry is not None:
            on_retry(attempt + 1, max_retries + 1, delay)
        await sleep(delay)

    return None


async def poll_with_interval(
    operation: Callable[[], Awaitable[Any]],
    *,
    max_iterations: int,
    interval_seconds: float,
    is_complete: PollPredicate,
    sleep: SleepFn = asyncio.sleep,
) -> PollOutcome:
    """Poll an async operation until completion or the iteration budget is exhausted."""

    last_result: Any = None
    total_iterations = max(1, max_iterations)
    for attempt in range(total_iterations):
        last_result = await operation()
        if is_complete(last_result):
            return PollOutcome(result=last_result, completed=True, attempts=attempt + 1)
        if attempt + 1 < total_iterations:
            await sleep(interval_seconds)

    return PollOutcome(result=last_result, completed=False, attempts=total_iterations)


def emit_workflow_output(
    *,
    json_output: bool,
    build_json: JsonPayloadBuilder,
    emit_json: JsonEmitter,
    render_human: HumanRenderer,
) -> None:
    """Emit one workflow result as canonical JSON or human-formatted text."""

    if json_output:
        emit_json(build_json())
        return
    render_human()


def record_route_resolution_event(
    connection: sqlite3.Connection,
    *,
    trace_id: str,
    run_id: str | None,
    command: str,
    mode: str,
    notebook_id: str | None,
    profile_id: str,
    cache_mode: str,
    reason: str,
    source_of_truth: str,
) -> None:
    """Append the standard route-resolution event for a workflow run."""

    append_run_event(
        connection,
        trace_id,
        "route.resolved",
        run_id=run_id,
        payload={
            "cache_mode": cache_mode,
            "command": command,
            "mode": mode,
            "notebook_id": notebook_id,
            "profile_id": profile_id,
            "reason": reason,
            "source_of_truth": source_of_truth,
        },
    )


def record_cache_event(
    connection: sqlite3.Connection,
    *,
    trace_id: str,
    run_id: str | None,
    kind: Literal["cache.hit", "cache.miss"],
    command: str,
    entity: str,
    notebook_id: str | None,
    prompt_hash: str | None = None,
    notebook_fingerprint: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> None:
    """Append the standard cache-hit/cache-miss event for a workflow run."""

    payload: dict[str, Any] = {
        "command": command,
        "entity": entity,
        "notebook_id": notebook_id,
    }
    if notebook_fingerprint is not None:
        payload["notebook_fingerprint"] = notebook_fingerprint
    if prompt_hash is not None:
        payload["prompt_hash"] = prompt_hash
    if extra_payload:
        payload.update(extra_payload)

    append_run_event(
        connection,
        trace_id,
        kind,
        run_id=run_id,
        payload=payload,
    )


__all__ = [
    "HumanRenderer",
    "JsonEmitter",
    "JsonPayloadBuilder",
    "emit_workflow_output",
    "PollOutcome",
    "LookupCurrentValue",
    "NotebookTargetCandidate",
    "NotebookTargetResolution",
    "NoticeCallback",
    "ResolveNotebookId",
    "ResolveSourceIds",
    "calculate_backoff_delay",
    "poll_with_interval",
    "record_cache_event",
    "record_route_resolution_event",
    "resolve_notebook_target",
    "retry_with_backoff",
    "workflow_cache_updates",
    "workflow_tables_touched",
]
