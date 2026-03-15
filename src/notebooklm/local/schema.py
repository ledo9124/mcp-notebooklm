"""SQLite schema helpers for the local NotebookLM cache."""

from __future__ import annotations

import sqlite3


INITIAL_SCHEMA_VERSION = 1
LATEST_SCHEMA_VERSION = 11
APP_STATE_SINGLETON_KEY = 1
MVP_TABLES = (
    "profiles",
    "auth_snapshots",
    "app_state",
    "notebooks",
    "sources",
    "artifacts",
    "research_runs",
    "query_runs",
    "query_results",
    "sync_runs",
    "run_events",
    "approval_requests",
)
HISTORY_TABLES = ("history_fts",)
INBOX_TABLES = (
    "inbox_items",
    "inbox_clusters",
)
RADAR_TABLES = (
    "watches",
    "watch_runs",
    "source_revisions",
    "change_events",
    "delta_briefings",
)
LEASE_TABLES = ("leases",)
WORKSPACE_TABLES = (
    "workspaces",
    "workspace_members",
    "workspace_rules",
    "workspace_index_entries",
    "workspace_index_fts",
)
POST_MVP_RUN_TABLES = (
    "workspace_runs",
    "doctor_runs",
)
INDEX_NAMES = (
    "idx_profiles_default",
    "idx_notebooks_profile_id",
    "idx_notebooks_profile_normalized_title",
    "idx_sources_notebook_id",
    "idx_sources_profile_id",
    "idx_sources_notebook_status",
    "idx_sources_profile_source_type",
    "idx_artifacts_notebook_id",
    "idx_artifacts_profile_id",
    "idx_artifacts_notebook_status",
    "idx_research_runs_notebook_id",
    "idx_research_runs_profile_id",
    "idx_query_runs_profile_id",
    "idx_query_runs_notebook_id",
    "idx_query_runs_prompt_hash",
    "idx_query_runs_prompt_fingerprint_intent",
    "idx_sync_runs_profile_id",
    "idx_sync_runs_profile_scope_started_at",
    "idx_run_events_trace_id",
    "idx_inbox_clusters_fingerprint",
    "idx_inbox_items_profile_state",
    "idx_inbox_items_notebook_state",
    "idx_inbox_items_cluster_id",
    "idx_watches_profile_id",
    "idx_watches_scope_type_scope_id",
    "idx_watches_status_next_run_at",
    "idx_watch_runs_watch_id",
    "idx_watch_runs_profile_id",
    "idx_source_revisions_source_revision_key",
    "idx_source_revisions_source_fetched_at",
    "idx_change_events_watch_created_at",
    "idx_change_events_state_created_at",
    "idx_delta_briefings_change_event_id",
    "idx_workspaces_profile_id",
    "idx_workspaces_profile_slug",
    "idx_workspace_members_workspace_id",
    "idx_workspace_members_notebook_id",
    "idx_workspace_rules_workspace_id",
    "idx_workspace_index_entries_workspace_id",
    "idx_workspace_index_entries_profile_id",
    "idx_workspace_index_entries_notebook_id",
    "idx_workspace_runs_profile_id",
    "idx_workspace_runs_workspace_id",
    "idx_doctor_runs_profile_id",
    "idx_leases_scope_type_scope_id",
    "idx_leases_holder",
    "idx_leases_expires_at",
)

_APPROVAL_REQUESTS_STATEMENT = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT NOT NULL PRIMARY KEY CHECK (id LIKE 'appr_%'),
    trace_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    risk_tier TEXT NOT NULL
        CHECK (
            risk_tier IN (
                'T0_READ',
                'T1_LOCAL_MUTATION',
                'T2_KNOWLEDGE_MUTATION',
                'T3_DESTRUCTIVE'
            )
        ),
    policy_name TEXT,
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    resolved_at TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
    reason TEXT,
    resume_token TEXT,
    decision_json TEXT
)
"""

_HISTORY_TABLES_STATEMENTS = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
        run_id UNINDEXED,
        trace_id UNINDEXED,
        profile_id UNINDEXED,
        prompt_text,
        answer_text,
        notebook_title,
        source_titles
    )
    """,
)

_MVP_INDEX_STATEMENTS = (
    """
    CREATE INDEX IF NOT EXISTS idx_sources_notebook_status
    ON sources (notebook_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sources_profile_source_type
    ON sources (profile_id, source_type)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_artifacts_notebook_status
    ON artifacts (notebook_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_query_runs_prompt_fingerprint_intent
    ON query_runs (prompt_hash, notebook_fingerprint, intent)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sync_runs_profile_scope_started_at
    ON sync_runs (profile_id, scope, started_at)
    """,
)

_INBOX_INDEX_STATEMENTS = (
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_clusters_fingerprint
    ON inbox_clusters (fingerprint)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_inbox_items_profile_state
    ON inbox_items (profile_id, state)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_inbox_items_notebook_state
    ON inbox_items (notebook_id, state)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_inbox_items_cluster_id
    ON inbox_items (cluster_id)
    """,
)

_RADAR_INDEX_STATEMENTS = (
    """
    CREATE INDEX IF NOT EXISTS idx_watches_profile_id
    ON watches (profile_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_watches_scope_type_scope_id
    ON watches (scope_type, scope_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_watches_status_next_run_at
    ON watches (status, next_run_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_watch_runs_watch_id
    ON watch_runs (watch_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_watch_runs_profile_id
    ON watch_runs (profile_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_source_revisions_source_revision_key
    ON source_revisions (source_id, revision_key)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_source_revisions_source_fetched_at
    ON source_revisions (source_id, fetched_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_change_events_watch_created_at
    ON change_events (watch_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_change_events_state_created_at
    ON change_events (state, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_delta_briefings_change_event_id
    ON delta_briefings (change_event_id)
    """,
)

_LEASE_INDEX_STATEMENTS = (
    """
    CREATE INDEX IF NOT EXISTS idx_leases_scope_type_scope_id
    ON leases (scope_type, scope_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_leases_holder
    ON leases (holder)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_leases_expires_at
    ON leases (expires_at)
    """,
)

_WORKSPACE_INDEX_STATEMENTS = (
    """
    CREATE INDEX IF NOT EXISTS idx_workspaces_profile_id
    ON workspaces (profile_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_workspaces_profile_slug
    ON workspaces (profile_id, slug)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace_id
    ON workspace_members (workspace_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_members_notebook_id
    ON workspace_members (notebook_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_rules_workspace_id
    ON workspace_rules (workspace_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_index_entries_workspace_id
    ON workspace_index_entries (workspace_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_index_entries_profile_id
    ON workspace_index_entries (profile_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_index_entries_notebook_id
    ON workspace_index_entries (notebook_id)
    """,
)

_POST_MVP_RUN_INDEX_STATEMENTS = (
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_runs_profile_id
    ON workspace_runs (profile_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_runs_workspace_id
    ON workspace_runs (workspace_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_doctor_runs_profile_id
    ON doctor_runs (profile_id)
    """,
)

_INBOX_TABLES_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS inbox_clusters (
        id TEXT NOT NULL PRIMARY KEY,
        fingerprint TEXT NOT NULL,
        canonical_uri TEXT,
        representative_item_id TEXT
            REFERENCES inbox_items(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inbox_items (
        id TEXT NOT NULL PRIMARY KEY,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        notebook_id TEXT
            REFERENCES notebooks(notebook_id) ON DELETE SET NULL,
        workspace_id TEXT,
        origin TEXT NOT NULL
            CHECK (
                origin IN (
                    'fast_research',
                    'deep_research',
                    'change_radar',
                    'manual',
                    'agent_proposal'
                )
            ),
        kind TEXT NOT NULL
            CHECK (kind IN ('source', 'report', 'replacement', 'resync')),
        state TEXT NOT NULL
            CHECK (
                state IN (
                    'pending',
                    'approved',
                    'rejected',
                    'deferred',
                    'applied',
                    'expired'
                )
            ),
        priority INTEGER NOT NULL DEFAULT 0 CHECK (priority >= 0),
        novelty_score REAL NOT NULL DEFAULT 0
            CHECK (novelty_score >= 0 AND novelty_score <= 1),
        relevance_score REAL NOT NULL DEFAULT 0
            CHECK (relevance_score >= 0 AND relevance_score <= 1),
        trust_score REAL NOT NULL DEFAULT 0
            CHECK (trust_score >= 0 AND trust_score <= 1),
        approval_required INTEGER NOT NULL DEFAULT 1
            CHECK (approval_required IN (0, 1)),
        title TEXT NOT NULL,
        canonical_uri TEXT,
        snippet TEXT,
        rationale_json TEXT,
        created_at TEXT NOT NULL,
        decision_at TEXT,
        cluster_id TEXT
            REFERENCES inbox_clusters(id) ON DELETE SET NULL
    )
    """,
    *_INBOX_INDEX_STATEMENTS,
)

_RADAR_TABLES_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS watches (
        id TEXT NOT NULL PRIMARY KEY,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        scope_type TEXT NOT NULL
            CHECK (
                scope_type IN (
                    'source',
                    'notebook',
                    'workspace',
                    'research_query'
                )
            ),
        scope_id TEXT NOT NULL,
        watch_kind TEXT NOT NULL
            CHECK (
                watch_kind IN (
                    'drive_sync',
                    'web_diff',
                    'local_file_hash',
                    'deep_research'
                )
            ),
        policy_json TEXT NOT NULL,
        status TEXT NOT NULL,
        schedule_json TEXT NOT NULL,
        next_run_at TEXT,
        last_run_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS watch_runs (
        id TEXT NOT NULL PRIMARY KEY CHECK (id LIKE 'wtr_%'),
        watch_id TEXT NOT NULL
            REFERENCES watches(id) ON DELETE CASCADE,
        trace_id TEXT NOT NULL,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT NOT NULL
            CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
        signature_before TEXT,
        signature_after TEXT,
        result_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_revisions (
        id TEXT NOT NULL PRIMARY KEY,
        source_id TEXT NOT NULL
            REFERENCES sources(source_id) ON DELETE CASCADE,
        revision_key TEXT NOT NULL,
        content_hash TEXT,
        etag TEXT,
        last_modified TEXT,
        fetched_at TEXT NOT NULL,
        metadata_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS change_events (
        id TEXT NOT NULL PRIMARY KEY,
        watch_id TEXT NOT NULL
            REFERENCES watches(id) ON DELETE CASCADE,
        source_id TEXT
            REFERENCES sources(source_id) ON DELETE SET NULL,
        notebook_id TEXT
            REFERENCES notebooks(notebook_id) ON DELETE SET NULL,
        workspace_id TEXT,
        change_kind TEXT NOT NULL,
        severity TEXT NOT NULL,
        state TEXT NOT NULL
            CHECK (state IN ('new', 'briefed', 'queued_inbox', 'ignored', 'applied')),
        created_at TEXT NOT NULL,
        data_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS delta_briefings (
        id TEXT NOT NULL PRIMARY KEY,
        change_event_id TEXT NOT NULL
            REFERENCES change_events(id) ON DELETE CASCADE,
        summary_md TEXT NOT NULL,
        impact_json TEXT NOT NULL,
        recommended_actions_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    *_RADAR_INDEX_STATEMENTS,
)

_LEASE_TABLES_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS leases (
        id TEXT NOT NULL PRIMARY KEY CHECK (id LIKE 'lease_%'),
        scope_type TEXT NOT NULL
            CHECK (
                scope_type IN (
                    'profile',
                    'notebook',
                    'workspace',
                    'watch',
                    'inbox_item'
                )
            ),
        scope_id TEXT NOT NULL,
        holder TEXT NOT NULL,
        purpose TEXT NOT NULL,
        advisory INTEGER NOT NULL DEFAULT 1
            CHECK (advisory IN (0, 1)),
        acquired_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        UNIQUE (scope_type, scope_id, holder)
    )
    """,
    *_LEASE_INDEX_STATEMENTS,
)

_WORKSPACE_TABLES_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id TEXT NOT NULL PRIMARY KEY CHECK (id LIKE 'ws_%'),
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        slug TEXT NOT NULL,
        description TEXT,
        kind TEXT NOT NULL
            CHECK (kind IN ('static', 'rule_based')),
        query_policy_json TEXT,
        approval_policy_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_members (
        id TEXT NOT NULL PRIMARY KEY CHECK (id LIKE 'wsm_%'),
        workspace_id TEXT NOT NULL
            REFERENCES workspaces(id) ON DELETE CASCADE,
        notebook_id TEXT NOT NULL
            REFERENCES notebooks(notebook_id) ON DELETE CASCADE,
        priority INTEGER NOT NULL DEFAULT 0,
        tags_json TEXT,
        enabled INTEGER NOT NULL DEFAULT 1
            CHECK (enabled IN (0, 1)),
        added_at TEXT NOT NULL,
        UNIQUE (workspace_id, notebook_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_rules (
        id TEXT NOT NULL PRIMARY KEY CHECK (id LIKE 'wsr_%'),
        workspace_id TEXT NOT NULL
            REFERENCES workspaces(id) ON DELETE CASCADE,
        rule_type TEXT NOT NULL,
        rule_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_index_entries (
        id TEXT NOT NULL PRIMARY KEY CHECK (id LIKE 'wsi_%'),
        workspace_id TEXT NOT NULL
            REFERENCES workspaces(id) ON DELETE CASCADE,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        notebook_id TEXT NOT NULL
            REFERENCES notebooks(notebook_id) ON DELETE CASCADE,
        notebook_title TEXT,
        notebook_summary TEXT,
        title_aliases_text TEXT,
        source_titles_text TEXT,
        source_snippets_text TEXT,
        tags_json TEXT,
        recent_query_text TEXT,
        content_text TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (workspace_id, notebook_id)
    )
    """,
    *_WORKSPACE_INDEX_STATEMENTS,
)

_WORKSPACE_FTS_STATEMENTS = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS workspace_index_fts USING fts5(
        entry_id UNINDEXED,
        workspace_id UNINDEXED,
        profile_id UNINDEXED,
        notebook_id UNINDEXED,
        notebook_title,
        notebook_summary,
        title_aliases_text,
        source_titles_text,
        source_snippets_text,
        tags_text,
        recent_query_text,
        content_text
    )
    """,
)

_POST_MVP_RUN_TABLES_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS workspace_runs (
        id TEXT NOT NULL PRIMARY KEY CHECK (id LIKE 'wr_%'),
        trace_id TEXT NOT NULL,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT NOT NULL
            CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
        workspace_id TEXT NOT NULL,
        mode TEXT NOT NULL
            CHECK (mode IN ('metadata', 'ask', 'overview', 'compare')),
        query_text TEXT,
        selected_notebooks_json TEXT,
        plan_json TEXT,
        result_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS doctor_runs (
        id TEXT NOT NULL PRIMARY KEY CHECK (id LIKE 'dr_%'),
        trace_id TEXT NOT NULL,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT NOT NULL
            CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
        mode TEXT NOT NULL
            CHECK (mode IN ('fast', 'deep')),
        overall_status TEXT
            CHECK (
                overall_status IS NULL
                OR overall_status IN ('healthy', 'degraded', 'broken')
            ),
        summary_json TEXT
    )
    """,
    *_POST_MVP_RUN_INDEX_STATEMENTS,
)

_SCHEMA_V1_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS profiles (
        profile_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        account_email TEXT,
        is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
        storage_state_path TEXT NOT NULL,
        browser_profile_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        approval_policy_json TEXT,
        last_login_at TEXT
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_default
    ON profiles (is_default) WHERE is_default = 1
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_snapshots (
        profile_id TEXT PRIMARY KEY
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        cookie_fingerprint TEXT NOT NULL,
        csrf_token TEXT NOT NULL,
        session_id TEXT NOT NULL,
        build_label TEXT NOT NULL,
        captured_at TEXT NOT NULL,
        validated_at TEXT,
        status TEXT NOT NULL,
        source TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_state (
        singleton_key INTEGER PRIMARY KEY CHECK (singleton_key = 1),
        active_profile_id TEXT
            REFERENCES profiles(profile_id) ON DELETE SET NULL,
        current_notebook_id TEXT,
        current_conversation_id TEXT,
        schema_version INTEGER NOT NULL
    )
    """,
    f"""
    INSERT INTO app_state (
        singleton_key,
        schema_version
    ) VALUES (
        {APP_STATE_SINGLETON_KEY},
        {INITIAL_SCHEMA_VERSION}
    ) ON CONFLICT(singleton_key) DO NOTHING
    """,
    """
    CREATE TABLE IF NOT EXISTS notebooks (
        notebook_id TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        is_owner INTEGER NOT NULL DEFAULT 0 CHECK (is_owner IN (0, 1)),
        share_visibility TEXT,
        created_at_remote TEXT,
        source_count INTEGER NOT NULL DEFAULT 0,
        artifact_count INTEGER NOT NULL DEFAULT 0,
        note_count INTEGER NOT NULL DEFAULT 0,
        summary_preview TEXT,
        index_synced_at TEXT,
        detail_synced_at TEXT,
        remote_fingerprint TEXT,
        approval_policy_json TEXT,
        tombstoned_at TEXT,
        raw_json TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notebooks_profile_id
    ON notebooks (profile_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notebooks_profile_normalized_title
    ON notebooks (profile_id, normalized_title)
    """,
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id TEXT PRIMARY KEY,
        notebook_id TEXT NOT NULL
            REFERENCES notebooks(notebook_id) ON DELETE CASCADE,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        source_type TEXT NOT NULL,
        title TEXT,
        origin_uri TEXT,
        status TEXT NOT NULL,
        freshness_state TEXT,
        drive_syncable INTEGER CHECK (drive_syncable IN (0, 1)),
        content_preview TEXT,
        added_at_remote TEXT,
        updated_at_remote TEXT,
        synced_at TEXT,
        remote_fingerprint TEXT,
        tombstoned_at TEXT,
        raw_json TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sources_notebook_id
    ON sources (notebook_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sources_profile_id
    ON sources (profile_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        artifact_id TEXT PRIMARY KEY,
        notebook_id TEXT NOT NULL
            REFERENCES notebooks(notebook_id) ON DELETE CASCADE,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        artifact_type TEXT NOT NULL,
        submode TEXT,
        title TEXT,
        prompt_hash TEXT,
        status TEXT NOT NULL,
        requested_at TEXT NOT NULL,
        last_polled_at TEXT,
        completed_at TEXT,
        download_ref TEXT,
        remote_fingerprint TEXT,
        raw_json TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_artifacts_notebook_id
    ON artifacts (notebook_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_artifacts_profile_id
    ON artifacts (profile_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS research_runs (
        research_id TEXT PRIMARY KEY,
        notebook_id TEXT NOT NULL
            REFERENCES notebooks(notebook_id) ON DELETE CASCADE,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        mode TEXT NOT NULL,
        query_text TEXT NOT NULL,
        status TEXT NOT NULL,
        discovered_count INTEGER NOT NULL DEFAULT 0,
        imported_count INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        raw_json TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_research_runs_notebook_id
    ON research_runs (notebook_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_research_runs_profile_id
    ON research_runs (profile_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS query_runs (
        id TEXT PRIMARY KEY CHECK (id LIKE 'qr_%'),
        trace_id TEXT NOT NULL,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        notebook_id TEXT
            REFERENCES notebooks(notebook_id) ON DELETE SET NULL,
        intent TEXT NOT NULL,
        mode TEXT NOT NULL,
        prompt_text TEXT NOT NULL,
        prompt_hash TEXT NOT NULL,
        settings_hash TEXT,
        notebook_fingerprint TEXT,
        cache_policy TEXT NOT NULL,
        route_reason TEXT NOT NULL,
        source_of_truth TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT NOT NULL
            CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
        reused_from TEXT
            REFERENCES query_runs(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_query_runs_profile_id
    ON query_runs (profile_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_query_runs_notebook_id
    ON query_runs (notebook_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_query_runs_prompt_hash
    ON query_runs (prompt_hash)
    """,
    """
        CREATE TABLE IF NOT EXISTS query_results (
            query_run_id TEXT PRIMARY KEY
                REFERENCES query_runs(id) ON DELETE CASCADE,
            result_type TEXT NOT NULL,
            answer_text TEXT,
            citations_json TEXT,
            artifact_id TEXT
                REFERENCES artifacts(artifact_id) ON DELETE SET NULL,
        result_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_runs (
        id TEXT PRIMARY KEY CHECK (id LIKE 'sr_%'),
        trace_id TEXT NOT NULL,
        profile_id TEXT NOT NULL
            REFERENCES profiles(profile_id) ON DELETE CASCADE,
        scope TEXT NOT NULL,
        target_id TEXT,
        trigger TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT NOT NULL
            CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
        stats_json TEXT,
        error_text TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sync_runs_profile_id
    ON sync_runs (profile_id)
    """,
    *_MVP_INDEX_STATEMENTS,
    """
    CREATE TABLE IF NOT EXISTS run_events (
        event_id TEXT PRIMARY KEY CHECK (event_id LIKE 'evt_%'),
        trace_id TEXT NOT NULL,
        run_id TEXT,
        kind TEXT NOT NULL,
        ts TEXT NOT NULL,
        payload_json TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_run_events_trace_id
    ON run_events (trace_id)
    """,
    _APPROVAL_REQUESTS_STATEMENT,
    *_HISTORY_TABLES_STATEMENTS,
    *_INBOX_TABLES_STATEMENTS,
    *_RADAR_TABLES_STATEMENTS,
    *_LEASE_TABLES_STATEMENTS,
    *_WORKSPACE_TABLES_STATEMENTS,
    *_WORKSPACE_FTS_STATEMENTS,
    *_POST_MVP_RUN_TABLES_STATEMENTS,
)


def schema_v1_statements() -> tuple[str, ...]:
    """Return the idempotent SQL statements that define schema version 1."""
    return _SCHEMA_V1_STATEMENTS


def apply_schema_v1(connection: sqlite3.Connection) -> None:
    """Apply the v1 schema payload to an open SQLite connection."""
    for statement in schema_v1_statements():
        connection.execute(statement)


def apply_schema_v2(connection: sqlite3.Connection) -> None:
    """Backfill post-v1 approval tables and mark the schema version as 2."""
    connection.execute(_APPROVAL_REQUESTS_STATEMENT)
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (2, APP_STATE_SINGLETON_KEY),
    )


def apply_schema_v3(connection: sqlite3.Connection) -> None:
    """Backfill the composite MVP indexes and mark the schema current."""
    for statement in _MVP_INDEX_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (3, APP_STATE_SINGLETON_KEY),
    )


def apply_schema_v4(connection: sqlite3.Connection) -> None:
    """Backfill the post-MVP inbox tables and mark the schema version as 4."""
    for statement in _INBOX_TABLES_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (4, APP_STATE_SINGLETON_KEY),
    )


def apply_schema_v5(connection: sqlite3.Connection) -> None:
    """Backfill the post-MVP change-radar tables and mark schema version 5."""
    for statement in _RADAR_TABLES_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (5, APP_STATE_SINGLETON_KEY),
    )


def apply_schema_v6(connection: sqlite3.Connection) -> None:
    """Backfill the shared lease table and mark the schema current."""
    for statement in _LEASE_TABLES_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (6, APP_STATE_SINGLETON_KEY),
    )


def apply_schema_v7(connection: sqlite3.Connection) -> None:
    """Backfill the post-MVP run tables and mark schema version 7."""
    for statement in _POST_MVP_RUN_TABLES_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (7, APP_STATE_SINGLETON_KEY),
    )


def apply_schema_v8(connection: sqlite3.Connection) -> None:
    """Backfill the history FTS table and mark the schema current."""
    for statement in _HISTORY_TABLES_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (8, APP_STATE_SINGLETON_KEY),
    )


def apply_schema_v9(connection: sqlite3.Connection) -> None:
    """Backfill the workspace metadata tables and mark the schema current."""
    for statement in _WORKSPACE_TABLES_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (9, APP_STATE_SINGLETON_KEY),
    )


def apply_schema_v10(connection: sqlite3.Connection) -> None:
    """Backfill the workspace FTS table and mark the schema current."""
    for statement in _WORKSPACE_FTS_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (10, APP_STATE_SINGLETON_KEY),
    )


def _table_has_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def _add_column_if_missing(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    definition_sql: str,
) -> None:
    if _table_has_column(connection, table_name, column_name):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition_sql}")


def apply_schema_v11(connection: sqlite3.Connection) -> None:
    """Backfill approval policy columns for profiles and notebooks."""
    _add_column_if_missing(
        connection,
        table_name="profiles",
        column_name="approval_policy_json",
        definition_sql="approval_policy_json TEXT",
    )
    _add_column_if_missing(
        connection,
        table_name="notebooks",
        column_name="approval_policy_json",
        definition_sql="approval_policy_json TEXT",
    )
    connection.execute(
        """
        UPDATE app_state
        SET schema_version = ?
        WHERE singleton_key = ?
        """,
        (LATEST_SCHEMA_VERSION, APP_STATE_SINGLETON_KEY),
    )


__all__ = [
    "APP_STATE_SINGLETON_KEY",
    "HISTORY_TABLES",
    "INDEX_NAMES",
    "INBOX_TABLES",
    "INITIAL_SCHEMA_VERSION",
    "LEASE_TABLES",
    "LATEST_SCHEMA_VERSION",
    "MVP_TABLES",
    "POST_MVP_RUN_TABLES",
    "RADAR_TABLES",
    "WORKSPACE_TABLES",
    "apply_schema_v1",
    "apply_schema_v2",
    "apply_schema_v3",
    "apply_schema_v4",
    "apply_schema_v5",
    "apply_schema_v6",
    "apply_schema_v7",
    "apply_schema_v8",
    "apply_schema_v9",
    "apply_schema_v10",
    "apply_schema_v11",
    "schema_v1_statements",
]
