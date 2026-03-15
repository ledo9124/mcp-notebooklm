"""Repository helpers for the local SQLite cache tables."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Generic, TypeVar


RecordT = TypeVar("RecordT")


def _sqlite_bool(value: int | bool | None) -> bool | None:
    """Normalize SQLite integer booleans into Python bools."""
    if value is None:
        return None
    return bool(value)


def _workspace_tags_text(tags_json: str | None) -> str | None:
    """Expand a JSON array of tags into plain text for FTS queries."""
    if not tags_json:
        return None
    try:
        tags = json.loads(tags_json)
    except json.JSONDecodeError:
        return tags_json
    if not isinstance(tags, list):
        return tags_json
    values = [str(tag).strip() for tag in tags if str(tag).strip()]
    return " ".join(values) or None


@dataclass(frozen=True)
class NotebookRecord:
    """Cached notebook metadata stored in the local SQLite cache."""

    notebook_id: str
    profile_id: str
    title: str
    normalized_title: str
    is_owner: bool = False
    share_visibility: str | None = None
    created_at_remote: str | None = None
    source_count: int = 0
    artifact_count: int = 0
    note_count: int = 0
    summary_preview: str | None = None
    index_synced_at: str | None = None
    detail_synced_at: str | None = None
    remote_fingerprint: str | None = None
    approval_policy_json: str | None = None
    tombstoned_at: str | None = None
    raw_json: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "NotebookRecord":
        return cls(
            notebook_id=row["notebook_id"],
            profile_id=row["profile_id"],
            title=row["title"],
            normalized_title=row["normalized_title"],
            is_owner=bool(row["is_owner"]),
            share_visibility=row["share_visibility"],
            created_at_remote=row["created_at_remote"],
            source_count=row["source_count"],
            artifact_count=row["artifact_count"],
            note_count=row["note_count"],
            summary_preview=row["summary_preview"],
            index_synced_at=row["index_synced_at"],
            detail_synced_at=row["detail_synced_at"],
            remote_fingerprint=row["remote_fingerprint"],
            approval_policy_json=row["approval_policy_json"],
            tombstoned_at=row["tombstoned_at"],
            raw_json=row["raw_json"],
        )


@dataclass(frozen=True)
class SourceRecord:
    """Cached source metadata stored in the local SQLite cache."""

    source_id: str
    notebook_id: str
    profile_id: str
    source_type: str
    status: str
    title: str | None = None
    origin_uri: str | None = None
    freshness_state: str | None = None
    drive_syncable: bool | None = None
    content_preview: str | None = None
    added_at_remote: str | None = None
    updated_at_remote: str | None = None
    synced_at: str | None = None
    remote_fingerprint: str | None = None
    tombstoned_at: str | None = None
    raw_json: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SourceRecord":
        return cls(
            source_id=row["source_id"],
            notebook_id=row["notebook_id"],
            profile_id=row["profile_id"],
            source_type=row["source_type"],
            status=row["status"],
            title=row["title"],
            origin_uri=row["origin_uri"],
            freshness_state=row["freshness_state"],
            drive_syncable=_sqlite_bool(row["drive_syncable"]),
            content_preview=row["content_preview"],
            added_at_remote=row["added_at_remote"],
            updated_at_remote=row["updated_at_remote"],
            synced_at=row["synced_at"],
            remote_fingerprint=row["remote_fingerprint"],
            tombstoned_at=row["tombstoned_at"],
            raw_json=row["raw_json"],
        )


@dataclass(frozen=True)
class ArtifactRecord:
    """Cached artifact metadata stored in the local SQLite cache."""

    artifact_id: str
    notebook_id: str
    profile_id: str
    artifact_type: str
    status: str
    requested_at: str
    submode: str | None = None
    title: str | None = None
    prompt_hash: str | None = None
    last_polled_at: str | None = None
    completed_at: str | None = None
    download_ref: str | None = None
    remote_fingerprint: str | None = None
    raw_json: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ArtifactRecord":
        return cls(
            artifact_id=row["artifact_id"],
            notebook_id=row["notebook_id"],
            profile_id=row["profile_id"],
            artifact_type=row["artifact_type"],
            status=row["status"],
            requested_at=row["requested_at"],
            submode=row["submode"],
            title=row["title"],
            prompt_hash=row["prompt_hash"],
            last_polled_at=row["last_polled_at"],
            completed_at=row["completed_at"],
            download_ref=row["download_ref"],
            remote_fingerprint=row["remote_fingerprint"],
            raw_json=row["raw_json"],
        )


@dataclass(frozen=True)
class ResearchRunRecord:
    """Cached research-run metadata stored in the local SQLite cache."""

    research_id: str
    notebook_id: str
    profile_id: str
    mode: str
    query_text: str
    status: str
    started_at: str
    updated_at: str
    discovered_count: int = 0
    imported_count: int = 0
    raw_json: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ResearchRunRecord":
        return cls(
            research_id=row["research_id"],
            notebook_id=row["notebook_id"],
            profile_id=row["profile_id"],
            mode=row["mode"],
            query_text=row["query_text"],
            status=row["status"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            discovered_count=row["discovered_count"],
            imported_count=row["imported_count"],
            raw_json=row["raw_json"],
        )


@dataclass(frozen=True)
class QueryRunRecord:
    """Cached query-run metadata stored in the local SQLite cache."""

    id: str
    trace_id: str
    profile_id: str
    intent: str
    mode: str
    prompt_text: str
    prompt_hash: str
    cache_policy: str
    route_reason: str
    source_of_truth: str
    started_at: str
    status: str
    notebook_id: str | None = None
    settings_hash: str | None = None
    notebook_fingerprint: str | None = None
    ended_at: str | None = None
    reused_from: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "QueryRunRecord":
        return cls(
            id=row["id"],
            trace_id=row["trace_id"],
            profile_id=row["profile_id"],
            notebook_id=row["notebook_id"],
            intent=row["intent"],
            mode=row["mode"],
            prompt_text=row["prompt_text"],
            prompt_hash=row["prompt_hash"],
            settings_hash=row["settings_hash"],
            notebook_fingerprint=row["notebook_fingerprint"],
            cache_policy=row["cache_policy"],
            route_reason=row["route_reason"],
            source_of_truth=row["source_of_truth"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            reused_from=row["reused_from"],
        )


@dataclass(frozen=True)
class QueryResultRecord:
    """Cached query-result metadata stored in the local SQLite cache."""

    query_run_id: str
    result_type: str
    created_at: str
    answer_text: str | None = None
    citations_json: str | None = None
    artifact_id: str | None = None
    result_json: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "QueryResultRecord":
        return cls(
            query_run_id=row["query_run_id"],
            result_type=row["result_type"],
            answer_text=row["answer_text"],
            citations_json=row["citations_json"],
            artifact_id=row["artifact_id"],
            result_json=row["result_json"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class HistorySearchHitRecord:
    """Joined history-search result spanning the FTS table and run metadata."""

    run_id: str
    trace_id: str
    profile_id: str
    intent: str
    mode: str
    prompt_text: str
    started_at: str
    status: str
    notebook_id: str | None = None
    notebook_title: str | None = None
    answer_text: str | None = None
    source_titles: str | None = None
    ended_at: str | None = None
    rank: float | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "HistorySearchHitRecord":
        return cls(
            run_id=row["run_id"],
            trace_id=row["trace_id"],
            profile_id=row["profile_id"],
            notebook_id=row["notebook_id"],
            notebook_title=row["notebook_title"],
            intent=row["intent"],
            mode=row["mode"],
            prompt_text=row["prompt_text"],
            answer_text=row["answer_text"],
            source_titles=row["source_titles"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            rank=row["rank"],
        )


@dataclass(frozen=True)
class HistoryRunDetailRecord:
    """Full history detail for one query run."""

    query_run: QueryRunRecord
    query_result: QueryResultRecord | None = None
    notebook_title: str | None = None
    source_titles: str | None = None


@dataclass(frozen=True)
class SyncRunRecord:
    """Cached sync-run metadata stored in the local SQLite cache."""

    id: str
    trace_id: str
    profile_id: str
    scope: str
    trigger: str
    started_at: str
    status: str
    target_id: str | None = None
    ended_at: str | None = None
    stats_json: str | None = None
    error_text: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SyncRunRecord":
        return cls(
            id=row["id"],
            trace_id=row["trace_id"],
            profile_id=row["profile_id"],
            scope=row["scope"],
            target_id=row["target_id"],
            trigger=row["trigger"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            stats_json=row["stats_json"],
            error_text=row["error_text"],
        )


@dataclass(frozen=True)
class WorkspaceRunRecord:
    """Cached workspace-run metadata stored in the local SQLite cache."""

    id: str
    trace_id: str
    profile_id: str
    started_at: str
    status: str
    workspace_id: str
    mode: str
    ended_at: str | None = None
    query_text: str | None = None
    selected_notebooks_json: str | None = None
    plan_json: str | None = None
    result_json: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WorkspaceRunRecord":
        return cls(
            id=row["id"],
            trace_id=row["trace_id"],
            profile_id=row["profile_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            workspace_id=row["workspace_id"],
            mode=row["mode"],
            query_text=row["query_text"],
            selected_notebooks_json=row["selected_notebooks_json"],
            plan_json=row["plan_json"],
            result_json=row["result_json"],
        )


@dataclass(frozen=True)
class DoctorRunRecord:
    """Cached doctor-run metadata stored in the local SQLite cache."""

    id: str
    trace_id: str
    profile_id: str
    started_at: str
    status: str
    mode: str
    ended_at: str | None = None
    overall_status: str | None = None
    summary_json: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "DoctorRunRecord":
        return cls(
            id=row["id"],
            trace_id=row["trace_id"],
            profile_id=row["profile_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            mode=row["mode"],
            overall_status=row["overall_status"],
            summary_json=row["summary_json"],
        )


@dataclass(frozen=True)
class WorkspaceRecord:
    """Workspace metadata used for cross-notebook grouping."""

    id: str
    profile_id: str
    name: str
    slug: str
    kind: str
    created_at: str
    updated_at: str
    description: str | None = None
    query_policy_json: str | None = None
    approval_policy_json: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WorkspaceRecord":
        return cls(
            id=row["id"],
            profile_id=row["profile_id"],
            name=row["name"],
            slug=row["slug"],
            description=row["description"],
            kind=row["kind"],
            query_policy_json=row["query_policy_json"],
            approval_policy_json=row["approval_policy_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True)
class WorkspaceMemberRecord:
    """One notebook membership within a workspace."""

    id: str
    workspace_id: str
    notebook_id: str
    added_at: str
    priority: int = 0
    tags_json: str | None = None
    enabled: bool = True

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WorkspaceMemberRecord":
        return cls(
            id=row["id"],
            workspace_id=row["workspace_id"],
            notebook_id=row["notebook_id"],
            priority=row["priority"],
            tags_json=row["tags_json"],
            enabled=bool(row["enabled"]),
            added_at=row["added_at"],
        )


@dataclass(frozen=True)
class WorkspaceRuleRecord:
    """One rule-based selector for a workspace."""

    id: str
    workspace_id: str
    rule_type: str
    rule_json: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WorkspaceRuleRecord":
        return cls(
            id=row["id"],
            workspace_id=row["workspace_id"],
            rule_type=row["rule_type"],
            rule_json=row["rule_json"],
        )


@dataclass(frozen=True)
class WorkspaceIndexEntryRecord:
    """Materialized workspace search corpus for later indexing/search."""

    id: str
    workspace_id: str
    profile_id: str
    notebook_id: str
    content_text: str
    updated_at: str
    notebook_title: str | None = None
    notebook_summary: str | None = None
    title_aliases_text: str | None = None
    source_titles_text: str | None = None
    source_snippets_text: str | None = None
    tags_json: str | None = None
    recent_query_text: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WorkspaceIndexEntryRecord":
        return cls(
            id=row["id"],
            workspace_id=row["workspace_id"],
            profile_id=row["profile_id"],
            notebook_id=row["notebook_id"],
            notebook_title=row["notebook_title"],
            notebook_summary=row["notebook_summary"],
            title_aliases_text=row["title_aliases_text"],
            source_titles_text=row["source_titles_text"],
            source_snippets_text=row["source_snippets_text"],
            tags_json=row["tags_json"],
            recent_query_text=row["recent_query_text"],
            content_text=row["content_text"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True)
class WorkspaceIndexSearchHitRecord:
    """Joined workspace-index search result spanning FTS and materialized rows."""

    entry_id: str
    workspace_id: str
    profile_id: str
    notebook_id: str
    notebook_title: str | None = None
    notebook_summary: str | None = None
    tags_json: str | None = None
    recent_query_text: str | None = None
    rank: float | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WorkspaceIndexSearchHitRecord":
        return cls(
            entry_id=row["entry_id"],
            workspace_id=row["workspace_id"],
            profile_id=row["profile_id"],
            notebook_id=row["notebook_id"],
            notebook_title=row["notebook_title"],
            notebook_summary=row["notebook_summary"],
            tags_json=row["tags_json"],
            recent_query_text=row["recent_query_text"],
            rank=row["rank"],
        )


@dataclass(frozen=True)
class ApprovalRequestRecord:
    """Cached approval-request metadata stored in the local SQLite cache."""

    id: str
    trace_id: str
    entity_type: str
    entity_id: str
    action: str
    risk_tier: str
    requested_by: str
    requested_at: str
    status: str
    policy_name: str | None = None
    resolved_at: str | None = None
    reason: str | None = None
    resume_token: str | None = None
    decision_json: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ApprovalRequestRecord":
        return cls(
            id=row["id"],
            trace_id=row["trace_id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            action=row["action"],
            risk_tier=row["risk_tier"],
            policy_name=row["policy_name"],
            requested_by=row["requested_by"],
            requested_at=row["requested_at"],
            resolved_at=row["resolved_at"],
            status=row["status"],
            reason=row["reason"],
            resume_token=row["resume_token"],
            decision_json=row["decision_json"],
        )


@dataclass(frozen=True)
class InboxClusterRecord:
    """Cluster metadata for grouping related inbox items."""

    id: str
    fingerprint: str
    representative_item_id: str | None = None
    canonical_uri: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "InboxClusterRecord":
        return cls(
            id=row["id"],
            fingerprint=row["fingerprint"],
            canonical_uri=row["canonical_uri"],
            representative_item_id=row["representative_item_id"],
        )


@dataclass(frozen=True)
class InboxItemRecord:
    """One research-inbox item awaiting review or import."""

    id: str
    profile_id: str
    origin: str
    kind: str
    state: str
    title: str
    created_at: str
    notebook_id: str | None = None
    workspace_id: str | None = None
    priority: int = 0
    novelty_score: float = 0.0
    relevance_score: float = 0.0
    trust_score: float = 0.0
    approval_required: bool = True
    canonical_uri: str | None = None
    snippet: str | None = None
    rationale_json: str | None = None
    decision_at: str | None = None
    cluster_id: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "InboxItemRecord":
        return cls(
            id=row["id"],
            profile_id=row["profile_id"],
            notebook_id=row["notebook_id"],
            workspace_id=row["workspace_id"],
            origin=row["origin"],
            kind=row["kind"],
            state=row["state"],
            priority=row["priority"],
            novelty_score=row["novelty_score"],
            relevance_score=row["relevance_score"],
            trust_score=row["trust_score"],
            approval_required=bool(row["approval_required"]),
            title=row["title"],
            canonical_uri=row["canonical_uri"],
            snippet=row["snippet"],
            rationale_json=row["rationale_json"],
            created_at=row["created_at"],
            decision_at=row["decision_at"],
            cluster_id=row["cluster_id"],
        )


@dataclass(frozen=True)
class LeaseRecord:
    """Advisory lease metadata for cross-process coordination."""

    id: str
    scope_type: str
    scope_id: str
    holder: str
    purpose: str
    acquired_at: str
    expires_at: str
    advisory: bool = True

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "LeaseRecord":
        return cls(
            id=row["id"],
            scope_type=row["scope_type"],
            scope_id=row["scope_id"],
            holder=row["holder"],
            purpose=row["purpose"],
            advisory=bool(row["advisory"]),
            acquired_at=row["acquired_at"],
            expires_at=row["expires_at"],
        )


class _BaseRepository(Generic[RecordT]):
    """Common CRUD helpers shared by the metadata repositories."""

    TABLE_NAME: str
    PRIMARY_KEY: str
    COLUMNS: tuple[str, ...]

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def _serialize(self, record: RecordT) -> tuple[object, ...]:
        return tuple(getattr(record, column) for column in self.COLUMNS)

    def _upsert(self, record: RecordT) -> None:
        columns = ", ".join(self.COLUMNS)
        placeholders = ", ".join("?" for _ in self.COLUMNS)
        updates = ", ".join(
            f"{column}=excluded.{column}"
            for column in self.COLUMNS
            if column != self.PRIMARY_KEY
        )
        with self._connection:
            self._connection.execute(
                f"""
                INSERT INTO {self.TABLE_NAME} ({columns})
                VALUES ({placeholders})
                ON CONFLICT({self.PRIMARY_KEY}) DO UPDATE SET
                {updates}
                """,
                self._serialize(record),
            )

    def delete(self, identifier: str) -> None:
        """Delete one record by primary key."""
        with self._connection:
            self._connection.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = ?",
                (identifier,),
            )

    def _get_row(self, identifier: str) -> sqlite3.Row | None:
        return self._connection.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = ?",
            (identifier,),
        ).fetchone()

    def _list_rows_for_profile(self, profile_id: str) -> list[sqlite3.Row]:
        return self._connection.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE profile_id = ? ORDER BY {self.PRIMARY_KEY}",
            (profile_id,),
        ).fetchall()


class _NotebookChildRepository(_BaseRepository[RecordT]):
    """Shared query helpers for notebook-owned metadata tables."""

    def _list_rows_for_notebook(self, notebook_id: str) -> list[sqlite3.Row]:
        return self._connection.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE notebook_id = ? ORDER BY {self.PRIMARY_KEY}",
            (notebook_id,),
        ).fetchall()


class _WorkspaceChildRepository(_BaseRepository[RecordT]):
    """Shared query helpers for workspace-owned metadata tables."""

    def _list_rows_for_workspace(self, workspace_id: str) -> list[sqlite3.Row]:
        return self._connection.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE workspace_id = ? ORDER BY {self.PRIMARY_KEY}",
            (workspace_id,),
        ).fetchall()


class NotebookRepository(_BaseRepository[NotebookRecord]):
    """CRUD helper for the `notebooks` cache table."""

    TABLE_NAME = "notebooks"
    PRIMARY_KEY = "notebook_id"
    COLUMNS = (
        "notebook_id",
        "profile_id",
        "title",
        "normalized_title",
        "is_owner",
        "share_visibility",
        "created_at_remote",
        "source_count",
        "artifact_count",
        "note_count",
        "summary_preview",
        "index_synced_at",
        "detail_synced_at",
        "remote_fingerprint",
        "approval_policy_json",
        "tombstoned_at",
        "raw_json",
    )

    def upsert(self, record: NotebookRecord) -> None:
        self._upsert(record)

    def get(self, notebook_id: str) -> NotebookRecord | None:
        row = self._get_row(notebook_id)
        return NotebookRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[NotebookRecord]:
        return [NotebookRecord.from_row(row) for row in self._list_rows_for_profile(profile_id)]


class SourceRepository(_NotebookChildRepository[SourceRecord]):
    """CRUD helper for the `sources` cache table."""

    TABLE_NAME = "sources"
    PRIMARY_KEY = "source_id"
    COLUMNS = (
        "source_id",
        "notebook_id",
        "profile_id",
        "source_type",
        "title",
        "origin_uri",
        "status",
        "freshness_state",
        "drive_syncable",
        "content_preview",
        "added_at_remote",
        "updated_at_remote",
        "synced_at",
        "remote_fingerprint",
        "tombstoned_at",
        "raw_json",
    )

    def upsert(self, record: SourceRecord) -> None:
        self._upsert(record)

    def get(self, source_id: str) -> SourceRecord | None:
        row = self._get_row(source_id)
        return SourceRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[SourceRecord]:
        return [SourceRecord.from_row(row) for row in self._list_rows_for_profile(profile_id)]

    def list_for_notebook(self, notebook_id: str) -> list[SourceRecord]:
        return [SourceRecord.from_row(row) for row in self._list_rows_for_notebook(notebook_id)]


class ArtifactRepository(_NotebookChildRepository[ArtifactRecord]):
    """CRUD helper for the `artifacts` cache table."""

    TABLE_NAME = "artifacts"
    PRIMARY_KEY = "artifact_id"
    COLUMNS = (
        "artifact_id",
        "notebook_id",
        "profile_id",
        "artifact_type",
        "submode",
        "title",
        "prompt_hash",
        "status",
        "requested_at",
        "last_polled_at",
        "completed_at",
        "download_ref",
        "remote_fingerprint",
        "raw_json",
    )

    def upsert(self, record: ArtifactRecord) -> None:
        self._upsert(record)

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        row = self._get_row(artifact_id)
        return ArtifactRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[ArtifactRecord]:
        return [ArtifactRecord.from_row(row) for row in self._list_rows_for_profile(profile_id)]

    def list_for_notebook(self, notebook_id: str) -> list[ArtifactRecord]:
        return [ArtifactRecord.from_row(row) for row in self._list_rows_for_notebook(notebook_id)]


class ResearchRunRepository(_NotebookChildRepository[ResearchRunRecord]):
    """CRUD helper for the `research_runs` cache table."""

    TABLE_NAME = "research_runs"
    PRIMARY_KEY = "research_id"
    COLUMNS = (
        "research_id",
        "notebook_id",
        "profile_id",
        "mode",
        "query_text",
        "status",
        "discovered_count",
        "imported_count",
        "started_at",
        "updated_at",
        "raw_json",
    )

    def upsert(self, record: ResearchRunRecord) -> None:
        self._upsert(record)

    def get(self, research_id: str) -> ResearchRunRecord | None:
        row = self._get_row(research_id)
        return ResearchRunRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[ResearchRunRecord]:
        return [
            ResearchRunRecord.from_row(row) for row in self._list_rows_for_profile(profile_id)
        ]

    def list_for_notebook(self, notebook_id: str) -> list[ResearchRunRecord]:
        return [
            ResearchRunRecord.from_row(row) for row in self._list_rows_for_notebook(notebook_id)
        ]


class QueryRunRepository(_NotebookChildRepository[QueryRunRecord]):
    """CRUD helper for the `query_runs` history table."""

    TABLE_NAME = "query_runs"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "trace_id",
        "profile_id",
        "notebook_id",
        "intent",
        "mode",
        "prompt_text",
        "prompt_hash",
        "settings_hash",
        "notebook_fingerprint",
        "cache_policy",
        "route_reason",
        "source_of_truth",
        "started_at",
        "ended_at",
        "status",
        "reused_from",
    )

    def upsert(self, record: QueryRunRecord) -> None:
        self._upsert(record)

    def get(self, run_id: str) -> QueryRunRecord | None:
        row = self._get_row(run_id)
        return QueryRunRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[QueryRunRecord]:
        return [QueryRunRecord.from_row(row) for row in self._list_rows_for_profile(profile_id)]

    def list_for_notebook(self, notebook_id: str) -> list[QueryRunRecord]:
        return [QueryRunRecord.from_row(row) for row in self._list_rows_for_notebook(notebook_id)]

    def search_history(
        self,
        query: str,
        *,
        profile_id: str | None = None,
        limit: int = 10,
    ) -> list[HistorySearchHitRecord]:
        sql = """
            SELECT
                history_fts.run_id AS run_id,
                history_fts.trace_id AS trace_id,
                history_fts.profile_id AS profile_id,
                query_runs.notebook_id AS notebook_id,
                COALESCE(history_fts.notebook_title, notebooks.title) AS notebook_title,
                query_runs.intent AS intent,
                query_runs.mode AS mode,
                query_runs.status AS status,
                query_runs.started_at AS started_at,
                query_runs.ended_at AS ended_at,
                history_fts.prompt_text AS prompt_text,
                history_fts.answer_text AS answer_text,
                history_fts.source_titles AS source_titles,
                bm25(history_fts) AS rank
            FROM history_fts
            JOIN query_runs
                ON query_runs.id = history_fts.run_id
            LEFT JOIN notebooks
                ON notebooks.notebook_id = query_runs.notebook_id
            WHERE history_fts MATCH ?
        """
        params: list[object] = [query]
        if profile_id is not None:
            sql += " AND history_fts.profile_id = ?"
            params.append(profile_id)
        sql += """
            ORDER BY rank, query_runs.started_at DESC, history_fts.run_id ASC
            LIMIT ?
        """
        params.append(limit)
        rows = self._connection.execute(sql, params).fetchall()
        return [HistorySearchHitRecord.from_row(row) for row in rows]

    def get_history_detail(self, run_id: str) -> HistoryRunDetailRecord | None:
        row = self._connection.execute(
            """
            SELECT
                query_runs.id AS id,
                query_runs.trace_id AS trace_id,
                query_runs.profile_id AS profile_id,
                query_runs.notebook_id AS notebook_id,
                query_runs.intent AS intent,
                query_runs.mode AS mode,
                query_runs.prompt_text AS prompt_text,
                query_runs.prompt_hash AS prompt_hash,
                query_runs.settings_hash AS settings_hash,
                query_runs.notebook_fingerprint AS notebook_fingerprint,
                query_runs.cache_policy AS cache_policy,
                query_runs.route_reason AS route_reason,
                query_runs.source_of_truth AS source_of_truth,
                query_runs.started_at AS started_at,
                query_runs.ended_at AS ended_at,
                query_runs.status AS status,
                query_runs.reused_from AS reused_from,
                query_results.result_type AS result_type,
                query_results.answer_text AS result_answer_text,
                query_results.citations_json AS result_citations_json,
                query_results.artifact_id AS result_artifact_id,
                query_results.result_json AS result_result_json,
                query_results.created_at AS result_created_at,
                COALESCE(history_fts.notebook_title, notebooks.title) AS notebook_title,
                history_fts.source_titles AS source_titles
            FROM query_runs
            LEFT JOIN query_results
                ON query_results.query_run_id = query_runs.id
            LEFT JOIN history_fts
                ON history_fts.run_id = query_runs.id
            LEFT JOIN notebooks
                ON notebooks.notebook_id = query_runs.notebook_id
            WHERE query_runs.id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None

        query_result = None
        if row["result_type"] is not None:
            query_result = QueryResultRecord(
                query_run_id=run_id,
                result_type=row["result_type"],
                answer_text=row["result_answer_text"],
                citations_json=row["result_citations_json"],
                artifact_id=row["result_artifact_id"],
                result_json=row["result_result_json"],
                created_at=row["result_created_at"],
            )

        return HistoryRunDetailRecord(
            query_run=QueryRunRecord.from_row(row),
            query_result=query_result,
            notebook_title=row["notebook_title"],
            source_titles=row["source_titles"],
        )


class QueryResultRepository(_BaseRepository[QueryResultRecord]):
    """CRUD helper for the `query_results` history table."""

    TABLE_NAME = "query_results"
    PRIMARY_KEY = "query_run_id"
    COLUMNS = (
        "query_run_id",
        "result_type",
        "answer_text",
        "citations_json",
        "artifact_id",
        "result_json",
        "created_at",
    )

    def upsert(self, record: QueryResultRecord) -> None:
        self._upsert(record)

    def get(self, query_run_id: str) -> QueryResultRecord | None:
        row = self._get_row(query_run_id)
        return QueryResultRecord.from_row(row) if row else None


class SyncRunRepository(_BaseRepository[SyncRunRecord]):
    """CRUD helper for the `sync_runs` history table."""

    TABLE_NAME = "sync_runs"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "trace_id",
        "profile_id",
        "scope",
        "target_id",
        "trigger",
        "started_at",
        "ended_at",
        "status",
        "stats_json",
        "error_text",
    )

    def upsert(self, record: SyncRunRecord) -> None:
        self._upsert(record)

    def get(self, run_id: str) -> SyncRunRecord | None:
        row = self._get_row(run_id)
        return SyncRunRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[SyncRunRecord]:
        return [SyncRunRecord.from_row(row) for row in self._list_rows_for_profile(profile_id)]


class WorkspaceRepository(_BaseRepository[WorkspaceRecord]):
    """CRUD helper for persisted workspaces."""

    TABLE_NAME = "workspaces"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "profile_id",
        "name",
        "slug",
        "description",
        "kind",
        "query_policy_json",
        "approval_policy_json",
        "created_at",
        "updated_at",
    )

    def upsert(self, record: WorkspaceRecord) -> None:
        self._upsert(record)

    def get(self, workspace_id: str) -> WorkspaceRecord | None:
        row = self._get_row(workspace_id)
        return WorkspaceRecord.from_row(row) if row else None

    def get_by_slug(self, profile_id: str, slug: str) -> WorkspaceRecord | None:
        row = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE profile_id = ? AND slug = ?
            """,
            (profile_id, slug),
        ).fetchone()
        return WorkspaceRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[WorkspaceRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE profile_id = ?
            ORDER BY slug, id
            """,
            (profile_id,),
        ).fetchall()
        return [WorkspaceRecord.from_row(row) for row in rows]


class WorkspaceMemberRepository(_WorkspaceChildRepository[WorkspaceMemberRecord]):
    """CRUD helper for static workspace membership rows."""

    TABLE_NAME = "workspace_members"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "workspace_id",
        "notebook_id",
        "priority",
        "tags_json",
        "enabled",
        "added_at",
    )

    def upsert(self, record: WorkspaceMemberRecord) -> None:
        self._upsert(record)

    def get(self, member_id: str) -> WorkspaceMemberRecord | None:
        row = self._get_row(member_id)
        return WorkspaceMemberRecord.from_row(row) if row else None

    def list_for_workspace(self, workspace_id: str) -> list[WorkspaceMemberRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE workspace_id = ?
            ORDER BY priority DESC, added_at ASC, id ASC
            """,
            (workspace_id,),
        ).fetchall()
        return [WorkspaceMemberRecord.from_row(row) for row in rows]

    def list_for_notebook(self, notebook_id: str) -> list[WorkspaceMemberRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE notebook_id = ?
            ORDER BY priority DESC, added_at ASC, id ASC
            """,
            (notebook_id,),
        ).fetchall()
        return [WorkspaceMemberRecord.from_row(row) for row in rows]


class WorkspaceRuleRepository(_WorkspaceChildRepository[WorkspaceRuleRecord]):
    """CRUD helper for rule-based workspace selectors."""

    TABLE_NAME = "workspace_rules"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "workspace_id",
        "rule_type",
        "rule_json",
    )

    def upsert(self, record: WorkspaceRuleRecord) -> None:
        self._upsert(record)

    def get(self, rule_id: str) -> WorkspaceRuleRecord | None:
        row = self._get_row(rule_id)
        return WorkspaceRuleRecord.from_row(row) if row else None

    def list_for_workspace(self, workspace_id: str) -> list[WorkspaceRuleRecord]:
        return [
            WorkspaceRuleRecord.from_row(row)
            for row in self._list_rows_for_workspace(workspace_id)
        ]


class WorkspaceIndexEntryRepository(_WorkspaceChildRepository[WorkspaceIndexEntryRecord]):
    """CRUD helper for the materialized workspace search corpus."""

    TABLE_NAME = "workspace_index_entries"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "workspace_id",
        "profile_id",
        "notebook_id",
        "notebook_title",
        "notebook_summary",
        "title_aliases_text",
        "source_titles_text",
        "source_snippets_text",
        "tags_json",
        "recent_query_text",
        "content_text",
        "updated_at",
    )

    def upsert(self, record: WorkspaceIndexEntryRecord) -> None:
        self._upsert(record)

    def replace_for_workspace(
        self,
        workspace_id: str,
        entries: list[WorkspaceIndexEntryRecord],
    ) -> None:
        """Replace one workspace corpus and keep its FTS rows in sync."""
        columns = ", ".join(self.COLUMNS)
        placeholders = ", ".join("?" for _ in self.COLUMNS)
        with self._connection:
            self._connection.execute(
                "DELETE FROM workspace_index_fts WHERE workspace_id = ?",
                (workspace_id,),
            )
            self._connection.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE workspace_id = ?",
                (workspace_id,),
            )
            for record in entries:
                self._connection.execute(
                    f"""
                    INSERT INTO {self.TABLE_NAME} ({columns})
                    VALUES ({placeholders})
                    """,
                    self._serialize(record),
                )
                self._connection.execute(
                    """
                    INSERT INTO workspace_index_fts (
                        entry_id,
                        workspace_id,
                        profile_id,
                        notebook_id,
                        notebook_title,
                        notebook_summary,
                        title_aliases_text,
                        source_titles_text,
                        source_snippets_text,
                        tags_text,
                        recent_query_text,
                        content_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.workspace_id,
                        record.profile_id,
                        record.notebook_id,
                        record.notebook_title,
                        record.notebook_summary,
                        record.title_aliases_text,
                        record.source_titles_text,
                        record.source_snippets_text,
                        _workspace_tags_text(record.tags_json),
                        record.recent_query_text,
                        record.content_text,
                    ),
                )

    def get(self, entry_id: str) -> WorkspaceIndexEntryRecord | None:
        row = self._get_row(entry_id)
        return WorkspaceIndexEntryRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[WorkspaceIndexEntryRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE profile_id = ?
            ORDER BY updated_at DESC, id ASC
            """,
            (profile_id,),
        ).fetchall()
        return [WorkspaceIndexEntryRecord.from_row(row) for row in rows]

    def list_for_workspace(self, workspace_id: str) -> list[WorkspaceIndexEntryRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE workspace_id = ?
            ORDER BY updated_at DESC, id ASC
            """,
            (workspace_id,),
        ).fetchall()
        return [WorkspaceIndexEntryRecord.from_row(row) for row in rows]

    def list_for_notebook(self, notebook_id: str) -> list[WorkspaceIndexEntryRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE notebook_id = ?
            ORDER BY updated_at DESC, id ASC
            """,
            (notebook_id,),
        ).fetchall()
        return [WorkspaceIndexEntryRecord.from_row(row) for row in rows]

    def search(
        self,
        query: str,
        *,
        workspace_id: str,
        profile_id: str | None = None,
        limit: int = 10,
    ) -> list[WorkspaceIndexSearchHitRecord]:
        sql = """
            SELECT
                workspace_index_fts.entry_id AS entry_id,
                workspace_index_fts.workspace_id AS workspace_id,
                workspace_index_fts.profile_id AS profile_id,
                workspace_index_fts.notebook_id AS notebook_id,
                workspace_index_entries.notebook_title AS notebook_title,
                workspace_index_entries.notebook_summary AS notebook_summary,
                workspace_index_entries.tags_json AS tags_json,
                workspace_index_entries.recent_query_text AS recent_query_text,
                bm25(workspace_index_fts) AS rank
            FROM workspace_index_fts
            JOIN workspace_index_entries
                ON workspace_index_entries.id = workspace_index_fts.entry_id
            WHERE workspace_index_fts MATCH ?
              AND workspace_index_fts.workspace_id = ?
        """
        params: list[object] = [query, workspace_id]
        if profile_id is not None:
            sql += " AND workspace_index_fts.profile_id = ?"
            params.append(profile_id)
        sql += """
            ORDER BY rank, workspace_index_entries.notebook_title ASC, workspace_index_fts.entry_id ASC
            LIMIT ?
        """
        params.append(limit)
        rows = self._connection.execute(sql, params).fetchall()
        return [WorkspaceIndexSearchHitRecord.from_row(row) for row in rows]


class WorkspaceRunRepository(_BaseRepository[WorkspaceRunRecord]):
    """CRUD helper for the `workspace_runs` history table."""

    TABLE_NAME = "workspace_runs"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "trace_id",
        "profile_id",
        "started_at",
        "ended_at",
        "status",
        "workspace_id",
        "mode",
        "query_text",
        "selected_notebooks_json",
        "plan_json",
        "result_json",
    )

    def upsert(self, record: WorkspaceRunRecord) -> None:
        self._upsert(record)

    def get(self, run_id: str) -> WorkspaceRunRecord | None:
        row = self._get_row(run_id)
        return WorkspaceRunRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[WorkspaceRunRecord]:
        return [WorkspaceRunRecord.from_row(row) for row in self._list_rows_for_profile(profile_id)]

    def list_for_workspace(self, workspace_id: str) -> list[WorkspaceRunRecord]:
        rows = self._connection.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE workspace_id = ? ORDER BY {self.PRIMARY_KEY}",
            (workspace_id,),
        ).fetchall()
        return [WorkspaceRunRecord.from_row(row) for row in rows]


class DoctorRunRepository(_BaseRepository[DoctorRunRecord]):
    """CRUD helper for the `doctor_runs` history table."""

    TABLE_NAME = "doctor_runs"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "trace_id",
        "profile_id",
        "started_at",
        "ended_at",
        "status",
        "mode",
        "overall_status",
        "summary_json",
    )

    def upsert(self, record: DoctorRunRecord) -> None:
        self._upsert(record)

    def get(self, run_id: str) -> DoctorRunRecord | None:
        row = self._get_row(run_id)
        return DoctorRunRecord.from_row(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[DoctorRunRecord]:
        return [DoctorRunRecord.from_row(row) for row in self._list_rows_for_profile(profile_id)]


class ApprovalRequestRepository(_BaseRepository[ApprovalRequestRecord]):
    """CRUD helper for the `approval_requests` safety table."""

    TABLE_NAME = "approval_requests"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "trace_id",
        "entity_type",
        "entity_id",
        "action",
        "risk_tier",
        "policy_name",
        "requested_by",
        "requested_at",
        "resolved_at",
        "status",
        "reason",
        "resume_token",
        "decision_json",
    )
    TERMINAL_STATUSES = ("approved", "rejected", "expired", "cancelled")

    def upsert(self, record: ApprovalRequestRecord) -> None:
        self._upsert(record)

    def get(self, approval_id: str) -> ApprovalRequestRecord | None:
        row = self._get_row(approval_id)
        return ApprovalRequestRecord.from_row(row) if row else None

    def get_by_resume_token(self, resume_token: str) -> ApprovalRequestRecord | None:
        row = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE resume_token = ?
            ORDER BY requested_at DESC, id DESC
            LIMIT 1
            """,
            (resume_token,),
        ).fetchone()
        return ApprovalRequestRecord.from_row(row) if row else None

    def list_pending(self) -> list[ApprovalRequestRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE status = 'pending'
            ORDER BY requested_at, id
            """
        ).fetchall()
        return [ApprovalRequestRecord.from_row(row) for row in rows]

    def list_for_entity(self, entity_type: str, entity_id: str) -> list[ApprovalRequestRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY requested_at, id
            """,
            (entity_type, entity_id),
        ).fetchall()
        return [ApprovalRequestRecord.from_row(row) for row in rows]

    def resolve(
        self,
        approval_id: str,
        *,
        status: str,
        resolved_at: str,
        decision_json: str | None = None,
    ) -> None:
        if status not in self.TERMINAL_STATUSES:
            raise ValueError("Approval resolution status must be terminal")
        with self._connection:
            self._connection.execute(
                f"""
                UPDATE {self.TABLE_NAME}
                SET status = ?, resolved_at = ?, decision_json = ?
                WHERE {self.PRIMARY_KEY} = ?
                """,
                (status, resolved_at, decision_json, approval_id),
                )


class LeaseRepository(_BaseRepository[LeaseRecord]):
    """CRUD helper for advisory lease records shared across post-MVP features."""

    TABLE_NAME = "leases"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "scope_type",
        "scope_id",
        "holder",
        "purpose",
        "advisory",
        "acquired_at",
        "expires_at",
    )

    def acquire(self, record: LeaseRecord) -> LeaseRecord:
        columns = ", ".join(self.COLUMNS)
        placeholders = ", ".join("?" for _ in self.COLUMNS)
        with self._connection:
            self._connection.execute(
                f"""
                INSERT INTO {self.TABLE_NAME} ({columns})
                VALUES ({placeholders})
                ON CONFLICT(scope_type, scope_id, holder) DO UPDATE SET
                    purpose = excluded.purpose,
                    advisory = excluded.advisory,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                """,
                self._serialize(record),
            )
        rows = self.list_for_scope(record.scope_type, record.scope_id)
        for lease in rows:
            if lease.holder == record.holder:
                return lease
        raise RuntimeError("Lease acquire did not persist a row")

    def get(self, lease_id: str) -> LeaseRecord | None:
        row = self._get_row(lease_id)
        return LeaseRecord.from_row(row) if row else None

    def release(self, lease_id: str) -> None:
        self.delete(lease_id)

    def list_for_holder(
        self,
        holder: str,
        *,
        active_at: str | None = None,
    ) -> list[LeaseRecord]:
        sql = f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE holder = ?
        """
        params: list[object] = [holder]
        if active_at is not None:
            sql += " AND expires_at >= ?"
            params.append(active_at)
        sql += " ORDER BY expires_at, acquired_at, id"
        rows = self._connection.execute(sql, params).fetchall()
        return [LeaseRecord.from_row(row) for row in rows]

    def list_for_scope(
        self,
        scope_type: str,
        scope_id: str,
        *,
        active_at: str | None = None,
    ) -> list[LeaseRecord]:
        sql = f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE scope_type = ? AND scope_id = ?
        """
        params: list[object] = [scope_type, scope_id]
        if active_at is not None:
            sql += " AND expires_at >= ?"
            params.append(active_at)
        sql += " ORDER BY expires_at, acquired_at, id"
        rows = self._connection.execute(sql, params).fetchall()
        return [LeaseRecord.from_row(row) for row in rows]

    def list_active(self, *, active_at: str) -> list[LeaseRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE expires_at >= ?
            ORDER BY expires_at, acquired_at, id
            """,
            (active_at,),
        ).fetchall()
        return [LeaseRecord.from_row(row) for row in rows]

    def list_stale(self, *, active_at: str) -> list[LeaseRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE expires_at < ?
            ORDER BY expires_at, acquired_at, id
            """,
            (active_at,),
        ).fetchall()
        return [LeaseRecord.from_row(row) for row in rows]

    def expire_stale(self, *, active_at: str) -> int:
        with self._connection:
            cursor = self._connection.execute(
                f"""
                DELETE FROM {self.TABLE_NAME}
                WHERE expires_at < ?
                """,
                (active_at,),
            )
        return cursor.rowcount


class InboxClusterRepository(_BaseRepository[InboxClusterRecord]):
    """CRUD helper for dedupe/cluster metadata in the research inbox."""

    TABLE_NAME = "inbox_clusters"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "fingerprint",
        "canonical_uri",
        "representative_item_id",
    )

    def upsert(self, record: InboxClusterRecord) -> None:
        self._upsert(record)

    def get(self, cluster_id: str) -> InboxClusterRecord | None:
        row = self._get_row(cluster_id)
        return InboxClusterRecord.from_row(row) if row else None

    def get_by_fingerprint(self, fingerprint: str) -> InboxClusterRecord | None:
        row = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE fingerprint = ?
            """,
            (fingerprint,),
        ).fetchone()
        return InboxClusterRecord.from_row(row) if row else None

    def list_all(self) -> list[InboxClusterRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            ORDER BY id
            """
        ).fetchall()
        return [InboxClusterRecord.from_row(row) for row in rows]


class InboxItemRepository(_BaseRepository[InboxItemRecord]):
    """CRUD helper for the post-MVP research inbox tables."""

    TABLE_NAME = "inbox_items"
    PRIMARY_KEY = "id"
    COLUMNS = (
        "id",
        "profile_id",
        "notebook_id",
        "workspace_id",
        "origin",
        "kind",
        "state",
        "priority",
        "novelty_score",
        "relevance_score",
        "trust_score",
        "approval_required",
        "title",
        "canonical_uri",
        "snippet",
        "rationale_json",
        "created_at",
        "decision_at",
        "cluster_id",
    )

    def upsert(self, record: InboxItemRecord) -> None:
        self._upsert(record)

    def get(self, item_id: str) -> InboxItemRecord | None:
        row = self._get_row(item_id)
        return InboxItemRecord.from_row(row) if row else None

    def list_for_profile(
        self,
        profile_id: str,
        *,
        state: str | None = None,
    ) -> list[InboxItemRecord]:
        sql = f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE profile_id = ?
        """
        params: list[object] = [profile_id]
        if state is not None:
            sql += " AND state = ?"
            params.append(state)
        sql += " ORDER BY priority DESC, created_at DESC, id ASC"
        rows = self._connection.execute(sql, params).fetchall()
        return [InboxItemRecord.from_row(row) for row in rows]

    def list_for_notebook(self, notebook_id: str) -> list[InboxItemRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE notebook_id = ?
            ORDER BY priority DESC, created_at DESC, id ASC
            """,
            (notebook_id,),
        ).fetchall()
        return [InboxItemRecord.from_row(row) for row in rows]

    def list_for_cluster(self, cluster_id: str) -> list[InboxItemRecord]:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE cluster_id = ?
            ORDER BY priority DESC, created_at DESC, id ASC
            """,
            (cluster_id,),
        ).fetchall()
        return [InboxItemRecord.from_row(row) for row in rows]


__all__ = [
    "ApprovalRequestRecord",
    "ApprovalRequestRepository",
    "ArtifactRecord",
    "ArtifactRepository",
    "DoctorRunRecord",
    "DoctorRunRepository",
    "HistoryRunDetailRecord",
    "HistorySearchHitRecord",
    "InboxClusterRecord",
    "InboxClusterRepository",
    "InboxItemRecord",
    "InboxItemRepository",
    "LeaseRecord",
    "LeaseRepository",
    "NotebookRecord",
    "NotebookRepository",
    "QueryResultRecord",
    "QueryResultRepository",
    "QueryRunRecord",
    "QueryRunRepository",
    "ResearchRunRecord",
    "ResearchRunRepository",
    "SourceRecord",
    "SourceRepository",
    "SyncRunRecord",
    "SyncRunRepository",
    "WorkspaceIndexEntryRecord",
    "WorkspaceIndexEntryRepository",
    "WorkspaceIndexSearchHitRecord",
    "WorkspaceMemberRecord",
    "WorkspaceMemberRepository",
    "WorkspaceRecord",
    "WorkspaceRepository",
    "WorkspaceRuleRecord",
    "WorkspaceRuleRepository",
    "WorkspaceRunRecord",
    "WorkspaceRunRepository",
]
