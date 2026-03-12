"""Shared BA data models and enums boundary."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema_version import SchemaFamily, current_schema_version

MODULE_PURPOSE = "Define canonical BA-facing models, enums, and structured payload shapes."

OWNS = (
    "Run-scoped BA dataclasses and enums",
    "Shared payload shapes passed between extraction, rendering, and validation",
    "Stable internal contracts for later ba.* MCP tools",
)

MUST_NOT_OWN = (
    "NotebookLM SDK calls",
    "Filesystem persistence",
    "Prompt text",
    "MCP tool registration",
)


class BAModel(BaseModel):
    """Strict base model for BA workflow payloads."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkflowMode(str, Enum):
    AUTO = "AUTO"
    BALANCED = "BALANCED"
    FE_FIRST = "FE_FIRST"
    CLARIFICATION_FIRST = "CLARIFICATION_FIRST"


class SourceType(str, Enum):
    PRIMARY_REQUIREMENT = "PRIMARY_REQUIREMENT"
    PRIMARY_CONTRACT = "PRIMARY_CONTRACT"
    SUPPORTING_GLOSSARY = "SUPPORTING_GLOSSARY"
    SUPPORTING_RULE = "SUPPORTING_RULE"
    SUPPORTING_DESIGN = "SUPPORTING_DESIGN"
    SUPPORTING_TECH = "SUPPORTING_TECH"
    SUPPORTING_CLARIFICATION = "SUPPORTING_CLARIFICATION"
    SUPPORTING_DECISION = "SUPPORTING_DECISION"
    OPTIONAL_CONTEXT = "OPTIONAL_CONTEXT"


class SourcePriority(str, Enum):
    REQUIRED = "REQUIRED"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class SourceContentKind(str, Enum):
    URL = "URL"
    FILE_PATH = "FILE_PATH"
    INLINE_TEXT = "INLINE_TEXT"


class SourceLifecycleStatus(str, Enum):
    REGISTERED = "REGISTERED"
    INGESTING = "INGESTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ParseQuality(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    FAILED = "FAILED"


class HaltRecommendation(str, Enum):
    PROCEED = "PROCEED"
    DEGRADE = "DEGRADE"
    CLARIFICATION_FIRST = "CLARIFICATION_FIRST"
    HALT = "HALT"


class FactDomain(str, Enum):
    SHARED = "SHARED"
    FE = "FE"
    BE = "BE"


class FactStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PROVISIONAL = "PROVISIONAL"
    MISSING = "MISSING"
    CONTRADICTED = "CONTRADICTED"
    INFERRED = "INFERRED"


class GapSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class GapKind(str, Enum):
    MISSING_REQUIREMENT_DETAIL = "MISSING_REQUIREMENT_DETAIL"
    CONTRADICTORY_REQUIREMENT_DETAIL = "CONTRADICTORY_REQUIREMENT_DETAIL"
    MISSING_BACKEND_CONTRACT = "MISSING_BACKEND_CONTRACT"
    FE_VISIBLE_BACKEND_DEPENDENCY = "FE_VISIBLE_BACKEND_DEPENDENCY"
    DEFERRED_IMPLEMENTATION_DETAIL = "DEFERRED_IMPLEMENTATION_DETAIL"
    REQUIRED_ASSUMPTION = "REQUIRED_ASSUMPTION"


class ReadinessDecision(str, Enum):
    READY_FOR_FE_AND_BE = "READY_FOR_FE_AND_BE"
    READY_FOR_FE_WITH_PROVISIONAL_CONTRACT = "READY_FOR_FE_WITH_PROVISIONAL_CONTRACT"
    PARTIAL_READY_NEEDS_CLARIFICATION = "PARTIAL_READY_NEEDS_CLARIFICATION"
    NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS = "NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS"


class ContractStatus(str, Enum):
    NOT_NEEDED = "NOT_NEEDED"
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"


class MockScenario(str, Enum):
    HAPPY_PATH = "happy_path"
    VALIDATION_ERROR = "validation_error"
    EMPTY_STATE = "empty_state"
    SERVER_ERROR = "server_error"


class ValidationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ValidationStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class RunStep(str, Enum):
    START_RUN = "START_RUN"
    REGISTER_SOURCES = "REGISTER_SOURCES"
    INGEST_AND_WAIT = "INGEST_AND_WAIT"
    SNAPSHOT_SOURCES = "SNAPSHOT_SOURCES"
    ASSESS_SOURCE_QUALITY = "ASSESS_SOURCE_QUALITY"
    BUILD_SOURCE_MANIFEST = "BUILD_SOURCE_MANIFEST"
    NORMALIZE_TERMINOLOGY = "NORMALIZE_TERMINOLOGY"
    BUILD_SCREEN_CATALOG = "BUILD_SCREEN_CATALOG"
    EXTRACT_CANONICAL = "EXTRACT_CANONICAL"
    REVIEW_GAPS = "REVIEW_GAPS"
    GENERATE_MATRICES = "GENERATE_MATRICES"
    EVALUATE_READINESS = "EVALUATE_READINESS"
    GENERATE_CONTRACTS = "GENERATE_CONTRACTS"
    RENDER_BUNDLE = "RENDER_BUNDLE"
    VALIDATE_BUNDLE = "VALIDATE_BUNDLE"


class RunStepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RunEventType(str, Enum):
    STARTED = "STARTED"
    RETRIED = "RETRIED"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    RESUMED = "RESUMED"
    COMPLETED = "COMPLETED"


class EvidenceRef(BAModel):
    source_key: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    locator: str | None = None
    quote: str | None = None

    @model_validator(mode="after")
    def validate_locator_or_quote(self) -> "EvidenceRef":
        if not self.locator and not self.quote:
            msg = "EvidenceRef requires at least one locator or quote."
            raise ValueError(msg)
        return self


class SourceSnapshotRecord(BAModel):
    source_key: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    fulltext_path: str | None = None
    guide_path: str | None = None
    freshness: str | None = None
    notebook_source_id: str | None = None
    title: str | None = None
    source_type: str | None = None
    char_count: int = Field(ge=0, default=0)


class SourceQualityAssessment(BAModel):
    source_key: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    parse_quality: ParseQuality
    character_count: int = Field(ge=0, default=0)
    heading_count: int = Field(ge=0, default=0)
    table_density: float = Field(ge=0.0, default=0.0)
    encoding_issues: list[str] = Field(default_factory=list)
    suspected_scan_indicators: list[str] = Field(default_factory=list)
    missing_sections: list[str] = Field(default_factory=list)
    recommendation: HaltRecommendation = HaltRecommendation.PROCEED


class SourceRegistrationWarningCode(str, Enum):
    INVALID_SOURCE_ENTRY = "INVALID_SOURCE_ENTRY"
    DUPLICATE_SOURCE_KEY = "DUPLICATE_SOURCE_KEY"
    MISSING_CRITICAL_SOURCE_TYPE = "MISSING_CRITICAL_SOURCE_TYPE"


class SourceRegistrationInput(BAModel):
    path_or_url_or_text: str = Field(min_length=1)
    source_key: str = Field(min_length=1)
    source_type: SourceType
    priority: SourcePriority
    notes: list[str] = Field(default_factory=list)
    title: str | None = None
    content_kind: SourceContentKind | None = None


class SourceRegistrationWarning(BAModel):
    code: SourceRegistrationWarningCode
    message: str = Field(min_length=1)
    source_key: str | None = None


class SourceManifestRow(BAModel):
    source_key: str = Field(min_length=1)
    source_type: SourceType
    priority: SourcePriority
    content_kind: SourceContentKind
    source_ref: str = Field(min_length=1)
    title: str | None = None
    notebook_source_id: str | None = None
    snapshot_id: str | None = None
    parse_quality: ParseQuality | None = None
    freshness: str | None = None
    status: SourceLifecycleStatus = SourceLifecycleStatus.REGISTERED
    notes: list[str] = Field(default_factory=list)
    used_in_screens: list[str] = Field(default_factory=list)


class SourceManifestDocument(BAModel):
    schema_version: str = Field(
        default_factory=lambda: current_schema_version(SchemaFamily.SOURCE_MANIFEST)
    )
    run_id: str = Field(min_length=1)
    feature_key: str = Field(min_length=1)
    rows: list[SourceManifestRow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SourceRegistrationResult(BAModel):
    manifest: SourceManifestDocument
    warnings: list[SourceRegistrationWarning] = Field(default_factory=list)
    missing_critical_source_types: list[SourceType] = Field(default_factory=list)
    update_only: bool = False


class TerminologyEntry(BAModel):
    standard_term: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    semantic_notes: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    ambiguity_flags: list[str] = Field(default_factory=list)


class TerminologyDocument(BAModel):
    schema_version: str = Field(default_factory=lambda: current_schema_version(SchemaFamily.TERMINOLOGY))
    run_id: str = Field(min_length=1)
    feature_key: str = Field(min_length=1)
    entries: list[TerminologyEntry] = Field(default_factory=list)


class QuestionRecord(BAModel):
    question_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    owner: str | None = None
    severity: GapSeverity = GapSeverity.MEDIUM
    screen_id: str | None = None
    blocking_workstreams: list[FactDomain] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ContradictionClaim(BAModel):
    claim: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ContradictionRecord(BAModel):
    contradiction_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    severity: GapSeverity = GapSeverity.HIGH
    claims: list[ContradictionClaim] = Field(min_length=2)
    open_question: str | None = None


class ScreenCatalogEntry(BAModel):
    screen_id: str = Field(min_length=1)
    screen_name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    roles: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    exit_points: list[str] = Field(default_factory=list)
    main_actions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    related_sources: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    open_questions: list[QuestionRecord] = Field(default_factory=list)


class ScreenCatalogDocument(BAModel):
    schema_version: str = Field(
        default_factory=lambda: current_schema_version(SchemaFamily.SCREEN_CATALOG)
    )
    run_id: str = Field(min_length=1)
    feature_key: str = Field(min_length=1)
    screens: list[ScreenCatalogEntry] = Field(default_factory=list)


class CanonicalFact(BAModel):
    fact_id: str = Field(min_length=1)
    domain: FactDomain
    category: str = Field(min_length=1)
    value: Any = None
    status: FactStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    note: str | None = None
    rationale: str | None = None
    origin: str | None = None

    @model_validator(mode="after")
    def validate_fact_status_requirements(self) -> "CanonicalFact":
        if self.status is FactStatus.CONFIRMED and not self.evidence:
            msg = "Confirmed facts require evidence."
            raise ValueError(msg)
        if self.status in {FactStatus.PROVISIONAL, FactStatus.INFERRED} and not self.rationale:
            msg = "Provisional or inferred facts require explicit rationale."
            raise ValueError(msg)
        return self


class GapRecord(BAModel):
    gap_id: str = Field(min_length=1)
    kind: GapKind
    summary: str = Field(min_length=1)
    severity: GapSeverity = GapSeverity.MEDIUM
    screen_id: str | None = None
    owner: str | None = None
    blocking_workstreams: list[FactDomain] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ExtractionQualitySummary(BAModel):
    parse_quality: ParseQuality
    notes: list[str] = Field(default_factory=list)
    degraded: bool = False


class CanonicalScreen(BAModel):
    schema_version: str = Field(
        default_factory=lambda: current_schema_version(SchemaFamily.CANONICAL_SCREEN)
    )
    feature_key: str = Field(min_length=1)
    screen_id: str = Field(min_length=1)
    mode: WorkflowMode
    run_id: str = Field(min_length=1)
    shared_facts: list[CanonicalFact] = Field(default_factory=list)
    fe_facts: list[CanonicalFact] = Field(default_factory=list)
    be_facts: list[CanonicalFact] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    contradictions: list[ContradictionRecord] = Field(default_factory=list)
    missing_info: list[GapRecord] = Field(default_factory=list)
    open_questions: list[QuestionRecord] = Field(default_factory=list)
    quality_summary: ExtractionQualitySummary


class GapReviewDocument(BAModel):
    schema_version: str = Field(default_factory=lambda: current_schema_version(SchemaFamily.GAP_REVIEW))
    run_id: str = Field(min_length=1)
    feature_key: str = Field(min_length=1)
    screen_id: str = Field(min_length=1)
    fe_blockers: list[GapRecord] = Field(default_factory=list)
    be_blockers: list[GapRecord] = Field(default_factory=list)
    shared_blockers: list[GapRecord] = Field(default_factory=list)
    non_blockers: list[GapRecord] = Field(default_factory=list)
    required_assumptions: list[GapRecord] = Field(default_factory=list)
    contradiction_backlog: list[ContradictionRecord] = Field(default_factory=list)
    questions_for_ba: list[QuestionRecord] = Field(default_factory=list)
    questions_for_tech_lead: list[QuestionRecord] = Field(default_factory=list)
    questions_for_design: list[QuestionRecord] = Field(default_factory=list)
    unassigned_questions: list[QuestionRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ScreenReadiness(BAModel):
    screen_id: str = Field(min_length=1)
    resolved_mode: WorkflowMode
    fe_ready: bool
    be_ready: bool
    blockers: list[GapRecord] = Field(default_factory=list)
    open_questions: list[QuestionRecord] = Field(default_factory=list)


class ReadinessSummary(BAModel):
    schema_version: str = Field(
        default_factory=lambda: current_schema_version(SchemaFamily.READINESS_SUMMARY)
    )
    run_id: str = Field(min_length=1)
    feature_key: str = Field(min_length=1)
    feature_mode: WorkflowMode
    decision: ReadinessDecision
    screens: list[ScreenReadiness] = Field(default_factory=list)
    blockers: list[GapRecord] = Field(default_factory=list)
    required_assumptions: list[GapRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ContractMetadata(BAModel):
    schema_version: str = Field(
        default_factory=lambda: current_schema_version(SchemaFamily.CONTRACT_METADATA)
    )
    run_id: str = Field(min_length=1)
    feature_key: str = Field(min_length=1)
    screen_id: str | None = None
    contract_status: ContractStatus
    provisional_endpoint_ids: list[str] = Field(default_factory=list)
    mock_scenarios: list[MockScenario] = Field(default_factory=list)
    source_evidence: list[EvidenceRef] = Field(default_factory=list)
    open_questions: list[QuestionRecord] = Field(default_factory=list)


class ValidationFinding(BAModel):
    code: str = Field(min_length=1)
    severity: ValidationSeverity
    message: str = Field(min_length=1)
    screen_id: str | None = None
    fact_id: str | None = None
    file_path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BAModel):
    schema_version: str = Field(
        default_factory=lambda: current_schema_version(SchemaFamily.VALIDATION_REPORT)
    )
    run_id: str = Field(min_length=1)
    feature_key: str = Field(min_length=1)
    status: ValidationStatus
    findings: list[ValidationFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RunStepRecord(BAModel):
    step: RunStep
    status: RunStepStatus = RunStepStatus.PENDING
    attempts: int = Field(ge=1, default=1)
    started_at: str | None = None
    completed_at: str | None = None
    halt_reason: str | None = None
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunEventRecord(BAModel):
    event_type: RunEventType
    step: RunStep | None = None
    message: str = Field(min_length=1)
    created_at: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RunStateSnapshot(BAModel):
    schema_version: str = Field(default_factory=lambda: current_schema_version(SchemaFamily.RUN_STATE))
    run_id: str = Field(min_length=1)
    feature_key: str = Field(min_length=1)
    status: RunStatus
    current_step: RunStep | None = None
    steps: list[RunStepRecord] = Field(default_factory=list)
    events: list[RunEventRecord] = Field(default_factory=list)
    halt_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RunAuditEntry(BAModel):
    recorded_at: str = Field(min_length=1)
    snapshot: RunStateSnapshot


class RunAuditDocument(BAModel):
    schema_version: str = Field(default_factory=lambda: current_schema_version(SchemaFamily.RUN_STATE))
    feature_key: str = Field(min_length=1)
    entries: list[RunAuditEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_entries_match_feature(self) -> "RunAuditDocument":
        for entry in self.entries:
            if entry.snapshot.feature_key != self.feature_key:
                raise ValueError("run audit entries must match document feature_key")
        return self


SourceSnapshot = SourceSnapshotRecord
EvidenceObject = EvidenceRef
BlockerOrQuestion = GapRecord
ValidatorOutput = ValidationReport


__all__ = [
    "BAModel",
    "CanonicalFact",
    "CanonicalScreen",
    "ContractMetadata",
    "ContractStatus",
    "ContradictionClaim",
    "ContradictionRecord",
    "EvidenceRef",
    "EvidenceObject",
    "ExtractionQualitySummary",
    "FactDomain",
    "FactStatus",
    "GapReviewDocument",
    "HaltRecommendation",
    "BlockerOrQuestion",
    "GapKind",
    "GapRecord",
    "GapSeverity",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "MockScenario",
    "OWNS",
    "ParseQuality",
    "QuestionRecord",
    "ReadinessDecision",
    "ReadinessSummary",
    "RunAuditDocument",
    "RunAuditEntry",
    "RunEventRecord",
    "RunEventType",
    "RunStateSnapshot",
    "RunStatus",
    "RunStep",
    "RunStepRecord",
    "RunStepStatus",
    "ScreenCatalogDocument",
    "ScreenCatalogEntry",
    "ScreenReadiness",
    "SourceLifecycleStatus",
    "SourceContentKind",
    "SourceManifestDocument",
    "SourceManifestRow",
    "SourcePriority",
    "SourceQualityAssessment",
    "SourceRegistrationInput",
    "SourceRegistrationResult",
    "SourceRegistrationWarning",
    "SourceRegistrationWarningCode",
    "SourceSnapshot",
    "SourceSnapshotRecord",
    "SourceType",
    "TerminologyDocument",
    "TerminologyEntry",
    "ValidationFinding",
    "ValidationReport",
    "ValidationSeverity",
    "ValidationStatus",
    "ValidatorOutput",
    "WorkflowMode",
]
