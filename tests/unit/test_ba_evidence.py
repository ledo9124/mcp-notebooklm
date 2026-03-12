"""Unit tests for BA evidence normalization and snapshot linkage."""

from __future__ import annotations

from types import SimpleNamespace

from notebooklm_mcp.ba.extraction import normalize_citations_to_evidence
from notebooklm_mcp.ba.models import (
    SourceContentKind,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceSnapshotRecord,
    SourceType,
)


def _manifest(*, snapshot_id: str | None = "requirements-abc123") -> SourceManifestDocument:
    return SourceManifestDocument(
        feature_key="customer-create",
        run_id="run-010",
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref="requirements/ba.pdf",
                notebook_source_id="src-1",
                snapshot_id=snapshot_id,
                title="Requirements PDF",
            )
        ],
    )


def test_normalize_citations_to_evidence_uses_manifest_links_for_adapter_citations() -> None:
    result = normalize_citations_to_evidence(
        [
            SimpleNamespace(
                source_id="src-1",
                quote="gateway handles auth",
                location="10-20",
                title="Requirements PDF",
            )
        ],
        manifest=_manifest(),
    )

    assert result.warnings == ()
    assert result.evidence[0].source_key == "requirements"
    assert result.evidence[0].snapshot_id == "requirements-abc123"
    assert result.evidence[0].locator == "10-20"
    assert result.evidence[0].quote == "gateway handles auth"


def test_normalize_citations_to_evidence_falls_back_to_snapshot_records_and_raw_shapes() -> None:
    result = normalize_citations_to_evidence(
        [
            {
                "source_id": "src-1",
                "cited_text": "customer id is required",
                "start_char": 12,
                "end_char": 28,
            }
        ],
        manifest=_manifest(snapshot_id=None),
        snapshots=[
            SourceSnapshotRecord(
                source_key="requirements",
                snapshot_id="requirements-def456",
                content_hash="hash-1",
                notebook_source_id="src-1",
                title="Requirements PDF",
                source_type="pdf",
                char_count=2048,
            )
        ],
    )

    assert result.warnings == ()
    assert result.evidence[0].snapshot_id == "requirements-def456"
    assert result.evidence[0].locator == "12-28"
    assert result.evidence[0].quote == "customer id is required"


def test_normalize_citations_to_evidence_deduplicates_identical_entries() -> None:
    citation = SimpleNamespace(source_id="src-1", quote="gateway handles auth", location="10-20")

    result = normalize_citations_to_evidence([citation, citation], manifest=_manifest())

    assert len(result.evidence) == 1
    assert result.warnings == ()


def test_normalize_citations_to_evidence_emits_warnings_for_missing_links_or_locator_data() -> None:
    result = normalize_citations_to_evidence(
        [
            {"source_id": "missing-source", "cited_text": "unmapped"},
            {"source_id": "src-1"},
        ],
        manifest=_manifest(),
    )

    assert result.evidence == ()
    assert result.warnings == (
        "citation[1] source 'missing-source' is not present in manifest",
        "citation[2] source 'src-1' is missing quote and locator",
    )
