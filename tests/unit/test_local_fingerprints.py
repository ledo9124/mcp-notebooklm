"""Unit tests for notebook fingerprint helpers."""

from __future__ import annotations

from notebooklm.local.fingerprints import (
    build_notebook_fingerprint_payload,
    compute_notebook_fingerprint,
)
from notebooklm.local.repositories import ArtifactRecord, NotebookRecord, SourceRecord
from notebooklm.rpc import ChatGoal, ChatResponseLength
from notebooklm.types import ChatSettings


def _notebook(summary_preview: str | None = "Short summary") -> NotebookRecord:
    return NotebookRecord(
        notebook_id="nb_1",
        profile_id="profile_a",
        title="Research Notebook",
        normalized_title="research-notebook",
        summary_preview=summary_preview,
    )


def _source(
    source_id: str,
    *,
    status: str = "ready",
    remote_fingerprint: str | None = None,
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        notebook_id="nb_1",
        profile_id="profile_a",
        source_type="url",
        status=status,
        remote_fingerprint=remote_fingerprint,
    )


def _artifact(artifact_id: str, *, status: str = "completed") -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        notebook_id="nb_1",
        profile_id="profile_a",
        artifact_type="report",
        status=status,
        requested_at="2026-03-15T00:00:00Z",
    )


def test_build_notebook_fingerprint_payload_canonicalizes_sources_artifacts_and_settings():
    payload = build_notebook_fingerprint_payload(
        _notebook(),
        sources=[
            _source("src_b", status="processing", remote_fingerprint="fp-b"),
            _source("src_a", status="ready"),
        ],
        artifacts=[
            _artifact("art_b", status="pending"),
            _artifact("art_a"),
        ],
        settings=ChatSettings(
            goal=ChatGoal.CUSTOM,
            response_length=ChatResponseLength.LONGER,
            custom_prompt="Focus on contradictions",
            source="default",
        ),
    )

    assert payload == {
        "title": "Research Notebook",
        "summary_preview": "Short summary",
        "sources": [
            {"source_id": "src_a", "status": "ready", "remote_fingerprint": None},
            {"source_id": "src_b", "status": "processing", "remote_fingerprint": "fp-b"},
        ],
        "artifacts": [
            {"artifact_id": "art_a", "status": "completed"},
            {"artifact_id": "art_b", "status": "pending"},
        ],
        "settings": {
            "goal": "custom",
            "response_length": "longer",
            "custom_prompt": "Focus on contradictions",
        },
    }


def test_compute_notebook_fingerprint_is_order_independent_and_normalizes_missing_optionals():
    notebook = _notebook(summary_preview=None)
    sources_a = [
        _source("src_b", status="processing", remote_fingerprint="fp-b"),
        _source("src_a", remote_fingerprint=None),
    ]
    sources_b = list(reversed(sources_a))
    artifacts_a = [_artifact("art_b", status="pending"), _artifact("art_a")]
    artifacts_b = list(reversed(artifacts_a))
    settings_a = {
        "goal": "default",
        "advanced": {"response_length": "shorter", "custom_prompt": None},
        "custom_prompt": None,
    }
    settings_b = {
        "advanced": {"response_length": "shorter"},
        "goal": "default",
    }

    fingerprint_a = compute_notebook_fingerprint(
        notebook,
        sources=sources_a,
        artifacts=artifacts_a,
        settings=settings_a,
    )
    fingerprint_b = compute_notebook_fingerprint(
        notebook,
        sources=sources_b,
        artifacts=artifacts_b,
        settings=settings_b,
    )

    assert fingerprint_a == fingerprint_b
    assert len(fingerprint_a) == 64


def test_compute_notebook_fingerprint_changes_when_source_inventory_changes():
    notebook = _notebook()
    baseline = compute_notebook_fingerprint(
        notebook,
        sources=[_source("src_a", remote_fingerprint="fp-a")],
    )
    changed = compute_notebook_fingerprint(
        notebook,
        sources=[
            _source("src_a", remote_fingerprint="fp-a"),
            _source("src_b", remote_fingerprint="fp-b"),
        ],
    )

    assert baseline != changed


def test_compute_notebook_fingerprint_changes_when_artifact_status_changes():
    notebook = _notebook()
    pending = compute_notebook_fingerprint(
        notebook,
        artifacts=[_artifact("art_1", status="pending")],
    )
    completed = compute_notebook_fingerprint(
        notebook,
        artifacts=[_artifact("art_1", status="completed")],
    )

    assert pending != completed


def test_compute_notebook_fingerprint_changes_when_settings_change():
    notebook = _notebook()
    shorter = compute_notebook_fingerprint(
        notebook,
        settings=ChatSettings(
            goal=ChatGoal.DEFAULT,
            response_length=ChatResponseLength.SHORTER,
            source="server",
        ),
    )
    longer = compute_notebook_fingerprint(
        notebook,
        settings=ChatSettings(
            goal=ChatGoal.DEFAULT,
            response_length=ChatResponseLength.LONGER,
            source="unknown",
        ),
    )

    assert shorter != longer
