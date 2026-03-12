"""Validation boundary for BA bundles, source quality, and run invariants."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
import re

import yaml

from .contracts import validate_mock_data_alignment
from .models import (
    CanonicalScreen,
    FactDomain,
    FactStatus,
    GapSeverity,
    HaltRecommendation,
    ParseQuality,
    ReadinessDecision,
    ReadinessSummary,
    ScreenCatalogDocument,
    SourceLifecycleStatus,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceQualityAssessment,
    SourceSnapshotRecord,
    SourceType,
    TerminologyDocument,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    WorkflowMode,
)
from .repairs import apply_deterministic_repairs
from .run_store import BARunStore

MODULE_PURPOSE = "Own bundle validation, source-quality policy, and QA report generation hooks."

OWNS = (
    "Validation rules over canonical BA models and rendered outputs",
    "Deterministic source-quality heuristics over persisted snapshots",
    "QA report production hooks",
    "Compatibility checks across schema versions and run artifacts",
)

MUST_NOT_OWN = (
    "NotebookLM SDK access",
    "Prompt generation",
    "MCP server transport glue",
    "Rerun decision logic",
)

_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+\S(?:.*\S)?$")
_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+\S(?:.*\S)?$")
_UPPERCASE_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 /_-]{5,}$")
_FRAGMENTED_TOKEN_RE = re.compile(r"\b(?:[A-Za-z0-9]{1,2}\s+){10,}[A-Za-z0-9]{1,2}\b")
_OCR_GLYPH_CLUSTER_RE = re.compile(r"(?:\b[Il1|]\b(?:\s+|$)){3,}|(?:\b[0O]\b(?:\s+|$)){3,}")

_REQUIRED_FEATURE_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("00-overview.md", "overview_markdown"),
    ("01-source-manifest.md", "source_manifest_markdown"),
    ("01-source-manifest.json", "source_manifest_json"),
    ("02-screen-catalog.json", "screen_catalog_json"),
    ("03-readiness-summary.md", "readiness_summary_markdown"),
    ("04-terminology.md", "terminology_markdown"),
    ("04-terminology.json", "terminology_json"),
    ("05-run-audit.json", "run_audit_json"),
)
_REQUIRED_SCREEN_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("canonical.json", "canonical_json"),
    ("fe.md", "fe_markdown"),
    ("be.md", "be_markdown"),
    ("questions.md", "questions_markdown"),
    ("field-matrix.csv", "field_matrix_csv"),
    ("action-rule-matrix.csv", "action_rule_matrix_csv"),
    ("api-matrix.csv", "api_matrix_csv"),
)
_READY_DECISIONS = {
    ReadinessDecision.READY_FOR_FE_AND_BE,
    ReadinessDecision.READY_FOR_FE_WITH_PROVISIONAL_CONTRACT,
}


def assess_source_quality(
    row: SourceManifestRow,
    snapshot: SourceSnapshotRecord,
    content: str,
) -> SourceQualityAssessment:
    """Score a persisted source snapshot using deterministic text heuristics."""
    normalized_content = content.replace("\r\n", "\n")
    stripped = normalized_content.strip()
    char_count = snapshot.char_count or len(stripped)
    lines = [line.strip() for line in normalized_content.splitlines() if line.strip()]
    lower_content = normalized_content.lower()

    heading_count = sum(1 for line in lines if _is_heading(line))
    table_lines = sum(1 for line in lines if "|" in line or "\t" in line)
    table_density = table_lines / max(len(lines), 1)

    encoding_issues: list[str] = []
    if "\ufffd" in normalized_content:
        encoding_issues.append("replacement_character")
    if "\x00" in normalized_content:
        encoding_issues.append("null_byte")
    if "Ã" in normalized_content or "â€" in normalized_content or "â€”" in normalized_content:
        encoding_issues.append("mojibake")

    suspected_scan_indicators: list[str] = []
    if _FRAGMENTED_TOKEN_RE.search(normalized_content):
        suspected_scan_indicators.append("fragmented_tokens")
    alpha_chars = sum(1 for char in normalized_content if char.isalpha())
    visible_chars = sum(1 for char in normalized_content if not char.isspace())
    if visible_chars and alpha_chars / visible_chars < 0.55:
        suspected_scan_indicators.append("low_alpha_ratio")
    if re.search(r"(?:[Il1|]{5,}|[0O]{5,})", normalized_content):
        suspected_scan_indicators.append("ocr_glyph_run")
    if _OCR_GLYPH_CLUSTER_RE.search(normalized_content):
        suspected_scan_indicators.append("ocr_glyph_run")

    missing_sections = _missing_sections(row.source_type, lower_content, heading_count)
    parse_quality = _parse_quality(
        char_count=char_count,
        heading_count=heading_count,
        table_density=table_density,
        encoding_issue_count=len(encoding_issues),
        scan_indicator_count=len(suspected_scan_indicators),
        missing_section_count=len(missing_sections),
    )
    recommendation = _recommendation(
        source_type=row.source_type,
        priority=row.priority,
        parse_quality=parse_quality,
    )

    return SourceQualityAssessment(
        source_key=snapshot.source_key,
        snapshot_id=snapshot.snapshot_id,
        parse_quality=parse_quality,
        character_count=char_count,
        heading_count=heading_count,
        table_density=table_density,
        encoding_issues=encoding_issues,
        suspected_scan_indicators=suspected_scan_indicators,
        missing_sections=missing_sections,
        recommendation=recommendation,
    )


def validate_bundle_artifacts(
    store: BARunStore,
    source_manifest: SourceManifestDocument,
    screen_catalog: ScreenCatalogDocument,
    readiness: ReadinessSummary,
    screen_artifacts: Sequence[object] = (),
    *,
    terminology: TerminologyDocument | None = None,
) -> ValidationReport:
    """Validate a rendered BA bundle and persist per-screen QA reports."""
    terminology = terminology or _load_optional_terminology(store)
    findings = apply_deterministic_repairs(
        store,
        source_manifest,
        screen_catalog,
        readiness,
        screen_artifacts,
        terminology=terminology,
    )
    warnings: list[str] = []
    readiness_by_screen = {screen.screen_id: screen for screen in readiness.screens}
    manifest_source_keys = {row.source_key for row in source_manifest.rows}

    _validate_feature_artifacts(store, findings)
    _validate_readiness_consistency(readiness, screen_catalog, findings)
    _validate_rerun_metadata(store, findings)
    _validate_source_manifest_rows(store, source_manifest, screen_catalog, findings)

    if terminology is not None:
        _validate_terminology_consistency(terminology, manifest_source_keys, findings)

    referenced_source_keys = set(_source_keys_from_terminology(terminology))
    for entry in screen_catalog.screens:
        readiness_screen = readiness_by_screen.get(entry.screen_id)
        _validate_screen_artifacts(store, entry.screen_id, readiness_screen, findings)
        referenced_source_keys.update(entry.related_sources)
        referenced_source_keys.update(_source_keys_from_catalog_entry(entry))

        try:
            screen = store.load_canonical_screen(entry.screen_id)
        except Exception:
            _append_finding(
                findings,
                code="missing-canonical-screen",
                severity=ValidationSeverity.ERROR,
                message="screen catalog entry is missing persisted canonical screen JSON",
                screen_id=entry.screen_id,
                file_path=f"screens/{entry.screen_id}/canonical.json",
            )
            continue

        referenced_source_keys.update(_source_keys_from_screen(screen))
        _validate_confirmed_fact_evidence(screen, findings)
        _validate_contradiction_state(screen, findings)
        _validate_screen_document_alignment(store, screen, findings)
        _validate_contract_bundle(store, entry.screen_id, readiness_screen, findings)

    _validate_manifest_references(source_manifest, screen_catalog, referenced_source_keys, findings)

    warnings.extend(
        finding.message for finding in findings if finding.severity is ValidationSeverity.WARNING
    )
    status = _report_status(findings)
    report = ValidationReport(
        run_id=store.run_id,
        feature_key=store.feature_key,
        status=status,
        findings=findings,
        warnings=warnings,
    )
    _persist_screen_qa_reports(store, screen_catalog, report)
    return report


def _missing_sections(source_type: SourceType, lower_content: str, heading_count: int) -> list[str]:
    missing: list[str] = []
    if heading_count == 0 and len(lower_content) > 250:
        missing.append("document_headings")

    if source_type in {SourceType.PRIMARY_REQUIREMENT, SourceType.PRIMARY_CONTRACT}:
        expected_sections = {
            "overview": ("overview", "summary", "purpose"),
            "requirements": ("requirement", "requirements", "user story"),
            "acceptance_criteria": ("acceptance", "criteria"),
        }
        for section, keywords in expected_sections.items():
            if not any(keyword in lower_content for keyword in keywords):
                missing.append(section)
    return missing


def _is_heading(line: str) -> bool:
    if _MARKDOWN_HEADING_RE.match(line):
        return True
    if _NUMBERED_HEADING_RE.match(line):
        return True
    if line.endswith(":") and len(line) >= 6:
        return True
    return bool(_UPPERCASE_HEADING_RE.match(line))


def _parse_quality(
    *,
    char_count: int,
    heading_count: int,
    table_density: float,
    encoding_issue_count: int,
    scan_indicator_count: int,
    missing_section_count: int,
) -> ParseQuality:
    if char_count < 120 or (encoding_issue_count >= 2 and scan_indicator_count >= 1):
        return ParseQuality.FAILED

    score = 0
    if char_count < 240:
        score += 1
        if heading_count == 0:
            score += 1
    elif char_count < 500:
        score += 1
    elif char_count < 1200 and heading_count == 0:
        score += 1

    if heading_count == 0 and char_count > 250:
        score += 2
    elif heading_count < 2 and char_count > 1000:
        score += 1

    if table_density > 0.35:
        score += 1
    score += encoding_issue_count
    score += scan_indicator_count
    if missing_section_count >= 2:
        score += 1

    if score >= 5:
        return ParseQuality.LOW
    if score >= 2:
        return ParseQuality.MEDIUM
    return ParseQuality.HIGH


def _recommendation(
    *,
    source_type: SourceType,
    priority: SourcePriority,
    parse_quality: ParseQuality,
) -> HaltRecommendation:
    is_primary = source_type in {SourceType.PRIMARY_REQUIREMENT, SourceType.PRIMARY_CONTRACT}
    is_required = priority is SourcePriority.REQUIRED

    if parse_quality is ParseQuality.FAILED:
        if is_primary or is_required:
            return HaltRecommendation.HALT
        return HaltRecommendation.CLARIFICATION_FIRST
    if parse_quality is ParseQuality.LOW:
        if is_primary or is_required:
            return HaltRecommendation.CLARIFICATION_FIRST
        return HaltRecommendation.DEGRADE
    if parse_quality is ParseQuality.MEDIUM:
        return HaltRecommendation.DEGRADE
    return HaltRecommendation.PROCEED


def _validate_feature_artifacts(store: BARunStore, findings: list[ValidationFinding]) -> None:
    for relative_path, attribute in _REQUIRED_FEATURE_ARTIFACTS:
        path = getattr(store.feature_paths, attribute)
        if path.exists():
            continue
        _append_finding(
            findings,
            code="missing-feature-artifact",
            severity=ValidationSeverity.ERROR,
            message=f"required feature artifact `{relative_path}` is missing",
            file_path=relative_path,
        )


def _validate_readiness_consistency(
    readiness: ReadinessSummary,
    screen_catalog: ScreenCatalogDocument,
    findings: list[ValidationFinding],
) -> None:
    if not screen_catalog.screens:
        _append_finding(
            findings,
            code="empty-screen-catalog",
            severity=ValidationSeverity.ERROR,
            message="screen catalog is empty; bundle validation requires at least one screen",
            file_path="02-screen-catalog.json",
        )
        return

    catalog_screen_ids = {screen.screen_id for screen in screen_catalog.screens}
    readiness_screen_ids = {screen.screen_id for screen in readiness.screens}
    for screen_id in sorted(catalog_screen_ids.difference(readiness_screen_ids)):
        _append_finding(
            findings,
            code="missing-readiness-screen",
            severity=ValidationSeverity.ERROR,
            message="readiness summary is missing a screen present in the catalog",
            screen_id=screen_id,
            file_path="03-readiness-summary.md",
        )
    for screen_id in sorted(readiness_screen_ids.difference(catalog_screen_ids)):
        _append_finding(
            findings,
            code="unexpected-readiness-screen",
            severity=ValidationSeverity.ERROR,
            message="readiness summary references a screen not present in the screen catalog",
            screen_id=screen_id,
            file_path="03-readiness-summary.md",
        )

    screens = readiness.screens
    if readiness.decision is ReadinessDecision.READY_FOR_FE_AND_BE:
        if readiness.blockers:
            _append_finding(
                findings,
                code="readiness-blocker-mismatch",
                severity=ValidationSeverity.ERROR,
                message="READY_FOR_FE_AND_BE cannot include unresolved blockers",
                file_path="03-readiness-summary.md",
            )
        if any(not screen.fe_ready or not screen.be_ready for screen in screens):
            _append_finding(
                findings,
                code="readiness-decision-mismatch",
                severity=ValidationSeverity.ERROR,
                message="READY_FOR_FE_AND_BE requires every screen to be FE-ready and BE-ready",
                file_path="03-readiness-summary.md",
            )
    elif readiness.decision is ReadinessDecision.READY_FOR_FE_WITH_PROVISIONAL_CONTRACT:
        if any(not screen.fe_ready for screen in screens) or not any(not screen.be_ready for screen in screens):
            _append_finding(
                findings,
                code="readiness-decision-mismatch",
                severity=ValidationSeverity.ERROR,
                message=(
                    "READY_FOR_FE_WITH_PROVISIONAL_CONTRACT requires every screen to be FE-ready "
                    "and at least one screen to remain BE-blocked"
                ),
                file_path="03-readiness-summary.md",
            )
        invalid_blockers = [
            blocker
            for blocker in readiness.blockers
            if FactDomain.FE in blocker.blocking_workstreams
            or FactDomain.SHARED in blocker.blocking_workstreams
        ]
        if invalid_blockers:
            _append_finding(
                findings,
                code="overconfident-readiness",
                severity=ValidationSeverity.ERROR,
                message=(
                    "READY_FOR_FE_WITH_PROVISIONAL_CONTRACT cannot retain FE or shared blockers"
                ),
                file_path="03-readiness-summary.md",
                details={"blocker_ids": [blocker.gap_id for blocker in invalid_blockers]},
            )
    elif readiness.decision is ReadinessDecision.PARTIAL_READY_NEEDS_CLARIFICATION:
        if not any(screen.fe_ready or screen.be_ready for screen in screens):
            _append_finding(
                findings,
                code="readiness-decision-mismatch",
                severity=ValidationSeverity.ERROR,
                message=(
                    "PARTIAL_READY_NEEDS_CLARIFICATION requires at least one partially ready screen"
                ),
                file_path="03-readiness-summary.md",
            )
    elif readiness.decision is ReadinessDecision.NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS and any(
        screen.fe_ready or screen.be_ready for screen in screens
    ):
        _append_finding(
            findings,
            code="readiness-decision-mismatch",
            severity=ValidationSeverity.ERROR,
            message="NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS cannot include ready screens",
            file_path="03-readiness-summary.md",
        )

    if readiness.decision in _READY_DECISIONS:
        critical_questions = [
            question
            for screen in screens
            for question in screen.open_questions
            if question.severity is GapSeverity.HIGH
        ]
        if critical_questions:
            _append_finding(
                findings,
                code="critical-questions-block-ready",
                severity=ValidationSeverity.ERROR,
                message="high-severity open questions prevent a ready validation outcome",
                file_path="03-readiness-summary.md",
                details={"question_ids": [question.question_id for question in critical_questions]},
            )


def _validate_rerun_metadata(store: BARunStore, findings: list[ValidationFinding]) -> None:
    impacted_path = store.run_paths.impacted_screens_json
    if not impacted_path.exists():
        return
    try:
        payload = json.loads(impacted_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _append_finding(
            findings,
            code="invalid-rerun-metadata",
            severity=ValidationSeverity.ERROR,
            message="impacted rerun metadata must be valid JSON when present",
            file_path=_relative_feature_path(store, impacted_path),
        )
        return
    if not isinstance(payload, Mapping):
        _append_finding(
            findings,
            code="invalid-rerun-metadata",
            severity=ValidationSeverity.ERROR,
            message="impacted rerun metadata must be a JSON object",
            file_path=_relative_feature_path(store, impacted_path),
        )
    if not store.feature_paths.changelog_markdown.exists():
        _append_finding(
            findings,
            code="missing-rerun-changelog",
            severity=ValidationSeverity.ERROR,
            message="rerun metadata exists but feature changelog markdown is missing",
            file_path="changelog.md",
        )


def _validate_source_manifest_rows(
    store: BARunStore,
    source_manifest: SourceManifestDocument,
    screen_catalog: ScreenCatalogDocument,
    findings: list[ValidationFinding],
) -> None:
    if not source_manifest.rows:
        _append_finding(
            findings,
            code="empty-source-manifest",
            severity=ValidationSeverity.ERROR,
            message="source manifest is empty; bundle validation requires registered sources",
            file_path="01-source-manifest.json",
        )
        return

    known_screen_ids = {screen.screen_id for screen in screen_catalog.screens}
    readyish_statuses = {SourceLifecycleStatus.READY, SourceLifecycleStatus.DEGRADED}
    for row in source_manifest.rows:
        if row.status in readyish_statuses and not row.notebook_source_id:
            _append_finding(
                findings,
                code="manifest-missing-notebook-source-id",
                severity=ValidationSeverity.ERROR,
                message="ready manifest row is missing notebook_source_id",
                file_path="01-source-manifest.json",
                details={"source_key": row.source_key},
            )
        if row.status in readyish_statuses and not row.snapshot_id:
            _append_finding(
                findings,
                code="manifest-missing-snapshot",
                severity=ValidationSeverity.ERROR,
                message="ready manifest row is missing a persisted snapshot id",
                file_path="01-source-manifest.json",
                details={"source_key": row.source_key},
            )
            continue
        if row.snapshot_id is None:
            continue
        if row.parse_quality is None:
            _append_finding(
                findings,
                code="manifest-missing-parse-quality",
                severity=ValidationSeverity.ERROR,
                message="manifest row with a snapshot must also record parse_quality",
                file_path="01-source-manifest.json",
                details={"source_key": row.source_key},
            )
        snapshot_paths = store.snapshot_paths(row.source_key, row.snapshot_id)
        if not snapshot_paths.metadata_json.exists():
            _append_finding(
                findings,
                code="missing-snapshot-metadata",
                severity=ValidationSeverity.ERROR,
                message="persisted snapshot metadata JSON is missing",
                file_path=_relative_feature_path(store, snapshot_paths.metadata_json),
                details={"source_key": row.source_key},
            )
        if not snapshot_paths.fulltext_txt.exists():
            _append_finding(
                findings,
                code="missing-snapshot-fulltext",
                severity=ValidationSeverity.ERROR,
                message="persisted snapshot fulltext is missing",
                file_path=_relative_feature_path(store, snapshot_paths.fulltext_txt),
                details={"source_key": row.source_key},
            )
        for screen_id in row.used_in_screens:
            if screen_id in known_screen_ids:
                continue
            _append_finding(
                findings,
                code="manifest-unknown-screen-usage",
                severity=ValidationSeverity.ERROR,
                message="source manifest references an unknown screen in used_in_screens",
                file_path="01-source-manifest.json",
                details={"source_key": row.source_key, "screen_id": screen_id},
            )


def _load_optional_terminology(store: BARunStore) -> TerminologyDocument | None:
    try:
        return store.load_terminology()
    except Exception:
        return None


def _validate_terminology_consistency(
    terminology: TerminologyDocument,
    manifest_source_keys: set[str],
    findings: list[ValidationFinding],
) -> None:
    owner_by_term: dict[str, str] = {}
    for entry in terminology.entries:
        variants = [entry.standard_term, *entry.aliases]
        for variant in variants:
            normalized = _normalize_term(variant)
            if not normalized:
                continue
            owner = owner_by_term.get(normalized)
            if owner is not None and owner != entry.standard_term:
                _append_finding(
                    findings,
                    code="terminology-conflict",
                    severity=ValidationSeverity.ERROR,
                    message="terminology aliases map the same normalized term to multiple standards",
                    file_path="04-terminology.json",
                    details={
                        "normalized_term": normalized,
                        "existing_standard": owner,
                        "conflicting_standard": entry.standard_term,
                    },
                )
                continue
            owner_by_term[normalized] = entry.standard_term
        for evidence in entry.evidence:
            if evidence.source_key in manifest_source_keys:
                continue
            _append_finding(
                findings,
                code="terminology-missing-source",
                severity=ValidationSeverity.ERROR,
                message="terminology evidence references a source absent from the manifest",
                file_path="04-terminology.json",
                details={"source_key": evidence.source_key, "term": entry.standard_term},
            )


def _validate_screen_artifacts(
    store: BARunStore,
    screen_id: str,
    readiness_screen: object | None,
    findings: list[ValidationFinding],
) -> None:
    paths = store.screen_paths(screen_id)
    for relative_name, attribute in _REQUIRED_SCREEN_ARTIFACTS:
        path = getattr(paths, attribute)
        if path.exists():
            continue
        _append_finding(
            findings,
            code="missing-screen-artifact",
            severity=ValidationSeverity.ERROR,
            message=f"required screen artifact `{relative_name}` is missing",
            screen_id=screen_id,
            file_path=f"screens/{screen_id}/{relative_name}",
        )

    if paths.fe_markdown.exists() and not paths.canonical_json.exists():
        _append_finding(
            findings,
            code="fe-without-canonical",
            severity=ValidationSeverity.ERROR,
            message="fe.md exists without canonical.json",
            screen_id=screen_id,
            file_path=f"screens/{screen_id}/fe.md",
        )
    if paths.be_markdown.exists() and not paths.canonical_json.exists():
        _append_finding(
            findings,
            code="be-without-canonical",
            severity=ValidationSeverity.ERROR,
            message="be.md exists without canonical.json",
            screen_id=screen_id,
            file_path=f"screens/{screen_id}/be.md",
        )

    if readiness_screen is None:
        _append_finding(
            findings,
            code="missing-screen-readiness",
            severity=ValidationSeverity.ERROR,
            message="screen bundle is missing a readiness entry",
            screen_id=screen_id,
            file_path="03-readiness-summary.md",
        )
        return

    if _contract_expected(paths.api_matrix_csv, readiness_screen):
        if not paths.contract_yaml.exists():
            _append_finding(
                findings,
                code="missing-provisional-contract",
                severity=ValidationSeverity.ERROR,
                message="screen requires a provisional contract but contract.provisional.yaml is missing",
                screen_id=screen_id,
                file_path=f"screens/{screen_id}/contract.provisional.yaml",
            )
        if not paths.mock_data_json.exists():
            _append_finding(
                findings,
                code="missing-mock-data",
                severity=ValidationSeverity.ERROR,
                message="screen requires mock-data.json alongside the provisional contract",
                screen_id=screen_id,
                file_path=f"screens/{screen_id}/mock-data.json",
            )


def _validate_confirmed_fact_evidence(
    screen: CanonicalScreen,
    findings: list[ValidationFinding],
) -> None:
    for fact in _all_facts(screen):
        if fact.status is not FactStatus.CONFIRMED or fact.evidence:
            continue
        _append_finding(
            findings,
            code="confirmed-fact-missing-evidence",
            severity=ValidationSeverity.ERROR,
            message="confirmed canonical fact is missing evidence",
            screen_id=screen.screen_id,
            file_path=f"screens/{screen.screen_id}/canonical.json",
            details={"fact_id": fact.fact_id},
        )


def _validate_contradiction_state(
    screen: CanonicalScreen,
    findings: list[ValidationFinding],
) -> None:
    contradicted_fact_ids = {
        fact.fact_id for fact in _all_facts(screen) if fact.status is FactStatus.CONTRADICTED
    }
    if contradicted_fact_ids and not screen.contradictions:
        _append_finding(
            findings,
            code="missing-contradiction-record",
            severity=ValidationSeverity.ERROR,
            message="contradicted facts require contradiction records in canonical.json",
            screen_id=screen.screen_id,
            file_path=f"screens/{screen.screen_id}/canonical.json",
            details={"fact_ids": sorted(contradicted_fact_ids)},
        )
    if screen.contradictions and not contradicted_fact_ids:
        _append_finding(
            findings,
            code="dangling-contradiction-record",
            severity=ValidationSeverity.WARNING,
            message="contradiction records exist without any contradicted canonical facts",
            screen_id=screen.screen_id,
            file_path=f"screens/{screen.screen_id}/canonical.json",
            details={
                "contradiction_ids": [record.contradiction_id for record in screen.contradictions],
            },
        )


def _validate_screen_document_alignment(
    store: BARunStore,
    screen: CanonicalScreen,
    findings: list[ValidationFinding],
) -> None:
    paths = store.screen_paths(screen.screen_id)
    if paths.fe_markdown.exists():
        fe_markdown = paths.fe_markdown.read_text(encoding="utf-8")
        for fact in screen.fe_facts:
            if _document_matches_fact(fe_markdown, fact):
                continue
            _append_finding(
                findings,
                code="fe-doc-canonical-mismatch",
                severity=ValidationSeverity.ERROR,
                message="fe.md does not reflect a canonical FE fact",
                screen_id=screen.screen_id,
                fact_id=fact.fact_id,
                file_path=f"screens/{screen.screen_id}/fe.md",
            )
    if paths.be_markdown.exists():
        be_markdown = paths.be_markdown.read_text(encoding="utf-8")
        for fact in screen.be_facts:
            if _document_matches_fact(be_markdown, fact):
                continue
            _append_finding(
                findings,
                code="be-doc-canonical-mismatch",
                severity=ValidationSeverity.ERROR,
                message="be.md does not reflect a canonical BE fact",
                screen_id=screen.screen_id,
                fact_id=fact.fact_id,
                file_path=f"screens/{screen.screen_id}/be.md",
            )


def _validate_contract_bundle(
    store: BARunStore,
    screen_id: str,
    readiness_screen: object | None,
    findings: list[ValidationFinding],
) -> None:
    if readiness_screen is None:
        return
    paths = store.screen_paths(screen_id)
    if not paths.contract_yaml.exists() or not paths.mock_data_json.exists():
        return

    try:
        openapi_document = yaml.safe_load(paths.contract_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        _append_finding(
            findings,
            code="invalid-contract-yaml",
            severity=ValidationSeverity.ERROR,
            message="contract.provisional.yaml must contain valid YAML",
            screen_id=screen_id,
            file_path=f"screens/{screen_id}/contract.provisional.yaml",
        )
        return
    if not isinstance(openapi_document, Mapping):
        _append_finding(
            findings,
            code="invalid-contract-yaml",
            severity=ValidationSeverity.ERROR,
            message="contract.provisional.yaml must decode to a mapping",
            screen_id=screen_id,
            file_path=f"screens/{screen_id}/contract.provisional.yaml",
        )
        return

    try:
        mock_data = json.loads(paths.mock_data_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _append_finding(
            findings,
            code="invalid-mock-data-json",
            severity=ValidationSeverity.ERROR,
            message="mock-data.json must contain valid JSON",
            screen_id=screen_id,
            file_path=f"screens/{screen_id}/mock-data.json",
        )
        return
    if not isinstance(mock_data, Mapping):
        _append_finding(
            findings,
            code="invalid-mock-data-json",
            severity=ValidationSeverity.ERROR,
            message="mock-data.json must decode to a JSON object",
            screen_id=screen_id,
            file_path=f"screens/{screen_id}/mock-data.json",
        )
        return

    for error in validate_mock_data_alignment(
        openapi_document=dict(openapi_document),
        mock_data=dict(mock_data),
    ):
        _append_finding(
            findings,
            code="contract-mock-misalignment",
            severity=ValidationSeverity.ERROR,
            message=error,
            screen_id=screen_id,
            file_path=f"screens/{screen_id}/mock-data.json",
        )


def _validate_manifest_references(
    source_manifest: SourceManifestDocument,
    screen_catalog: ScreenCatalogDocument,
    referenced_source_keys: set[str],
    findings: list[ValidationFinding],
) -> None:
    manifest_source_keys = {row.source_key for row in source_manifest.rows}
    for source_key in sorted(referenced_source_keys.difference(manifest_source_keys)):
        _append_finding(
            findings,
            code="missing-source-manifest-coverage",
            severity=ValidationSeverity.ERROR,
            message="bundle references a source key that is absent from the source manifest",
            file_path="01-source-manifest.json",
            details={"source_key": source_key},
        )
    catalog_screen_ids = {screen.screen_id for screen in screen_catalog.screens}
    for row in source_manifest.rows:
        for screen_id in row.used_in_screens:
            if screen_id in catalog_screen_ids:
                continue
            _append_finding(
                findings,
                code="manifest-unknown-screen-usage",
                severity=ValidationSeverity.ERROR,
                message="source manifest usage points at a screen missing from the catalog",
                file_path="01-source-manifest.json",
                details={"source_key": row.source_key, "screen_id": screen_id},
            )


def _persist_screen_qa_reports(
    store: BARunStore,
    screen_catalog: ScreenCatalogDocument,
    report: ValidationReport,
) -> None:
    for screen in screen_catalog.screens:
        payload = {
            "schema_version": report.schema_version,
            "feature_key": report.feature_key,
            "run_id": report.run_id,
            "screen_id": screen.screen_id,
            "status": _screen_report_status(report, screen.screen_id).value,
            "bundle_status": report.status.value,
            "findings": [
                finding.model_dump(mode="json")
                for finding in report.findings
                if _finding_applies_to_screen(finding, screen.screen_id)
            ],
            "warnings": list(report.warnings),
        }
        store.save_qa_report_json(
            screen.screen_id,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )


def _screen_report_status(report: ValidationReport, screen_id: str) -> ValidationStatus:
    findings = [finding for finding in report.findings if _finding_applies_to_screen(finding, screen_id)]
    return _report_status(findings)


def _finding_applies_to_screen(finding: ValidationFinding, screen_id: str) -> bool:
    if finding.screen_id == screen_id:
        return True
    if finding.screen_id is None and (
        finding.file_path is None or not finding.file_path.startswith("screens/")
    ):
        return True
    return bool(finding.file_path and finding.file_path.startswith(f"screens/{screen_id}/"))


def _contract_expected(api_matrix_path: Path, readiness_screen: object) -> bool:
    if not api_matrix_path.exists() or not _csv_has_rows(api_matrix_path):
        return False
    return bool(
        readiness_screen.fe_ready
        and (
            readiness_screen.resolved_mode is WorkflowMode.FE_FIRST
            or not readiness_screen.be_ready
        )
    )


def _csv_has_rows(path: Path) -> bool:
    with path.open(encoding="utf-8", newline="") as handle:
        return any(csv.DictReader(handle))


def _document_matches_fact(document: str, fact: object) -> bool:
    anchors = _fact_anchors(fact)
    if not anchors:
        return True
    normalized_document = _normalize_text(document)
    return any(anchor in normalized_document for anchor in anchors)


def _fact_anchors(fact: object) -> list[str]:
    candidates = sorted(
        {
            normalized
            for normalized in (
                _normalize_text(value)
                for value in _iter_scalar_strings(getattr(fact, "value", None))
            )
            if len(normalized.replace(" ", "")) >= 4
        },
        key=len,
        reverse=True,
    )
    return candidates[:5]


def _iter_scalar_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_scalar_strings(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from _iter_scalar_strings(item)
        return
    if value is not None and not isinstance(value, bool):
        yield str(value)


def _all_facts(screen: CanonicalScreen) -> Sequence[object]:
    return (*screen.shared_facts, *screen.fe_facts, *screen.be_facts)


def _source_keys_from_catalog_entry(entry: object) -> set[str]:
    source_keys = set(getattr(entry, "related_sources", ()))
    for evidence in getattr(entry, "evidence", ()):
        source_keys.add(evidence.source_key)
    for question in getattr(entry, "open_questions", ()):
        for evidence in getattr(question, "evidence", ()):
            source_keys.add(evidence.source_key)
    return {source_key for source_key in source_keys if source_key}


def _source_keys_from_screen(screen: CanonicalScreen) -> set[str]:
    source_keys: set[str] = set()
    for fact in _all_facts(screen):
        for evidence in fact.evidence:
            source_keys.add(evidence.source_key)
    for gap in (*screen.missing_info, *screen.open_questions):
        for evidence in gap.evidence:
            source_keys.add(evidence.source_key)
    for contradiction in screen.contradictions:
        for claim in contradiction.claims:
            for evidence in claim.evidence:
                source_keys.add(evidence.source_key)
    return {source_key for source_key in source_keys if source_key}


def _source_keys_from_terminology(terminology: TerminologyDocument | None) -> set[str]:
    if terminology is None:
        return set()
    return {
        evidence.source_key
        for entry in terminology.entries
        for evidence in entry.evidence
        if evidence.source_key
    }


def _normalize_term(value: str) -> str:
    return _normalize_text(value)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _relative_feature_path(store: BARunStore, path: Path) -> str:
    return path.relative_to(store.feature_paths.root).as_posix()


def _append_finding(
    findings: list[ValidationFinding],
    *,
    code: str,
    severity: ValidationSeverity,
    message: str,
    screen_id: str | None = None,
    fact_id: str | None = None,
    file_path: str | None = None,
    details: Mapping[str, object] | None = None,
) -> None:
    findings.append(
        ValidationFinding(
            code=code,
            severity=severity,
            message=message,
            screen_id=screen_id,
            fact_id=fact_id,
            file_path=file_path,
            details=dict(details or {}),
        )
    )


def _report_status(findings: Sequence[ValidationFinding]) -> ValidationStatus:
    if any(finding.severity is ValidationSeverity.ERROR for finding in findings):
        return ValidationStatus.FAIL
    if any(finding.severity is ValidationSeverity.WARNING for finding in findings):
        return ValidationStatus.WARN
    return ValidationStatus.PASS


__all__ = [
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "assess_source_quality",
    "validate_bundle_artifacts",
]
