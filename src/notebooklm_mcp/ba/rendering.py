"""Rendering boundary for BA bundles and output layout."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Sequence
from io import StringIO

from .models import BAModel
from .gaps import all_gap_review_questions, build_gap_review_document, classify_question_owner
from .matrices import APIMatrixRow, ActionRuleMatrixRow, FieldMatrixRow
from .models import (
    CanonicalScreen,
    ContradictionRecord,
    FactDomain,
    FactStatus,
    GapRecord,
    GapReviewDocument,
    QuestionRecord,
    ReadinessSummary,
    RunAuditDocument,
    RunAuditEntry,
    RunStatus,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    ScreenReadiness,
    SourceManifestDocument,
    SourceManifestRow,
    SourceQualityAssessment,
    SourceSnapshotRecord,
    TerminologyDocument,
    TerminologyEntry,
)
from .run_store import BARunStore

MODULE_PURPOSE = "Own deterministic rendering of BA bundles, manifests, and human-facing outputs."

OWNS = (
    "Bundle layout rules",
    "Output formatting from canonical BA models",
    "Stable render helpers reused by CLI-like and MCP entry points",
)

MUST_NOT_OWN = (
    "NotebookLM SDK access",
    "Prompt selection",
    "Low-level filesystem persistence primitives",
    "Validation policy",
)


class ScreenBundleArtifact(BAModel):
    """Pre-rendered per-screen artifacts ready for final bundle assembly."""

    screen_id: str
    canonical_json: str
    fe_markdown: str | None = None
    be_markdown: str | None = None
    questions_markdown: str | None = None
    field_matrix_csv: str | None = None
    action_rule_matrix_csv: str | None = None
    api_matrix_csv: str | None = None
    contract_yaml: str | None = None
    mock_data_json: str | None = None
    qa_report_json: str | None = None


def build_source_manifest_document(
    manifest: SourceManifestDocument,
    *,
    snapshots: Sequence[SourceSnapshotRecord] = (),
    quality_assessments: Sequence[SourceQualityAssessment] = (),
) -> SourceManifestDocument:
    """Merge snapshot and quality metadata into a canonical source-manifest document."""
    snapshots_by_source_key = {snapshot.source_key: snapshot for snapshot in snapshots}
    quality_by_source_key = {assessment.source_key: assessment for assessment in quality_assessments}

    rows = [
        _merge_source_manifest_row(
            row,
            snapshot=snapshots_by_source_key.get(row.source_key),
            quality=quality_by_source_key.get(row.source_key),
        )
        for row in manifest.rows
    ]
    return manifest.model_copy(update={"rows": rows})


def render_source_manifest_markdown(manifest: SourceManifestDocument) -> str:
    """Render the authoritative human-readable source manifest artifact."""
    lines = [
        "# Source Manifest",
        "",
        f"- Feature key: `{manifest.feature_key}`",
        f"- Run id: `{manifest.run_id}`",
        f"- Schema version: `{manifest.schema_version}`",
        f"- Source count: {len(manifest.rows)}",
    ]

    status_counts = Counter(row.status.value for row in manifest.rows)
    if status_counts:
        lines.append(f"- Status counts: {_format_counter(status_counts)}")

    quality_counts = Counter(
        row.parse_quality.value for row in manifest.rows if row.parse_quality is not None
    )
    if quality_counts:
        lines.append(f"- Parse quality counts: {_format_counter(quality_counts)}")

    lines.extend(["", "## Sources", ""])
    if manifest.rows:
        lines.extend(
            [
                "| Source Key | Title | Type | Priority | Status | Quality | Freshness | Snapshot |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in manifest.rows:
            lines.append(
                "| {source_key} | {title} | {source_type} | {priority} | {status} | {quality} | "
                "{freshness} | {snapshot} |".format(
                    source_key=_table_code(row.source_key),
                    title=_table_text(row.title or row.source_key),
                    source_type=_table_code(row.source_type.value),
                    priority=_table_code(row.priority.value),
                    status=_table_code(row.status.value),
                    quality=_table_code(_optional_value(row.parse_quality)),
                    freshness=_table_code(row.freshness or "unknown"),
                    snapshot=_table_code(row.snapshot_id or "not-captured"),
                )
            )
    else:
        lines.append("_No sources registered._")

    if manifest.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in manifest.warnings)

    if manifest.rows:
        lines.extend(["", "## Details", ""])
        for row in manifest.rows:
            lines.extend(
                [
                    f"### `{row.source_key}`",
                    "",
                    f"- Title: {_inline_text(row.title or row.source_key)}",
                    f"- Source ref: `{row.source_ref}`",
                    f"- Content kind: `{row.content_kind.value}`",
                    f"- Source type: `{row.source_type.value}`",
                    f"- Priority: `{row.priority.value}`",
                    f"- Status: `{row.status.value}`",
                    f"- Parse quality: `{_optional_value(row.parse_quality)}`",
                    f"- Freshness: `{row.freshness or 'unknown'}`",
                    f"- Snapshot id: `{row.snapshot_id or 'not-captured'}`",
                    f"- Notebook source id: `{row.notebook_source_id or 'unavailable'}`",
                    f"- Notes: {_inline_list(row.notes)}",
                    f"- Used in screens: {_inline_code_list(row.used_in_screens)}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def render_source_manifest_json(manifest: SourceManifestDocument) -> str:
    """Render the authoritative machine-readable source manifest artifact."""
    return manifest.model_dump_json(indent=2)


def render_terminology_markdown(document: TerminologyDocument) -> str:
    """Render the authoritative human-readable terminology artifact."""
    lines = [
        "# Terminology",
        "",
        f"- Feature key: `{document.feature_key}`",
        f"- Run id: `{document.run_id}`",
        f"- Schema version: `{document.schema_version}`",
        f"- Term count: {len(document.entries)}",
        f"- Alias count: {sum(len(entry.aliases) for entry in document.entries)}",
        f"- Ambiguous terms: {sum(1 for entry in document.entries if entry.ambiguity_flags)}",
    ]

    lines.extend(["", "## Terms", ""])
    if document.entries:
        lines.extend(
            [
                "| Standard Term | Aliases | Ambiguity Flags | Evidence |",
                "| --- | --- | --- | --- |",
            ]
        )
        for entry in document.entries:
            lines.append(
                "| {standard_term} | {aliases} | {ambiguity_flags} | {evidence_count} |".format(
                    standard_term=_table_code(entry.standard_term),
                    aliases=_table_text(", ".join(entry.aliases) or "_none_"),
                    ambiguity_flags=_table_text(", ".join(entry.ambiguity_flags) or "_none_"),
                    evidence_count=_table_code(str(len(entry.evidence))),
                )
            )
    else:
        lines.append("_No terminology extracted._")

    if document.entries:
        lines.extend(["", "## Details", ""])
        for entry in document.entries:
            lines.extend(_render_terminology_entry(entry))

    return "\n".join(lines).rstrip() + "\n"


def render_terminology_json(document: TerminologyDocument) -> str:
    """Render the authoritative machine-readable terminology artifact."""
    return document.model_dump_json(indent=2)


def render_question_backlog_markdown(review: GapReviewDocument) -> str:
    """Render the per-screen question backlog from structured gap review data."""

    question_count = (
        len(review.questions_for_ba)
        + len(review.questions_for_tech_lead)
        + len(review.questions_for_design)
        + len(review.unassigned_questions)
    )
    lines = [
        "# Questions Backlog",
        "",
        f"- Feature key: `{review.feature_key}`",
        f"- Run id: `{review.run_id}`",
        f"- Screen id: `{review.screen_id}`",
        f"- Schema version: `{review.schema_version}`",
        f"- FE blockers: {len(review.fe_blockers)}",
        f"- BE blockers: {len(review.be_blockers)}",
        f"- Shared blockers: {len(review.shared_blockers)}",
        f"- Required assumptions: {len(review.required_assumptions)}",
        f"- Contradictions: {len(review.contradiction_backlog)}",
        f"- Open questions: {question_count}",
        "",
        "## MISSING",
        "",
    ]

    lines.extend(_render_gap_group("FE blockers", review.fe_blockers))
    lines.extend(_render_gap_group("BE blockers", review.be_blockers))
    lines.extend(_render_gap_group("Shared blockers", review.shared_blockers))
    lines.extend(_render_gap_group("Required assumptions", review.required_assumptions))
    lines.extend(_render_gap_group("Non-blockers", review.non_blockers))

    lines.extend(["## CONTRADICTED", ""])
    if review.contradiction_backlog:
        for contradiction in review.contradiction_backlog:
            lines.extend(_render_contradiction_entry(contradiction))
    else:
        lines.append("_No contradictions recorded._")
        lines.append("")

    lines.extend(_render_question_group("QUESTION_FOR_BA", review.questions_for_ba))
    lines.extend(_render_question_group("QUESTION_FOR_TECH_LEAD", review.questions_for_tech_lead))
    lines.extend(_render_question_group("QUESTION_FOR_DESIGN", review.questions_for_design))
    if review.unassigned_questions:
        lines.extend(_render_question_group("UNASSIGNED", review.unassigned_questions))

    if review.warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in review.warnings)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_gap_review_json(review: GapReviewDocument) -> str:
    """Render the structured gap review as authoritative machine-readable JSON."""

    return review.model_dump_json(indent=2)


def render_field_matrix_csv(rows: Sequence[FieldMatrixRow]) -> str:
    """Render field-matrix rows to deterministic CSV."""

    return _render_csv(
        rows,
        fieldnames=(
            "row_id",
            "screen_id",
            "fact_id",
            "source_domain",
            "fact_status",
            "field_name",
            "field_label",
            "field_type",
            "required",
            "description",
            "evidence_count",
            "evidence_refs",
        ),
    )


def render_action_rule_matrix_csv(rows: Sequence[ActionRuleMatrixRow]) -> str:
    """Render action-rule matrix rows to deterministic CSV."""

    return _render_csv(
        rows,
        fieldnames=(
            "row_id",
            "screen_id",
            "fact_id",
            "source_domain",
            "fact_status",
            "action_name",
            "trigger",
            "rule_summary",
            "outcome",
            "evidence_count",
            "evidence_refs",
        ),
    )


def render_api_matrix_csv(rows: Sequence[APIMatrixRow]) -> str:
    """Render API-matrix rows to deterministic CSV."""

    return _render_csv(
        rows,
        fieldnames=(
            "row_id",
            "screen_id",
            "fact_id",
            "source_domain",
            "fact_status",
            "interface_name",
            "interaction_type",
            "method",
            "target",
            "request_summary",
            "response_summary",
            "evidence_count",
            "evidence_refs",
        ),
    )


def render_fe_spec_markdown(
    catalog_entry: ScreenCatalogEntry,
    screen: CanonicalScreen,
    *,
    matrices,
    review: GapReviewDocument | None = None,
    readiness: ScreenReadiness | None = None,
) -> str:
    """Render deterministic FE-facing markdown from canonical, matrix, and readiness state."""

    review = review or build_gap_review_document(screen)
    lines = [
        f"# FE Spec: {catalog_entry.screen_name}",
        "",
        f"- Screen id: `{catalog_entry.screen_id}`",
        f"- Purpose: {catalog_entry.purpose}",
        f"- Roles: {_inline_list(catalog_entry.roles)}",
        f"- Entry points: {_inline_list(catalog_entry.entry_points)}",
        f"- Exit points: {_inline_list(catalog_entry.exit_points)}",
        f"- Dependencies: {_inline_list(catalog_entry.dependencies or screen.dependencies)}",
    ]
    if readiness is not None:
        lines.extend(
            [
                f"- Resolved mode: `{readiness.resolved_mode.value}`",
                f"- FE ready: `{str(readiness.fe_ready).lower()}`",
                f"- BE ready: `{str(readiness.be_ready).lower()}`",
            ]
        )

    lines.extend(
        [
            "",
            "## User Intent",
            "",
            catalog_entry.purpose,
            "",
            "## States",
            "",
        ]
    )
    state_lines = _render_state_lines(screen)
    lines.extend(state_lines or ["_No explicit UI states were evidenced._"])

    lines.extend(["", "## Fields and Validations", ""])
    if matrices.field_rows:
        for row in matrices.field_rows:
            lines.extend(_render_field_row(row))
    else:
        lines.append("_No FE-visible fields were extracted._")

    lines.extend(["", "## Actions", ""])
    action_lines = _render_action_lines(catalog_entry, matrices.action_rule_rows)
    lines.extend(action_lines or ["_No explicit FE actions were evidenced._"])

    lines.extend(["", "## Visible Business Rules", ""])
    rule_lines = _render_rule_lines(matrices.action_rule_rows)
    lines.extend(rule_lines or ["_No FE-visible business rules were extracted._"])

    lines.extend(["", "## API Dependencies or Provisional Contracts", ""])
    api_lines = _render_api_dependency_lines(screen, matrices.api_rows)
    lines.extend(api_lines or ["_No API dependencies were extracted._"])

    lines.extend(["", "## Loading/Error/Empty States", ""])
    lifecycle_lines = _render_lifecycle_state_lines(screen)
    lines.extend(lifecycle_lines or ["_No explicit loading, error, or empty states were evidenced._"])

    lines.extend(["", "## Open FE Questions", ""])
    question_lines = _render_fe_question_lines(review, readiness)
    lines.extend(question_lines or ["_No open FE questions remain._"])

    lines.extend(["", "## Provisional Markers", ""])
    provisional_lines = _render_provisional_lines(screen, review)
    lines.extend(provisional_lines or ["_No provisional FE markers remain._"])

    return "\n".join(lines).rstrip() + "\n"


def render_be_spec_markdown(
    catalog_entry: ScreenCatalogEntry,
    screen: CanonicalScreen,
    *,
    matrices,
    review: GapReviewDocument | None = None,
    readiness: ScreenReadiness | None = None,
) -> str:
    """Render deterministic BE-facing markdown from canonical, matrix, and readiness state."""

    review = review or build_gap_review_document(screen)
    lines = [
        f"# BE Spec: {catalog_entry.screen_name}",
        "",
        f"- Screen id: `{catalog_entry.screen_id}`",
        f"- Purpose: {catalog_entry.purpose}",
        f"- Roles: {_inline_list(catalog_entry.roles)}",
        f"- Main actions: {_inline_list(catalog_entry.main_actions)}",
        f"- Dependencies: {_inline_list(catalog_entry.dependencies or screen.dependencies)}",
    ]
    if readiness is not None:
        lines.extend(
            [
                f"- Resolved mode: `{readiness.resolved_mode.value}`",
                f"- FE ready: `{str(readiness.fe_ready).lower()}`",
                f"- BE ready: `{str(readiness.be_ready).lower()}`",
            ]
        )

    lines.extend(["", "## Implementation Intent", "", catalog_entry.purpose, ""])

    lines.extend(["## Entities and Data Contracts", ""])
    entity_lines = _render_be_entity_lines(matrices.field_rows)
    lines.extend(entity_lines or ["_No explicit backend data contracts were extracted._"])

    lines.extend(["", "## Workflows and Business Rules", ""])
    workflow_lines = _render_be_workflow_lines(matrices.action_rule_rows)
    lines.extend(workflow_lines or ["_No backend workflow rules were extracted._"])

    lines.extend(["", "## Endpoints, Events, and Jobs", ""])
    interface_lines = _render_be_interface_lines(matrices.api_rows, screen)
    lines.extend(interface_lines or ["_No backend interfaces were extracted._"])

    lines.extend(["", "## Validation Rules and Permissions", ""])
    validation_lines = _render_be_validation_and_permission_lines(matrices.action_rule_rows)
    lines.extend(validation_lines or ["_No explicit validation or permission notes were evidenced._"])

    lines.extend(["", "## Contradictions", ""])
    contradiction_lines = _render_be_contradiction_lines(review)
    lines.extend(contradiction_lines or ["_No contradictions recorded._"])

    lines.extend(["", "## Open BE Questions", ""])
    question_lines = _render_be_question_lines(review, readiness)
    lines.extend(question_lines or ["_No open BE questions remain._"])

    return "\n".join(lines).rstrip() + "\n"


def render_overview_markdown(
    *,
    source_manifest: SourceManifestDocument,
    screen_catalog: ScreenCatalogDocument,
    readiness: ReadinessSummary,
    terminology: TerminologyDocument | None = None,
    run_audit: RunAuditDocument | None = None,
    run_history_notes: Sequence[str] = (),
) -> str:
    """Render the feature-level overview promised by the BA bundle contract."""

    lines = [
        "# Feature Overview",
        "",
        f"- Feature key: `{source_manifest.feature_key}`",
        f"- Run id: `{source_manifest.run_id}`",
        f"- Requested mode: `{readiness.feature_mode.value}`",
        f"- Final decision: `{readiness.decision.value}`",
        f"- Screen count: {len(screen_catalog.screens)}",
        f"- Source count: {len(source_manifest.rows)}",
        "",
        "## Mode and Decision",
        "",
        f"- Requested mode: `{readiness.feature_mode.value}`",
        f"- Final decision: `{readiness.decision.value}`",
    ]
    if readiness.warnings:
        lines.append("- Why: " + " | ".join(readiness.warnings[:3]))
    else:
        lines.append("- Why: no readiness downgrades or contradictions were recorded.")

    status_counts = Counter(row.status.value for row in source_manifest.rows)
    quality_counts = Counter(
        row.parse_quality.value for row in source_manifest.rows if row.parse_quality is not None
    )
    lines.extend(
        [
            "",
            "## Source Health Summary",
            "",
            f"- Status counts: {_format_counter(status_counts) if status_counts else '_none_'}",
            f"- Parse quality counts: {_format_counter(quality_counts) if quality_counts else '_none_'}",
            f"- Manifest warnings: {_inline_list(source_manifest.warnings)}",
        ]
    )

    lines.extend(["", "## Screen Inventory", ""])
    if screen_catalog.screens:
        for screen in screen_catalog.screens:
            lines.append(
                "- `{screen_id}` {name}: {purpose} (roles: {roles}; dependencies: {dependencies})".format(
                    screen_id=screen.screen_id,
                    name=screen.screen_name,
                    purpose=screen.purpose,
                    roles=_inline_list(screen.roles),
                    dependencies=_inline_list(screen.dependencies),
                )
            )
    else:
        lines.append("_No screens were cataloged._")

    lines.extend(["", "## Run History Summary", ""])
    history_lines = list(run_history_notes) or summarize_run_audit_notes(run_audit) or [
        f"Current run `{source_manifest.run_id}` captured the latest structured BA artifacts.",
        "No additional run-history summary is available yet.",
    ]
    lines.extend(f"- {note}" for note in history_lines)

    lines.extend(["", "## Terminology Highlights", ""])
    if terminology and terminology.entries:
        for entry in terminology.entries[:5]:
            aliases = f" (aliases: {_inline_list(entry.aliases)})" if entry.aliases else ""
            lines.append(f"- `{entry.standard_term}`{aliases}")
    else:
        lines.append("_No terminology entries were provided._")

    lines.extend(
        [
            "",
            "## Final Decision",
            "",
            f"- Decision: `{readiness.decision.value}`",
            f"- Blocker count: {len(readiness.blockers)}",
            f"- FE-first assumption count: {len(readiness.required_assumptions)}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_readiness_summary_markdown(summary: ReadinessSummary) -> str:
    """Render the feature-level readiness summary artifact."""

    lines = [
        "# Readiness Summary",
        "",
        f"- Feature key: `{summary.feature_key}`",
        f"- Run id: `{summary.run_id}`",
        f"- Requested mode: `{summary.feature_mode.value}`",
        f"- Decision: `{summary.decision.value}`",
        "",
        "## Screen Readiness",
        "",
    ]
    if summary.screens:
        for screen in summary.screens:
            lines.append(
                "- `{screen_id}` mode=`{mode}` FE=`{fe}` BE=`{be}` blockers={blockers} questions={questions}".format(
                    screen_id=screen.screen_id,
                    mode=screen.resolved_mode.value,
                    fe=str(screen.fe_ready).lower(),
                    be=str(screen.be_ready).lower(),
                    blockers=len(screen.blockers),
                    questions=len(screen.open_questions),
                )
            )
    else:
        lines.append("_No screen readiness records were supplied._")

    lines.extend(["", "## Blockers by Owner", ""])
    lines.extend(_render_blockers_by_owner(summary.blockers))

    lines.extend(["", "## Assumptions Required for FE-first Execution", ""])
    if summary.required_assumptions:
        for assumption in summary.required_assumptions:
            lines.append(
                "- [{severity}] {summary} (owner: {owner}; workstreams: {workstreams})".format(
                    severity=assumption.severity.value,
                    summary=assumption.summary,
                    owner=assumption.owner or "unassigned",
                    workstreams=_format_workstreams(assumption.blocking_workstreams),
                )
            )
    else:
        lines.append("_No FE-first assumptions are currently required._")

    lines.extend(["", "## Rerun Recommendation", ""])
    degraded = any("degraded" in warning.casefold() for warning in summary.warnings)
    if degraded:
        lines.append(
            "- Rerun the impacted screens after clarifying degraded sources or re-capturing cleaner evidence."
        )
    else:
        lines.append("- Rerun only after source snapshots change or blocker state materially changes.")

    if summary.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in summary.warnings)
    return "\n".join(lines).rstrip() + "\n"


def render_run_audit_json(audit: RunAuditDocument) -> str:
    """Render the machine-readable run-audit artifact."""

    return audit.model_dump_json(indent=2)


def summarize_run_audit_notes(
    audit: RunAuditDocument | None,
    *,
    max_notes: int = 3,
) -> list[str]:
    """Derive concise overview notes from typed run-audit checkpoints."""

    if audit is None or not audit.entries:
        return []

    notes = [
        (
            f"{len(audit.entries)} audit checkpoint(s) recorded across "
            f"{len({entry.snapshot.run_id for entry in audit.entries})} run(s)."
        )
    ]
    latest = audit.entries[-1]
    notes.append(_format_run_audit_note(latest, prefix="Latest checkpoint"))

    latest_problem = next(
        (
            entry
            for entry in reversed(audit.entries[:-1])
            if entry.snapshot.status in {RunStatus.DEGRADED, RunStatus.HALTED, RunStatus.FAILED}
        ),
        None,
    )
    if latest.snapshot.status in {RunStatus.DEGRADED, RunStatus.HALTED, RunStatus.FAILED}:
        latest_problem = latest
    if latest_problem is not None and latest_problem is not latest:
        notes.append(_format_run_audit_note(latest_problem, prefix="Latest non-healthy checkpoint"))

    return notes[:max_notes]


def build_bundle_file_map(
    *,
    source_manifest: SourceManifestDocument,
    screen_catalog: ScreenCatalogDocument,
    readiness: ReadinessSummary,
    screen_artifacts: Sequence[ScreenBundleArtifact],
    terminology: TerminologyDocument | None = None,
    run_audit: RunAuditDocument | None = None,
    run_history_notes: Sequence[str] = (),
) -> dict[str, str]:
    """Build the deterministic feature bundle file map from rendered artifact inputs."""

    bundle_files: dict[str, str] = {
        "00-overview.md": render_overview_markdown(
            source_manifest=source_manifest,
            screen_catalog=screen_catalog,
            readiness=readiness,
            terminology=terminology,
            run_audit=run_audit,
            run_history_notes=run_history_notes,
        ),
        "01-source-manifest.md": render_source_manifest_markdown(source_manifest),
        "01-source-manifest.json": render_source_manifest_json(source_manifest),
        "02-screen-catalog.json": screen_catalog.model_dump_json(indent=2),
        "03-readiness-summary.md": render_readiness_summary_markdown(readiness),
    }
    if terminology is not None:
        bundle_files["04-terminology.md"] = render_terminology_markdown(terminology)
        bundle_files["04-terminology.json"] = render_terminology_json(terminology)
    if run_audit is not None:
        bundle_files["05-run-audit.json"] = render_run_audit_json(run_audit)

    for screen_artifact in sorted(screen_artifacts, key=lambda item: item.screen_id):
        prefix = f"screens/{screen_artifact.screen_id}"
        bundle_files[f"{prefix}/canonical.json"] = screen_artifact.canonical_json
        for file_name, content in (
            ("fe.md", screen_artifact.fe_markdown),
            ("be.md", screen_artifact.be_markdown),
            ("questions.md", screen_artifact.questions_markdown),
            ("field-matrix.csv", screen_artifact.field_matrix_csv),
            ("action-rule-matrix.csv", screen_artifact.action_rule_matrix_csv),
            ("api-matrix.csv", screen_artifact.api_matrix_csv),
            ("contract.provisional.yaml", screen_artifact.contract_yaml),
            ("mock-data.json", screen_artifact.mock_data_json),
            ("qa-report.json", screen_artifact.qa_report_json),
        ):
            if content is None:
                continue
            bundle_files[f"{prefix}/{file_name}"] = content
    return bundle_files


def write_bundle_layout(
    store: BARunStore,
    *,
    source_manifest: SourceManifestDocument,
    screen_catalog: ScreenCatalogDocument,
    readiness: ReadinessSummary,
    screen_artifacts: Sequence[ScreenBundleArtifact],
    terminology: TerminologyDocument | None = None,
    run_audit: RunAuditDocument | None = None,
    run_history_notes: Sequence[str] = (),
) -> dict[str, str]:
    """Write the deterministic bundle layout through the existing run-store abstraction."""

    bundle_files = build_bundle_file_map(
        source_manifest=source_manifest,
        screen_catalog=screen_catalog,
        readiness=readiness,
        screen_artifacts=screen_artifacts,
        terminology=terminology,
        run_audit=run_audit,
        run_history_notes=run_history_notes,
    )
    written: dict[str, str] = {}
    for relative_path, content in bundle_files.items():
        path = store.feature_paths.root / relative_path
        written[relative_path] = store.write_text(path, content).as_posix()
    return written


def _merge_source_manifest_row(
    row: SourceManifestRow,
    *,
    snapshot: SourceSnapshotRecord | None,
    quality: SourceQualityAssessment | None,
) -> SourceManifestRow:
    updates: dict[str, object] = {}
    if snapshot is not None:
        updates["snapshot_id"] = snapshot.snapshot_id
        if snapshot.freshness:
            updates["freshness"] = snapshot.freshness
        if snapshot.notebook_source_id and not row.notebook_source_id:
            updates["notebook_source_id"] = snapshot.notebook_source_id
        if snapshot.title and not row.title:
            updates["title"] = snapshot.title
    if quality is not None:
        updates["parse_quality"] = quality.parse_quality
    if not updates:
        return row
    return row.model_copy(update=updates)


def _format_counter(counter: Counter[str]) -> str:
    return ", ".join(f"`{key}`={counter[key]}" for key in sorted(counter))


def _optional_value(value: object | None) -> str:
    if value is None:
        return "unknown"
    raw = getattr(value, "value", value)
    return str(raw)


def _table_text(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", "<br>")


def _table_code(value: str) -> str:
    return f"`{_table_text(value)}`"


def _inline_text(value: str) -> str:
    return value if value else "_none_"


def _inline_list(values: Sequence[str]) -> str:
    if not values:
        return "_none_"
    return ", ".join(values)


def _inline_code_list(values: Sequence[str]) -> str:
    if not values:
        return "_none yet_"
    return ", ".join(f"`{value}`" for value in values)


def _render_terminology_entry(entry: TerminologyEntry) -> list[str]:
    lines = [
        f"### `{entry.standard_term}`",
        "",
        f"- Aliases: {_inline_list(entry.aliases)}",
        f"- Semantic notes: {_inline_list(entry.semantic_notes)}",
        f"- Ambiguity flags: {_inline_list(entry.ambiguity_flags)}",
    ]
    if entry.evidence:
        lines.append("- Evidence:")
        lines.extend(f"  - {_format_evidence_ref(item)}" for item in entry.evidence)
    else:
        lines.append("- Evidence: _none_")
    lines.append("")
    return lines


def _render_gap_group(title: str, gaps: Sequence[GapRecord]) -> list[str]:
    lines = [f"### {title}", ""]
    if not gaps:
        lines.append("_None._")
        lines.append("")
        return lines
    for gap in gaps:
        workstreams = ", ".join(item.value for item in gap.blocking_workstreams) or "shared"
        owner = gap.owner or "unassigned"
        lines.append(
            "- [{severity}] `{kind}` {summary} (owner: {owner}; workstreams: {workstreams})".format(
                severity=gap.severity.value,
                kind=gap.kind.value,
                summary=gap.summary,
                owner=owner,
                workstreams=workstreams,
            )
        )
    lines.append("")
    return lines


def _render_state_lines(screen: CanonicalScreen) -> list[str]:
    lines: list[str] = []
    for fact in (*screen.shared_facts, *screen.fe_facts):
        category = _normalize_category(fact.category)
        if "state" not in category:
            continue
        summary = _render_fact_summary(fact)
        if summary:
            lines.append(f"- {summary}")
    return lines


def _render_contradiction_entry(contradiction: ContradictionRecord) -> list[str]:
    lines = [f"### `{contradiction.contradiction_id}`", ""]
    lines.append(f"- Severity: `{contradiction.severity.value}`")
    lines.append(f"- Summary: {contradiction.summary}")
    if contradiction.open_question:
        lines.append(f"- Resolution question: {contradiction.open_question}")
    else:
        lines.append("- Resolution question: _missing_")
    if contradiction.claims:
        lines.append("- Claims:")
        lines.extend(f"  - {claim.claim}" for claim in contradiction.claims)
    lines.append("")
    return lines


def _render_field_row(row: FieldMatrixRow) -> list[str]:
    lines = [f"### `{row.field_name}`", ""]
    lines.append(f"- Label: {row.field_label or row.field_name}")
    lines.append(f"- Type: `{row.field_type or 'unknown'}`")
    lines.append(f"- Required: `{_optional_bool(row.required)}`")
    lines.append(f"- Source domain: `{row.source_domain.value}`")
    lines.append(f"- Fact status: `{row.fact_status.value}`")
    lines.append(f"- Description: {row.description or '_none_'}")
    lines.append(f"- Traceability: `{row.fact_id}` / evidence={row.evidence_count}")
    lines.append("")
    return lines


def _render_action_lines(
    catalog_entry: ScreenCatalogEntry,
    action_rows: Sequence[ActionRuleMatrixRow],
) -> list[str]:
    actions = list(dict.fromkeys([*catalog_entry.main_actions, *(row.action_name for row in action_rows)]))
    return [f"- {action}" for action in actions if action]


def _render_rule_lines(rows: Sequence[ActionRuleMatrixRow]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        detail = row.rule_summary
        if row.trigger:
            detail = f"{detail} Trigger: {row.trigger}."
        if row.outcome:
            detail = f"{detail} Outcome: {row.outcome}."
        lines.append(f"- [{row.fact_status.value}] {detail}")
    return lines


def _render_api_dependency_lines(
    screen: CanonicalScreen,
    api_rows: Sequence[APIMatrixRow],
) -> list[str]:
    lines = []
    for row in api_rows:
        provisional = " provisional" if row.fact_status is not FactStatus.CONFIRMED else ""
        target = row.target or "_unspecified target_"
        method = row.method or row.interaction_type
        lines.append(f"- [{row.fact_status.value}]{provisional} `{method}` `{target}` for {row.interface_name}")
    for dependency in screen.dependencies:
        if not any(dependency.casefold() in line.casefold() for line in lines):
            lines.append(f"- dependency: {dependency}")
    return lines


def _render_lifecycle_state_lines(screen: CanonicalScreen) -> list[str]:
    lines: list[str] = []
    for fact in (*screen.shared_facts, *screen.fe_facts):
        category = _normalize_category(fact.category)
        if not any(token in category for token in ("loading", "error", "empty")):
            continue
        summary = _render_fact_summary(fact)
        if summary:
            lines.append(f"- [{fact.status.value}] {summary}")
    return lines


def _render_fe_question_lines(
    review: GapReviewDocument,
    readiness: ScreenReadiness | None,
) -> list[str]:
    questions = list(readiness.open_questions) if readiness is not None else list(all_gap_review_questions(review))
    lines: list[str] = []
    for question in questions:
        workstreams = {item.value for item in question.blocking_workstreams}
        if workstreams and "FE" not in workstreams and "SHARED" not in workstreams:
            continue
        lines.append(f"- [{question.severity.value}] {question.summary}")
    for gap in (*review.fe_blockers, *review.shared_blockers):
        lines.append(f"- [{gap.severity.value}] blocker: {gap.summary}")
    return list(dict.fromkeys(lines))


def _render_be_entity_lines(rows: Sequence[FieldMatrixRow]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        lines.append(
            "- [{status}] `{name}` ({field_type}; required={required}; source=`{source_domain}`; {trace})"
            .format(
                status=row.fact_status.value,
                name=row.field_name,
                field_type=row.field_type or "unknown",
                required=_optional_bool(row.required),
                source_domain=row.source_domain.value,
                trace=_traceability_text(row.fact_id, row.evidence_count),
            )
        )
    return list(dict.fromkeys(lines))


def _render_be_workflow_lines(rows: Sequence[ActionRuleMatrixRow]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        detail = row.rule_summary
        if row.trigger:
            detail = f"{detail} Trigger: {row.trigger}."
        if row.outcome:
            detail = f"{detail} Outcome: {row.outcome}."
        lines.append(
            "- [{status}] `{action}`: {detail} (source=`{source_domain}`; {trace})".format(
                status=row.fact_status.value,
                action=row.action_name,
                detail=detail,
                source_domain=row.source_domain.value,
                trace=_traceability_text(row.fact_id, row.evidence_count),
            )
        )
    return list(dict.fromkeys(lines))


def _render_be_interface_lines(
    rows: Sequence[APIMatrixRow],
    screen: CanonicalScreen,
) -> list[str]:
    lines: list[str] = []
    for row in rows:
        method = f"`{row.method}` " if row.method else ""
        target = f" `{row.target}`" if row.target else ""
        detail_parts = []
        if row.request_summary:
            detail_parts.append(f"request: {row.request_summary}")
        if row.response_summary:
            detail_parts.append(f"response: {row.response_summary}")
        detail_parts.append(_traceability_text(row.fact_id, row.evidence_count))
        detail = "; ".join(detail_parts)
        lines.append(
            f"- [{row.fact_status.value}] `{row.interaction_type}` {row.interface_name}: "
            f"{method}{target} ({detail})"
        )
    for dependency in screen.dependencies:
        if not any(dependency.casefold() in line.casefold() for line in lines):
            lines.append(f"- dependency: {dependency}")
    return list(dict.fromkeys(lines))


def _render_be_validation_and_permission_lines(
    rows: Sequence[ActionRuleMatrixRow],
) -> list[str]:
    lines: list[str] = []
    for row in rows:
        haystack = " ".join(
            part for part in (row.action_name, row.trigger, row.rule_summary, row.outcome) if part
        ).casefold()
        if not any(
            token in haystack
            for token in (
                "validation",
                "valid",
                "permission",
                "access",
                "role",
                "authoriz",
                "auth",
                "unique",
                "duplicate",
                "required",
                "allow",
                "deny",
                "reject",
                "approval",
            )
        ):
            continue
        lines.append(
            "- [{status}] {summary} (action=`{action}`; {trace})".format(
                status=row.fact_status.value,
                summary=row.rule_summary,
                action=row.action_name,
                trace=_traceability_text(row.fact_id, row.evidence_count),
            )
        )
    return list(dict.fromkeys(lines))


def _render_be_contradiction_lines(review: GapReviewDocument) -> list[str]:
    lines: list[str] = []
    for contradiction in review.contradiction_backlog:
        lines.extend(_render_contradiction_entry(contradiction))
    return lines


def _render_be_question_lines(
    review: GapReviewDocument,
    readiness: ScreenReadiness | None,
) -> list[str]:
    questions = list(readiness.open_questions) if readiness is not None else list(all_gap_review_questions(review))
    lines: list[str] = []
    for question in questions:
        if not _targets_backend(question):
            continue
        lines.append(
            "- [{severity}] {summary} (owner: {owner}; workstreams: {workstreams}; evidence={evidence})"
            .format(
                severity=question.severity.value,
                summary=question.summary,
                owner=question.owner or "unassigned",
                workstreams=_format_workstreams(question.blocking_workstreams),
                evidence=len(question.evidence),
            )
        )
    if readiness is None:
        for contradiction in review.contradiction_backlog:
            if not contradiction.open_question:
                continue
            lines.append(
                "- [{severity}] {summary} (owner: BA; workstreams: SHARED)".format(
                    severity=contradiction.severity.value,
                    summary=contradiction.open_question,
                )
            )
    for gap in (*review.be_blockers, *review.shared_blockers):
        lines.append(
            "- [{severity}] blocker: {summary} (owner: {owner}; workstreams: {workstreams}; evidence={evidence})"
            .format(
                severity=gap.severity.value,
                summary=gap.summary,
                owner=gap.owner or "unassigned",
                workstreams=_format_workstreams(gap.blocking_workstreams),
                evidence=len(gap.evidence),
            )
        )
    return list(dict.fromkeys(lines))


def _render_provisional_lines(
    screen: CanonicalScreen,
    review: GapReviewDocument,
) -> list[str]:
    lines: list[str] = []
    for fact in (*screen.shared_facts, *screen.fe_facts, *screen.be_facts):
        if fact.status not in {FactStatus.PROVISIONAL, FactStatus.INFERRED}:
            continue
        lines.append(f"- `{fact.category}` remains {fact.status.value.lower()}: { _render_fact_summary(fact) }")
    for gap in review.required_assumptions:
        lines.append(f"- required assumption: {gap.summary}")
    return list(dict.fromkeys(lines))


def _render_question_group(title: str, questions: Sequence[QuestionRecord]) -> list[str]:
    lines = [f"## {title}", ""]
    if not questions:
        lines.append("_None._")
        lines.append("")
        return lines
    for question in questions:
        owner = question.owner or "unassigned"
        workstreams = ", ".join(item.value for item in question.blocking_workstreams) or "none"
        lines.append(
            "- [{severity}] {summary} (owner: {owner}; workstreams: {workstreams})".format(
                severity=question.severity.value,
                summary=question.summary,
                owner=owner,
                workstreams=workstreams,
            )
        )
    lines.append("")
    return lines


def _format_evidence_ref(source: object) -> str:
    source_key = getattr(source, "source_key", "unknown")
    snapshot_id = getattr(source, "snapshot_id", "unknown")
    locator = getattr(source, "locator", None) or "unknown"
    quote = getattr(source, "quote", None)
    if quote:
        return (
            f"`{source_key}` / `{snapshot_id}` / `{locator}` / "
            f"\"{str(quote).replace(chr(10), ' ')}\""
        )
    return f"`{source_key}` / `{snapshot_id}` / `{locator}`"


def _traceability_text(fact_id: str, evidence_count: int) -> str:
    return f"trace=`{fact_id}` / evidence={evidence_count}"


def _format_workstreams(workstreams: Sequence[FactDomain]) -> str:
    return ", ".join(item.value for item in workstreams) or "none"


def _targets_backend(question: QuestionRecord) -> bool:
    workstreams = set(question.blocking_workstreams)
    if FactDomain.BE in workstreams or FactDomain.SHARED in workstreams:
        return True
    return classify_question_owner(question) in {"tech_lead", "unassigned"}


def _render_csv(rows: Sequence[object], *, fieldnames: Sequence[str]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                field_name: _csv_value(getattr(row, field_name, ""))
                for field_name in fieldnames
            }
        )
    return buffer.getvalue()


def _csv_value(value: object) -> object:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return str(raw)


def _render_fact_summary(fact: CanonicalScreen | object) -> str:
    value = getattr(fact, "value", None)
    if isinstance(value, dict):
        for key in ("summary", "description", "label", "name", "path", "value"):
            candidate = value.get(key)
            if candidate:
                return str(candidate)
        return json.dumps(value, sort_keys=True)
    text = str(value).strip()
    if text and text != "None":
        return text
    note = getattr(fact, "note", None)
    return str(note or "").strip()


def _normalize_category(value: str) -> str:
    return " ".join(str(value).replace("_", " ").strip().casefold().split())


def _optional_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "true" if value else "false"


def _render_blockers_by_owner(blockers: Sequence[GapRecord]) -> list[str]:
    if not blockers:
        return ["_No blockers remain._"]
    grouped: dict[str, list[GapRecord]] = {}
    for blocker in blockers:
        grouped.setdefault(blocker.owner or "unassigned", []).append(blocker)
    lines: list[str] = []
    for owner in sorted(grouped, key=str.casefold):
        summaries = "; ".join(
            f"[{blocker.severity.value}] {blocker.summary}" for blocker in grouped[owner]
        )
        lines.append(f"- {owner}: {summaries}")
    return lines


def _format_run_audit_note(entry: RunAuditEntry, *, prefix: str) -> str:
    snapshot = entry.snapshot
    note = f"{prefix}: `{entry.recorded_at}` run `{snapshot.run_id}` -> `{snapshot.status.value}`"
    if snapshot.current_step is not None:
        note += f" at `{snapshot.current_step.value}`"
    if snapshot.halt_reason:
        note += f" (reason: {snapshot.halt_reason})"
    elif snapshot.warnings:
        note += f" (warnings: {len(snapshot.warnings)})"
    return note


__all__ = [
    "ScreenBundleArtifact",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "build_bundle_file_map",
    "render_be_spec_markdown",
    "render_fe_spec_markdown",
    "render_overview_markdown",
    "render_readiness_summary_markdown",
    "render_run_audit_json",
    "render_action_rule_matrix_csv",
    "render_api_matrix_csv",
    "render_field_matrix_csv",
    "render_gap_review_json",
    "render_question_backlog_markdown",
    "render_terminology_json",
    "render_terminology_markdown",
    "build_source_manifest_document",
    "render_source_manifest_json",
    "render_source_manifest_markdown",
    "summarize_run_audit_notes",
    "write_bundle_layout",
]
