"""Shared public-contract helpers for BA MCP tool wrappers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .._result import make_tool_result
from .models import BAModel, RunStep, WorkflowMode
from .run_store import BARunStore, RunMetadata

MODULE_PURPOSE = "Own shared naming and payload-envelope contracts for public ba.* MCP tools."

OWNS = (
    "Shared ba.* tool naming conventions",
    "Standard success-envelope/result helpers for BA MCP tools",
    "Plan-aligned request/result models for the first public BA tool contracts",
)

MUST_NOT_OWN = (
    "FastMCP server registration side effects",
    "BA workflow state transitions or orchestration logic",
    "NotebookLM transport access",
    "Rendered bundle formatting",
)

PLANNED_BA_TOOL_NAMES: tuple[str, ...] = (
    "ba.start_run",
    "ba.register_sources",
    "ba.ingest_and_wait",
    "ba.snapshot_sources",
    "ba.assess_source_quality",
    "ba.build_source_manifest",
    "ba.normalize_terminology",
    "ba.build_screen_catalog",
    "ba.extract_canonical",
    "ba.review_gaps",
    "ba.generate_matrices",
    "ba.evaluate_readiness",
    "ba.generate_contracts",
    "ba.render_bundle",
    "ba.validate_bundle",
    "ba.status",
    "ba.run_pipeline",
    "ba.rerun_impacted",
)

RUN_PIPELINE_STEP_SEQUENCE: tuple[RunStep, ...] = (
    RunStep.START_RUN,
    RunStep.REGISTER_SOURCES,
    RunStep.INGEST_AND_WAIT,
    RunStep.SNAPSHOT_SOURCES,
    RunStep.ASSESS_SOURCE_QUALITY,
    RunStep.BUILD_SOURCE_MANIFEST,
    RunStep.NORMALIZE_TERMINOLOGY,
    RunStep.BUILD_SCREEN_CATALOG,
    RunStep.EXTRACT_CANONICAL,
    RunStep.REVIEW_GAPS,
    RunStep.GENERATE_MATRICES,
    RunStep.EVALUATE_READINESS,
    RunStep.GENERATE_CONTRACTS,
    RunStep.RENDER_BUNDLE,
    RunStep.VALIDATE_BUNDLE,
)

RUN_PIPELINE_DRY_RUN_STOP_STEP = RunStep.EVALUATE_READINESS

RUN_STEP_TOOL_NAME_MAP: dict[RunStep, str] = {
    RunStep.START_RUN: "ba.start_run",
    RunStep.REGISTER_SOURCES: "ba.register_sources",
    RunStep.INGEST_AND_WAIT: "ba.ingest_and_wait",
    RunStep.SNAPSHOT_SOURCES: "ba.snapshot_sources",
    RunStep.ASSESS_SOURCE_QUALITY: "ba.assess_source_quality",
    RunStep.BUILD_SOURCE_MANIFEST: "ba.build_source_manifest",
    RunStep.NORMALIZE_TERMINOLOGY: "ba.normalize_terminology",
    RunStep.BUILD_SCREEN_CATALOG: "ba.build_screen_catalog",
    RunStep.EXTRACT_CANONICAL: "ba.extract_canonical",
    RunStep.REVIEW_GAPS: "ba.review_gaps",
    RunStep.GENERATE_MATRICES: "ba.generate_matrices",
    RunStep.EVALUATE_READINESS: "ba.evaluate_readiness",
    RunStep.GENERATE_CONTRACTS: "ba.generate_contracts",
    RunStep.RENDER_BUNDLE: "ba.render_bundle",
    RunStep.VALIDATE_BUNDLE: "ba.validate_bundle",
}


class NotebookLifecycle(str, Enum):
    """Supported notebook reuse policies for BA runs."""

    REUSE_FEATURE_NOTEBOOK = "REUSE_FEATURE_NOTEBOOK"
    EPHEMERAL_RUN_NOTEBOOK = "EPHEMERAL_RUN_NOTEBOOK"


class BAToolSuccessEnvelope(BAModel):
    """Standardized success payload for public BA MCP tools."""

    ok: bool = True
    tool: str = Field(min_length=1)
    feature_key: str = Field(min_length=1)
    run_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class BAStartRunRequest(BAModel):
    """Plan-aligned request contract for ``ba.start_run``."""

    feature_key: str = Field(min_length=1)
    mode: WorkflowMode = WorkflowMode.AUTO
    output_dir: str = Field(min_length=1)
    notebook_lifecycle: NotebookLifecycle = NotebookLifecycle.REUSE_FEATURE_NOTEBOOK
    assumption_profile: dict[str, Any] = Field(default_factory=dict)


class BAStartRunResult(BAModel):
    """Plan-aligned response contract for ``ba.start_run``."""

    run_id: str = Field(min_length=1)
    resolved_output_dir: str = Field(min_length=1)
    mode_requested: WorkflowMode
    notebook_lifecycle: NotebookLifecycle
    run_metadata_path: str = Field(min_length=1)


def run_pipeline_steps(*, dry_run: bool = False) -> tuple[RunStep, ...]:
    """Return the plan-aligned ordered step sequence for ``ba.run_pipeline``."""

    if not dry_run:
        return RUN_PIPELINE_STEP_SEQUENCE

    cutoff = RUN_PIPELINE_STEP_SEQUENCE.index(RUN_PIPELINE_DRY_RUN_STOP_STEP) + 1
    return RUN_PIPELINE_STEP_SEQUENCE[:cutoff]


def tool_name_for_run_step(step: RunStep) -> str:
    """Resolve the public ``ba.*`` tool name associated with a pipeline step."""

    try:
        return RUN_STEP_TOOL_NAME_MAP[step]
    except KeyError as exc:
        msg = f"unsupported run-pipeline step: {step!r}"
        raise ValueError(msg) from exc


def run_pipeline_tool_names(*, dry_run: bool = False) -> tuple[str, ...]:
    """Return the ordered public tool names for ``ba.run_pipeline``."""

    return tuple(tool_name_for_run_step(step) for step in run_pipeline_steps(dry_run=dry_run))


def build_start_run_result(
    *,
    store: BARunStore,
    metadata: RunMetadata,
    notebook_lifecycle: NotebookLifecycle,
) -> BAStartRunResult:
    """Build the standard ``ba.start_run`` result from persisted run metadata."""

    return BAStartRunResult(
        run_id=metadata.run_id,
        resolved_output_dir=store.feature_paths.root.as_posix(),
        mode_requested=metadata.mode_requested or WorkflowMode.AUTO,
        notebook_lifecycle=notebook_lifecycle,
        run_metadata_path=store.run_paths.run_metadata_json.as_posix(),
    )


def make_ba_tool_result(
    *,
    tool_name: str,
    feature_key: str,
    run_id: str | None = None,
    data: BaseModel | Mapping[str, Any] | None = None,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """Wrap BA tool data in the shared public success envelope."""

    envelope = BAToolSuccessEnvelope(
        tool=tool_name,
        feature_key=feature_key,
        run_id=run_id,
        data=_normalize_tool_data(data),
        warnings=list(warnings),
    )
    return make_tool_result(envelope.model_dump(mode="json"))


def _normalize_tool_data(data: BaseModel | Mapping[str, Any] | None) -> dict[str, Any]:
    if data is None:
        return {}
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json")
    return dict(data)


__all__ = [
    "BAStartRunRequest",
    "BAStartRunResult",
    "BAToolSuccessEnvelope",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "NotebookLifecycle",
    "OWNS",
    "PLANNED_BA_TOOL_NAMES",
    "RUN_PIPELINE_DRY_RUN_STOP_STEP",
    "RUN_PIPELINE_STEP_SEQUENCE",
    "RUN_STEP_TOOL_NAME_MAP",
    "build_start_run_result",
    "make_ba_tool_result",
    "run_pipeline_steps",
    "run_pipeline_tool_names",
    "tool_name_for_run_step",
]
