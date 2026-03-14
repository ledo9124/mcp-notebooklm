"""NotebookLM CLI package.

Exports only the command groups and registration hooks used by the root CLI shell.
"""

from .chat import register_chat_commands
from .generate import generate
from .notebook import register_notebook_commands
from .research import research
from .session import register_session_commands
from .source import source

__all__ = [
    "source",
    "generate",
    "research",
    "register_session_commands",
    "register_notebook_commands",
    "register_chat_commands",
]
