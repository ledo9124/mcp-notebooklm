"""Helpers for notebook-detail sync writeback."""

from __future__ import annotations

from dataclasses import replace
import sqlite3
from typing import Any

from .fingerprints import compute_notebook_fingerprint
from .repositories import ArtifactRepository, NotebookRecord, NotebookRepository, SourceRepository


def sync_notebook_detail_fingerprint(
    connection: sqlite3.Connection,
    notebook_id: str,
    *,
    settings: Any | None = None,
) -> NotebookRecord:
    """Recompute and persist a notebook fingerprint after detail-state writeback."""
    notebook_repository = NotebookRepository(connection)
    notebook = notebook_repository.get(notebook_id)
    if notebook is None:
        raise LookupError(f"unknown notebook: {notebook_id}")

    fingerprint = compute_notebook_fingerprint(
        notebook,
        sources=SourceRepository(connection).list_for_notebook(notebook_id),
        artifacts=ArtifactRepository(connection).list_for_notebook(notebook_id),
        settings=settings,
    )
    updated_notebook = replace(notebook, remote_fingerprint=fingerprint)
    notebook_repository.upsert(updated_notebook)
    return updated_notebook


__all__ = ["sync_notebook_detail_fingerprint"]
