"""Unit tests for BA source registration and manifest normalization."""

from __future__ import annotations

from pathlib import Path

from notebooklm_mcp.ba.adapter import BACapabilityAdapter
from notebooklm_mcp.ba.models import (
    SourceContentKind,
    SourceManifestDocument,
    SourceRegistrationWarningCode,
    SourceType,
)
from notebooklm_mcp.ba.run_store import BARunStore


def test_register_sources_normalizes_manifest_rows_and_persists_manifest(tmp_path: Path) -> None:
    requirements_pdf = tmp_path / "requirements" / "ba.pdf"
    requirements_pdf.parent.mkdir(parents=True, exist_ok=True)
    requirements_pdf.write_text("placeholder", encoding="utf-8")

    adapter = BACapabilityAdapter(client=object())
    result = adapter.register_sources(
        feature_key="customer-create",
        run_id="run-1",
        workspace_root=tmp_path,
        source_entries=[
            {
                "path_or_url_or_text": "requirements/ba.pdf",
                "source_key": "ba-pdf",
                "source_type": "PRIMARY_REQUIREMENT",
                "priority": "REQUIRED",
            },
            {
                "path_or_url_or_text": "https://example.com/glossary",
                "source_key": "glossary",
                "source_type": "SUPPORTING_GLOSSARY",
                "priority": "NORMAL",
                "notes": ["legacy terms"],
            },
            {
                "path_or_url_or_text": "Clarification note body",
                "source_key": "clarification-note",
                "source_type": "SUPPORTING_CLARIFICATION",
                "priority": "HIGH",
            },
        ],
    )

    assert [row.source_key for row in result.manifest.rows] == [
        "ba-pdf",
        "glossary",
        "clarification-note",
    ]
    assert result.manifest.rows[0].content_kind is SourceContentKind.FILE_PATH
    assert result.manifest.rows[0].source_ref == "requirements/ba.pdf"
    assert result.manifest.rows[1].content_kind is SourceContentKind.URL
    assert result.manifest.rows[2].content_kind is SourceContentKind.INLINE_TEXT
    assert result.warnings == []

    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-1",
    )
    store.create()
    store.write_model_json(store.feature_paths.source_manifest_json, result.manifest)
    loaded = store.read_model_json(store.feature_paths.source_manifest_json, SourceManifestDocument)

    assert loaded.rows[0].source_key == "ba-pdf"
    assert loaded.rows[2].title == "Clarification Note"


def test_register_sources_warns_on_invalid_entries_duplicates_and_missing_primary(tmp_path: Path) -> None:
    adapter = BACapabilityAdapter(client=object())
    result = adapter.register_sources(
        feature_key="customer-create",
        run_id="run-2",
        workspace_root=tmp_path,
        source_entries=[
            {
                "path_or_url_or_text": "https://example.com/guide",
                "source_key": "dup",
                "source_type": "SUPPORTING_GLOSSARY",
                "priority": "NORMAL",
            },
            {
                "path_or_url_or_text": "Second value",
                "source_key": "dup",
                "source_type": "SUPPORTING_DECISION",
                "priority": "LOW",
            },
            {
                "path_or_url_or_text": "missing/file.pdf",
                "source_key": "missing-file",
                "source_type": "PRIMARY_CONTRACT",
                "priority": "HIGH",
                "content_kind": "FILE_PATH",
            },
            {
                "source_key": "malformed",
                "source_type": "PRIMARY_REQUIREMENT",
                "priority": "REQUIRED",
            },
        ],
    )

    assert [row.source_key for row in result.manifest.rows] == ["dup"]
    assert result.missing_critical_source_types == [SourceType.PRIMARY_REQUIREMENT]
    assert [warning.code for warning in result.warnings] == [
        SourceRegistrationWarningCode.DUPLICATE_SOURCE_KEY,
        SourceRegistrationWarningCode.INVALID_SOURCE_ENTRY,
        SourceRegistrationWarningCode.INVALID_SOURCE_ENTRY,
        SourceRegistrationWarningCode.MISSING_CRITICAL_SOURCE_TYPE,
    ]
    assert result.manifest.warnings[-1].startswith("At least one PRIMARY_REQUIREMENT")
