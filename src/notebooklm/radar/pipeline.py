"""Core change-detection pipeline helpers for source watches."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import httpx

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
    SourceRepository,
)
from notebooklm.observability import current_trace, generate_trace_id
from notebooklm.sync.invalidation import invalidate_notebook_detail

from .adapters import AdapterKind, RevisionSnapshot, snapshot_target


JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
ChangeSeverity = Literal["noise", "minor", "material", "critical"]

_OPEN_CHANGE_EVENT_STATES = ("new", "briefed", "queued_inbox")
_ACTIVE_INBOX_ITEM_STATES = ("pending", "approved", "deferred")
_SEVERITY_ALIASES: dict[str, ChangeSeverity] = {
    "noise": "noise",
    "minor": "minor",
    "low": "minor",
    "material": "material",
    "medium": "material",
    "normal": "material",
    "critical": "critical",
    "high": "critical",
}
_CROCKFORD_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@dataclass(frozen=True)
class RadarWatch:
    """Structured view of one row from the `watches` table."""

    id: str
    profile_id: str
    scope_type: str
    scope_id: str
    watch_kind: str
    policy_json: str
    status: str
    schedule_json: str
    next_run_at: str | None
    last_run_at: str | None

    @property
    def policy(self) -> dict[str, JsonValue]:
        return _load_json_object(self.policy_json)

    @property
    def schedule(self) -> dict[str, JsonValue]:
        return _load_json_object(self.schedule_json)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "RadarWatch":
        return cls(
            id=row["id"],
            profile_id=row["profile_id"],
            scope_type=row["scope_type"],
            scope_id=row["scope_id"],
            watch_kind=row["watch_kind"],
            policy_json=row["policy_json"],
            status=row["status"],
            schedule_json=row["schedule_json"],
            next_run_at=row["next_run_at"],
            last_run_at=row["last_run_at"],
        )


@dataclass(frozen=True)
class StoredSourceRevision:
    """Structured view of one row from the `source_revisions` table."""

    id: str
    source_id: str
    revision_key: str
    content_hash: str | None
    etag: str | None
    last_modified: str | None
    fetched_at: str
    metadata_json: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StoredSourceRevision":
        return cls(
            id=row["id"],
            source_id=row["source_id"],
            revision_key=row["revision_key"],
            content_hash=row["content_hash"],
            etag=row["etag"],
            last_modified=row["last_modified"],
            fetched_at=row["fetched_at"],
            metadata_json=row["metadata_json"],
        )


@dataclass(frozen=True)
class StoredDeltaBriefing:
    """Structured view of one row from the `delta_briefings` table."""

    id: str
    change_event_id: str
    summary_md: str
    impact_json: str
    recommended_actions_json: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StoredDeltaBriefing":
        return cls(
            id=row["id"],
            change_event_id=row["change_event_id"],
            summary_md=row["summary_md"],
            impact_json=row["impact_json"],
            recommended_actions_json=row["recommended_actions_json"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class ChangeDecision:
    """Comparison output between the latest stored revision and a fresh snapshot."""

    change_kind: str
    severity: ChangeSeverity
    changed_fields: tuple[str, ...]
    data: dict[str, JsonValue]


@dataclass(frozen=True)
class WatchRunResult:
    """Result summary for one completed or failed watch execution."""

    watch_id: str
    watch_run_id: str
    trace_id: str
    status: str
    changed: bool
    baseline_created: bool
    signature_before: str | None
    signature_after: str | None
    source_revision_id: str | None
    change_event_id: str | None
    delta_briefing_id: str | None
    change_kind: str | None
    severity: ChangeSeverity | None
    invalidated_sync_runs: int
    next_run_at: str | None
    error_text: str | None = None


def _normalize_timestamp(ts: datetime | None = None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _timestamp_text(ts: datetime | None = None) -> str:
    return _normalize_timestamp(ts).isoformat()


def _encode_crockford_base32(value: int, length: int) -> str:
    chars = ["0"] * length
    for index in range(length - 1, -1, -1):
        chars[index] = _CROCKFORD_BASE32[value & 31]
        value >>= 5
    return "".join(chars)


def _generate_identifier(prefix: str, ts: datetime | None = None) -> str:
    timestamp = _normalize_timestamp(ts)
    timestamp_ms = int(timestamp.timestamp() * 1000)
    ulid_value = (timestamp_ms << 80) | secrets.randbits(80)
    return f"{prefix}_{_encode_crockford_base32(ulid_value, 26)}"


def _load_json_object(raw_json: str | None) -> dict[str, JsonValue]:
    if raw_json is None:
        return {}
    try:
        loaded = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _json_text(value: dict[str, JsonValue]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _parse_schedule_delta(schedule: dict[str, JsonValue]) -> timedelta | None:
    for key in ("every_seconds", "interval_seconds", "seconds"):
        value = schedule.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return timedelta(seconds=float(value))

    interval = schedule.get("interval")
    if isinstance(interval, str):
        normalized = interval.strip().casefold()
        if normalized == "hourly":
            return timedelta(hours=1)
        if normalized == "daily":
            return timedelta(days=1)
        if normalized == "weekly":
            return timedelta(weeks=1)
        if normalized == "monthly":
            return timedelta(days=30)

    return None


def _compute_next_run_at(watch: RadarWatch, *, now: datetime) -> str | None:
    delta = _parse_schedule_delta(watch.schedule)
    if delta is None:
        return None
    return _timestamp_text(now + delta)


def _resolve_policy_severity(
    policy: dict[str, JsonValue],
    *,
    keys: tuple[str, ...],
    default: ChangeSeverity,
) -> ChangeSeverity:
    for key in keys:
        value = policy.get(key)
        if not isinstance(value, str):
            continue
        mapped = _SEVERITY_ALIASES.get(value.strip().casefold())
        if mapped is not None:
            return mapped
    return default


def _list_metadata_changes(
    previous: StoredSourceRevision,
    snapshot: RevisionSnapshot,
) -> tuple[str, ...]:
    changed_fields: list[str] = []
    if previous.revision_key != snapshot.revision_key:
        changed_fields.append("revision_key")
    if previous.content_hash != snapshot.content_hash:
        changed_fields.append("content_hash")
    if previous.etag != snapshot.etag:
        changed_fields.append("etag")
    if previous.last_modified != snapshot.last_modified:
        changed_fields.append("last_modified")
    if not changed_fields:
        return ()
    return tuple(changed_fields)


def _build_change_decision(
    previous: StoredSourceRevision,
    snapshot: RevisionSnapshot,
    *,
    policy: dict[str, JsonValue],
) -> ChangeDecision | None:
    changed_fields = _list_metadata_changes(previous, snapshot)
    if not changed_fields:
        return None

    data: dict[str, JsonValue] = {
        "adapter_kind": snapshot.adapter_kind,
        "canonical_uri": snapshot.canonical_uri,
        "changed_fields": list(changed_fields),
        "current_content_hash": snapshot.content_hash,
        "current_etag": snapshot.etag,
        "current_last_modified": snapshot.last_modified,
        "current_revision_key": snapshot.revision_key,
        "previous_content_hash": previous.content_hash,
        "previous_etag": previous.etag,
        "previous_last_modified": previous.last_modified,
        "previous_revision_id": previous.id,
        "previous_revision_key": previous.revision_key,
    }

    if previous.content_hash != snapshot.content_hash:
        return ChangeDecision(
            change_kind="content_hash_changed",
            severity=_resolve_policy_severity(
                policy,
                keys=("content_materiality", "materiality"),
                default="material",
            ),
            changed_fields=changed_fields,
            data=data,
        )

    return ChangeDecision(
        change_kind="metadata_only_changed",
        severity=_resolve_policy_severity(
            policy,
            keys=("metadata_materiality",),
            default="minor",
        ),
        changed_fields=changed_fields,
        data=data,
    )


def _target_from_file_uri(raw_uri: str) -> str:
    parsed = urlparse(raw_uri)
    if parsed.scheme == "file":
        return str(Path(unquote(parsed.path)).expanduser())
    return raw_uri


def _resolve_source_target(
    watch: RadarWatch,
    *,
    source_origin_uri: str | None,
) -> tuple[str, AdapterKind]:
    policy = watch.policy
    if watch.watch_kind == "web_diff":
        target = (
            policy.get("target_url")
            or policy.get("url")
            or policy.get("target")
            or source_origin_uri
        )
        if not isinstance(target, str) or not target.strip():
            raise LookupError(f"watch {watch.id} has no URL target")
        return target, "web"

    if watch.watch_kind == "local_file_hash":
        target = (
            policy.get("target_path")
            or policy.get("path")
            or policy.get("target")
            or source_origin_uri
        )
        if not isinstance(target, str) or not target.strip():
            raise LookupError(f"watch {watch.id} has no local-file target")
        return _target_from_file_uri(target), "local_file"

    raise NotImplementedError(
        f"watch kind {watch.watch_kind!r} is not supported by the source pipeline"
    )


def _load_watch(connection: sqlite3.Connection, watch_id: str) -> RadarWatch | None:
    row = connection.execute(
        """
        SELECT
            id,
            profile_id,
            scope_type,
            scope_id,
            watch_kind,
            policy_json,
            status,
            schedule_json,
            next_run_at,
            last_run_at
        FROM watches
        WHERE id = ?
        """,
        (watch_id,),
    ).fetchone()
    return RadarWatch.from_row(row) if row else None


def _list_due_watch_rows(
    connection: sqlite3.Connection,
    *,
    due_at: str,
    limit: int | None,
) -> list[sqlite3.Row]:
    query = """
        SELECT
            id,
            profile_id,
            scope_type,
            scope_id,
            watch_kind,
            policy_json,
            status,
            schedule_json,
            next_run_at,
            last_run_at
        FROM watches
        WHERE status = 'active'
          AND (next_run_at IS NULL OR next_run_at <= ?)
        ORDER BY
            CASE WHEN next_run_at IS NULL THEN 0 ELSE 1 END,
            next_run_at ASC,
            id ASC
    """
    params: list[object] = [due_at]
    if limit is not None:
        query = f"{query}\nLIMIT ?"
        params.append(limit)
    return connection.execute(query, params).fetchall()


def list_due_watches(
    connection: sqlite3.Connection,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[RadarWatch]:
    """Return active watches whose next scheduled run is due."""

    due_at = _timestamp_text(now)
    return [RadarWatch.from_row(row) for row in _list_due_watch_rows(connection, due_at=due_at, limit=limit)]


def _latest_source_revision(
    connection: sqlite3.Connection,
    source_id: str,
) -> StoredSourceRevision | None:
    row = connection.execute(
        """
        SELECT
            id,
            source_id,
            revision_key,
            content_hash,
            etag,
            last_modified,
            fetched_at,
            metadata_json
        FROM source_revisions
        WHERE source_id = ?
        ORDER BY fetched_at DESC, id DESC
        LIMIT 1
        """,
        (source_id,),
    ).fetchone()
    return StoredSourceRevision.from_row(row) if row else None


def _insert_source_revision(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    snapshot: RevisionSnapshot,
) -> str:
    revision_id = _generate_identifier("rev")
    connection.execute(
        """
        INSERT INTO source_revisions (
            id,
            source_id,
            revision_key,
            content_hash,
            etag,
            last_modified,
            fetched_at,
            metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision_id,
            source_id,
            snapshot.revision_key,
            snapshot.content_hash,
            snapshot.etag,
            snapshot.last_modified,
            snapshot.fetched_at,
            _json_text(snapshot.metadata),
        ),
    )
    return revision_id


def _insert_change_event(
    connection: sqlite3.Connection,
    *,
    watch: RadarWatch,
    notebook_id: str | None,
    source_id: str,
    decision: ChangeDecision,
    created_at: str,
) -> str:
    change_event_id = _generate_identifier("chg")
    connection.execute(
        """
        INSERT INTO change_events (
            id,
            watch_id,
            source_id,
            notebook_id,
            workspace_id,
            change_kind,
            severity,
            state,
            created_at,
            data_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            change_event_id,
            watch.id,
            source_id,
            notebook_id,
            None,
            decision.change_kind,
            decision.severity,
            "new",
            created_at,
            _json_text(decision.data),
        ),
    )
    return change_event_id


def _insert_watch_run(
    connection: sqlite3.Connection,
    *,
    watch_run_id: str,
    watch: RadarWatch,
    trace_id: str,
    started_at: str,
    ended_at: str,
    status: str,
    signature_before: str | None,
    signature_after: str | None,
    result: dict[str, JsonValue],
) -> None:
    connection.execute(
        """
        INSERT INTO watch_runs (
            id,
            watch_id,
            trace_id,
            profile_id,
            started_at,
            ended_at,
            status,
            signature_before,
            signature_after,
            result_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            watch_run_id,
            watch.id,
            trace_id,
            watch.profile_id,
            started_at,
            ended_at,
            status,
            signature_before,
            signature_after,
            _json_text(result),
        ),
    )


def _change_inbox_kind(decision: ChangeDecision) -> str:
    if decision.change_kind == "content_hash_changed":
        return "replacement"
    return "resync"


def _change_inbox_title(source, decision: ChangeDecision) -> str:
    source_label = source.title or source.source_id
    if _change_inbox_kind(decision) == "replacement":
        return f"Replacement candidate for changed source: {source_label}"
    return f"Resync candidate for changed source metadata: {source_label}"


def _change_inbox_snippet(source, decision: ChangeDecision) -> str:
    source_label = source.title or source.source_id
    severity = decision.severity
    if _change_inbox_kind(decision) == "replacement":
        return (
            f"Radar detected a {severity} content change for `{source_label}`. "
            "Review the delta briefing and approve the staged replacement before reimporting."
        )
    return (
        f"Radar detected a {severity} metadata change for `{source_label}`. "
        "Review the delta briefing and approve the staged resync before refreshing local knowledge."
    )


def _change_inbox_suggested_action(decision: ChangeDecision) -> str:
    if _change_inbox_kind(decision) == "replacement":
        return "approve_replacement_candidate"
    return "approve_resync_candidate"


def _change_inbox_fingerprint(
    *,
    watch: RadarWatch,
    source,
    decision: ChangeDecision,
) -> str:
    payload = {
        "canonical_uri": decision.data.get("canonical_uri") or source.origin_uri,
        "change_kind": decision.change_kind,
        "current_content_hash": decision.data.get("current_content_hash"),
        "current_revision_key": decision.data.get("current_revision_key"),
        "severity": decision.severity,
        "source_id": source.source_id,
        "watch_id": watch.id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _change_inbox_cluster_id(fingerprint: str) -> str:
    return f"icl_{fingerprint}"


def _change_inbox_item_id(fingerprint: str) -> str:
    return f"inb_{fingerprint}"


def _score_change_inbox_item(
    connection: sqlite3.Connection,
    source,
    *,
    decision: ChangeDecision,
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
        snippet=_change_inbox_snippet(source, decision),
        canonical_uri=decision.data.get("canonical_uri") or source.origin_uri,
    )
    score = score_inbox_candidate(
        InboxScoringSignals(
            origin="change_radar",
            kind=_change_inbox_kind(decision),
            title=source.title,
            snippet=_change_inbox_snippet(source, decision),
            canonical_uri=decision.data.get("canonical_uri") or source.origin_uri,
            context_text=notebook_title,
            existing_canonical_uris=existing_canonical_uris,
            existing_titles=existing_titles,
            parseable=bool(decision.data.get("canonical_uri") or source.origin_uri),
            context=scoring_context,
        )
    )
    return score, scoring_context


def _change_inbox_priority(severity: ChangeSeverity) -> int:
    if severity == "critical":
        return 3
    return 2


def _change_inbox_rationale_json(
    *,
    watch: RadarWatch,
    source,
    decision: ChangeDecision,
    change_event_id: str,
    delta_briefing_id: str,
    scores: InboxScore,
    scoring_context: InboxScoringContext,
) -> str:
    return json.dumps(
        {
            "change_event_id": change_event_id,
            "change_kind": decision.change_kind,
            "changed_fields": list(decision.changed_fields),
            "current_revision_id": decision.data.get("current_revision_id"),
            "current_revision_key": decision.data.get("current_revision_key"),
            "delta_briefing_id": delta_briefing_id,
            "invalidated_sync_runs": decision.data.get("invalidated_sync_runs"),
            "previous_revision_id": decision.data.get("previous_revision_id"),
            "previous_revision_key": decision.data.get("previous_revision_key"),
            "scores": {
                "relevance": scores.relevance,
                "novelty": scores.novelty,
                "trust": scores.trust,
            },
            "scoring_context": scoring_context.to_dict(),
            "severity": decision.severity,
            "source_id": source.source_id,
            "suggested_action": _change_inbox_suggested_action(decision),
            "watch_id": watch.id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _update_change_event_state(
    connection: sqlite3.Connection,
    *,
    change_event_id: str,
    state: str,
) -> None:
    connection.execute(
        """
        UPDATE change_events
        SET state = ?
        WHERE id = ?
        """,
        (state, change_event_id),
    )


def _update_change_event_data(
    connection: sqlite3.Connection,
    *,
    change_event_id: str,
    updates: dict[str, JsonValue],
) -> None:
    row = connection.execute(
        """
        SELECT data_json
        FROM change_events
        WHERE id = ?
        """,
        (change_event_id,),
    ).fetchone()
    if row is None:
        return
    payload = _load_json_object(row["data_json"])
    payload.update(updates)
    connection.execute(
        """
        UPDATE change_events
        SET data_json = ?
        WHERE id = ?
        """,
        (_json_text(payload), change_event_id),
    )


def _stage_change_inbox_item(
    connection: sqlite3.Connection,
    *,
    watch: RadarWatch,
    source,
    decision: ChangeDecision,
    change_event_id: str,
    delta_briefing_id: str,
    created_at: str,
) -> tuple[str | None, str | None, bool]:
    if decision.severity not in {"material", "critical"}:
        return None, None, False

    item_repository = InboxItemRepository(connection)
    cluster_repository = InboxClusterRepository(connection)
    notebook_repository = NotebookRepository(connection)
    fingerprint = _change_inbox_fingerprint(watch=watch, source=source, decision=decision)
    inbox_item_id = _change_inbox_item_id(fingerprint)
    existing_item = item_repository.get(inbox_item_id)
    existing_cluster = cluster_repository.get_by_fingerprint(fingerprint)
    cluster_id = existing_cluster.id if existing_cluster is not None else _change_inbox_cluster_id(fingerprint)
    canonical_uri = decision.data.get("canonical_uri") or source.origin_uri
    representative_item_id = (
        existing_cluster.representative_item_id
        if existing_cluster is not None and existing_cluster.representative_item_id is not None
        else (existing_item.id if existing_item is not None else None)
    )

    cluster_repository.upsert(
        InboxClusterRecord(
            id=cluster_id,
            fingerprint=fingerprint,
            canonical_uri=canonical_uri,
            representative_item_id=representative_item_id,
        )
    )

    staged = existing_item is None
    queued = staged
    if staged:
        notebook = notebook_repository.get(source.notebook_id) if source.notebook_id else None
        source_repository = SourceRepository(connection)
        existing_sources = (
            source_repository.list_for_notebook(source.notebook_id) if source.notebook_id else []
        )
        score, scoring_context = _score_change_inbox_item(
            connection,
            source,
            decision=decision,
            profile_id=source.profile_id,
            notebook_id=source.notebook_id,
            notebook_title=notebook.title if notebook is not None else None,
            existing_canonical_uris=tuple(
                candidate.origin_uri for candidate in existing_sources if candidate.origin_uri
            ),
            existing_titles=tuple(candidate.title for candidate in existing_sources if candidate.title),
        )
        item_repository.upsert(
            InboxItemRecord(
                id=inbox_item_id,
                profile_id=source.profile_id,
                notebook_id=source.notebook_id,
                origin="change_radar",
                kind=_change_inbox_kind(decision),
                state="pending",
                title=_change_inbox_title(source, decision),
                created_at=created_at,
                priority=_change_inbox_priority(decision.severity),
                novelty_score=score.novelty,
                relevance_score=score.relevance,
                trust_score=score.trust,
                approval_required=True,
                canonical_uri=canonical_uri,
                snippet=_change_inbox_snippet(source, decision),
                rationale_json=_change_inbox_rationale_json(
                    watch=watch,
                    source=source,
                    decision=decision,
                    change_event_id=change_event_id,
                    delta_briefing_id=delta_briefing_id,
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
                canonical_uri=canonical_uri,
                representative_item_id=inbox_item_id,
            )
        )
    else:
        queued = existing_item.state in _ACTIVE_INBOX_ITEM_STATES

    if queued:
        _update_change_event_state(connection, change_event_id=change_event_id, state="queued_inbox")
        _update_change_event_data(
            connection,
            change_event_id=change_event_id,
            updates={
                "approval_required": True,
                "inbox_cluster_id": cluster_id,
                "inbox_item_id": inbox_item_id,
                "inbox_kind": _change_inbox_kind(decision),
                "suggested_action": _change_inbox_suggested_action(decision),
            },
        )
        return inbox_item_id, cluster_id, staged
    return None, None, False


def _delta_briefing_payload(
    *,
    source,
    decision: ChangeDecision,
    invalidated_sync_runs: int,
) -> tuple[str, dict[str, JsonValue], list[dict[str, JsonValue]]]:
    source_label = source.title or source.source_id
    changed_fields = ", ".join(decision.changed_fields)
    if decision.change_kind == "content_hash_changed":
        what_changed = (
            f"Source `{source_label}` changed materially at `{decision.data['canonical_uri']}`. "
            f"Changed fields: {changed_fields}."
        )
        severity_detail = (
            "Cached notebook detail was invalidated because the content itself changed."
            if invalidated_sync_runs > 0
            else "The content changed and should be reviewed before trusting cached answers."
        )
        recommended_actions = [
            {
                "kind": "review_change",
                "description": "Review the captured diff context and confirm the source still supports current notebook conclusions.",
            },
            {
                "kind": "resync_source",
                "description": (
                    f"Review the staged inbox replacement candidate for source `{source.source_id}` "
                    f"in notebook `{source.notebook_id}` and approve reimport if needed."
                ),
            },
        ]
    else:
        what_changed = (
            f"Source `{source_label}` changed metadata at `{decision.data['canonical_uri']}` "
            f"without a content hash change. Changed fields: {changed_fields}."
        )
        if decision.severity in {"material", "critical"}:
            severity_detail = (
                "Notebook detail was invalidated because this metadata change is configured as material."
            )
            recommended_actions = [
                {
                    "kind": "review_change",
                    "description": "Review the metadata-only change to confirm the tracked source still matches expectations.",
                },
                {
                    "kind": "resync_source",
                    "description": (
                        f"Review the staged inbox resync candidate for source `{source.source_id}` "
                        "before refreshing local knowledge."
                    ),
                },
            ]
        else:
            severity_detail = "No notebook-detail invalidation was required because the content hash is unchanged."
            recommended_actions = [
                {
                    "kind": "review_change",
                    "description": "Review the metadata-only change to decide whether follow-up monitoring is needed.",
                },
                {
                    "kind": "monitor_source",
                    "description": "Wait for another radar run unless a human wants to manually inspect the source now.",
                },
            ]

    impact = {
        "notebooks": [source.notebook_id] if source.notebook_id else [],
        "workspaces": [],
        "query_runs": [],
        "stale_query_runs_possible": decision.severity in {"material", "critical"},
        "invalidated_sync_runs": invalidated_sync_runs,
    }

    summary_md = "\n".join(
        [
            "## What Changed",
            what_changed,
            "",
            "## Severity",
            f"`{decision.severity}`. {severity_detail}",
            "",
            "## Affected Surfaces",
            f"- Notebooks: `{source.notebook_id}`" if source.notebook_id else "- Notebooks: none linked",
            "- Workspaces: none linked in the local cache yet.",
            (
                "- Queries: exact cached query links are not tracked yet; treat notebook answers as potentially stale."
                if decision.severity in {"material", "critical"}
                else "- Queries: no exact cached query links are tracked for this metadata-only change."
            ),
            "",
            "## Recommended Action",
            *(f"{index}. {action['description']}" for index, action in enumerate(recommended_actions, start=1)),
        ]
    )
    return summary_md, impact, recommended_actions


def _insert_delta_briefing(
    connection: sqlite3.Connection,
    *,
    change_event_id: str,
    summary_md: str,
    impact: dict[str, JsonValue],
    recommended_actions: list[dict[str, JsonValue]],
    created_at: str,
) -> str:
    delta_briefing_id = _generate_identifier("brief")
    connection.execute(
        """
        INSERT INTO delta_briefings (
            id,
            change_event_id,
            summary_md,
            impact_json,
            recommended_actions_json,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            delta_briefing_id,
            change_event_id,
            summary_md,
            _json_text(impact),
            _json_text({"actions": recommended_actions}),
            created_at,
        ),
    )
    return delta_briefing_id


def _update_watch_schedule(
    connection: sqlite3.Connection,
    *,
    watch_id: str,
    last_run_at: str,
    next_run_at: str | None,
) -> None:
    connection.execute(
        """
        UPDATE watches
        SET last_run_at = ?, next_run_at = ?
        WHERE id = ?
        """,
        (last_run_at, next_run_at, watch_id),
    )


def _has_open_material_change_event(
    connection: sqlite3.Connection,
    *,
    watch_id: str,
    source_id: str,
) -> bool:
    placeholders = ",".join("?" for _ in _OPEN_CHANGE_EVENT_STATES)
    row = connection.execute(
        f"""
        SELECT 1
        FROM change_events
        WHERE watch_id = ?
          AND source_id = ?
          AND severity IN ('material', 'critical')
          AND state IN ({placeholders})
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (watch_id, source_id, *_OPEN_CHANGE_EVENT_STATES),
    ).fetchone()
    return row is not None


def _desired_freshness_state(
    connection: sqlite3.Connection,
    *,
    watch_id: str,
    source_id: str,
    severity: ChangeSeverity | None,
) -> str:
    if severity in {"material", "critical"}:
        return "stale"
    if _has_open_material_change_event(connection, watch_id=watch_id, source_id=source_id):
        return "stale"
    return "fresh"


def _source_with_freshness(source, freshness_state: str):
    return replace(source, freshness_state=freshness_state)


async def run_watch(
    connection: sqlite3.Connection,
    watch_id: str,
    *,
    now: datetime | None = None,
    trace_id: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> WatchRunResult:
    """Execute one watch run and persist its result to the radar tables."""

    timestamp = _normalize_timestamp(now)
    persisted_now = timestamp.isoformat()
    active_trace = current_trace()
    persisted_trace_id = trace_id or (
        active_trace.trace_id if active_trace is not None else generate_trace_id(timestamp)
    )
    watch_run_id = _generate_identifier("wtr", timestamp)

    watch = _load_watch(connection, watch_id)
    if watch is None:
        raise LookupError(f"unknown watch: {watch_id}")

    next_run_at = _compute_next_run_at(watch, now=timestamp)
    signature_before: str | None = None
    signature_after: str | None = None

    try:
        if watch.scope_type != "source":
            raise NotImplementedError(
                f"watch scope {watch.scope_type!r} is not supported by the source pipeline"
            )

        source_repository = SourceRepository(connection)
        source = source_repository.get(watch.scope_id)
        if source is None:
            raise LookupError(f"unknown source for watch {watch.id}: {watch.scope_id}")

        target, adapter_kind = _resolve_source_target(watch, source_origin_uri=source.origin_uri)
        previous_revision = _latest_source_revision(connection, source.source_id)
        if previous_revision is not None:
            signature_before = previous_revision.revision_key

        snapshot = await snapshot_target(
            target,
            adapter_kind=adapter_kind,
            client=client,
            now=timestamp,
        )
        signature_after = snapshot.revision_key

        baseline_created = previous_revision is None
        changed = False
        source_revision_id: str | None = None
        change_event_id: str | None = None
        delta_briefing_id: str | None = None
        change_kind: str | None = None
        change_event_state: str | None = None
        inbox_cluster_id: str | None = None
        inbox_item_id: str | None = None
        inbox_item_staged = False
        severity: ChangeSeverity | None = None
        invalidated_sync_runs = 0

        if baseline_created:
            with connection:
                source_revision_id = _insert_source_revision(
                    connection,
                    source_id=source.source_id,
                    snapshot=snapshot,
                )
                desired_freshness = _desired_freshness_state(
                    connection,
                    watch_id=watch.id,
                    source_id=source.source_id,
                    severity=None,
                )
                if source.freshness_state != desired_freshness:
                    source_repository.upsert(_source_with_freshness(source, desired_freshness))
                result_payload: dict[str, JsonValue] = {
                    "baseline_created": True,
                    "changed": False,
                    "source_revision_id": source_revision_id,
                }
                _update_watch_schedule(
                    connection,
                    watch_id=watch.id,
                    last_run_at=persisted_now,
                    next_run_at=next_run_at,
                )
                _insert_watch_run(
                    connection,
                    watch_run_id=watch_run_id,
                    watch=watch,
                    trace_id=persisted_trace_id,
                    started_at=persisted_now,
                    ended_at=persisted_now,
                    status="completed",
                    signature_before=signature_before,
                    signature_after=signature_after,
                    result=result_payload,
                )
        else:
            assert previous_revision is not None
            decision = _build_change_decision(
                previous_revision,
                snapshot,
                policy=watch.policy,
            )
            if decision is not None and decision.severity in {"material", "critical"}:
                invalidated_sync_runs = invalidate_notebook_detail(
                    connection,
                    source.notebook_id,
                    profile_id=source.profile_id,
                    reason=f"change_radar:{watch.id}:{decision.change_kind}",
                )

            with connection:
                if decision is not None:
                    changed = True
                    change_kind = decision.change_kind
                    severity = decision.severity
                    source_revision_id = _insert_source_revision(
                        connection,
                        source_id=source.source_id,
                        snapshot=snapshot,
                    )
                    decision_payload = dict(decision.data)
                    decision_payload["current_revision_id"] = source_revision_id
                    decision_payload["invalidated_sync_runs"] = invalidated_sync_runs
                    decision = ChangeDecision(
                        change_kind=decision.change_kind,
                        severity=decision.severity,
                        changed_fields=decision.changed_fields,
                        data=decision_payload,
                    )
                    change_event_id = _insert_change_event(
                        connection,
                        watch=watch,
                        notebook_id=source.notebook_id,
                        source_id=source.source_id,
                        decision=decision,
                        created_at=persisted_now,
                    )
                    summary_md, impact, recommended_actions = _delta_briefing_payload(
                        source=source,
                        decision=decision,
                        invalidated_sync_runs=invalidated_sync_runs,
                    )
                    delta_briefing_id = _insert_delta_briefing(
                        connection,
                        change_event_id=change_event_id,
                        summary_md=summary_md,
                        impact=impact,
                        recommended_actions=recommended_actions,
                        created_at=persisted_now,
                    )
                    inbox_item_id, inbox_cluster_id, inbox_item_staged = _stage_change_inbox_item(
                        connection,
                        watch=watch,
                        source=source,
                        decision=decision,
                        change_event_id=change_event_id,
                        delta_briefing_id=delta_briefing_id,
                        created_at=persisted_now,
                    )
                    change_event_state = "queued_inbox" if inbox_item_id is not None else "new"

                desired_freshness = _desired_freshness_state(
                    connection,
                    watch_id=watch.id,
                    source_id=source.source_id,
                    severity=severity,
                )
                if source.freshness_state != desired_freshness:
                    source_repository.upsert(_source_with_freshness(source, desired_freshness))

                result_payload = {
                    "baseline_created": False,
                    "change_event_id": change_event_id,
                    "change_kind": change_kind,
                    "change_event_state": change_event_state,
                    "changed": changed,
                    "delta_briefing_id": delta_briefing_id,
                    "inbox_cluster_id": inbox_cluster_id,
                    "inbox_item_id": inbox_item_id,
                    "inbox_item_staged": inbox_item_staged,
                    "invalidated_sync_runs": invalidated_sync_runs,
                    "severity": severity,
                    "source_revision_id": source_revision_id,
                }
                _update_watch_schedule(
                    connection,
                    watch_id=watch.id,
                    last_run_at=persisted_now,
                    next_run_at=next_run_at,
                )
                _insert_watch_run(
                    connection,
                    watch_run_id=watch_run_id,
                    watch=watch,
                    trace_id=persisted_trace_id,
                    started_at=persisted_now,
                    ended_at=persisted_now,
                    status="completed",
                    signature_before=signature_before,
                    signature_after=signature_after,
                    result=result_payload,
                )

        if changed:
            append_run_event(
                connection,
                persisted_trace_id,
                "change.detected",
                run_id=watch_run_id,
                payload={
                    "change_event_id": change_event_id,
                    "change_kind": change_kind,
                    "change_event_state": change_event_state,
                    "inbox_item_id": inbox_item_id,
                    "severity": severity,
                    "source_id": source.source_id,
                    "watch_id": watch.id,
                },
                ts=timestamp,
            )
            append_run_event(
                connection,
                persisted_trace_id,
                "delta.briefing.created",
                run_id=watch_run_id,
                payload={
                    "change_event_id": change_event_id,
                    "delta_briefing_id": delta_briefing_id,
                    "inbox_item_id": inbox_item_id,
                    "severity": severity,
                    "watch_id": watch.id,
                },
                ts=timestamp,
            )
            if inbox_item_staged and inbox_item_id is not None:
                append_run_event(
                    connection,
                    persisted_trace_id,
                    "inbox.item.created",
                    run_id=watch_run_id,
                    payload={
                        "change_event_id": change_event_id,
                        "cluster_id": inbox_cluster_id,
                        "delta_briefing_id": delta_briefing_id,
                        "item_id": inbox_item_id,
                        "source_id": source.source_id,
                        "watch_id": watch.id,
                    },
                    ts=timestamp,
                )

        append_run_event(
            connection,
            persisted_trace_id,
            "watch.run.completed",
            run_id=watch_run_id,
            payload={
                "baseline_created": baseline_created,
                "change_event_id": change_event_id,
                "change_kind": change_kind,
                "change_event_state": change_event_state,
                "changed": changed,
                "delta_briefing_id": delta_briefing_id,
                "inbox_cluster_id": inbox_cluster_id,
                "inbox_item_id": inbox_item_id,
                "inbox_item_staged": inbox_item_staged,
                "severity": severity,
                "status": "completed",
                "watch_id": watch.id,
            },
            ts=timestamp,
        )

        return WatchRunResult(
            watch_id=watch.id,
            watch_run_id=watch_run_id,
            trace_id=persisted_trace_id,
            status="completed",
            changed=changed,
            baseline_created=baseline_created,
            signature_before=signature_before,
            signature_after=signature_after,
            source_revision_id=source_revision_id,
            change_event_id=change_event_id,
            delta_briefing_id=delta_briefing_id,
            change_kind=change_kind,
            severity=severity,
            invalidated_sync_runs=invalidated_sync_runs,
            next_run_at=next_run_at,
        )
    except Exception as exc:
        with connection:
            _update_watch_schedule(
                connection,
                watch_id=watch.id,
                last_run_at=persisted_now,
                next_run_at=next_run_at,
            )
            _insert_watch_run(
                connection,
                watch_run_id=watch_run_id,
                watch=watch,
                trace_id=persisted_trace_id,
                started_at=persisted_now,
                ended_at=persisted_now,
                status="failed",
                signature_before=signature_before,
                signature_after=signature_after,
                result={
                    "baseline_created": False,
                    "changed": False,
                    "error": str(exc),
                },
            )

        append_run_event(
            connection,
            persisted_trace_id,
            "watch.run.completed",
            run_id=watch_run_id,
            payload={
                "changed": False,
                "error": str(exc),
                "status": "failed",
                "watch_id": watch.id,
            },
            ts=timestamp,
        )

        return WatchRunResult(
            watch_id=watch.id,
            watch_run_id=watch_run_id,
            trace_id=persisted_trace_id,
            status="failed",
            changed=False,
            baseline_created=False,
            signature_before=signature_before,
            signature_after=signature_after,
            source_revision_id=None,
            change_event_id=None,
            delta_briefing_id=None,
            change_kind=None,
            severity=None,
            invalidated_sync_runs=0,
            next_run_at=next_run_at,
            error_text=str(exc),
        )


async def run_due_watches(
    connection: sqlite3.Connection,
    *,
    now: datetime | None = None,
    limit: int | None = None,
    trace_id: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[WatchRunResult]:
    """Run all active watches that are due at the provided timestamp."""

    due_at = _timestamp_text(now)
    watch_rows = _list_due_watch_rows(connection, due_at=due_at, limit=limit)
    results: list[WatchRunResult] = []
    for row in watch_rows:
        result = await run_watch(
            connection,
            row["id"],
            now=now,
            trace_id=trace_id,
            client=client,
        )
        results.append(result)
    return results


__all__ = [
    "ChangeDecision",
    "RadarWatch",
    "StoredDeltaBriefing",
    "StoredSourceRevision",
    "WatchRunResult",
    "list_due_watches",
    "run_due_watches",
    "run_watch",
]
