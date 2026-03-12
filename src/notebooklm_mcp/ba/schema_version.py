"""Schema-versioning boundary for BA artifacts and payloads."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

MODULE_PURPOSE = "Own schema family/version identifiers and compatibility helpers for BA outputs."

OWNS = (
    "Schema family names",
    "Version bump policy helpers",
    "Compatibility checks for stored runs and rendered bundles",
)

MUST_NOT_OWN = (
    "Extraction logic",
    "NotebookLM RPC access",
    "Rendered output formatting",
    "MCP transport concerns",
)


class SchemaFamily(str, Enum):
    """Stable schema families emitted by the BA runner."""

    SOURCE_MANIFEST = "source_manifest"
    TERMINOLOGY = "terminology"
    SCREEN_CATALOG = "screen_catalog"
    CANONICAL_SCREEN = "canonical_screen"
    GAP_REVIEW = "gap_review"
    READINESS_SUMMARY = "readiness_summary"
    CONTRACT_METADATA = "contract_metadata"
    VALIDATION_REPORT = "validation_report"
    RUN_STATE = "run_state"
    METRICS_REPORT = "metrics_report"


class SchemaChangeKind(str, Enum):
    """Policy categories for intentional schema evolution."""

    NONE = "none"
    ADDITIVE = "additive"
    BREAKING = "breaking"


class SchemaVersion(BaseModel):
    """Version descriptor for a single BA schema family."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family: SchemaFamily
    major: int = Field(ge=1)
    minor: int = Field(ge=0, default=0)

    @property
    def token(self) -> str:
        """Return the serialized schema token stored in artifacts."""
        return f"ba.{self.family.value}.v{self.major}.{self.minor}"

    def bump(self, change: SchemaChangeKind) -> "SchemaVersion":
        """Return a new version after applying a schema change policy."""
        if change is SchemaChangeKind.NONE:
            return self
        if change is SchemaChangeKind.ADDITIVE:
            return SchemaVersion(family=self.family, major=self.major, minor=self.minor + 1)
        return SchemaVersion(family=self.family, major=self.major + 1, minor=0)


CURRENT_SCHEMA_VERSIONS: dict[SchemaFamily, SchemaVersion] = {
    family: SchemaVersion(family=family, major=1, minor=0) for family in SchemaFamily
}
CURRENT_SCHEMA_VERSIONS[SchemaFamily.RUN_STATE] = SchemaVersion(
    family=SchemaFamily.RUN_STATE,
    major=1,
    minor=1,
)

SCHEMA_CHANGE_RULES: dict[SchemaChangeKind, str] = {
    SchemaChangeKind.NONE: (
        "Do not bump when only docs, comments, tests, or internal implementation details change."
    ),
    SchemaChangeKind.ADDITIVE: (
        "Bump MINOR for backward-compatible additions such as optional fields, new non-required "
        "enum values, or extra derived metadata that older readers can ignore."
    ),
    SchemaChangeKind.BREAKING: (
        "Bump MAJOR for incompatible changes such as removing or renaming fields, changing field "
        "meaning, tightening requiredness, or changing enum semantics."
    ),
}


def current_schema_version(family: SchemaFamily) -> str:
    """Return the serialized current version token for a schema family."""
    return CURRENT_SCHEMA_VERSIONS[family].token


def is_compatible(version: SchemaVersion, expected_family: SchemaFamily) -> bool:
    """Check whether a stored version is readable by the current code.

    Compatibility is intentionally conservative:
    - family must match
    - major version must match
    - any minor version is accepted within the same major line
    """

    current = CURRENT_SCHEMA_VERSIONS[expected_family]
    return version.family is expected_family and version.major == current.major


def classify_change(
    *,
    removed_fields: bool = False,
    renamed_fields: bool = False,
    changed_meaning: bool = False,
    tightened_requiredness: bool = False,
    added_optional_fields: bool = False,
    added_enum_values: bool = False,
) -> SchemaChangeKind:
    """Classify a schema edit using the BA runner's versioning policy."""

    if removed_fields or renamed_fields or changed_meaning or tightened_requiredness:
        return SchemaChangeKind.BREAKING
    if added_optional_fields or added_enum_values:
        return SchemaChangeKind.ADDITIVE
    return SchemaChangeKind.NONE


__all__ = [
    "CURRENT_SCHEMA_VERSIONS",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "SCHEMA_CHANGE_RULES",
    "SchemaChangeKind",
    "SchemaFamily",
    "SchemaVersion",
    "classify_change",
    "current_schema_version",
    "is_compatible",
]
