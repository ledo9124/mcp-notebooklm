"""Canonical overview workflow command."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import time
import uuid
from typing import Any

import click

from ..client import NotebookLMClient
from ..contracts import Diagnostics, Envelope, Intent, Route, Transport, manifest_risk_guard
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..local.fingerprints import compute_notebook_fingerprint
from ..local.repositories import (
    ArtifactRepository,
    NotebookRecord,
    NotebookRepository,
    QueryResultRecord,
    QueryResultRepository,
    QueryRunRecord,
    QueryRunRepository,
    SourceRepository,
)
from ..profiles.manager import ProfileManager
from ..workflows.runtime import (
    emit_workflow_output,
    record_cache_event,
    record_route_resolution_event,
    workflow_cache_updates,
)
from .helpers import console, json_output_response, require_notebook, resolve_notebook_id, with_client
from .options import json_option
from .session import _trace_and_run_id


_OVERVIEW_RPC_BINDING = RPC_MAP[(Intent.QUERY.value, "summary")]
_OVERVIEW_PROMPT = "overview"
_OVERVIEW_CACHE_POLICY = "refresh"
_OVERVIEW_SOURCE_OF_TRUTH = "remote_http"
_OVERVIEW_ROUTE_REASON = (
    "Structured overview command fetches a lightweight remote notebook summary."
)


@dataclass(frozen=True)
class _OverviewPersistenceState:
    query_run_id: str
    trace_id: str
    profile_id: str
    notebook_id: str
    settings_hash: str
    notebook_fingerprint: str | None
    started_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _settings_hash(*, include_topics: bool) -> str:
    return _hash_text(_canonical_json({"include_topics": include_topics}))


def _query_run_id(trace_id: str) -> str:
    if trace_id.startswith("trc_") and trace_id.removeprefix("trc_"):
        return f"qr_{trace_id.removeprefix('trc_')}"
    return f"qr_{uuid.uuid4().hex}"


def _active_profile_id(connection) -> str:
    profile = ProfileManager(connection).get_active_profile()
    return profile.profile_id if profile is not None else "default"


def _ensure_cached_notebook(connection, *, notebook_id: str, profile_id: str):
    repository = NotebookRepository(connection)
    notebook = repository.get(notebook_id)
    if notebook is not None:
        return notebook
    repository.upsert(
        NotebookRecord(
            notebook_id=notebook_id,
            profile_id=profile_id,
            title=notebook_id,
            normalized_title=notebook_id.casefold(),
        )
    )
    return None


def _resolve_notebook_fingerprint(connection, notebook) -> str | None:
    if notebook is None:
        return None
    if notebook.remote_fingerprint:
        return notebook.remote_fingerprint
    return compute_notebook_fingerprint(
        notebook,
        sources=SourceRepository(connection).list_for_notebook(notebook.notebook_id),
        artifacts=ArtifactRepository(connection).list_for_notebook(notebook.notebook_id),
    )


def _topic_payload(topic: Any) -> dict[str, str]:
    return {
        "question": getattr(topic, "question", ""),
        "prompt": getattr(topic, "prompt", ""),
    }


def _description_payload(description, *, include_topics: bool) -> dict[str, Any]:
    topics = []
    if include_topics and description is not None:
        topics = [_topic_payload(topic) for topic in getattr(description, "suggested_topics", [])]
    return {
        "summary": "" if description is None else getattr(description, "summary", "") or "",
        "suggested_topics": topics,
    }


def _run_record(
    state: _OverviewPersistenceState,
    *,
    status: str,
    ended_at: str | None = None,
) -> QueryRunRecord:
    return QueryRunRecord(
        id=state.query_run_id,
        trace_id=state.trace_id,
        profile_id=state.profile_id,
        notebook_id=state.notebook_id,
        intent="overview",
        mode=_OVERVIEW_RPC_BINDING.mode,
        prompt_text=_OVERVIEW_PROMPT,
        prompt_hash=_hash_text(_OVERVIEW_PROMPT),
        settings_hash=state.settings_hash,
        notebook_fingerprint=state.notebook_fingerprint,
        cache_policy=_OVERVIEW_CACHE_POLICY,
        route_reason=_OVERVIEW_ROUTE_REASON,
        source_of_truth=_OVERVIEW_SOURCE_OF_TRUTH,
        started_at=state.started_at,
        ended_at=ended_at,
        status=status,
    )


def _record_overview_start(
    *,
    trace_id: str,
    notebook_id: str,
    include_topics: bool,
) -> _OverviewPersistenceState:
    started_at = _utc_now()
    settings_hash = _settings_hash(include_topics=include_topics)
    with connect_db() as connection:
        profile_id = _active_profile_id(connection)
        notebook = _ensure_cached_notebook(
            connection,
            notebook_id=notebook_id,
            profile_id=profile_id,
        )
        state = _OverviewPersistenceState(
            query_run_id=_query_run_id(trace_id),
            trace_id=trace_id,
            profile_id=profile_id,
            notebook_id=notebook_id,
            settings_hash=settings_hash,
            notebook_fingerprint=_resolve_notebook_fingerprint(connection, notebook),
            started_at=started_at,
        )
        QueryRunRepository(connection).upsert(_run_record(state, status="running"))
        record_route_resolution_event(
            connection,
            trace_id=trace_id,
            run_id=state.query_run_id,
            command="overview",
            mode=_OVERVIEW_RPC_BINDING.mode,
            notebook_id=notebook_id,
            profile_id=state.profile_id,
            cache_mode=_OVERVIEW_CACHE_POLICY,
            reason=_OVERVIEW_ROUTE_REASON,
            source_of_truth=_OVERVIEW_SOURCE_OF_TRUTH,
        )
        record_cache_event(
            connection,
            trace_id=trace_id,
            run_id=state.query_run_id,
            kind="cache.miss",
            command="overview",
            entity="query_results",
            notebook_id=notebook_id,
            notebook_fingerprint=state.notebook_fingerprint,
        )
        return state


def _record_overview_result(
    state: _OverviewPersistenceState,
    *,
    result_payload: dict[str, Any],
) -> None:
    finished_at = _utc_now()
    with connect_db() as connection:
        QueryRunRepository(connection).upsert(
            _run_record(state, status="completed", ended_at=finished_at)
        )
        QueryResultRepository(connection).upsert(
            QueryResultRecord(
                query_run_id=state.query_run_id,
                result_type="summary",
                answer_text=result_payload["summary"] or None,
                result_json=_canonical_json(result_payload),
                created_at=finished_at,
            )
        )


def _record_overview_failure(state: _OverviewPersistenceState) -> None:
    with connect_db() as connection:
        QueryRunRepository(connection).upsert(
            _run_record(state, status="failed", ended_at=_utc_now())
        )


def _overview_envelope(
    ctx: click.Context,
    *,
    notebook_id: str,
    profile_id: str,
    result_payload: dict[str, Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, _OVERVIEW_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_OVERVIEW_RPC_BINDING.intent),
            mode=_OVERVIEW_RPC_BINDING.mode,
            notebook_id=notebook_id,
            profile_id=profile_id,
            source_of_truth=_OVERVIEW_SOURCE_OF_TRUTH,
            cache_mode=_OVERVIEW_CACHE_POLICY,
            reason=_OVERVIEW_ROUTE_REASON,
            transport=Transport(
                kind=_OVERVIEW_RPC_BINDING.transport_kind,
                endpoint=_OVERVIEW_RPC_BINDING.endpoint,
                rpcid=_OVERVIEW_RPC_BINDING.rpcid,
            ),
        ),
        result=result_payload,
        cache_updates=workflow_cache_updates("query_runs", "query_results", "run_events"),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_overview_payload(payload: dict[str, Any]) -> None:
    summary = payload.get("summary", "")
    if summary:
        console.print("[bold cyan]Overview:[/bold cyan]")
        console.print(summary)
    else:
        console.print("[yellow]No summary available[/yellow]")

    topics = payload.get("suggested_topics", [])
    if not topics:
        return

    console.print("\n[bold cyan]Suggested Topics:[/bold cyan]")
    for index, topic in enumerate(topics, 1):
        console.print(f"  {index}. {topic.get('question', '')}")


@click.command("overview")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set). Supports partial IDs.",
)
@click.option("--topics", is_flag=True, help="Include suggested topics")
@json_option
@manifest_risk_guard("overview")
@with_client
def overview_cmd(ctx, notebook_id, topics, json_output, client_auth):
    """Get a lightweight remote notebook overview."""
    notebook_target = require_notebook(notebook_id)

    async def _run():
        started = time.perf_counter()
        trace_id, _ = _trace_and_run_id(ctx, _OVERVIEW_RPC_BINDING.mode)
        async with NotebookLMClient(client_auth) as client:
            resolved_id = await resolve_notebook_id(client, notebook_target)
            state = _record_overview_start(
                trace_id=trace_id,
                notebook_id=resolved_id,
                include_topics=topics,
            )
            try:
                description = await client.notebooks.get_description(resolved_id)
            except Exception:
                _record_overview_failure(state)
                raise

        result_payload = _description_payload(description, include_topics=topics)
        _record_overview_result(state, result_payload=result_payload)
        elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
        emit_workflow_output(
            json_output=json_output,
            build_json=lambda: _overview_envelope(
                ctx,
                notebook_id=resolved_id,
                profile_id=state.profile_id,
                result_payload=result_payload,
                elapsed_ms=elapsed_ms,
            ),
            emit_json=json_output_response,
            render_human=lambda: _render_overview_payload(result_payload),
        )

    return _run()


def register_overview_commands(cli) -> None:
    """Register the canonical overview workflow root."""
    cli.add_command(overview_cmd)
