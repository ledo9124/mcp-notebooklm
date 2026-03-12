"""Unit tests for BA upstream canary and MCP smoke helpers."""

from __future__ import annotations

from typing import Any

from notebooklm_mcp.ba import canaries as ba_canaries
from notebooklm_mcp.tools import register_tools


class _FakeServer:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, *, name: str | None = None, description: str | None = None):  # pragma: no cover
        assert isinstance(description, str) or description is None

        def _decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return _decorator


def test_sdk_surface_canaries_cover_expected_areas_and_pass() -> None:
    report = ba_canaries.run_sdk_surface_canaries()

    assert report.ok is True
    assert {finding.area for finding in report.findings} == {
        "source_ingest",
        "source_snapshot",
        "structured_chat",
        "notes_bridge",
        "chat_settings",
        "output_language",
        "report_artifacts",
        "data_table_artifacts",
        "mind_map_artifacts",
    }
    assert all(finding.status is ba_canaries.CanaryStatus.PASS for finding in report.findings)


def test_mcp_tool_surface_canaries_pass_for_current_registration() -> None:
    server = _FakeServer()

    register_tools(server)
    report = ba_canaries.run_mcp_tool_surface_canaries(server.tools)

    assert report.ok is True
    assert {finding.area for finding in report.findings} == {
        "ba_public_tools",
        "source_and_chat_tools",
        "notes_bridge_tools",
        "settings_tools",
        "artifact_tools",
    }
    assert all(finding.status is ba_canaries.CanaryStatus.PASS for finding in report.findings)


def test_mcp_tool_surface_canaries_fail_by_capability_area() -> None:
    report = ba_canaries.run_mcp_tool_surface_canaries(
        {
            "ba.start_run",
            "ba.register_sources",
            "ba.status",
            "ba.run_pipeline",
            "notebooklm_notebooks_create",
            "notebooklm_sources_add_text",
            "notebooklm_sources_get_content",
            "notebooklm_chat_ask",
            "notebooklm_notes_list",
            "notebooklm_notes_get",
            "notebooklm_notes_create",
            "notebooklm_settings_get",
            "notebooklm_settings_patch",
            "notebooklm_output_language_get",
            "notebooklm_output_language_set",
            "notebooklm_reports_generate",
            "notebooklm_reports_download",
            "notebooklm_data_tables_generate",
            "notebooklm_data_tables_download",
            "notebooklm_mind_maps_generate",
            "notebooklm_mind_maps_download",
        }
    )

    assert report.ok is False
    failures = {finding.area: finding for finding in report.findings if finding.status is ba_canaries.CanaryStatus.FAIL}
    assert set(failures) == {"ba_public_tools", "notes_bridge_tools"}
    assert "ba.validate_bundle" in failures["ba_public_tools"].details
    assert "ba.rerun_impacted" in failures["ba_public_tools"].details
    assert "notebooklm_notes_create_curated_source" in failures["notes_bridge_tools"].details


def test_sdk_canary_failures_name_the_specific_area() -> None:
    class _BrokenSources:
        async def add_url(self, notebook_id: str, url: str) -> None:
            return None

    finding = ba_canaries._evaluate_sdk_area(  # type: ignore[attr-defined]
        "source_snapshot",
        (
            ba_canaries.MethodCanary(  # type: ignore[attr-defined]
                "_BrokenSources",
                _BrokenSources,
                "get_fulltext",
                ("notebook_id", "source_id"),
            ),
        ),
    )

    assert finding.status is ba_canaries.CanaryStatus.FAIL
    assert finding.area == "source_snapshot"
    assert finding.details == ("_BrokenSources.get_fulltext is missing",)
