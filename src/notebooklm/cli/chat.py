"""Chat CLI commands.

Commands:
    ask        Ask a notebook a question
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import time
from typing import Any
import uuid

import click

from ..client import NotebookLMClient
from ..contracts import Diagnostics, Envelope, Freshness, Route, Transport
from ..contracts.intents import Intent
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
from ..observability import bind_trace
from ..profiles.manager import ProfileManager
from ..types import AskResult, ChatReference
from ..workflows.ask import (
    NotebookTargetCandidate,
    determine_conversation_id,
    get_latest_conversation_from_server,
    resolve_notebook_target,
)
from ..workflows.runtime import (
    emit_workflow_output,
    record_cache_event,
    record_route_resolution_event,
    workflow_cache_updates,
)
from .helpers import (
    console,
    get_current_conversation,
    get_current_notebook,
    json_output_response,
    require_notebook,
    resolve_notebook_id,
    resolve_source_ids,
    set_current_conversation,
    with_client,
)
from .session import _inspect_auth_state, _trace_and_run_id


_ASK_RPC_BINDING = RPC_MAP[("QUERY", "answer")]
_ASK_CACHE_MODE = "smart"
_ASK_SOURCE_OF_TRUTH = "remote_http"
_ASK_ROUTE_REASON = "Structured ask command uses the remote query transport."
_ASK_CACHE_HIT_SOURCE_OF_TRUTH = "local_cache"
_ASK_CACHE_HIT_ROUTE_REASON = "Exact prompt/source/fingerprint match reused a cached ask result."
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AskPersistenceState:
    query_run_id: str
    trace_id: str
    profile_id: str
    notebook_id: str
    question: str
    prompt_hash: str
    settings_hash: str
    notebook_fingerprint: str | None
    source_of_truth: str
    route_reason: str
    started_at: str
    reused_from: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ask_settings_hash(source_ids: tuple[str, ...]) -> str:
    return _hash_text(_canonical_json({"source_ids": sorted(source_ids)}))


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


def _cached_notebook_targets(connection) -> list[NotebookTargetCandidate]:
    profile_id = _active_profile_id(connection)
    return [
        NotebookTargetCandidate(
            notebook_id=notebook.notebook_id,
            title=notebook.title,
            normalized_title=notebook.normalized_title,
        )
        for notebook in NotebookRepository(connection).list_for_profile(profile_id)
    ]


async def _resolve_ask_notebook_id(
    client,
    *,
    notebook_target: str,
    explicit_notebook_id: str | None,
) -> str:
    with connect_db() as connection:
        try:
            resolution = resolve_notebook_target(
                explicit_notebook_id=explicit_notebook_id,
                current_notebook_id=get_current_notebook(),
                cached_candidates=_cached_notebook_targets(connection),
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if resolution.target is None:
        raise click.ClickException("No notebook specified for ask.")
    if explicit_notebook_id is not None and resolution.source == "local_cache":
        if resolution.target != explicit_notebook_id:
            return resolution.target
    return await resolve_notebook_id(client, notebook_target)


def _query_run_record(
    state: _AskPersistenceState,
    *,
    status: str,
    ended_at: str | None = None,
) -> QueryRunRecord:
    return QueryRunRecord(
        id=state.query_run_id,
        trace_id=state.trace_id,
        profile_id=state.profile_id,
        notebook_id=state.notebook_id,
        intent="ask",
        mode=_ASK_RPC_BINDING.mode,
        prompt_text=state.question,
        prompt_hash=state.prompt_hash,
        settings_hash=state.settings_hash,
        notebook_fingerprint=state.notebook_fingerprint,
        cache_policy=_ASK_CACHE_MODE,
        route_reason=state.route_reason,
        source_of_truth=state.source_of_truth,
        started_at=state.started_at,
        ended_at=ended_at,
        status=status,
        reused_from=state.reused_from,
    )


def _record_query_run_start(
    *,
    trace_id: str,
    query_run_id: str,
    notebook_id: str,
    question: str,
    settings_hash: str,
    source_of_truth: str = _ASK_SOURCE_OF_TRUTH,
    route_reason: str = _ASK_ROUTE_REASON,
    cache_event_kind: str = "cache.miss",
    reused_from: str | None = None,
) -> _AskPersistenceState | None:
    try:
        with connect_db() as connection:
            profile_id = _active_profile_id(connection)
            notebook = _ensure_cached_notebook(
                connection,
                notebook_id=notebook_id,
                profile_id=profile_id,
            )
            state = _AskPersistenceState(
                query_run_id=query_run_id,
                trace_id=trace_id,
                profile_id=notebook.profile_id if notebook is not None else profile_id,
                notebook_id=notebook_id,
                question=question,
                prompt_hash=_hash_text(question),
                settings_hash=settings_hash,
                notebook_fingerprint=_resolve_notebook_fingerprint(connection, notebook),
                source_of_truth=source_of_truth,
                route_reason=route_reason,
                started_at=_utc_now(),
                reused_from=reused_from,
            )
            QueryRunRepository(connection).upsert(_query_run_record(state, status="running"))
            record_route_resolution_event(
                connection,
                trace_id=trace_id,
                run_id=query_run_id,
                command="ask",
                mode=_ASK_RPC_BINDING.mode,
                notebook_id=notebook_id,
                profile_id=state.profile_id,
                cache_mode=_ASK_CACHE_MODE,
                reason=route_reason,
                source_of_truth=source_of_truth,
            )
            record_cache_event(
                connection,
                trace_id=trace_id,
                run_id=query_run_id,
                kind=cache_event_kind,
                command="ask",
                entity="query_results",
                notebook_id=notebook_id,
                notebook_fingerprint=state.notebook_fingerprint,
                prompt_hash=state.prompt_hash,
            )
            return state
    except Exception as exc:
        logger.debug("Failed to record ask query-run start: %s", exc)
        return None


def _record_query_run_success(state: _AskPersistenceState | None, result) -> None:
    if state is None:
        return
    try:
        payload = asdict(result)
        payload.pop("raw_response", None)
        citations = [asdict(reference) for reference in result.references]
        completed_at = _utc_now()
        with connect_db() as connection:
            QueryRunRepository(connection).upsert(
                _query_run_record(state, status="completed", ended_at=completed_at)
            )
            QueryResultRepository(connection).upsert(
                QueryResultRecord(
                    query_run_id=state.query_run_id,
                    result_type="answer",
                    answer_text=result.answer,
                    citations_json=_canonical_json(citations),
                    result_json=_canonical_json(payload),
                    created_at=completed_at,
                )
            )
    except Exception as exc:
        logger.debug("Failed to record ask query-run success: %s", exc)
        return


def _record_query_run_failure(state: _AskPersistenceState | None) -> None:
    if state is None:
        return
    try:
        with connect_db() as connection:
            QueryRunRepository(connection).upsert(
                _query_run_record(state, status="failed", ended_at=_utc_now())
            )
    except Exception as exc:
        logger.debug("Failed to record ask query-run failure: %s", exc)
        return


def _deserialize_ask_result(result_json: str) -> AskResult:
    payload = json.loads(result_json)
    references = [ChatReference(**reference) for reference in payload.pop("references", [])]
    payload["references"] = references
    payload["raw_response"] = ""
    return AskResult(**payload)


def _lookup_reusable_ask_result(
    connection,
    *,
    notebook_id: str,
    prompt_hash: str,
    settings_hash: str,
    notebook_fingerprint: str | None,
) -> tuple[str, AskResult] | None:
    if notebook_fingerprint is None:
        return None

    row = connection.execute(
        """
        SELECT
            query_runs.id AS run_id,
            query_results.result_json AS result_json
        FROM query_runs
        JOIN query_results
            ON query_results.query_run_id = query_runs.id
        WHERE query_runs.notebook_id = ?
          AND query_runs.intent = 'ask'
          AND query_runs.status = 'completed'
          AND query_runs.prompt_hash = ?
          AND query_runs.settings_hash = ?
          AND query_runs.notebook_fingerprint = ?
        ORDER BY COALESCE(query_runs.ended_at, query_runs.started_at) DESC, query_runs.id DESC
        LIMIT 1
        """,
        (notebook_id, prompt_hash, settings_hash, notebook_fingerprint),
    ).fetchone()
    if row is None or row["result_json"] is None:
        return None
    return row["run_id"], _deserialize_ask_result(row["result_json"])


def _ask_json_response(
    ctx: click.Context,
    *,
    notebook_id: str,
    result_payload: dict[str, Any],
    elapsed_ms: int,
    source_of_truth: str = _ASK_SOURCE_OF_TRUTH,
    route_reason: str = _ASK_ROUTE_REASON,
    used_cached_result: bool = False,
) -> dict:
    """Wrap ask results in the canonical JSON envelope."""
    try:
        _, profile_id = _inspect_auth_state(ctx)
    except Exception:
        profile_id = "default"

    trace_id, run_id = _trace_and_run_id(ctx, _ASK_RPC_BINDING.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(_ASK_RPC_BINDING.intent),
            mode=_ASK_RPC_BINDING.mode,
            notebook_id=notebook_id,
            profile_id=profile_id,
            source_of_truth=source_of_truth,
            cache_mode="smart",
            reason=route_reason,
            transport=Transport(kind="local")
            if used_cached_result
            else Transport(
                kind=_ASK_RPC_BINDING.transport_kind,
                endpoint=_ASK_RPC_BINDING.endpoint,
                rpcid=_ASK_RPC_BINDING.rpcid,
              ),
        ),
        freshness=Freshness(used_cached_result=True) if used_cached_result else None,
        result=result_payload,
        cache_updates=workflow_cache_updates("query_runs", "query_results", "run_events"),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _ask_result_payload(result: AskResult) -> dict[str, Any]:
    payload = asdict(result)
    payload.pop("raw_response", None)
    return payload


def _ask_conversation_label(
    payload: dict[str, Any],
    *,
    reused_cached_result: bool,
    resumed_from_server: bool,
) -> str | None:
    conversation_id = payload.get("conversation_id")
    if not conversation_id:
        return None
    if reused_cached_result:
        return f"Conversation: {conversation_id} (cached reuse)"
    if payload.get("is_follow_up") and resumed_from_server:
        return f"Resumed conversation: {conversation_id}"
    if payload.get("is_follow_up"):
        return f"Conversation: {conversation_id} (turn {payload.get('turn_number') or '?'})"
    return f"New conversation: {conversation_id}"


def _render_ask_result(
    payload: dict[str, Any],
    *,
    reused_cached_result: bool = False,
    resumed_from_server: bool = False,
) -> None:
    if reused_cached_result:
        console.print("[dim]Reused exact cached answer from local history.[/dim]")
    console.print("[bold cyan]Answer:[/bold cyan]")
    console.print(payload.get("answer", ""))
    conversation_label = _ask_conversation_label(
        payload,
        reused_cached_result=reused_cached_result,
        resumed_from_server=resumed_from_server,
    )
    if conversation_label:
        console.print(f"\n[dim]{conversation_label}[/dim]")


def register_chat_commands(cli):
    """Register chat commands on the main CLI group."""

    @cli.command("ask")
    @click.argument("question")
    @click.option(
        "-n",
        "--notebook",
        "notebook_id",
        default=None,
        help="Notebook ID (uses current if not set)",
    )
    @click.option("--conversation-id", "-c", default=None, help="Continue a specific conversation")
    @click.option(
        "--source",
        "-s",
        "source_ids",
        multiple=True,
        help="Limit to specific source IDs (can be repeated)",
    )
    @click.option(
        "--json", "json_output", is_flag=True, help="Output as JSON (includes references)"
    )
    @with_client
    def ask_cmd(
        ctx,
        question,
        notebook_id,
        conversation_id,
        source_ids,
        json_output,
        client_auth,
    ):
        """Ask a notebook a question.

        By default, the CLI continues the cached conversation for the current
        notebook when possible. If there is no cached conversation, it asks the
        server for the most recent conversation and resumes that thread when
        available. Use --conversation-id to continue a specific thread.

        The answer includes inline citations like [1], [2] that reference
        sources. Use --json to get structured output with source IDs for each
        reference.

        \b
        Example:
          notebooklm ask "what are the main themes?"
          notebooklm ask -c <id> "continue this one"
          notebooklm ask -s src_001 -s src_002 "question about specific sources"
          notebooklm ask "explain X" --json             # Get answer with source references
        """
        nb_id = require_notebook(notebook_id)
        started_at = time.perf_counter()

        async def _run():
            async with NotebookLMClient(client_auth) as client:
                trace_id, _ = _trace_and_run_id(ctx, _ASK_RPC_BINDING.mode)
                query_run_id = _query_run_id(trace_id)
                trace = ctx.obj.get("trace") if ctx.obj else None
                bound_trace = trace.with_run_id(query_run_id) if trace is not None else None
                if ctx.obj is not None and bound_trace is not None:
                    ctx.obj["trace"] = bound_trace

                with (
                    bind_trace(bound_trace)
                    if bound_trace is not None
                    else bind_trace(trace_id=trace_id, run_id=query_run_id)
                ):
                    resolved_notebook_id = await _resolve_ask_notebook_id(
                        client,
                        notebook_target=nb_id,
                        explicit_notebook_id=notebook_id,
                    )
                    def notice(message: str) -> None:
                        console.print(f"[dim]{message}[/dim]")

                    effective_conversation_id = determine_conversation_id(
                        explicit_conversation_id=conversation_id,
                        explicit_notebook_id=notebook_id,
                        resolved_notebook_id=resolved_notebook_id,
                        json_output=json_output,
                        get_current_notebook=get_current_notebook,
                        get_current_conversation=get_current_conversation,
                        emit_notice=notice,
                    )
                    resumed_from_server = False
                    if not effective_conversation_id:
                        effective_conversation_id = await get_latest_conversation_from_server(
                            client,
                            resolved_notebook_id,
                            json_output=json_output,
                            emit_notice=notice,
                        )
                        resumed_from_server = effective_conversation_id is not None

                    settings_hash = _ask_settings_hash(source_ids)
                    reused_from: str | None = None
                    if effective_conversation_id is None:
                        with connect_db() as connection:
                            notebook = NotebookRepository(connection).get(resolved_notebook_id)
                            reusable = _lookup_reusable_ask_result(
                                connection,
                                notebook_id=resolved_notebook_id,
                                prompt_hash=_hash_text(question),
                                settings_hash=settings_hash,
                                notebook_fingerprint=_resolve_notebook_fingerprint(
                                    connection,
                                    notebook,
                                ),
                            )
                        if reusable is not None:
                            reused_from, result = reusable
                            result_payload = _ask_result_payload(result)
                            persistence_state = _record_query_run_start(
                                trace_id=trace_id,
                                query_run_id=query_run_id,
                                notebook_id=resolved_notebook_id,
                                question=question,
                                settings_hash=settings_hash,
                                source_of_truth=_ASK_CACHE_HIT_SOURCE_OF_TRUTH,
                                route_reason=_ASK_CACHE_HIT_ROUTE_REASON,
                                cache_event_kind="cache.hit",
                                reused_from=reused_from,
                            )
                            _record_query_run_success(persistence_state, result)

                            if result.conversation_id:
                                set_current_conversation(result.conversation_id)

                            elapsed_ms = max(
                                0, int((time.perf_counter() - started_at) * 1000)
                            )
                            emit_workflow_output(
                                json_output=json_output,
                                build_json=lambda: _ask_json_response(
                                    ctx,
                                    notebook_id=resolved_notebook_id,
                                    result_payload=result_payload,
                                    elapsed_ms=elapsed_ms,
                                    source_of_truth=_ASK_CACHE_HIT_SOURCE_OF_TRUTH,
                                    route_reason=_ASK_CACHE_HIT_ROUTE_REASON,
                                    used_cached_result=True,
                                ),
                                emit_json=json_output_response,
                                render_human=lambda: _render_ask_result(
                                    result_payload,
                                    reused_cached_result=True,
                                ),
                            )
                            return

                    persistence_state = _record_query_run_start(
                        trace_id=trace_id,
                        query_run_id=query_run_id,
                        notebook_id=resolved_notebook_id,
                        question=question,
                        settings_hash=settings_hash,
                    )
                    try:
                        resolved_source_ids = await resolve_source_ids(
                            client,
                            resolved_notebook_id,
                            source_ids,
                        )
                        result = await client.chat.ask(
                            resolved_notebook_id,
                            question,
                            source_ids=resolved_source_ids,
                            conversation_id=effective_conversation_id,
                        )
                    except Exception:
                        _record_query_run_failure(persistence_state)
                        raise
                _record_query_run_success(persistence_state, result)

                if result.conversation_id:
                    set_current_conversation(result.conversation_id)

                result_payload = _ask_result_payload(result)
                elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
                emit_workflow_output(
                    json_output=json_output,
                    build_json=lambda: _ask_json_response(
                        ctx,
                        notebook_id=resolved_notebook_id,
                        result_payload=result_payload,
                        elapsed_ms=elapsed_ms,
                    ),
                    emit_json=json_output_response,
                    render_human=lambda: _render_ask_result(
                        result_payload,
                        resumed_from_server=resumed_from_server,
                    ),
                )

        return _run()
