"""Unit tests for BA source registration and manifest normalization."""

from __future__ import annotations

from pathlib import Path

from notebooklm_mcp.ba.models import (
    SourceContentKind,
    SourcePriority,
    SourceType,
    WorkflowMode,
)
from notebooklm_mcp.ba.run_store import BARunStore, SourceRegistrationInput


def test_register_sources_generates_stable_keys_and_persists_result(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-003",
    )
    store.create(mode_requested=WorkflowMode.FE_FIRST)

    inputs = [
        SourceRegistrationInput(
            path_or_url_or_text="https://example.com/spec/customer-create",
            source_type=SourceType.PRIMARY_REQUIREMENT,
            priority=SourcePriority.REQUIRED,
        ),
        SourceRegistrationInput(
            path_or_url_or_text="Decision note about mock API behavior",
            source_type=SourceType.SUPPORTING_DECISION,
            priority=SourcePriority.HIGH,
        ),
    ]

    first = store.register_sources(inputs)
    second = store.register_sources(inputs)

    assert [item.source_key for item in first.registered_sources] == [
        item.source_key for item in second.registered_sources
    ]
    assert first.manifest.rows[0].source_type is SourceType.PRIMARY_REQUIREMENT
    assert first.manifest.rows[0].content_kind is SourceContentKind.URL
    assert first.manifest.rows[1].content_kind is SourceContentKind.INLINE_TEXT
    assert store.run_paths.source_registration_json.exists()


def test_register_sources_preserves_explicit_keys_and_warns_on_duplicates(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-004",
    )
    store.create(mode_requested=WorkflowMode.BALANCED)

    result = store.register_sources(
        [
            SourceRegistrationInput(
                path_or_url_or_text="/tmp/ba.pdf",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                source_key="BA-PDF",
            ),
            SourceRegistrationInput(
                path_or_url_or_text="/tmp/rules.pdf",
                source_type=SourceType.SUPPORTING_RULE,
                source_key="ba-pdf",
            ),
        ]
    )

    assert result.registered_sources[0].source_key == "ba-pdf"
    assert result.manifest.rows[0].content_kind is SourceContentKind.FILE_PATH
    assert result.manifest.rows[0].source_ref == "/tmp/ba.pdf"
    assert result.manifest.rows[0].title == "ba.pdf"
    assert any("duplicate source_key" in warning for warning in result.warnings)


def test_register_sources_warns_when_primary_requirement_is_missing(tmp_path: Path) -> None:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-005",
    )
    store.create()

    result = store.register_sources(
        [
            SourceRegistrationInput(
                path_or_url_or_text="Glossary entry list",
                source_type=SourceType.SUPPORTING_GLOSSARY,
            )
        ]
    )

    assert result.missing_critical_sources == [SourceType.PRIMARY_REQUIREMENT]
    assert any("PRIMARY_REQUIREMENT" in warning for warning in result.warnings)
