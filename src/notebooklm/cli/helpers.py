"""CLI helper utilities.

Provides common functionality for all CLI commands:
- Authentication handling (get_client)
- Async execution (run_async)
- Error handling
- JSON/Rich output formatting
- Context management (current notebook/conversation)
- @with_client decorator for command boilerplate reduction
"""

import asyncio
import json
import logging
import os
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from ..auth import (
    _get_storage_path_for_persistence,
    AuthTokens,
    fetch_tokens,
    load_auth_from_storage,
)
from ..contracts import CacheUpdates, Diagnostics, Envelope, Freshness, Intent, Route, Transport
from ..local.db import connect_db
from ..paths import get_browser_profile_dir, get_context_path
from ..sync import sync_notebook_index

console = Console()
logger = logging.getLogger(__name__)

# Backward-compatible module-level constants (for tests that patch these)
# Note: Prefer using get_context_path() and get_browser_profile_dir() for dynamic resolution
# These are evaluated once at import time, so NOTEBOOKLM_HOME changes after import won't affect them
CONTEXT_FILE = get_context_path()
BROWSER_PROFILE_DIR = get_browser_profile_dir()


# =============================================================================
# ASYNC EXECUTION
# =============================================================================


def run_async(coro):
    """Run async coroutine in sync context."""
    return asyncio.run(coro)


# =============================================================================
# AUTHENTICATION
# =============================================================================


def _compat_build_label() -> str:
    """Return a non-empty compatibility build label for legacy test stubs."""
    return os.environ.get("NOTEBOOKLM_BL", "boq_labs-tailwind-frontend_compat")


def get_client(ctx) -> tuple[dict, str, str, str]:
    """Get auth components from context.

    Args:
        ctx: Click context with optional storage_path in obj

    Returns:
        Tuple of (cookies, csrf_token, session_id, build_label)

    Raises:
        FileNotFoundError: If auth storage not found
    """
    storage_path = ctx.obj.get("storage_path") if ctx.obj else None
    cookies = load_auth_from_storage(storage_path)
    fetched = run_async(fetch_tokens(cookies))
    if len(fetched) == 2:
        csrf, session_id = fetched
        build_label = _compat_build_label()
        logger.warning(
            "fetch_tokens returned a legacy 2-tuple; using compatibility build label %s",
            build_label,
        )
    else:
        csrf, session_id, build_label = fetched
    return cookies, csrf, session_id, build_label


def get_auth_tokens(ctx) -> AuthTokens:
    """Get AuthTokens object from context.

    Args:
        ctx: Click context

    Returns:
        AuthTokens ready for client construction
    """
    cookies, csrf, session_id, build_label = get_client(ctx)
    storage_path = ctx.obj.get("storage_path") if ctx.obj else None
    return AuthTokens(
        cookies=cookies,
        csrf_token=csrf,
        session_id=session_id,
        build_label=build_label,
        storage_path=_get_storage_path_for_persistence(storage_path),
    )


# =============================================================================
# CONTEXT MANAGEMENT
# =============================================================================


def _get_context_value(key: str) -> str | None:
    """Read a single value from context.json."""
    context_file = get_context_path()
    if not context_file.exists():
        return None
    try:
        data = json.loads(context_file.read_text(encoding="utf-8"))
        return data.get(key)
    except json.JSONDecodeError:
        logger.warning(
            "Context file %s is corrupted; cannot read '%s'. Run 'notebooklm clear' to reset.",
            context_file,
            key,
        )
        return None
    except OSError as e:
        logger.warning("Cannot read context file %s: %s", context_file, e)
        return None


def _set_context_value(key: str, value: str | None) -> None:
    """Set or clear a single value in context.json."""
    context_file = get_context_path()
    if not context_file.exists():
        return
    try:
        data = json.loads(context_file.read_text(encoding="utf-8"))
        if value is not None:
            data[key] = value
        elif key in data:
            del data[key]
        context_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except json.JSONDecodeError:
        logger.warning(
            "Context file %s is corrupted; cannot update '%s'. Run 'notebooklm clear' to reset.",
            context_file,
            key,
        )
    except OSError as e:
        logger.warning("Failed to write context file %s for key '%s': %s", context_file, key, e)


def get_current_notebook() -> str | None:
    """Get the current notebook ID from context."""
    return _get_context_value("notebook_id")


def set_current_notebook(
    notebook_id: str,
    title: str | None = None,
    is_owner: bool | None = None,
    created_at: str | None = None,
):
    """Set the current notebook context.

    conversation_id is never preserved — the server owns the canonical ID per
    notebook, and a stale local value would silently use the wrong UUID.
    """
    context_file = get_context_path()
    context_file.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, str | bool] = {"notebook_id": notebook_id}
    if title:
        data["title"] = title
    if is_owner is not None:
        data["is_owner"] = is_owner
    if created_at:
        data["created_at"] = created_at

    context_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_context():
    """Clear the current context."""
    context_file = get_context_path()
    if context_file.exists():
        context_file.unlink()


def get_current_conversation() -> str | None:
    """Get the current conversation ID from context."""
    return _get_context_value("conversation_id")


def set_current_conversation(conversation_id: str | None):
    """Set or clear the current conversation ID in context."""
    _set_context_value("conversation_id", conversation_id)


def validate_id(entity_id: str, entity_name: str = "ID") -> str:
    """Validate and normalize an entity ID.

    Args:
        entity_id: The ID to validate
        entity_name: Name for error messages (e.g., "notebook", "source")

    Returns:
        Stripped ID

    Raises:
        click.ClickException: If ID is empty or whitespace-only
    """
    if not entity_id or not entity_id.strip():
        raise click.ClickException(f"{entity_name} ID cannot be empty")
    return entity_id.strip()


def require_notebook(notebook_id: str | None) -> str:
    """Get notebook ID from argument or context, raise if neither.

    Args:
        notebook_id: Optional notebook ID from command argument

    Returns:
        Notebook ID (from argument or context), validated and stripped

    Raises:
        SystemExit: If no notebook ID available
        click.ClickException: If notebook ID is empty/whitespace
    """
    if notebook_id:
        return validate_id(notebook_id, "Notebook")
    current = get_current_notebook()
    if current:
        return validate_id(current, "Notebook")
    console.print(
        "[red]No notebook specified. Use 'notebooklm use <id>' to set context or provide notebook_id.[/red]"
    )
    raise SystemExit(1)


def _notebook_identifier(item: Any) -> str:
    identifier = getattr(item, "id", None)
    if identifier is None:
        identifier = getattr(item, "notebook_id", None)
    return str(identifier or "")


def _raise_ambiguous_id_error(partial_id: str, matches: list[Any], entity_name: str) -> None:
    lines = [f"Ambiguous ID '{partial_id}' matches {len(matches)} {entity_name}s:"]
    for item in matches[:5]:
        title = getattr(item, "title", None) or "(untitled)"
        lines.append(f"  {_notebook_identifier(item)[:12]}... {title}")
    if len(matches) > 5:
        lines.append(f"  ... and {len(matches) - 5} more")
    lines.append("\nSpecify more characters to narrow down.")
    raise click.ClickException("\n".join(lines))


async def _resolve_cached_long_notebook_id(client, partial_id: str) -> str:
    storage_path = getattr(getattr(client, "auth", None), "storage_path", None)
    with connect_db() as connection:
        state = await sync_notebook_index(
            client,
            connection,
            storage_path=storage_path,
        )
        matches = [
            notebook
            for notebook in state.notebooks
            if _notebook_identifier(notebook).lower().startswith(partial_id.lower())
        ]
        if not matches and state.used_cache:
            state = await sync_notebook_index(
                client,
                connection,
                storage_path=storage_path,
                force_refresh=True,
            )
            matches = [
                notebook
                for notebook in state.notebooks
                if _notebook_identifier(notebook).lower().startswith(partial_id.lower())
            ]

    if len(matches) == 1:
        return _notebook_identifier(matches[0])
    if len(matches) == 0:
        raise click.ClickException(
            f"No notebook found matching '{partial_id}'. "
            "Run 'notebooklm list --refresh' to see available notebooks."
        )
    _raise_ambiguous_id_error(partial_id, matches, "notebook")


async def _resolve_partial_id(
    partial_id: str,
    list_fn,
    entity_name: str,
    list_command: str,
    long_id_resolver=None,
) -> str:
    """Generic partial ID resolver.

    Allows users to type partial IDs like 'abc' instead of full UUIDs.
    Matches are case-insensitive prefix matches.

    Args:
        partial_id: Full or partial ID to resolve
        list_fn: Async function that returns list of items with id/title attributes
        entity_name: Name for error messages (e.g., "notebook", "source")
        list_command: CLI command to list items (e.g., "list", "source list")

    Returns:
        Full ID of the matched item

    Raises:
        click.ClickException: If ID is empty, no match, or ambiguous match
    """
    # Validate and normalize the ID
    partial_id = validate_id(partial_id, entity_name)

    # Skip resolution for IDs that look complete (20+ chars)
    if len(partial_id) >= 20:
        if long_id_resolver is not None:
            return await long_id_resolver(partial_id)
        return partial_id

    items = await list_fn()
    matches = [item for item in items if item.id.lower().startswith(partial_id.lower())]

    if len(matches) == 1:
        if matches[0].id != partial_id:
            title = matches[0].title or "(untitled)"
            console.print(f"[dim]Matched: {matches[0].id[:12]}... ({title})[/dim]")
        return matches[0].id
    elif len(matches) == 0:
        raise click.ClickException(
            f"No {entity_name} found starting with '{partial_id}'. "
            f"Run 'notebooklm {list_command}' to see available {entity_name}s."
        )
    else:
        lines = [f"Ambiguous ID '{partial_id}' matches {len(matches)} {entity_name}s:"]
        for item in matches[:5]:
            title = item.title or "(untitled)"
            lines.append(f"  {item.id[:12]}... {title}")
        if len(matches) > 5:
            lines.append(f"  ... and {len(matches) - 5} more")
        lines.append("\nSpecify more characters to narrow down.")
        raise click.ClickException("\n".join(lines))


async def resolve_notebook_id(client, partial_id: str) -> str:
    """Resolve partial notebook ID to full ID."""
    return await _resolve_partial_id(
        partial_id,
        list_fn=lambda: client.notebooks.list(),
        entity_name="notebook",
        list_command="list",
        long_id_resolver=lambda value: _resolve_cached_long_notebook_id(client, value),
    )


async def resolve_source_id(client, notebook_id: str, partial_id: str) -> str:
    """Resolve partial source ID to full ID."""
    return await _resolve_partial_id(
        partial_id,
        list_fn=lambda: client.sources.list(notebook_id),
        entity_name="source",
        list_command="source list",
    )


async def resolve_source_ids(
    client, notebook_id: str, source_ids: tuple[str, ...]
) -> list[str] | None:
    """Resolve multiple partial source IDs to full IDs.

    Args:
        client: NotebookLM client
        notebook_id: Resolved notebook ID
        source_ids: Tuple of partial source IDs from CLI

    Returns:
        List of resolved source IDs, or None if no source IDs provided
    """
    if not source_ids:
        return None
    resolved = []
    for sid in source_ids:
        resolved.append(await resolve_source_id(client, notebook_id, sid))
    return resolved


# =============================================================================
# ERROR HANDLING
# =============================================================================


def handle_error(e: Exception):
    """Handle and display errors consistently."""
    console.print(f"[red]Error: {e}[/red]")
    raise SystemExit(1)


def emit_local_json_error(
    code: str,
    message: str,
    *,
    mode: str,
    reason: str,
    extra: Mapping[str, Any] | None = None,
    ctx: click.Context | None = None,
    diagnostics: Diagnostics | None = None,
    exit_code: int = 1,
) -> None:
    """Emit a canonical local-only JSON error envelope and exit."""
    json_error_response(
        code,
        message,
        extra=dict(extra) if extra else None,
        ctx=ctx,
        intent=Intent.LOCAL_METADATA,
        mode=mode,
        source_of_truth="local_cache",
        cache_mode="offline",
        reason=reason,
        transport=Transport(kind="local"),
        diagnostics=diagnostics,
        exit_code=exit_code,
    )


def handle_auth_error(
    json_output: bool = False,
    *,
    ctx: click.Context | None = None,
    mode: str = "auth_required",
    elapsed_ms: int = 0,
):
    """Handle authentication errors with helpful context."""
    from ..paths import get_path_info, get_storage_path

    path_info = get_path_info()
    storage_path = get_storage_path()
    has_env_var = bool(os.environ.get("NOTEBOOKLM_AUTH_JSON"))
    has_home_env = bool(os.environ.get("NOTEBOOKLM_HOME"))
    storage_source = path_info["home_source"]

    if json_output:
        emit_local_json_error(
            "AUTH_REQUIRED",
            "Auth not found. Run 'notebooklm login' first.",
            mode=mode,
            ctx=ctx,
            reason="Load local NotebookLM authentication before executing the requested CLI command.",
            extra={
                "checked_paths": {
                    "storage_file": str(storage_path),
                    "storage_source": storage_source,
                    "env_var": "NOTEBOOKLM_AUTH_JSON" if has_env_var else None,
                },
                "help": "Run 'notebooklm login' or set NOTEBOOKLM_AUTH_JSON",
            },
            diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
        )
    else:
        console.print("[red]Not logged in.[/red]\n")
        console.print("[dim]Checked locations:[/dim]")
        console.print(f"  • Storage file: [cyan]{storage_path}[/cyan]")
        if has_home_env:
            console.print("    [dim](via $NOTEBOOKLM_HOME)[/dim]")
        env_status = "[yellow]set but invalid[/yellow]" if has_env_var else "[dim]not set[/dim]"
        console.print(f"  • NOTEBOOKLM_AUTH_JSON: {env_status}")
        console.print("\n[bold]Options to authenticate:[/bold]")
        console.print("  1. Run: [green]notebooklm login[/green]")
        console.print("  2. Set [cyan]NOTEBOOKLM_AUTH_JSON[/cyan] env var (for CI/CD)")
        console.print("  3. Use [cyan]--storage /path/to/file.json[/cyan] flag")
        raise SystemExit(1)


# =============================================================================
# DECORATORS
# =============================================================================


def with_client(f):
    """Decorator that handles auth, async execution, and errors for CLI commands.

    This decorator eliminates boilerplate from commands that need:
    - Authentication (get AuthTokens from context)
    - Async execution (run coroutine with asyncio.run)
    - Error handling (auth errors, general exceptions)

    The decorated function stays SYNC (Click doesn't support async) but returns
    a coroutine. The decorator runs the coroutine and handles errors.

    Usage:
        @cli.command("list")
        @click.option("--json", "json_output", is_flag=True)
        @with_client
        def list_notebooks(ctx, json_output, client_auth):
            async def _run():
                async with NotebookLMClient(client_auth) as client:
                    notebooks = await client.notebooks.list()
                    output_notebooks(notebooks, json_output)
            return _run()

    Args:
        f: Function that accepts client_auth (AuthTokens) and returns a coroutine

    Returns:
        Decorated function with Click pass_context
    """

    @wraps(f)
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        cmd_name = f.__name__
        start = time.monotonic()
        logger.debug("CLI command starting: %s", cmd_name)

        json_output = kwargs.get("json_output", False)

        def log_result(status: str, detail: str = "") -> float:
            elapsed = time.monotonic() - start
            if detail:
                logger.debug("CLI command %s: %s (%.3fs) - %s", status, cmd_name, elapsed, detail)
            else:
                logger.debug("CLI command %s: %s (%.3fs)", status, cmd_name, elapsed)
            return elapsed

        try:
            auth = get_auth_tokens(ctx)
            coro = f(ctx, *args, client_auth=auth, **kwargs)
            result = run_async(coro)
            log_result("completed")
            return result
        except FileNotFoundError:
            elapsed = log_result("failed", "not authenticated")
            handle_auth_error(
                json_output,
                ctx=ctx,
                mode=cmd_name,
                elapsed_ms=max(0, int(elapsed * 1000)),
            )
        except Exception as e:
            elapsed = log_result("failed", str(e))
            if json_output:
                emit_local_json_error(
                    "ERROR",
                    str(e),
                    mode=cmd_name,
                    ctx=ctx,
                    reason=f"Report a local CLI error raised while executing `{cmd_name}`.",
                    diagnostics=Diagnostics(
                        retries=0,
                        auth_refreshed=False,
                        elapsed_ms=max(0, int(elapsed * 1000)),
                    ),
                )
            else:
                handle_error(e)

    return wrapper


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================


def json_output_response(data: dict) -> None:
    """Print JSON response (no colors for machine parsing)."""
    click.echo(json.dumps(data, indent=2, default=str))


def emit_compatibility_warning(canonical_command: str, *, enabled: bool = True) -> None:
    """Print the standard compatibility warning for a legacy command surface."""
    if not enabled:
        return
    console.print(
        "[yellow]Deprecated compatibility command. "
        f"Use `{canonical_command}` instead.[/yellow]"
    )


def _error_result_payload(
    code: str,
    message: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if extra:
        payload.update(dict(extra))
    return payload


def _trace_and_run_id(
    ctx: click.Context | None,
    *,
    mode: str,
    run_id: str | None = None,
) -> tuple[str, str]:
    trace_id = ctx.obj.get("trace_id") if ctx and ctx.obj else None
    if not trace_id:
        trace_id = "trc_unknown"
    if run_id is not None:
        return trace_id, run_id
    trace = ctx.obj.get("trace") if ctx and ctx.obj else None
    derived_run_id = trace.run_id if trace and trace.run_id else f"run_{mode}_{trace_id.removeprefix('trc_')}"
    return trace_id, derived_run_id


def _binding_intent(binding: Any, *, fallback: Intent | None = None) -> Intent | None:
    try:
        return Intent(binding.intent)
    except ValueError:
        if getattr(binding, "intent", None) == "MUTATION":
            return Intent.LOCAL_MUTATION
        return fallback


def json_error_response(
    code: str,
    message: str,
    extra: dict | None = None,
    *,
    ctx: click.Context | None = None,
    binding: Any | None = None,
    intent: Intent | None = None,
    mode: str | None = None,
    profile_id: str = "default",
    notebook_id: str | None = None,
    source_of_truth: str = "local_cache",
    cache_mode: str = "offline",
    reason: str | None = None,
    transport: Transport | None = None,
    freshness: Freshness | None = None,
    cache_updates: CacheUpdates | None = None,
    diagnostics: Diagnostics | None = None,
    run_id: str | None = None,
    exit_code: int = 1,
) -> None:
    """Print JSON error and exit (no colors for machine parsing).

    Args:
        code: Error code (e.g., "AUTH_REQUIRED", "ERROR")
        message: Human-readable error message
        extra: Optional additional data to include in response
    """
    if binding is not None:
        intent = _binding_intent(binding, fallback=intent)
        mode = mode or binding.mode
        transport = transport or Transport(
            kind=binding.transport_kind,
            endpoint=binding.endpoint,
            rpcid=binding.rpcid,
        )

    if intent is not None and mode is not None and transport is not None:
        trace_id, effective_run_id = _trace_and_run_id(ctx, mode=mode, run_id=run_id)
        response = Envelope(
            ok=False,
            trace_id=trace_id,
            run_id=effective_run_id,
            route=Route(
                intent=intent,
                mode=mode,
                notebook_id=notebook_id,
                profile_id=profile_id,
                source_of_truth=source_of_truth,
                cache_mode=cache_mode,
                reason=reason or message,
                transport=transport,
            ),
            result=_error_result_payload(code, message, extra),
            freshness=freshness,
            cache_updates=cache_updates or CacheUpdates(),
            diagnostics=diagnostics or Diagnostics(),
        ).to_dict()
    else:
        response = {"error": True, "code": code, "message": message}
        if extra:
            response.update(extra)
    click.echo(json.dumps(response, indent=2, default=str))
    raise SystemExit(exit_code)


def display_research_sources(sources: list[dict], max_display: int = 10) -> None:
    """Display research sources in a formatted table.

    Args:
        sources: List of source dicts with 'title' and 'url' keys
        max_display: Maximum sources to show before truncating (default 10)
    """
    console.print(f"[bold]Found {len(sources)} sources[/bold]")

    if sources:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Title", style="cyan")
        table.add_column("URL", style="dim")
        for src in sources[:max_display]:
            table.add_row(
                src.get("title", "Untitled")[:50],
                src.get("url", "")[:60],
            )
        if len(sources) > max_display:
            table.add_row(f"... and {len(sources) - max_display} more", "")
        console.print(table)
def get_source_type_display(source_type: str) -> str:
    """Get display string for source type.

    Args:
        source_type: Type string from Source.kind (SourceType str enum)

    Returns:
        Display string with emoji
    """
    # Extract value if it's a SourceType enum, otherwise use as-is
    type_str = source_type.value if hasattr(source_type, "value") else str(source_type)
    type_map = {
        # From SourceType str enum values (types.py)
        "google_docs": "📄 Google Docs",
        "google_slides": "📊 Google Slides",
        "google_spreadsheet": "📊 Google Sheets",
        "pdf": "📄 PDF",
        "pasted_text": "📝 Pasted Text",
        "docx": "📝 DOCX",
        "web_page": "🌐 Web Page",
        "markdown": "📝 Markdown",
        "youtube": "🎬 YouTube",
        "media": "🎵 Media",
        "google_drive_audio": "🎧 Drive Audio",
        "google_drive_video": "🎬 Drive Video",
        "image": "🖼️ Image",
        "csv": "📊 CSV",
        "unknown": "❓ Unknown",
    }
    return type_map.get(type_str, f"❓ {type_str}")
