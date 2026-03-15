"""CLI interface for NotebookLM automation.

Canonical grammar families are frozen around:
  notebooklm auth <subcommand>
  notebooklm notebook <subcommand>
  notebooklm source <subcommand>
  notebooklm sync <subcommand>
  notebooklm cache <subcommand>
  notebooklm <workflow-root>
  notebooklm <maintenance-root>

Current shipped commands remain a transitional compatibility surface:
  notebooklm login                    # Authenticate
  notebooklm use <notebook_id>        # Set current notebook context
  notebooklm status                   # Show current context
  notebooklm auth check               # Validate auth and diagnose issues
  notebooklm auth inspect             # Inspect persisted auth/profile state
  notebooklm auth refresh             # Force homepage refresh and persist auth state
  notebooklm doctor                   # Fast local health check
  notebooklm list                     # List notebooks
  notebooklm create <title>           # Create notebook
  notebooklm overview                 # Get a lightweight notebook overview
  notebooklm summary                  # Summarize the current notebook
  notebooklm ask <question>           # Ask the current notebook a question
  notebooklm source <command>         # Source add/list/wait operations
  notebooklm sync <command>           # Explicit metadata sync operations
  notebooklm history <command>        # Local history search/show operations
  notebooklm watch <command>          # Manage local radar watch definitions
  notebooklm radar <command>          # Review radar events and stored briefings
  notebooklm cache <command>          # Local cache diagnostics and maintenance
  notebooklm workspace <command>      # Local workspace management and indexing
  notebooklm summarize                # Generate a briefing document
  notebooklm study-guide              # Generate a study guide
  notebooklm audio                    # Generate an audio overview
  notebooklm generate <type>          # Compatibility artifact subcommands
  notebooklm research <command>       # Monitor research started via source add-research
  notebooklm agent "request"          # Route one natural-language request
  notebooklm route <command>          # Explain experimental routing decisions

See docs/cli-reference.md for the frozen grammar map and the currently shipped
normalization-era command surface.
"""

# Runtime Python version guard (must run before any PEP 604 syntax is evaluated)
import sys

from ._version_check import check_python_version as _check_python_version

_check_python_version()
del _check_python_version

import asyncio
import logging
import os
from pathlib import Path

# =============================================================================
# WINDOWS COMPATIBILITY FIXES (issue #75, #79, #80)
# Must be applied before any async code runs
# =============================================================================

if sys.platform == "win32":
    # Fix #79: Windows asyncio ProactorEventLoop can hang indefinitely at IOCP layer
    # (GetQueuedCompletionStatus) in certain environments like Sandboxie.
    # SelectorEventLoop avoids this issue.
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Fix #80: Non-English Windows systems (cp950, cp932, etc.) can fail with
    # UnicodeEncodeError when outputting Unicode characters like checkmarks.
    # Setting PYTHONUTF8 ensures consistent UTF-8 encoding.
    os.environ.setdefault("PYTHONUTF8", "1")

import click

from . import __version__
from .auth import DEFAULT_STORAGE_PATH
from .observability import bind_trace

# Import command groups from cli package
from .cli import (
    agent,
    cache,
    events,
    generate,
    history,
    inbox,
    radar,
    register_chat_commands,
    register_doctor_commands,
    register_generate_workflow_commands,
    register_notebook_commands,
    register_overview_commands,
    register_session_commands,
    research,
    route,
    source,
    sync,
    trace,
    watch,
    workspace,
)
from .cli.grouped import SectionedGroup

# Import helpers needed for backward compatibility with tests


# =============================================================================
# MAIN CLI GROUP
# =============================================================================


@click.group(cls=SectionedGroup)
@click.version_option(version=__version__, prog_name="NotebookLM CLI")
@click.option(
    "--storage",
    type=click.Path(exists=False),
    default=None,
    help=f"Path to storage_state.json (default: {DEFAULT_STORAGE_PATH})",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v for INFO, -vv for DEBUG)",
)
@click.pass_context
def cli(ctx, storage, verbose):
    """NotebookLM CLI.

    \b
    Canonical grammar freeze:
      auth / notebook / source / sync / workflow roots / maintenance commands

    Compatibility note:
      The currently shipped direct roots (`login`, `list`, `create`, `overview`,
      `summary`, `generate`, etc.) remain available during normalization. See
      docs/cli-reference.md for the frozen command-family map.

    \b
    Quick start:
      notebooklm login              # Authenticate first
      notebooklm list               # List your notebooks
      notebooklm create "My Notes"  # Create a notebook
      notebooklm ask "Hi"           # Ask the current notebook a question

    \b
    Tip: Use partial notebook IDs (e.g., 'notebooklm use abc' matches 'abc123...')
    """
    # Configure logging based on verbosity: -v for INFO, -vv+ for DEBUG
    if verbose >= 2:
        logging.getLogger("notebooklm").setLevel(logging.DEBUG)
    elif verbose == 1:
        logging.getLogger("notebooklm").setLevel(logging.INFO)

    ctx.ensure_object(dict)
    trace_binding = bind_trace()
    trace = trace_binding.__enter__()
    ctx.call_on_close(lambda: trace_binding.__exit__(None, None, None))
    ctx.obj["trace"] = trace
    ctx.obj["trace_id"] = trace.trace_id
    ctx.obj["storage_path"] = Path(storage) if storage else None


# =============================================================================
# REGISTER COMMANDS
# =============================================================================

# Register top-level commands from modules
register_session_commands(cli)
register_notebook_commands(cli)
register_chat_commands(cli)
register_overview_commands(cli)
register_doctor_commands(cli)
register_generate_workflow_commands(cli)

# Register command groups (subcommand style)
cli.add_command(source)
cli.add_command(sync)
cli.add_command(history)
cli.add_command(trace)
cli.add_command(events)
cli.add_command(cache)
cli.add_command(agent)
cli.add_command(generate)
cli.add_command(inbox)
cli.add_command(watch)
cli.add_command(radar)
cli.add_command(research)
cli.add_command(route)
cli.add_command(workspace)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    # Windows-specific fixes
    if sys.platform == "win32":
        # Force UTF-8 encoding for Unicode output on non-English Windows systems
        # Prevents UnicodeEncodeError when displaying Unicode characters (✓, ✗, box drawing)
        # on systems with legacy encodings (cp950, cp932, cp936, etc.)
        os.environ.setdefault("PYTHONUTF8", "1")

        # Fix asyncio hanging issue - use WindowsSelectorEventLoopPolicy instead of
        # default ProactorEventLoop to avoid IOCP blocking on network operations
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    cli()


if __name__ == "__main__":
    main()
