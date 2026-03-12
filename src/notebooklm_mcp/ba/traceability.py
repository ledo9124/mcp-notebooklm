"""Traceability helpers for mapping BA sources and evidence back to screens."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import re

from pydantic import Field

from .matrices import ScreenMatrixBundle
from .models import (
    BAModel,
    CanonicalScreen,
    EvidenceRef,
    ScreenCatalogDocument,
)

MODULE_PURPOSE = "Own deterministic source-to-screen traceability helpers for selective rerun planning."

OWNS = (
    "Pure traceability indexes over screen catalogs, canonical screens, and matrix evidence refs",
    "Dependency expansion from directly impacted screens to downstream dependents",
    "Typed parsing helpers for persisted matrix evidence references",
)

MUST_NOT_OWN = (
    "NotebookLM SDK access",
    "Filesystem persistence mechanics",
    "Prompt text or extraction policy",
    "MCP registration or wrapper result envelopes",
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_MATRIX_EVIDENCE_REF_RE = re.compile(
    r"^(?P<source_key>[^@:\s]+)@(?P<snapshot_id>[^:\s]+)(?::(?P<locator>.*))?$"
)


class MatrixEvidencePointer(BAModel):
    source_key: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    locator: str | None = None


class ScreenTraceabilityRecord(BAModel):
    screen_id: str = Field(min_length=1)
    source_keys: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    dependent_screens: list[str] = Field(default_factory=list)


def parse_matrix_evidence_ref(value: str) -> MatrixEvidencePointer | None:
    """Parse a persisted matrix evidence ref such as ``source@snapshot:locator``."""

    match = _MATRIX_EVIDENCE_REF_RE.fullmatch(value.strip())
    if match is None:
        return None
    locator = (match.group("locator") or "").strip() or None
    return MatrixEvidencePointer(
        source_key=match.group("source_key"),
        snapshot_id=match.group("snapshot_id"),
        locator=locator,
    )


def build_screen_traceability_index(
    *,
    screen_catalog: ScreenCatalogDocument | None = None,
    canonical_screens: Sequence[CanonicalScreen] = (),
    matrix_bundles: Sequence[ScreenMatrixBundle] | Mapping[str, ScreenMatrixBundle] = (),
) -> dict[str, ScreenTraceabilityRecord]:
    """Build a deterministic screen traceability index from persisted BA artifacts."""

    catalog_by_id = {
        screen.screen_id: screen
        for screen in (() if screen_catalog is None else screen_catalog.screens)
    }
    dependency_index = _dependency_index(catalog_by_id.values(), canonical_screens)
    canonical_by_id = {screen.screen_id: screen for screen in canonical_screens}
    matrix_by_id = _matrix_bundle_index(matrix_bundles)

    screen_ids = sorted(
        set(catalog_by_id).union(canonical_by_id).union(matrix_by_id),
        key=_normalize_identifier,
    )
    forward_dependencies: dict[str, set[str]] = {}
    records: dict[str, ScreenTraceabilityRecord] = {}

    for screen_id in screen_ids:
        catalog_entry = catalog_by_id.get(screen_id)
        canonical_screen = canonical_by_id.get(screen_id)
        matrix_bundle = matrix_by_id.get(screen_id)

        source_keys: list[str] = []
        evidence_refs: list[str] = []
        dependencies: list[str] = []

        if catalog_entry is not None:
            source_keys.extend(catalog_entry.related_sources)
            for evidence in catalog_entry.evidence:
                source_keys.append(evidence.source_key)
                evidence_refs.append(_format_evidence_ref(evidence))
            dependencies.extend(_resolve_dependency_ids(catalog_entry.dependencies, dependency_index))

        if canonical_screen is not None:
            for evidence in _screen_evidence(canonical_screen):
                source_keys.append(evidence.source_key)
                evidence_refs.append(_format_evidence_ref(evidence))
            dependencies.extend(_resolve_dependency_ids(canonical_screen.dependencies, dependency_index))

        if matrix_bundle is not None:
            for ref in _matrix_evidence_refs(matrix_bundle):
                evidence_refs.append(ref)
                pointer = parse_matrix_evidence_ref(ref)
                if pointer is not None:
                    source_keys.append(pointer.source_key)

        deduped_dependencies = _sorted_texts(
            dependency
            for dependency in dependencies
            if dependency and dependency != screen_id
        )
        forward_dependencies[screen_id] = set(deduped_dependencies)
        records[screen_id] = ScreenTraceabilityRecord(
            screen_id=screen_id,
            source_keys=_sorted_texts(source_keys),
            evidence_refs=_sorted_texts(evidence_refs),
            depends_on=deduped_dependencies,
        )

    reverse_dependencies: dict[str, list[str]] = defaultdict(list)
    for screen_id, dependencies in forward_dependencies.items():
        for dependency in dependencies:
            reverse_dependencies[dependency].append(screen_id)

    for screen_id, record in tuple(records.items()):
        records[screen_id] = record.model_copy(
            update={
                "dependent_screens": _sorted_texts(reverse_dependencies.get(screen_id, ())),
            }
        )

    return records


def build_source_to_screen_index(
    traceability_index: Mapping[str, ScreenTraceabilityRecord],
) -> dict[str, list[str]]:
    """Invert a screen traceability index into ``source_key -> screen_ids``."""

    source_index: dict[str, set[str]] = defaultdict(set)
    for screen_id, record in traceability_index.items():
        for source_key in record.source_keys:
            if source_key:
                source_index[source_key].add(screen_id)

    return {
        source_key: _sorted_texts(screen_ids)
        for source_key, screen_ids in sorted(
            source_index.items(),
            key=lambda item: _normalize_identifier(item[0]),
        )
    }


def expand_dependent_screens(
    screen_ids: Sequence[str],
    *,
    traceability_index: Mapping[str, ScreenTraceabilityRecord],
) -> list[str]:
    """Expand direct screen impacts to include downstream dependent screens."""

    expanded: set[str] = {screen_id for screen_id in screen_ids if screen_id}
    frontier = sorted(expanded, key=_normalize_identifier)

    while frontier:
        screen_id = frontier.pop(0)
        record = traceability_index.get(screen_id)
        if record is None:
            continue
        for dependent in record.dependent_screens:
            if dependent not in expanded:
                expanded.add(dependent)
                frontier.append(dependent)
        frontier.sort(key=_normalize_identifier)

    return _sorted_texts(expanded)


def map_changed_sources_to_screens(
    changed_source_keys: Sequence[str],
    *,
    screen_catalog: ScreenCatalogDocument | None = None,
    canonical_screens: Sequence[CanonicalScreen] = (),
    matrix_bundles: Sequence[ScreenMatrixBundle] | Mapping[str, ScreenMatrixBundle] = (),
    include_dependents: bool = True,
) -> list[str]:
    """Resolve changed source keys to impacted screens via persisted traceability data."""

    traceability_index = build_screen_traceability_index(
        screen_catalog=screen_catalog,
        canonical_screens=canonical_screens,
        matrix_bundles=matrix_bundles,
    )
    source_index = build_source_to_screen_index(traceability_index)
    normalized_source_index: dict[str, set[str]] = defaultdict(set)
    for source_key, screen_ids in source_index.items():
        normalized_source_index[_normalize_identifier(source_key)].update(screen_ids)

    direct_impacts: set[str] = set()
    for source_key in changed_source_keys:
        if not source_key:
            continue
        direct_impacts.update(source_index.get(source_key, ()))
        direct_impacts.update(normalized_source_index.get(_normalize_identifier(source_key), ()))

    direct_impact_ids = _sorted_texts(direct_impacts)
    if not include_dependents:
        return direct_impact_ids
    return expand_dependent_screens(direct_impact_ids, traceability_index=traceability_index)


def _dependency_index(
    catalog_entries: Sequence[object],
    canonical_screens: Sequence[CanonicalScreen],
) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in catalog_entries:
        screen_id = getattr(item, "screen_id", None)
        screen_name = getattr(item, "screen_name", None)
        if screen_id:
            index.setdefault(_normalize_identifier(screen_id), screen_id)
        if screen_name:
            index.setdefault(_normalize_identifier(screen_name), screen_id)
    for screen in canonical_screens:
        index.setdefault(_normalize_identifier(screen.screen_id), screen.screen_id)
    return index


def _resolve_dependency_ids(
    dependencies: Sequence[str],
    dependency_index: Mapping[str, str],
) -> list[str]:
    resolved: list[str] = []
    for dependency in dependencies:
        normalized = _normalize_identifier(dependency)
        if normalized and normalized in dependency_index:
            resolved.append(dependency_index[normalized])
    return resolved


def _matrix_bundle_index(
    matrix_bundles: Sequence[ScreenMatrixBundle] | Mapping[str, ScreenMatrixBundle],
) -> dict[str, ScreenMatrixBundle]:
    if isinstance(matrix_bundles, Mapping):
        return dict(matrix_bundles)
    return {bundle.screen_id: bundle for bundle in matrix_bundles}


def _matrix_evidence_refs(bundle: ScreenMatrixBundle) -> tuple[str, ...]:
    refs: list[str] = []
    for row in (*bundle.field_rows, *bundle.action_rule_rows, *bundle.api_rows):
        refs.extend(row.evidence_refs)
    return tuple(_sorted_texts(refs))


def _screen_evidence(screen: CanonicalScreen) -> tuple[EvidenceRef, ...]:
    evidence: list[EvidenceRef] = []
    for fact in (*screen.shared_facts, *screen.fe_facts, *screen.be_facts):
        evidence.extend(fact.evidence)
    for contradiction in screen.contradictions:
        evidence.extend(_contradiction_evidence(contradiction))
    for gap in screen.missing_info:
        evidence.extend(gap.evidence)
    for question in screen.open_questions:
        evidence.extend(question.evidence)
    return tuple(
        sorted(
            _dedupe_evidence(evidence),
            key=lambda item: (
                item.source_key,
                item.snapshot_id,
                item.locator or "",
                item.quote or "",
            ),
        )
    )


def _contradiction_evidence(contradiction: object) -> tuple[EvidenceRef, ...]:
    evidence: list[EvidenceRef] = []
    for claim in getattr(contradiction, "claims", ()):
        evidence.extend(getattr(claim, "evidence", ()))
    return tuple(evidence)


def _dedupe_evidence(evidence: Sequence[EvidenceRef]) -> list[EvidenceRef]:
    deduped: dict[tuple[str, str, str, str], EvidenceRef] = {}
    for item in evidence:
        deduped.setdefault(
            (
                item.source_key,
                item.snapshot_id,
                item.locator or "",
                item.quote or "",
            ),
            item,
        )
    return list(deduped.values())


def _format_evidence_ref(evidence: EvidenceRef) -> str:
    locator = evidence.locator or (evidence.quote or "").replace("\n", " ").strip()
    if locator:
        return f"{evidence.source_key}@{evidence.snapshot_id}:{locator}"
    return f"{evidence.source_key}@{evidence.snapshot_id}"


def _sorted_texts(values: Sequence[str] | set[str]) -> list[str]:
    return sorted({value for value in values if value}, key=_normalize_identifier)


def _normalize_identifier(value: str) -> str:
    return _NON_ALNUM_RE.sub("-", value.strip().lower()).strip("-")


__all__ = [
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "MatrixEvidencePointer",
    "ScreenTraceabilityRecord",
    "build_screen_traceability_index",
    "build_source_to_screen_index",
    "expand_dependent_screens",
    "map_changed_sources_to_screens",
    "parse_matrix_evidence_ref",
]
