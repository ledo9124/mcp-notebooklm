"""Structural canaries for BA-runner upstream and MCP-surface drift.

These checks are intentionally cheap: they validate the exact SDK and MCP
surfaces the BA runner depends on most without requiring live NotebookLM
network access. Their job is to fail by capability area when upstream code
moves in a way that would break the BA adapter or the public `ba.*` layer.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum
import inspect
from typing import Any

from notebooklm._artifacts import ArtifactsAPI
from notebooklm._chat import ChatAPI
from notebooklm._notes import NotesAPI
from notebooklm._settings import SettingsAPI
from notebooklm._sources import SourcesAPI


class CanaryStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class MethodCanary:
    owner_name: str
    owner: type[Any]
    method_name: str
    required_params: tuple[str, ...]


@dataclass(frozen=True)
class ToolCanary:
    area: str
    required_tools: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class CanaryFinding:
    area: str
    status: CanaryStatus
    summary: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanaryReport:
    name: str
    findings: tuple[CanaryFinding, ...]

    @property
    def ok(self) -> bool:
        return all(finding.status is not CanaryStatus.FAIL for finding in self.findings)

    @property
    def failed_areas(self) -> tuple[str, ...]:
        return tuple(finding.area for finding in self.findings if finding.status is CanaryStatus.FAIL)


SDK_CANARIES: dict[str, tuple[MethodCanary, ...]] = {
    "source_ingest": (
        MethodCanary("SourcesAPI", SourcesAPI, "add_url", ("notebook_id", "url")),
        MethodCanary("SourcesAPI", SourcesAPI, "add_text", ("notebook_id", "title", "content")),
        MethodCanary("SourcesAPI", SourcesAPI, "add_file", ("notebook_id", "file_path")),
        MethodCanary("SourcesAPI", SourcesAPI, "add_drive", ("notebook_id", "file_id", "title")),
        MethodCanary(
            "SourcesAPI",
            SourcesAPI,
            "wait_until_ready",
            ("notebook_id", "source_id", "timeout"),
        ),
    ),
    "source_snapshot": (
        MethodCanary("SourcesAPI", SourcesAPI, "list", ("notebook_id",)),
        MethodCanary("SourcesAPI", SourcesAPI, "get", ("notebook_id", "source_id")),
        MethodCanary("SourcesAPI", SourcesAPI, "get_fulltext", ("notebook_id", "source_id")),
        MethodCanary("SourcesAPI", SourcesAPI, "get_guide", ("notebook_id", "source_id")),
        MethodCanary("SourcesAPI", SourcesAPI, "check_freshness", ("notebook_id", "source_id")),
    ),
    "structured_chat": (
        MethodCanary("ChatAPI", ChatAPI, "ask", ("notebook_id", "question")),
        MethodCanary("ChatAPI", ChatAPI, "get_conversation_id", ("notebook_id",)),
        MethodCanary("ChatAPI", ChatAPI, "get_history", ("notebook_id", "limit")),
    ),
    "notes_bridge": (
        MethodCanary("NotesAPI", NotesAPI, "list", ("notebook_id",)),
        MethodCanary("NotesAPI", NotesAPI, "get", ("notebook_id", "note_id")),
        MethodCanary("NotesAPI", NotesAPI, "create", ("notebook_id", "title", "content")),
        MethodCanary("NotesAPI", NotesAPI, "update", ("notebook_id", "note_id", "content", "title")),
        MethodCanary("NotesAPI", NotesAPI, "delete", ("notebook_id", "note_id")),
        MethodCanary("SourcesAPI", SourcesAPI, "add_text", ("notebook_id", "title", "content")),
    ),
    "chat_settings": (
        MethodCanary("ChatAPI", ChatAPI, "get_settings", ("notebook_id", "strict")),
        MethodCanary("ChatAPI", ChatAPI, "set_settings", ("notebook_id", "settings")),
        MethodCanary("ChatAPI", ChatAPI, "update_settings", ("notebook_id",)),
        MethodCanary("ChatAPI", ChatAPI, "reset_settings", ("notebook_id",)),
    ),
    "output_language": (
        MethodCanary("SettingsAPI", SettingsAPI, "get_output_language", ()),
        MethodCanary("SettingsAPI", SettingsAPI, "set_output_language", ("language",)),
    ),
    "report_artifacts": (
        MethodCanary("ArtifactsAPI", ArtifactsAPI, "generate_report", ("notebook_id",)),
        MethodCanary(
            "ArtifactsAPI",
            ArtifactsAPI,
            "wait_for_completion",
            ("notebook_id", "task_id"),
        ),
        MethodCanary("ArtifactsAPI", ArtifactsAPI, "download_report", ("notebook_id", "output_path")),
        MethodCanary("ArtifactsAPI", ArtifactsAPI, "export_report", ("notebook_id", "artifact_id")),
    ),
    "data_table_artifacts": (
        MethodCanary("ArtifactsAPI", ArtifactsAPI, "generate_data_table", ("notebook_id",)),
        MethodCanary(
            "ArtifactsAPI",
            ArtifactsAPI,
            "wait_for_completion",
            ("notebook_id", "task_id"),
        ),
        MethodCanary(
            "ArtifactsAPI",
            ArtifactsAPI,
            "download_data_table",
            ("notebook_id", "output_path"),
        ),
        MethodCanary("ArtifactsAPI", ArtifactsAPI, "export_data_table", ("notebook_id", "artifact_id")),
    ),
    "mind_map_artifacts": (
        MethodCanary("ArtifactsAPI", ArtifactsAPI, "generate_mind_map", ("notebook_id",)),
        MethodCanary("ArtifactsAPI", ArtifactsAPI, "download_mind_map", ("notebook_id", "output_path")),
    ),
}

MCP_TOOL_CANARIES: tuple[ToolCanary, ...] = (
    ToolCanary(
        area="ba_public_tools",
        required_tools=(
            "ba.start_run",
            "ba.register_sources",
            "ba.status",
            "ba.validate_bundle",
            "ba.run_pipeline",
            "ba.rerun_impacted",
        ),
        summary="Workflow-native BA MCP handlers remain publicly registered.",
    ),
    ToolCanary(
        area="source_and_chat_tools",
        required_tools=(
            "notebooklm_notebooks_create",
            "notebooklm_sources_add_text",
            "notebooklm_sources_get_content",
            "notebooklm_chat_ask",
        ),
        summary="Generic notebook/source/chat tools required for BA bootstrap and source inspection remain registered.",
    ),
    ToolCanary(
        area="notes_bridge_tools",
        required_tools=(
            "notebooklm_notes_list",
            "notebooklm_notes_get",
            "notebooklm_notes_create",
            "notebooklm_notes_create_curated_source",
        ),
        summary="Note CRUD and note-to-source bridge helpers remain registered.",
    ),
    ToolCanary(
        area="settings_tools",
        required_tools=(
            "notebooklm_settings_get",
            "notebooklm_settings_patch",
            "notebooklm_output_language_get",
            "notebooklm_output_language_set",
        ),
        summary="Notebook chat settings and global output-language tools remain registered.",
    ),
    ToolCanary(
        area="artifact_tools",
        required_tools=(
            "notebooklm_reports_generate",
            "notebooklm_reports_download",
            "notebooklm_data_tables_generate",
            "notebooklm_data_tables_download",
            "notebooklm_mind_maps_generate",
            "notebooklm_mind_maps_download",
        ),
        summary="Artifact helpers used by BA support flows remain registered.",
    ),
)


def run_sdk_surface_canaries() -> CanaryReport:
    """Validate the exact NotebookLM SDK surfaces the BA adapter relies on."""
    findings = tuple(
        _evaluate_sdk_area(area, checks)
        for area, checks in SDK_CANARIES.items()
    )
    return CanaryReport(name="sdk_surface", findings=findings)


def run_mcp_tool_surface_canaries(tool_names: Collection[str]) -> CanaryReport:
    """Validate the registered MCP tools needed by BA workflows and support paths."""
    available = set(tool_names)
    findings = tuple(_evaluate_tool_area(canary, available) for canary in MCP_TOOL_CANARIES)
    return CanaryReport(name="mcp_tool_surface", findings=findings)


def _evaluate_sdk_area(area: str, checks: Sequence[MethodCanary]) -> CanaryFinding:
    problems: list[str] = []
    for check in checks:
        method = getattr(check.owner, check.method_name, None)
        if method is None:
            problems.append(f"{check.owner_name}.{check.method_name} is missing")
            continue

        signature = inspect.signature(method)
        params = tuple(signature.parameters)
        missing_params = [param for param in check.required_params if param not in params]
        if missing_params:
            problems.append(
                f"{check.owner_name}.{check.method_name} is missing parameter(s): "
                + ", ".join(missing_params)
            )

    if problems:
        return CanaryFinding(
            area=area,
            status=CanaryStatus.FAIL,
            summary=f"{area} drifted away from the BA adapter's expected SDK surface.",
            details=tuple(problems),
        )

    return CanaryFinding(
        area=area,
        status=CanaryStatus.PASS,
        summary=f"{area} still matches the SDK surface expected by the BA adapter.",
    )


def _evaluate_tool_area(canary: ToolCanary, available: Collection[str]) -> CanaryFinding:
    missing = tuple(tool for tool in canary.required_tools if tool not in available)
    if missing:
        return CanaryFinding(
            area=canary.area,
            status=CanaryStatus.FAIL,
            summary=f"{canary.area} lost one or more required MCP tools.",
            details=missing,
        )

    return CanaryFinding(
        area=canary.area,
        status=CanaryStatus.PASS,
        summary=canary.summary,
    )


__all__ = [
    "CanaryFinding",
    "CanaryReport",
    "CanaryStatus",
    "MCP_TOOL_CANARIES",
    "SDK_CANARIES",
    "ToolCanary",
    "run_mcp_tool_surface_canaries",
    "run_sdk_surface_canaries",
]
