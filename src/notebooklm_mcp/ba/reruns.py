"""Rerun-planning boundary for incremental BA workflows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from enum import Enum
from math import ceil
import re
from typing import Any

from pydantic import Field

from .models import (
    BAModel,
    CanonicalScreen,
    FactStatus,
    ReadinessSummary,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    SourceManifestDocument,
    SourceSnapshotRecord,
    SourceType,
    TerminologyDocument,
)

MODULE_PURPOSE = "Own impact analysis and selective rerun planning across BA workflow stages."

OWNS = (
    "Change-impact planning for partial reruns",
    "Stage invalidation rules based on stored run metadata",
    "Rerun orchestration decisions over extraction/rendering/validation outputs",
)

MUST_NOT_OWN = (
    "NotebookLM SDK parity logic",
    "Raw persistence mechanics",
    "Prompt text",
    "MCP tool registration",
)

_HEADING_RE = re.compile(r"^(?:#{1,6}\s+\S.*|[A-Z][A-Za-z0-9 /_-]{2,80}:)$")
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


class RerunDecision(str, Enum):
    """Plan-level rerun outcomes."""

    NO_CHANGES = "NO_CHANGES"
    SELECTIVE = "SELECTIVE"
    FULL_FEATURE = "FULL_FEATURE"


class SourceSnapshotText(BAModel):
    """Persisted snapshot record paired with fulltext for diffing."""

    record: SourceSnapshotRecord
    content: str = ""


class SourceSnapshotDiff(BAModel):
    """Structured change summary for one source between two snapshots."""

    source_key: str = Field(min_length=1)
    source_type: SourceType | None = None
    previous_snapshot_id: str | None = None
    current_snapshot_id: str | None = None
    previous_content_hash: str | None = None
    current_content_hash: str | None = None
    hash_changed: bool = False
    changed_span_count: int = Field(ge=0, default=0)
    similarity: float = Field(ge=0.0, le=1.0, default=1.0)
    added_headings: list[str] = Field(default_factory=list)
    removed_headings: list[str] = Field(default_factory=list)
    added_terms: list[str] = Field(default_factory=list)
    removed_terms: list[str] = Field(default_factory=list)
    related_screens: list[str] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ImpactedScreen(BAModel):
    """One screen that should participate in a selective rerun."""

    screen_id: str = Field(min_length=1)
    source_keys: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class RerunPlan(BAModel):
    """Full rerun decision with source diffs and impacted screen mapping."""

    feature_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    decision: RerunDecision
    changed_sources: list[SourceSnapshotDiff] = Field(default_factory=list)
    impacted_screens: list[ImpactedScreen] = Field(default_factory=list)
    dependent_artifacts: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def attach_source_screen_usage(
    manifest: SourceManifestDocument,
    *,
    screen_catalog: ScreenCatalogDocument,
    canonical_screens: Mapping[str, CanonicalScreen] | None = None,
) -> SourceManifestDocument:
    """Attach per-source screen usage so later reruns have stronger mapping hints."""

    usage_by_source: dict[str, set[str]] = defaultdict(set)
    for screen in screen_catalog.screens:
        source_keys = set(screen.related_sources)
        source_keys.update(item.source_key for item in screen.evidence)
        source_keys.update(_canonical_source_keys(canonical_screens, screen.screen_id))
        for source_key in source_keys:
            usage_by_source[source_key].add(screen.screen_id)

    rows = [
        row.model_copy(
            update={
                "used_in_screens": sorted(
                    set(row.used_in_screens).union(usage_by_source.get(row.source_key, set()))
                )
            }
        )
        for row in manifest.rows
    ]
    return manifest.model_copy(update={"rows": rows})


def build_rerun_plan(
    *,
    feature_key: str,
    run_id: str,
    previous_manifest: SourceManifestDocument,
    current_manifest: SourceManifestDocument,
    previous_screen_catalog: ScreenCatalogDocument,
    current_screen_catalog: ScreenCatalogDocument,
    previous_terminology: TerminologyDocument,
    current_terminology: TerminologyDocument,
    previous_canonical_screens: Mapping[str, CanonicalScreen],
    previous_snapshots: Mapping[str, SourceSnapshotText],
    current_snapshots: Mapping[str, SourceSnapshotText],
    matrix_source_links: Mapping[str, Sequence[str]] | None = None,
) -> RerunPlan:
    """Compare current artifacts to the persisted baseline and decide rerun scope."""

    previous_rows = {row.source_key: row for row in previous_manifest.rows}
    current_rows = {row.source_key: row for row in current_manifest.rows}
    source_screen_links = _source_screen_links(
        previous_manifest=previous_manifest,
        current_manifest=current_manifest,
        previous_screen_catalog=previous_screen_catalog,
        current_screen_catalog=current_screen_catalog,
        previous_canonical_screens=previous_canonical_screens,
        matrix_source_links=matrix_source_links or {},
    )
    changed_screen_ids = _changed_screen_catalog_ids(previous_screen_catalog, current_screen_catalog)
    term_links = _term_screen_links(
        previous_screen_catalog=previous_screen_catalog,
        current_screen_catalog=current_screen_catalog,
        previous_canonical_screens=previous_canonical_screens,
        terminology=(previous_terminology, current_terminology),
    )
    previous_terms_by_source, previous_all_terms = _terms_by_source(previous_terminology)
    current_terms_by_source, current_all_terms = _terms_by_source(current_terminology)
    changed_terms = sorted(previous_all_terms.symmetric_difference(current_all_terms), key=str.casefold)

    impacted_reasons: dict[str, list[str]] = defaultdict(list)
    impacted_sources: dict[str, set[str]] = defaultdict(set)
    changed_sources: list[SourceSnapshotDiff] = []
    warnings: list[str] = []

    for source_key in sorted(set(previous_rows) | set(current_rows) | set(previous_snapshots) | set(current_snapshots)):
        diff = _build_source_diff(
            source_key=source_key,
            source_type=(current_rows.get(source_key) or previous_rows.get(source_key)).source_type
            if (current_rows.get(source_key) or previous_rows.get(source_key))
            else None,
            previous_snapshot=previous_snapshots.get(source_key),
            current_snapshot=current_snapshots.get(source_key),
            previous_terms=previous_terms_by_source.get(source_key, set()),
            current_terms=current_terms_by_source.get(source_key, set()),
        )
        if diff is None:
            continue

        linked_screens = set(source_screen_links.get(source_key, ()))
        for term in (*diff.added_terms, *diff.removed_terms):
            linked_screens.update(term_links.get(term, ()))
        diff.related_screens = sorted(linked_screens)
        changed_sources.append(diff)

        if not linked_screens:
            warnings.append(
                f"changed source `{source_key}` had no direct screen links; consider a full rerun if downstream drift appears."
            )
        for screen_id in linked_screens:
            impacted_sources[screen_id].add(source_key)
            impacted_reasons[screen_id].append(_source_reason_text(diff))

    for screen_id in changed_screen_ids:
        impacted_reasons[screen_id].append("screen catalog entry changed")

    for term in changed_terms:
        for screen_id in term_links.get(term, ()):
            impacted_reasons[screen_id].append(f"terminology changed: {term}")

    escalation_reasons: list[str] = []
    if _screen_catalog_changed_materially(
        previous_screen_catalog,
        current_screen_catalog,
        changed_screen_ids=changed_screen_ids,
    ):
        escalation_reasons.append("screen catalog changed materially")

    if _cross_cutting_terminology_change(
        changed_terms=changed_terms,
        term_links=term_links,
        total_screens=len(current_screen_catalog.screens),
    ):
        escalation_reasons.append("terminology changes are cross-cutting across the feature")

    for diff in changed_sources:
        current_row = current_rows.get(diff.source_key)
        if _source_quality_degraded(current_row):
            escalation_reasons.append(
                f"source quality degraded for `{diff.source_key}`"
            )
        if _is_primary_requirement_replaced(diff=diff, row=current_row):
            escalation_reasons.append(
                f"primary requirement source `{diff.source_key}` appears to have been replaced wholesale"
            )

    impacted_screens = [
        ImpactedScreen(
            screen_id=screen_id,
            source_keys=sorted(impacted_sources.get(screen_id, set())),
            reasons=_dedupe_texts(impacted_reasons[screen_id]),
        )
        for screen_id in sorted(impacted_reasons)
    ]

    if changed_sources and not impacted_screens and not escalation_reasons:
        escalation_reasons.append("changed sources could not be mapped safely to impacted screens")

    decision = RerunDecision.NO_CHANGES
    if changed_sources:
        decision = (
            RerunDecision.FULL_FEATURE if escalation_reasons else RerunDecision.SELECTIVE
        )

    dependent_artifacts: list[str] = []
    if changed_sources:
        dependent_artifacts = [
            "00-overview.md",
            "01-source-manifest.md",
            "01-source-manifest.json",
            "02-screen-catalog.json",
            "03-readiness-summary.md",
            "04-terminology.md",
            "04-terminology.json",
        ]
        if decision is RerunDecision.SELECTIVE:
            dependent_artifacts.extend(
                f"screens/{item.screen_id}/..." for item in impacted_screens
            )

    return RerunPlan(
        feature_key=feature_key,
        run_id=run_id,
        decision=decision,
        changed_sources=changed_sources,
        impacted_screens=impacted_screens,
        dependent_artifacts=dependent_artifacts,
        escalation_reasons=_dedupe_texts(escalation_reasons),
        warnings=_dedupe_texts(warnings),
    )


def render_rerun_changelog(
    plan: RerunPlan,
    *,
    screens: Sequence[CanonicalScreen] = (),
    readiness: ReadinessSummary | None = None,
) -> str:
    """Render a human-readable changelog for a rerun decision."""

    provisional_screens = provisional_screen_ids(screens, readiness=readiness)
    lines = [
        "# Changelog",
        "",
        f"- Feature key: `{plan.feature_key}`",
        f"- Run id: `{plan.run_id}`",
        f"- Decision: `{plan.decision.value}`",
    ]
    if plan.escalation_reasons:
        lines.append("- Escalation: " + " | ".join(plan.escalation_reasons))
    if plan.warnings:
        lines.append("- Warnings: " + " | ".join(plan.warnings[:3]))

    lines.extend(["", "## Changed Sources", ""])
    if plan.changed_sources:
        for diff in plan.changed_sources:
            lines.append(f"- `{diff.source_key}`: {_inline_list(diff.summary)}")
            if diff.related_screens:
                lines.append(f"  related screens: {_inline_code_list(diff.related_screens)}")
    else:
        lines.append("- No source-content changes were detected against the persisted baseline.")

    lines.extend(["", "## Impacted Screens", ""])
    if plan.impacted_screens:
        for screen in plan.impacted_screens:
            lines.append(
                "- `{screen_id}` sources={sources} reasons={reasons}".format(
                    screen_id=screen.screen_id,
                    sources=_inline_code_list(screen.source_keys),
                    reasons=_inline_list(screen.reasons),
                )
            )
    else:
        lines.append("- No screen-specific rerun work is required.")

    lines.extend(["", "## Dependent Summaries", ""])
    if plan.dependent_artifacts:
        lines.extend(f"- `{artifact}`" for artifact in plan.dependent_artifacts)
    else:
        lines.append("- No dependent summary artifacts need regeneration.")

    lines.extend(["", "## What Remains Provisional", ""])
    if provisional_screens:
        lines.append(f"- Screens still carrying provisional or downgraded state: {_inline_code_list(provisional_screens)}")
    elif readiness is not None and readiness.required_assumptions:
        lines.append(f"- FE-first assumptions still recorded: {len(readiness.required_assumptions)}")
    else:
        lines.append("- No currently persisted screens are marked provisional by the available readiness/canonical state.")

    return "\n".join(lines).rstrip() + "\n"


def provisional_screen_ids(
    screens: Sequence[CanonicalScreen],
    *,
    readiness: ReadinessSummary | None = None,
) -> list[str]:
    """Return screen ids that still carry provisional or degraded semantics."""

    readiness_by_screen = {item.screen_id: item for item in readiness.screens} if readiness else {}
    provisional: list[str] = []
    for screen in screens:
        has_uncertain_fact = any(
            fact.status is not FactStatus.CONFIRMED
            for fact in (*screen.shared_facts, *screen.fe_facts, *screen.be_facts)
        )
        screen_readiness = readiness_by_screen.get(screen.screen_id)
        if has_uncertain_fact or (
            screen_readiness is not None and (not screen_readiness.fe_ready or not screen_readiness.be_ready)
        ):
            provisional.append(screen.screen_id)
    return sorted(set(provisional))


def _build_source_diff(
    *,
    source_key: str,
    source_type: SourceType | None,
    previous_snapshot: SourceSnapshotText | None,
    current_snapshot: SourceSnapshotText | None,
    previous_terms: set[str],
    current_terms: set[str],
) -> SourceSnapshotDiff | None:
    previous_text = previous_snapshot.content if previous_snapshot is not None else ""
    current_text = current_snapshot.content if current_snapshot is not None else ""
    previous_lines = previous_text.splitlines()
    current_lines = current_text.splitlines()
    matcher = SequenceMatcher(a=previous_lines, b=current_lines)
    changed_span_count = sum(1 for tag, *_ in matcher.get_opcodes() if tag != "equal")
    similarity = matcher.ratio() if previous_lines or current_lines else 1.0
    added_headings = sorted(set(_extract_headings(current_text)).difference(_extract_headings(previous_text)))
    removed_headings = sorted(set(_extract_headings(previous_text)).difference(_extract_headings(current_text)))
    added_terms = sorted(current_terms.difference(previous_terms), key=str.casefold)
    removed_terms = sorted(previous_terms.difference(current_terms), key=str.casefold)
    hash_changed = (
        previous_snapshot is None
        or current_snapshot is None
        or previous_snapshot.record.content_hash != current_snapshot.record.content_hash
    )
    changed = (
        previous_snapshot is None
        or current_snapshot is None
        or hash_changed
        or bool(added_headings or removed_headings or added_terms or removed_terms)
    )
    if not changed:
        return None

    summary: list[str] = []
    if previous_snapshot is None:
        summary.append("new snapshot captured")
    elif current_snapshot is None:
        summary.append("latest snapshot is unavailable")
    if hash_changed:
        summary.append("content hash changed")
    if added_headings or removed_headings:
        summary.append(
            f"heading delta +{len(added_headings)}/-{len(removed_headings)}"
        )
    if changed_span_count:
        summary.append(f"{changed_span_count} changed span(s)")
    if added_terms or removed_terms:
        summary.append(
            "terminology delta "
            f"+{len(added_terms)}/-{len(removed_terms)}"
        )

    return SourceSnapshotDiff(
        source_key=source_key,
        source_type=source_type,
        previous_snapshot_id=previous_snapshot.record.snapshot_id if previous_snapshot else None,
        current_snapshot_id=current_snapshot.record.snapshot_id if current_snapshot else None,
        previous_content_hash=previous_snapshot.record.content_hash if previous_snapshot else None,
        current_content_hash=current_snapshot.record.content_hash if current_snapshot else None,
        hash_changed=hash_changed,
        changed_span_count=changed_span_count,
        similarity=similarity,
        added_headings=added_headings,
        removed_headings=removed_headings,
        added_terms=added_terms,
        removed_terms=removed_terms,
        summary=summary,
    )


def _source_screen_links(
    *,
    previous_manifest: SourceManifestDocument,
    current_manifest: SourceManifestDocument,
    previous_screen_catalog: ScreenCatalogDocument,
    current_screen_catalog: ScreenCatalogDocument,
    previous_canonical_screens: Mapping[str, CanonicalScreen],
    matrix_source_links: Mapping[str, Sequence[str]],
) -> dict[str, set[str]]:
    links: dict[str, set[str]] = defaultdict(set)

    for manifest in (previous_manifest, current_manifest):
        for row in manifest.rows:
            for screen_id in row.used_in_screens:
                links[row.source_key].add(screen_id)

    for catalog in (previous_screen_catalog, current_screen_catalog):
        for screen in catalog.screens:
            for source_key in set(screen.related_sources) | _screen_evidence_source_keys(screen):
                links[source_key].add(screen.screen_id)

    for screen_id, screen in previous_canonical_screens.items():
        for source_key in _canonical_screen_source_keys(screen):
            links[source_key].add(screen_id)

    for screen_id, source_keys in matrix_source_links.items():
        for source_key in source_keys:
            links[source_key].add(screen_id)

    return links


def _term_screen_links(
    *,
    previous_screen_catalog: ScreenCatalogDocument,
    current_screen_catalog: ScreenCatalogDocument,
    previous_canonical_screens: Mapping[str, CanonicalScreen],
    terminology: tuple[TerminologyDocument, TerminologyDocument],
) -> dict[str, set[str]]:
    previous_terms, current_terms = terminology
    all_terms = {
        term
        for document in (previous_terms, current_terms)
        for term in _all_terminology_terms(document)
    }
    screen_blobs: dict[str, str] = {}
    for catalog in (previous_screen_catalog, current_screen_catalog):
        for screen in catalog.screens:
            blob = screen_blobs.get(screen.screen_id, "")
            screen_blobs[screen.screen_id] = blob + "\n" + _screen_blob(screen)
    for screen_id, screen in previous_canonical_screens.items():
        blob = screen_blobs.get(screen_id, "")
        screen_blobs[screen_id] = blob + "\n" + _canonical_blob(screen)

    links: dict[str, set[str]] = defaultdict(set)
    for term in sorted(all_terms, key=str.casefold):
        needle = _normalize_text(term)
        if not needle:
            continue
        for screen_id, blob in screen_blobs.items():
            if needle in blob:
                links[term].add(screen_id)
    return links


def _changed_screen_catalog_ids(
    previous: ScreenCatalogDocument,
    current: ScreenCatalogDocument,
) -> set[str]:
    changed: set[str] = set()
    previous_by_id = {screen.screen_id: screen for screen in previous.screens}
    current_by_id = {screen.screen_id: screen for screen in current.screens}
    for screen_id in set(previous_by_id) | set(current_by_id):
        if screen_id not in previous_by_id or screen_id not in current_by_id:
            changed.add(screen_id)
            continue
        if previous_by_id[screen_id].model_dump(mode="json") != current_by_id[screen_id].model_dump(mode="json"):
            changed.add(screen_id)
    return changed


def _screen_catalog_changed_materially(
    previous: ScreenCatalogDocument,
    current: ScreenCatalogDocument,
    *,
    changed_screen_ids: set[str],
) -> bool:
    previous_ids = {screen.screen_id for screen in previous.screens}
    current_ids = {screen.screen_id for screen in current.screens}
    if previous_ids != current_ids:
        return True
    if not changed_screen_ids:
        return False
    total = max(len(current_ids), 1)
    return len(changed_screen_ids) >= max(2, ceil(total * 0.6))


def _cross_cutting_terminology_change(
    *,
    changed_terms: Sequence[str],
    term_links: Mapping[str, set[str]],
    total_screens: int,
) -> bool:
    if total_screens <= 1 or len(changed_terms) < 2:
        return False
    affected = {
        screen_id
        for term in changed_terms
        for screen_id in term_links.get(term, set())
    }
    return len(affected) >= max(2, ceil(total_screens * 0.6))


def _source_quality_degraded(row: Any) -> bool:
    parse_quality = getattr(row, "parse_quality", None)
    parse_quality_value = getattr(parse_quality, "value", str(parse_quality or ""))
    status = getattr(row, "status", None)
    status_value = getattr(status, "value", str(status or ""))
    return parse_quality_value in {"LOW", "FAILED"} or status_value in {"DEGRADED", "FAILED"}


def _is_primary_requirement_replaced(*, diff: SourceSnapshotDiff, row: Any) -> bool:
    if row is None or getattr(row, "source_type", None) is not SourceType.PRIMARY_REQUIREMENT:
        return False
    if not diff.hash_changed:
        return False
    has_heading_overlap = bool(set(diff.added_headings) & set(diff.removed_headings))
    return diff.similarity < 0.5 or (
        diff.changed_span_count >= 3 and not has_heading_overlap and (diff.added_headings or diff.removed_headings)
    )


def _terms_by_source(document: TerminologyDocument) -> tuple[dict[str, set[str]], set[str]]:
    by_source: dict[str, set[str]] = defaultdict(set)
    all_terms: set[str] = set()
    for entry in document.entries:
        terms = {entry.standard_term, *entry.aliases}
        all_terms.update(term for term in terms if term)
        source_keys = {item.source_key for item in entry.evidence if item.source_key}
        if not source_keys:
            continue
        for source_key in source_keys:
            by_source[source_key].update(terms)
    return by_source, all_terms


def _all_terminology_terms(document: TerminologyDocument) -> set[str]:
    terms: set[str] = set()
    for entry in document.entries:
        terms.add(entry.standard_term)
        terms.update(entry.aliases)
    return {term for term in terms if term}


def _extract_headings(text: str) -> list[str]:
    headings: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and _HEADING_RE.match(line):
            headings.append(line.removeprefix("#").strip())
    return headings


def _source_reason_text(diff: SourceSnapshotDiff) -> str:
    if diff.summary:
        return f"{diff.source_key}: {', '.join(diff.summary[:3])}"
    return f"{diff.source_key}: snapshot changed"


def _screen_evidence_source_keys(screen: ScreenCatalogEntry) -> set[str]:
    return {item.source_key for item in screen.evidence if item.source_key}


def _canonical_source_keys(
    canonical_screens: Mapping[str, CanonicalScreen] | None,
    screen_id: str,
) -> set[str]:
    if not canonical_screens or screen_id not in canonical_screens:
        return set()
    return _canonical_screen_source_keys(canonical_screens[screen_id])


def _canonical_screen_source_keys(screen: CanonicalScreen) -> set[str]:
    source_keys: set[str] = set()
    for fact in (*screen.shared_facts, *screen.fe_facts, *screen.be_facts):
        source_keys.update(item.source_key for item in fact.evidence if item.source_key)
    for gap in screen.missing_info:
        source_keys.update(item.source_key for item in gap.evidence if item.source_key)
    for question in screen.open_questions:
        source_keys.update(item.source_key for item in question.evidence if item.source_key)
    for contradiction in screen.contradictions:
        for claim in contradiction.claims:
            source_keys.update(item.source_key for item in claim.evidence if item.source_key)
    return source_keys


def _screen_blob(screen: ScreenCatalogEntry) -> str:
    text_parts = [
        screen.screen_id,
        screen.screen_name,
        screen.purpose,
        *screen.roles,
        *screen.entry_points,
        *screen.exit_points,
        *screen.main_actions,
        *screen.dependencies,
    ]
    return _normalize_text(" ".join(text_parts))


def _canonical_blob(screen: CanonicalScreen) -> str:
    text_parts: list[str] = [screen.screen_id]
    for fact in (*screen.shared_facts, *screen.fe_facts, *screen.be_facts):
        text_parts.append(fact.fact_id)
        text_parts.append(fact.category)
        text_parts.append(_flatten_value(fact.value))
        if fact.note:
            text_parts.append(fact.note)
        if fact.rationale:
            text_parts.append(fact.rationale)
    for gap in screen.missing_info:
        text_parts.append(gap.summary)
    for question in screen.open_questions:
        text_parts.append(question.summary)
    return _normalize_text(" ".join(text_parts))


def _flatten_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(_flatten_value(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " ".join(_flatten_value(item) for item in value)
    return str(value or "")


def _normalize_text(value: str) -> str:
    return _NON_WORD_RE.sub(" ", value.casefold()).strip()


def _inline_list(values: Sequence[str]) -> str:
    return ", ".join(values) if values else "none"


def _inline_code_list(values: Sequence[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def _dedupe_texts(values: Sequence[str]) -> list[str]:
    deduped: dict[str, None] = {}
    for value in values:
        text = value.strip()
        if text:
            deduped.setdefault(text, None)
    return list(deduped)


__all__ = [
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "ImpactedScreen",
    "RerunDecision",
    "RerunPlan",
    "SourceSnapshotDiff",
    "SourceSnapshotText",
    "attach_source_screen_usage",
    "build_rerun_plan",
    "provisional_screen_ids",
    "render_rerun_changelog",
]
