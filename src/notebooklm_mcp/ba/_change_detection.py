"""Private support helpers for BA snapshot diffing and rerun impact analysis."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from enum import Enum

from pydantic import Field

from .matrices import ScreenMatrixBundle
from .models import (
    BAModel,
    CanonicalScreen,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    SourceManifestDocument,
    SourceSnapshotRecord,
    TerminologyDocument,
)
from .traceability import (
    build_screen_traceability_index,
    expand_dependent_screens,
    parse_matrix_evidence_ref,
)

MODULE_PURPOSE = "Own private snapshot diffing and impact-analysis helpers for incremental BA reruns."

OWNS = (
    "Deterministic before/after snapshot comparisons",
    "Screen-impact candidate mapping from manifest, evidence, and terminology signals",
    "Machine-readable impact payloads and human-readable rerun changelog rendering",
)

MUST_NOT_OWN = (
    "Public MCP wrapper registration",
    "NotebookLM transport access",
    "Filesystem persistence mechanics",
    "Step execution orchestration",
)

_DOCUMENT_BODY = "Document Body"
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+\S(?:.*\S)?$")
_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+\S(?:.*\S)?$")
_UPPERCASE_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 /_-]{5,}$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


class SnapshotChangeKind(str, Enum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    UNCHANGED = "UNCHANGED"


class SourceSnapshotDelta(BAModel):
    source_key: str = Field(min_length=1)
    change_kind: SnapshotChangeKind
    before_snapshot_id: str | None = None
    after_snapshot_id: str | None = None
    before_content_hash: str | None = None
    after_content_hash: str | None = None
    before_title: str | None = None
    after_title: str | None = None
    changed_headings: list[str] = Field(default_factory=list)
    changed_terms: list[str] = Field(default_factory=list)


class ImpactedScreenCandidate(BAModel):
    screen_id: str = Field(min_length=1)
    screen_name: str = Field(min_length=1)
    changed_sources: list[str] = Field(default_factory=list)
    changed_terms: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class RerunImpactReport(BAModel):
    changed_sources: list[str] = Field(default_factory=list)
    deltas: list[SourceSnapshotDelta] = Field(default_factory=list)
    impacted_screens: list[ImpactedScreenCandidate] = Field(default_factory=list)
    requires_full_rerun: bool = False
    escalation_reasons: list[str] = Field(default_factory=list)


def diff_source_snapshots(
    before_snapshots: Sequence[SourceSnapshotRecord],
    after_snapshots: Sequence[SourceSnapshotRecord],
    *,
    before_text_by_source: Mapping[str, str] | None = None,
    after_text_by_source: Mapping[str, str] | None = None,
    terminology: TerminologyDocument | None = None,
    include_unchanged: bool = False,
) -> tuple[SourceSnapshotDelta, ...]:
    """Return deterministic deltas across before/after snapshot sets."""

    before_by_source = {snapshot.source_key: snapshot for snapshot in before_snapshots}
    after_by_source = {snapshot.source_key: snapshot for snapshot in after_snapshots}
    before_text_by_source = before_text_by_source or {}
    after_text_by_source = after_text_by_source or {}

    deltas: list[SourceSnapshotDelta] = []
    for source_key in sorted(set(before_by_source) | set(after_by_source)):
        before = before_by_source.get(source_key)
        after = after_by_source.get(source_key)
        change_kind = _change_kind(before, after)
        if change_kind is SnapshotChangeKind.UNCHANGED and not include_unchanged:
            continue

        before_text = before_text_by_source.get(source_key, "")
        after_text = after_text_by_source.get(source_key, "")
        changed_headings = (
            _changed_headings(before_text, after_text)
            if change_kind is not SnapshotChangeKind.UNCHANGED
            else []
        )
        changed_terms = (
            _changed_terms(before_text, after_text, terminology)
            if change_kind is not SnapshotChangeKind.UNCHANGED
            else []
        )
        deltas.append(
            SourceSnapshotDelta(
                source_key=source_key,
                change_kind=change_kind,
                before_snapshot_id=before.snapshot_id if before else None,
                after_snapshot_id=after.snapshot_id if after else None,
                before_content_hash=before.content_hash if before else None,
                after_content_hash=after.content_hash if after else None,
                before_title=before.title if before else None,
                after_title=after.title if after else None,
                changed_headings=changed_headings,
                changed_terms=changed_terms,
            )
        )
    return tuple(deltas)


def analyze_rerun_impact(
    *,
    before_snapshots: Sequence[SourceSnapshotRecord],
    after_snapshots: Sequence[SourceSnapshotRecord],
    before_text_by_source: Mapping[str, str] | None = None,
    after_text_by_source: Mapping[str, str] | None = None,
    screen_catalog: ScreenCatalogDocument,
    canonical_screens: Sequence[CanonicalScreen] = (),
    source_manifest: SourceManifestDocument | None = None,
    terminology: TerminologyDocument | None = None,
    matrix_bundles: Sequence[ScreenMatrixBundle] | Mapping[str, ScreenMatrixBundle] = (),
) -> RerunImpactReport:
    """Map source deltas to candidate impacted screens and escalation signals."""

    deltas = list(
        diff_source_snapshots(
            before_snapshots,
            after_snapshots,
            before_text_by_source=before_text_by_source,
            after_text_by_source=after_text_by_source,
            terminology=terminology,
        )
    )
    catalog_by_id = {screen.screen_id: screen for screen in screen_catalog.screens}
    canonical_by_id = {screen.screen_id: screen for screen in canonical_screens}
    used_in_screens = _used_in_screens_by_source(source_manifest)
    traceability_index = build_screen_traceability_index(
        screen_catalog=screen_catalog,
        canonical_screens=canonical_screens,
        matrix_bundles=matrix_bundles,
    )
    matrix_sources_by_screen = _matrix_sources_by_screen(matrix_bundles)

    impacted: dict[str, ImpactedScreenCandidate] = {}
    covered_sources: set[str] = set()

    for catalog_entry in screen_catalog.screens:
        canonical_screen = canonical_by_id.get(catalog_entry.screen_id)
        traceability_record = traceability_index.get(catalog_entry.screen_id)
        search_blob = _screen_search_blob(catalog_entry, canonical_screen)
        evidence_sources = set(_catalog_evidence_sources(catalog_entry))
        if canonical_screen is not None:
            evidence_sources.update(_canonical_evidence_sources(canonical_screen))

        changed_sources: set[str] = set()
        changed_terms: set[str] = set()
        reasons: set[str] = set()

        for delta in deltas:
            matched = False
            if catalog_entry.screen_id in used_in_screens.get(delta.source_key, set()):
                reasons.add("manifest_usage")
                matched = True
            if delta.source_key in catalog_entry.related_sources:
                reasons.add("related_source")
                matched = True
            if delta.source_key in evidence_sources:
                reason = "canonical_evidence" if canonical_screen is not None else "catalog_evidence"
                reasons.add(reason)
                matched = True

            if (
                not matched
                and traceability_record is not None
                and delta.source_key in traceability_record.source_keys
            ):
                reasons.add(
                    "matrix_evidence"
                    if delta.source_key in matrix_sources_by_screen.get(catalog_entry.screen_id, set())
                    else "traceability_source"
                )
                matched = True

            term_hits = [term for term in delta.changed_terms if _text_mentions(search_blob, term)]
            if term_hits:
                changed_terms.update(term_hits)
                reasons.add("terminology_match")
                matched = True

            if matched:
                changed_sources.add(delta.source_key)

        if changed_sources or changed_terms:
            impacted[catalog_entry.screen_id] = ImpactedScreenCandidate(
                screen_id=catalog_entry.screen_id,
                screen_name=catalog_entry.screen_name,
                changed_sources=sorted(changed_sources),
                changed_terms=sorted(changed_terms),
                reasons=sorted(reasons),
            )
            covered_sources.update(changed_sources)

    expanded_screen_ids = expand_dependent_screens(
        list(impacted),
        traceability_index=traceability_index,
    )
    for screen_id in expanded_screen_ids:
        if screen_id in impacted:
            continue
        catalog_entry = catalog_by_id.get(screen_id)
        if catalog_entry is None:
            continue
        traceability_record = traceability_index.get(screen_id)
        parent_candidates = [
            impacted[parent_id]
            for parent_id in (() if traceability_record is None else traceability_record.depends_on)
            if parent_id in impacted
        ]
        changed_sources = sorted(
            {
                source_key
                for candidate in parent_candidates
                for source_key in candidate.changed_sources
            }
        )
        changed_terms = sorted(
            {
                term
                for candidate in parent_candidates
                for term in candidate.changed_terms
            }
        )
        impacted[screen_id] = ImpactedScreenCandidate(
            screen_id=screen_id,
            screen_name=catalog_entry.screen_name,
            changed_sources=changed_sources,
            changed_terms=changed_terms,
            reasons=["depends_on_impacted_screen"],
        )

    for candidate in impacted.values():
        covered_sources.update(candidate.changed_sources)

    escalation_reasons: list[str] = []
    changed_sources = [delta.source_key for delta in deltas]
    uncovered_sources = sorted(set(changed_sources) - covered_sources)
    if uncovered_sources:
        escalation_reasons.append(
            "no deterministic screen match for changed sources: " + ", ".join(uncovered_sources)
        )
    if screen_catalog.screens and len(impacted) == len(screen_catalog.screens) and len(impacted) > 1:
        escalation_reasons.append("changes cut across every known screen")

    return RerunImpactReport(
        changed_sources=changed_sources,
        deltas=sorted(deltas, key=lambda item: item.source_key),
        impacted_screens=sorted(impacted.values(), key=lambda item: item.screen_id),
        requires_full_rerun=bool(escalation_reasons),
        escalation_reasons=escalation_reasons,
    )


def render_impacted_screens_json(report: RerunImpactReport) -> str:
    """Serialize a rerun impact report for ``impacted-screens.json``."""

    return report.model_dump_json(indent=2) + "\n"


def render_changelog_markdown(report: RerunImpactReport) -> str:
    """Render a deterministic human-readable changelog for a rerun plan."""

    lines = ["# Changelog", ""]

    if not report.deltas:
        lines.extend(["No source changes were detected.", ""])
    else:
        lines.extend(["## Source Changes", ""])
        for delta in report.deltas:
            lines.append(
                "- `{source_key}`: {change_kind} ({before} -> {after})".format(
                    source_key=delta.source_key,
                    change_kind=delta.change_kind.value.lower(),
                    before=delta.before_snapshot_id or "none",
                    after=delta.after_snapshot_id or "none",
                )
            )
            if delta.changed_headings:
                lines.append("  headings: " + ", ".join(f"`{item}`" for item in delta.changed_headings))
            if delta.changed_terms:
                lines.append("  terms: " + ", ".join(f"`{item}`" for item in delta.changed_terms))
        lines.append("")

    lines.extend(["## Impacted Screens", ""])
    if not report.impacted_screens:
        lines.append("- No deterministic screen matches were found.")
    else:
        for screen in report.impacted_screens:
            lines.append(f"- `{screen.screen_id}` {screen.screen_name}")
            lines.append(
                "  reasons: " + ", ".join(f"`{reason}`" for reason in screen.reasons)
                if screen.reasons
                else "  reasons: none"
            )
            lines.append(
                "  changed sources: " + ", ".join(f"`{item}`" for item in screen.changed_sources)
                if screen.changed_sources
                else "  changed sources: none"
            )
            if screen.changed_terms:
                lines.append(
                    "  changed terms: " + ", ".join(f"`{item}`" for item in screen.changed_terms)
                )
    lines.append("")

    lines.extend(["## Rerun Recommendation", ""])
    if report.requires_full_rerun:
        lines.append("- Full rerun recommended.")
        for reason in report.escalation_reasons:
            lines.append(f"  reason: {reason}")
    else:
        lines.append("- Targeted rerun is sufficient.")
    lines.append("")
    return "\n".join(lines)


def _change_kind(
    before: SourceSnapshotRecord | None,
    after: SourceSnapshotRecord | None,
) -> SnapshotChangeKind:
    if before is None and after is not None:
        return SnapshotChangeKind.ADDED
    if before is not None and after is None:
        return SnapshotChangeKind.REMOVED
    if before is None or after is None:
        msg = "before/after snapshot pairing must be complete"
        raise ValueError(msg)
    if (
        before.content_hash == after.content_hash
        and before.title == after.title
        and before.freshness == after.freshness
    ):
        return SnapshotChangeKind.UNCHANGED
    return SnapshotChangeKind.MODIFIED


def _changed_headings(before_text: str, after_text: str) -> list[str]:
    before_sections = _section_map(before_text)
    after_sections = _section_map(after_text)
    return sorted(
        heading
        for heading in set(before_sections) | set(after_sections)
        if before_sections.get(heading, "") != after_sections.get(heading, "")
    )


def _changed_terms(
    before_text: str,
    after_text: str,
    terminology: TerminologyDocument | None,
) -> list[str]:
    if terminology is None:
        return []

    changed_terms: list[str] = []
    for entry in terminology.entries:
        variants = tuple(dict.fromkeys([entry.standard_term, *entry.aliases]))
        before_presence = tuple(_text_mentions(before_text, variant) for variant in variants)
        after_presence = tuple(_text_mentions(after_text, variant) for variant in variants)
        if before_presence != after_presence:
            changed_terms.append(entry.standard_term)
    return sorted(dict.fromkeys(changed_terms))


def _section_map(text: str) -> dict[str, str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return {}

    sections: dict[str, list[str]] = defaultdict(list)
    current_heading = _DOCUMENT_BODY
    saw_heading = False

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if _is_heading(line):
            current_heading = _normalize_heading(line)
            saw_heading = True
            sections.setdefault(current_heading, [])
            continue
        sections[current_heading].append(raw_line.rstrip())

    if not saw_heading:
        return {_DOCUMENT_BODY: normalized}
    return {
        heading: "\n".join(lines).strip()
        for heading, lines in sections.items()
        if heading != _DOCUMENT_BODY or any(line.strip() for line in lines)
    }


def _is_heading(line: str) -> bool:
    if _MARKDOWN_HEADING_RE.match(line):
        return True
    if _NUMBERED_HEADING_RE.match(line):
        return True
    if line.endswith(":") and len(line) >= 6:
        return True
    return bool(_UPPERCASE_HEADING_RE.match(line))


def _normalize_heading(line: str) -> str:
    heading = line.strip()
    if heading.startswith("#"):
        heading = heading.lstrip("#").strip()
    heading = re.sub(r"^\d+(?:\.\d+)*[.)]?\s+", "", heading)
    if heading.endswith(":") and len(heading) >= 6:
        heading = heading[:-1].strip()
    return re.sub(r"\s+", " ", heading)


def _used_in_screens_by_source(
    source_manifest: SourceManifestDocument | None,
) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    if source_manifest is None:
        return mapping
    for row in source_manifest.rows:
        mapping[row.source_key].update(row.used_in_screens)
    return mapping


def _matrix_sources_by_screen(
    matrix_bundles: Sequence[ScreenMatrixBundle] | Mapping[str, ScreenMatrixBundle],
) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    bundles = matrix_bundles.values() if isinstance(matrix_bundles, Mapping) else matrix_bundles
    for bundle in bundles:
        for row in (*bundle.field_rows, *bundle.action_rule_rows, *bundle.api_rows):
            for evidence_ref in row.evidence_refs:
                pointer = parse_matrix_evidence_ref(evidence_ref)
                if pointer is not None:
                    mapping[bundle.screen_id].add(pointer.source_key)
    return mapping


def _catalog_evidence_sources(catalog_entry: ScreenCatalogEntry) -> tuple[str, ...]:
    return tuple(item.source_key for item in catalog_entry.evidence)


def _canonical_evidence_sources(canonical_screen: CanonicalScreen) -> tuple[str, ...]:
    sources: list[str] = []
    for fact in canonical_screen.shared_facts:
        sources.extend(item.source_key for item in fact.evidence)
    for fact in canonical_screen.fe_facts:
        sources.extend(item.source_key for item in fact.evidence)
    for fact in canonical_screen.be_facts:
        sources.extend(item.source_key for item in fact.evidence)
    for gap in canonical_screen.missing_info:
        sources.extend(item.source_key for item in gap.evidence)
    for question in canonical_screen.open_questions:
        sources.extend(item.source_key for item in question.evidence)
    for contradiction in canonical_screen.contradictions:
        for claim in contradiction.claims:
            sources.extend(item.source_key for item in claim.evidence)
    return tuple(sources)


def _screen_search_blob(
    catalog_entry: ScreenCatalogEntry,
    canonical_screen: CanonicalScreen | None,
) -> str:
    values: list[str] = [
        catalog_entry.screen_id,
        catalog_entry.screen_name,
        catalog_entry.purpose,
        *catalog_entry.roles,
        *catalog_entry.entry_points,
        *catalog_entry.exit_points,
        *catalog_entry.main_actions,
        *catalog_entry.dependencies,
        *catalog_entry.related_sources,
    ]
    if canonical_screen is not None:
        values.extend(_canonical_search_values(canonical_screen))
    return "\n".join(value for value in values if value)


def _canonical_search_values(canonical_screen: CanonicalScreen) -> list[str]:
    values: list[str] = []
    for fact in (*canonical_screen.shared_facts, *canonical_screen.fe_facts, *canonical_screen.be_facts):
        values.extend([fact.fact_id, fact.category, _json_text(fact.value), fact.note or "", fact.rationale or ""])
    for gap in canonical_screen.missing_info:
        values.extend([gap.gap_id, gap.summary, gap.owner or ""])
    for question in canonical_screen.open_questions:
        values.extend([question.question_id, question.summary, question.owner or ""])
    for contradiction in canonical_screen.contradictions:
        values.extend([contradiction.contradiction_id, contradiction.summary, contradiction.open_question or ""])
        values.extend(claim.claim for claim in contradiction.claims)
    values.extend(canonical_screen.dependencies)
    return [value for value in values if value]


def _json_text(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return str(value)


def _text_mentions(haystack: str, needle: str) -> bool:
    if not haystack.strip() or not needle.strip():
        return False
    pattern = re.compile(rf"(?<!\w){re.escape(needle.strip())}(?!\w)", re.IGNORECASE)
    return bool(pattern.search(haystack))


__all__ = [
    "ImpactedScreenCandidate",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "RerunImpactReport",
    "SnapshotChangeKind",
    "SourceSnapshotDelta",
    "analyze_rerun_impact",
    "diff_source_snapshots",
    "render_changelog_markdown",
    "render_impacted_screens_json",
]
