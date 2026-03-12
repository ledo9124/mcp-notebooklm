"""BA-specific MCP tool entry-point boundary."""

from __future__ import annotations

import contextlib
import csv
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import inspect
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any

from notebooklm.exceptions import ValidationError

from .._errors import handle_mcp_errors, sanitize_error_message
from .._mapping import map_to_enum
from .._result import make_tool_result, to_json_compatible
from .adapter import BACapabilityAdapter, BAReadyTimeoutPolicy
from .contracts import (
    build_provisional_contract_artifacts,
    render_contract_yaml,
    render_mock_data_json,
)
from .extraction import (
    extract_canonical_screen,
    extract_screen_catalog_document,
    extract_terminology_document,
)
from .gaps import build_gap_review_document
from .matrices import build_screen_matrix_bundle
from .metrics import (
    MetricsCaptureSource,
    RunMetricsHistoryDocument,
    RunMetricsSnapshot,
    build_metrics_snapshot,
    render_metrics_summary_markdown,
)
from .models import (
    CanonicalScreen,
    HaltRecommendation,
    ReadinessSummary,
    RunStatus,
    RunStep,
    RunStepStatus,
    ScreenCatalogDocument,
    SourceContentKind,
    SourcePriority,
    SourceRegistrationResult,
    SourceSnapshotRecord,
    SourceQualityAssessment,
    SourceType,
    TerminologyDocument,
    ValidationReport,
    WorkflowMode,
)
from .readiness import evaluate_readiness
from .rendering import (
    ScreenBundleArtifact,
    build_source_manifest_document,
    render_action_rule_matrix_csv,
    render_api_matrix_csv,
    render_be_spec_markdown,
    render_fe_spec_markdown,
    render_field_matrix_csv,
    render_question_backlog_markdown,
    render_readiness_summary_markdown,
    render_source_manifest_markdown,
    render_terminology_markdown,
    write_bundle_layout,
)
from .run_store import BARunStore, SourceRegistrationInput
from .reruns import (
    RerunDecision,
    RerunPlan,
    SourceSnapshotText,
    attach_source_screen_usage,
    build_rerun_plan,
    render_rerun_changelog,
)
from .state_machine import BARunStateMachine, RunStateTransitionError, next_run_step
from .tool_contracts import run_pipeline_steps, tool_name_for_run_step
from .validation import assess_source_quality, validate_bundle_artifacts

MODULE_PURPOSE = "Own future ba.* MCP tool registration and thin transport wrappers."

OWNS = (
    "ba.* MCP tool registration",
    "Thin request/response wrappers over BA subsystem services",
    "Transport-facing payload normalization for BA tool handlers",
)

MUST_NOT_OWN = (
    "NotebookLM capability normalization",
    "Run-store persistence details",
    "Prompt text definitions",
    "Extraction/rendering/validation business logic",
)

logger = logging.getLogger("notebooklm_mcp.ba.tools")

_NOTEBOOK_LIFECYCLES = {
    "REUSE_FEATURE_NOTEBOOK",
    "EPHEMERAL_RUN_NOTEBOOK",
}


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value.strip()


def _optional_text(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field=field)


def _require_bool(value: bool, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be a boolean.")
    return value


def _normalize_output_dir(value: str | None) -> Path:
    if value is None:
        return Path(".").resolve()
    return Path(_require_text(value, field="output_dir")).resolve()


def _normalize_notebook_lifecycle(value: str) -> str:
    normalized = _require_text(value, field="notebook_lifecycle").upper()
    if normalized not in _NOTEBOOK_LIFECYCLES:
        valid = ", ".join(sorted(_NOTEBOOK_LIFECYCLES))
        raise ValidationError(
            f"notebook_lifecycle must be one of: {valid}. Got: {value!r}"
        )
    return normalized


def _normalize_assumption_profile(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValidationError("assumption_profile must be an object/map when provided.")
    return {str(key): value[key] for key in value}


def _generate_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid4().hex[:8]}"


def _serialize_model(model: Any) -> dict[str, Any]:
    payload = to_json_compatible(model)
    if isinstance(payload, dict):
        return payload
    raise TypeError(f"expected a mapping-like payload, got {type(model)!r}")


def _tool_result(
    *,
    tool_name: str,
    feature_key: str,
    run_id: str,
    output_dir: Path,
    result: Mapping[str, Any],
    warnings: Sequence[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "tool": tool_name,
        "feature_key": feature_key,
        "run_id": run_id,
        "resolved_output_dir": str(output_dir),
        "result": dict(result),
    }
    if warnings:
        payload["warnings"] = list(warnings)
    return make_tool_result(payload)


def _resolve_app_context(ctx: MCPContext) -> Any:
    request_context = getattr(ctx, "request_context", None)
    app = getattr(request_context, "lifespan_context", None)
    if app is None:
        app = getattr(ctx, "lifespan_context", None)
    if app is not None and hasattr(app, "client"):
        return app
    raise RuntimeError("NotebookLM MCP lifespan context is unavailable.")


@contextlib.asynccontextmanager
async def _acquire_slot(app: Any):
    acquire_slot = getattr(app, "acquire_slot", None)
    if callable(acquire_slot):
        async with acquire_slot():
            yield
        return
    yield


async def _report_progress(ctx: MCPContext, current: int, total: int, message: str) -> None:
    reporter = getattr(ctx, "report_progress", None)
    if not callable(reporter):
        return

    attempts = (
        {"current": current, "total": total, "message": message},
        {"progress": current, "total": total, "message": message},
        {"current": current, "total": total},
    )
    for kwargs in attempts:
        try:
            value = reporter(**kwargs)
        except TypeError:
            continue
        if inspect.isawaitable(value):
            await value
        return

    with contextlib.suppress(Exception):
        value = reporter(current, total, message)
        if inspect.isawaitable(value):
            await value


def _register_tool(
    server: Any,
    *,
    name: str,
    description: str,
    handler: Callable[..., Any],
) -> None:
    tool_factory = getattr(server, "tool", None)
    if not callable(tool_factory):
        logger.warning("Cannot register tool %s: server has no callable tool()", name)
        return

    for kwargs in (
        {"name": name, "description": description},
        {"name": name},
        {},
    ):
        try:
            decorator = tool_factory(**kwargs)
        except TypeError:
            continue

        if not callable(decorator):
            continue

        decorator(handler)
        return

    raise RuntimeError(f"Failed to register MCP tool: {name}")


def _store_for(feature_key: str, run_id: str, output_dir: Path) -> BARunStore:
    return BARunStore(
        feature_key=feature_key,
        run_id=run_id,
        workspace_root=output_dir,
    )


def _start_run_metadata(
    *,
    mode: WorkflowMode,
    notebook_lifecycle: str,
    assumption_profile: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "mode_requested": mode.value,
        "notebook_lifecycle": notebook_lifecycle,
        "assumption_profile": dict(assumption_profile),
    }


def _require_start_run_completed(machine: BARunStateMachine) -> None:
    for record in machine.state.steps:
        if record.step is RunStep.START_RUN and record.status is RunStepStatus.COMPLETED:
            return
    raise ValidationError("ba.start_run must complete before ba.register_sources.")


def _handle_transition_error(exc: RunStateTransitionError) -> None:
    raise ValidationError(str(exc)) from exc


def _normalize_source_inputs(
    sources: Sequence[Mapping[str, Any]],
) -> list[SourceRegistrationInput]:
    inputs: list[SourceRegistrationInput] = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, Mapping):
            raise ValidationError(f"sources[{index}] must be an object.")

        source_key = source.get("source_key")
        notes = source.get("notes", [])
        if notes is None:
            notes = []
        if not isinstance(notes, Sequence) or isinstance(notes, (str, bytes, bytearray)):
            raise ValidationError(f"sources[{index}].notes must be a list of strings.")

        inputs.append(
            SourceRegistrationInput(
                path_or_url_or_text=_require_text(
                    source.get("path_or_url_or_text"),
                    field=f"sources[{index}].path_or_url_or_text",
                ),
                source_key=_optional_text(source_key, field=f"sources[{index}].source_key"),
                source_type=map_to_enum(
                    source.get("source_type"),
                    SourceType,
                    field_name=f"sources[{index}].source_type",
                ),
                priority=map_to_enum(
                    source.get("priority", "normal"),
                    SourcePriority,
                    field_name=f"sources[{index}].priority",
                ),
                notes=[
                    _require_text(note, field=f"sources[{index}].notes[]")
                    for note in notes
                ],
                title=_optional_text(source.get("title"), field=f"sources[{index}].title"),
                content_kind=(
                    map_to_enum(
                        source["content_kind"],
                        SourceContentKind,
                        field_name=f"sources[{index}].content_kind",
                    )
                    if source.get("content_kind") is not None
                    else None
                ),
            )
        )
    return inputs


def _store_source_registration(store: BARunStore, registration: Any) -> None:
    store.write_model_json(store.run_paths.source_registration_json, registration)


def _source_ids_from_manifest(manifest: Any) -> tuple[str, ...]:
    return tuple(
        row.notebook_source_id
        for row in manifest.rows
        if getattr(row, "notebook_source_id", None)
    )


def _source_scope_text(manifest: Any) -> str:
    lines = []
    for row in manifest.rows:
        title = row.title or row.source_ref
        status = getattr(row.status, "value", str(row.status))
        snapshot_id = row.snapshot_id or "pending"
        lines.append(
            f"- {row.source_key}: {title} [{row.source_type.value}] status={status} snapshot={snapshot_id}"
        )
    return "\n".join(lines)


def _load_snapshot_records(
    store: BARunStore,
    manifest: Any,
) -> list[SourceSnapshotRecord]:
    records: list[SourceSnapshotRecord] = []
    for row in manifest.rows:
        if row.snapshot_id:
            records.append(store.load_source_snapshot(row.source_key, row.snapshot_id))
    return records


def _load_quality_assessments(
    store: BARunStore,
    manifest: Any,
) -> list[SourceQualityAssessment]:
    assessments: list[SourceQualityAssessment] = []
    for row in manifest.rows:
        if row.snapshot_id:
            with contextlib.suppress(Exception):
                assessments.append(
                    store.load_source_quality_assessment(
                        row.source_key,
                        row.snapshot_id,
                        SourceQualityAssessment,
                    )
                )
    return assessments


def _warning_reason(prefix: str, warnings: Sequence[str]) -> str:
    if warnings:
        return f"{prefix}: {warnings[0]}"
    return prefix


def _dedupe_warnings(*warning_groups: Sequence[str] | None) -> list[str]:
    deduped: dict[str, None] = {}
    for group in warning_groups:
        if not group:
            continue
        for warning in group:
            text = warning.strip()
            if text:
                deduped.setdefault(text, None)
    return list(deduped)


def _screen_readiness_index(readiness_summary: Any) -> dict[str, Any]:
    return {screen.screen_id: screen for screen in readiness_summary.screens}


def _screen_catalog_index(screen_catalog: Any) -> dict[str, Any]:
    return {screen.screen_id: screen for screen in screen_catalog.screens}


def _load_canonical_screens(
    store: BARunStore,
    screen_catalog: ScreenCatalogDocument,
) -> dict[str, CanonicalScreen]:
    return {
        screen.screen_id: store.load_canonical_screen(screen.screen_id)
        for screen in screen_catalog.screens
    }


def _load_snapshot_texts(
    store: BARunStore,
    manifest: Any,
) -> dict[str, SourceSnapshotText]:
    snapshots: dict[str, SourceSnapshotText] = {}
    for row in manifest.rows:
        if not row.snapshot_id:
            continue
        record = store.load_source_snapshot(row.source_key, row.snapshot_id)
        snapshots[row.source_key] = SourceSnapshotText(
            record=record,
            content=store.load_source_snapshot_text(row.source_key, row.snapshot_id),
        )
    return snapshots


def _load_matrix_source_links(
    store: BARunStore,
    screen_ids: Sequence[str],
) -> dict[str, list[str]]:
    links: dict[str, list[str]] = {}
    for screen_id in screen_ids:
        source_keys: set[str] = set()
        paths = store.screen_paths(screen_id)
        for path in (
            paths.field_matrix_csv,
            paths.action_rule_matrix_csv,
            paths.api_matrix_csv,
        ):
            if not path.exists():
                continue
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    raw_refs = row.get("evidence_refs", "")
                    for item in raw_refs.split(";"):
                        reference = item.strip()
                        if not reference or "@" not in reference:
                            continue
                        source_key, _, _ = reference.partition("@")
                        if source_key:
                            source_keys.add(source_key.strip())
        if source_keys:
            links[screen_id] = sorted(source_keys)
    return links


def _remove_stale_optional_screen_artifacts(
    store: BARunStore,
    *,
    screen_ids: Sequence[str],
    contract_screens: Sequence[str],
) -> None:
    contract_screen_set = set(contract_screens)
    for screen_id in screen_ids:
        paths = store.screen_paths(screen_id)
        if screen_id not in contract_screen_set:
            with contextlib.suppress(FileNotFoundError):
                paths.contract_yaml.unlink()
            with contextlib.suppress(FileNotFoundError):
                paths.mock_data_json.unlink()
        with contextlib.suppress(FileNotFoundError):
            paths.qa_report_json.unlink()


def _fail_pipeline_step(
    machine: BARunStateMachine,
    step: RunStep,
    exc: Exception,
    *,
    message: str,
) -> None:
    with contextlib.suppress(Exception):
        machine.fail(
            sanitize_error_message(str(exc)),
            step=step,
            message=message,
        )


def _pipeline_response(
    *,
    feature_key: str,
    run_id: str,
    store: BARunStore,
    warnings: Sequence[str],
    step_results: Mapping[str, Any],
    state: Any,
    dry_run: bool,
    notebook_id: str,
    bundle_files: Mapping[str, str] | None = None,
    validation: Mapping[str, Any] | None = None,
    stopped_after_step: str | None = None,
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _tool_result(
        tool_name="ba.run_pipeline",
        feature_key=feature_key,
        run_id=run_id,
        output_dir=store.feature_paths.root,
        warnings=_dedupe_warnings(warnings),
        result={
            "notebook_id": notebook_id,
            "dry_run": dry_run,
            "state": _serialize_model(state),
            "step_results": dict(step_results),
            "bundle_files": dict(bundle_files or {}),
            "validation": dict(validation or {}),
            "stopped_after_step": stopped_after_step,
            "metrics": dict(metrics or {}),
        },
    )


def _qa_report_paths(store: BARunStore, screen_ids: Sequence[str]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for screen_id in screen_ids:
        qa_report_path = store.screen_paths(screen_id).qa_report_json
        if qa_report_path.exists():
            paths[screen_id] = str(qa_report_path)
    return paths


def _attach_qa_reports_to_screen_artifacts(
    store: BARunStore,
    screen_artifacts: Sequence[ScreenBundleArtifact],
) -> list[ScreenBundleArtifact]:
    updated: list[ScreenBundleArtifact] = []
    for artifact in screen_artifacts:
        qa_report_json = artifact.qa_report_json
        with contextlib.suppress(Exception):
            qa_report_json = store.load_qa_report_json(artifact.screen_id)
        updated.append(artifact.model_copy(update={"qa_report_json": qa_report_json}))
    return updated


def _validation_result_payload(
    report: ValidationReport,
    *,
    store: BARunStore,
    screen_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "executed": True,
        "status": report.status.value,
        "finding_count": len(report.findings),
        "warning_count": len(report.warnings),
        "qa_report_paths": _qa_report_paths(store, screen_ids),
        "report": _serialize_model(report),
    }


def _metrics_payload(
    store: BARunStore,
    *,
    snapshot: RunMetricsSnapshot | None,
    history: RunMetricsHistoryDocument | None,
) -> dict[str, Any]:
    return {
        "snapshot": _serialize_model(snapshot) if snapshot is not None else None,
        "history_count": len(history.entries) if history is not None else 0,
        "run_metrics_path": str(store.run_paths.metrics_json),
        "metrics_history_path": str(store.feature_paths.metrics_history_json),
        "metrics_summary_path": str(store.feature_paths.metrics_summary_markdown),
    }


def _load_metrics_payload(store: BARunStore) -> dict[str, Any]:
    snapshot: RunMetricsSnapshot | None = None
    history: RunMetricsHistoryDocument | None = None
    with contextlib.suppress(Exception):
        history = store.load_metrics_history()
    with contextlib.suppress(Exception):
        if store.run_paths.metrics_json.exists():
            snapshot = store.load_metrics_snapshot()
    return _metrics_payload(store, snapshot=snapshot, history=history)


def _refresh_metrics_payload(
    *,
    store: BARunStore,
    metadata: Any,
    state: Any,
    source: MetricsCaptureSource,
    source_manifest: SourceManifestDocument | None = None,
    screen_catalog: ScreenCatalogDocument | None = None,
    readiness: ReadinessSummary | None = None,
    validation_report: ValidationReport | None = None,
    rerun_plan: RerunPlan | None = None,
    notes: Sequence[str] = (),
) -> dict[str, Any]:
    history = store.load_metrics_history()
    snapshot = build_metrics_snapshot(
        feature_key=store.feature_key,
        run_id=store.run_id,
        source=source,
        state=state,
        run_created_at=getattr(metadata, "created_at", None),
        source_manifest=source_manifest,
        screen_catalog=screen_catalog,
        readiness=readiness,
        validation_report=validation_report,
        rerun_plan=rerun_plan,
        history_entries=history.entries,
        notes=notes,
    )
    store.save_metrics_snapshot(snapshot)
    history = store.append_metrics_snapshot(snapshot)
    store.save_metrics_summary_markdown(
        render_metrics_summary_markdown(snapshot, history=history)
    )
    return _metrics_payload(store, snapshot=snapshot, history=history)


def _load_existing_run_state(
    *,
    feature_key: str,
    run_id: str,
    output_dir: Path,
) -> tuple[BARunStore, Any, BARunStateMachine]:
    store = _store_for(feature_key, run_id, output_dir)
    if not store.run_paths.run_state_json.exists() or not store.run_paths.run_metadata_json.exists():
        raise ValidationError(
            "No persisted BA run exists for the requested feature/run pair. "
            "Start the run with ba.start_run before requesting status."
        )
    metadata = store.load_metadata()
    machine = BARunStateMachine.from_store(store)
    return store, metadata, machine


def _status_step_rows(state: Any) -> list[dict[str, Any]]:
    records = {record.step: record for record in state.steps}
    rows: list[dict[str, Any]] = []
    for step in run_pipeline_steps():
        record = records.get(step)
        if record is None:
            rows.append(
                {
                    "step": step.value,
                    "tool": tool_name_for_run_step(step),
                    "status": "NOT_STARTED",
                    "attempts": 0,
                    "started_at": None,
                    "completed_at": None,
                    "halt_reason": None,
                    "notes": [],
                    "metadata": {},
                    "current": False,
                }
            )
            continue
        serialized = _serialize_model(record)
        serialized["tool"] = tool_name_for_run_step(step)
        serialized["current"] = state.current_step is step
        rows.append(serialized)
    return rows


def _next_status_step(state: Any) -> RunStep | None:
    if state.status is RunStatus.COMPLETED:
        return None
    if state.current_step is not None:
        return state.current_step
    completed_steps = [record.step for record in state.steps if record.status is RunStepStatus.COMPLETED]
    if not completed_steps:
        return RunStep.START_RUN
    completed_index = {step: index for index, step in enumerate(run_pipeline_steps())}
    last_completed = max(completed_steps, key=lambda step: completed_index[step])
    return next_run_step(last_completed)


def _status_resumability(state: Any, machine: BARunStateMachine) -> dict[str, Any]:
    can_resume = machine.can_resume()
    suggested_step = state.current_step if state.current_step is not None else _next_status_step(state)
    requires_explicit_step = can_resume and state.current_step is None and suggested_step is not None
    hint: str | None = None
    if can_resume and requires_explicit_step and suggested_step is not None:
        hint = (
            f"Resume should set current_step to {suggested_step.value} before continuing; "
            "the paused run no longer points at an active step."
        )
    elif can_resume:
        hint = "Resume re-opens the paused run at the current step without incrementing attempts."
    return {
        "can_resume": can_resume,
        "resume_step": suggested_step.value if can_resume and suggested_step is not None else None,
        "resume_tool": (
            tool_name_for_run_step(suggested_step)
            if can_resume and suggested_step is not None
            else None
        ),
        "requires_explicit_step": requires_explicit_step,
        "hint": hint,
    }


def register_ba_tools(server: Any) -> dict[str, Callable[..., Any]]:
    """Register BA-specific MCP tools and return handlers keyed by tool name."""

    @handle_mcp_errors
    async def ba_start_run(
        ctx: MCPContext,
        feature_key: str,
        run_id: str | None = None,
        mode: str = "auto",
        output_dir: str | None = None,
        notebook_lifecycle: str = "REUSE_FEATURE_NOTEBOOK",
        assumption_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del ctx
        clean_feature_key = _require_text(feature_key, field="feature_key")
        resolved_run_id = _optional_text(run_id, field="run_id") or _generate_run_id()
        resolved_output_dir = _normalize_output_dir(output_dir)
        resolved_mode = map_to_enum(mode, WorkflowMode, field_name="mode")
        resolved_notebook_lifecycle = _normalize_notebook_lifecycle(notebook_lifecycle)
        resolved_assumptions = _normalize_assumption_profile(assumption_profile)

        store = _store_for(clean_feature_key, resolved_run_id, resolved_output_dir)
        metadata = store.create(mode_requested=resolved_mode)
        machine = BARunStateMachine.from_store(store)
        existing_start = next(
            (record for record in machine.state.steps if record.step is RunStep.START_RUN),
            None,
        )
        warnings: list[str] = []
        if existing_start is not None and existing_start.status is RunStepStatus.COMPLETED:
            state = machine.state
            warnings.append("ba.start_run was already completed for this run; returning persisted state.")
        else:
            transition_metadata = _start_run_metadata(
                mode=resolved_mode,
                notebook_lifecycle=resolved_notebook_lifecycle,
                assumption_profile=resolved_assumptions,
            )
            try:
                machine.start_run(
                    metadata=transition_metadata,
                    note="Run root initialized",
                )
                state = machine.complete_step(
                    RunStep.START_RUN,
                    message="START_RUN completed",
                )
            except RunStateTransitionError as exc:
                _handle_transition_error(exc)

        return _tool_result(
            tool_name="ba.start_run",
            feature_key=clean_feature_key,
            run_id=resolved_run_id,
            output_dir=store.feature_paths.root,
            warnings=warnings,
            result={
                "run_id": resolved_run_id,
                "mode_requested": resolved_mode.value,
                "notebook_lifecycle": resolved_notebook_lifecycle,
                "assumption_profile": resolved_assumptions,
                "run_metadata_path": str(store.run_paths.run_metadata_json),
                "run_state_path": str(store.run_paths.run_state_json),
                "metadata": _serialize_model(metadata),
                "state": _serialize_model(state),
            },
        )

    @handle_mcp_errors
    async def ba_register_sources(
        ctx: MCPContext,
        feature_key: str,
        run_id: str,
        sources: list[dict[str, Any]],
        output_dir: str | None = None,
        update_only: bool = False,
    ) -> dict[str, Any]:
        del ctx
        clean_feature_key = _require_text(feature_key, field="feature_key")
        clean_run_id = _require_text(run_id, field="run_id")
        resolved_output_dir = _normalize_output_dir(output_dir)
        clean_update_only = _require_bool(update_only, field="update_only")
        if not isinstance(sources, list) or not sources:
            raise ValidationError("sources must be a non-empty list.")

        store = _store_for(clean_feature_key, clean_run_id, resolved_output_dir)
        store.create()
        machine = BARunStateMachine.from_store(store)
        _require_start_run_completed(machine)

        source_inputs = _normalize_source_inputs(sources)

        try:
            machine.start_step(
                RunStep.REGISTER_SOURCES,
                metadata={
                    "requested_source_count": len(source_inputs),
                    "update_only": clean_update_only,
                },
            )
        except RunStateTransitionError as exc:
            _handle_transition_error(exc)

        try:
            registration = store.register_sources(source_inputs, update_only=clean_update_only)
            state = machine.complete_step(
                RunStep.REGISTER_SOURCES,
                message="REGISTER_SOURCES completed",
                metadata={
                    "registered_source_count": len(registration.registered_sources),
                    "warning_count": len(registration.warnings),
                    "missing_critical_source_count": len(registration.missing_critical_sources),
                    "update_only": clean_update_only,
                },
            )
        except Exception as exc:
            try:
                machine.fail(
                    sanitize_error_message(str(exc)),
                    step=RunStep.REGISTER_SOURCES,
                    message="ba.register_sources failed",
                )
            except RunStateTransitionError:
                logger.debug("Unable to persist failure state for ba.register_sources", exc_info=True)
            raise

        return _tool_result(
            tool_name="ba.register_sources",
            feature_key=clean_feature_key,
            run_id=clean_run_id,
            output_dir=store.feature_paths.root,
            warnings=registration.warnings,
            result={
                "state": _serialize_model(state),
                "source_registration": _serialize_model(registration),
                "source_registration_path": str(store.run_paths.source_registration_json),
            },
        )

    @handle_mcp_errors
    async def ba_status(
        ctx: MCPContext,
        feature_key: str,
        run_id: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        del ctx
        clean_feature_key = _require_text(feature_key, field="feature_key")
        clean_run_id = _require_text(run_id, field="run_id")
        resolved_output_dir = _normalize_output_dir(output_dir)

        store, metadata, machine = _load_existing_run_state(
            feature_key=clean_feature_key,
            run_id=clean_run_id,
            output_dir=resolved_output_dir,
        )
        state = machine.state
        step_rows = _status_step_rows(state)
        next_step = _next_status_step(state)

        return _tool_result(
            tool_name="ba.status",
            feature_key=clean_feature_key,
            run_id=clean_run_id,
            output_dir=store.feature_paths.root,
            warnings=state.warnings,
            result={
                "metadata": _serialize_model(metadata),
                "state": _serialize_model(state),
                "progress": {
                    "total_planned_steps": len(step_rows),
                    "recorded_steps": len(state.steps),
                    "completed_steps": sum(
                        1
                        for record in state.steps
                        if record.status is RunStepStatus.COMPLETED
                    ),
                    "current_step": state.current_step.value if state.current_step is not None else None,
                    "current_tool": (
                        tool_name_for_run_step(state.current_step)
                        if state.current_step is not None
                        else None
                    ),
                    "next_step": next_step.value if next_step is not None else None,
                    "next_tool": tool_name_for_run_step(next_step) if next_step is not None else None,
                    "completed_step_names": [
                        row["step"] for row in step_rows if row["status"] == RunStepStatus.COMPLETED.value
                    ],
                    "not_started_step_names": [
                        row["step"] for row in step_rows if row["status"] == "NOT_STARTED"
                    ],
                },
                "resumability": _status_resumability(state, machine),
                "steps": step_rows,
                "last_event": _serialize_model(state.events[-1]) if state.events else None,
                "run_metadata_path": str(store.run_paths.run_metadata_json),
                "run_state_path": str(store.run_paths.run_state_json),
                "metrics": _load_metrics_payload(store),
            },
        )

    @handle_mcp_errors
    async def ba_validate_bundle(
        ctx: MCPContext,
        feature_key: str,
        run_id: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        del ctx
        clean_feature_key = _require_text(feature_key, field="feature_key")
        clean_run_id = _require_text(run_id, field="run_id")
        resolved_output_dir = _normalize_output_dir(output_dir)

        store, metadata, machine = _load_existing_run_state(
            feature_key=clean_feature_key,
            run_id=clean_run_id,
            output_dir=resolved_output_dir,
        )

        try:
            source_manifest = store.load_source_manifest()
            screen_catalog = store.load_screen_catalog()
            terminology = store.load_terminology()
            canonical_screens = _load_canonical_screens(store, screen_catalog)
        except Exception as exc:
            msg = (
                "ba.validate_bundle requires a rendered BA bundle baseline; run ba.run_pipeline "
                "through render first."
            )
            raise ValidationError(msg) from exc

        readiness = evaluate_readiness(
            list(canonical_screens.values()),
            feature_mode=metadata.mode_requested or WorkflowMode.AUTO,
        )
        screen_ids = [screen.screen_id for screen in screen_catalog.screens]
        validation = _validation_result_payload(
            validate_bundle_artifacts(
                store,
                source_manifest,
                screen_catalog,
                readiness,
                terminology=terminology,
            ),
            store=store,
            screen_ids=screen_ids,
        )
        metrics = _refresh_metrics_payload(
            store=store,
            metadata=metadata,
            state=machine.state,
            source=MetricsCaptureSource.VALIDATE_BUNDLE,
            source_manifest=source_manifest,
            screen_catalog=screen_catalog,
            readiness=readiness,
            validation_report=ValidationReport.model_validate(validation["report"]),
            notes=validation["report"]["warnings"],
        )

        return _tool_result(
            tool_name="ba.validate_bundle",
            feature_key=clean_feature_key,
            run_id=clean_run_id,
            output_dir=store.feature_paths.root,
            warnings=validation["report"]["warnings"],
            result={
                "metadata": _serialize_model(metadata),
                "state": _serialize_model(machine.state),
                "readiness": _serialize_model(readiness),
                "validation": validation,
                "metrics": metrics,
            },
        )

    @handle_mcp_errors
    async def ba_run_pipeline(
        ctx: MCPContext,
        notebook_id: str,
        feature_key: str,
        sources: list[dict[str, Any]],
        run_id: str | None = None,
        mode: str = "auto",
        output_dir: str | None = None,
        notebook_lifecycle: str = "REUSE_FEATURE_NOTEBOOK",
        assumption_profile: dict[str, Any] | None = None,
        update_only: bool = False,
        dry_run: bool = False,
        poll_budget_seconds: float = 120.0,
        ready_timeout_policy: str = "DEGRADE",
    ) -> dict[str, Any]:
        clean_feature_key = _require_text(feature_key, field="feature_key")
        clean_notebook_id = _require_text(notebook_id, field="notebook_id")
        clean_dry_run = _require_bool(dry_run, field="dry_run")
        clean_update_only = _require_bool(update_only, field="update_only")
        total_steps = 15
        warnings: list[str] = []
        step_results: dict[str, Any] = {}

        start_result = await ba_start_run(
            ctx,
            feature_key=clean_feature_key,
            run_id=run_id,
            mode=mode,
            output_dir=output_dir,
            notebook_lifecycle=notebook_lifecycle,
            assumption_profile=assumption_profile,
        )
        start_payload = start_result["structuredContent"]
        clean_run_id = start_payload["run_id"]
        step_results["start_run"] = start_payload["result"]
        warnings.extend(start_payload.get("warnings", []))
        await _report_progress(ctx, 1, total_steps, "START_RUN completed")

        register_result = await ba_register_sources(
            ctx,
            feature_key=clean_feature_key,
            run_id=clean_run_id,
            sources=sources,
            output_dir=output_dir,
            update_only=clean_update_only,
        )
        register_payload = register_result["structuredContent"]
        step_results["register_sources"] = register_payload["result"]
        warnings.extend(register_payload.get("warnings", []))
        await _report_progress(ctx, 2, total_steps, "REGISTER_SOURCES completed")

        resolved_output_dir = _normalize_output_dir(output_dir)
        store = _store_for(clean_feature_key, clean_run_id, resolved_output_dir)
        metadata = store.load_metadata()
        source_registration = store.load_source_registration()
        machine = BARunStateMachine.from_store(store)
        app = _resolve_app_context(ctx)
        adapter = BACapabilityAdapter(app.client)

        async def _ask_callable(
            prompt_text: str,
            *,
            source_ids: list[str] | None = None,
            conversation_id: str | None = None,
        ) -> Any:
            return await adapter.ask_with_structured_citations(
                clean_notebook_id,
                prompt_text,
                source_ids=source_ids,
                conversation_id=conversation_id,
            )

        async with _acquire_slot(app):
            try:
                machine.start_step(
                    RunStep.INGEST_AND_WAIT,
                    metadata={
                        "poll_budget_seconds": poll_budget_seconds,
                        "ready_timeout_policy": ready_timeout_policy,
                    },
                )
                ingest_result = await adapter.ingest_and_wait(
                    clean_notebook_id,
                    source_registration.manifest,
                    poll_budget_seconds=poll_budget_seconds,
                    ready_timeout_policy=map_to_enum(
                        ready_timeout_policy,
                        BAReadyTimeoutPolicy,
                        field_name="ready_timeout_policy",
                    ),
                    workspace_root=store.workspace_root,
                )
                source_registration = source_registration.model_copy(
                    update={
                        "manifest": ingest_result.manifest,
                        "warnings": _dedupe_warnings(
                            source_registration.warnings,
                            ingest_result.warnings,
                        ),
                    }
                )
                _store_source_registration(store, source_registration)
                if ingest_result.recommendation is HaltRecommendation.HALT:
                    state = machine.halt(
                        _warning_reason(
                            "Source ingest halted before downstream BA stages could run",
                            ingest_result.warnings,
                        ),
                        step=RunStep.INGEST_AND_WAIT,
                        message="INGEST_AND_WAIT halted",
                        metadata={"recommendation": ingest_result.recommendation.value},
                    )
                    step_results["ingest_and_wait"] = {
                        "ingest_result": ingest_result,
                        "state": state,
                    }
                    warnings.extend(ingest_result.warnings)
                    await _report_progress(ctx, 3, total_steps, "INGEST_AND_WAIT halted")
                    return _pipeline_response(
                        feature_key=clean_feature_key,
                        run_id=clean_run_id,
                        store=store,
                        warnings=warnings,
                        step_results=step_results,
                        state=state,
                        dry_run=clean_dry_run,
                        notebook_id=clean_notebook_id,
                        validation={"executed": False, "reason": "pipeline halted during ingest"},
                        stopped_after_step=RunStep.INGEST_AND_WAIT.value,
                        metrics=_refresh_metrics_payload(
                            store=store,
                            metadata=metadata,
                            state=state,
                            source=MetricsCaptureSource.RUN_PIPELINE,
                            source_manifest=source_registration.manifest,
                            notes=ingest_result.warnings,
                        ),
                    )
                if ingest_result.recommendation is HaltRecommendation.DEGRADE:
                    state = machine.mark_degraded(
                        _warning_reason(
                            "Source ingest degraded before downstream BA stages could run",
                            ingest_result.warnings,
                        ),
                        step=RunStep.INGEST_AND_WAIT,
                        message="INGEST_AND_WAIT degraded",
                        warning="one or more sources were not ready within the polling budget",
                        metadata={"recommendation": ingest_result.recommendation.value},
                    )
                    step_results["ingest_and_wait"] = {
                        "ingest_result": ingest_result,
                        "state": state,
                    }
                    warnings.extend(ingest_result.warnings)
                    await _report_progress(ctx, 3, total_steps, "INGEST_AND_WAIT degraded")
                    return _pipeline_response(
                        feature_key=clean_feature_key,
                        run_id=clean_run_id,
                        store=store,
                        warnings=warnings,
                        step_results=step_results,
                        state=state,
                        dry_run=clean_dry_run,
                        notebook_id=clean_notebook_id,
                        validation={"executed": False, "reason": "pipeline degraded during ingest"},
                        stopped_after_step=RunStep.INGEST_AND_WAIT.value,
                        metrics=_refresh_metrics_payload(
                            store=store,
                            metadata=metadata,
                            state=state,
                            source=MetricsCaptureSource.RUN_PIPELINE,
                            source_manifest=source_registration.manifest,
                            notes=ingest_result.warnings,
                        ),
                    )
                state = machine.complete_step(
                    RunStep.INGEST_AND_WAIT,
                    message="INGEST_AND_WAIT completed",
                    metadata={
                        "recommendation": ingest_result.recommendation.value,
                        "selected_source_count": len(ingest_result.selected_source_keys),
                    },
                )
                step_results["ingest_and_wait"] = {
                    "ingest_result": ingest_result,
                    "state": state,
                    "source_registration_path": str(store.run_paths.source_registration_json),
                }
                warnings.extend(ingest_result.warnings)
                await _report_progress(ctx, 3, total_steps, "INGEST_AND_WAIT completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.INGEST_AND_WAIT,
                    exc,
                    message="ba.run_pipeline ingest step failed",
                )
                raise

            try:
                machine.start_step(RunStep.SNAPSHOT_SOURCES)
                snapshot_records: list[SourceSnapshotRecord] = []
                for row in source_registration.manifest.rows:
                    if not row.notebook_source_id:
                        continue
                    snapshot = await adapter.collect_source_snapshot(
                        clean_notebook_id,
                        row.notebook_source_id,
                    )
                    snapshot_records.append(
                        store.persist_source_snapshot(
                            source_key=row.source_key,
                            notebook_source_id=snapshot.source_id,
                            title=snapshot.title,
                            source_type=snapshot.source_type,
                            content=snapshot.content,
                            char_count=snapshot.char_count,
                            guide_summary=snapshot.guide_summary,
                            guide_keywords=snapshot.guide_keywords,
                            is_fresh=snapshot.is_fresh,
                        )
                    )
                source_manifest = store.attach_snapshot_records(
                    source_registration.manifest,
                    snapshot_records,
                )
                source_registration = source_registration.model_copy(update={"manifest": source_manifest})
                _store_source_registration(store, source_registration)
                state = machine.complete_step(
                    RunStep.SNAPSHOT_SOURCES,
                    message="SNAPSHOT_SOURCES completed",
                    metadata={"snapshot_count": len(snapshot_records)},
                )
                step_results["snapshot_sources"] = {
                    "snapshots": snapshot_records,
                    "state": state,
                }
                await _report_progress(ctx, 4, total_steps, "SNAPSHOT_SOURCES completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.SNAPSHOT_SOURCES,
                    exc,
                    message="ba.run_pipeline snapshot step failed",
                )
                raise

            try:
                machine.start_step(RunStep.ASSESS_SOURCE_QUALITY)
                quality_assessments: list[SourceQualityAssessment] = []
                for row in source_manifest.rows:
                    if not row.snapshot_id:
                        continue
                    snapshot = store.load_source_snapshot(row.source_key, row.snapshot_id)
                    content = store.load_source_snapshot_text(row.source_key, row.snapshot_id)
                    assessment = assess_source_quality(row, snapshot, content)
                    store.save_source_quality_assessment(
                        row.source_key,
                        row.snapshot_id,
                        assessment,
                    )
                    quality_assessments.append(assessment)
                recommendations = {assessment.recommendation for assessment in quality_assessments}
                if HaltRecommendation.HALT in recommendations:
                    state = machine.halt(
                        "Source quality requires a hard stop before extraction can continue",
                        step=RunStep.ASSESS_SOURCE_QUALITY,
                        message="ASSESS_SOURCE_QUALITY halted",
                    )
                    step_results["assess_source_quality"] = {
                        "assessments": quality_assessments,
                        "state": state,
                    }
                    await _report_progress(ctx, 5, total_steps, "ASSESS_SOURCE_QUALITY halted")
                    return _pipeline_response(
                        feature_key=clean_feature_key,
                        run_id=clean_run_id,
                        store=store,
                        warnings=warnings,
                        step_results=step_results,
                        state=state,
                        dry_run=clean_dry_run,
                        notebook_id=clean_notebook_id,
                        validation={"executed": False, "reason": "pipeline halted by source quality"},
                        stopped_after_step=RunStep.ASSESS_SOURCE_QUALITY.value,
                        metrics=_refresh_metrics_payload(
                            store=store,
                            metadata=metadata,
                            state=state,
                            source=MetricsCaptureSource.RUN_PIPELINE,
                            source_manifest=source_manifest,
                        ),
                    )
                if HaltRecommendation.CLARIFICATION_FIRST in recommendations:
                    state = machine.mark_degraded(
                        "Source quality requires clarification before extraction can continue",
                        step=RunStep.ASSESS_SOURCE_QUALITY,
                        message="ASSESS_SOURCE_QUALITY degraded",
                        warning="one or more critical sources need clarification-first handling",
                    )
                    step_results["assess_source_quality"] = {
                        "assessments": quality_assessments,
                        "state": state,
                    }
                    await _report_progress(ctx, 5, total_steps, "ASSESS_SOURCE_QUALITY degraded")
                    return _pipeline_response(
                        feature_key=clean_feature_key,
                        run_id=clean_run_id,
                        store=store,
                        warnings=warnings,
                        step_results=step_results,
                        state=state,
                        dry_run=clean_dry_run,
                        notebook_id=clean_notebook_id,
                        validation={"executed": False, "reason": "pipeline degraded by source quality"},
                        stopped_after_step=RunStep.ASSESS_SOURCE_QUALITY.value,
                        metrics=_refresh_metrics_payload(
                            store=store,
                            metadata=metadata,
                            state=state,
                            source=MetricsCaptureSource.RUN_PIPELINE,
                            source_manifest=source_manifest,
                        ),
                    )
                state = machine.complete_step(
                    RunStep.ASSESS_SOURCE_QUALITY,
                    message="ASSESS_SOURCE_QUALITY completed",
                    metadata={"assessment_count": len(quality_assessments)},
                )
                step_results["assess_source_quality"] = {
                    "assessments": quality_assessments,
                    "state": state,
                }
                await _report_progress(ctx, 5, total_steps, "ASSESS_SOURCE_QUALITY completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.ASSESS_SOURCE_QUALITY,
                    exc,
                    message="ba.run_pipeline source-quality step failed",
                )
                raise

            try:
                machine.start_step(RunStep.BUILD_SOURCE_MANIFEST)
                source_manifest = build_source_manifest_document(
                    source_manifest,
                    snapshots=snapshot_records,
                    quality_assessments=quality_assessments,
                )
                store.save_source_manifest_artifacts(
                    source_manifest,
                    markdown=render_source_manifest_markdown(source_manifest),
                )
                source_registration = source_registration.model_copy(update={"manifest": source_manifest})
                _store_source_registration(store, source_registration)
                state = machine.complete_step(
                    RunStep.BUILD_SOURCE_MANIFEST,
                    message="BUILD_SOURCE_MANIFEST completed",
                    metadata={"source_count": len(source_manifest.rows)},
                )
                step_results["build_source_manifest"] = {
                    "manifest": source_manifest,
                    "state": state,
                    "source_manifest_json": str(store.feature_paths.source_manifest_json),
                    "source_manifest_markdown": str(store.feature_paths.source_manifest_markdown),
                }
                await _report_progress(ctx, 6, total_steps, "BUILD_SOURCE_MANIFEST completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.BUILD_SOURCE_MANIFEST,
                    exc,
                    message="ba.run_pipeline source-manifest step failed",
                )
                raise

            source_scope = _source_scope_text(source_manifest)
            source_ids = _source_ids_from_manifest(source_manifest)
            conversation_id: str | None = None

            try:
                machine.start_step(RunStep.NORMALIZE_TERMINOLOGY)
                terminology_result = await extract_terminology_document(
                    _ask_callable,
                    feature_key=clean_feature_key,
                    run_id=clean_run_id,
                    manifest=source_manifest,
                    source_scope=source_scope,
                    source_ids=source_ids,
                    snapshots=snapshot_records,
                    conversation_id=conversation_id,
                )
                conversation_id = terminology_result.conversation_id
                store.save_terminology_artifacts(
                    terminology_result.document,
                    markdown=render_terminology_markdown(terminology_result.document),
                )
                state = machine.complete_step(
                    RunStep.NORMALIZE_TERMINOLOGY,
                    message="NORMALIZE_TERMINOLOGY completed",
                    metadata={"term_count": len(terminology_result.document.entries)},
                )
                step_results["normalize_terminology"] = {
                    "terminology": terminology_result,
                    "state": state,
                    "terminology_json": str(store.feature_paths.terminology_json),
                    "terminology_markdown": str(store.feature_paths.terminology_markdown),
                }
                warnings.extend(terminology_result.warnings)
                await _report_progress(ctx, 7, total_steps, "NORMALIZE_TERMINOLOGY completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.NORMALIZE_TERMINOLOGY,
                    exc,
                    message="ba.run_pipeline terminology step failed",
                )
                raise

            try:
                machine.start_step(RunStep.BUILD_SCREEN_CATALOG)
                screen_catalog_result = await extract_screen_catalog_document(
                    _ask_callable,
                    feature_key=clean_feature_key,
                    run_id=clean_run_id,
                    manifest=source_manifest,
                    source_scope=source_scope,
                    terminology=terminology_result.document,
                    source_ids=source_ids,
                    snapshots=snapshot_records,
                    conversation_id=conversation_id,
                )
                conversation_id = screen_catalog_result.conversation_id
                store.save_screen_catalog(screen_catalog_result.document)
                state = machine.complete_step(
                    RunStep.BUILD_SCREEN_CATALOG,
                    message="BUILD_SCREEN_CATALOG completed",
                    metadata={"screen_count": len(screen_catalog_result.document.screens)},
                )
                step_results["build_screen_catalog"] = {
                    "screen_catalog": screen_catalog_result,
                    "state": state,
                    "screen_catalog_json": str(store.feature_paths.screen_catalog_json),
                }
                warnings.extend(screen_catalog_result.warnings)
                await _report_progress(ctx, 8, total_steps, "BUILD_SCREEN_CATALOG completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.BUILD_SCREEN_CATALOG,
                    exc,
                    message="ba.run_pipeline screen-catalog step failed",
                )
                raise

            try:
                machine.start_step(RunStep.EXTRACT_CANONICAL)
                canonical_results = []
                canonical_screens = []
                for catalog_entry in screen_catalog_result.document.screens:
                    canonical_result = await extract_canonical_screen(
                        _ask_callable,
                        feature_key=clean_feature_key,
                        run_id=clean_run_id,
                        screen=catalog_entry,
                        manifest=source_manifest,
                        mode=map_to_enum(mode, WorkflowMode, field_name="mode"),
                        source_scope=source_scope,
                        terminology=terminology_result.document,
                        source_ids=source_ids,
                        snapshots=snapshot_records,
                        conversation_id=conversation_id,
                    )
                    conversation_id = canonical_result.conversation_id
                    store.save_canonical_screen(canonical_result.screen)
                    canonical_results.append(canonical_result)
                    canonical_screens.append(canonical_result.screen)
                    warnings.extend(canonical_result.warnings)
                state = machine.complete_step(
                    RunStep.EXTRACT_CANONICAL,
                    message="EXTRACT_CANONICAL completed",
                    metadata={"screen_count": len(canonical_results)},
                )
                step_results["extract_canonical"] = {
                    "canonical_results": canonical_results,
                    "state": state,
                }
                await _report_progress(ctx, 9, total_steps, "EXTRACT_CANONICAL completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.EXTRACT_CANONICAL,
                    exc,
                    message="ba.run_pipeline canonical-extraction step failed",
                )
                raise

            try:
                machine.start_step(RunStep.REVIEW_GAPS)
                gap_reviews = {
                    screen.screen_id: build_gap_review_document(screen)
                    for screen in canonical_screens
                }
                state = machine.complete_step(
                    RunStep.REVIEW_GAPS,
                    message="REVIEW_GAPS completed",
                    metadata={"screen_count": len(gap_reviews)},
                )
                step_results["review_gaps"] = {
                    "gap_reviews": gap_reviews,
                    "state": state,
                }
                await _report_progress(ctx, 10, total_steps, "REVIEW_GAPS completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.REVIEW_GAPS,
                    exc,
                    message="ba.run_pipeline gap-review step failed",
                )
                raise

            try:
                machine.start_step(RunStep.GENERATE_MATRICES)
                matrix_bundles = {
                    screen.screen_id: build_screen_matrix_bundle(screen)
                    for screen in canonical_screens
                }
                for screen_id, bundle in matrix_bundles.items():
                    store.save_screen_matrix_artifacts(
                        screen_id,
                        field_csv=render_field_matrix_csv(bundle.field_rows),
                        action_rule_csv=render_action_rule_matrix_csv(bundle.action_rule_rows),
                        api_csv=render_api_matrix_csv(bundle.api_rows),
                    )
                state = machine.complete_step(
                    RunStep.GENERATE_MATRICES,
                    message="GENERATE_MATRICES completed",
                    metadata={"screen_count": len(matrix_bundles)},
                )
                step_results["generate_matrices"] = {
                    "matrix_bundles": matrix_bundles,
                    "state": state,
                }
                await _report_progress(ctx, 11, total_steps, "GENERATE_MATRICES completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.GENERATE_MATRICES,
                    exc,
                    message="ba.run_pipeline matrix step failed",
                )
                raise

            try:
                machine.start_step(RunStep.EVALUATE_READINESS)
                readiness_summary = evaluate_readiness(
                    canonical_screens,
                    feature_mode=map_to_enum(mode, WorkflowMode, field_name="mode"),
                )
                state = machine.complete_step(
                    RunStep.EVALUATE_READINESS,
                    message="EVALUATE_READINESS completed",
                    metadata={"decision": readiness_summary.decision.value},
                )
                step_results["evaluate_readiness"] = {
                    "readiness": readiness_summary,
                    "state": state,
                }
                warnings.extend(readiness_summary.warnings)
                await _report_progress(ctx, 12, total_steps, "EVALUATE_READINESS completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.EVALUATE_READINESS,
                    exc,
                    message="ba.run_pipeline readiness step failed",
                )
                raise

            if clean_dry_run:
                state = machine.halt(
                    "dry_run requested stop after readiness assessment",
                    step=None,
                    message="DRY RUN stop after EVALUATE_READINESS",
                    metadata={"dry_run": True},
                )
                return _pipeline_response(
                    feature_key=clean_feature_key,
                    run_id=clean_run_id,
                    store=store,
                    warnings=warnings,
                    step_results=step_results,
                    state=state,
                    dry_run=clean_dry_run,
                    notebook_id=clean_notebook_id,
                    validation={"executed": False, "reason": "dry_run requested stop after readiness assessment"},
                    stopped_after_step=RunStep.EVALUATE_READINESS.value,
                    metrics=_refresh_metrics_payload(
                        store=store,
                        metadata=metadata,
                        state=state,
                        source=MetricsCaptureSource.RUN_PIPELINE,
                        source_manifest=source_manifest,
                        screen_catalog=screen_catalog_result.document,
                        readiness=readiness_summary,
                        notes=readiness_summary.warnings,
                    ),
                )

            if readiness_summary.decision.value not in {
                "READY_FOR_FE_AND_BE",
                "READY_FOR_FE_WITH_PROVISIONAL_CONTRACT",
            }:
                state = machine.halt(
                    "readiness assessment concluded the pipeline cannot proceed to contract and render stages",
                    step=None,
                    message="Pipeline halted after readiness assessment",
                    metadata={"decision": readiness_summary.decision.value},
                )
                return _pipeline_response(
                    feature_key=clean_feature_key,
                    run_id=clean_run_id,
                    store=store,
                    warnings=warnings,
                    step_results=step_results,
                    state=state,
                    dry_run=clean_dry_run,
                    notebook_id=clean_notebook_id,
                    validation={"executed": False, "reason": "pipeline halted by readiness decision"},
                    stopped_after_step=RunStep.EVALUATE_READINESS.value,
                    metrics=_refresh_metrics_payload(
                        store=store,
                        metadata=metadata,
                        state=state,
                        source=MetricsCaptureSource.RUN_PIPELINE,
                        source_manifest=source_manifest,
                        screen_catalog=screen_catalog_result.document,
                        readiness=readiness_summary,
                        notes=readiness_summary.warnings,
                    ),
                )

            try:
                machine.start_step(RunStep.GENERATE_CONTRACTS)
                readiness_by_screen = _screen_readiness_index(readiness_summary)
                contract_screens: list[str] = []
                rendered_contracts: dict[str, dict[str, str]] = {}
                for screen in canonical_screens:
                    readiness = readiness_by_screen[screen.screen_id]
                    contract_artifacts = build_provisional_contract_artifacts(
                        screen,
                        matrices=matrix_bundles[screen.screen_id],
                        readiness=readiness,
                    )
                    if contract_artifacts is None:
                        continue
                    contract_yaml = render_contract_yaml(contract_artifacts.openapi_document)
                    mock_data_json = render_mock_data_json(contract_artifacts.mock_data)
                    store.save_contract_yaml(screen.screen_id, contract_yaml)
                    store.save_mock_data_json(screen.screen_id, mock_data_json)
                    rendered_contracts[screen.screen_id] = {
                        "contract_yaml": contract_yaml,
                        "mock_data_json": mock_data_json,
                    }
                    contract_screens.append(screen.screen_id)
                state = machine.complete_step(
                    RunStep.GENERATE_CONTRACTS,
                    message="GENERATE_CONTRACTS completed",
                    metadata={"screen_count": len(contract_screens)},
                )
                step_results["generate_contracts"] = {
                    "contract_screens": contract_screens,
                    "state": state,
                }
                await _report_progress(ctx, 13, total_steps, "GENERATE_CONTRACTS completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.GENERATE_CONTRACTS,
                    exc,
                    message="ba.run_pipeline contract step failed",
                )
                raise

            try:
                machine.start_step(RunStep.RENDER_BUNDLE)
                screen_catalog_by_id = _screen_catalog_index(screen_catalog_result.document)
                screen_artifacts: list[ScreenBundleArtifact] = []
                for screen in canonical_screens:
                    catalog_entry = screen_catalog_by_id[screen.screen_id]
                    review = gap_reviews[screen.screen_id]
                    readiness = readiness_by_screen[screen.screen_id]
                    matrices = matrix_bundles[screen.screen_id]
                    fe_markdown = render_fe_spec_markdown(
                        catalog_entry,
                        screen,
                        matrices=matrices,
                        review=review,
                        readiness=readiness,
                    )
                    be_markdown = render_be_spec_markdown(
                        catalog_entry,
                        screen,
                        matrices=matrices,
                        review=review,
                        readiness=readiness,
                    )
                    questions_markdown = render_question_backlog_markdown(review)
                    store.save_fe_spec_markdown(screen.screen_id, fe_markdown)
                    store.save_be_spec_markdown(screen.screen_id, be_markdown)
                    store.save_questions_markdown(screen.screen_id, questions_markdown)
                    rendered_contract = rendered_contracts.get(screen.screen_id, {})
                    screen_artifacts.append(
                        ScreenBundleArtifact(
                            screen_id=screen.screen_id,
                            canonical_json=screen.model_dump_json(indent=2),
                            fe_markdown=fe_markdown,
                            be_markdown=be_markdown,
                            questions_markdown=questions_markdown,
                            field_matrix_csv=render_field_matrix_csv(matrices.field_rows),
                            action_rule_matrix_csv=render_action_rule_matrix_csv(
                                matrices.action_rule_rows
                            ),
                            api_matrix_csv=render_api_matrix_csv(matrices.api_rows),
                            contract_yaml=rendered_contract.get("contract_yaml"),
                            mock_data_json=rendered_contract.get("mock_data_json"),
                        )
                    )
                bundle_files = write_bundle_layout(
                    store,
                    source_manifest=source_manifest,
                    screen_catalog=screen_catalog_result.document,
                    readiness=readiness_summary,
                    screen_artifacts=screen_artifacts,
                    terminology=terminology_result.document,
                    run_audit=store.load_run_audit(),
                )
                state = machine.complete_step(
                    RunStep.RENDER_BUNDLE,
                    message="RENDER_BUNDLE completed",
                    metadata={"bundle_file_count": len(bundle_files)},
                )
                step_results["render_bundle"] = {
                    "bundle_files": bundle_files,
                    "state": state,
                }
                await _report_progress(ctx, 14, total_steps, "RENDER_BUNDLE completed")
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.RENDER_BUNDLE,
                    exc,
                    message="ba.run_pipeline render step failed",
                )
                raise

            screen_ids = [screen.screen_id for screen in screen_catalog_result.document.screens]
            try:
                machine.start_step(
                    RunStep.VALIDATE_BUNDLE,
                    metadata={"bundle_file_count": len(bundle_files)},
                )
                bundle_files = write_bundle_layout(
                    store,
                    source_manifest=source_manifest,
                    screen_catalog=screen_catalog_result.document,
                    readiness=readiness_summary,
                    screen_artifacts=screen_artifacts,
                    terminology=terminology_result.document,
                    run_audit=store.load_run_audit(),
                )
                report = validate_bundle_artifacts(
                    store,
                    source_manifest,
                    screen_catalog_result.document,
                    readiness_summary,
                    screen_artifacts=screen_artifacts,
                    terminology=terminology_result.document,
                )
            except Exception as exc:
                _fail_pipeline_step(
                    machine,
                    RunStep.VALIDATE_BUNDLE,
                    exc,
                    message="ba.run_pipeline validation step failed",
                )
                raise

            validation_result = _validation_result_payload(
                report,
                store=store,
                screen_ids=screen_ids,
            )
            step_results["validate_bundle"] = validation_result
            bundle_files.update(
                {
                    f"screens/{screen_id}/qa-report.json": path
                    for screen_id, path in validation_result["qa_report_paths"].items()
                }
            )

            if report.status.value == "FAIL":
                  state = machine.halt(
                      "bundle validation reported failing findings",
                      step=RunStep.VALIDATE_BUNDLE,
                      message="VALIDATE_BUNDLE halted",
                    metadata={
                        "status": report.status.value,
                        "finding_count": len(report.findings),
                          "warning_count": len(report.warnings),
                      },
                  )
                  bundle_files = write_bundle_layout(
                      store,
                      source_manifest=source_manifest,
                      screen_catalog=screen_catalog_result.document,
                      readiness=readiness_summary,
                      screen_artifacts=_attach_qa_reports_to_screen_artifacts(store, screen_artifacts),
                      terminology=terminology_result.document,
                      run_audit=store.load_run_audit(),
                  )
                  bundle_files.update(
                      {
                          f"screens/{screen_id}/qa-report.json": path
                          for screen_id, path in validation_result["qa_report_paths"].items()
                      }
                  )
                  await _report_progress(ctx, 15, total_steps, "VALIDATE_BUNDLE halted")
                  return _pipeline_response(
                      feature_key=clean_feature_key,
                    run_id=clean_run_id,
                    store=store,
                    warnings=_dedupe_warnings(warnings, report.warnings),
                    step_results=step_results,
                    state=state,
                    dry_run=clean_dry_run,
                    notebook_id=clean_notebook_id,
                    bundle_files=bundle_files,
                    validation=validation_result,
                    stopped_after_step=RunStep.VALIDATE_BUNDLE.value,
                    metrics=_refresh_metrics_payload(
                        store=store,
                        metadata=metadata,
                        state=state,
                        source=MetricsCaptureSource.RUN_PIPELINE,
                        source_manifest=source_manifest,
                        screen_catalog=screen_catalog_result.document,
                        readiness=readiness_summary,
                        validation_report=report,
                        notes=report.warnings,
                    ),
                )

            machine.complete_step(
                RunStep.VALIDATE_BUNDLE,
                message="VALIDATE_BUNDLE completed",
                metadata={
                    "status": report.status.value,
                    "finding_count": len(report.findings),
                    "warning_count": len(report.warnings),
                },
            )
            await _report_progress(ctx, 15, total_steps, "VALIDATE_BUNDLE completed")

            state = machine.complete_run(
                message="BA run_pipeline completed",
                metadata={
                    "validation_executed": True,
                    "validation_status": report.status.value,
                    "bundle_file_count": len(bundle_files),
                },
            )
            bundle_files = write_bundle_layout(
                store,
                source_manifest=source_manifest,
                screen_catalog=screen_catalog_result.document,
                readiness=readiness_summary,
                screen_artifacts=_attach_qa_reports_to_screen_artifacts(store, screen_artifacts),
                terminology=terminology_result.document,
                run_audit=store.load_run_audit(),
            )
            bundle_files.update(
                {
                    f"screens/{screen_id}/qa-report.json": path
                    for screen_id, path in validation_result["qa_report_paths"].items()
                }
            )
            return _pipeline_response(
                feature_key=clean_feature_key,
                run_id=clean_run_id,
                store=store,
                warnings=_dedupe_warnings(warnings, report.warnings),
                step_results=step_results,
                state=state,
                dry_run=clean_dry_run,
                notebook_id=clean_notebook_id,
                bundle_files=bundle_files,
                validation=validation_result,
                metrics=_refresh_metrics_payload(
                    store=store,
                    metadata=metadata,
                    state=state,
                    source=MetricsCaptureSource.RUN_PIPELINE,
                    source_manifest=source_manifest,
                    screen_catalog=screen_catalog_result.document,
                    readiness=readiness_summary,
                    validation_report=report,
                    notes=report.warnings,
                ),
            )

    @handle_mcp_errors
    async def ba_rerun_impacted(
        ctx: MCPContext,
        notebook_id: str,
        feature_key: str,
        run_id: str,
        output_dir: str | None = None,
        source_keys: list[str] | None = None,
        poll_budget_seconds: float = 120.0,
        ready_timeout_policy: str = "DEGRADE",
    ) -> dict[str, Any]:
          clean_feature_key = _require_text(feature_key, field="feature_key")
          clean_run_id = _require_text(run_id, field="run_id")
          clean_notebook_id = _require_text(notebook_id, field="notebook_id")
          resolved_output_dir = _normalize_output_dir(output_dir)

          store, metadata, _machine = _load_existing_run_state(
              feature_key=clean_feature_key,
              run_id=clean_run_id,
              output_dir=resolved_output_dir,
          )

          try:
              previous_registration = store.load_source_registration()
              previous_manifest = store.load_source_manifest()
              previous_terminology = store.load_terminology()
              previous_screen_catalog = store.load_screen_catalog()
              previous_canonical_screens = _load_canonical_screens(store, previous_screen_catalog)
          except Exception as exc:  # pragma: no cover - defensive error boundary
              msg = "ba.rerun_impacted requires an existing BA bundle baseline; run ba.run_pipeline first."
              raise ValidationError(msg) from exc

          if not previous_manifest.rows or not previous_canonical_screens:
              raise ValidationError(
                  "ba.rerun_impacted requires persisted source and screen artifacts from a prior BA run."
              )

          previous_snapshots = _load_snapshot_texts(store, previous_manifest)
          if not previous_snapshots:
              raise ValidationError(
                  "ba.rerun_impacted requires persisted source snapshots from the prior run."
              )

          feature_mode = metadata.mode_requested or WorkflowMode.AUTO
          previous_readiness = evaluate_readiness(
              list(previous_canonical_screens.values()),
              feature_mode=feature_mode,
          )

          manifest_source_keys = tuple(row.source_key for row in previous_manifest.rows)
          if source_keys is None:
              selected_source_keys = manifest_source_keys
          else:
              if not isinstance(source_keys, list):
                  raise ValidationError("source_keys must be a list when provided.")
              deduped: dict[str, None] = {}
              for raw_source_key in source_keys:
                  text = _require_text(raw_source_key, field="source_keys[]")
                  if text not in manifest_source_keys:
                      raise ValidationError(
                          f"source_keys contains unknown source_key '{text}'."
                      )
                  deduped.setdefault(text, None)
              selected_source_keys = tuple(deduped)
          if not selected_source_keys:
              raise ValidationError("source_keys resolved to an empty selection.")

          warnings: list[str] = []
          current_snapshot_texts = dict(previous_snapshots)
          current_records_by_key = {
              source_key: snapshot.record for source_key, snapshot in previous_snapshots.items()
          }
          current_quality_by_key = {
              assessment.source_key: assessment
              for assessment in _load_quality_assessments(store, previous_manifest)
          }

          app = _resolve_app_context(ctx)
          adapter = BACapabilityAdapter(app.client)

          async def _ask_callable(
              prompt_text: str,
              *,
              source_ids: list[str] | None = None,
              conversation_id: str | None = None,
          ) -> Any:
              return await adapter.ask_with_structured_citations(
                  clean_notebook_id,
                  prompt_text,
                  source_ids=source_ids,
                  conversation_id=conversation_id,
              )

          async with _acquire_slot(app):
              ingest_result = await adapter.ingest_and_wait(
                  clean_notebook_id,
                  previous_manifest,
                  source_keys=selected_source_keys,
                  poll_budget_seconds=poll_budget_seconds,
                  ready_timeout_policy=map_to_enum(
                      ready_timeout_policy,
                      BAReadyTimeoutPolicy,
                      field_name="ready_timeout_policy",
                  ),
                  workspace_root=store.workspace_root,
              )
              warnings.extend(ingest_result.warnings)

              if ingest_result.recommendation is not HaltRecommendation.PROCEED:
                  reason = _warning_reason(
                      "source ingest degraded before impacted rerun could proceed",
                      ingest_result.warnings,
                  )
                  plan = RerunPlan(
                      feature_key=clean_feature_key,
                      run_id=clean_run_id,
                      decision=RerunDecision.FULL_FEATURE,
                      escalation_reasons=[reason],
                      warnings=_dedupe_warnings(warnings),
                  )
                  changelog = render_rerun_changelog(
                      plan,
                      screens=list(previous_canonical_screens.values()),
                      readiness=previous_readiness,
                  )
                  impacted_path = store.save_impacted_screens_json(plan.model_dump_json(indent=2))
                  changelog_path = store.save_changelog_markdown(changelog)
                  return _tool_result(
                      tool_name="ba.rerun_impacted",
                      feature_key=clean_feature_key,
                      run_id=clean_run_id,
                      output_dir=store.feature_paths.root,
                      warnings=_dedupe_warnings(warnings, plan.warnings),
                      result={
                          "notebook_id": clean_notebook_id,
                          "applied": False,
                          "selected_source_keys": list(selected_source_keys),
                          "plan": _serialize_model(plan),
                          "impacted_screens_path": str(impacted_path),
                          "changelog_path": str(changelog_path),
                          "bundle_files": {},
                          "metrics": _refresh_metrics_payload(
                              store=store,
                              metadata=metadata,
                              state=store.load_run_state(),
                              source=MetricsCaptureSource.RERUN_IMPACTED,
                              source_manifest=previous_manifest,
                              screen_catalog=previous_screen_catalog,
                              readiness=previous_readiness,
                              rerun_plan=plan,
                              notes=_dedupe_warnings(warnings, plan.warnings),
                          ),
                      },
                  )

              for row in ingest_result.manifest.rows:
                  if row.source_key not in selected_source_keys or not row.notebook_source_id:
                      continue
                  snapshot = await adapter.collect_source_snapshot(
                      clean_notebook_id,
                      row.notebook_source_id,
                  )
                  record = store.persist_source_snapshot(
                      source_key=row.source_key,
                      notebook_source_id=snapshot.source_id,
                      title=snapshot.title,
                      source_type=snapshot.source_type,
                      content=snapshot.content,
                      guide_summary=snapshot.guide_summary,
                      guide_keywords=snapshot.guide_keywords,
                      is_fresh=snapshot.is_fresh,
                      char_count=snapshot.char_count,
                  )
                  assessment = assess_source_quality(row, record, snapshot.content)
                  store.save_source_quality_assessment(row.source_key, record.snapshot_id, assessment)
                  current_snapshot_texts[row.source_key] = SourceSnapshotText(
                      record=record,
                      content=snapshot.content,
                  )
                  current_records_by_key[row.source_key] = record
                  current_quality_by_key[row.source_key] = assessment

              current_manifest = build_source_manifest_document(
                  ingest_result.manifest,
                  snapshots=list(current_records_by_key.values()),
                  quality_assessments=list(current_quality_by_key.values()),
              )

              light_plan = build_rerun_plan(
                  feature_key=clean_feature_key,
                  run_id=clean_run_id,
                  previous_manifest=previous_manifest,
                  current_manifest=current_manifest,
                  previous_screen_catalog=previous_screen_catalog,
                  current_screen_catalog=previous_screen_catalog,
                  previous_terminology=previous_terminology,
                  current_terminology=previous_terminology,
                  previous_canonical_screens=previous_canonical_screens,
                  previous_snapshots=previous_snapshots,
                  current_snapshots=current_snapshot_texts,
                  matrix_source_links=_load_matrix_source_links(
                      store,
                      [screen.screen_id for screen in previous_screen_catalog.screens],
                  ),
              )
              if light_plan.decision is RerunDecision.NO_CHANGES:
                  changelog = render_rerun_changelog(
                      light_plan,
                      screens=list(previous_canonical_screens.values()),
                      readiness=previous_readiness,
                  )
                  impacted_path = store.save_impacted_screens_json(
                      light_plan.model_dump_json(indent=2)
                  )
                  changelog_path = store.save_changelog_markdown(changelog)
                  return _tool_result(
                      tool_name="ba.rerun_impacted",
                      feature_key=clean_feature_key,
                      run_id=clean_run_id,
                      output_dir=store.feature_paths.root,
                      warnings=_dedupe_warnings(warnings, light_plan.warnings),
                      result={
                          "notebook_id": clean_notebook_id,
                          "applied": False,
                          "selected_source_keys": list(selected_source_keys),
                          "plan": _serialize_model(light_plan),
                          "impacted_screens_path": str(impacted_path),
                          "changelog_path": str(changelog_path),
                          "bundle_files": {},
                          "metrics": _refresh_metrics_payload(
                              store=store,
                              metadata=metadata,
                              state=store.load_run_state(),
                              source=MetricsCaptureSource.RERUN_IMPACTED,
                              source_manifest=current_manifest,
                              screen_catalog=previous_screen_catalog,
                              readiness=previous_readiness,
                              rerun_plan=light_plan,
                              notes=_dedupe_warnings(warnings, light_plan.warnings),
                          ),
                      },
                  )

              source_scope = _source_scope_text(current_manifest)
              current_snapshot_records = [
                  current_records_by_key[row.source_key]
                  for row in current_manifest.rows
                  if row.source_key in current_records_by_key
              ]
              source_ids = _source_ids_from_manifest(current_manifest)

              terminology_result = await extract_terminology_document(
                  _ask_callable,
                  feature_key=clean_feature_key,
                  run_id=clean_run_id,
                  manifest=current_manifest,
                  source_scope=source_scope,
                  source_ids=source_ids,
                  snapshots=current_snapshot_records,
              )
              screen_catalog_result = await extract_screen_catalog_document(
                  _ask_callable,
                  feature_key=clean_feature_key,
                  run_id=clean_run_id,
                  manifest=current_manifest,
                  source_scope=source_scope,
                  terminology=terminology_result.document,
                  source_ids=source_ids,
                  snapshots=current_snapshot_records,
                  prior_catalog=previous_screen_catalog,
              )
              warnings.extend(terminology_result.warnings)
              warnings.extend(screen_catalog_result.warnings)

              plan = build_rerun_plan(
                  feature_key=clean_feature_key,
                  run_id=clean_run_id,
                  previous_manifest=previous_manifest,
                  current_manifest=current_manifest,
                  previous_screen_catalog=previous_screen_catalog,
                  current_screen_catalog=screen_catalog_result.document,
                  previous_terminology=previous_terminology,
                  current_terminology=terminology_result.document,
                  previous_canonical_screens=previous_canonical_screens,
                  previous_snapshots=previous_snapshots,
                  current_snapshots=current_snapshot_texts,
                  matrix_source_links=_load_matrix_source_links(
                      store,
                      [screen.screen_id for screen in previous_screen_catalog.screens],
                  ),
              )

              if plan.decision is not RerunDecision.SELECTIVE:
                  changelog = render_rerun_changelog(
                      plan,
                      screens=list(previous_canonical_screens.values()),
                      readiness=previous_readiness,
                  )
                  impacted_path = store.save_impacted_screens_json(plan.model_dump_json(indent=2))
                  changelog_path = store.save_changelog_markdown(changelog)
                  return _tool_result(
                      tool_name="ba.rerun_impacted",
                      feature_key=clean_feature_key,
                      run_id=clean_run_id,
                      output_dir=store.feature_paths.root,
                      warnings=_dedupe_warnings(
                          warnings,
                          plan.warnings,
                      ),
                      result={
                          "notebook_id": clean_notebook_id,
                          "applied": False,
                          "selected_source_keys": list(selected_source_keys),
                          "plan": _serialize_model(plan),
                          "impacted_screens_path": str(impacted_path),
                          "changelog_path": str(changelog_path),
                          "bundle_files": {},
                          "metrics": _refresh_metrics_payload(
                              store=store,
                              metadata=metadata,
                              state=store.load_run_state(),
                              source=MetricsCaptureSource.RERUN_IMPACTED,
                              source_manifest=current_manifest,
                              screen_catalog=screen_catalog_result.document,
                              readiness=previous_readiness,
                              rerun_plan=plan,
                              notes=_dedupe_warnings(warnings, plan.warnings),
                          ),
                      },
                  )

              screen_catalog_by_id = _screen_catalog_index(screen_catalog_result.document)
              impacted_screen_ids = [item.screen_id for item in plan.impacted_screens]
              combined_screens = dict(previous_canonical_screens)
              for screen_id in impacted_screen_ids:
                  screen_entry = screen_catalog_by_id[screen_id]
                  canonical_result = await extract_canonical_screen(
                      _ask_callable,
                      feature_key=clean_feature_key,
                      run_id=clean_run_id,
                      screen=screen_entry,
                      manifest=current_manifest,
                      mode=feature_mode,
                      source_scope=source_scope,
                      terminology=terminology_result.document,
                      source_ids=source_ids,
                      snapshots=current_snapshot_records,
                  )
                  warnings.extend(canonical_result.warnings)
                  combined_screens[screen_id] = canonical_result.screen
                  store.save_canonical_screen(canonical_result.screen)

          current_manifest = attach_source_screen_usage(
              current_manifest,
              screen_catalog=screen_catalog_result.document,
              canonical_screens=combined_screens,
          )
          store.save_source_manifest_artifacts(
              current_manifest,
              markdown=render_source_manifest_markdown(current_manifest),
          )
          store.save_terminology_artifacts(
              terminology_result.document,
              markdown=render_terminology_markdown(terminology_result.document),
          )
          store.save_screen_catalog(screen_catalog_result.document)

          updated_registration = previous_registration.model_copy(
              update={
                  "manifest": current_manifest,
                  "warnings": _dedupe_warnings(
                      previous_registration.warnings,
                      warnings,
                  ),
              }
          )
          _store_source_registration(store, updated_registration)

          reviews = {
              screen_id: build_gap_review_document(screen)
              for screen_id, screen in combined_screens.items()
          }
          matrices_by_id = {}
          for screen_id, screen in combined_screens.items():
              bundle = build_screen_matrix_bundle(screen)
              matrices_by_id[screen_id] = bundle
              store.save_screen_matrix_artifacts(
                  screen_id,
                  field_csv=render_field_matrix_csv(bundle.field_rows),
                  action_rule_csv=render_action_rule_matrix_csv(bundle.action_rule_rows),
                  api_csv=render_api_matrix_csv(bundle.api_rows),
              )

          readiness_summary = evaluate_readiness(
              list(combined_screens.values()),
              feature_mode=feature_mode,
          )
          store.write_text(
              store.feature_paths.readiness_summary_markdown,
              render_readiness_summary_markdown(readiness_summary),
          )
          readiness_by_screen = _screen_readiness_index(readiness_summary)

          rendered_contracts: dict[str, tuple[str, str]] = {}
          for screen in screen_catalog_result.document.screens:
              contract_artifacts = build_provisional_contract_artifacts(
                  combined_screens[screen.screen_id],
                  matrices=matrices_by_id[screen.screen_id],
                  readiness=readiness_by_screen[screen.screen_id],
              )
              if contract_artifacts is None:
                  continue
              contract_yaml = render_contract_yaml(contract_artifacts.openapi_document)
              mock_data_json = render_mock_data_json(contract_artifacts.mock_data)
              store.save_contract_yaml(screen.screen_id, contract_yaml)
              store.save_mock_data_json(screen.screen_id, mock_data_json)
              rendered_contracts[screen.screen_id] = (contract_yaml, mock_data_json)

          _remove_stale_optional_screen_artifacts(
              store,
              screen_ids=[screen.screen_id for screen in screen_catalog_result.document.screens],
              contract_screens=tuple(rendered_contracts),
          )

          screen_artifacts: list[ScreenBundleArtifact] = []
          for screen in screen_catalog_result.document.screens:
              review = reviews[screen.screen_id]
              readiness = readiness_by_screen[screen.screen_id]
              matrices = matrices_by_id[screen.screen_id]
              fe_markdown = render_fe_spec_markdown(
                  screen,
                  combined_screens[screen.screen_id],
                  matrices=matrices,
                  review=review,
                  readiness=readiness,
              )
              be_markdown = render_be_spec_markdown(
                  screen,
                  combined_screens[screen.screen_id],
                  matrices=matrices,
                  review=review,
                  readiness=readiness,
              )
              questions_markdown = render_question_backlog_markdown(review)
              store.save_fe_spec_markdown(screen.screen_id, fe_markdown)
              store.save_be_spec_markdown(screen.screen_id, be_markdown)
              store.save_questions_markdown(screen.screen_id, questions_markdown)
              contract_yaml, mock_data_json = rendered_contracts.get(
                  screen.screen_id,
                  (None, None),
              )
              screen_artifacts.append(
                  ScreenBundleArtifact(
                      screen_id=screen.screen_id,
                      canonical_json=combined_screens[screen.screen_id].model_dump_json(indent=2),
                      fe_markdown=fe_markdown,
                      be_markdown=be_markdown,
                      questions_markdown=questions_markdown,
                      field_matrix_csv=render_field_matrix_csv(matrices.field_rows),
                      action_rule_matrix_csv=render_action_rule_matrix_csv(matrices.action_rule_rows),
                      api_matrix_csv=render_api_matrix_csv(matrices.api_rows),
                      contract_yaml=contract_yaml,
                      mock_data_json=mock_data_json,
                  )
              )

          bundle_files = write_bundle_layout(
              store,
              source_manifest=current_manifest,
              screen_catalog=screen_catalog_result.document,
              readiness=readiness_summary,
              screen_artifacts=screen_artifacts,
              terminology=terminology_result.document,
              run_audit=store.load_run_audit(),
          )
          changelog = render_rerun_changelog(
              plan,
              screens=list(combined_screens.values()),
              readiness=readiness_summary,
          )
          impacted_path = store.save_impacted_screens_json(plan.model_dump_json(indent=2))
          changelog_path = store.save_changelog_markdown(changelog)

          return _tool_result(
              tool_name="ba.rerun_impacted",
              feature_key=clean_feature_key,
              run_id=clean_run_id,
              output_dir=store.feature_paths.root,
              warnings=_dedupe_warnings(warnings, plan.warnings),
              result={
                  "notebook_id": clean_notebook_id,
                  "applied": True,
                  "selected_source_keys": list(selected_source_keys),
                  "updated_screen_ids": impacted_screen_ids,
                  "plan": _serialize_model(plan),
                  "impacted_screens_path": str(impacted_path),
                  "changelog_path": str(changelog_path),
                  "bundle_files": bundle_files,
                  "source_registration_path": str(store.run_paths.source_registration_json),
                  "source_manifest_path": str(store.feature_paths.source_manifest_json),
                  "screen_catalog_path": str(store.feature_paths.screen_catalog_json),
                  "terminology_path": str(store.feature_paths.terminology_json),
                  "metrics": _refresh_metrics_payload(
                      store=store,
                      metadata=metadata,
                      state=store.load_run_state(),
                      source=MetricsCaptureSource.RERUN_IMPACTED,
                      source_manifest=current_manifest,
                      screen_catalog=screen_catalog_result.document,
                      readiness=readiness_summary,
                      rerun_plan=plan,
                      notes=_dedupe_warnings(warnings, plan.warnings),
                  ),
              },
          )

    handlers: dict[str, Callable[..., Any]] = {
        "ba.start_run": ba_start_run,
        "ba.register_sources": ba_register_sources,
        "ba.status": ba_status,
        "ba.validate_bundle": ba_validate_bundle,
        "ba.run_pipeline": ba_run_pipeline,
        "ba.rerun_impacted": ba_rerun_impacted,
    }

    descriptions = {
        "ba.start_run": (
            "Bootstrap a BA feature run with explicit metadata, local output roots, and persisted run-state defaults."
        ),
        "ba.register_sources": (
            "Register typed BA sources into the persisted run manifest before downstream workflow stages execute."
        ),
        "ba.status": (
            "Inspect persisted BA run progress, step states, halt reasons, and resume guidance without reading files directly."
        ),
        "ba.validate_bundle": (
            "Run deterministic BA bundle QA checks, emit per-screen qa-report.json artifacts, and summarize pass/warn/fail findings."
        ),
        "ba.run_pipeline": (
            "Execute the current BA workflow pipeline from run bootstrap through validation with explicit state updates and progress reporting."
        ),
        "ba.rerun_impacted": (
            "Compare current source snapshots to the persisted BA baseline, rerun only impacted screens when safe, and emit rerun changelog artifacts."
        ),
    }

    for name, handler in handlers.items():
        _register_tool(
            server,
            name=name,
            description=descriptions[name],
            handler=handler,
        )

    return handlers


__all__ = ["MODULE_PURPOSE", "MUST_NOT_OWN", "OWNS", "register_ba_tools"]
