"""Helpers for computing deterministic notebook fingerprints."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import json
from typing import Any

from notebooklm.types import ChatSettings

from .repositories import ArtifactRecord, NotebookRecord, SourceRecord


JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _normalize_settings(settings: Any | None) -> dict[str, JsonValue]:
    """Normalize settings into a canonical JSON mapping."""
    if settings is None:
        return {}

    if isinstance(settings, ChatSettings):
        normalized: dict[str, JsonValue] = {
            "goal": settings.goal.name.lower(),
            "response_length": settings.response_length.name.lower(),
        }
        if settings.custom_prompt is not None:
            normalized["custom_prompt"] = settings.custom_prompt
        return normalized

    normalized = _normalize_json_value(settings)
    if normalized is None:
        return {}
    if not isinstance(normalized, dict):
        raise TypeError("settings must normalize to a mapping")
    return normalized


def _normalize_json_value(value: Any) -> JsonValue:
    """Normalize arbitrary JSON-like values into a deterministic shape."""
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, Enum):
        return value.value if isinstance(value.value, str | int | float | bool) else value.name

    if isinstance(value, ChatSettings):
        return _normalize_settings(value)

    if is_dataclass(value):
        return _normalize_json_value(asdict(value))

    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key in sorted(value.keys(), key=str):
            item = _normalize_json_value(value[key])
            if item is not None:
                normalized[str(key)] = item
        return normalized

    if isinstance(value, list | tuple):
        return [_normalize_json_value(item) for item in value]

    if isinstance(value, set | frozenset):
        normalized_items = [_normalize_json_value(item) for item in value]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        )

    raise TypeError(f"unsupported value for notebook fingerprint canonicalization: {type(value)!r}")


def build_notebook_fingerprint_payload(
    notebook: NotebookRecord,
    *,
    sources: Iterable[SourceRecord] = (),
    artifacts: Iterable[ArtifactRecord] = (),
    settings: Any | None = None,
) -> dict[str, JsonValue]:
    """Build the canonical notebook-state payload used for fingerprinting."""
    source_payload = [
        {
            "source_id": source.source_id,
            "status": source.status,
            "remote_fingerprint": source.remote_fingerprint,
        }
        for source in sorted(sources, key=lambda item: item.source_id)
    ]
    artifact_payload = [
        {
            "artifact_id": artifact.artifact_id,
            "status": artifact.status,
        }
        for artifact in sorted(artifacts, key=lambda item: item.artifact_id)
    ]
    return {
        "title": notebook.title,
        "summary_preview": notebook.summary_preview,
        "sources": source_payload,
        "artifacts": artifact_payload,
        "settings": _normalize_settings(settings),
    }


def compute_notebook_fingerprint(
    notebook: NotebookRecord,
    *,
    sources: Iterable[SourceRecord] = (),
    artifacts: Iterable[ArtifactRecord] = (),
    settings: Any | None = None,
) -> str:
    """Compute a SHA-256 notebook fingerprint from canonical notebook state."""
    payload = build_notebook_fingerprint_payload(
        notebook,
        sources=sources,
        artifacts=artifacts,
        settings=settings,
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["build_notebook_fingerprint_payload", "compute_notebook_fingerprint"]
