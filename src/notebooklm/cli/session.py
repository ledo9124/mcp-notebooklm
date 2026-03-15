"""Session and context management CLI commands.

Commands:
    login   Log in to NotebookLM via browser
    use     Set the current notebook context
    status  Show current context
    clear   Clear current notebook context
"""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.table import Table

from ..auth import (
    _get_storage_path_for_persistence,
    _load_storage_state,
    _persist_build_label_to_storage,
    AuthTokens,
    extract_build_label_from_html,
    extract_cookies_from_storage,
)
from ..client import NotebookLMClient
from ..contracts import RiskTier, risk_guard
from ..contracts.envelope_schema import Diagnostics, Envelope, Route, Transport
from ..contracts.intents import Intent
from ..local.cache import resolve_cache_db_path
from ..paths import (
    get_browser_profile_dir,
    get_context_path,
    get_path_info,
    get_storage_path,
)
from ..profiles.manager import AuthSnapshotRecord, ProfileManager, ProfileRecord
from .helpers import (
    clear_context,
    console,
    emit_compatibility_warning,
    get_auth_tokens,
    get_current_notebook,
    json_output_response,
    resolve_notebook_id,
    run_async,
    set_current_notebook,
)


@contextmanager
def _windows_playwright_event_loop() -> Iterator[None]:
    """Temporarily restore default event loop policy for Playwright on Windows.

    Playwright's sync API uses subprocess to spawn the browser, which requires
    ProactorEventLoop on Windows. However, we set WindowsSelectorEventLoopPolicy
    globally to fix CLI hanging issues (#79). This context manager temporarily
    restores the default policy for Playwright, then switches back.

    On non-Windows platforms, this is a no-op.

    Yields:
        None

    Example:
        with _windows_playwright_event_loop():
            with sync_playwright() as p:
                # Browser operations work on Windows
                ...
    """
    if sys.platform != "win32":
        yield
        return

    # Save current policy and restore default (ProactorEventLoop) for Playwright
    original_policy = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    try:
        yield
    finally:
        # Restore WindowsSelectorEventLoopPolicy for other async operations
        asyncio.set_event_loop_policy(original_policy)


def _ensure_chromium_installed() -> None:
    """Check if Chromium is installed and install if needed.

    This pre-flight check runs `playwright install --dry-run chromium` to detect
    if the browser needs installation, then auto-installs if necessary.

    Silently proceeds on any errors - Playwright will handle them during launch.
    """
    try:
        result = subprocess.run(
            ["playwright", "install", "--dry-run", "chromium"],
            capture_output=True,
            text=True,
        )
        # Check if dry-run indicates browser needs installing
        stdout_lower = result.stdout.lower()
        if "chromium" not in stdout_lower or "will download" not in stdout_lower:
            return

        console.print("[yellow]Chromium browser not installed. Installing now...[/yellow]")
        install_result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            text=True,
        )
        if install_result.returncode != 0:
            console.print(
                "[red]Failed to install Chromium browser.[/red]\n"
                "Run manually: playwright install chromium"
            )
            raise SystemExit(1)
        console.print("[green]Chromium installed successfully.[/green]\n")
    except SystemExit:
        raise
    except Exception as e:
        # FileNotFoundError: playwright CLI not found but sync_playwright imported
        # Other exceptions: dry-run check failed - let Playwright handle it during launch
          console.print(
              f"[dim]Warning: Chromium pre-flight check failed: {e}. Proceeding anyway.[/dim]"
          )


def _now_utc() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    """Best-effort ISO-8601 parsing for persisted timestamps."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _snapshot_age_seconds(snapshot: AuthSnapshotRecord | None) -> int | None:
    """Return auth snapshot age in seconds when captured_at is parseable."""
    captured_at = _parse_timestamp(snapshot.captured_at if snapshot else None)
    if captured_at is None:
        return None
    return max(0, int((_now_utc() - captured_at).total_seconds()))


def _resolve_auth_storage(ctx: click.Context) -> tuple[Path | None, Path | None, str]:
    """Resolve the current auth input path, persistence path, and display source."""
    input_path = Path(ctx.obj["storage_path"]) if ctx.obj and ctx.obj.get("storage_path") else None
    if input_path is None and "NOTEBOOKLM_AUTH_JSON" not in os.environ:
        input_path = get_storage_path()

    storage_path = _get_storage_path_for_persistence(input_path)
    if input_path is None:
        return None, storage_path, "NOTEBOOKLM_AUTH_JSON"
    resolved_input = Path(input_path).expanduser().resolve()
    return resolved_input, storage_path, f"file ({resolved_input})"


def _open_profile_manager_read_only() -> ProfileManager | None:
    """Open the cache DB in read-only mode when it already exists."""
    db_path = resolve_cache_db_path()
    if not db_path.exists():
        return None
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    return ProfileManager(connection)


def _matching_profile_for_storage(
    manager: ProfileManager, storage_path: Path | None
) -> ProfileRecord | None:
    """Find the profile bound to the current storage path, if any."""
    if storage_path is None:
        return manager.get_active_profile()
    return next(
        (profile for profile in manager.list_profiles() if profile.storage_state_path == storage_path),
        None,
    )


def _load_profile_snapshot(
    storage_path: Path | None,
) -> tuple[ProfileRecord | None, AuthSnapshotRecord | None]:
    """Return the profile/snapshot pair for the current auth storage, if present."""
    manager = _open_profile_manager_read_only()
    if manager is None:
        return None, None
    try:
        profile = _matching_profile_for_storage(manager, storage_path)
        if profile is None:
            return None, None
        return profile, manager.get_auth_snapshot(profile.profile_id)
    except sqlite3.Error:
        return None, None
    finally:
        manager.close()


def _current_profile_id(storage_path: Path | None = None) -> str:
    """Return the best-effort active profile id for local-only commands."""
    manager = _open_profile_manager_read_only()
    if manager is None:
        return "default"
    try:
        profile = _matching_profile_for_storage(manager, storage_path)
        if profile is not None:
            return profile.profile_id
        active = manager.get_active_profile()
        if active is not None:
            return active.profile_id
        profiles = manager.list_profiles()
        if len(profiles) == 1:
            return profiles[0].profile_id
        return "default"
    except sqlite3.Error:
        return "default"
    finally:
        manager.close()


def _trace_and_run_id(ctx: click.Context, mode: str) -> tuple[str, str]:
    """Return the current trace identifier plus a deterministic run id."""
    trace_id = ctx.obj.get("trace_id") if ctx.obj else None
    if not trace_id:
        trace_id = "trc_unknown"
    trace = ctx.obj.get("trace") if ctx.obj else None
    run_id = trace.run_id if trace and trace.run_id else f"run_{mode}_{trace_id.removeprefix('trc_')}"
    return trace_id, run_id


def _profile_payload(profile: ProfileRecord | None) -> dict[str, Any] | None:
    """Serialize a profile record for JSON output."""
    if profile is None:
        return None
    return {
        "profile_id": profile.profile_id,
        "display_name": profile.display_name,
        "account_email": profile.account_email,
        "is_default": profile.is_default,
        "storage_state_path": str(profile.storage_state_path),
        "browser_profile_path": str(profile.browser_profile_path),
        "last_login_at": profile.last_login_at,
    }


def _snapshot_payload(
    snapshot: AuthSnapshotRecord | None,
    *,
    current_cookie_fingerprint: str,
) -> dict[str, Any]:
    """Serialize auth snapshot details for JSON output."""
    if snapshot is None:
        return {
            "present": False,
            "captured_at": None,
            "validated_at": None,
            "age_seconds": None,
            "status": None,
            "source": None,
            "cookie_fingerprint": None,
            "matches_storage_cookies": None,
        }
    return {
        "present": True,
        "captured_at": snapshot.captured_at,
        "validated_at": snapshot.validated_at,
        "age_seconds": _snapshot_age_seconds(snapshot),
        "status": snapshot.status,
        "source": snapshot.source,
        "cookie_fingerprint": snapshot.cookie_fingerprint,
        "matches_storage_cookies": snapshot.cookie_fingerprint == current_cookie_fingerprint,
    }


def _inspect_auth_state(ctx: click.Context) -> tuple[dict[str, Any], str]:
    """Collect local auth/profile state without making network requests."""
    input_path, storage_path, auth_source = _resolve_auth_storage(ctx)
    storage_state = _load_storage_state(input_path)
    cookies = extract_cookies_from_storage(storage_state)
    profile, snapshot = _load_profile_snapshot(storage_path)
    build_label = str(storage_state.get("bl", "") or "")
    fingerprint = AuthTokens(
        cookies=cookies,
        csrf_token="",
        session_id="",
        build_label=build_label,
        storage_path=storage_path,
    ).cookie_fingerprint
    profile_id = profile.profile_id if profile else "default"

    result = {
        "auth_source": auth_source,
        "storage_path": str(storage_path) if storage_path is not None else None,
        "profile": _profile_payload(profile),
        "cookie_count": len(cookies),
        "cookie_fingerprint": fingerprint,
        "build_label_present": bool(build_label or (snapshot and snapshot.build_label)),
        "csrf_present": bool(snapshot and snapshot.csrf_token),
        "session_id_present": bool(snapshot and snapshot.session_id),
        "snapshot": _snapshot_payload(snapshot, current_cookie_fingerprint=fingerprint),
    }
    return result, profile_id


def _auth_envelope(
    ctx: click.Context,
    *,
    intent: Intent,
    mode: str,
    reason: str,
    profile_id: str,
    result: dict[str, Any],
    transport: Transport,
    source_of_truth: str,
    cache_mode: str,
    ok: bool = True,
    auth_refreshed: bool = False,
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    """Wrap auth command JSON output in the canonical envelope."""
    trace_id, run_id = _trace_and_run_id(ctx, mode)
    return Envelope(
        ok=ok,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=intent,
            mode=mode,
            notebook_id=None,
            profile_id=profile_id,
            source_of_truth=source_of_truth,
            cache_mode=cache_mode,
            reason=reason,
            transport=transport,
        ),
        result=result,
        diagnostics=Diagnostics(
            retries=0,
            auth_refreshed=auth_refreshed,
            elapsed_ms=elapsed_ms,
        ),
    ).to_dict()


def _status_envelope(
    ctx: click.Context,
    *,
    mode: str,
    notebook_id: str | None,
    profile_id: str,
    reason: str,
    result: dict[str, Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    """Wrap session status JSON output in the canonical envelope."""
    trace_id, run_id = _trace_and_run_id(ctx, mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent.LOCAL_METADATA,
            mode=mode,
            notebook_id=notebook_id,
            profile_id=profile_id,
            source_of_truth="local_cache",
            cache_mode="offline",
            reason=reason,
            transport=Transport(kind="local"),
        ),
        result=result,
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _render_auth_inspect(result: dict[str, Any]) -> None:
    """Display human-readable auth inspection details."""
    profile = result["profile"] or {}
    snapshot = result["snapshot"]

    table = Table(title="Auth Inspect")
    table.add_column("Field", style="dim")
    table.add_column("Value", style="cyan")
    table.add_row("Auth source", result["auth_source"])
    table.add_row("Storage path", result["storage_path"] or "-")
    table.add_row("Profile", profile.get("profile_id", "unlinked"))
    table.add_row("Profile name", profile.get("display_name", "-"))
    table.add_row("Account", profile.get("account_email") or "-")
    table.add_row("Snapshot present", "yes" if snapshot["present"] else "no")
    table.add_row("Snapshot status", snapshot["status"] or "-")
    table.add_row("Snapshot source", snapshot["source"] or "-")
    table.add_row("Snapshot age (s)", str(snapshot["age_seconds"]) if snapshot["age_seconds"] is not None else "-")
    table.add_row("Build label present", "yes" if result["build_label_present"] else "no")
    table.add_row("CSRF present", "yes" if result["csrf_present"] else "no")
    table.add_row("Session ID present", "yes" if result["session_id_present"] else "no")
    table.add_row("Cookie count", str(result["cookie_count"]))
    table.add_row("Cookie fingerprint", result["cookie_fingerprint"])
    console.print(table)

    if not snapshot["present"]:
        console.print(
            "\n[yellow]No persisted auth snapshot found. Run 'notebooklm auth refresh' to capture one.[/yellow]"
        )


def _render_auth_refresh(result: dict[str, Any]) -> None:
    """Display human-readable auth refresh results."""
    profile = result["profile"] or {}
    snapshot = result["snapshot"]

    table = Table(title="Auth Refresh")
    table.add_column("Field", style="dim")
    table.add_column("Value", style="cyan")
    table.add_row("Auth source", result["auth_source"])
    table.add_row("Storage path", result["storage_path"] or "-")
    table.add_row("Profile", profile.get("profile_id", "unlinked"))
    table.add_row("Build label", result["build_label"])
    table.add_row("Persisted to storage", "yes" if result["persisted_to_storage"] else "no")
    table.add_row("Persisted snapshot", "yes" if result["persisted_snapshot"] else "no")
    table.add_row("Snapshot status", snapshot["status"] or "-")
    table.add_row("Snapshot source", snapshot["source"] or "-")
    table.add_row("Cookie fingerprint", result["cookie_fingerprint"])
    console.print(table)

    if result["persisted_to_storage"] and result["persisted_snapshot"]:
        console.print("\n[green]Authentication refreshed and persisted.[/green]")
    else:
        console.print(
            "\n[yellow]Authentication refreshed, but the updated snapshot could not be fully persisted.[/yellow]"
        )


def register_session_commands(cli):
    """Register session commands on the main CLI group."""

    @cli.command("login")
    @click.option(
        "--storage",
        type=click.Path(),
        default=None,
        help="Where to save storage_state.json (default: $NOTEBOOKLM_HOME/storage_state.json)",
    )
    def login(storage):
        """Log in to NotebookLM via browser.

        Opens a browser window for Google login. After logging in,
        press ENTER in the terminal to save authentication.

        Note: Cannot be used when NOTEBOOKLM_AUTH_JSON is set (use file-based
        auth or unset the env var first).
        """
        # Check for conflicting env var
        if os.environ.get("NOTEBOOKLM_AUTH_JSON"):
            console.print(
                "[red]Error: Cannot run 'login' when NOTEBOOKLM_AUTH_JSON is set.[/red]\n"
                "The NOTEBOOKLM_AUTH_JSON environment variable provides inline authentication,\n"
                "which conflicts with browser-based login that saves to a file.\n\n"
                "Either:\n"
                "  1. Unset NOTEBOOKLM_AUTH_JSON and run 'login' again\n"
                "  2. Continue using NOTEBOOKLM_AUTH_JSON for authentication"
            )
            raise SystemExit(1)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            console.print(
                "[red]Playwright not installed. Run:[/red]\n"
                "  pip install notebooklm[browser]\n"
                "  playwright install chromium"
            )
            raise SystemExit(1) from None

        # Pre-flight check: verify Chromium browser is installed
        _ensure_chromium_installed()

        storage_path = Path(storage) if storage else get_storage_path()
        browser_profile = get_browser_profile_dir()
        storage_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        browser_profile.mkdir(parents=True, exist_ok=True, mode=0o700)

        console.print("[yellow]Opening browser for Google login...[/yellow]")
        console.print(f"[dim]Using persistent profile: {browser_profile}[/dim]")

        # Use context manager to restore ProactorEventLoop for Playwright on Windows
        # (fixes #89: NotImplementedError on Windows Python 3.12)
        with _windows_playwright_event_loop(), sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(browser_profile),
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--password-store=basic",  # Avoid macOS keychain encryption for headless compatibility
                ],
                ignore_default_args=["--enable-automation"],
            )

            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://notebooklm.google.com/")

            console.print("\n[bold green]Instructions:[/bold green]")
            console.print("1. Complete the Google login in the browser window")
            console.print("2. Wait until you see the NotebookLM homepage")
            console.print("3. Press [bold]ENTER[/bold] here to save and close\n")

            input("[Press ENTER when logged in] ")

            current_url = page.url
            if "notebooklm.google.com" not in current_url:
                console.print(f"[yellow]Warning: Current URL is {current_url}[/yellow]")
                if not click.confirm("Save authentication anyway?"):
                    context.close()
                    raise SystemExit(1)

            build_label = None
            try:
                build_label = extract_build_label_from_html(page.content(), current_url)
            except ValueError as exc:
                console.print(f"[yellow]Warning: Could not persist build label: {exc}[/yellow]")

            context.storage_state(path=str(storage_path))
            _persist_build_label_to_storage(storage_path, build_label or "")
            # Restrict permissions to owner only (contains sensitive cookies)
            storage_path.chmod(0o600)
            context.close()

        console.print(f"\n[green]Authentication saved to:[/green] {storage_path}")

    @cli.command("use")
    @click.argument("notebook_id")
    @click.pass_context
    def use_notebook(ctx, notebook_id):
        """Set the current notebook context.

        Once set, all commands will use this notebook by default.
        You can still override by passing --notebook explicitly.

        Supports partial IDs - 'notebooklm use abc' matches 'abc123...'

        \b
          Example:
            notebooklm use nb123
            notebooklm ask "what is this about?"   # Uses nb123
            notebooklm generate video "a fun explainer"  # Uses nb123
        """
        emit_compatibility_warning("notebooklm notebook use <id-or-title>")
        try:
            auth = get_auth_tokens(ctx)

            async def _get():
                async with NotebookLMClient(auth) as client:
                    # Resolve partial ID to full ID
                    resolved_id = await resolve_notebook_id(client, notebook_id)
                    nb = await client.notebooks.get(resolved_id)
                    return nb, resolved_id

            nb, resolved_id = run_async(_get())

            created_str = nb.created_at.strftime("%Y-%m-%d") if nb.created_at else None
            set_current_notebook(resolved_id, nb.title, nb.is_owner, created_str)

            table = Table()
            table.add_column("ID", style="cyan")
            table.add_column("Title", style="green")
            table.add_column("Owner")
            table.add_column("Created", style="dim")

            created = created_str or "-"
            owner_status = "Owner" if nb.is_owner else "Shared"
            table.add_row(nb.id, nb.title, owner_status, created)

            console.print(table)

        except FileNotFoundError:
            set_current_notebook(notebook_id)
            table = Table()
            table.add_column("ID", style="cyan")
            table.add_column("Title", style="green")
            table.add_column("Owner")
            table.add_column("Created", style="dim")
            table.add_row(notebook_id, "-", "-", "-")
            console.print(table)
        except click.ClickException:
            # Re-raise click exceptions (from resolve_notebook_id)
            raise
        except Exception as e:
            set_current_notebook(notebook_id)
            table = Table()
            table.add_column("ID", style="cyan")
            table.add_column("Title", style="green")
            table.add_column("Owner")
            table.add_column("Created", style="dim")
            table.add_row(notebook_id, f"Warning: {str(e)}", "-", "-")
            console.print(table)

    @cli.command("status")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @click.option("--paths", "show_paths", is_flag=True, help="Show resolved file paths")
    @click.pass_context
    def status(ctx: click.Context, json_output, show_paths):
        """Show current context (active notebook and conversation).

        Use --paths to see where configuration files are located
        (useful for debugging NOTEBOOKLM_HOME).
        """
        started_at = time.perf_counter()
        context_file = get_context_path()
        notebook_id = get_current_notebook()
        profile_id = _current_profile_id()

        # Handle --paths flag
        if show_paths:
            path_info = get_path_info()
            if json_output:
                json_output_response(
                    _status_envelope(
                        ctx,
                        mode="status_paths",
                        notebook_id=None,
                        profile_id=profile_id,
                        reason="Resolve the local NotebookLM home, storage, and context paths.",
                        result={"paths": path_info},
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    )
                )
                return

            table = Table(title="Configuration Paths")
            table.add_column("File", style="dim")
            table.add_column("Path", style="cyan")
            table.add_column("Source", style="green")

            table.add_row("Home Directory", path_info["home_dir"], path_info["home_source"])
            table.add_row("Storage State", path_info["storage_path"], "")
            table.add_row("Context", path_info["context_path"], "")
            table.add_row("Browser Profile", path_info["browser_profile_dir"], "")

            # Show if NOTEBOOKLM_AUTH_JSON is set
            if os.environ.get("NOTEBOOKLM_AUTH_JSON"):
                console.print(
                    "[yellow]Note: NOTEBOOKLM_AUTH_JSON is set (inline auth active)[/yellow]\n"
                )

            console.print(table)
            return

        if notebook_id:
            try:
                data = json.loads(context_file.read_text(encoding="utf-8"))
                title = data.get("title", "-")
                is_owner = data.get("is_owner", True)
                created_at = data.get("created_at", "-")
                conversation_id = data.get("conversation_id")

                if json_output:
                    json_output_response(
                        _status_envelope(
                            ctx,
                            mode="status",
                            notebook_id=notebook_id,
                            profile_id=profile_id,
                            reason="Inspect the locally selected notebook context and conversation state.",
                            result={
                                "has_context": True,
                                "notebook": {
                                    "id": notebook_id,
                                    "title": title if title != "-" else None,
                                    "is_owner": is_owner,
                                },
                                "conversation_id": conversation_id,
                            },
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                        )
                    )
                    return

                table = Table(title="Current Context")
                table.add_column("Property", style="dim")
                table.add_column("Value", style="cyan")

                table.add_row("Notebook ID", notebook_id)
                table.add_row("Title", str(title))
                owner_status = "Owner" if is_owner else "Shared"
                table.add_row("Ownership", owner_status)
                table.add_row("Created", created_at)
                if conversation_id:
                    table.add_row("Conversation", conversation_id)
                else:
                    table.add_row("Conversation", "[dim]None (will auto-select on next ask)[/dim]")
                console.print(table)
            except (OSError, json.JSONDecodeError):
                if json_output:
                    json_output_response(
                        _status_envelope(
                            ctx,
                            mode="status",
                            notebook_id=notebook_id,
                            profile_id=profile_id,
                            reason="Inspect the locally selected notebook context and conversation state.",
                            result={
                                "has_context": True,
                                "notebook": {
                                    "id": notebook_id,
                                    "title": None,
                                    "is_owner": None,
                                },
                                "conversation_id": None,
                            },
                            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                        )
                    )
                    return

                table = Table(title="Current Context")
                table.add_column("Property", style="dim")
                table.add_column("Value", style="cyan")
                table.add_row("Notebook ID", notebook_id)
                table.add_row("Title", "-")
                table.add_row("Ownership", "-")
                table.add_row("Created", "-")
                table.add_row("Conversation", "[dim]None[/dim]")
                console.print(table)
        else:
            if json_output:
                json_output_response(
                    _status_envelope(
                        ctx,
                        mode="status",
                        notebook_id=None,
                        profile_id=profile_id,
                        reason="Inspect the locally selected notebook context and conversation state.",
                        result={
                            "has_context": False,
                            "notebook": None,
                            "conversation_id": None,
                        },
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    )
                )
                return

            console.print(
                "[yellow]No notebook selected. Use 'notebooklm use <id>' to set one.[/yellow]"
            )

    @cli.command("clear")
    def clear_cmd():
        """Clear current notebook context."""
        clear_context()
        console.print("[green]Context cleared[/green]")

    @cli.group("auth")
    def auth_group():
        """Authentication management commands."""
        pass

    @auth_group.command("check")
    @click.option(
        "--test", "test_fetch", is_flag=True, help="Test token fetch (makes network request)"
    )
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @click.pass_context
    def auth_check(ctx: click.Context, test_fetch, json_output):
        """Check authentication status and diagnose issues.

        Validates that authentication is properly configured by checking:
        - Storage file exists and is readable
        - JSON structure is valid
        - Required cookies (SID) are present
        - Cookie domains are correct

        Use --test to also verify tokens can be fetched from NotebookLM
        (requires network access).

        \b
        Examples:
          notebooklm auth check           # Quick local validation
          notebooklm auth check --test    # Full validation with network test
          notebooklm auth check --json    # Machine-readable output
        """
        from ..auth import (
            extract_cookies_from_storage,
            fetch_tokens,
        )

        started_at = time.perf_counter()
        input_path, storage_path, auth_source = _resolve_auth_storage(ctx)
        active_storage_path = input_path if input_path is not None else storage_path
        has_env_var = "NOTEBOOKLM_AUTH_JSON" in os.environ
        has_home_env = bool(os.environ.get("NOTEBOOKLM_HOME"))
        has_storage_override = bool(ctx.obj and ctx.obj.get("storage_path"))
        profile_id = _current_profile_id(None if has_env_var else storage_path)

        checks: dict[str, bool | None] = {
            "storage_exists": False,
            "json_valid": False,
            "cookies_present": False,
            "sid_cookie": False,
            "token_fetch": None,  # None = not tested, True/False = result
        }

        # Determine auth source for display
        if not has_env_var and not has_storage_override and has_home_env and storage_path is not None:
            auth_source = f"$NOTEBOOKLM_HOME ({storage_path})"

        details: dict[str, Any] = {
            "storage_path": str(active_storage_path) if active_storage_path is not None else None,
            "auth_source": auth_source,
            "cookies_found": [],
            "cookie_domains": [],
            "error": None,
        }

        # Check 1: Storage exists
        if has_env_var:
            checks["storage_exists"] = True
        else:
            checks["storage_exists"] = active_storage_path is not None and active_storage_path.exists()

        if not checks["storage_exists"]:
            details["error"] = f"Storage file not found: {active_storage_path}"
            _output_auth_check(
                ctx,
                checks,
                details,
                json_output,
                test_fetch=test_fetch,
                profile_id=profile_id,
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
            return

        # Check 2: JSON valid
        try:
            if has_env_var:
                storage_state = json.loads(os.environ["NOTEBOOKLM_AUTH_JSON"])
            else:
                storage_state = json.loads(active_storage_path.read_text(encoding="utf-8"))
            checks["json_valid"] = True
        except json.JSONDecodeError as e:
            details["error"] = f"Invalid JSON: {e}"
            _output_auth_check(
                ctx,
                checks,
                details,
                json_output,
                test_fetch=test_fetch,
                profile_id=profile_id,
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
            return

        # Check 3: Cookies present
        try:
            cookies = extract_cookies_from_storage(storage_state)
            checks["cookies_present"] = True
            checks["sid_cookie"] = "SID" in cookies
            details["cookies_found"] = list(cookies.keys())

            # Build detailed cookie-by-domain mapping for debugging
            cookies_by_domain: dict[str, list[str]] = {}
            for cookie in storage_state.get("cookies", []):
                domain = cookie.get("domain", "")
                name = cookie.get("name", "")
                if domain and name and "google" in domain.lower():
                    cookies_by_domain.setdefault(domain, []).append(name)

            details["cookies_by_domain"] = cookies_by_domain
            details["cookie_domains"] = sorted(cookies_by_domain.keys())
        except ValueError as e:
            details["error"] = str(e)
            _output_auth_check(
                ctx,
                checks,
                details,
                json_output,
                test_fetch=test_fetch,
                profile_id=profile_id,
                elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
            return

        # Check 4: Token fetch (optional)
        if test_fetch:
            try:
                csrf, session_id, build_label = run_async(fetch_tokens(cookies))
                checks["token_fetch"] = True
                details["csrf_length"] = len(csrf)
                details["session_id_length"] = len(session_id)
                details["build_label_length"] = len(build_label)
            except Exception as e:
                checks["token_fetch"] = False
                details["error"] = f"Token fetch failed: {e}"

        _output_auth_check(
            ctx,
            checks,
            details,
            json_output,
            test_fetch=test_fetch,
            profile_id=profile_id,
            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        )

    def _output_auth_check(
        ctx: click.Context,
        checks: dict,
        details: dict,
        json_output: bool,
        *,
        test_fetch: bool,
        profile_id: str,
        elapsed_ms: int,
    ):
        """Output auth check results."""
        all_passed = all(v is True for v in checks.values() if v is not None)

        if json_output:
            json_output_response(
                _auth_envelope(
                    ctx,
                    intent=Intent.DOCTOR,
                    mode="check",
                    reason="Validate local auth storage integrity and optionally test live token fetch.",
                    profile_id=profile_id,
                    result={
                        "status": "ok" if all_passed else "error",
                        "checks": checks,
                        "details": details,
                    },
                    transport=Transport(kind="httpx", endpoint="https://notebooklm.google.com/")
                    if test_fetch
                    else Transport(kind="local"),
                    source_of_truth="mixed" if test_fetch else "local_cache",
                    cache_mode="network" if test_fetch else "offline",
                    ok=all_passed,
                    elapsed_ms=elapsed_ms,
                )
            )
            return

        # Rich output
        table = Table(title="Authentication Check")
        table.add_column("Check", style="dim")
        table.add_column("Status")
        table.add_column("Details", style="cyan")

        def status_icon(val):
            if val is None:
                return "[dim]⊘ skipped[/dim]"
            return "[green]✓ pass[/green]" if val else "[red]✗ fail[/red]"

        table.add_row(
            "Storage exists",
            status_icon(checks["storage_exists"]),
            details["auth_source"],
        )
        table.add_row(
            "JSON valid",
            status_icon(checks["json_valid"]),
            "",
        )
        table.add_row(
            "Cookies present",
            status_icon(checks["cookies_present"]),
            f"{len(details.get('cookies_found', []))} cookies" if checks["cookies_present"] else "",
        )
        table.add_row(
            "SID cookie",
            status_icon(checks["sid_cookie"]),
            ", ".join(details.get("cookie_domains", [])[:3]) or "",
        )
        table.add_row(
            "Token fetch",
            status_icon(checks["token_fetch"]),
            "use --test to check" if checks["token_fetch"] is None else "",
        )

        console.print(table)

        # Show detailed cookie breakdown by domain
        cookies_by_domain = details.get("cookies_by_domain", {})
        if cookies_by_domain:
            console.print()  # Blank line
            cookie_table = Table(title="Cookies by Domain")
            cookie_table.add_column("Domain", style="cyan")
            cookie_table.add_column("Cookies")

            # Key auth cookies to highlight
            key_cookies = {"SID", "HSID", "SSID", "APISID", "SAPISID", "SIDCC"}

            def format_cookie_name(name: str) -> str:
                if name in key_cookies:
                    return f"[green]{name}[/green]"
                if name.startswith("__Secure-"):
                    return f"[blue]{name}[/blue]"
                return f"[dim]{name}[/dim]"

            for domain in sorted(cookies_by_domain.keys()):
                cookie_names = cookies_by_domain[domain]
                formatted = [format_cookie_name(name) for name in sorted(cookie_names)]
                cookie_table.add_row(domain, ", ".join(formatted))

            console.print(cookie_table)

        if details.get("error"):
            console.print(f"\n[red]Error:[/red] {details['error']}")

        if all_passed:
            console.print("\n[green]Authentication is valid.[/green]")
        elif not checks["storage_exists"]:
            console.print("\n[yellow]Run 'notebooklm login' to authenticate.[/yellow]")
        elif checks["token_fetch"] is False:
            console.print(
                "\n[yellow]Cookies may be expired. Run 'notebooklm login' to refresh.[/yellow]"
            )

    @auth_group.command("inspect")
    @click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
    @risk_guard(RiskTier.T0_READ, approval_gated=False, destructive=False)
    @click.pass_context
    def auth_inspect(ctx: click.Context, json_output: bool) -> None:
        """Inspect the current auth snapshot and storage-backed profile state."""
        started_at = time.perf_counter()
        try:
            result, profile_id = _inspect_auth_state(ctx)
        except (FileNotFoundError, ValueError) as exc:
            if json_output:
                json_output_response(
                    _auth_envelope(
                        ctx,
                        intent=Intent.DOCTOR,
                        mode="inspect",
                        reason="inspect auth snapshot and profile state",
                        profile_id="default",
                        result={"error": str(exc)},
                        transport=Transport(kind="local"),
                        source_of_truth="local_cache",
                        cache_mode="offline",
                        ok=False,
                        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                    )
                )
                raise SystemExit(1) from exc
            raise click.ClickException(str(exc)) from exc

        if json_output:
            json_output_response(
                _auth_envelope(
                    ctx,
                    intent=Intent.DOCTOR,
                    mode="inspect",
                    reason="inspect auth snapshot and profile state",
                    profile_id=profile_id,
                    result=result,
                    transport=Transport(kind="local"),
                    source_of_truth="local_cache",
                    cache_mode="offline",
                    elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                )
            )
            return

        _render_auth_inspect(result)

    @auth_group.command("refresh")
    @click.option("--json", "json_output", is_flag=True, help="Output as canonical JSON envelope")
    @risk_guard(RiskTier.T1_LOCAL_MUTATION, approval_gated=False, destructive=False)
    @click.pass_context
    def auth_refresh(ctx: click.Context, json_output: bool) -> None:
        """Refresh auth tokens from the homepage and persist the new snapshot."""
        started_at = time.perf_counter()
        input_path, storage_path, auth_source = _resolve_auth_storage(ctx)

        try:
            if storage_path is None:
                raise click.ClickException(
                    "'auth refresh' requires file-backed auth so refreshed state can be persisted. "
                    "Use '--storage PATH' or unset NOTEBOOKLM_AUTH_JSON."
                )

            storage_state = _load_storage_state(input_path)
            cookies = extract_cookies_from_storage(storage_state)
            _, previous_snapshot = _load_profile_snapshot(storage_path)
            auth = AuthTokens(
                cookies=cookies,
                csrf_token=previous_snapshot.csrf_token if previous_snapshot else "",
                session_id=previous_snapshot.session_id if previous_snapshot else "",
                build_label=str(storage_state.get("bl", "") or (previous_snapshot.build_label if previous_snapshot else "")),
                storage_path=storage_path,
            )

            async def _refresh() -> AuthTokens:
                async with NotebookLMClient(auth) as client:
                    return await client.refresh_auth()

            refreshed_auth = run_async(_refresh())
            refreshed_state, profile_id = _inspect_auth_state(ctx)
            refreshed_state["auth_source"] = auth_source
            refreshed_state["build_label"] = refreshed_auth.build_label
            refreshed_storage_state = _load_storage_state(input_path)
            refreshed_state["persisted_to_storage"] = (
                str(refreshed_storage_state.get("bl", "") or "") == refreshed_auth.build_label
            )
            snapshot = refreshed_state["snapshot"]
            refreshed_state["persisted_snapshot"] = bool(
                snapshot["present"]
                and snapshot["cookie_fingerprint"] == refreshed_auth.cookie_fingerprint
                and refreshed_state["csrf_present"]
                and refreshed_state["session_id_present"]
                and refreshed_state["build_label_present"]
            )
        except (FileNotFoundError, ValueError, click.ClickException) as exc:
            if json_output:
                json_output_response(
                    _auth_envelope(
                        ctx,
                        intent=Intent.LOCAL_METADATA,
                        mode="refresh",
                        reason="refresh auth tokens from the homepage and persist them",
                        profile_id="default",
                        result={"error": str(exc)},
                        transport=Transport(kind="httpx", endpoint="https://notebooklm.google.com/"),
                        source_of_truth="mixed",
                        cache_mode="refresh",
                        ok=False,
                        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                    )
                )
                raise SystemExit(1) from exc
            raise click.ClickException(str(exc)) from exc

        if json_output:
            json_output_response(
                _auth_envelope(
                    ctx,
                    intent=Intent.LOCAL_METADATA,
                    mode="refresh",
                    reason="refresh auth tokens from the homepage and persist them",
                    profile_id=profile_id,
                    result=refreshed_state,
                    transport=Transport(kind="httpx", endpoint="https://notebooklm.google.com/"),
                    source_of_truth="mixed",
                    cache_mode="refresh",
                    auth_refreshed=True,
                    elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                )
            )
            return

        _render_auth_refresh(refreshed_state)
