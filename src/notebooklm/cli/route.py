"""Experimental route diagnostics commands."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any

import click
from rich.table import Table

from ..contracts import Diagnostics, Envelope, Intent, Route as RouteEnvelope, Transport
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..local.repositories import NotebookRepository
from ..profiles.manager import ProfileManager
from ..router.classify import IntentClassification, classify_request
from ..router.execute import AgentExecutionPlan, build_execution_plan
from ..router.freshness import (
    CacheModeDecision,
    CacheModeViolationError,
    FreshnessSnapshot,
    MetadataScope,
    collect_freshness_snapshot,
    decide_cache_mode,
    normalize_cache_mode,
)
from ..router.resolve import (
    NotebookResolution,
    NotebookResolutionCandidate,
    RankedNotebookCandidate,
    resolve_notebook_target,
)
from ..router.structured import StructuredCommandMatch, match_structured_command
from .helpers import console, get_current_notebook, json_output_response
from .session import _trace_and_run_id

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DRY_RUN_MODE = "route_dry_run"
_EXPLAIN_MODE = "route_explain"
_DEFAULT_COMMAND_NAME = "_dry_run"
_STRUCTURED_SKIP_REASON = (
    "request already parses as a shipped CLI leaf, so NL classification and "
    "notebook-routing heuristics are skipped."
)
_PENDING_FRESHNESS_REASON = (
    "pending notebook-detail freshness because no target notebook was resolved yet."
)


@dataclass(frozen=True)
class RouteAnalysis:
    """Resolved route-analysis payload for one request."""

    request: str
    profile_id: str
    cache_mode: str
    explicit_notebook_id: str | None
    current_notebook_id: str | None
    structured_match: StructuredCommandMatch | None
    classification: IntentClassification | None = None
    resolution: NotebookResolution | None = None
    metadata_scope: MetadataScope | None = None
    scope_note: str | None = None
    freshness: FreshnessSnapshot | None = None
    decision: CacheModeDecision | None = None
    blocked_reason: str | None = None
    execution_plan: AgentExecutionPlan | None = None


class RouteGroup(click.Group):
    """Click group that accepts `route "request" --dry-run` plus subcommands."""

    default_command_name = _DEFAULT_COMMAND_NAME

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        argv = list(args)
        if self._should_prepend_default_command(ctx, argv):
            argv.insert(0, self.default_command_name)
        return super().parse_args(ctx, argv)

    def _should_prepend_default_command(self, ctx: click.Context, args: list[str]) -> bool:
        if not args:
            return False
        if "--help" in args or "-h" in args:
            return False

        command_names = {
            name
            for name in self.list_commands(ctx)
            if (command := self.get_command(ctx, name)) is not None and not command.hidden
        }

        for token in args:
            if token.startswith("-"):
                continue
            return token not in command_names
        return False


@click.group(cls=RouteGroup)
def route() -> None:
    """Explain experimental routing decisions without executing them.

    Examples:
      notebooklm route "summarize current notebook" --dry-run
      notebooklm route explain "which notebooks have stale drive sources?"
    """


def _active_profile_id(connection) -> str:
    manager = ProfileManager(connection)
    active = manager.get_active_profile()
    if active is not None:
        return active.profile_id
    profiles = manager.list_profiles()
    if len(profiles) == 1:
        return profiles[0].profile_id
    return "default"


def _cached_notebook_candidates(connection, profile_id: str) -> list[NotebookResolutionCandidate]:
    repository = NotebookRepository(connection)
    candidates: list[NotebookResolutionCandidate] = []
    for record in repository.list_for_profile(profile_id):
        if record.tombstoned_at is not None:
            continue
        candidates.append(
            NotebookResolutionCandidate(
                notebook_id=record.notebook_id,
                title=record.title,
                normalized_title=record.normalized_title,
            )
        )
    return candidates


def _metadata_scope_for_request(
    *,
    intent: Intent,
    request: str,
    resolved_notebook_id: str | None,
) -> tuple[MetadataScope | None, str]:
    if intent is not Intent.LOCAL_METADATA:
        return None, "Remote/query-style intents do not use metadata-scope gating."

    tokens = set(_TOKEN_RE.findall(request.casefold()))
    if {"source", "sources"} & tokens and resolved_notebook_id is None:
        return (
            None,
            "This request inspects source metadata across notebooks, so detail freshness "
            "cannot be evaluated until a notebook target is known.",
        )
    if resolved_notebook_id is not None and (
        {"show", "source", "sources", "guide"} & tokens or "current" in tokens
    ):
        return "notebook_detail", "This request depends on notebook detail/source metadata."
    return "notebook_index", "This request can be answered from notebook-index metadata."


def _workflow_label(intent: Intent) -> str:
    labels = {
        Intent.LOCAL_METADATA: "local metadata inspection",
        Intent.REMOTE_METADATA: "remote metadata sync",
        Intent.QUERY: "query workflow",
        Intent.GENERATION: "generation workflow",
        Intent.RESEARCH: "research workflow",
    }
    return labels.get(intent, intent.value.casefold().replace("_", " "))


def _age_label(age_s: int | None) -> str:
    if age_s is None:
        return "unknown"
    return f"{age_s}s"


def _bool_label(value: bool | None) -> str:
    if value is None:
        return "(pending)"
    return "true" if value else "false"


def _transport_label(transport: Transport | None) -> str:
    if transport is None:
        return "(pending)"
    return transport.kind


def _render_candidates(candidates: tuple[RankedNotebookCandidate, ...]) -> None:
    if not candidates:
        return

    table = Table(title="Ranked candidates")
    table.add_column("Notebook ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Score", style="magenta")
    table.add_column("Reason", style="yellow")
    for candidate in candidates:
        table.add_row(
            candidate.notebook_id,
            candidate.title,
            f"{candidate.score:.2f}",
            candidate.reason,
        )
    console.print(table)


def _resolve_route_analysis(
    *,
    request: str,
    explicit_notebook_id: str | None,
    cache_mode: str,
) -> RouteAnalysis:
    effective_cache_mode = normalize_cache_mode(cache_mode)
    with connect_db() as connection:
        profile_id = _active_profile_id(connection)
        current_notebook_id = get_current_notebook()
        cached_candidates = _cached_notebook_candidates(connection, profile_id)

        structured_match = match_structured_command(request)
        if structured_match is not None:
            return RouteAnalysis(
                request=request,
                profile_id=profile_id,
                cache_mode=effective_cache_mode,
                explicit_notebook_id=explicit_notebook_id,
                current_notebook_id=current_notebook_id,
                structured_match=structured_match,
            )

        classification = classify_request(request)
        resolution = resolve_notebook_target(
            request=request,
            explicit_notebook_id=explicit_notebook_id,
            current_notebook_id=current_notebook_id,
            cached_candidates=cached_candidates,
        )
        metadata_scope, scope_note = _metadata_scope_for_request(
            intent=classification.intent,
            request=request,
            resolved_notebook_id=resolution.notebook_id,
        )
        freshness = collect_freshness_snapshot(
            connection,
            profile_id=profile_id,
            notebook_id=resolution.notebook_id,
        )

    decision = None
    blocked_reason = None
    if classification.intent is not Intent.LOCAL_METADATA or metadata_scope is not None:
        try:
            decision = decide_cache_mode(
                classification.intent,
                snapshot=freshness,
                cache_mode=effective_cache_mode,
                metadata_scope=metadata_scope,
            )
        except CacheModeViolationError as exc:
            blocked_reason = str(exc)

    execution_plan = build_execution_plan(
        request=request,
        classification=classification,
        resolution=resolution,
        allow_partial_resolution=True,
    )
    return RouteAnalysis(
        request=request,
        profile_id=profile_id,
        cache_mode=effective_cache_mode,
        explicit_notebook_id=explicit_notebook_id,
        current_notebook_id=current_notebook_id,
        structured_match=None,
        classification=classification,
        resolution=resolution,
        metadata_scope=metadata_scope,
        scope_note=scope_note,
        freshness=freshness,
        decision=decision,
        blocked_reason=blocked_reason,
        execution_plan=execution_plan,
    )


def _analysis_transport(analysis: RouteAnalysis) -> Transport | None:
    if analysis.structured_match is not None:
        return None
    if analysis.execution_plan is not None and analysis.classification is not None:
        binding = RPC_MAP.get((analysis.classification.intent.value, analysis.execution_plan.mode))
        if binding is not None:
            return Transport(
                kind=binding.transport_kind,
                endpoint=binding.endpoint,
                rpcid=binding.rpcid,
            )
    if analysis.decision is not None:
        return Transport(kind="local" if analysis.decision.source_of_truth == "local_cache" else "httpx")
    return None


def _structured_payload(structured_match: StructuredCommandMatch) -> dict[str, Any]:
    return {
        "command_path": list(structured_match.command_path),
        "argv": list(structured_match.argv),
        "arguments": list(structured_match.arguments),
        "reason": _STRUCTURED_SKIP_REASON,
    }


def _intent_payload(classification: IntentClassification) -> dict[str, Any]:
    return {
        "value": classification.intent.value,
        "confidence": classification.confidence,
        "matched_terms": list(classification.matched_terms),
        "rationale": classification.rationale,
    }


def _resolution_payload(resolution: NotebookResolution) -> dict[str, Any]:
    return {
        "status": resolution.status,
        "source": resolution.source,
        "notebook_id": resolution.notebook_id,
        "matched_text": resolution.matched_text,
        "rationale": resolution.rationale,
        "candidates": [
            {
                "notebook_id": candidate.notebook_id,
                "title": candidate.title,
                "score": candidate.score,
                "reason": candidate.reason,
            }
            for candidate in resolution.candidates
        ],
    }


def _plan_payload(plan: AgentExecutionPlan) -> dict[str, Any]:
    return {
        "command_name": plan.command_name,
        "mode": plan.mode,
        "notebook_id": plan.notebook_id,
        "resolution_source": plan.resolution_source,
        "requires_notebook": plan.requires_notebook,
        "waitable": plan.waitable,
        "arguments": plan.arguments,
        "rationale": plan.rationale,
    }


def _freshness_payload(analysis: RouteAnalysis) -> dict[str, Any] | None:
    if analysis.freshness is None:
        return None
    return {
        "metadata_scope": analysis.metadata_scope,
        "scope_note": analysis.scope_note,
        "notebook_index_synced_at": analysis.freshness.notebook_index_synced_at,
        "notebook_detail_synced_at": analysis.freshness.notebook_detail_synced_at,
        "notebook_index_age_s": analysis.freshness.notebook_index_age_s,
        "notebook_detail_age_s": analysis.freshness.notebook_detail_age_s,
        "notebook_index_is_fresh": analysis.freshness.notebook_index_is_fresh,
        "notebook_detail_is_fresh": analysis.freshness.notebook_detail_is_fresh,
    }


def _cache_decision_payload(analysis: RouteAnalysis) -> dict[str, Any] | None:
    if analysis.structured_match is not None:
        return None

    if analysis.decision is not None:
        status = "resolved"
        reason = analysis.decision.reason
        source_of_truth = analysis.decision.source_of_truth
        used_cached_result = analysis.decision.used_cached_result
        should_sync_metadata = analysis.decision.should_sync_metadata
    elif analysis.blocked_reason is not None:
        status = "blocked"
        reason = analysis.blocked_reason
        source_of_truth = None
        used_cached_result = None
        should_sync_metadata = None
    else:
        status = "pending"
        reason = _PENDING_FRESHNESS_REASON
        source_of_truth = None
        used_cached_result = None
        should_sync_metadata = None

    transport = _analysis_transport(analysis)
    return {
        "status": status,
        "source_of_truth": source_of_truth,
        "used_cached_result": used_cached_result,
        "should_sync_metadata": should_sync_metadata,
        "reason": reason,
        "transport": None
        if transport is None
        else {
            "kind": transport.kind,
            "endpoint": transport.endpoint,
            "rpcid": transport.rpcid,
        },
    }


def _analysis_payload(analysis: RouteAnalysis, *, view: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "view": view,
        "request": analysis.request,
        "cache_mode": analysis.cache_mode,
        "context": {
            "profile_id": analysis.profile_id,
            "explicit_notebook_id": analysis.explicit_notebook_id,
            "current_notebook_id": analysis.current_notebook_id,
        },
    }
    if analysis.structured_match is not None:
        payload["structured_command"] = _structured_payload(analysis.structured_match)
        return payload

    assert analysis.classification is not None
    assert analysis.resolution is not None
    assert analysis.execution_plan is not None

    payload["intent"] = _intent_payload(analysis.classification)
    payload["notebook_resolution"] = _resolution_payload(analysis.resolution)
    payload["execution_plan"] = _plan_payload(analysis.execution_plan)
    payload["freshness_snapshot"] = _freshness_payload(analysis)
    payload["cache_decision"] = _cache_decision_payload(analysis)
    return payload


def _diagnostic_envelope(
    ctx: click.Context,
    *,
    analysis: RouteAnalysis,
    mode: str,
    elapsed_ms: int,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, mode)
    freshness = None
    if analysis.freshness is not None:
        used_cached_result = analysis.decision.used_cached_result if analysis.decision is not None else False
        freshness = analysis.freshness.to_contract(used_cached_result=used_cached_result)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=RouteEnvelope(
            intent=Intent.LOCAL_METADATA,
            mode=mode,
            notebook_id=analysis.resolution.notebook_id if analysis.resolution is not None else None,
            profile_id=analysis.profile_id,
            source_of_truth="local_cache",
            cache_mode=analysis.cache_mode,
            reason=(
                "Preview the experimental routing decision without executing it."
                if mode == _DRY_RUN_MODE
                else "Explain the experimental routing logic without executing it."
            ),
            transport=Transport(kind="local"),
        ),
        result=_analysis_payload(
            analysis,
            view="dry_run" if mode == _DRY_RUN_MODE else "explain",
        ),
        freshness=freshness,
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_dry_run(analysis: RouteAnalysis) -> None:
    console.print("[bold]Route dry run[/bold]")
    console.print(f"Request: {analysis.request}")
    console.print(f"Cache mode: {analysis.cache_mode}")
    if analysis.structured_match is not None:
        console.print("[bold]Structured command wins[/bold]")
        console.print(f"Command path: {' '.join(analysis.structured_match.command_path)}")
        console.print(
            "Arguments: "
            + (" ".join(analysis.structured_match.arguments) if analysis.structured_match.arguments else "(none)")
        )
        console.print(f"Decision: {_STRUCTURED_SKIP_REASON}")
        return

    assert analysis.classification is not None
    assert analysis.resolution is not None
    assert analysis.execution_plan is not None

    cache_decision = _cache_decision_payload(analysis)
    assert cache_decision is not None

    console.print(f"Intent: {analysis.classification.intent.value} ({analysis.classification.confidence:.2f})")
    console.print(
        "Target notebook: "
        f"{analysis.resolution.notebook_id or '(none)'} "
        f"[{analysis.resolution.status} via {analysis.resolution.source}]"
    )
    console.print(f"Command: {analysis.execution_plan.command_name}")
    console.print(f"Mode: {analysis.execution_plan.mode}")
    console.print(
        "Freshness: "
        f"index={_age_label(analysis.freshness.notebook_index_age_s if analysis.freshness else None)}, "
        f"detail={_age_label(analysis.freshness.notebook_detail_age_s if analysis.freshness else None)}"
    )
    console.print(f"Transport: {_transport_label(_analysis_transport(analysis))}")
    console.print(f"Source of truth: {cache_decision['source_of_truth'] or '(pending)'}")
    console.print(f"Used cached result: {_bool_label(cache_decision['used_cached_result'])}")
    console.print(f"Should sync metadata: {_bool_label(cache_decision['should_sync_metadata'])}")
    console.print(f"Decision: {cache_decision['status']}")
    console.print(f"Reason: {cache_decision['reason']}")
    _render_candidates(analysis.resolution.candidates)


def _render_explain(analysis: RouteAnalysis) -> None:
    console.print("[bold]Route explanation[/bold]")
    console.print(f"Request: {analysis.request}")
    console.print(f"Profile: {analysis.profile_id}")
    console.print(f"Cache mode: {analysis.cache_mode}")
    if analysis.explicit_notebook_id:
        console.print(f"Explicit --notebook: {analysis.explicit_notebook_id}")
    if analysis.current_notebook_id:
        console.print(f"Current notebook context: {analysis.current_notebook_id}")

    if analysis.structured_match is not None:
        console.print("[bold]Structured command wins[/bold]")
        console.print(f"Command path: {' '.join(analysis.structured_match.command_path)}")
        console.print(
            "Arguments: "
            + (" ".join(analysis.structured_match.arguments) if analysis.structured_match.arguments else "(none)")
        )
        console.print(f"Explanation: {_STRUCTURED_SKIP_REASON}")
        return

    assert analysis.classification is not None
    assert analysis.resolution is not None
    assert analysis.execution_plan is not None

    console.print("[bold]Intent classification[/bold]")
    console.print(f"Intent: {analysis.classification.intent.value}")
    console.print(f"Workflow: {_workflow_label(analysis.classification.intent)}")
    console.print(f"Confidence: {analysis.classification.confidence:.2f}")
    console.print(
        "Matched terms: "
        + (
            ", ".join(analysis.classification.matched_terms)
            if analysis.classification.matched_terms
            else "(none)"
        )
    )
    console.print(f"Rationale: {analysis.classification.rationale}")

    console.print("[bold]Notebook resolution[/bold]")
    console.print(f"Status: {analysis.resolution.status}")
    console.print(f"Source: {analysis.resolution.source}")
    console.print(f"Notebook ID: {analysis.resolution.notebook_id or '(none)'}")
    console.print(f"Matched text: {analysis.resolution.matched_text or '(none)'}")
    console.print(f"Rationale: {analysis.resolution.rationale}")
    _render_candidates(analysis.resolution.candidates)

    console.print("[bold]Execution plan[/bold]")
    console.print(f"Command: {analysis.execution_plan.command_name}")
    console.print(f"Mode: {analysis.execution_plan.mode}")
    console.print(f"Requires notebook: {analysis.execution_plan.requires_notebook}")
    console.print(f"Waitable: {analysis.execution_plan.waitable}")
    console.print(f"Transport: {_transport_label(_analysis_transport(analysis))}")
    console.print(f"Rationale: {analysis.execution_plan.rationale}")

    console.print("[bold]Cache / freshness[/bold]")
    console.print(f"Metadata scope: {analysis.metadata_scope or '(pending)'}")
    console.print(f"Scope note: {analysis.scope_note}")
    console.print(
        f"Notebook index age: {_age_label(analysis.freshness.notebook_index_age_s if analysis.freshness else None)}"
    )
    console.print(
        f"Notebook detail age: {_age_label(analysis.freshness.notebook_detail_age_s if analysis.freshness else None)}"
    )

    if analysis.decision is not None:
        console.print(f"Source of truth: {analysis.decision.source_of_truth}")
        console.print(f"Used cached result: {analysis.decision.used_cached_result}")
        console.print(f"Should sync metadata: {analysis.decision.should_sync_metadata}")
        console.print(f"Decision rationale: {analysis.decision.reason}")
    elif analysis.blocked_reason is not None:
        console.print(f"Blocked by cache mode: {analysis.blocked_reason}")
    else:
        console.print(f"Decision: {_PENDING_FRESHNESS_REASON}")


def _emit_route_output(
    ctx: click.Context,
    *,
    request: str,
    explicit_notebook_id: str | None,
    cache_mode: str,
    json_output: bool,
    verbose: bool,
) -> None:
    started_at = time.perf_counter()
    analysis = _resolve_route_analysis(
        request=request,
        explicit_notebook_id=explicit_notebook_id,
        cache_mode=cache_mode,
    )
    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if json_output:
        json_output_response(
            _diagnostic_envelope(
                ctx,
                analysis=analysis,
                mode=_EXPLAIN_MODE if verbose else _DRY_RUN_MODE,
                elapsed_ms=elapsed_ms,
            )
        )
        return
    if verbose:
        _render_explain(analysis)
    else:
        _render_dry_run(analysis)


@route.command(_DEFAULT_COMMAND_NAME, hidden=True)
@click.argument("request")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview the routing decision without executing anything.",
)
@click.option(
    "--notebook",
    "explicit_notebook_id",
    help="Optional notebook selector to feed into notebook resolution.",
)
@click.option(
    "--cache-mode",
    type=click.Choice(["smart", "refresh", "offline", "network"], case_sensitive=False),
    default="smart",
    show_default=True,
    help="Evaluate the routing decision under one cache mode.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@click.pass_context
def route_dry_run(
    ctx: click.Context,
    request: str,
    dry_run: bool,
    explicit_notebook_id: str | None,
    cache_mode: str,
    json_output: bool,
) -> None:
    """Preview the experimental routing decision for one natural-language request."""
    if not dry_run:
        raise click.ClickException(
            "Route execution is not implemented. Use `notebooklm route \"request\" --dry-run` "
            "or `notebooklm route explain \"request\"`."
        )
    _emit_route_output(
        ctx,
        request=request,
        explicit_notebook_id=explicit_notebook_id,
        cache_mode=cache_mode,
        json_output=json_output,
        verbose=False,
    )


@route.command("explain")
@click.argument("request")
@click.option(
    "--notebook",
    "explicit_notebook_id",
    help="Optional notebook selector to feed into notebook resolution.",
)
@click.option(
    "--cache-mode",
    type=click.Choice(["smart", "refresh", "offline", "network"], case_sensitive=False),
    default="smart",
    show_default=True,
    help="Evaluate the routing decision under one cache mode.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
@click.pass_context
def route_explain(
    ctx: click.Context,
    request: str,
    explicit_notebook_id: str | None,
    cache_mode: str,
    json_output: bool,
) -> None:
    """Explain how the experimental router would handle one request."""
    _emit_route_output(
        ctx,
        request=request,
        explicit_notebook_id=explicit_notebook_id,
        cache_mode=cache_mode,
        json_output=json_output,
        verbose=True,
    )


__all__ = ["route", "route_explain"]
