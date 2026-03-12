"""Extraction boundary for deterministic BA fact gathering."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, TypeAlias

from .models import (
    CanonicalFact,
    CanonicalScreen,
    ContradictionClaim,
    ContradictionRecord,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    GapKind,
    GapRecord,
    GapSeverity,
    ParseQuality,
    QuestionRecord,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    SourceManifestDocument,
    SourceSnapshotRecord,
    TerminologyDocument,
    TerminologyEntry,
    WorkflowMode,
)
from .prompts import BAPromptTemplate, get_ba_prompt

MODULE_PURPOSE = "Own canonical extraction from normalized NotebookLM evidence into BA facts."

OWNS = (
    "Evidence-to-fact extraction stages",
    "Canonicalization rules over adapter outputs",
    "Intermediate extraction payloads used by rendering and validation",
)

MUST_NOT_OWN = (
    "NotebookLM transport details",
    "Filesystem run-store implementation",
    "Final output rendering",
    "MCP tool registration",
)

JSONPayload: TypeAlias = dict[str, Any] | list[Any]
StructuredAskCallable: TypeAlias = Callable[..., Awaitable[Any]]

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_SIMPLE_JSON_FIELD_RE = re.compile(
    r'"([^"\\]+)"\s*:\s*("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)'
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TERMINOLOGY_SCHEMA_CONTRACT = """{
  "entries": [
    {
      "standard_term": "canonical business term",
      "aliases": ["supported synonym or shorthand"],
      "semantic_notes": ["what the term means in this feature"],
      "ambiguity_flags": ["why the term remains unresolved, if applicable"]
    }
  ]
}"""
_SCREEN_CATALOG_SCHEMA_CONTRACT = """{
  "screens": [
    {
      "screen_name": "human-readable screen label",
      "purpose": "why this screen exists",
      "roles": ["actor or persona"],
      "entry_points": ["how the screen is reached"],
      "exit_points": ["where the flow can go next"],
      "main_actions": ["primary user actions"],
      "dependencies": ["cross-screen or backend dependencies"],
      "related_sources": ["source identifier or title"],
      "open_questions": ["unresolved questions to preserve explicitly"]
    }
  ]
}"""
_CANONICAL_SCREEN_SCHEMA_CONTRACT = """{
  "shared_facts": [{"category": "business rule", "value": "fact value", "status": "CONFIRMED"}],
  "fe_facts": [{"category": "field", "value": "UI behavior", "status": "PROVISIONAL"}],
  "be_facts": [{"category": "endpoint", "value": "/resource", "status": "CONFIRMED"}],
  "dependencies": ["dependency or related screen"],
  "contradictions": [
    {
      "summary": "what conflicts",
      "claims": [{"claim": "first claim"}, {"claim": "second claim"}],
      "open_question": "what would resolve it"
    }
  ],
  "missing_info": [{"kind": "MISSING_REQUIREMENT_DETAIL", "summary": "what is still missing"}],
  "open_questions": ["unresolved question"],
  "quality_summary": {"parse_quality": "HIGH", "notes": ["quality note"], "degraded": false}
}"""


class StructuredParseQuality(str, Enum):
    EXACT = "EXACT"
    FENCED_JSON = "FENCED_JSON"
    SPAN_EXTRACTED = "SPAN_EXTRACTED"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class StructuredParseResult:
    raw_text: str
    parse_quality: StructuredParseQuality
    payload: JSONPayload | None
    partial_payload: dict[str, Any] | None = None
    selected_json_text: str | None = None


@dataclass(frozen=True, slots=True)
class StructuredAskResult:
    prompt_name: str
    prompt_text: str
    raw_text: str
    parse_quality: StructuredParseQuality
    payload: JSONPayload | None
    partial_payload: dict[str, Any] | None
    conversation_id: str | None
    turn_number: int | None
    is_follow_up: bool | None
    citations: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceNormalizationResult:
    evidence: tuple[EvidenceRef, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TerminologyExtractionResult:
    document: TerminologyDocument
    raw_text: str
    parse_quality: StructuredParseQuality
    warnings: tuple[str, ...] = ()
    partial_payload: dict[str, Any] | None = None
    conversation_id: str | None = None
    turn_number: int | None = None
    is_follow_up: bool | None = None


@dataclass(frozen=True, slots=True)
class ScreenCatalogExtractionResult:
    document: ScreenCatalogDocument
    raw_text: str
    parse_quality: StructuredParseQuality
    warnings: tuple[str, ...] = ()
    partial_payload: dict[str, Any] | None = None
    conversation_id: str | None = None
    turn_number: int | None = None
    is_follow_up: bool | None = None


@dataclass(frozen=True, slots=True)
class CanonicalScreenExtractionResult:
    screen: CanonicalScreen
    raw_text: str
    parse_quality: StructuredParseQuality
    warnings: tuple[str, ...] = ()
    partial_payload: dict[str, Any] | None = None
    conversation_id: str | None = None
    turn_number: int | None = None
    is_follow_up: bool | None = None


def parse_structured_response(raw_text: str) -> StructuredParseResult:
    """Apply the deterministic structured-response parsing ladder."""
    stripped = raw_text.strip()

    parsed = _try_json_payload(stripped)
    if parsed is not None:
        return StructuredParseResult(
            raw_text=raw_text,
            parse_quality=StructuredParseQuality.EXACT,
            payload=parsed,
            selected_json_text=stripped,
        )

    fenced_payload, fenced_text = _extract_fenced_json(stripped)
    if fenced_payload is not None:
        return StructuredParseResult(
            raw_text=raw_text,
            parse_quality=StructuredParseQuality.FENCED_JSON,
            payload=fenced_payload,
            selected_json_text=fenced_text,
        )

    span_payload, span_text = _extract_first_valid_json_span(stripped)
    if span_payload is not None:
        return StructuredParseResult(
            raw_text=raw_text,
            parse_quality=StructuredParseQuality.SPAN_EXTRACTED,
            payload=span_payload,
            selected_json_text=span_text,
        )

    return StructuredParseResult(
        raw_text=raw_text,
        parse_quality=StructuredParseQuality.DEGRADED,
        payload=None,
        partial_payload=_safe_partial_payload(stripped),
    )


async def ask_structured(
    ask_callable: StructuredAskCallable,
    *,
    prompt_name: str,
    prompt_context: Mapping[str, Any],
    source_ids: Sequence[str] | None = None,
    conversation_id: str | None = None,
    prompt_template: BAPromptTemplate | None = None,
) -> StructuredAskResult:
    """Render a named prompt, execute an ask callable, and parse the result deterministically."""
    template = prompt_template or get_ba_prompt(prompt_name)
    prompt_text = template.render(**dict(prompt_context))
    response = await ask_callable(
        prompt_text,
        source_ids=list(source_ids) if source_ids is not None else None,
        conversation_id=conversation_id,
    )
    parsed = parse_structured_response(str(getattr(response, "answer", "")))
    citations = tuple(getattr(response, "citations", ()) or ())
    return StructuredAskResult(
        prompt_name=template.name,
        prompt_text=prompt_text,
        raw_text=parsed.raw_text,
        parse_quality=parsed.parse_quality,
        payload=parsed.payload,
        partial_payload=parsed.partial_payload,
        conversation_id=getattr(response, "conversation_id", None),
        turn_number=getattr(response, "turn_number", None),
        is_follow_up=getattr(response, "is_follow_up", None),
        citations=citations,
    )


def normalize_citations_to_evidence(
    citations: Sequence[Any],
    *,
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord] = (),
) -> EvidenceNormalizationResult:
    """Normalize citation variants into stable snapshot-linked ``EvidenceRef`` objects."""
    link_by_identifier = _build_evidence_link_index(manifest, snapshots)
    evidence: list[EvidenceRef] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()

    for index, citation in enumerate(citations, start=1):
        source_identifier = _citation_source_identifier(citation)
        if not source_identifier:
            warnings.append(f"citation[{index}] missing source identifier")
            continue

        link = link_by_identifier.get(source_identifier)
        if link is None:
            warnings.append(f"citation[{index}] source '{source_identifier}' is not present in manifest")
            continue
        if not link.snapshot_id:
            warnings.append(
                f"citation[{index}] source '{source_identifier}' has no linked snapshot_id"
            )
            continue

        quote = _citation_field(citation, "quote", "cited_text")
        locator = _citation_locator(citation)
        if not quote and not locator:
            warnings.append(
                f"citation[{index}] source '{source_identifier}' is missing quote and locator"
            )
            continue

        item = EvidenceRef(
            source_key=link.source_key,
            snapshot_id=link.snapshot_id,
            locator=locator,
            quote=quote,
        )
        fingerprint = (item.source_key, item.snapshot_id, item.locator, item.quote)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        evidence.append(item)

    return EvidenceNormalizationResult(evidence=tuple(evidence), warnings=tuple(warnings))


async def extract_terminology_document(
    ask_callable: StructuredAskCallable,
    *,
    feature_key: str,
    run_id: str,
    manifest: SourceManifestDocument,
    source_scope: str,
    source_ids: Sequence[str] | None = None,
    snapshots: Sequence[SourceSnapshotRecord] = (),
    conversation_id: str | None = None,
) -> TerminologyExtractionResult:
    """Extract and normalize a terminology document from structured BA output."""
    ask_result = await ask_structured(
        ask_callable,
        prompt_name="terminology_extract",
        prompt_context={
            "feature_key": feature_key,
            "source_scope": source_scope,
            "schema_contract": _TERMINOLOGY_SCHEMA_CONTRACT,
        },
        source_ids=source_ids,
        conversation_id=conversation_id,
    )
    evidence_result = normalize_citations_to_evidence(
        ask_result.citations,
        manifest=manifest,
        snapshots=snapshots,
    )
    document, build_warnings = _build_terminology_document(
        ask_result.payload,
        partial_payload=ask_result.partial_payload,
        feature_key=feature_key,
        run_id=run_id,
        shared_evidence=evidence_result.evidence,
        manifest=manifest,
        snapshots=snapshots,
    )
    return TerminologyExtractionResult(
        document=document,
        raw_text=ask_result.raw_text,
        parse_quality=ask_result.parse_quality,
        warnings=(*evidence_result.warnings, *build_warnings),
        partial_payload=ask_result.partial_payload,
        conversation_id=ask_result.conversation_id,
        turn_number=ask_result.turn_number,
        is_follow_up=ask_result.is_follow_up,
    )


def build_terminology_lookup(document: TerminologyDocument) -> dict[str, str]:
    """Build an alias-safe lookup from normalized vocabulary to canonical terms."""
    ambiguous_aliases = _ambiguous_alias_keys(document.entries)
    lookup: dict[str, str] = {}

    for entry in document.entries:
        standard_key = _normalize_term_key(entry.standard_term)
        if standard_key:
            lookup[standard_key] = entry.standard_term
        for alias in entry.aliases:
            alias_key = _normalize_term_key(alias)
            if alias_key and alias_key not in ambiguous_aliases:
                lookup.setdefault(alias_key, entry.standard_term)

    return lookup


def canonicalize_term(term: str, terminology: TerminologyDocument) -> str | None:
    """Resolve a freeform term or alias to the canonical terminology entry."""
    term_key = _normalize_term_key(term)
    if not term_key:
        return None
    return build_terminology_lookup(terminology).get(term_key)


async def extract_screen_catalog_document(
    ask_callable: StructuredAskCallable,
    *,
    feature_key: str,
    run_id: str,
    manifest: SourceManifestDocument,
    source_scope: str,
    terminology: TerminologyDocument | None = None,
    source_ids: Sequence[str] | None = None,
    snapshots: Sequence[SourceSnapshotRecord] = (),
    prior_catalog: ScreenCatalogDocument | None = None,
    candidate_screen_hints: Sequence[str] = (),
    conversation_id: str | None = None,
) -> ScreenCatalogExtractionResult:
    """Extract and normalize the stable screen catalog for a feature run."""
    scope_text = source_scope
    if candidate_screen_hints:
        scope_text = (
            f"{source_scope}\nCandidate screen hints: "
            + ", ".join(_sorted_texts(candidate_screen_hints))
        )
    ask_result = await ask_structured(
        ask_callable,
        prompt_name="screen_catalog_extract",
        prompt_context={
            "feature_key": feature_key,
            "source_scope": scope_text,
            "schema_contract": _SCREEN_CATALOG_SCHEMA_CONTRACT,
        },
        source_ids=source_ids,
        conversation_id=conversation_id,
    )
    evidence_result = normalize_citations_to_evidence(
        ask_result.citations,
        manifest=manifest,
        snapshots=snapshots,
    )
    document, build_warnings = _build_screen_catalog_document(
        ask_result.payload,
        partial_payload=ask_result.partial_payload,
        feature_key=feature_key,
        run_id=run_id,
        shared_evidence=evidence_result.evidence,
        manifest=manifest,
        snapshots=snapshots,
        terminology=terminology,
        prior_catalog=prior_catalog,
    )
    return ScreenCatalogExtractionResult(
        document=document,
        raw_text=ask_result.raw_text,
        parse_quality=ask_result.parse_quality,
        warnings=(*evidence_result.warnings, *build_warnings),
        partial_payload=ask_result.partial_payload,
        conversation_id=ask_result.conversation_id,
        turn_number=ask_result.turn_number,
        is_follow_up=ask_result.is_follow_up,
    )


async def extract_canonical_screen(
    ask_callable: StructuredAskCallable,
    *,
    feature_key: str,
    run_id: str,
    screen: ScreenCatalogEntry,
    manifest: SourceManifestDocument,
    mode: WorkflowMode,
    source_scope: str,
    terminology: TerminologyDocument | None = None,
    source_ids: Sequence[str] | None = None,
    snapshots: Sequence[SourceSnapshotRecord] = (),
    conversation_id: str | None = None,
    concern_area: str | None = None,
) -> CanonicalScreenExtractionResult:
    """Extract and normalize the canonical truth layer for a single screen."""
    ask_result = await ask_structured(
        ask_callable,
        prompt_name="canonical_screen_extract",
        prompt_context={
            "feature_key": feature_key,
            "screen_id": screen.screen_id,
            "concern_area": concern_area
            or f"{screen.purpose}\nCapture shared, FE, and BE facts plus contradictions and missing info.",
            "source_scope": source_scope,
            "schema_contract": _CANONICAL_SCREEN_SCHEMA_CONTRACT,
        },
        source_ids=source_ids,
        conversation_id=conversation_id,
    )
    evidence_result = normalize_citations_to_evidence(
        ask_result.citations,
        manifest=manifest,
        snapshots=snapshots,
    )
    canonical_screen, build_warnings = _build_canonical_screen(
        ask_result.payload,
        partial_payload=ask_result.partial_payload,
        feature_key=feature_key,
        run_id=run_id,
        screen=screen,
        mode=mode,
        shared_evidence=evidence_result.evidence,
        manifest=manifest,
        snapshots=snapshots,
        terminology=terminology,
        response_parse_quality=ask_result.parse_quality,
    )
    return CanonicalScreenExtractionResult(
        screen=canonical_screen,
        raw_text=ask_result.raw_text,
        parse_quality=ask_result.parse_quality,
        warnings=(*evidence_result.warnings, *build_warnings),
        partial_payload=ask_result.partial_payload,
        conversation_id=ask_result.conversation_id,
        turn_number=ask_result.turn_number,
        is_follow_up=ask_result.is_follow_up,
    )


def _try_json_payload(candidate: str) -> JSONPayload | None:
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _extract_fenced_json(text: str) -> tuple[JSONPayload | None, str | None]:
    for match in _JSON_FENCE_RE.finditer(text):
        candidate = match.group(1).strip()
        parsed = _try_json_payload(candidate)
        if parsed is not None:
            return parsed, candidate
    return None, None


def _extract_first_valid_json_span(text: str) -> tuple[JSONPayload | None, str | None]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            parsed, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed, text[index : index + end]
    return None, None


def _safe_partial_payload(text: str) -> dict[str, Any] | None:
    fields: dict[str, Any] = {}
    for key, value in _SIMPLE_JSON_FIELD_RE.findall(text):
        try:
            fields[key] = json.loads(value)
        except json.JSONDecodeError:
            continue
    return fields or None


@dataclass(frozen=True, slots=True)
class _EvidenceLink:
    source_key: str
    snapshot_id: str | None


def _build_terminology_document(
    payload: JSONPayload | None,
    *,
    partial_payload: dict[str, Any] | None,
    feature_key: str,
    run_id: str,
    shared_evidence: Sequence[EvidenceRef],
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord],
) -> tuple[TerminologyDocument, tuple[str, ...]]:
    candidate_payload = _terminology_payload(payload, partial_payload)
    entry_payloads = _terminology_entry_payloads(candidate_payload)
    warnings = (
        _coerce_string_list(candidate_payload, "warnings")
        if isinstance(candidate_payload, Mapping)
        else []
    )

    if not entry_payloads:
        warnings.append("no terminology entries found in structured response payload")
        return (
            TerminologyDocument(
                run_id=run_id,
                feature_key=feature_key,
            ),
            tuple(warnings),
        )

    merged_entries: dict[str, TerminologyEntry] = {}
    downgraded_alias_merge = False

    for index, raw_entry in enumerate(entry_payloads, start=1):
        if not isinstance(raw_entry, Mapping):
            warnings.append(f"entry[{index}] is not a mapping")
            continue

        standard_term = _first_text(raw_entry, "standard_term", "canonical_term", "term", "name")
        if not standard_term:
            warnings.append(f"entry[{index}] missing standard_term")
            continue

        entry_evidence, evidence_warnings = _entry_evidence(
            raw_entry,
            shared_evidence=shared_evidence,
            manifest=manifest,
            snapshots=snapshots,
        )
        warnings.extend(f"entry[{index}]: {warning}" for warning in evidence_warnings)

        aliases = _coerce_string_list(raw_entry, "aliases", "synonyms", "alternate_terms")
        semantic_notes = _coerce_string_list(raw_entry, "semantic_notes", "notes", "meanings")
        ambiguity_flags = _coerce_string_list(
            raw_entry,
            "ambiguity_flags",
            "ambiguities",
            "open_questions",
        )

        if aliases and not entry_evidence:
            ambiguity_flags = _merge_text_lists(
                ambiguity_flags,
                [f"alias_requires_evidence:{alias}" for alias in aliases],
            )
            aliases = []
            downgraded_alias_merge = True

        normalized_entry = TerminologyEntry(
            standard_term=standard_term,
            aliases=aliases,
            semantic_notes=semantic_notes,
            evidence=list(entry_evidence),
            ambiguity_flags=ambiguity_flags,
        )
        entry_key = _normalize_term_key(normalized_entry.standard_term)
        existing = merged_entries.get(entry_key)
        merged_entries[entry_key] = (
            normalized_entry
            if existing is None
            else _merge_terminology_entry(existing, normalized_entry)
        )

    if downgraded_alias_merge:
        warnings.append(
            "one or more alias merges were downgraded to ambiguity flags because no normalized evidence was available"
        )

    finalized_entries = _finalize_terminology_entries(merged_entries.values())
    return (
        TerminologyDocument(
            run_id=run_id,
            feature_key=feature_key,
            entries=list(finalized_entries),
        ),
        tuple(warnings),
    )


def _build_screen_catalog_document(
    payload: JSONPayload | None,
    *,
    partial_payload: dict[str, Any] | None,
    feature_key: str,
    run_id: str,
    shared_evidence: Sequence[EvidenceRef],
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord],
    terminology: TerminologyDocument | None,
    prior_catalog: ScreenCatalogDocument | None,
) -> tuple[ScreenCatalogDocument, tuple[str, ...]]:
    candidate_payload = _screen_catalog_payload(payload, partial_payload)
    screen_payloads = _screen_entry_payloads(candidate_payload)
    warnings = (
        _coerce_string_list(candidate_payload, "warnings")
        if isinstance(candidate_payload, Mapping)
        else []
    )
    if not screen_payloads:
        warnings.append("no screen entries found in structured response payload")
        return (
            ScreenCatalogDocument(
                run_id=run_id,
                feature_key=feature_key,
            ),
            tuple(warnings),
        )

    source_key_index = _source_key_index(manifest)
    prior_name_index = (
        {_normalize_term_key(screen.screen_name): screen for screen in prior_catalog.screens}
        if prior_catalog is not None
        else {}
    )
    used_ids = {screen.screen_id for screen in prior_catalog.screens} if prior_catalog is not None else set()
    screens: list[ScreenCatalogEntry] = []

    for index, raw_entry in enumerate(screen_payloads, start=1):
        if not isinstance(raw_entry, Mapping):
            warnings.append(f"screen[{index}] is not a mapping")
            continue

        screen_name = _first_text(raw_entry, "screen_name", "name", "title")
        purpose = _first_text(raw_entry, "purpose", "summary", "description")
        if not screen_name:
            warnings.append(f"screen[{index}] missing screen_name")
            continue
        if not purpose:
            warnings.append(f"screen[{index}] missing purpose")
            continue

        entry_evidence, evidence_warnings = _entry_evidence(
            raw_entry,
            shared_evidence=shared_evidence,
            manifest=manifest,
            snapshots=snapshots,
        )
        warnings.extend(f"screen[{index}]: {warning}" for warning in evidence_warnings)
        if not entry_evidence:
            warnings.append(
                f"screen[{index}] '{screen_name}' has no normalized evidence; catalog entry remains provisional"
            )

        screen_id = _stable_screen_id(
            screen_name,
            purpose=purpose,
            prior_match=prior_name_index.get(_normalize_term_key(screen_name)),
            used_ids=used_ids,
        )
        used_ids.add(screen_id)

        screens.append(
            ScreenCatalogEntry(
                screen_id=screen_id,
                screen_name=screen_name.strip(),
                purpose=purpose.strip(),
                roles=_canonicalize_catalog_values(
                    _coerce_string_list(raw_entry, "roles", "actors"),
                    terminology,
                ),
                entry_points=_canonicalize_catalog_values(
                    _coerce_string_list(raw_entry, "entry_points", "triggers"),
                    terminology,
                ),
                exit_points=_canonicalize_catalog_values(
                    _coerce_string_list(raw_entry, "exit_points", "outcomes"),
                    terminology,
                ),
                main_actions=_canonicalize_catalog_values(
                    _coerce_string_list(raw_entry, "main_actions", "actions"),
                    terminology,
                ),
                dependencies=_canonicalize_catalog_values(
                    _coerce_string_list(raw_entry, "dependencies", "depends_on"),
                    terminology,
                ),
                related_sources=_related_source_keys(
                    raw_entry,
                    source_key_index=source_key_index,
                    evidence=entry_evidence,
                ),
                evidence=list(_sorted_evidence(entry_evidence)),
                open_questions=_coerce_question_records(
                    raw_entry,
                    screen_id=screen_id,
                    evidence=entry_evidence,
                ),
            )
        )

    return (
        ScreenCatalogDocument(
            run_id=run_id,
            feature_key=feature_key,
            screens=sorted(screens, key=lambda item: item.screen_id),
        ),
        tuple(warnings),
    )


def _build_canonical_screen(
    payload: JSONPayload | None,
    *,
    partial_payload: dict[str, Any] | None,
    feature_key: str,
    run_id: str,
    screen: ScreenCatalogEntry,
    mode: WorkflowMode,
    shared_evidence: Sequence[EvidenceRef],
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord],
    terminology: TerminologyDocument | None,
    response_parse_quality: StructuredParseQuality,
) -> tuple[CanonicalScreen, tuple[str, ...]]:
    candidate_payload = _canonical_payload(payload, partial_payload)
    warnings = (
        _coerce_string_list(candidate_payload, "warnings")
        if isinstance(candidate_payload, Mapping)
        else []
    )

    shared_facts, shared_warnings = _coerce_canonical_facts(
        _payload_items(candidate_payload, "shared_facts"),
        domain=FactDomain.SHARED,
        screen_id=screen.screen_id,
        shared_evidence=shared_evidence,
        manifest=manifest,
        snapshots=snapshots,
    )
    fe_facts, fe_warnings = _coerce_canonical_facts(
        _payload_items(candidate_payload, "fe_facts"),
        domain=FactDomain.FE,
        screen_id=screen.screen_id,
        shared_evidence=shared_evidence,
        manifest=manifest,
        snapshots=snapshots,
    )
    be_facts, be_warnings = _coerce_canonical_facts(
        _payload_items(candidate_payload, "be_facts"),
        domain=FactDomain.BE,
        screen_id=screen.screen_id,
        shared_evidence=shared_evidence,
        manifest=manifest,
        snapshots=snapshots,
    )
    contradictions, contradiction_warnings = _coerce_contradictions(
        _payload_items(candidate_payload, "contradictions"),
        screen_id=screen.screen_id,
        shared_evidence=shared_evidence,
        manifest=manifest,
        snapshots=snapshots,
    )
    missing_info, gap_warnings = _coerce_gap_records(
        _payload_items(candidate_payload, "missing_info", "gaps"),
        screen_id=screen.screen_id,
        shared_evidence=shared_evidence,
        manifest=manifest,
        snapshots=snapshots,
    )
    extracted_questions = _coerce_question_records(
        candidate_payload if isinstance(candidate_payload, Mapping) else {},
        screen_id=screen.screen_id,
        evidence=shared_evidence,
    )
    dependencies = _canonicalize_catalog_values(
        _merge_text_lists(
            screen.dependencies,
            _payload_string_list(candidate_payload, "dependencies"),
        ),
        terminology,
    )
    quality_summary = _coerce_quality_summary(
        candidate_payload.get("quality_summary") if isinstance(candidate_payload, Mapping) else None,
        response_parse_quality=response_parse_quality,
    )

    warnings.extend(shared_warnings)
    warnings.extend(fe_warnings)
    warnings.extend(be_warnings)
    warnings.extend(contradiction_warnings)
    warnings.extend(gap_warnings)

    return (
        CanonicalScreen(
            feature_key=feature_key,
            screen_id=screen.screen_id,
            mode=mode,
            run_id=run_id,
            shared_facts=shared_facts,
            fe_facts=fe_facts,
            be_facts=be_facts,
            dependencies=dependencies,
            contradictions=contradictions,
            missing_info=missing_info,
            open_questions=_merge_question_records(screen.open_questions, extracted_questions),
            quality_summary=quality_summary,
        ),
        tuple(warnings),
    )


def _merge_terminology_entry(
    existing: TerminologyEntry,
    incoming: TerminologyEntry,
) -> TerminologyEntry:
    return TerminologyEntry(
        standard_term=existing.standard_term,
        aliases=_merge_text_lists(existing.aliases, incoming.aliases),
        semantic_notes=_merge_text_lists(existing.semantic_notes, incoming.semantic_notes),
        evidence=list(_merge_evidence(existing.evidence, incoming.evidence)),
        ambiguity_flags=_merge_text_lists(existing.ambiguity_flags, incoming.ambiguity_flags),
    )


def _finalize_terminology_entries(
    entries: Sequence[TerminologyEntry],
) -> tuple[TerminologyEntry, ...]:
    alias_owners: dict[str, set[str]] = {}
    for entry in entries:
        entry_key = _normalize_term_key(entry.standard_term)
        for alias in entry.aliases:
            alias_key = _normalize_term_key(alias)
            if alias_key:
                alias_owners.setdefault(alias_key, set()).add(entry_key)

    finalized: list[TerminologyEntry] = []
    for entry in sorted(entries, key=lambda item: _normalize_term_key(item.standard_term)):
        collisions = [
            alias
            for alias in entry.aliases
            if len(alias_owners.get(_normalize_term_key(alias), set())) > 1
        ]
        finalized.append(
            entry.model_copy(
                update={
                    "aliases": _sorted_texts(entry.aliases),
                    "semantic_notes": _sorted_texts(entry.semantic_notes),
                    "ambiguity_flags": _sorted_texts(
                        _merge_text_lists(
                            _sorted_texts(entry.ambiguity_flags),
                            [f"alias_collision:{alias}" for alias in collisions],
                        )
                    ),
                    "evidence": list(_sorted_evidence(entry.evidence)),
                }
            )
        )
    return tuple(finalized)


def _entry_evidence(
    raw_entry: Mapping[str, Any],
    *,
    shared_evidence: Sequence[EvidenceRef],
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord],
) -> tuple[tuple[EvidenceRef, ...], tuple[str, ...]]:
    raw_evidence = raw_entry.get("evidence")
    if isinstance(raw_evidence, Sequence) and not isinstance(raw_evidence, (str, bytes, bytearray)):
        evidence_result = normalize_citations_to_evidence(
            raw_evidence,
            manifest=manifest,
            snapshots=snapshots,
        )
        return evidence_result.evidence, evidence_result.warnings
    # NotebookLM currently exposes citations at the ask-response level, so share that
    # normalized evidence with per-term entries until term-scoped citations exist.
    return tuple(shared_evidence), ()


def _screen_catalog_payload(
    payload: JSONPayload | None,
    partial_payload: dict[str, Any] | None,
) -> Mapping[str, Any] | Sequence[Any]:
    return _terminology_payload(payload, partial_payload)


def _screen_entry_payloads(
    payload: Mapping[str, Any] | Sequence[Any],
) -> list[Any]:
    if isinstance(payload, list):
        return list(payload)
    for key in ("screens", "entries", "catalog"):
        value = payload.get(key)
        if isinstance(value, list):
            return list(value)
    if payload and any(key in payload for key in ("screen_name", "name", "title")):
        return [payload]
    return []


def _canonical_payload(
    payload: JSONPayload | None,
    partial_payload: dict[str, Any] | None,
) -> Mapping[str, Any] | Sequence[Any]:
    return _terminology_payload(payload, partial_payload)


def _payload_items(
    payload: Mapping[str, Any] | Sequence[Any],
    *field_names: str,
) -> list[Any]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return list(payload)
    if not isinstance(payload, Mapping):
        return []
    for field_name in field_names:
        value = payload.get(field_name)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return list(value)
        if isinstance(value, Mapping):
            return [value]
    return []


def _payload_string_list(
    payload: Mapping[str, Any] | Sequence[Any],
    *field_names: str,
) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    return _coerce_string_list(payload, *field_names)


def _terminology_payload(
    payload: JSONPayload | None,
    partial_payload: dict[str, Any] | None,
) -> Mapping[str, Any] | Sequence[Any]:
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, list):
        return payload
    if partial_payload:
        return partial_payload
    return {}


def _terminology_entry_payloads(
    payload: Mapping[str, Any] | Sequence[Any],
) -> list[Any]:
    if isinstance(payload, list):
        return list(payload)
    for key in ("entries", "terms", "terminology"):
        value = payload.get(key)
        if isinstance(value, list):
            return list(value)
    if payload and any(
        key in payload
        for key in (
            "standard_term",
            "canonical_term",
            "term",
            "name",
        )
    ):
        return [payload]
    return []


def _coerce_string_list(payload: Mapping[str, Any], *field_names: str) -> list[str]:
    values: list[str] = []
    for field_name in field_names:
        raw = payload.get(field_name)
        if raw is None:
            continue
        if isinstance(raw, str):
            values.append(raw.strip())
            continue
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            values.extend(str(item).strip() for item in raw if str(item).strip())
    return _sorted_texts(values)


def _canonicalize_catalog_values(
    values: Sequence[str],
    terminology: TerminologyDocument | None,
) -> list[str]:
    if terminology is None:
        return _sorted_texts(values)
    normalized = [canonicalize_term(value, terminology) or value for value in values]
    return _sorted_texts(normalized)


def _coerce_canonical_facts(
    raw_facts: Sequence[Any],
    *,
    domain: FactDomain,
    screen_id: str,
    shared_evidence: Sequence[EvidenceRef],
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord],
) -> tuple[list[CanonicalFact], list[str]]:
    facts: list[CanonicalFact] = []
    warnings: list[str] = []

    for index, raw_fact in enumerate(raw_facts, start=1):
        if not isinstance(raw_fact, Mapping):
            warnings.append(f"{domain.value} fact[{index}] is not a mapping")
            continue

        category = _first_text(raw_fact, "category", "type", "name")
        if not category:
            warnings.append(f"{domain.value} fact[{index}] missing category")
            continue

        value = raw_fact.get("value")
        if value is None:
            value = _first_text(raw_fact, "summary", "detail", "fact")
        if value is None:
            warnings.append(f"{domain.value} fact[{index}] missing value")
            continue

        status = _coerce_fact_status(raw_fact.get("status"))
        confidence = _coerce_optional_float(raw_fact.get("confidence"))
        note = _first_text(raw_fact, "note", "notes", "summary")
        rationale = _first_text(raw_fact, "rationale", "why", "reason")
        origin = _first_text(raw_fact, "origin", "source_of_truth")
        fact_evidence, evidence_warnings = _entry_evidence(
            raw_fact,
            shared_evidence=shared_evidence,
            manifest=manifest,
            snapshots=snapshots,
        )
        warnings.extend(f"{domain.value} fact[{index}]: {warning}" for warning in evidence_warnings)

        if status is FactStatus.CONFIRMED and not fact_evidence:
            status = FactStatus.PROVISIONAL
            rationale = rationale or "missing normalized evidence for confirmation"
            origin = origin or "structured_extraction"
            warnings.append(
                f"{domain.value} fact[{index}] downgraded to PROVISIONAL because no normalized evidence was available"
            )
        elif status in {FactStatus.PROVISIONAL, FactStatus.INFERRED}:
            if not rationale:
                rationale = note or "structured extraction did not provide explicit rationale"
                warnings.append(
                    f"{domain.value} fact[{index}] supplied fallback rationale for {status.value}"
                )
            if not origin:
                origin = "structured_extraction"
                warnings.append(
                    f"{domain.value} fact[{index}] supplied fallback origin for {status.value}"
                )

        facts.append(
            CanonicalFact(
                fact_id=_fact_id(screen_id, domain, category, value),
                domain=domain,
                category=category.strip(),
                value=value,
                status=status,
                confidence=confidence,
                evidence=list(_sorted_evidence(fact_evidence)),
                note=note,
                rationale=rationale,
                origin=origin,
            )
        )

    return facts, warnings


def _coerce_contradictions(
    raw_contradictions: Sequence[Any],
    *,
    screen_id: str,
    shared_evidence: Sequence[EvidenceRef],
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord],
) -> tuple[list[ContradictionRecord], list[str]]:
    contradictions: list[ContradictionRecord] = []
    warnings: list[str] = []

    for index, raw_contradiction in enumerate(raw_contradictions, start=1):
        if not isinstance(raw_contradiction, Mapping):
            warnings.append(f"contradiction[{index}] is not a mapping")
            continue

        summary = _first_text(raw_contradiction, "summary", "topic", "description")
        if not summary:
            warnings.append(f"contradiction[{index}] missing summary")
            continue

        claims = _coerce_contradiction_claims(
            _payload_items(raw_contradiction, "claims", "positions"),
            shared_evidence=shared_evidence,
            manifest=manifest,
            snapshots=snapshots,
        )
        if len(claims) < 2:
            warnings.append(f"contradiction[{index}] requires at least two claims")
            continue

        contradictions.append(
            ContradictionRecord(
                contradiction_id=_record_id(screen_id, "contradiction", summary),
                summary=summary,
                severity=_coerce_gap_severity(raw_contradiction.get("severity")),
                claims=claims,
                open_question=_first_text(raw_contradiction, "open_question", "question"),
            )
        )

    return contradictions, warnings


def _coerce_contradiction_claims(
    raw_claims: Sequence[Any],
    *,
    shared_evidence: Sequence[EvidenceRef],
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord],
) -> list[ContradictionClaim]:
    claims: list[ContradictionClaim] = []
    for raw_claim in raw_claims:
        if isinstance(raw_claim, Mapping):
            claim_text = _first_text(raw_claim, "claim", "summary", "text")
            if not claim_text:
                continue
            claim_evidence, _ = _entry_evidence(
                raw_claim,
                shared_evidence=shared_evidence,
                manifest=manifest,
                snapshots=snapshots,
            )
            claims.append(
                ContradictionClaim(
                    claim=claim_text,
                    evidence=list(_sorted_evidence(claim_evidence)),
                )
            )
            continue
        claim_text = str(raw_claim).strip()
        if claim_text:
            claims.append(
                ContradictionClaim(
                    claim=claim_text,
                    evidence=list(_sorted_evidence(shared_evidence)),
                )
            )
    return claims


def _coerce_gap_records(
    raw_gaps: Sequence[Any],
    *,
    screen_id: str,
    shared_evidence: Sequence[EvidenceRef],
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord],
) -> tuple[list[GapRecord], list[str]]:
    gaps: list[GapRecord] = []
    warnings: list[str] = []

    for index, raw_gap in enumerate(raw_gaps, start=1):
        if isinstance(raw_gap, Mapping):
            summary = _first_text(raw_gap, "summary", "question", "text", "detail", "gap", "assumption")
            if not summary:
                warnings.append(f"gap[{index}] missing summary")
                continue
            gap_evidence, evidence_warnings = _entry_evidence(
                raw_gap,
                shared_evidence=shared_evidence,
                manifest=manifest,
                snapshots=snapshots,
            )
            warnings.extend(f"gap[{index}]: {warning}" for warning in evidence_warnings)
            gaps.append(
                GapRecord(
                    gap_id=_record_id(
                        screen_id,
                        _coerce_gap_kind(raw_gap.get("kind")).value.lower(),
                        summary,
                    ),
                    kind=_coerce_gap_kind(raw_gap.get("kind")),
                    summary=summary,
                    severity=_coerce_gap_severity(raw_gap.get("severity")),
                    screen_id=screen_id,
                    owner=_first_text(
                        raw_gap,
                        "owner",
                        "owner_role",
                        "assignee",
                        "target_owner",
                        "needs_from",
                    ),
                    blocking_workstreams=_coerce_fact_domains(
                        raw_gap.get("blocking_workstreams")
                        or raw_gap.get("blocked_workstreams")
                        or raw_gap.get("workstreams")
                        or raw_gap.get("workstream")
                    ),
                    evidence=list(_sorted_evidence(gap_evidence)),
                )
            )
            continue

        summary = str(raw_gap).strip()
        if not summary:
            continue
        gaps.append(
            GapRecord(
                gap_id=_record_id(screen_id, "gap", summary),
                kind=GapKind.MISSING_REQUIREMENT_DETAIL,
                summary=summary,
                screen_id=screen_id,
                evidence=list(_sorted_evidence(shared_evidence)),
            )
        )

    return gaps, warnings


def _coerce_quality_summary(
    raw_quality: Any,
    *,
    response_parse_quality: StructuredParseQuality,
) -> ExtractionQualitySummary:
    if isinstance(raw_quality, Mapping):
        parse_quality = _coerce_parse_quality(raw_quality.get("parse_quality"))
        notes = _coerce_string_list(raw_quality, "notes", "warnings")
        degraded = bool(raw_quality.get("degraded"))
    else:
        parse_quality = None
        notes = []
        degraded = False

    derived_quality = parse_quality or _derive_parse_quality(response_parse_quality)
    return ExtractionQualitySummary(
        parse_quality=derived_quality,
        notes=notes,
        degraded=degraded or response_parse_quality is StructuredParseQuality.DEGRADED,
    )


def _merge_question_records(
    left: Sequence[QuestionRecord],
    right: Sequence[QuestionRecord],
) -> list[QuestionRecord]:
    by_id: dict[str, QuestionRecord] = {record.question_id: record for record in left}
    for record in right:
        by_id.setdefault(record.question_id, record)
    return [by_id[key] for key in sorted(by_id)]


def _first_text(payload: Mapping[str, Any], *field_names: str) -> str | None:
    for field_name in field_names:
        value = payload.get(field_name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _merge_text_lists(left: Sequence[str], right: Sequence[str]) -> list[str]:
    merged: dict[str, str] = {}
    for value in (*left, *right):
        normalized = _normalize_term_key(value)
        if normalized and normalized not in merged:
            merged[normalized] = str(value).strip()
    return list(merged.values())


def _sorted_texts(values: Sequence[str]) -> list[str]:
    deduped = _merge_text_lists((), values)
    return sorted(deduped, key=_normalize_term_key)


def _merge_evidence(
    left: Sequence[EvidenceRef],
    right: Sequence[EvidenceRef],
) -> tuple[EvidenceRef, ...]:
    by_key: dict[tuple[str, str, str | None, str | None], EvidenceRef] = {}
    for item in (*left, *right):
        key = (item.source_key, item.snapshot_id, item.locator, item.quote)
        by_key.setdefault(key, item)
    return tuple(by_key.values())


def _sorted_evidence(evidence: Sequence[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    return tuple(
        sorted(
            _merge_evidence((), evidence),
            key=lambda item: (
                item.source_key,
                item.snapshot_id,
                item.locator or "",
                item.quote or "",
            ),
        )
    )


def _ambiguous_alias_keys(entries: Sequence[TerminologyEntry]) -> set[str]:
    alias_owners: dict[str, set[str]] = {}
    for entry in entries:
        entry_key = _normalize_term_key(entry.standard_term)
        for alias in entry.aliases:
            alias_key = _normalize_term_key(alias)
            if alias_key:
                alias_owners.setdefault(alias_key, set()).add(entry_key)
    return {alias_key for alias_key, owners in alias_owners.items() if len(owners) > 1}


def _normalize_term_key(value: Any) -> str:
    return " ".join(str(value).strip().casefold().split())


def _slugify_identifier(value: str) -> str:
    normalized = _SLUG_RE.sub("-", _normalize_term_key(value))
    return normalized.strip("-") or "screen"


def _stable_screen_id(
    screen_name: str,
    *,
    purpose: str,
    prior_match: ScreenCatalogEntry | None,
    used_ids: set[str],
) -> str:
    if prior_match is not None:
        return prior_match.screen_id

    base_id = _slugify_identifier(screen_name)
    if base_id not in used_ids:
        return base_id

    suffix = hashlib.sha256(
        json.dumps(
            {
                "screen_name": _normalize_term_key(screen_name),
                "purpose": _normalize_term_key(purpose),
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:6]
    candidate = f"{base_id}-{suffix}"
    if candidate not in used_ids:
        return candidate

    counter = 2
    while f"{candidate}-{counter}" in used_ids:
        counter += 1
    return f"{candidate}-{counter}"


def _source_key_index(manifest: SourceManifestDocument) -> dict[str, str]:
    index: dict[str, str] = {}
    for row in manifest.rows:
        for identifier in (row.source_key, row.notebook_source_id, row.title, row.source_ref):
            if identifier:
                index.setdefault(_normalize_term_key(identifier), row.source_key)
    return index


def _related_source_keys(
    raw_entry: Mapping[str, Any],
    *,
    source_key_index: Mapping[str, str],
    evidence: Sequence[EvidenceRef],
) -> list[str]:
    keys = [
        source_key_index.get(_normalize_term_key(value), value)
        for value in _coerce_string_list(raw_entry, "related_sources", "source_keys", "sources")
    ]
    keys.extend(item.source_key for item in evidence)
    return _sorted_texts(keys)


def _coerce_question_records(
    raw_entry: Mapping[str, Any],
    *,
    screen_id: str,
    evidence: Sequence[EvidenceRef],
) -> list[QuestionRecord]:
    raw_questions = raw_entry.get("open_questions")
    if raw_questions is None:
        raw_questions = raw_entry.get("questions")
    if raw_questions is None:
        return []

    if isinstance(raw_questions, str):
        items: list[Any] = [raw_questions]
    elif isinstance(raw_questions, Sequence) and not isinstance(raw_questions, (bytes, bytearray)):
        items = list(raw_questions)
    else:
        return []

    questions: list[QuestionRecord] = []
    for item in items:
        if isinstance(item, Mapping):
            summary = _first_text(item, "summary", "question", "text", "prompt")
            owner = _first_text(
                item,
                "owner",
                "owner_role",
                "assignee",
                "target_owner",
                "needs_from",
            )
            severity = _coerce_gap_severity(item.get("severity"))
            workstreams = _coerce_fact_domains(
                item.get("blocking_workstreams")
                or item.get("blocked_workstreams")
                or item.get("workstreams")
                or item.get("workstream")
            )
        else:
            summary = str(item).strip()
            owner = None
            severity = GapSeverity.MEDIUM
            workstreams = []

        if not summary:
            continue

        questions.append(
            QuestionRecord(
                question_id=_question_id(screen_id, summary),
                summary=summary,
                owner=owner,
                severity=severity,
                screen_id=screen_id,
                blocking_workstreams=workstreams,
                evidence=list(_sorted_evidence(evidence)),
            )
        )
    return questions


def _question_id(screen_id: str, summary: str) -> str:
    slug = _slugify_identifier(summary)[:24]
    digest = hashlib.sha256(_normalize_term_key(summary).encode("utf-8")).hexdigest()[:6]
    return f"{screen_id}-q-{slug}-{digest}"


def _coerce_gap_severity(value: Any) -> GapSeverity:
    if value is None:
        return GapSeverity.MEDIUM
    normalized = _normalize_term_key(value)
    severity_aliases = {
        GapSeverity.CRITICAL: {
            "critical",
            "blocker",
            "p0",
            "sev0",
            "severity 0",
            "showstopper",
        },
        GapSeverity.HIGH: {
            "high",
            "p1",
            "sev1",
            "severity 1",
            "major",
        },
        GapSeverity.MEDIUM: {
            "medium",
            "med",
            "p2",
            "sev2",
            "severity 2",
            "moderate",
        },
        GapSeverity.LOW: {
            "low",
            "minor",
            "p3",
            "sev3",
            "severity 3",
            "nice to have",
        },
    }
    for severity, aliases in severity_aliases.items():
        if normalized == severity.value.casefold() or normalized in aliases:
            return severity
    try:
        return GapSeverity(str(value).strip().upper())
    except ValueError:
        return GapSeverity.MEDIUM


def _coerce_fact_domains(value: Any) -> list[FactDomain]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = [token for token in re.split(r"[,/]| and ", value, flags=re.IGNORECASE) if token]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        candidates = []
        for item in value:
            candidates.extend(
                token
                for token in re.split(r"[,/]| and ", str(item), flags=re.IGNORECASE)
                if token
            )
    else:
        return []

    domains: list[FactDomain] = []
    seen: set[FactDomain] = set()
    for candidate in candidates:
        normalized = _normalize_term_key(candidate)
        domain_aliases = {
            FactDomain.FE: {
                "fe",
                "frontend",
                "front end",
                "ui",
                "ux",
                "client",
            },
            FactDomain.BE: {
                "be",
                "backend",
                "back end",
                "api",
                "service",
                "server",
            },
            FactDomain.SHARED: {
                "shared",
                "both",
                "cross functional",
                "cross-functional",
                "all",
                "system",
            },
        }
        matched = next(
            (
                domain
                for domain, aliases in domain_aliases.items()
                if normalized == domain.value.casefold() or normalized in aliases
            ),
            None,
        )
        if matched is not None:
            if matched not in seen:
                seen.add(matched)
                domains.append(matched)
            continue
        try:
            domain = FactDomain(str(candidate).strip().upper())
        except ValueError:
            continue
        if domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def _coerce_fact_status(value: Any) -> FactStatus:
    if value is None:
        return FactStatus.PROVISIONAL
    try:
        return FactStatus(str(value).strip().upper())
    except ValueError:
        return FactStatus.PROVISIONAL


def _coerce_gap_kind(value: Any) -> GapKind:
    if value is None:
        return GapKind.MISSING_REQUIREMENT_DETAIL
    normalized = _normalize_term_key(value)
    kind_aliases = {
        GapKind.CONTRADICTORY_REQUIREMENT_DETAIL: (
            "contradiction",
            "contradictory requirement detail",
            "conflicting requirement",
            "requirement conflict",
            "inconsistent requirement",
        ),
        GapKind.MISSING_BACKEND_CONTRACT: (
            "missing backend contract",
            "backend contract gap",
            "api contract gap",
            "missing api contract",
            "response shape gap",
            "missing response shape",
        ),
        GapKind.FE_VISIBLE_BACKEND_DEPENDENCY: (
            "fe visible backend dependency",
            "frontend backend dependency",
            "front end backend dependency",
            "backend dependency",
            "api dependency",
            "ui blocked by backend",
        ),
        GapKind.DEFERRED_IMPLEMENTATION_DETAIL: (
            "deferred implementation detail",
            "deferred detail",
            "non blocking detail",
            "non-blocking detail",
            "follow up detail",
            "later phase detail",
        ),
        GapKind.REQUIRED_ASSUMPTION: (
            "required assumption",
            "assumption",
            "working assumption",
            "provisional assumption",
        ),
        GapKind.MISSING_REQUIREMENT_DETAIL: (
            "missing requirement detail",
            "requirement gap",
            "missing detail",
            "needs clarification",
            "clarification needed",
        ),
    }
    for gap_kind, aliases in kind_aliases.items():
        if normalized == gap_kind.value.casefold() or normalized in aliases:
            return gap_kind
    try:
        return GapKind(str(value).strip().upper())
    except ValueError:
        return GapKind.MISSING_REQUIREMENT_DETAIL


def _coerce_parse_quality(value: Any) -> ParseQuality | None:
    if value is None:
        return None
    try:
        return ParseQuality(str(value).strip().upper())
    except ValueError:
        return None


def _derive_parse_quality(value: StructuredParseQuality) -> ParseQuality:
    if value is StructuredParseQuality.EXACT:
        return ParseQuality.HIGH
    if value in {StructuredParseQuality.FENCED_JSON, StructuredParseQuality.SPAN_EXTRACTED}:
        return ParseQuality.MEDIUM
    return ParseQuality.LOW


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fact_id(screen_id: str, domain: FactDomain, category: str, value: Any) -> str:
    payload = json.dumps(
        {
            "domain": domain.value,
            "category": _normalize_term_key(category),
            "value": value,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:6]
    return f"{screen_id}-{domain.value.lower()}-{_slugify_identifier(category)[:16]}-{digest}"


def _record_id(screen_id: str, prefix: str, summary: str) -> str:
    digest = hashlib.sha256(_normalize_term_key(summary).encode("utf-8")).hexdigest()[:6]
    return f"{screen_id}-{prefix}-{_slugify_identifier(summary)[:20]}-{digest}"


def _build_evidence_link_index(
    manifest: SourceManifestDocument,
    snapshots: Sequence[SourceSnapshotRecord],
) -> dict[str, _EvidenceLink]:
    snapshot_by_source_key = {snapshot.source_key: snapshot for snapshot in snapshots}
    link_by_identifier: dict[str, _EvidenceLink] = {}

    for row in manifest.rows:
        snapshot = snapshot_by_source_key.get(row.source_key)
        link = _EvidenceLink(
            source_key=row.source_key,
            snapshot_id=row.snapshot_id or (snapshot.snapshot_id if snapshot is not None else None),
        )
        for identifier in (
            row.source_key,
            row.notebook_source_id,
            snapshot.notebook_source_id if snapshot is not None else None,
        ):
            if identifier:
                link_by_identifier[str(identifier)] = link

    for snapshot in snapshots:
        link = _EvidenceLink(source_key=snapshot.source_key, snapshot_id=snapshot.snapshot_id)
        for identifier in (snapshot.source_key, snapshot.notebook_source_id):
            if identifier and identifier not in link_by_identifier:
                link_by_identifier[str(identifier)] = link

    return link_by_identifier


def _citation_source_identifier(citation: Any) -> str | None:
    for field in ("source_id", "source_key"):
        value = _citation_field(citation, field)
        if value:
            return str(value)
    return None


def _citation_locator(citation: Any) -> str | None:
    location = _citation_field(citation, "location")
    if location:
        return str(location)

    start_char = _citation_field(citation, "start_char")
    end_char = _citation_field(citation, "end_char")
    if start_char is not None or end_char is not None:
        start_text = "?" if start_char is None else str(start_char)
        end_text = "?" if end_char is None else str(end_char)
        return f"{start_text}-{end_text}"

    for fallback in ("url", "title"):
        value = _citation_field(citation, fallback)
        if value:
            return str(value)
    return None


def _citation_field(citation: Any, *field_names: str) -> Any:
    if isinstance(citation, Mapping):
        for field_name in field_names:
            if field_name in citation:
                return citation[field_name]
        return None
    for field_name in field_names:
        if hasattr(citation, field_name):
            return getattr(citation, field_name)
    return None


__all__ = [
    "CanonicalScreenExtractionResult",
    "EvidenceNormalizationResult",
    "JSONPayload",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "StructuredAskCallable",
    "StructuredAskResult",
    "StructuredParseQuality",
    "StructuredParseResult",
    "ScreenCatalogExtractionResult",
    "TerminologyExtractionResult",
    "ask_structured",
    "build_terminology_lookup",
    "canonicalize_term",
    "extract_canonical_screen",
    "extract_screen_catalog_document",
    "extract_terminology_document",
    "normalize_citations_to_evidence",
    "parse_structured_response",
]
