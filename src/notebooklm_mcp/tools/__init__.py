"""Tool registration for notebooklm-mcp."""

from __future__ import annotations

from typing import Any

from ..ba.tools import register_ba_tools
from .artifacts import register_artifact_tools
from .chat import register_chat_tools
from .chat_settings import register_chat_settings_tools
from .experimental_artifacts import register_experimental_artifact_tools
from .mind_maps import register_mind_map_tools
from .notes import register_notes_tools
from .notebooks import register_notebook_tools
from .ops import register_ops_tools
from .settings import register_settings_tools
from .sources import register_sources_tools
from .workflows import register_workflow_tools


def register_tools(_server: Any) -> None:
    """Register MCP tools with the server instance.

    Tool implementations are added in follow-up beads.
    """
    register_notebook_tools(_server)
    register_notes_tools(_server)
    register_sources_tools(_server)
    register_chat_tools(_server)
    register_chat_settings_tools(_server)
    register_artifact_tools(_server)
    register_mind_map_tools(_server)
    register_experimental_artifact_tools(_server)
    register_settings_tools(_server)
    register_ops_tools(_server)
    register_workflow_tools(_server)
    register_ba_tools(_server)
