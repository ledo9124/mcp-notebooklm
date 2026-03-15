"""NotebookLM CLI package.

Exports only the command groups and registration hooks used by the root CLI shell.
"""

from .chat import register_chat_commands
from .agent import agent
from .cache import cache
from .doctor import register_doctor_commands
from .events import events
from .generate import generate, register_generate_workflow_commands
from .history import history
from .inbox import inbox
from .notebook import register_notebook_commands
from .overview import register_overview_commands
from .radar import radar, watch
from .research import research
from .route import route
from .session import register_session_commands
from .source import source
from .sync import sync
from .trace import trace
from .workspace import workspace

__all__ = [
    "agent",
    "cache",
    "events",
    "history",
    "inbox",
    "radar",
    "watch",
    "route",
    "source",
    "sync",
    "trace",
    "workspace",
    "generate",
    "register_generate_workflow_commands",
    "register_overview_commands",
    "research",
    "register_doctor_commands",
    "register_session_commands",
    "register_notebook_commands",
    "register_chat_commands",
]
