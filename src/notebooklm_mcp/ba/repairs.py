"""Deterministic repair policy for safe BA bundle artifact rewrites."""

from __future__ import annotations

from collections.abc import Sequence

from .models import (
    ReadinessSummary,
    ScreenCatalogDocument,
    SourceManifestDocument,
    TerminologyDocument,
    ValidationFinding,
    ValidationSeverity,
)
from .rendering import ScreenBundleArtifact, build_bundle_file_map
from .run_store import BARunStore

MODULE_PURPOSE = "Own the allowlisted deterministic repair rules for rendered BA bundle artifacts."

OWNS = (
    "Safe repair path allowlists for deterministic bundle files",
    "Audit-friendly repair finding generation",
    "Filesystem rewrites derived from existing rendered inputs only",
)

MUST_NOT_OWN = (
    "Semantic gap resolution",
    "Evidence invention",
    "NotebookLM SDK access",
    "Pipeline step orchestration",
)

_SAFE_FEATURE_REPAIR_PATHS = frozenset(
    {
        "00-overview.md",
        "01-source-manifest.md",
        "01-source-manifest.json",
        "02-screen-catalog.json",
        "03-readiness-summary.md",
        "04-terminology.md",
        "04-terminology.json",
    }
)

_SAFE_SCREEN_REPAIR_FILES = frozenset(
    {
        "canonical.json",
        "fe.md",
        "be.md",
        "questions.md",
        "field-matrix.csv",
        "action-rule-matrix.csv",
        "api-matrix.csv",
        "contract.provisional.yaml",
        "mock-data.json",
    }
)


def apply_deterministic_repairs(
    store: BARunStore,
    source_manifest: SourceManifestDocument,
    screen_catalog: ScreenCatalogDocument,
    readiness: ReadinessSummary,
    screen_artifacts: Sequence[object] = (),
    *,
    terminology: TerminologyDocument | None = None,
) -> list[ValidationFinding]:
    """Repair only files whose canonical content is already available locally."""

    typed_screen_artifacts = [
        artifact for artifact in screen_artifacts if isinstance(artifact, ScreenBundleArtifact)
    ]
    if terminology is None:
        try:
            terminology = store.load_terminology()
        except Exception:
            terminology = None

    try:
        run_audit = store.load_run_audit()
    except Exception:
        run_audit = None

    expected_files = build_bundle_file_map(
        source_manifest=source_manifest,
        screen_catalog=screen_catalog,
        readiness=readiness,
        screen_artifacts=typed_screen_artifacts,
        terminology=terminology,
        run_audit=run_audit,
    )

    repairs: list[ValidationFinding] = []
    for relative_path, expected_content in sorted(expected_files.items()):
        if not _is_safe_repair_path(relative_path):
            continue

        target_path = store.feature_paths.root / relative_path
        previous_state = _repair_state(target_path, expected_content)
        if previous_state is None:
            continue

        store.write_text(target_path, expected_content)
        repairs.append(
            ValidationFinding(
                code="deterministic-repair-applied",
                severity=ValidationSeverity.WARNING,
                message=_repair_message(relative_path, previous_state),
                screen_id=_screen_id_for_path(relative_path),
                file_path=relative_path,
                details={
                    "previous_state": previous_state,
                    "repair_policy": "deterministic-rendered-artifact",
                    "repair_source": (
                        "screen_artifacts" if relative_path.startswith("screens/") else "bundle_inputs"
                    ),
                },
            )
        )
    return repairs


def _is_safe_repair_path(relative_path: str) -> bool:
    if relative_path in _SAFE_FEATURE_REPAIR_PATHS:
        return True
    if not relative_path.startswith("screens/"):
        return False

    parts = relative_path.split("/")
    return len(parts) == 3 and parts[2] in _SAFE_SCREEN_REPAIR_FILES


def _repair_state(target_path, expected_content: str) -> str | None:
    if not target_path.exists():
        return "missing"

    try:
        current_content = target_path.read_text(encoding="utf-8")
    except Exception:
        return "unreadable"

    if current_content == expected_content:
        return None
    return "drifted"


def _screen_id_for_path(relative_path: str) -> str | None:
    if not relative_path.startswith("screens/"):
        return None

    parts = relative_path.split("/")
    if len(parts) < 3:
        return None
    return parts[1]


def _repair_message(relative_path: str, previous_state: str) -> str:
    if previous_state == "missing":
        return f"restored missing deterministic artifact `{relative_path}` from local rendered inputs"
    if previous_state == "unreadable":
        return f"rewrote unreadable deterministic artifact `{relative_path}` from local rendered inputs"
    return f"rewrote drifted deterministic artifact `{relative_path}` from local rendered inputs"


__all__ = [
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "apply_deterministic_repairs",
]
