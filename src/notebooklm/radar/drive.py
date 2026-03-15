"""Drive-specific stale-source detection for change-radar flows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import sqlite3

from notebooklm.inbox import (
    InboxScore,
    InboxScoringContext,
    InboxScoringSignals,
    collect_inbox_scoring_context,
    score_inbox_candidate,
)
from notebooklm.local.events import append_run_event
from notebooklm.local.repositories import (
    InboxClusterRecord,
    InboxClusterRepository,
    InboxItemRecord,
    InboxItemRepository,
    NotebookRepository,
    SourceRecord,
    SourceRepository,
)
from notebooklm.observability import generate_trace_id


@dataclass(frozen=True)
class DriveStaleDetection:
    """One stale-drive-source detection outcome."""

    source_id: str
    fingerprint: str
    stale_reason: str
    staged: bool
    inbox_item_id: str
    cluster_id: str
    trace_id: str


def _normalize_timestamp(ts: datetime | None = None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _drive_stale_reason(source: SourceRecord) -> str | None:
    if source.drive_syncable is not True or source.status != "ready":
        return None

    updated_at = _parse_timestamp(source.updated_at_remote)
    synced_at = _parse_timestamp(source.synced_at)
    if updated_at is None:
        return None
    if synced_at is None:
        return "missing_sync_baseline"
    if updated_at > synced_at:
        return "remote_updated_after_sync"
    return None


def _canonical_uri(source: SourceRecord) -> str:
    return source.origin_uri or f"drive://source/{source.source_id}"


def _fingerprint(source: SourceRecord, stale_reason: str) -> str:
    payload = {
        "canonical_uri": _canonical_uri(source),
        "reason": stale_reason,
        "source_id": source.source_id,
        "synced_at": source.synced_at,
        "updated_at_remote": source.updated_at_remote,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cluster_id(fingerprint: str) -> str:
    return f"icl_{fingerprint}"


def _inbox_item_id(fingerprint: str) -> str:
    return f"inb_{fingerprint}"


def _rationale_json(
    source: SourceRecord,
    stale_reason: str,
    *,
    scores: InboxScore,
    scoring_context: InboxScoringContext,
) -> str:
    return json.dumps(
        {
            "scores": {
                "relevance": scores.relevance,
                "novelty": scores.novelty,
                "trust": scores.trust,
            },
            "scoring_context": scoring_context.to_dict(),
            "stale_reason": stale_reason,
            "source_id": source.source_id,
            "source_type": source.source_type,
            "updated_at_remote": source.updated_at_remote,
            "synced_at": source.synced_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _stale_title(source: SourceRecord) -> str:
    label = source.title or source.source_id
    return f"Drive source may be stale: {label}"


def _stale_snippet(source: SourceRecord, stale_reason: str) -> str:
    if stale_reason == "missing_sync_baseline":
        return "Drive-backed source has no local sync baseline yet; review whether it needs a resync."
    return (
        "Drive-backed source appears newer in Drive than the cached NotebookLM snapshot; "
        f"remote={source.updated_at_remote or 'unknown'} synced={source.synced_at or 'unknown'}."
    )


def _score_drive_inbox_item(
    connection: sqlite3.Connection,
    source: SourceRecord,
    *,
    stale_reason: str,
    profile_id: str,
    notebook_id: str | None,
    notebook_title: str | None,
    existing_canonical_uris: tuple[str, ...],
    existing_titles: tuple[str, ...],
) -> tuple[InboxScore, InboxScoringContext]:
    scoring_context = collect_inbox_scoring_context(
        connection,
        profile_id=profile_id,
        notebook_id=notebook_id,
        title=source.title,
        snippet=_stale_snippet(source, stale_reason),
        canonical_uri=_canonical_uri(source),
    )
    score = score_inbox_candidate(
        InboxScoringSignals(
            origin="change_radar",
            kind="resync",
            title=source.title,
            snippet=_stale_snippet(source, stale_reason),
            canonical_uri=_canonical_uri(source),
            context_text=notebook_title,
            existing_canonical_uris=existing_canonical_uris,
            existing_titles=existing_titles,
            parseable=bool(source.origin_uri),
            context=scoring_context,
        )
    )
    return score, scoring_context


def detect_drive_source_staleness(
    connection: sqlite3.Connection,
    profile_id: str,
    *,
    now: datetime | None = None,
    trace_id: str | None = None,
) -> list[DriveStaleDetection]:
    """Detect stale Drive-backed sources and stage review items in the inbox."""

    timestamp = _normalize_timestamp(now)
    persisted_ts = timestamp.isoformat()
    persisted_trace_id = trace_id or generate_trace_id(timestamp)

    source_repository = SourceRepository(connection)
    notebook_repository = NotebookRepository(connection)
    cluster_repository = InboxClusterRepository(connection)
    item_repository = InboxItemRepository(connection)

    detections: list[DriveStaleDetection] = []
    for source in source_repository.list_for_profile(profile_id):
        stale_reason = _drive_stale_reason(source)
        if stale_reason is None:
            if source.drive_syncable is True and source.status == "ready" and source.freshness_state != "fresh":
                source_repository.upsert(replace(source, freshness_state="fresh"))
            continue

        if source.freshness_state != "stale":
            source_repository.upsert(replace(source, freshness_state="stale"))

        fingerprint = _fingerprint(source, stale_reason)
        inbox_item_id = _inbox_item_id(fingerprint)
        existing_item = item_repository.get(inbox_item_id)
        existing_cluster = cluster_repository.get_by_fingerprint(fingerprint)
        cluster_id = existing_cluster.id if existing_cluster is not None else _cluster_id(fingerprint)
        notebook = notebook_repository.get(source.notebook_id)
        sibling_sources = source_repository.list_for_notebook(source.notebook_id)
        score, scoring_context = _score_drive_inbox_item(
            connection,
            source,
            stale_reason=stale_reason,
            profile_id=source.profile_id,
            notebook_id=source.notebook_id,
            notebook_title=notebook.title if notebook is not None else None,
            existing_canonical_uris=tuple(
                candidate.origin_uri for candidate in sibling_sources if candidate.origin_uri
            ),
            existing_titles=tuple(candidate.title for candidate in sibling_sources if candidate.title),
        )

        if existing_cluster is None:
            cluster_repository.upsert(
                InboxClusterRecord(
                    id=cluster_id,
                    fingerprint=fingerprint,
                    canonical_uri=_canonical_uri(source),
                    representative_item_id=None,
                )
            )
        elif existing_cluster.representative_item_id != inbox_item_id:
            cluster_repository.upsert(
                InboxClusterRecord(
                    id=existing_cluster.id,
                    fingerprint=existing_cluster.fingerprint,
                    canonical_uri=existing_cluster.canonical_uri or _canonical_uri(source),
                    representative_item_id=existing_cluster.representative_item_id or inbox_item_id,
                )
            )

        staged = existing_item is None
        if staged:
            item_repository.upsert(
                InboxItemRecord(
                    id=inbox_item_id,
                    profile_id=source.profile_id,
                    notebook_id=source.notebook_id,
                    origin="change_radar",
                    kind="resync",
                    state="pending",
                    title=_stale_title(source),
                    created_at=persisted_ts,
                    priority=2,
                    novelty_score=score.novelty,
                    relevance_score=score.relevance,
                    trust_score=score.trust,
                    approval_required=True,
                    canonical_uri=_canonical_uri(source),
                    snippet=_stale_snippet(source, stale_reason),
                    rationale_json=_rationale_json(
                        source,
                        stale_reason,
                        scores=score,
                        scoring_context=scoring_context,
                    ),
                    cluster_id=cluster_id,
                )
            )
            cluster_repository.upsert(
                InboxClusterRecord(
                    id=cluster_id,
                    fingerprint=fingerprint,
                    canonical_uri=_canonical_uri(source),
                    representative_item_id=inbox_item_id,
                )
            )
            append_run_event(
                connection,
                persisted_trace_id,
                "change.detected",
                payload={
                    "source_id": source.source_id,
                    "reason": stale_reason,
                    "fingerprint": fingerprint,
                },
                ts=timestamp,
            )
            append_run_event(
                connection,
                persisted_trace_id,
                "inbox.item.created",
                payload={
                    "item_id": inbox_item_id,
                    "source_id": source.source_id,
                    "cluster_id": cluster_id,
                },
                ts=timestamp,
            )

        detections.append(
            DriveStaleDetection(
                source_id=source.source_id,
                fingerprint=fingerprint,
                stale_reason=stale_reason,
                staged=staged,
                inbox_item_id=inbox_item_id,
                cluster_id=cluster_id,
                trace_id=persisted_trace_id,
            )
        )

    return detections


__all__ = ["DriveStaleDetection", "detect_drive_source_staleness"]
