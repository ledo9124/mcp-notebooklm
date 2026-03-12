"""Unit tests for BA public MCP tool wrappers."""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from notebooklm_mcp._errors import MCPToolError
import notebooklm_mcp.ba.tools as ba_tools
from notebooklm_mcp.ba.adapter import (
    BAIngestWaitResult,
    BAReadyTimeoutPolicy,
    BASourceOperationResult,
    BASourceReadinessState,
    BASourceSnapshot,
)
from notebooklm_mcp.ba.extraction import (
    CanonicalScreenExtractionResult,
    ScreenCatalogExtractionResult,
    StructuredParseQuality,
    TerminologyExtractionResult,
)
from notebooklm_mcp.ba.models import (
    CanonicalFact,
    CanonicalScreen,
    EvidenceRef,
    ExtractionQualitySummary,
    FactDomain,
    FactStatus,
    HaltRecommendation,
    ParseQuality,
    ScreenCatalogDocument,
    ScreenCatalogEntry,
    SourceContentKind,
    SourceLifecycleStatus,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceQualityAssessment,
    SourceType,
    TerminologyDocument,
    TerminologyEntry,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    WorkflowMode,
)
from notebooklm_mcp.ba.run_store import BARunStore
from notebooklm_mcp.ba.rendering import render_source_manifest_markdown, render_terminology_markdown
from notebooklm_mcp.ba.state_machine import BARunStateMachine
from notebooklm_mcp.ba.tools import register_ba_tools


class _FakeServer:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, *, name: str | None = None, description: str | None = None):
        assert isinstance(description, str) or description is None

        def _decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return _decorator


def _decode_text_result(result: dict[str, Any]) -> dict[str, Any]:
    content = result["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    text = first["text"]
    assert isinstance(text, str)
    return json.loads(text)


class _FakeApp:
    def __init__(self) -> None:
        self.client = object()

    @asynccontextmanager
    async def acquire_slot(self):
        yield


class _FakeContext:
    def __init__(self, app: _FakeApp) -> None:
        self.request_context = SimpleNamespace(lifespan_context=app)
        self.progress_updates: list[dict[str, Any]] = []

    async def report_progress(self, current: int, total: int, message: str) -> None:
        self.progress_updates.append(
            {
                "current": current,
                "total": total,
                "message": message,
            }
        )


class _FakeAdapter:
    def __init__(
        self,
        *,
        recommendation: HaltRecommendation = HaltRecommendation.PROCEED,
        warnings: tuple[str, ...] = (),
        snapshot_contents: dict[str, str] | None = None,
    ) -> None:
        self.recommendation = recommendation
        self.warnings = warnings
        self.snapshot_contents = dict(snapshot_contents or {})
        self.ingest_calls: list[dict[str, Any]] = []
        self.snapshot_calls: list[tuple[str, str]] = []

    async def ingest_and_wait(
        self,
        notebook_id: str,
        manifest: Any,
        *,
        source_keys: tuple[str, ...] | list[str] | None = None,
        poll_budget_seconds: float,
        ready_timeout_policy: BAReadyTimeoutPolicy,
        workspace_root: Path,
    ) -> BAIngestWaitResult:
        del workspace_root
        self.ingest_calls.append(
            {
                "notebook_id": notebook_id,
                "poll_budget_seconds": poll_budget_seconds,
                "ready_timeout_policy": ready_timeout_policy,
                "source_keys": list(source_keys) if source_keys is not None else None,
            }
        )
        readiness_state = (
            BASourceReadinessState.DEGRADED
            if self.recommendation is HaltRecommendation.DEGRADE
            else BASourceReadinessState.READY
        )
        status = (
            SourceLifecycleStatus.DEGRADED
            if self.recommendation is HaltRecommendation.DEGRADE
            else SourceLifecycleStatus.READY
        )
        rows = [
            row.model_copy(
                update={
                    "notebook_source_id": row.notebook_source_id or f"src-{index}",
                    "status": status,
                }
            )
            for index, row in enumerate(manifest.rows, start=1)
        ]
        updated_manifest = manifest.model_copy(update={"rows": rows})
        source_results = tuple(
            BASourceOperationResult(
                source_key=row.source_key,
                notebook_id=notebook_id,
                notebook_source_id=row.notebook_source_id,
                title=row.title or row.source_key,
                readiness_state=readiness_state,
                source_type="pdf",
                status=1,
                degraded_reason=(
                    "timed out waiting for notebook source readiness"
                    if self.recommendation is HaltRecommendation.DEGRADE
                    else None
                ),
            )
            for row in rows
        )
        return BAIngestWaitResult(
            notebook_id=notebook_id,
            manifest=updated_manifest,
            source_results=source_results,
            selected_source_keys=(
                tuple(source_keys)
                if source_keys is not None
                else tuple(row.source_key for row in rows)
            ),
            poll_budget_seconds=poll_budget_seconds,
            ready_timeout_policy=ready_timeout_policy,
            elapsed_seconds=3.5,
            recommendation=self.recommendation,
            warnings=self.warnings,
        )

    async def collect_source_snapshot(
        self,
        notebook_id: str,
        source_id: str,
    ) -> BASourceSnapshot:
        self.snapshot_calls.append((notebook_id, source_id))
        content = self.snapshot_contents.get(
            source_id,
            (
                "Customer create requirements.\n"
                "Screen: Customer Form.\n"
                "API: POST /customers.\n"
            ),
        )
        return BASourceSnapshot(
            notebook_id=notebook_id,
            source_id=source_id,
            title="BA Requirements",
            source_type="pdf",
            status=1,
            is_ready=True,
            url=None,
            content=content,
            char_count=len(content),
            guide_summary="Customer create feature requirements",
            guide_keywords=("customer", "create", "form"),
            is_fresh=True,
        )


def _evidence(source_key: str, snapshot_id: str, locator: str) -> EvidenceRef:
    return EvidenceRef(
        source_key=source_key,
        snapshot_id=snapshot_id,
        locator=locator,
    )


def _terminology_result(
    *,
    feature_key: str,
    run_id: str,
    snapshot_id: str,
    source_key: str,
) -> TerminologyExtractionResult:
    return TerminologyExtractionResult(
        document=TerminologyDocument(
            feature_key=feature_key,
            run_id=run_id,
            entries=[
                TerminologyEntry(
                    standard_term="Customer",
                    aliases=["Client"],
                    semantic_notes=["Business entity created by the sales flow"],
                    evidence=[_evidence(source_key, snapshot_id, "1-2")],
                )
            ],
        ),
        raw_text='{"entries": [{"standard_term": "Customer"}]}',
        parse_quality=StructuredParseQuality.EXACT,
        conversation_id="conv-terms",
        turn_number=1,
        is_follow_up=False,
    )


def _screen_catalog_result(
    *,
    feature_key: str,
    run_id: str,
    snapshot_id: str,
    source_key: str,
) -> ScreenCatalogExtractionResult:
    return ScreenCatalogExtractionResult(
        document=ScreenCatalogDocument(
            feature_key=feature_key,
            run_id=run_id,
            screens=[
                ScreenCatalogEntry(
                    screen_id="customer-form",
                    screen_name="Customer Form",
                    purpose="Create a customer record",
                    roles=["Sales"],
                    entry_points=["Customer list"],
                    exit_points=["Customer detail"],
                    main_actions=["Save customer"],
                    dependencies=["Create Customer"],
                    related_sources=[source_key],
                    evidence=[_evidence(source_key, snapshot_id, "3-6")],
                )
            ],
        ),
        raw_text='{"screens": [{"screen_id": "customer-form"}]}',
        parse_quality=StructuredParseQuality.EXACT,
        conversation_id="conv-screens",
        turn_number=2,
        is_follow_up=True,
    )


def _canonical_screen(
    *,
    feature_key: str,
    run_id: str,
    snapshot_id: str,
    source_key: str,
) -> CanonicalScreen:
    return CanonicalScreen(
        feature_key=feature_key,
        screen_id="customer-form",
        mode=WorkflowMode.FE_FIRST,
        run_id=run_id,
        shared_facts=[
            CanonicalFact(
                fact_id="fact-save-rule",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={
                    "action_name": "Save customer",
                    "trigger": "User clicks Save",
                    "rule": "Customer email must be unique",
                    "outcome": "Reject duplicate email submissions",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(source_key, snapshot_id, "7-10")],
            )
        ],
        fe_facts=[
            CanonicalFact(
                fact_id="fact-email-field",
                domain=FactDomain.FE,
                category="field",
                value={
                    "field_name": "email",
                    "label": "Email Address",
                    "field_type": "email",
                    "required": True,
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(source_key, snapshot_id, "11-14")],
            )
        ],
        be_facts=[
            CanonicalFact(
                fact_id="fact-create-endpoint",
                domain=FactDomain.BE,
                category="endpoint",
                value={
                    "endpoint_name": "Create Customer",
                    "method": "post",
                    "path": "/customers",
                    "request_body": "name, email",
                    "response_body": "customer id",
                },
                status=FactStatus.CONFIRMED,
                evidence=[_evidence(source_key, snapshot_id, "15-19")],
            )
        ],
        dependencies=["Create Customer"],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


def _canonical_result(
    *,
    feature_key: str,
    run_id: str,
    snapshot_id: str,
    source_key: str,
) -> CanonicalScreenExtractionResult:
    return CanonicalScreenExtractionResult(
        screen=_canonical_screen(
            feature_key=feature_key,
            run_id=run_id,
            snapshot_id=snapshot_id,
            source_key=source_key,
        ),
        raw_text='{"screen_id": "customer-form"}',
        parse_quality=StructuredParseQuality.EXACT,
        conversation_id="conv-canonical",
        turn_number=3,
        is_follow_up=True,
    )


def _source_content(source_key: str) -> str:
    if source_key == "requirements":
        return (
            "Customer create requirements.\n"
            "Screen: Customer Form.\n"
            "API: POST /customers.\n"
        )
    return (
        "Customer listing glossary.\n"
        "Screen: Customer List.\n"
        "Term: Customer Summary.\n"
    )


def _snapshot_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def _evidence_for(source_key: str, snapshot_id: str, locator: str) -> EvidenceRef:
    return EvidenceRef(source_key=source_key, snapshot_id=snapshot_id, locator=locator)


def _baseline_terminology(
    *,
    feature_key: str,
    run_id: str,
    snapshot_ids: dict[str, str],
) -> TerminologyDocument:
    return TerminologyDocument(
        feature_key=feature_key,
        run_id=run_id,
        entries=[
            TerminologyEntry(
                standard_term="Customer",
                aliases=["Client"],
                evidence=[_evidence_for("requirements", snapshot_ids["requirements"], "1-2")],
            ),
            TerminologyEntry(
                standard_term="Customer Summary",
                aliases=["List Item"],
                evidence=[_evidence_for("glossary", snapshot_ids["glossary"], "1-2")],
            ),
        ],
    )


def _baseline_screen_catalog(
    *,
    feature_key: str,
    run_id: str,
    snapshot_ids: dict[str, str],
) -> ScreenCatalogDocument:
    return ScreenCatalogDocument(
        feature_key=feature_key,
        run_id=run_id,
        screens=[
            ScreenCatalogEntry(
                screen_id="customer-form",
                screen_name="Customer Form",
                purpose="Create a customer record",
                roles=["Sales"],
                entry_points=["Customer list"],
                exit_points=["Customer detail"],
                main_actions=["Save customer"],
                dependencies=["Create Customer"],
                related_sources=["requirements"],
                evidence=[_evidence_for("requirements", snapshot_ids["requirements"], "3-6")],
            ),
            ScreenCatalogEntry(
                screen_id="customer-list",
                screen_name="Customer List",
                purpose="Browse customers",
                roles=["Sales"],
                entry_points=["Dashboard"],
                exit_points=["Customer form"],
                main_actions=["Open customer"],
                dependencies=["Load Customer Summary"],
                related_sources=["glossary"],
                evidence=[_evidence_for("glossary", snapshot_ids["glossary"], "2-4")],
            ),
        ],
    )


def _canonical_screen_for(
    *,
    feature_key: str,
    run_id: str,
    screen_id: str,
    source_key: str,
    snapshot_id: str,
    provisional: bool = False,
) -> CanonicalScreen:
    fact_status = FactStatus.PROVISIONAL if provisional else FactStatus.CONFIRMED
    rationale = "Pending contract confirmation." if provisional else None
    return CanonicalScreen(
        feature_key=feature_key,
        screen_id=screen_id,
        mode=WorkflowMode.FE_FIRST,
        run_id=run_id,
        shared_facts=[
            CanonicalFact(
                fact_id=f"{screen_id}-rule",
                domain=FactDomain.SHARED,
                category="business_rule",
                value={"summary": f"{screen_id} rule"},
                status=fact_status,
                evidence=[_evidence_for(source_key, snapshot_id, "7-9")] if not provisional else [],
                rationale=rationale,
            )
        ],
        fe_facts=[],
        be_facts=[],
        dependencies=[],
        quality_summary=ExtractionQualitySummary(parse_quality=ParseQuality.HIGH),
    )


async def _seed_rerun_baseline(
    handlers: dict[str, Any],
    tmp_path: Path,
    *,
    feature_key: str = "customer-create",
    run_id: str = "run-900",
) -> BARunStore:
    await handlers["ba.start_run"](
        None,
        feature_key=feature_key,
        run_id=run_id,
        output_dir=str(tmp_path),
    )
    await handlers["ba.register_sources"](
        None,
        feature_key=feature_key,
        run_id=run_id,
        output_dir=str(tmp_path),
        sources=[
            {
                "path_or_url_or_text": "requirements/ba.pdf",
                "source_key": "requirements",
                "source_type": "primary-requirement",
                "priority": "required",
            },
            {
                "path_or_url_or_text": "https://example.com/glossary",
                "source_key": "glossary",
                "source_type": "supporting-glossary",
                "priority": "normal",
            },
        ],
    )
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key=feature_key,
        run_id=run_id,
    )
    registration = store.load_source_registration()

    snapshot_ids: dict[str, str] = {}
    rows: list[SourceManifestRow] = []
    for index, row in enumerate(registration.manifest.rows, start=1):
        content = _source_content(row.source_key)
        source_id = f"src-{index}"
        record = store.persist_source_snapshot(
            source_key=row.source_key,
            notebook_source_id=source_id,
            title=row.title or row.source_key,
            source_type="pdf",
            content=content,
            guide_summary=f"{row.source_key} guide",
            guide_keywords=(row.source_key,),
            is_fresh=True,
            char_count=len(content),
        )
        snapshot_ids[row.source_key] = record.snapshot_id
        store.save_source_quality_assessment(
            row.source_key,
            record.snapshot_id,
            SourceQualityAssessment(
                source_key=row.source_key,
                snapshot_id=record.snapshot_id,
                parse_quality=ParseQuality.HIGH,
                character_count=len(content),
                heading_count=2,
                table_density=0.0,
            ),
        )
        rows.append(
            row.model_copy(
                update={
                    "notebook_source_id": source_id,
                    "status": SourceLifecycleStatus.READY,
                    "snapshot_id": record.snapshot_id,
                    "parse_quality": ParseQuality.HIGH,
                    "used_in_screens": (
                        ["customer-form"] if row.source_key == "requirements" else ["customer-list"]
                    ),
                }
            )
        )

    manifest = SourceManifestDocument(
        run_id=run_id,
        feature_key=feature_key,
        rows=rows,
        warnings=registration.manifest.warnings,
    )
    store.write_model_json(
        store.run_paths.source_registration_json,
        registration.model_copy(update={"manifest": manifest}),
    )
    store.save_source_manifest_artifacts(
        manifest,
        markdown=render_source_manifest_markdown(manifest),
    )

    terminology = _baseline_terminology(
        feature_key=feature_key,
        run_id=run_id,
        snapshot_ids=snapshot_ids,
    )
    store.save_terminology_artifacts(
        terminology,
        markdown=render_terminology_markdown(terminology),
    )

    screen_catalog = _baseline_screen_catalog(
        feature_key=feature_key,
        run_id=run_id,
        snapshot_ids=snapshot_ids,
    )
    store.save_screen_catalog(screen_catalog)
    store.save_canonical_screen(
        _canonical_screen_for(
            feature_key=feature_key,
            run_id=run_id,
            screen_id="customer-form",
            source_key="requirements",
            snapshot_id=snapshot_ids["requirements"],
        )
    )
    store.save_canonical_screen(
        _canonical_screen_for(
            feature_key=feature_key,
            run_id=run_id,
            screen_id="customer-list",
            source_key="glossary",
            snapshot_id=snapshot_ids["glossary"],
            provisional=True,
        )
    )
    return store


def _install_pipeline_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapter: _FakeAdapter | None = None,
    quality_recommendation: HaltRecommendation = HaltRecommendation.PROCEED,
) -> _FakeAdapter:
    fake_adapter = adapter or _FakeAdapter()
    monkeypatch.setattr(ba_tools, "BACapabilityAdapter", lambda client: fake_adapter)

    def _fake_assess_source_quality(row: Any, snapshot: Any, content: str) -> SourceQualityAssessment:
        del snapshot
        return SourceQualityAssessment(
            source_key=row.source_key,
            snapshot_id=row.snapshot_id,
            parse_quality=ParseQuality.HIGH,
            character_count=len(content),
            heading_count=4,
            table_density=0.1,
            recommendation=quality_recommendation,
        )

    async def _fake_extract_terminology(
        _ask_callable: Any,
        *,
        feature_key: str,
        run_id: str,
        snapshots: list[Any],
        **_: Any,
    ) -> TerminologyExtractionResult:
        return _terminology_result(
            feature_key=feature_key,
            run_id=run_id,
            snapshot_id=snapshots[0].snapshot_id,
            source_key=snapshots[0].source_key,
        )

    async def _fake_extract_screen_catalog(
        _ask_callable: Any,
        *,
        feature_key: str,
        run_id: str,
        snapshots: list[Any],
        **_: Any,
    ) -> ScreenCatalogExtractionResult:
        return _screen_catalog_result(
            feature_key=feature_key,
            run_id=run_id,
            snapshot_id=snapshots[0].snapshot_id,
            source_key=snapshots[0].source_key,
        )

    async def _fake_extract_canonical(
        _ask_callable: Any,
        *,
        feature_key: str,
        run_id: str,
        snapshots: list[Any],
        **_: Any,
    ) -> CanonicalScreenExtractionResult:
        return _canonical_result(
            feature_key=feature_key,
            run_id=run_id,
            snapshot_id=snapshots[0].snapshot_id,
            source_key=snapshots[0].source_key,
        )

    monkeypatch.setattr(ba_tools, "assess_source_quality", _fake_assess_source_quality)
    monkeypatch.setattr(ba_tools, "extract_terminology_document", _fake_extract_terminology)
    monkeypatch.setattr(ba_tools, "extract_screen_catalog_document", _fake_extract_screen_catalog)
    monkeypatch.setattr(ba_tools, "extract_canonical_screen", _fake_extract_canonical)
    return fake_adapter


def test_register_ba_tools_registers_current_public_surface() -> None:
    server = _FakeServer()

    handlers = register_ba_tools(server)

    assert set(handlers) == {
        "ba.start_run",
        "ba.register_sources",
        "ba.status",
        "ba.validate_bundle",
        "ba.run_pipeline",
        "ba.rerun_impacted",
    }
    assert set(server.tools) == {
        "ba.start_run",
        "ba.register_sources",
        "ba.status",
        "ba.validate_bundle",
        "ba.run_pipeline",
        "ba.rerun_impacted",
    }


@pytest.mark.asyncio
async def test_ba_start_run_returns_consistent_envelope_and_persists_state(
    tmp_path: Path,
) -> None:
    handlers = register_ba_tools(_FakeServer())

    result = await handlers["ba.start_run"](
        None,
        feature_key="customer-create",
        mode="balanced",
        output_dir=str(tmp_path),
        notebook_lifecycle="EPHEMERAL_RUN_NOTEBOOK",
        assumption_profile={"backend_exists": False},
    )

    structured = result["structuredContent"]
    assert _decode_text_result(result) == structured
    assert structured["ok"] is True
    assert structured["tool"] == "ba.start_run"
    assert structured["feature_key"] == "customer-create"
    assert structured["run_id"].startswith("run-")
    assert structured["resolved_output_dir"] == str(
        tmp_path / "docs" / "features" / "customer-create"
    )

    payload = structured["result"]
    assert payload["mode_requested"] == "BALANCED"
    assert payload["notebook_lifecycle"] == "EPHEMERAL_RUN_NOTEBOOK"
    assert payload["assumption_profile"] == {"backend_exists": False}
    assert payload["state"]["status"] == "RUNNING"
    assert payload["state"]["current_step"] is None
    assert payload["state"]["steps"] == [
        {
            "step": "START_RUN",
            "status": "COMPLETED",
            "attempts": 1,
            "started_at": payload["state"]["steps"][0]["started_at"],
            "completed_at": payload["state"]["steps"][0]["completed_at"],
            "halt_reason": None,
            "notes": ["Run root initialized"],
            "metadata": {
                "mode_requested": "BALANCED",
                "notebook_lifecycle": "EPHEMERAL_RUN_NOTEBOOK",
                "assumption_profile": {"backend_exists": False},
            },
        }
    ]
    assert Path(payload["run_metadata_path"]).exists()
    assert Path(payload["run_state_path"]).exists()


@pytest.mark.asyncio
async def test_ba_register_sources_uses_same_envelope_and_advances_run_state(
    tmp_path: Path,
) -> None:
    handlers = register_ba_tools(_FakeServer())

    start_result = await handlers["ba.start_run"](
        None,
        feature_key="customer-create",
        run_id="run-123",
        output_dir=str(tmp_path),
    )
    assert start_result["structuredContent"]["run_id"] == "run-123"

    register_result = await handlers["ba.register_sources"](
        None,
        feature_key="customer-create",
        run_id="run-123",
        output_dir=str(tmp_path),
        sources=[
            {
                "path_or_url_or_text": "requirements/ba.pdf",
                "source_type": "primary-requirement",
                "priority": "required",
                "notes": ["authoritative"],
            },
            {
                "path_or_url_or_text": "https://example.com/glossary",
                "source_key": "domain-glossary",
                "source_type": "supporting-glossary",
                "priority": "normal",
            },
        ],
    )

    structured = register_result["structuredContent"]
    assert _decode_text_result(register_result) == structured
    assert structured["ok"] is True
    assert structured["tool"] == "ba.register_sources"
    assert structured["feature_key"] == "customer-create"
    assert structured["run_id"] == "run-123"

    payload = structured["result"]
    assert payload["state"]["status"] == "RUNNING"
    assert payload["state"]["current_step"] is None
    assert [step["step"] for step in payload["state"]["steps"]] == [
        "START_RUN",
        "REGISTER_SOURCES",
    ]
    assert payload["state"]["steps"][-1]["status"] == "COMPLETED"
    assert payload["state"]["steps"][-1]["metadata"]["registered_source_count"] == 2

    registration = payload["source_registration"]
    assert registration["feature_key"] == "customer-create"
    assert registration["run_id"] == "run-123"
    assert len(registration["registered_sources"]) == 2
    assert registration["manifest"]["rows"][0]["source_type"] == "PRIMARY_REQUIREMENT"
    assert registration["missing_critical_sources"] == []
    assert Path(payload["source_registration_path"]).exists()


@pytest.mark.asyncio
async def test_ba_register_sources_requires_start_run_first(tmp_path: Path) -> None:
    handlers = register_ba_tools(_FakeServer())

    with pytest.raises(MCPToolError) as exc_info:
        await handlers["ba.register_sources"](
            None,
            feature_key="customer-create",
            run_id="run-456",
            output_dir=str(tmp_path),
            sources=[
                {
                    "path_or_url_or_text": "requirements/ba.pdf",
                    "source_type": "primary-requirement",
                }
            ],
        )

    assert exc_info.value.error_code == "invalid_params"
    assert "ba.start_run" in exc_info.value.message


@pytest.mark.asyncio
async def test_ba_status_reports_ordered_progress_for_started_run(tmp_path: Path) -> None:
    handlers = register_ba_tools(_FakeServer())

    await handlers["ba.start_run"](
        None,
        feature_key="customer-create",
        run_id="run-200",
        output_dir=str(tmp_path),
    )

    result = await handlers["ba.status"](
        None,
        feature_key="customer-create",
        run_id="run-200",
        output_dir=str(tmp_path),
    )

    structured = result["structuredContent"]
    assert _decode_text_result(result) == structured
    assert structured["tool"] == "ba.status"
    assert structured["feature_key"] == "customer-create"
    assert structured["run_id"] == "run-200"

    payload = structured["result"]
    assert payload["state"]["status"] == "RUNNING"
    assert payload["progress"] == {
        "total_planned_steps": 15,
        "recorded_steps": 1,
        "completed_steps": 1,
        "current_step": None,
        "current_tool": None,
        "next_step": "REGISTER_SOURCES",
        "next_tool": "ba.register_sources",
        "completed_step_names": ["START_RUN"],
        "not_started_step_names": [
            "REGISTER_SOURCES",
            "INGEST_AND_WAIT",
            "SNAPSHOT_SOURCES",
            "ASSESS_SOURCE_QUALITY",
            "BUILD_SOURCE_MANIFEST",
            "NORMALIZE_TERMINOLOGY",
            "BUILD_SCREEN_CATALOG",
            "EXTRACT_CANONICAL",
            "REVIEW_GAPS",
            "GENERATE_MATRICES",
            "EVALUATE_READINESS",
            "GENERATE_CONTRACTS",
            "RENDER_BUNDLE",
            "VALIDATE_BUNDLE",
        ],
    }
    assert payload["resumability"] == {
        "can_resume": False,
        "resume_step": None,
        "resume_tool": None,
        "requires_explicit_step": False,
        "hint": None,
    }
    assert payload["steps"][0]["tool"] == "ba.start_run"
    assert payload["steps"][0]["status"] == "COMPLETED"
    assert payload["steps"][1]["tool"] == "ba.register_sources"
    assert payload["steps"][1]["status"] == "NOT_STARTED"
    assert Path(payload["run_metadata_path"]).exists()
    assert Path(payload["run_state_path"]).exists()
    assert payload["metrics"]["snapshot"] is None
    assert payload["metrics"]["run_metrics_path"].endswith("metrics.json")


@pytest.mark.asyncio
async def test_ba_status_surfaces_resumability_for_degraded_run(tmp_path: Path) -> None:
    handlers = register_ba_tools(_FakeServer())
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-201",
    )
    store.create()
    machine = BARunStateMachine.from_store(store)
    machine.start_run()
    machine.complete_step(ba_tools.RunStep.START_RUN)
    machine.start_step(ba_tools.RunStep.ASSESS_SOURCE_QUALITY)
    machine.mark_degraded(
        "OCR quality too low",
        warning="OCR quality too low",
    )

    result = await handlers["ba.status"](
        None,
        feature_key="customer-create",
        run_id="run-201",
        output_dir=str(tmp_path),
    )

    payload = result["structuredContent"]["result"]
    assert result["structuredContent"]["warnings"] == ["OCR quality too low"]
    assert payload["state"]["status"] == "DEGRADED"
    assert payload["state"]["current_step"] == "ASSESS_SOURCE_QUALITY"
    assert payload["progress"]["current_step"] == "ASSESS_SOURCE_QUALITY"
    assert payload["progress"]["current_tool"] == "ba.assess_source_quality"
    assert payload["progress"]["next_step"] == "ASSESS_SOURCE_QUALITY"
    assert payload["progress"]["next_tool"] == "ba.assess_source_quality"
    assert payload["resumability"] == {
        "can_resume": True,
        "resume_step": "ASSESS_SOURCE_QUALITY",
        "resume_tool": "ba.assess_source_quality",
        "requires_explicit_step": False,
        "hint": "Resume re-opens the paused run at the current step without incrementing attempts.",
    }
    degraded_step = next(
        step for step in payload["steps"] if step["step"] == "ASSESS_SOURCE_QUALITY"
    )
    assert degraded_step["status"] == "DEGRADED"
    assert degraded_step["current"] is True
    assert payload["last_event"]["event_type"] == "DEGRADED"
    assert payload["last_event"]["details"]["reason"] == "OCR quality too low"


@pytest.mark.asyncio
async def test_ba_status_requires_existing_run(tmp_path: Path) -> None:
    handlers = register_ba_tools(_FakeServer())

    with pytest.raises(MCPToolError) as exc_info:
        await handlers["ba.status"](
            None,
            feature_key="customer-create",
            run_id="run-missing",
            output_dir=str(tmp_path),
        )

    assert exc_info.value.error_code == "invalid_params"
    assert "ba.start_run" in exc_info.value.message


@pytest.mark.asyncio
async def test_ba_run_pipeline_completes_through_validation_and_persists_qa_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_adapter = _install_pipeline_fakes(monkeypatch)
    handlers = register_ba_tools(_FakeServer())
    ctx = _FakeContext(_FakeApp())

    result = await handlers["ba.run_pipeline"](
        ctx,
        notebook_id="nb-123",
        feature_key="customer-create",
        run_id="run-789",
        mode="fe_first",
        output_dir=str(tmp_path),
        sources=[
            {
                "path_or_url_or_text": "requirements/ba.pdf",
                "source_type": "primary-requirement",
                "priority": "required",
            }
        ],
    )

    structured = result["structuredContent"]
    assert _decode_text_result(result) == structured
    assert structured["tool"] == "ba.run_pipeline"
    assert structured["feature_key"] == "customer-create"
    assert structured["run_id"] == "run-789"

    payload = structured["result"]
    assert payload["notebook_id"] == "nb-123"
    assert payload["dry_run"] is False
    assert payload["stopped_after_step"] is None
    assert payload["validation"]["executed"] is True
    assert payload["validation"]["status"] in {"PASS", "WARN"}
    assert payload["validation"]["finding_count"] >= 0
    assert payload["validation"]["warning_count"] >= 0
    assert payload["validation"]["qa_report_paths"] == {
        "customer-form": str(
            tmp_path
            / "docs"
            / "features"
            / "customer-create"
            / "screens"
            / "customer-form"
            / "qa-report.json"
        )
    }
    assert payload["state"]["status"] == "COMPLETED"
    assert payload["state"]["current_step"] is None
    assert payload["state"]["steps"][-1]["step"] == "VALIDATE_BUNDLE"
    assert payload["step_results"]["evaluate_readiness"]["readiness"]["decision"] == "READY_FOR_FE_AND_BE"
    assert payload["step_results"]["generate_contracts"]["contract_screens"] == ["customer-form"]
    assert payload["step_results"]["validate_bundle"]["status"] in {"PASS", "WARN"}
    assert "screens/customer-form/contract.provisional.yaml" in payload["bundle_files"]
    assert "screens/customer-form/mock-data.json" in payload["bundle_files"]
    assert "screens/customer-form/qa-report.json" in payload["bundle_files"]
    assert payload["metrics"]["snapshot"]["source"] == "RUN_PIPELINE"
    assert payload["metrics"]["snapshot"]["time_to_first_fe_spec_seconds"]["basis"] == "EXACT"
    assert Path(payload["metrics"]["run_metrics_path"]).exists()
    assert Path(payload["bundle_files"]["00-overview.md"]).exists()
    assert Path(payload["bundle_files"]["screens/customer-form/contract.provisional.yaml"]).exists()
    assert Path(payload["bundle_files"]["screens/customer-form/qa-report.json"]).exists()
    assert fake_adapter.snapshot_calls == [("nb-123", "src-1")]
    assert len(ctx.progress_updates) == 15
    assert ctx.progress_updates[-1]["message"] == "VALIDATE_BUNDLE completed"

    status_result = await handlers["ba.status"](
        None,
        feature_key="customer-create",
        run_id="run-789",
        output_dir=str(tmp_path),
    )
    status_payload = status_result["structuredContent"]["result"]
    assert status_payload["state"]["status"] == "COMPLETED"
    assert status_payload["progress"]["next_step"] is None
    assert status_payload["resumability"]["can_resume"] is False
    assert status_payload["metrics"]["snapshot"]["source"] == "RUN_PIPELINE"
    assert status_payload["metrics"]["history_count"] == 1
    assert next(
        step for step in status_payload["steps"] if step["step"] == "VALIDATE_BUNDLE"
    )["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_ba_run_pipeline_halts_when_validation_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_pipeline_fakes(monkeypatch)
    failing_report = ValidationReport(
        run_id="run-795",
        feature_key="customer-create",
        status=ValidationStatus.FAIL,
        findings=[
            ValidationFinding(
                code="contract-mock-misalignment",
                severity=ValidationSeverity.ERROR,
                message="mock-data is missing operation `create-customer`",
                screen_id="customer-form",
                file_path="screens/customer-form/mock-data.json",
            )
        ],
    )
    monkeypatch.setattr(ba_tools, "validate_bundle_artifacts", lambda *args, **kwargs: failing_report)
    handlers = register_ba_tools(_FakeServer())
    ctx = _FakeContext(_FakeApp())

    result = await handlers["ba.run_pipeline"](
        ctx,
        notebook_id="nb-123",
        feature_key="customer-create",
        run_id="run-795",
        mode="fe_first",
        output_dir=str(tmp_path),
        sources=[
            {
                "path_or_url_or_text": "requirements/ba.pdf",
                "source_type": "primary-requirement",
                "priority": "required",
            }
        ],
    )

    payload = result["structuredContent"]["result"]
    assert payload["validation"]["executed"] is True
    assert payload["validation"]["status"] == "FAIL"
    assert payload["state"]["status"] == "HALTED"
    assert payload["state"]["current_step"] == "VALIDATE_BUNDLE"
    assert payload["stopped_after_step"] == "VALIDATE_BUNDLE"
    assert next(
        step for step in payload["state"]["steps"] if step["step"] == "VALIDATE_BUNDLE"
    )["status"] == "HALTED"
    assert len(ctx.progress_updates) == 15
    assert ctx.progress_updates[-1]["message"] == "VALIDATE_BUNDLE halted"


@pytest.mark.asyncio
async def test_ba_validate_bundle_rechecks_existing_run_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_pipeline_fakes(monkeypatch)
    handlers = register_ba_tools(_FakeServer())

    await handlers["ba.run_pipeline"](
        _FakeContext(_FakeApp()),
        notebook_id="nb-123",
        feature_key="customer-create",
        run_id="run-796",
        mode="fe_first",
        output_dir=str(tmp_path),
        sources=[
            {
                "path_or_url_or_text": "requirements/ba.pdf",
                "source_type": "primary-requirement",
                "priority": "required",
            }
        ],
    )

    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id="run-796",
    )
    store.save_mock_data_json(
        "customer-form",
        json.dumps(
            {
                "contract_status": "PROVISIONAL",
                "feature_key": "customer-create",
                "run_id": "run-796",
                "screen_id": "customer-form",
                "operations": {},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    result = await handlers["ba.validate_bundle"](
        None,
        feature_key="customer-create",
        run_id="run-796",
        output_dir=str(tmp_path),
    )

    payload = result["structuredContent"]["result"]
    assert payload["validation"]["status"] == "FAIL"
    assert payload["validation"]["finding_count"] >= 1
    assert any(
        finding["code"] == "contract-mock-misalignment"
        for finding in payload["validation"]["report"]["findings"]
    )
    assert Path(payload["validation"]["qa_report_paths"]["customer-form"]).exists()
    assert payload["metrics"]["snapshot"]["source"] == "VALIDATE_BUNDLE"
    assert payload["metrics"]["history_count"] == 2
    assert Path(payload["metrics"]["run_metrics_path"]).exists()


@pytest.mark.asyncio
async def test_ba_run_pipeline_dry_run_halts_after_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_pipeline_fakes(monkeypatch)
    handlers = register_ba_tools(_FakeServer())
    ctx = _FakeContext(_FakeApp())

    result = await handlers["ba.run_pipeline"](
        ctx,
        notebook_id="nb-123",
        feature_key="customer-create",
        run_id="run-790",
        mode="fe_first",
        output_dir=str(tmp_path),
        dry_run=True,
        sources=[
            {
                "path_or_url_or_text": "requirements/ba.pdf",
                "source_type": "primary-requirement",
                "priority": "required",
            }
        ],
    )

    payload = result["structuredContent"]["result"]
    assert payload["dry_run"] is True
    assert payload["stopped_after_step"] == "EVALUATE_READINESS"
    assert payload["validation"] == {
        "executed": False,
        "reason": "dry_run requested stop after readiness assessment",
    }
    assert payload["state"]["status"] == "HALTED"
    assert payload["state"]["current_step"] is None
    assert payload["state"]["halt_reason"] == "dry_run requested stop after readiness assessment"
    assert payload["state"]["steps"][-1]["step"] == "EVALUATE_READINESS"
    assert "generate_contracts" not in payload["step_results"]
    assert "render_bundle" not in payload["step_results"]
    assert payload["bundle_files"] == {}
    assert len(ctx.progress_updates) == 12
    assert ctx.progress_updates[-1]["message"] == "EVALUATE_READINESS completed"


@pytest.mark.asyncio
async def test_ba_run_pipeline_returns_degraded_state_when_ingest_times_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_adapter = _install_pipeline_fakes(
        monkeypatch,
        adapter=_FakeAdapter(
            recommendation=HaltRecommendation.DEGRADE,
            warnings=("source readiness timed out",),
        ),
    )
    handlers = register_ba_tools(_FakeServer())
    ctx = _FakeContext(_FakeApp())

    result = await handlers["ba.run_pipeline"](
        ctx,
        notebook_id="nb-123",
        feature_key="customer-create",
        run_id="run-791",
        output_dir=str(tmp_path),
        ready_timeout_policy="DEGRADE",
        sources=[
            {
                "path_or_url_or_text": "requirements/ba.pdf",
                "source_type": "primary-requirement",
                "priority": "required",
            }
        ],
    )

    structured = result["structuredContent"]
    payload = structured["result"]
    assert structured["warnings"] == ["source readiness timed out"]
    assert payload["stopped_after_step"] == "INGEST_AND_WAIT"
    assert payload["validation"] == {
        "executed": False,
        "reason": "pipeline degraded during ingest",
    }
    assert payload["state"]["status"] == "DEGRADED"
    assert payload["state"]["current_step"] == "INGEST_AND_WAIT"
    assert payload["state"]["steps"][-1]["status"] == "DEGRADED"
    assert payload["step_results"]["ingest_and_wait"]["ingest_result"]["recommendation"] == "DEGRADE"
    assert "snapshot_sources" not in payload["step_results"]
    assert payload["bundle_files"] == {}
    assert fake_adapter.snapshot_calls == []
    assert len(ctx.progress_updates) == 3
    assert ctx.progress_updates[-1]["message"] == "INGEST_AND_WAIT degraded"


@pytest.mark.asyncio
async def test_ba_rerun_impacted_selectively_updates_only_impacted_screen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_adapter = _FakeAdapter(
        snapshot_contents={
            "src-1": (
                "Customer create requirements.\n"
                "Screen: Customer Form.\n"
                "API: POST /customers.\n"
                "Rule: Email must be verified before save.\n"
            ),
            "src-2": _source_content("glossary"),
        }
    )
    monkeypatch.setattr(ba_tools, "BACapabilityAdapter", lambda client: fake_adapter)
    monkeypatch.setattr(
        ba_tools,
        "assess_source_quality",
        lambda row, snapshot, content: SourceQualityAssessment(
            source_key=row.source_key,
            snapshot_id=snapshot.snapshot_id,
            parse_quality=ParseQuality.HIGH,
            character_count=len(content),
            heading_count=2,
            table_density=0.0,
        ),
    )

    canonical_calls: list[str] = []

    async def _fake_extract_terminology(
        _ask_callable: Any,
        *,
        feature_key: str,
        run_id: str,
        snapshots: list[Any],
        **_: Any,
    ) -> TerminologyExtractionResult:
        snapshot_ids = {item.source_key: item.snapshot_id for item in snapshots}
        return TerminologyExtractionResult(
            document=TerminologyDocument(
                feature_key=feature_key,
                run_id=run_id,
                entries=[
                    TerminologyEntry(
                        standard_term="Customer",
                        aliases=["Client"],
                        evidence=[_evidence_for("requirements", snapshot_ids["requirements"], "1-2")],
                    ),
                    TerminologyEntry(
                        standard_term="Customer Summary",
                        aliases=["List Item"],
                        evidence=[_evidence_for("glossary", snapshot_ids["glossary"], "1-2")],
                    ),
                ],
            ),
            raw_text='{"entries": [{"standard_term": "Customer"}]}',
            parse_quality=StructuredParseQuality.EXACT,
        )

    async def _fake_extract_screen_catalog(
        _ask_callable: Any,
        *,
        feature_key: str,
        run_id: str,
        snapshots: list[Any],
        **_: Any,
    ) -> ScreenCatalogExtractionResult:
        snapshot_ids = {item.source_key: item.snapshot_id for item in snapshots}
        return ScreenCatalogExtractionResult(
            document=_baseline_screen_catalog(
                feature_key=feature_key,
                run_id=run_id,
                snapshot_ids=snapshot_ids,
            ),
            raw_text='{"screens": [{"screen_id": "customer-form"}]}',
            parse_quality=StructuredParseQuality.EXACT,
        )

    async def _fake_extract_canonical(
        _ask_callable: Any,
        *,
        feature_key: str,
        run_id: str,
        screen: ScreenCatalogEntry,
        snapshots: list[Any],
        **_: Any,
    ) -> CanonicalScreenExtractionResult:
        canonical_calls.append(screen.screen_id)
        snapshot_ids = {item.source_key: item.snapshot_id for item in snapshots}
        assert screen.screen_id == "customer-form"
        return CanonicalScreenExtractionResult(
            screen=_canonical_screen_for(
                feature_key=feature_key,
                run_id=run_id,
                screen_id="customer-form",
                source_key="requirements",
                snapshot_id=snapshot_ids["requirements"],
            ),
            raw_text='{"screen_id": "customer-form"}',
            parse_quality=StructuredParseQuality.EXACT,
        )

    monkeypatch.setattr(ba_tools, "extract_terminology_document", _fake_extract_terminology)
    monkeypatch.setattr(ba_tools, "extract_screen_catalog_document", _fake_extract_screen_catalog)
    monkeypatch.setattr(ba_tools, "extract_canonical_screen", _fake_extract_canonical)

    handlers = register_ba_tools(_FakeServer())
    await _seed_rerun_baseline(handlers, tmp_path, run_id="run-900")

    result = await handlers["ba.rerun_impacted"](
        _FakeContext(_FakeApp()),
        notebook_id="nb-123",
        feature_key="customer-create",
        run_id="run-900",
        output_dir=str(tmp_path),
    )

    structured = result["structuredContent"]
    payload = structured["result"]
    assert _decode_text_result(result) == structured
    assert structured["tool"] == "ba.rerun_impacted"
    assert payload["applied"] is True
    assert payload["updated_screen_ids"] == ["customer-form"]
    assert payload["plan"]["decision"] == "SELECTIVE"
    assert [item["screen_id"] for item in payload["plan"]["impacted_screens"]] == ["customer-form"]
    assert canonical_calls == ["customer-form"]
    assert payload["metrics"]["snapshot"]["source"] == "RERUN_IMPACTED"
    assert Path(payload["metrics"]["run_metrics_path"]).exists()
    assert Path(payload["impacted_screens_path"]).exists()
    assert Path(payload["changelog_path"]).exists()
    assert "customer-form" in Path(payload["changelog_path"]).read_text(encoding="utf-8")
    assert Path(payload["bundle_files"]["00-overview.md"]).exists()


@pytest.mark.asyncio
async def test_ba_rerun_impacted_escalates_when_screen_catalog_changes_materially(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_adapter = _FakeAdapter(
        snapshot_contents={
            "src-1": (
                "Customer create requirements.\n"
                "Screen: Customer Form.\n"
                "Screen: Customer Detail.\n"
                "API: POST /customers.\n"
            ),
            "src-2": _source_content("glossary"),
        }
    )
    monkeypatch.setattr(ba_tools, "BACapabilityAdapter", lambda client: fake_adapter)
    monkeypatch.setattr(
        ba_tools,
        "assess_source_quality",
        lambda row, snapshot, content: SourceQualityAssessment(
            source_key=row.source_key,
            snapshot_id=snapshot.snapshot_id,
            parse_quality=ParseQuality.HIGH,
            character_count=len(content),
            heading_count=2,
            table_density=0.0,
        ),
    )

    canonical_calls: list[str] = []

    async def _fake_extract_terminology(
        _ask_callable: Any,
        *,
        feature_key: str,
        run_id: str,
        snapshots: list[Any],
        **_: Any,
    ) -> TerminologyExtractionResult:
        snapshot_ids = {item.source_key: item.snapshot_id for item in snapshots}
        return TerminologyExtractionResult(
            document=_baseline_terminology(
                feature_key=feature_key,
                run_id=run_id,
                snapshot_ids=snapshot_ids,
            ),
            raw_text='{"entries": [{"standard_term": "Customer"}]}',
            parse_quality=StructuredParseQuality.EXACT,
        )

    async def _fake_extract_screen_catalog(
        _ask_callable: Any,
        *,
        feature_key: str,
        run_id: str,
        snapshots: list[Any],
        **_: Any,
    ) -> ScreenCatalogExtractionResult:
        snapshot_ids = {item.source_key: item.snapshot_id for item in snapshots}
        baseline = _baseline_screen_catalog(
            feature_key=feature_key,
            run_id=run_id,
            snapshot_ids=snapshot_ids,
        )
        return ScreenCatalogExtractionResult(
            document=baseline.model_copy(
                update={
                    "screens": [
                        *baseline.screens,
                        ScreenCatalogEntry(
                            screen_id="customer-detail",
                            screen_name="Customer Detail",
                            purpose="Review a saved customer",
                            roles=["Sales"],
                            related_sources=["requirements"],
                            evidence=[
                                _evidence_for(
                                    "requirements",
                                    snapshot_ids["requirements"],
                                    "10-12",
                                )
                            ],
                        ),
                    ]
                }
            ),
            raw_text='{"screens": [{"screen_id": "customer-detail"}]}',
            parse_quality=StructuredParseQuality.EXACT,
        )

    async def _fake_extract_canonical(*_: Any, **kwargs: Any) -> CanonicalScreenExtractionResult:
        canonical_calls.append(kwargs["screen"].screen_id)
        raise AssertionError("selective canonical extraction should not run when rerun escalates")

    monkeypatch.setattr(ba_tools, "extract_terminology_document", _fake_extract_terminology)
    monkeypatch.setattr(ba_tools, "extract_screen_catalog_document", _fake_extract_screen_catalog)
    monkeypatch.setattr(ba_tools, "extract_canonical_screen", _fake_extract_canonical)

    handlers = register_ba_tools(_FakeServer())
    await _seed_rerun_baseline(handlers, tmp_path, run_id="run-901")

    result = await handlers["ba.rerun_impacted"](
        _FakeContext(_FakeApp()),
        notebook_id="nb-123",
        feature_key="customer-create",
        run_id="run-901",
        output_dir=str(tmp_path),
    )

    payload = result["structuredContent"]["result"]
    assert payload["applied"] is False
    assert payload["plan"]["decision"] == "FULL_FEATURE"
    assert "screen catalog changed materially" in payload["plan"]["escalation_reasons"]
    assert canonical_calls == []
    assert Path(payload["impacted_screens_path"]).exists()
    assert "FULL_FEATURE" in Path(payload["changelog_path"]).read_text(encoding="utf-8")
