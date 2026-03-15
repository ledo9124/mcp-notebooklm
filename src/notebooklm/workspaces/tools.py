"""Host-callable workspace tool wrappers for external agent runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time
from typing import Any, Awaitable, Callable, Literal

from ..client import NotebookLMClient
from ..contracts import Intent
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..observability.tracing import generate_trace_id
from .service import build_workspace_query_envelope, invoke_workspace_query

WorkspaceToolMode = Literal["ask", "compare"]
WorkspaceToolClientFactory = Callable[[str | Path | None], Awaitable[Any]]

_WORKSPACE_ASK_RPC_BINDING = RPC_MAP[(Intent.WORKSPACE_QUERY.value, "workspace_ask")]
_WORKSPACE_COMPARE_RPC_BINDING = RPC_MAP[(Intent.WORKSPACE_COMPARE.value, "workspace_compare")]

_QUESTION_PROPERTY = {
    "type": "string",
    "description": "Question to run against the workspace.",
}

_DESCRIPTION_BY_MODE: dict[WorkspaceToolMode, str] = {
    "ask": "Ask the workspace. The tool selects the most relevant notebooks locally, asks them live in NotebookLM, and returns a synthesized answer with notebook provenance.",
    "compare": "Compare perspectives inside the workspace. The tool keeps notebook-specific positions separate so overlap, differences, and contradictions stay visible, and it may stage local inbox proposals when contradictions need gap-fill follow-up.",
}


def _slugify_workspace_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or value.casefold()


def _binding_for_mode(mode: WorkspaceToolMode):
    if mode == "ask":
        return _WORKSPACE_ASK_RPC_BINDING
    if mode == "compare":
        return _WORKSPACE_COMPARE_RPC_BINDING
    raise ValueError(f"Unsupported workspace tool mode: {mode}")


def _input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"question": dict(_QUESTION_PROPERTY)},
        "required": ["question"],
        "additionalProperties": False,
    }


def _tool_name(workspace_name: str, mode: WorkspaceToolMode) -> str:
    return f"{mode}_workspace_{_slugify_workspace_name(workspace_name).replace('-', '_')}"


def _tool_description(workspace_name: str, mode: WorkspaceToolMode) -> str:
    return f"{workspace_name}: {_DESCRIPTION_BY_MODE[mode]}"


def _normalize_question(question: str) -> str:
    normalized = " ".join(question.split()).strip()
    if not normalized:
        raise ValueError("Workspace tools require a non-empty question.")
    return normalized


async def _default_client_factory(storage_path: str | Path | None) -> NotebookLMClient:
    normalized_path = None if storage_path is None else str(Path(storage_path).expanduser())
    return await NotebookLMClient.from_storage(normalized_path)


@dataclass(frozen=True)
class WorkspaceToolDefinition:
    """Small host-facing descriptor for one callable workspace tool."""

    name: str
    description: str
    input_schema: dict[str, object]
    workspace_name: str
    workspace_slug: str
    mode: WorkspaceToolMode
    profile_id: str | None = None


@dataclass
class WorkspaceTool:
    """Callable wrapper that exposes one workspace ask/compare flow as a tool."""

    workspace_name: str
    mode: WorkspaceToolMode = "ask"
    profile_id: str | None = None
    db_path: str | Path | None = None
    storage_path: str | Path | None = None
    client_factory: WorkspaceToolClientFactory | None = None

    def __post_init__(self) -> None:
        _binding_for_mode(self.mode)

    @property
    def workspace_slug(self) -> str:
        return _slugify_workspace_name(self.workspace_name)

    @property
    def name(self) -> str:
        return _tool_name(self.workspace_name, self.mode)

    @property
    def description(self) -> str:
        return _tool_description(self.workspace_name, self.mode)

    @property
    def input_schema(self) -> dict[str, object]:
        return _input_schema()

    @property
    def definition(self) -> WorkspaceToolDefinition:
        return WorkspaceToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            workspace_name=self.workspace_name,
            workspace_slug=self.workspace_slug,
            mode=self.mode,
            profile_id=self.profile_id,
        )

    async def invoke(self, question: str) -> dict[str, object]:
        normalized_question = _normalize_question(question)
        binding = _binding_for_mode(self.mode)
        trace_id = generate_trace_id()
        started_at = time.perf_counter()
        client_factory = self.client_factory or _default_client_factory
        client = await client_factory(self.storage_path)

        async with client as active_client:

            async def _ask_notebook(candidate, prompt: str):
                return await active_client.chat.ask(candidate.notebook_id, prompt)

            with connect_db(self.db_path) as connection:
                invocation = await invoke_workspace_query(
                    connection,
                    profile_id=self.profile_id,
                    name_or_slug=self.workspace_name,
                    question=normalized_question,
                    trace_id=trace_id,
                    ask_notebook=_ask_notebook,
                    mode=self.mode,
                )

        elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        return build_workspace_query_envelope(
            trace_id=trace_id,
            elapsed_ms=elapsed_ms,
            invocation=invocation,
            intent=Intent(binding.intent),
            route_mode=binding.mode,
            transport_kind=binding.transport_kind,
        )

    async def __call__(self, question: str) -> dict[str, object]:
        return await self.invoke(question)


def build_workspace_tool(
    workspace_name: str,
    *,
    mode: WorkspaceToolMode = "ask",
    profile_id: str | None = None,
    db_path: str | Path | None = None,
    storage_path: str | Path | None = None,
    client_factory: WorkspaceToolClientFactory | None = None,
) -> WorkspaceTool:
    """Return a host-callable wrapper for one workspace ask/compare flow."""
    return WorkspaceTool(
        workspace_name=workspace_name,
        mode=mode,
        profile_id=profile_id,
        db_path=db_path,
        storage_path=storage_path,
        client_factory=client_factory,
    )


__all__ = [
    "WorkspaceTool",
    "WorkspaceToolClientFactory",
    "WorkspaceToolDefinition",
    "WorkspaceToolMode",
    "build_workspace_tool",
]
