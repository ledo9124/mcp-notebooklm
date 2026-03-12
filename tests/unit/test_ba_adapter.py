"""Unit tests for notebooklm_mcp.ba.adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from notebooklm.exceptions import SourceTimeoutError
from notebooklm.rpc.types import ReportFormat, SourceStatus
from notebooklm.types import AskResult, ChatReference, GenerationStatus, Source, SourceFulltext
from notebooklm_mcp.ba.adapter import (
    BACapabilityAdapter,
    BACapabilityName,
    BACapabilityState,
    BAIngestWaitResult,
    BAMindMapResult,
    BAReadyTimeoutPolicy,
    BASourceOperationResult,
    BASourceReadinessState,
    BASourceSnapshot,
    BAStructuredAskResult,
    UnsupportedBACapabilityError,
)
from notebooklm_mcp.ba.models import (
    HaltRecommendation,
    SourceContentKind,
    SourceLifecycleStatus,
    SourceManifestDocument,
    SourceManifestRow,
    SourcePriority,
    SourceType,
)


def _fake_client() -> SimpleNamespace:
    return SimpleNamespace(
        sources=SimpleNamespace(),
        notes=SimpleNamespace(),
        chat=SimpleNamespace(),
        research=SimpleNamespace(),
        settings=SimpleNamespace(),
        artifacts=SimpleNamespace(),
    )


def test_capability_catalog_centralizes_states() -> None:
    adapter = BACapabilityAdapter(_fake_client())

    capabilities = adapter.describe_capabilities()

    assert capabilities["source_snapshot"].state is BACapabilityState.AVAILABLE
    assert capabilities["note_to_source_bridge"].state is BACapabilityState.DEGRADED
    assert capabilities["note_export"].state is BACapabilityState.UNSUPPORTED
    assert adapter.get_capability(BACapabilityName.MIND_MAP_ARTIFACTS).summary


def test_require_capability_raises_for_unsupported_or_disallowed_degraded() -> None:
    adapter = BACapabilityAdapter(_fake_client())

    with pytest.raises(UnsupportedBACapabilityError):
        adapter.require_capability(BACapabilityName.NOTE_EXPORT)

    with pytest.raises(UnsupportedBACapabilityError):
        adapter.require_capability(
            BACapabilityName.NOTE_TO_SOURCE_BRIDGE,
            allow_degraded=False,
        )


@pytest.mark.asyncio
async def test_collect_source_snapshot_normalizes_full_fidelity_payload() -> None:
    client = _fake_client()
    client.sources.get = AsyncMock(
        return_value=Source(
            id="src-1",
            title="Requirements PDF",
            url="https://example.com/spec.pdf",
            _type_code=3,
            status=SourceStatus.READY,
        )
    )
    client.sources.get_fulltext = AsyncMock(
        return_value=SourceFulltext(
            source_id="src-1",
            title="Requirements PDF",
            content="full source text",
            _type_code=3,
            url="https://example.com/spec.pdf",
            char_count=16,
        )
    )
    client.sources.get_guide = AsyncMock(
        return_value={"summary": "Guide summary", "keywords": ["scope", "timeline"]}
    )
    client.sources.check_freshness = AsyncMock(return_value=True)

    adapter = BACapabilityAdapter(client)
    snapshot = await adapter.collect_source_snapshot("nb-1", "src-1")

    assert isinstance(snapshot, BASourceSnapshot)
    assert snapshot.source_type == "pdf"
    assert snapshot.guide_summary == "Guide summary"
    assert snapshot.guide_keywords == ("scope", "timeline")
    assert snapshot.is_fresh is True
    assert snapshot.is_ready is True


@pytest.mark.asyncio
async def test_ask_with_structured_citations_enriches_source_metadata() -> None:
    client = _fake_client()
    client.chat.ask = AsyncMock(
        return_value=AskResult(
            answer="Use the API gateway.",
            conversation_id="conv-1",
            turn_number=2,
            is_follow_up=True,
            references=[
                ChatReference(
                    source_id="src-1",
                    cited_text="gateway handles auth",
                    start_char=10,
                    end_char=20,
                )
            ],
        )
    )
    client.sources.list = AsyncMock(
        return_value=[
            Source(
                id="src-1",
                title="Architecture Note",
                url="https://example.com/arch",
                _type_code=5,
                status=SourceStatus.READY,
            )
        ]
    )

    adapter = BACapabilityAdapter(client)
    result = await adapter.ask_with_structured_citations("nb-1", "What should FE call first?")

    assert isinstance(result, BAStructuredAskResult)
    assert result.answer == "Use the API gateway."
    assert result.citations[0].title == "Architecture Note"
    assert result.citations[0].url == "https://example.com/arch"
    assert result.citations[0].location == "10-20"


@pytest.mark.asyncio
async def test_create_text_source_from_note_content_marks_bridge_as_degraded() -> None:
    client = _fake_client()
    client.sources.add_text = AsyncMock(
        return_value=Source(
            id="src-note",
            title="Research note",
            _type_code=8,
            status=SourceStatus.READY,
        )
    )

    adapter = BACapabilityAdapter(client)
    result = await adapter.create_text_source_from_note_content(
        "nb-1",
        title="Research note",
        content="Converted content",
    )

    assert result.kind == "source"
    assert result.object_id == "src-note"
    assert result.support is not None
    assert result.support.state is BACapabilityState.DEGRADED


@pytest.mark.asyncio
async def test_generate_report_normalizes_generation_status_and_report_format() -> None:
    client = _fake_client()
    client.artifacts.generate_report = AsyncMock(
        return_value=GenerationStatus(task_id="art-1", status="in_progress")
    )

    adapter = BACapabilityAdapter(client)
    task = await adapter.generate_report(
        "nb-1",
        report_format="blog_post",
        source_ids=("src-1", "src-2"),
        language="en",
    )

    assert task.artifact_kind == "report"
    assert task.task_id == "art-1"
    client.artifacts.generate_report.assert_awaited_once_with(
        "nb-1",
        report_format=ReportFormat.BLOG_POST,
        source_ids=["src-1", "src-2"],
        language="en",
        custom_prompt=None,
        extra_instructions=None,
    )


@pytest.mark.asyncio
async def test_generate_mind_map_returns_explicit_degraded_result() -> None:
    client = _fake_client()
    client.artifacts.generate_mind_map = AsyncMock(
        return_value={"mind_map": {"name": "Main Flow"}, "note_id": "note-1"}
    )

    adapter = BACapabilityAdapter(client)
    result = await adapter.generate_mind_map("nb-1", source_ids=("src-1",))

    assert isinstance(result, BAMindMapResult)
    assert result.note_id == "note-1"
    assert result.mind_map == {"name": "Main Flow"}
    assert result.support.state is BACapabilityState.DEGRADED


@pytest.mark.asyncio
async def test_wait_for_source_result_returns_degraded_timeout_payload() -> None:
    client = _fake_client()
    client.sources.wait_until_ready = AsyncMock(
        side_effect=SourceTimeoutError(
            "src-1",
            timeout=30.0,
            last_status=SourceStatus.PROCESSING,
        )
    )
    client.sources.get = AsyncMock(
        return_value=Source(
            id="src-1",
            title="Requirements URL",
            _type_code=5,
            status=SourceStatus.PROCESSING,
        )
    )

    adapter = BACapabilityAdapter(client)
    result = await adapter.wait_for_source_result(
        "nb-1",
        source_key="requirements",
        source_id="src-1",
        timeout=30.0,
    )

    assert isinstance(result, BASourceOperationResult)
    assert result.source_key == "requirements"
    assert result.notebook_source_id == "src-1"
    assert result.readiness_state is BASourceReadinessState.DEGRADED
    assert "30.0s" in (result.degraded_reason or "")


@pytest.mark.asyncio
async def test_ingest_and_wait_ingests_uningested_manifest_rows_and_updates_statuses(
    tmp_path: Path,
) -> None:
    requirements_pdf = tmp_path / "requirements.pdf"
    requirements_pdf.write_text("placeholder", encoding="utf-8")

    client = _fake_client()
    client.sources.add_file = AsyncMock(
        return_value=Source(
            id="src-file",
            title="requirements.pdf",
            _type_code=None,
            status=SourceStatus.PROCESSING,
        )
    )
    client.sources.add_text = AsyncMock(
        return_value=Source(
            id="src-note",
            title="Clarification Note",
            _type_code=8,
            status=SourceStatus.PROCESSING,
        )
    )

    async def _wait_until_ready(
        notebook_id: str,
        source_id: str,
        *,
        timeout: float = 120.0,
    ) -> Source:
        title = "requirements.pdf" if source_id == "src-file" else "Clarification Note"
        type_code = 3 if source_id == "src-file" else 8
        return Source(
            id=source_id,
            title=title,
            _type_code=type_code,
            status=SourceStatus.READY,
        )

    client.sources.wait_until_ready = AsyncMock(side_effect=_wait_until_ready)
    adapter = BACapabilityAdapter(client)
    manifest = SourceManifestDocument(
        run_id="run-1",
        feature_key="customer-create",
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref="requirements.pdf",
                title="Requirements PDF",
            ),
            SourceManifestRow(
                source_key="clarification",
                source_type=SourceType.SUPPORTING_CLARIFICATION,
                priority=SourcePriority.HIGH,
                content_kind=SourceContentKind.INLINE_TEXT,
                source_ref="Clarification note body",
                title="Clarification Note",
            ),
        ],
    )

    result = await adapter.ingest_and_wait(
        "nb-1",
        manifest,
        workspace_root=tmp_path,
        poll_budget_seconds=45.0,
    )

    assert isinstance(result, BAIngestWaitResult)
    assert result.selected_source_keys == ("requirements", "clarification")
    assert result.recommendation is HaltRecommendation.PROCEED
    assert [entry.readiness_state for entry in result.source_results] == [
        BASourceReadinessState.READY,
        BASourceReadinessState.READY,
    ]
    assert [row.notebook_source_id for row in result.manifest.rows] == ["src-file", "src-note"]
    assert [row.status for row in result.manifest.rows] == [
        SourceLifecycleStatus.READY,
        SourceLifecycleStatus.READY,
    ]
    client.sources.add_file.assert_awaited_once()
    client.sources.add_text.assert_awaited_once()
    assert client.sources.wait_until_ready.await_count == 2


@pytest.mark.asyncio
async def test_ingest_and_wait_applies_fail_policy_to_timeout_results() -> None:
    client = _fake_client()
    client.sources.add_url = AsyncMock(
        return_value=Source(
            id="src-url",
            title="Requirements URL",
            _type_code=5,
            status=SourceStatus.PROCESSING,
        )
    )
    client.sources.wait_until_ready = AsyncMock(
        side_effect=SourceTimeoutError(
            "src-url",
            timeout=20.0,
            last_status=SourceStatus.PROCESSING,
        )
    )
    client.sources.get = AsyncMock(
        return_value=Source(
            id="src-url",
            title="Requirements URL",
            _type_code=5,
            status=SourceStatus.PROCESSING,
        )
    )
    adapter = BACapabilityAdapter(client)
    manifest = SourceManifestDocument(
        run_id="run-2",
        feature_key="customer-create",
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.URL,
                source_ref="https://example.com/spec",
                title="Requirements URL",
            )
        ],
    )

    result = await adapter.ingest_and_wait(
        "nb-2",
        manifest,
        poll_budget_seconds=20.0,
        ready_timeout_policy=BAReadyTimeoutPolicy.FAIL,
    )

    assert result.source_results[0].readiness_state is BASourceReadinessState.DEGRADED
    assert result.manifest.rows[0].status is SourceLifecycleStatus.DEGRADED
    assert result.recommendation is HaltRecommendation.HALT
    assert "20.0s" in (result.source_results[0].degraded_reason or "")


@pytest.mark.asyncio
async def test_ingest_and_wait_waits_existing_selected_sources_without_reingesting() -> None:
    client = _fake_client()
    client.sources.wait_until_ready = AsyncMock(
        return_value=Source(
            id="src-existing",
            title="Requirements PDF",
            _type_code=3,
            status=SourceStatus.READY,
        )
    )
    adapter = BACapabilityAdapter(client)
    manifest = SourceManifestDocument(
        run_id="run-3",
        feature_key="customer-create",
        rows=[
            SourceManifestRow(
                source_key="requirements",
                source_type=SourceType.PRIMARY_REQUIREMENT,
                priority=SourcePriority.REQUIRED,
                content_kind=SourceContentKind.FILE_PATH,
                source_ref="requirements.pdf",
                title="Requirements PDF",
                notebook_source_id="src-existing",
                status=SourceLifecycleStatus.INGESTING,
            ),
            SourceManifestRow(
                source_key="glossary",
                source_type=SourceType.SUPPORTING_GLOSSARY,
                priority=SourcePriority.NORMAL,
                content_kind=SourceContentKind.URL,
                source_ref="https://example.com/glossary",
                title="Glossary",
            ),
        ],
    )

    result = await adapter.ingest_and_wait(
        "nb-3",
        manifest,
        source_keys=("requirements",),
    )

    assert result.selected_source_keys == ("requirements",)
    assert [entry.source_key for entry in result.source_results] == ["requirements"]
    assert result.manifest.rows[0].status is SourceLifecycleStatus.READY
    assert result.manifest.rows[1].notebook_source_id is None
    assert getattr(getattr(client.sources, "add_file", None), "await_count", 0) == 0
