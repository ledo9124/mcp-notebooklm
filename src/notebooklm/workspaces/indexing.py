"""Local helpers for building and querying workspace search indexes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import sqlite3

from ..local.repositories import (
    LeaseRecord,
    LeaseRepository,
    NotebookRepository,
    SourceRepository,
    WorkspaceIndexEntryRecord,
    WorkspaceIndexEntryRepository,
    WorkspaceIndexSearchHitRecord,
    WorkspaceMemberRecord,
    WorkspaceMemberRepository,
    WorkspaceRecord,
)

_WORKSPACE_INDEX_HOLDER = "workspace.index"
_DEFAULT_LEASE_TTL_SECONDS = 300
_DEFAULT_CANDIDATE_LIMIT = 3
_DEFAULT_CANDIDATE_SEARCH_LIMIT = 8
_RECENT_QUERY_LIMIT = 3
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")
_QUERY_TOKEN_LIMIT = 8


@dataclass(frozen=True)
class WorkspaceIndexBuildResult:
    """Summary for one workspace-index rebuild."""

    workspace_id: str
    profile_id: str
    entry_count: int
    notebook_ids: tuple[str, ...]
    lease_id: str


@dataclass(frozen=True)
class WorkspaceCandidateRecord:
    """One workspace notebook shortlisted for a later ask/compare plan."""

    entry_id: str
    workspace_id: str
    profile_id: str
    notebook_id: str
    notebook_title: str | None = None
    notebook_summary: str | None = None
    member_priority: int = 0
    tags: tuple[str, ...] = ()
    recent_query_text: str | None = None
    fts_rank: float | None = None
    selection_reason: str = "fts"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _expires_at(started_at: str, ttl_seconds: int) -> str:
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return (started + timedelta(seconds=ttl_seconds)).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:20]}"


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.split())
    return collapsed or None


def _join_text(*parts: str | None) -> str:
    values = [value for value in (_normalize_text(part) for part in parts) if value]
    return "\n".join(values)


def _decode_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = [raw]
    if not isinstance(data, list):
        data = [data]
    return sorted({str(tag).strip() for tag in data if str(tag).strip()})


def _query_terms(value: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in _QUERY_TOKEN_RE.findall(value.casefold()):
        if len(token) <= 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= _QUERY_TOKEN_LIMIT:
            break
    return tuple(terms)


def _fts_query(value: str) -> str | None:
    terms = _query_terms(value)
    if not terms:
        return None
    return " OR ".join(f'"{term}"' for term in terms)


def _candidate_from_entry(
    entry: WorkspaceIndexEntryRecord,
    member: WorkspaceMemberRecord,
    *,
    fts_rank: float | None,
    selection_reason: str,
) -> WorkspaceCandidateRecord:
    return WorkspaceCandidateRecord(
        entry_id=entry.id,
        workspace_id=entry.workspace_id,
        profile_id=entry.profile_id,
        notebook_id=entry.notebook_id,
        notebook_title=entry.notebook_title,
        notebook_summary=entry.notebook_summary,
        member_priority=member.priority,
        tags=tuple(_decode_tags(entry.tags_json)),
        recent_query_text=entry.recent_query_text,
        fts_rank=fts_rank,
        selection_reason=selection_reason,
    )


def _recent_query_text(connection: sqlite3.Connection, notebook_id: str) -> str | None:
    rows = connection.execute(
        """
        SELECT
            query_runs.prompt_text AS prompt_text,
            query_results.answer_text AS answer_text
        FROM query_runs
        LEFT JOIN query_results
            ON query_results.query_run_id = query_runs.id
        WHERE query_runs.notebook_id = ?
          AND query_runs.status = 'completed'
        ORDER BY COALESCE(query_runs.ended_at, query_runs.started_at) DESC, query_runs.id DESC
        LIMIT ?
        """,
        (notebook_id, _RECENT_QUERY_LIMIT),
    ).fetchall()
    content = _join_text(
        *[
            _join_text(row["prompt_text"], row["answer_text"])
            for row in rows
        ]
    )
    return content or None


def _entry_for_member(
    connection: sqlite3.Connection,
    *,
    workspace: WorkspaceRecord,
    member: WorkspaceMemberRecord,
    updated_at: str,
) -> WorkspaceIndexEntryRecord | None:
    notebook = NotebookRepository(connection).get(member.notebook_id)
    if notebook is None or notebook.tombstoned_at is not None:
        return None

    sources = [
        source
        for source in SourceRepository(connection).list_for_notebook(member.notebook_id)
        if source.tombstoned_at is None
    ]
    tags = _decode_tags(member.tags_json)
    tags_json = json.dumps(tags, separators=(",", ":"), ensure_ascii=True) if tags else None
    title_aliases_text = (
        notebook.normalized_title
        if notebook.normalized_title and notebook.normalized_title != notebook.title.casefold()
        else None
    )
    source_titles_text = _join_text(*(source.title for source in sources))
    source_snippets_text = _join_text(*(source.content_preview for source in sources))
    recent_query_text = _recent_query_text(connection, member.notebook_id)
    content_text = _join_text(
        notebook.title,
        notebook.summary_preview,
        title_aliases_text,
        source_titles_text,
        source_snippets_text,
        " ".join(tags) if tags else None,
        recent_query_text,
    )
    if not content_text:
        content_text = notebook.title

    return WorkspaceIndexEntryRecord(
        id=_stable_id("wsi", workspace.id, member.notebook_id),
        workspace_id=workspace.id,
        profile_id=workspace.profile_id,
        notebook_id=member.notebook_id,
        notebook_title=notebook.title,
        notebook_summary=notebook.summary_preview,
        title_aliases_text=title_aliases_text,
        source_titles_text=source_titles_text or None,
        source_snippets_text=source_snippets_text or None,
        tags_json=tags_json,
        recent_query_text=recent_query_text,
        content_text=content_text,
        updated_at=updated_at,
    )


def build_workspace_index(
    connection: sqlite3.Connection,
    *,
    workspace: WorkspaceRecord,
    holder: str = _WORKSPACE_INDEX_HOLDER,
    lease_ttl_seconds: int = _DEFAULT_LEASE_TTL_SECONDS,
    now: str | None = None,
) -> WorkspaceIndexBuildResult:
    """Rebuild the materialized workspace corpus and its FTS mirror."""
    updated_at = now or _utc_now()
    lease = LeaseRepository(connection).acquire(
        LeaseRecord(
            id=_stable_id("lease", workspace.id, holder),
            scope_type="workspace",
            scope_id=workspace.id,
            holder=holder,
            purpose="rebuild workspace index",
            acquired_at=updated_at,
            expires_at=_expires_at(updated_at, lease_ttl_seconds),
            advisory=True,
        )
    )
    try:
        members = [
            member
            for member in WorkspaceMemberRepository(connection).list_for_workspace(workspace.id)
            if member.enabled
        ]
        entries = [
            entry
            for entry in (
                _entry_for_member(
                    connection,
                    workspace=workspace,
                    member=member,
                    updated_at=updated_at,
                )
                for member in members
            )
            if entry is not None
        ]
        WorkspaceIndexEntryRepository(connection).replace_for_workspace(workspace.id, entries)
        return WorkspaceIndexBuildResult(
            workspace_id=workspace.id,
            profile_id=workspace.profile_id,
            entry_count=len(entries),
            notebook_ids=tuple(entry.notebook_id for entry in entries),
            lease_id=lease.id,
        )
    finally:
        LeaseRepository(connection).release(lease.id)


def search_workspace_index(
    connection: sqlite3.Connection,
    *,
    workspace: WorkspaceRecord,
    query: str,
    limit: int = 10,
) -> list[WorkspaceIndexSearchHitRecord]:
    """Query the workspace FTS corpus for one workspace."""
    return WorkspaceIndexEntryRepository(connection).search(
        query,
        workspace_id=workspace.id,
        profile_id=workspace.profile_id,
        limit=limit,
    )


def select_workspace_candidates(
    connection: sqlite3.Connection,
    *,
    workspace: WorkspaceRecord,
    query: str,
    limit: int = _DEFAULT_CANDIDATE_LIMIT,
    search_limit: int = _DEFAULT_CANDIDATE_SEARCH_LIMIT,
) -> list[WorkspaceCandidateRecord]:
    """Return a ranked local shortlist for a future workspace ask/compare plan."""
    if limit <= 0:
        return []

    members = [
        member
        for member in WorkspaceMemberRepository(connection).list_for_workspace(workspace.id)
        if member.enabled
    ]
    member_by_notebook = {member.notebook_id: member for member in members}
    if not member_by_notebook:
        return []

    entries = {
        entry.notebook_id: entry
        for entry in WorkspaceIndexEntryRepository(connection).list_for_workspace(workspace.id)
        if entry.profile_id == workspace.profile_id
    }
    if not entries:
        return []

    normalized_query = _fts_query(query)
    if normalized_query is not None:
        hits = search_workspace_index(
            connection,
            workspace=workspace,
            query=normalized_query,
            limit=max(limit, search_limit),
        )
        candidates = [
            _candidate_from_entry(
                entries[hit.notebook_id],
                member_by_notebook[hit.notebook_id],
                fts_rank=hit.rank,
                selection_reason="fts",
            )
            for hit in hits
            if hit.notebook_id in entries and hit.notebook_id in member_by_notebook
        ]
        if candidates:
            return sorted(
                candidates,
                key=lambda candidate: (
                    float("inf") if candidate.fts_rank is None else candidate.fts_rank,
                    -candidate.member_priority,
                    candidate.notebook_title or "",
                    candidate.notebook_id,
                ),
            )[:limit]

    return [
        _candidate_from_entry(
            entries[member.notebook_id],
            member,
            fts_rank=None,
            selection_reason="priority_fallback",
        )
        for member in members
        if member.notebook_id in entries
    ][:limit]


__all__ = [
    "WorkspaceCandidateRecord",
    "WorkspaceIndexBuildResult",
    "build_workspace_index",
    "select_workspace_candidates",
    "search_workspace_index",
]
