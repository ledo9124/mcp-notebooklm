"""Research workflow CLI commands and local run tracking helpers."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import time
from typing import Any

import click
from rich.table import Table

from ..client import NotebookLMClient
from ..contracts import (
    CacheUpdates,
    Diagnostics,
    Envelope,
    Intent,
    Route,
    Transport,
    manifest_risk_guard,
)
from ..contracts.rpc_map import RPC_MAP
from ..inbox import (
    InboxScore,
    InboxScoringContext,
    InboxScoringSignals,
    collect_inbox_scoring_context,
    score_inbox_candidate,
)
from ..inbox.dedupe import InboxDedupeCandidate, InboxDedupeCluster, cluster_inbox_candidates
from ..local.db import connect_db
from ..local.events import append_run_event
from ..local.repositories import (
    InboxClusterRecord,
    InboxClusterRepository,
    InboxItemRecord,
    InboxItemRepository,
    ResearchRunRecord,
    ResearchRunRepository,
    SourceRepository,
)
from ..observability.tracing import bind_trace
from ..profiles.manager import ProfileManager
from ..workflows.runtime import (
    emit_workflow_output,
    poll_with_interval,
    workflow_cache_updates,
    workflow_tables_touched,
)
from .helpers import (
    console,
    display_research_sources,
    json_output_response,
    require_notebook,
    resolve_notebook_id,
    with_client,
)
from .session import _trace_and_run_id


_ACTIVE_RESEARCH_INBOX_STATES = frozenset({"pending", "approved", "deferred"})


@dataclass(frozen=True)
class _ResearchInboxDraft:
    item_id: str
    title: str
    kind: str
    origin: str
    canonical_uri: str | None
    snippet: str | None
    scores: InboxScore
    scoring_context: InboxScoringContext = InboxScoringContext()
    candidate: dict[str, Any] | None = None
    existing_item: InboxItemRecord | None = None
    content_hash: str | None = None
    report_citation_provenance: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace_id(ctx: click.Context) -> str:
    trace_id = ctx.obj.get("trace_id") if ctx.obj else None
    return trace_id or "trc_unknown"


def _trace_binding(ctx: click.Context, run_id: str | None):
    trace = ctx.obj.get("trace") if ctx.obj else None
    if trace is not None:
        return bind_trace(trace.with_run_id(run_id))
    return bind_trace(trace_id=_trace_id(ctx), run_id=run_id)


def _active_profile_id(connection: sqlite3.Connection) -> str:
    profile = ProfileManager(connection).get_active_profile()
    return profile.profile_id if profile is not None else "default"
_RESEARCH_START_RPC_BINDINGS = {
    "fast": RPC_MAP[(Intent.RESEARCH.value, "fast")],
    "deep": RPC_MAP[(Intent.RESEARCH.value, "deep")],
}
_RESEARCH_STATUS_RPC_BINDING = RPC_MAP[(Intent.RESEARCH.value, "research_status")]
_RESEARCH_IMPORT_RPC_BINDING = RPC_MAP[(Intent.RESEARCH.value, "research_import")]

def _profile_id_for_research_run(research_id: str | None, *, fallback: str | None = None) -> str:
    with connect_db() as connection:
        if research_id:
            record = ResearchRunRepository(connection).get(research_id)
            if record is not None:
                return record.profile_id
        return fallback or _active_profile_id(connection)


def _research_run_id(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    value = payload.get("research_id") or payload.get("task_id")
    return str(value) if value else None


def _research_envelope(
    ctx: click.Context,
    *,
    binding,
    profile_id: str,
    notebook_id: str | None,
    result: dict[str, Any],
    reason: str,
    source_of_truth: str,
    cache_mode: str,
    elapsed_ms: int,
    ok: bool = True,
    cache_updates: CacheUpdates | None = None,
    run_id: str | None = None,
    transport: Transport | None = None,
) -> dict[str, Any]:
    trace_id, fallback_run_id = _trace_and_run_id(ctx, binding.mode)
    return Envelope(
        ok=ok,
        trace_id=trace_id,
        run_id=run_id or fallback_run_id,
        route=Route(
            intent=Intent(binding.intent),
            mode=binding.mode,
            notebook_id=notebook_id,
            profile_id=profile_id,
            source_of_truth=source_of_truth,
            cache_mode=cache_mode,
            reason=reason,
            transport=transport
            or Transport(
                kind=binding.transport_kind,
                endpoint=binding.endpoint,
                rpcid=binding.rpcid,
            ),
        ),
        result=result,
        freshness=None,
        cache_updates=cache_updates or CacheUpdates(),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_research_start_result(result: dict[str, Any], *, notebook_id: str) -> None:
    console.print("[green]Research started.[/green]")
    console.print(f"[dim]Research ID: {result['research_id']}[/dim]")
    console.print(
        "[dim]Use 'research wait "
        f"{result['research_id']}' or 'research status --notebook {notebook_id}'[/dim]"
    )


def _render_research_status_result(status: dict[str, Any]) -> None:
    status_val = status.get("status", "unknown")
    research_label = status.get("research_id") or status.get("task_id")

    if status_val == "no_research":
        console.print("[dim]No research running[/dim]")
        return
    if status_val == "in_progress":
        console.print(f"[yellow]Research in progress:[/yellow] {status.get('query', '')}")
        if research_label:
            console.print(f"[dim]Research ID: {research_label}[/dim]")
        console.print("[dim]Use 'research wait <id>' to wait for completion[/dim]")
        return
    if status_val == "completed":
        console.print(f"[green]Research completed:[/green] {status.get('query', '')}")
        if research_label:
            console.print(f"[dim]Research ID: {research_label}[/dim]")
        display_research_sources(status.get("sources", []))
        summary = status.get("summary", "")
        if summary:
            console.print(f"\n[bold]Summary:[/bold]\n{summary[:500]}")
        console.print(
            "\n[dim]Use 'research import <id> --dry-run' to preview and stage sources in inbox[/dim]"
        )
        return

    console.print(f"[yellow]Status: {status_val}[/yellow]")


def _render_research_wait_result(result: dict[str, Any], *, import_all: bool) -> None:
    console.print(f"[green]✓ Research completed:[/green] {result.get('query', '')}")
    console.print(f"[dim]Research ID: {result['research_id']}[/dim]")
    display_research_sources(result.get("sources", []))
    if import_all and result.get("staged"):
        console.print(f"[green]Staged {result['staged']} source(s) in inbox[/green]")
        console.print(
            "[dim]Use `notebooklm inbox list`, `inbox approve <item-id>`, and "
            "`inbox import <item-id>` to review and apply them.[/dim]"
        )
    elif import_all and result.get("existing_inbox_count"):
        console.print("[yellow]Research sources are already staged in inbox.[/yellow]")
        console.print("[dim]Use `notebooklm inbox list` to review them.[/dim]")
    elif import_all and result.get("message"):
        console.print(f"[yellow]{result['message']}[/yellow]")


def _inbox_item_to_dict(item: InboxItemRecord) -> dict[str, Any]:
    return {
        "id": item.id,
        "profile_id": item.profile_id,
        "notebook_id": item.notebook_id,
        "workspace_id": item.workspace_id,
        "origin": item.origin,
        "kind": item.kind,
        "state": item.state,
        "priority": item.priority,
        "novelty_score": item.novelty_score,
        "relevance_score": item.relevance_score,
        "trust_score": item.trust_score,
        "approval_required": item.approval_required,
        "title": item.title,
        "canonical_uri": item.canonical_uri,
        "snippet": item.snippet,
        "created_at": item.created_at,
        "decision_at": item.decision_at,
        "cluster_id": item.cluster_id,
        "rationale": json.loads(item.rationale_json) if item.rationale_json else None,
    }


def _normalize_research_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _json_compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _first_nonempty_text(*values: Any) -> str | None:
    for value in values:
        text = _normalize_research_text(value)
        if text:
            return text
    return None


def _decode_research_rationale(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    if isinstance(payload, dict):
        return payload
    return {"raw": payload}


def _research_candidate_content_hash(raw_source: dict[str, Any]) -> str | None:
    return _first_nonempty_text(
        raw_source.get("content_hash"),
        raw_source.get("hash"),
        raw_source.get("checksum"),
        raw_source.get("sha256"),
    )


def _research_candidate_report_citation_provenance(raw_source: dict[str, Any]) -> str | None:
    direct = _first_nonempty_text(
        raw_source.get("report_citation_provenance"),
        raw_source.get("report_citation_id"),
        raw_source.get("citation_id"),
    )
    if direct:
        return direct

    for key in ("report_citation", "citation", "provenance"):
        nested = raw_source.get(key)
        if not isinstance(nested, dict):
            continue
        direct = _first_nonempty_text(
            nested.get("id"),
            nested.get("citation_id"),
            nested.get("key"),
            nested.get("provenance"),
        )
        if direct:
            return direct
        if nested:
            return _json_compact(nested)
    return None


def _candidate_reason_label(reason: str | None) -> str:
    return {
        "missing_url": "missing URL",
        "duplicate_candidate": "duplicate in run",
        "already_present": "already present locally",
    }.get(reason, "")


def _build_research_import_plan(
    connection: sqlite3.Connection,
    *,
    record: ResearchRunRecord,
    status: dict[str, Any],
) -> dict[str, Any]:
    payload = _decode_raw_payload(record)
    sources = status.get("sources", [])
    if not isinstance(sources, list):
        sources = []

    existing_urls = {
        source.origin_uri.strip().casefold()
        for source in SourceRepository(connection).list_for_notebook(record.notebook_id)
        if source.origin_uri and not source.tombstoned_at
    }

    seen_urls: set[str] = set()
    import_candidates: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    skipped_missing_url = 0
    skipped_duplicate_candidate = 0
    skipped_existing_source = 0

    for index, raw_source in enumerate(sources, start=1):
        if not isinstance(raw_source, dict):
            continue

        title = _normalize_research_text(raw_source.get("title")) or "Untitled"
        url = _normalize_research_text(raw_source.get("url"))
        content_hash = _research_candidate_content_hash(raw_source)
        report_citation_provenance = _research_candidate_report_citation_provenance(raw_source)
        decision = "import"
        reason: str | None = None
        if not url:
            decision = "skip"
            reason = "missing_url"
            skipped_missing_url += 1
        else:
            normalized_url = url.casefold()
            if normalized_url in seen_urls:
                decision = "skip"
                reason = "duplicate_candidate"
                skipped_duplicate_candidate += 1
            elif normalized_url in existing_urls:
                decision = "skip"
                reason = "already_present"
                skipped_existing_source += 1
            seen_urls.add(normalized_url)

        candidate = {
            "index": index,
            "title": title,
            "url": url,
            "decision": decision,
            "reason": reason,
            "content_hash": content_hash,
            "report_citation_provenance": report_citation_provenance,
            "provenance": {
                "research_id": record.research_id,
                "source_index": index,
                "mode": status.get("mode", record.mode),
                "search_source": status.get("search_source"),
            },
        }
        candidates.append(candidate)
        if decision == "import":
            import_candidates.append(
                {
                    "title": title,
                    "url": url,
                    "content_hash": content_hash,
                    "report_citation_provenance": report_citation_provenance,
                }
            )

    return {
        "research_id": record.research_id,
        "notebook_id": record.notebook_id,
        "query": status.get("query") or record.query_text,
        "mode": status.get("mode", record.mode),
        "search_source": status.get("search_source"),
        "research_status": status.get("status", record.status),
        "candidate_summary": {
            "total_candidates": len(candidates),
            "importable_count": len(import_candidates),
            "skipped_missing_url": skipped_missing_url,
            "skipped_duplicate_candidate": skipped_duplicate_candidate,
            "skipped_existing_source": skipped_existing_source,
            "already_imported_count": record.imported_count,
        },
        "candidates": candidates,
        "import_candidates": import_candidates,
    }


def _render_research_import_plan(plan: dict[str, Any], *, preview: bool) -> None:
    summary = plan["candidate_summary"]
    heading = "Research Import Preview" if preview else "Research Import Results"
    console.print(f"[bold]{heading}[/bold] {plan['research_id']}")
    console.print(
        "[dim]"
        f"Notebook: {plan['notebook_id']} | "
        f"Query: {plan.get('query') or '-'} | "
        f"Importable: {summary['importable_count']} of {summary['total_candidates']}"
        "[/dim]"
    )
    console.print(
        "[dim]"
        f"Skipped: missing URL={summary['skipped_missing_url']}, "
        f"duplicate={summary['skipped_duplicate_candidate']}, "
        f"already present={summary['skipped_existing_source']}"
        "[/dim]"
    )

    if not plan["candidates"]:
        console.print("[yellow]No research sources are available for import.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Decision", style="cyan")
    table.add_column("Title", style="cyan")
    table.add_column("URL", style="dim")
    table.add_column("Reason", style="yellow")
    for candidate in plan["candidates"]:
        table.add_row(
            str(candidate["index"]),
            candidate["decision"],
            candidate["title"],
            candidate["url"],
            _candidate_reason_label(candidate.get("reason")),
        )
    console.print(table)


def _research_inbox_origin(mode: str | None) -> str:
    normalized = _normalize_research_text(mode).casefold()
    if normalized == "deep":
        return "deep_research"
    return "fast_research"


def _research_cluster_fingerprint(notebook_id: str, dedupe_fingerprint: str) -> str:
    encoded = _json_compact(
        {"dedupe_fingerprint": dedupe_fingerprint, "notebook_id": notebook_id}
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _research_item_fingerprint(research_id: str, canonical_uri: str) -> str:
    encoded = json.dumps(
        {"canonical_uri": canonical_uri.strip().casefold(), "research_id": research_id},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _research_cluster_id(fingerprint: str) -> str:
    return f"icl_{fingerprint}"


def _research_item_id(fingerprint: str) -> str:
    return f"inb_{fingerprint}"


def _research_priority(relevance: float, trust: float) -> int:
    if relevance >= 0.75 or trust >= 0.8:
        return 4
    if relevance >= 0.6 or trust >= 0.65:
        return 3
    return 2


def _research_inbox_snippet(plan: dict[str, Any]) -> str:
    query = _normalize_research_text(plan.get("query")) or "research run"
    mode = _normalize_research_text(plan.get("mode")) or "fast"
    search_source = _normalize_research_text(plan.get("search_source")) or "web"
    return f"{mode.title()} research candidate for \"{query}\" via {search_source}."


def _research_inbox_rationale_json(plan: dict[str, Any], candidate: dict[str, Any]) -> str:
    payload = {
        "query": plan.get("query"),
        "research_id": plan["research_id"],
        "mode": plan.get("mode"),
        "search_source": plan.get("search_source"),
        "candidate": {
            "index": candidate["index"],
            "title": candidate["title"],
            "url": candidate["url"],
        },
        "provenance": candidate.get("provenance"),
    }
    if candidate.get("content_hash"):
        payload["candidate"]["content_hash"] = candidate["content_hash"]
    if candidate.get("report_citation_provenance"):
        payload["candidate"]["report_citation_provenance"] = candidate["report_citation_provenance"]
    return _json_compact(payload)


def _research_score_payload(scores: InboxScore) -> dict[str, float]:
    return {
        "relevance": scores.relevance,
        "novelty": scores.novelty,
        "trust": scores.trust,
    }


def _research_scoring_context_payload(context: InboxScoringContext) -> dict[str, int]:
    return context.to_dict()


def _research_existing_item_scores(item: InboxItemRecord) -> InboxScore:
    return InboxScore(
        relevance=item.relevance_score,
        novelty=item.novelty_score,
        trust=item.trust_score,
    )


def _research_existing_item_report_citation_provenance(item: InboxItemRecord) -> str | None:
    rationale = _decode_research_rationale(item.rationale_json)
    candidate = rationale.get("candidate")
    if isinstance(candidate, dict):
        direct = _first_nonempty_text(
            candidate.get("report_citation_provenance"),
            candidate.get("report_citation_id"),
            candidate.get("citation_id"),
        )
        if direct:
            return direct
    provenance = rationale.get("provenance")
    if isinstance(provenance, dict):
        direct = _first_nonempty_text(
            provenance.get("report_citation_provenance"),
            provenance.get("report_citation_id"),
            provenance.get("citation_id"),
        )
        if direct:
            return direct
    return None


def _research_existing_item_content_hash(item: InboxItemRecord) -> str | None:
    rationale = _decode_research_rationale(item.rationale_json)
    candidate = rationale.get("candidate")
    if isinstance(candidate, dict):
        return _first_nonempty_text(
            candidate.get("content_hash"),
            candidate.get("hash"),
            candidate.get("checksum"),
        )
    return None


def _research_dedupe_candidate(entry: _ResearchInboxDraft) -> InboxDedupeCandidate:
    return InboxDedupeCandidate(
        id=entry.item_id,
        kind=entry.kind,
        title=entry.title,
        canonical_uri=entry.canonical_uri,
        content_hash=entry.content_hash,
        report_citation_provenance=entry.report_citation_provenance,
        priority=(
            entry.existing_item.priority
            if entry.existing_item is not None
            else _research_priority(entry.scores.relevance, entry.scores.trust)
        ),
        novelty_score=entry.scores.novelty,
        relevance_score=entry.scores.relevance,
        trust_score=entry.scores.trust,
    )


def _research_cluster_action_payload(action) -> dict[str, Any]:
    payload = {"kind": action.kind}
    if action.target_count is not None:
        payload["target_count"] = action.target_count
    return payload


def _research_cluster_payload(
    cluster: InboxDedupeCluster,
    *,
    notebook_id: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    fingerprint = _research_cluster_fingerprint(notebook_id, cluster.fingerprint)
    cluster_id = _research_cluster_id(fingerprint)
    variant_ids = [variant.candidate.id for variant in cluster.variants]
    member_ids = [cluster.representative.id, *variant_ids]
    action = _research_cluster_action_payload(cluster.recommended_action)
    summary = {
        "id": cluster_id,
        "fingerprint": fingerprint,
        "dedupe_fingerprint": cluster.fingerprint,
        "canonical_uri": cluster.representative.canonical_uri,
        "representative_item_id": cluster.representative.id,
        "member_item_ids": member_ids,
        "variant_item_ids": variant_ids,
        "signals": list(cluster.signals),
        "recommended_action": action,
    }
    member_payloads = {
        cluster.representative.id: {
            **summary,
            "is_representative": True,
            "match_signals": list(cluster.signals),
        }
    }
    for variant in cluster.variants:
        member_payloads[variant.candidate.id] = {
            **summary,
            "is_representative": False,
            "match_signals": list(variant.match_signals),
        }
    return summary, member_payloads


def _merge_research_rationale(
    raw: str | None,
    *,
    scores: InboxScore,
    scoring_context: InboxScoringContext,
    cluster_payload: dict[str, Any] | None,
) -> str:
    payload = _decode_research_rationale(raw)
    payload["scores"] = _research_score_payload(scores)
    payload["scoring_context"] = _research_scoring_context_payload(scoring_context)
    if cluster_payload is not None:
        payload["cluster"] = cluster_payload
    return _json_compact(payload)


def _stage_research_import_candidates(
    connection: sqlite3.Connection,
    ctx: click.Context,
    *,
    record: ResearchRunRecord,
    plan: dict[str, Any],
) -> dict[str, Any]:
    source_repository = SourceRepository(connection)
    cluster_repository = InboxClusterRepository(connection)
    item_repository = InboxItemRepository(connection)
    existing_sources = source_repository.list_for_notebook(record.notebook_id)
    existing_canonical_uris = tuple(
        source.origin_uri
        for source in existing_sources
        if source.origin_uri and not source.tombstoned_at
    )
    existing_titles = tuple(
        source.title
        for source in existing_sources
        if source.title and not source.tombstoned_at
    )
    repeated_urls = Counter(
        candidate["url"].casefold()
        for candidate in plan["candidates"]
        if candidate.get("url")
    )
    origin = _research_inbox_origin(plan.get("mode"))
    snippet = _research_inbox_snippet(plan)
    created_at = _utc_now()
    staged_items: list[InboxItemRecord] = []
    reused_item_ids: list[str] = []
    active_existing_items = [
        item
        for item in item_repository.list_for_notebook(record.notebook_id)
        if item.state in _ACTIVE_RESEARCH_INBOX_STATES
    ]
    active_existing_items_by_id = {item.id: item for item in active_existing_items}
    new_drafts: list[_ResearchInboxDraft] = []

    for candidate in plan["candidates"]:
        if candidate["decision"] != "import":
            continue

        canonical_uri = candidate["url"]
        item_fingerprint = _research_item_fingerprint(record.research_id, canonical_uri)
        item_id = _research_item_id(item_fingerprint)
        existing_item = active_existing_items_by_id.get(item_id) or item_repository.get(item_id)
        if existing_item is not None:
            reused_item_ids.append(existing_item.id)
            if existing_item.state in _ACTIVE_RESEARCH_INBOX_STATES:
                active_existing_items_by_id[existing_item.id] = existing_item
            continue

        scoring_context = collect_inbox_scoring_context(
            connection,
            profile_id=record.profile_id,
            notebook_id=record.notebook_id,
            title=candidate["title"],
            snippet=snippet,
            canonical_uri=canonical_uri,
        )
        scores = score_inbox_candidate(
            InboxScoringSignals(
                origin=origin,
                kind="source",
                title=candidate["title"],
                snippet=snippet,
                canonical_uri=canonical_uri,
                context_text=plan.get("query"),
                existing_canonical_uris=existing_canonical_uris,
                existing_titles=existing_titles,
                cluster_match=False,
                cited_by_research=True,
                repeated_agreement_count=repeated_urls[canonical_uri.casefold()],
                parseable=True,
                context=scoring_context,
            )
        )
        new_drafts.append(
            _ResearchInboxDraft(
                item_id=item_id,
                title=candidate["title"],
                kind="source",
                origin=origin,
                canonical_uri=canonical_uri,
                snippet=snippet,
                scores=scores,
                scoring_context=scoring_context,
                candidate=candidate,
                content_hash=candidate.get("content_hash"),
                report_citation_provenance=candidate.get("report_citation_provenance"),
            )
        )

    cluster_inputs = [
        _ResearchInboxDraft(
            item_id=item.id,
            title=item.title,
            kind=item.kind,
            origin=item.origin,
            canonical_uri=item.canonical_uri,
            snippet=item.snippet,
            scores=_research_existing_item_scores(item),
            existing_item=item,
            content_hash=_research_existing_item_content_hash(item),
            report_citation_provenance=_research_existing_item_report_citation_provenance(item),
        )
        for item in active_existing_items_by_id.values()
    ]
    cluster_inputs.extend(new_drafts)

    cluster_summaries: list[dict[str, Any]] = []
    cluster_member_payloads: dict[str, dict[str, Any]] = {}
    if cluster_inputs:
        for cluster in cluster_inbox_candidates(
            [_research_dedupe_candidate(entry) for entry in cluster_inputs]
        ):
            summary, member_payloads = _research_cluster_payload(
                cluster,
                notebook_id=record.notebook_id,
            )
            cluster_summaries.append(summary)
            cluster_member_payloads.update(member_payloads)

    touched_item_ids = {draft.item_id for draft in new_drafts} | set(reused_item_ids)
    touched_fingerprints = {
        payload["fingerprint"]
        for item_id, payload in cluster_member_payloads.items()
        if item_id in touched_item_ids
    }
    touched_cluster_summaries = [
        summary for summary in cluster_summaries if summary["fingerprint"] in touched_fingerprints
    ]

    for summary in touched_cluster_summaries:
        existing_cluster = cluster_repository.get_by_fingerprint(summary["fingerprint"])
        if existing_cluster is not None:
            summary["id"] = existing_cluster.id
        for payload in cluster_member_payloads.values():
            if payload["fingerprint"] == summary["fingerprint"]:
                payload["cluster_id"] = summary["id"]
        representative_exists = item_repository.get(summary["representative_item_id"]) is not None
        cluster_repository.upsert(
            InboxClusterRecord(
                id=summary["id"],
                fingerprint=summary["fingerprint"],
                canonical_uri=summary["canonical_uri"],
                representative_item_id=(
                    summary["representative_item_id"] if representative_exists else None
                ),
            )
        )

    for item in active_existing_items_by_id.values():
        cluster_payload = cluster_member_payloads.get(item.id)
        if cluster_payload is None or cluster_payload["fingerprint"] not in touched_fingerprints:
            continue
        updated = InboxItemRecord(
            id=item.id,
            profile_id=item.profile_id,
            notebook_id=item.notebook_id,
            workspace_id=item.workspace_id,
            origin=item.origin,
            kind=item.kind,
            state=item.state,
            title=item.title,
            created_at=item.created_at,
            priority=item.priority,
            novelty_score=item.novelty_score,
            relevance_score=item.relevance_score,
            trust_score=item.trust_score,
            approval_required=item.approval_required,
            canonical_uri=item.canonical_uri,
            snippet=item.snippet,
            rationale_json=_merge_research_rationale(
                item.rationale_json,
                scores=_research_existing_item_scores(item),
                scoring_context=InboxScoringContext(),
                cluster_payload=cluster_payload,
            ),
            decision_at=item.decision_at,
            cluster_id=cluster_payload["cluster_id"],
        )
        item_repository.upsert(updated)
        active_existing_items_by_id[item.id] = updated

    for draft in new_drafts:
        cluster_payload = cluster_member_payloads.get(draft.item_id)
        item = InboxItemRecord(
            id=draft.item_id,
            profile_id=record.profile_id,
            notebook_id=record.notebook_id,
            origin=draft.origin,
            kind=draft.kind,
            state="pending",
            title=draft.title,
            created_at=created_at,
            priority=_research_priority(draft.scores.relevance, draft.scores.trust),
            novelty_score=draft.scores.novelty,
            relevance_score=draft.scores.relevance,
            trust_score=draft.scores.trust,
            approval_required=True,
            canonical_uri=draft.canonical_uri,
            snippet=draft.snippet,
            rationale_json=_merge_research_rationale(
                _research_inbox_rationale_json(plan, draft.candidate or {}),
                scores=draft.scores,
                scoring_context=draft.scoring_context,
                cluster_payload=cluster_payload,
            ),
            cluster_id=cluster_payload["cluster_id"] if cluster_payload is not None else None,
        )
        item_repository.upsert(item)
        append_run_event(
            connection,
            _trace_id(ctx),
            "inbox.item.created",
            run_id=record.research_id,
            payload={
                "item_id": item.id,
                "cluster_id": item.cluster_id,
                "candidate_index": draft.candidate["index"] if draft.candidate is not None else None,
                "canonical_uri": draft.canonical_uri,
                "notebook_id": record.notebook_id,
                "research_id": record.research_id,
            },
        )
        staged_items.append(item)
        active_existing_items_by_id[item.id] = item

    for summary in touched_cluster_summaries:
        cluster_repository.upsert(
            InboxClusterRecord(
                id=summary["id"],
                fingerprint=summary["fingerprint"],
                canonical_uri=summary["canonical_uri"],
                representative_item_id=summary["representative_item_id"],
            )
        )

    existing_items = [
        active_existing_items_by_id.get(item_id) or item_repository.get(item_id)
        for item_id in reused_item_ids
    ]
    existing_items = [item for item in existing_items if item is not None]

    message: str | None = None
    if staged_items:
        message = f"Staged {len(staged_items)} research source(s) in inbox."
        if existing_items:
            message = f"{message} {len(existing_items)} candidate(s) were already staged."
    elif existing_items:
        message = "Research sources are already staged in inbox."

    return {
        "staged": len(staged_items),
        "existing_inbox_count": len(existing_items),
        "inbox_item_ids": [item.id for item in [*staged_items, *existing_items]],
        "inbox_items": [_inbox_item_to_dict(item) for item in [*staged_items, *existing_items]],
        "inbox_clusters": touched_cluster_summaries,
        "message": message,
    }


def _ensure_cached_notebook(
    connection: sqlite3.Connection,
    *,
    notebook_id: str,
    profile_id: str,
    title: str | None = None,
) -> None:
    existing = connection.execute(
        "SELECT notebook_id FROM notebooks WHERE notebook_id = ?",
        (notebook_id,),
    ).fetchone()
    if existing is not None:
        return

    persisted_title = (title or notebook_id).strip() or notebook_id
    with connection:
        connection.execute(
            """
            INSERT INTO notebooks (
                notebook_id,
                profile_id,
                title,
                normalized_title
            ) VALUES (?, ?, ?, ?)
            """,
            (
                notebook_id,
                profile_id,
                persisted_title,
                persisted_title.casefold(),
            ),
        )


def _decode_raw_payload(record: ResearchRunRecord | None) -> dict[str, Any]:
    if record is None or not record.raw_json:
        return {}
    try:
        payload = json.loads(record.raw_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _status_from_record(record: ResearchRunRecord) -> dict[str, Any]:
    payload = _decode_raw_payload(record)
    result = {
        "task_id": record.research_id,
        "research_id": record.research_id,
        "status": record.status,
        "query": payload.get("query", record.query_text),
        "sources": payload.get("sources", []),
        "summary": payload.get("summary", ""),
        "mode": payload.get("mode", record.mode),
        "search_source": payload.get("search_source"),
        "notebook_id": record.notebook_id,
        "discovered_count": record.discovered_count,
        "imported_count": record.imported_count,
    }
    report_id = payload.get("report_id")
    if report_id:
        result["report_id"] = report_id
    return result


def _research_import_uses_stored_status(record: ResearchRunRecord) -> bool:
    stored_status = _status_from_record(record)
    stored_sources = stored_status.get("sources", [])
    return record.status == "completed" and isinstance(stored_sources, list) and bool(stored_sources)


def _upsert_research_run(
    connection: sqlite3.Connection,
    *,
    research_id: str,
    notebook_id: str,
    status: str,
    mode: str | None = None,
    query_text: str | None = None,
    discovered_count: int | None = None,
    imported_count: int | None = None,
    profile_id: str | None = None,
    raw_payload: dict[str, Any] | None = None,
    started_at: str | None = None,
) -> ResearchRunRecord:
    repo = ResearchRunRepository(connection)
    existing = repo.get(research_id)
    existing_payload = _decode_raw_payload(existing)
    merged_payload = existing_payload if raw_payload is None else {**existing_payload, **raw_payload}
    now = _utc_now()

    persisted_profile_id = profile_id or (
        existing.profile_id if existing is not None else _active_profile_id(connection)
    )
    _ensure_cached_notebook(
        connection,
        notebook_id=notebook_id if notebook_id else existing.notebook_id,
        profile_id=persisted_profile_id,
    )

    record = ResearchRunRecord(
        research_id=research_id,
        notebook_id=notebook_id if notebook_id else existing.notebook_id,
        profile_id=persisted_profile_id,
        mode=mode or (existing.mode if existing is not None else "fast"),
        query_text=query_text
        if query_text is not None
        else (existing.query_text if existing is not None else ""),
        status=status,
        started_at=started_at or (existing.started_at if existing is not None else now),
        updated_at=now,
        discovered_count=discovered_count
        if discovered_count is not None
        else (existing.discovered_count if existing is not None else 0),
        imported_count=imported_count
        if imported_count is not None
        else (existing.imported_count if existing is not None else 0),
        raw_json=json.dumps(merged_payload, sort_keys=True, separators=(",", ":")),
    )
    repo.upsert(record)
    return record


def _latest_research_run(
    connection: sqlite3.Connection,
    notebook_id: str,
) -> ResearchRunRecord | None:
    repo = ResearchRunRepository(connection)
    records = repo.list_for_notebook(notebook_id)
    if not records:
        return None
    return max(records, key=lambda record: (record.updated_at, record.started_at, record.research_id))


def _persist_polled_status(
    connection: sqlite3.Connection,
    *,
    notebook_id: str,
    status: dict[str, Any],
    existing: ResearchRunRecord | None,
) -> ResearchRunRecord | None:
    research_id = status.get("task_id") or (existing.research_id if existing is not None else None)
    if not research_id:
        return existing

    payload = dict(status)
    payload["research_id"] = research_id
    if existing is not None:
        payload.setdefault("search_source", _decode_raw_payload(existing).get("search_source"))

    return _upsert_research_run(
        connection,
        research_id=research_id,
        notebook_id=notebook_id,
        profile_id=existing.profile_id if existing is not None else None,
        mode=existing.mode if existing is not None else payload.get("mode"),
        query_text=status.get("query")
        or (existing.query_text if existing is not None else ""),
        status=status.get("status", existing.status if existing is not None else "unknown"),
        discovered_count=len(status.get("sources", []))
        if "sources" in status
        else (existing.discovered_count if existing is not None else 0),
        imported_count=existing.imported_count if existing is not None else 0,
        raw_payload=payload,
        started_at=existing.started_at if existing is not None else None,
    )


def _record_research_event(
    connection: sqlite3.Connection,
    ctx: click.Context,
    *,
    kind: str,
    research_id: str | None,
    payload: dict[str, Any],
) -> None:
    append_run_event(
        connection,
        _trace_id(ctx),
        kind,
        run_id=research_id,
        payload=payload,
    )


async def start_research_run(
    ctx: click.Context,
    *,
    client: NotebookLMClient,
    notebook_id: str,
    query: str,
    search_source: str,
    mode: str,
) -> dict[str, Any]:
    result = await client.research.start(notebook_id, query, search_source, mode)
    if not result:
        raise click.ClickException("Research failed to start")

    research_id = str(result["task_id"])
    payload = {
        **result,
        "research_id": research_id,
        "search_source": search_source,
        "status": "in_progress",
        "sources": [],
        "summary": "",
    }
    with connect_db() as connection:
        record = _upsert_research_run(
            connection,
            research_id=research_id,
            notebook_id=notebook_id,
            status="in_progress",
            mode=mode,
            query_text=query,
            raw_payload=payload,
        )
        _record_research_event(
            connection,
            ctx,
            kind="research.started",
            research_id=record.research_id,
            payload={
                "notebook_id": notebook_id,
                "mode": record.mode,
                "query": record.query_text,
                "search_source": search_source,
            },
        )
    return payload


async def poll_research_status(
    ctx: click.Context,
    *,
    client: NotebookLMClient,
    notebook_id: str,
    research_id: str | None = None,
) -> tuple[dict[str, Any], ResearchRunRecord | None]:
    with connect_db() as connection:
        existing = (
            ResearchRunRepository(connection).get(research_id)
            if research_id
            else _latest_research_run(connection, notebook_id)
        )
        if research_id and existing is None:
            raise click.ClickException(f"Unknown research run: {research_id}")

    with _trace_binding(ctx, research_id or (existing.research_id if existing else None)):
        status = await client.research.poll(notebook_id)

    with connect_db() as connection:
        if (
            status.get("status") == "no_research"
            and research_id
            and existing is not None
            and existing.status == "completed"
        ):
            result = _status_from_record(existing)
        else:
            if research_id and status.get("task_id") and status["task_id"] != research_id:
                raise click.ClickException(
                    f"Research run {research_id} is not the notebook's current task "
                    f"({status['task_id']})."
                )
            persisted = _persist_polled_status(
                connection,
                notebook_id=notebook_id,
                status=status,
                existing=existing,
            )
            result = status if persisted is None else _status_from_record(persisted)
            existing = persisted

        event_research_id = research_id or result.get("research_id")
        _record_research_event(
            connection,
            ctx,
            kind="research.polled",
            research_id=event_research_id,
            payload={
                "notebook_id": notebook_id,
                "status": result.get("status"),
                "discovered_count": len(result.get("sources", [])),
            },
        )
        return result, existing


async def wait_for_research_run(
    ctx: click.Context,
    *,
    client: NotebookLMClient,
    notebook_id: str,
    timeout: int,
    interval: int,
    import_all: bool,
    research_id: str | None = None,
    storage_path=None,
    json_output: bool = False,
) -> dict[str, Any]:
    max_iterations = max(1, timeout // interval)
    last_status: dict[str, Any] = {"status": "timeout"}
    persisted: ResearchRunRecord | None = None

    async def _poll_once() -> tuple[dict[str, Any], ResearchRunRecord | None]:
        return await poll_research_status(
            ctx,
            client=client,
            notebook_id=notebook_id,
            research_id=research_id,
        )

    with console.status("Waiting for research to complete..."):
        outcome = await poll_with_interval(
            _poll_once,
            max_iterations=max_iterations,
            interval_seconds=interval,
            is_complete=lambda polled: polled[0].get("status") in {"completed", "no_research"},
            sleep=asyncio.sleep,
        )
        if outcome.result is not None:
            last_status, persisted = outcome.result

        if last_status.get("status") == "no_research":
            raise click.ClickException("No research running")

        if not outcome.completed:
            resolved_research_id = research_id or last_status.get("research_id")
            with connect_db() as connection:
                if resolved_research_id:
                    updated = _upsert_research_run(
                        connection,
                        research_id=resolved_research_id,
                        notebook_id=notebook_id,
                        profile_id=persisted.profile_id if persisted is not None else None,
                        mode=persisted.mode if persisted is not None else None,
                        query_text=last_status.get("query")
                        or (persisted.query_text if persisted is not None else ""),
                        status="timeout",
                        discovered_count=persisted.discovered_count if persisted is not None else 0,
                        imported_count=persisted.imported_count if persisted is not None else 0,
                        raw_payload={**last_status, "research_id": resolved_research_id},
                        started_at=persisted.started_at if persisted is not None else None,
                    )
                    _record_research_event(
                        connection,
                        ctx,
                        kind="research.polled",
                        research_id=updated.research_id,
                        payload={
                            "notebook_id": notebook_id,
                            "status": "timeout",
                            "timeout_seconds": timeout,
                        },
                    )
            raise click.ClickException(f"Timed out after {timeout} seconds")

    resolved_research_id = (
        research_id
        or last_status.get("research_id")
        or last_status.get("task_id")
        or (persisted.research_id if persisted is not None else None)
    )
    sources = last_status.get("sources", [])
    imported_sources: list[dict[str, str]] = []

    with connect_db() as connection:
        completed = _upsert_research_run(
            connection,
            research_id=resolved_research_id or (persisted.research_id if persisted is not None else ""),
            notebook_id=notebook_id,
            profile_id=persisted.profile_id if persisted is not None else None,
            mode=persisted.mode if persisted is not None else None,
            query_text=last_status.get("query")
            or (persisted.query_text if persisted is not None else ""),
            status="completed",
            discovered_count=len(sources),
            imported_count=(
                (persisted.imported_count if persisted is not None else 0)
                + len(imported_sources)
            ),
            raw_payload={
                **last_status,
                "research_id": resolved_research_id,
                "imported_sources": imported_sources,
            },
            started_at=persisted.started_at if persisted is not None else None,
        )
        _record_research_event(
            connection,
            ctx,
            kind="research.completed",
            research_id=completed.research_id,
            payload={
                "notebook_id": notebook_id,
                "discovered_count": len(sources),
                "imported_count": len(imported_sources),
            },
        )
        if imported_sources:
            _record_research_event(
                connection,
                ctx,
                kind="research.imported",
                research_id=completed.research_id,
                payload={
                    "notebook_id": notebook_id,
                    "imported_count": len(imported_sources),
                },
            )
        result = _status_from_record(completed)

    result["sources_found"] = len(sources)
    if import_all and resolved_research_id:
        import_result = await import_research_run(
            ctx,
            client=client,
            research_id=resolved_research_id,
            dry_run=False,
            approval_token=None,
            json_output=json_output,
            storage_path=storage_path,
            status=result,
        )
        result["candidate_summary"] = import_result["candidate_summary"]
        result["candidates"] = import_result["candidates"]
        result["import_candidates"] = import_result["import_candidates"]
        if "message" in import_result:
            result["message"] = import_result["message"]
        if "staged" in import_result:
            result["staged"] = import_result["staged"]
            result["existing_inbox_count"] = import_result.get("existing_inbox_count", 0)
            result["inbox_item_ids"] = import_result.get("inbox_item_ids", [])
            result["inbox_items"] = import_result.get("inbox_items", [])
    elif imported_sources:
        result["imported"] = len(imported_sources)
        result["imported_sources"] = imported_sources
    return result


async def import_research_run(
    ctx: click.Context,
    *,
    client: NotebookLMClient,
    research_id: str,
    dry_run: bool,
    approval_token: str | None,
    json_output: bool,
    storage_path=None,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with connect_db() as connection:
        record = ResearchRunRepository(connection).get(research_id)
    if record is None:
        raise click.ClickException(f"Unknown research run: {research_id}")

    current_status = status
    if current_status is None:
        stored_status = _status_from_record(record)
        stored_sources = stored_status.get("sources", [])
        if record.status == "completed" and isinstance(stored_sources, list) and stored_sources:
            current_status = stored_status
        else:
            current_status, refreshed = await poll_research_status(
                ctx,
                client=client,
                notebook_id=record.notebook_id,
                research_id=research_id,
            )
            if refreshed is not None:
                record = refreshed

    if current_status.get("status") != "completed":
        raise click.ClickException(
            f"Research run {research_id} is not completed yet. Use `notebooklm research wait {research_id}` first."
        )

    with connect_db() as connection:
        record = ResearchRunRepository(connection).get(research_id) or record
        plan = _build_research_import_plan(
            connection,
            record=record,
            status=current_status,
        )
        if dry_run:
            return {
                **plan,
                "status": "preview",
                "would_import": len(plan["import_candidates"]),
            }
        if not plan["import_candidates"]:
            return {
                **plan,
                "status": "completed",
                "staged": 0,
                "existing_inbox_count": 0,
                "inbox_item_ids": [],
                "inbox_items": [],
                "inbox_clusters": [],
                "message": "No importable research sources remain.",
            }
        staged = _stage_research_import_candidates(
            connection,
            ctx,
            record=record,
            plan=plan,
        )
        _upsert_research_run(
            connection,
            research_id=research_id,
            notebook_id=record.notebook_id,
            profile_id=record.profile_id,
            mode=plan["mode"],
            query_text=plan["query"],
            status="completed",
            discovered_count=plan["candidate_summary"]["total_candidates"],
            imported_count=record.imported_count,
                raw_payload={
                    **current_status,
                    "research_id": research_id,
                    "candidate_summary": plan["candidate_summary"],
                    "import_candidates": plan["import_candidates"],
                    "staged": staged["staged"],
                    "existing_inbox_count": staged["existing_inbox_count"],
                    "inbox_item_ids": staged["inbox_item_ids"],
                    "inbox_items": staged["inbox_items"],
                    "inbox_clusters": staged["inbox_clusters"],
                },
            started_at=record.started_at,
        )

    return {
        **plan,
        **staged,
        "status": "staged",
    }


@click.group()
def research():
    """Research management commands.

    \b
    Commands:
      start     Start a research run and persist its run id
      status    Check research status (non-blocking)
      wait      Wait for research to complete (blocking)
      import    Preview and stage sources from a completed research run

    \b
    Explicit runs are the canonical path:
      notebooklm research start "AI" --mode deep
      notebooklm research wait <research-id>
      notebooklm research import <research-id> --dry-run

    \b
    The older `source add-research` flow still works and now stores the same
    local run metadata under the hood.
    """
    pass
@research.command("start")
@click.argument("query")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--from",
    "search_source",
    type=click.Choice(["web", "drive"]),
    default="web",
    help="Search source (default: web)",
)
@click.option(
    "--mode",
    type=click.Choice(["fast", "deep"]),
    default="fast",
    help="Search mode (default: fast)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def research_start(ctx, query, notebook_id, search_source, mode, json_output, client_auth):
    """Start a research run and print the research id."""
    started_at = time.perf_counter()
    nb_id = require_notebook(notebook_id)

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            if not json_output:
                console.print(
                    f"[yellow]Starting {mode} research on {search_source}...[/yellow]"
                )
            result = await start_research_run(
                ctx,
                client=client,
                notebook_id=nb_id_resolved,
                query=query,
                search_source=search_source,
                mode=mode,
            )
            emit_workflow_output(
                json_output=json_output,
                build_json=lambda: _research_envelope(
                    ctx,
                    binding=_RESEARCH_START_RPC_BINDINGS[mode],
                    profile_id=_profile_id_for_research_run(_research_run_id(result)),
                    notebook_id=nb_id_resolved,
                    result=result,
                    reason="Start a live NotebookLM research run and persist local tracking metadata.",
                      source_of_truth="remote_http",
                      cache_mode="network",
                      elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                      cache_updates=workflow_cache_updates("research_runs", "run_events"),
                      run_id=_research_run_id(result),
                  ),
                emit_json=json_output_response,
                render_human=lambda: _render_research_start_result(
                    result,
                    notebook_id=nb_id_resolved,
                ),
            )

    return _run()


@research.command("status")
@click.argument("research_id", required=False)
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def research_status(ctx, research_id, notebook_id, json_output, client_auth):
    """Check research status for the current notebook or a stored research id."""
    started_at = time.perf_counter()
    nb_id = notebook_id

    async def _run():
        nonlocal nb_id
        resolved_profile_id = _profile_id_for_research_run(None)
        async with NotebookLMClient(client_auth) as client:
            if research_id:
                with connect_db() as connection:
                    record = ResearchRunRepository(connection).get(research_id)
                if record is None:
                    raise click.ClickException(f"Unknown research run: {research_id}")
                nb_id = record.notebook_id
                resolved_profile_id = record.profile_id
            nb_id_resolved = await resolve_notebook_id(client, require_notebook(nb_id))
            status, persisted = await poll_research_status(
                ctx,
                client=client,
                notebook_id=nb_id_resolved,
                research_id=research_id,
            )
            if persisted is not None:
                resolved_profile_id = persisted.profile_id

            emit_workflow_output(
                json_output=json_output,
                build_json=lambda: _research_envelope(
                    ctx,
                    binding=_RESEARCH_STATUS_RPC_BINDING,
                    profile_id=resolved_profile_id,
                    notebook_id=nb_id_resolved,
                    result=status,
                    reason="Poll the live research task and merge any updated state into the local run tracker.",
                      source_of_truth="mixed",
                      cache_mode="network",
                      elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                      cache_updates=workflow_cache_updates("research_runs", "run_events")
                      if (_research_run_id(status) or research_id)
                      else workflow_cache_updates("run_events"),
                      run_id=_research_run_id(status) or research_id,
                  ),
                emit_json=json_output_response,
                render_human=lambda: _render_research_status_result(status),
            )

    return _run()


@research.command("wait")
@click.argument("research_id", required=False)
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--timeout",
    default=300,
    type=int,
    help="Maximum seconds to wait (default: 300)",
)
@click.option(
    "--interval",
    default=5,
    type=int,
    help="Seconds between status checks (default: 5)",
)
@click.option("--import-all", is_flag=True, help="Stage all found sources in inbox when done")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def research_wait(
    ctx,
    research_id,
    notebook_id,
    timeout,
    interval,
    import_all,
    json_output,
    client_auth,
):
    """Wait for research to complete, optionally targeting a specific research id."""
    started_at = time.perf_counter()
    nb_id = notebook_id

    async def _run():
        nonlocal nb_id
        resolved_profile_id = _profile_id_for_research_run(None)
        nb_id_resolved: str | None = None
        async with NotebookLMClient(client_auth) as client:
            try:
                if research_id:
                    with connect_db() as connection:
                        record = ResearchRunRepository(connection).get(research_id)
                    if record is None:
                        raise click.ClickException(f"Unknown research run: {research_id}")
                    nb_id = record.notebook_id
                    resolved_profile_id = record.profile_id

                nb_id_resolved = await resolve_notebook_id(client, require_notebook(nb_id))
                result = await wait_for_research_run(
                    ctx,
                    client=client,
                    notebook_id=nb_id_resolved,
                    timeout=timeout,
                    interval=interval,
                    import_all=import_all,
                    research_id=research_id,
                    storage_path=client_auth.storage_path,
                    json_output=json_output,
                )
            except click.ClickException as exc:
                if not json_output:
                    raise

                message = exc.message
                status = "error"
                tables_touched: list[str] = []
                if message == "No research running":
                    status = "no_research"
                    tables_touched = workflow_tables_touched("run_events")
                elif message.startswith("Timed out after"):
                    status = "timeout"
                    tables_touched = workflow_tables_touched("research_runs", "run_events")
                elif message.startswith("Unknown research run:"):
                    status = "not_found"

                json_output_response(
                    _research_envelope(
                        ctx,
                        binding=_RESEARCH_STATUS_RPC_BINDING,
                        profile_id=resolved_profile_id,
                        notebook_id=nb_id_resolved,
                        result={"status": status, "error": message},
                        reason="Poll the live research task until completion and persist the final local run state.",
                        source_of_truth="mixed",
                        cache_mode="network",
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                        ok=False,
                        cache_updates=workflow_cache_updates(*tables_touched),
                        run_id=research_id,
                    )
                )
                raise SystemExit(1)

            emit_workflow_output(
                json_output=json_output,
                build_json=lambda: _research_envelope(
                    ctx,
                    binding=_RESEARCH_STATUS_RPC_BINDING,
                    profile_id=resolved_profile_id,
                    notebook_id=nb_id_resolved,
                    result=result,
                    reason="Poll the live research task until completion and persist the final local run state.",
                    source_of_truth="mixed",
                    cache_mode="network",
                    elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    cache_updates=workflow_cache_updates(
                        "research_runs",
                        "run_events",
                        "inbox_items",
                        "inbox_clusters",
                    )
                    if (result.get("staged") or result.get("existing_inbox_count"))
                    else workflow_cache_updates("research_runs", "run_events"),
                    run_id=_research_run_id(result) or research_id,
                ),
                emit_json=json_output_response,
                render_human=lambda: _render_research_wait_result(
                    result,
                    import_all=import_all,
                ),
            )

    return _run()


@research.command("import")
@click.argument("research_id")
@click.option("--dry-run", is_flag=True, help="Preview research import candidates without mutating the notebook.")
@click.option(
    "--approval-token",
    default=None,
    help="Reserved compatibility flag; inbox staging does not require a research approval token.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@manifest_risk_guard("research.import")
@with_client
def research_import(
    ctx,
    research_id: str,
    dry_run: bool,
    approval_token: str | None,
    json_output: bool,
    client_auth,
):
    """Preview or stage sources from a completed research run."""
    started_at = time.perf_counter()
    initial_record: ResearchRunRecord | None = None
    with connect_db() as connection:
        initial_record = ResearchRunRepository(connection).get(research_id)
    used_status_poll = bool(
        initial_record is not None and not _research_import_uses_stored_status(initial_record)
    )
    resolved_profile_id = (
        initial_record.profile_id if initial_record is not None else _profile_id_for_research_run(None)
    )
    route_notebook_id = initial_record.notebook_id if initial_record is not None else None

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            payload = await import_research_run(
                ctx,
                client=client,
                research_id=research_id,
                dry_run=dry_run,
                approval_token=approval_token,
                json_output=json_output,
                storage_path=client_auth.storage_path,
            )

        if json_output:
            did_stage = payload.get("status") == "staged"
            tables_touched: list[str] = []
            if used_status_poll or did_stage:
                tables_touched = workflow_tables_touched("research_runs", "run_events")
            if did_stage:
                tables_touched = workflow_tables_touched(
                    *tables_touched,
                    "inbox_items",
                    "inbox_clusters",
                )

            source_of_truth = "mixed" if used_status_poll else "local_cache"
            cache_mode = "network" if used_status_poll else "offline"
            transport = (
                None
                if used_status_poll
                else Transport(kind="local")
            )
            reason = (
                "Stage importable research candidates in the local inbox for later approval/import."
                if did_stage
                else "Preview research import candidates from the locally tracked research run."
            )
            json_output_response(
                _research_envelope(
                    ctx,
                    binding=_RESEARCH_IMPORT_RPC_BINDING,
                    profile_id=resolved_profile_id,
                    notebook_id=route_notebook_id,
                    result=payload,
                    reason=reason,
                    source_of_truth=source_of_truth,
                    cache_mode=cache_mode,
                    elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    cache_updates=workflow_cache_updates(*tables_touched),
                    run_id=research_id,
                    transport=transport,
                )
            )
            return

        _render_research_import_plan(payload, preview=dry_run)
        if dry_run:
            console.print(
                f"[dim]Rerun with `notebooklm research import {research_id}` to stage candidates in inbox.[/dim]"
            )
            return
        if payload.get("staged"):
            console.print(f"[green]Staged {payload['staged']} research source(s) in inbox.[/green]")
            if payload.get("existing_inbox_count"):
                console.print(
                    f"[dim]{payload['existing_inbox_count']} candidate(s) were already staged.[/dim]"
                )
            console.print(
                "[dim]Use `notebooklm inbox list`, `inbox approve <item-id>`, and "
                "`inbox import <item-id>` to review and apply them.[/dim]"
            )
        elif payload.get("existing_inbox_count"):
            console.print("[yellow]Research sources are already staged in inbox.[/yellow]")
            console.print("[dim]Use `notebooklm inbox list` to review them.[/dim]")
        elif payload.get("message"):
            console.print(f"[yellow]{payload['message']}[/yellow]")

    return _run()
