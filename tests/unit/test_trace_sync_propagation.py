"""Regression tests for trace propagation into sync runs."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm.local.db import configure_connection
from notebooklm.local.migrations import run_default_migrations
from notebooklm.observability.tracing import bind_trace
from notebooklm.profiles.manager import ProfileManager
from notebooklm.sync import sync_notebook_index
from notebooklm.types import Notebook


def _connect() -> sqlite3.Connection:
    connection = configure_connection(sqlite3.connect(":memory:"))
    run_default_migrations(connection)
    manager = ProfileManager(connection)
    manager.create_profile(
        profile_id="default",
        display_name="Default",
        storage_state_path="/tmp/storage.json",
        browser_profile_path="/tmp/browser-profile",
        is_default=True,
    )
    manager.switch_profile("default")
    return connection


def _client_with_notebooks(notebooks: list[Notebook]) -> MagicMock:
    client = MagicMock()
    client.notebooks = MagicMock()
    client.notebooks.list = AsyncMock(return_value=notebooks)
    return client


@pytest.mark.asyncio
async def test_sync_notebook_index_uses_bound_trace_id_for_sync_run():
    """A bound trace should flow into the sync_runs row created by notebook sync."""
    connection = _connect()
    client = _client_with_notebooks(
        [
            Notebook(
                id="nb_trace",
                title="Trace Notebook",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                sources_count=1,
                is_owner=True,
            )
        ]
    )

    with bind_trace(trace_id="trc_sync_bound", run_id="run_cli_root"):
        state = await sync_notebook_index(
            client,
            connection,
            profile_id="default",
            now=datetime(2026, 3, 15, 3, 0, tzinfo=timezone.utc),
        )

    row = connection.execute(
        "SELECT trace_id FROM sync_runs WHERE id = ?",
        (state.sync_run_id,),
    ).fetchone()

    assert row is not None
    assert row["trace_id"] == "trc_sync_bound"
