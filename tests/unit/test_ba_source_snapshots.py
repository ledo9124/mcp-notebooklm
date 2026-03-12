"""Unit tests for BA source snapshot collection and persistence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from notebooklm.rpc.types import SourceStatus
from notebooklm.types import Source, SourceFulltext
from notebooklm_mcp.ba.adapter import BACapabilityAdapter
from notebooklm_mcp.ba.models import (
    SourceContentKind,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceSnapshotRecord,
    SourceType,
)
from notebooklm_mcp.ba.run_store import BARunStore


def _fake_client() -> SimpleNamespace:
    return SimpleNamespace(
        sources=SimpleNamespace(),
        notes=SimpleNamespace(),
        chat=SimpleNamespace(),
        research=SimpleNamespace(),
        settings=SimpleNamespace(),
        artifacts=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_collect_and_persist_source_snapshot_artifacts(tmp_path: Path) -> None:
    client = _fake_client()
    client.sources.get = AsyncMock(
        return_value=Source(
            id="src-1",
            title="Requirements PDF",
            url="https://example.com/spec.pdf",
            _type_code=3,
            status=SourceStatus.READY,
        )
    )
    client.sources.get_fulltext = AsyncMock(
        return_value=SourceFulltext(
            source_id="src-1",
            title="Requirements PDF",
            content="full source text",
            _type_code=3,
            url="https://example.com/spec.pdf",
            char_count=16,
        )
    )
    client.sources.get_guide = AsyncMock(
        return_value={"summary": "Guide summary", "keywords": ["scope", "timeline"]}
    )
    client.sources.check_freshness = AsyncMock(return_value=True)

    adapter = BACapabilityAdapter(client)
    snapshot = await adapter.collect_source_snapshot("nb-1", "src-1")

    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-006",
    )
    store.create()
    record = store.persist_source_snapshot(
        source_key="requirements",
        notebook_source_id=snapshot.source_id,
        title=snapshot.title,
        source_type=snapshot.source_type,
        content=snapshot.content,
        char_count=snapshot.char_count,
        guide_summary=snapshot.guide_summary,
        guide_keywords=snapshot.guide_keywords,
        is_fresh=snapshot.is_fresh,
    )
    loaded = store.load_source_snapshot("requirements", record.snapshot_id)

    assert loaded == record
    assert loaded.content_hash == hashlib.sha256(b"full source text").hexdigest()
    assert loaded.freshness == "fresh"
    assert loaded.fulltext_path is not None
    assert (tmp_path / loaded.fulltext_path).read_text(encoding="utf-8") == "full source text"
    assert loaded.guide_path is not None
    assert json.loads((tmp_path / loaded.guide_path).read_text(encoding="utf-8")) == {
        "summary": "Guide summary",
        "keywords": ["scope", "timeline"],
    }


def test_attach_snapshot_records_updates_manifest_rows() -> None:
    store = BARunStore(
        workspace_root=Path("."),
        feature_key="customer-create",
        run_id="run-007",
    )
    manifest = SourceManifestDocument(
        run_id="run-007",
        feature_key="customer-create",
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.URL,
                source_ref="https://example.com/spec",
                title="Requirements URL",
            ),
            SourceManifestRow(
                source_key="glossary",
                source_type=SourceType.SUPPORTING_GLOSSARY,
                priority=SourcePriority.NORMAL,
                content_kind=SourceContentKind.INLINE_TEXT,
                source_ref="Glossary terms",
                title="Glossary Terms",
            ),
        ],
    )

    updated = store.attach_snapshot_records(
        manifest,
        [
            SourceSnapshotRecord(
                source_key="requirements",
                snapshot_id="requirements-abc123",
                content_hash="abc123",
                fulltext_path="docs/features/customer-create/runs/run-007/snapshots/requirements/requirements-abc123/fulltext.txt",
                freshness="stale",
                notebook_source_id="src-1",
                title="Requirements URL",
                source_type="web_page",
                char_count=128,
            )
        ],
    )

    assert updated.rows[0].snapshot_id == "requirements-abc123"
    assert updated.rows[0].freshness == "stale"
    assert updated.rows[1].snapshot_id is None
