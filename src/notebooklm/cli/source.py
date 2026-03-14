"""Source management CLI commands.

Commands:
    list         List sources in a notebook
    add          Add a source (url, text, file, youtube)
    add-research Search web/drive and add sources from results
    wait         Wait for a source to finish processing
"""

import asyncio
from pathlib import Path

import click
from rich.table import Table

from .._url_utils import is_youtube_url
from ..client import NotebookLMClient
from ..types import source_status_to_str
from .helpers import (
    console,
    display_research_sources,
    get_source_type_display,
    json_output_response,
    require_notebook,
    resolve_notebook_id,
    resolve_source_id,
    with_client,
)


@click.group()
def source():
    """Source management commands.

    \b
    Commands:
      list         List sources in a notebook
      add          Add a source (url, text, file, youtube)
      add-research Search web/drive and add sources from results
      wait         Wait for a source to finish processing

    \b
    Partial ID Support:
      `source wait` accepts partial SOURCE_ID values. Instead of typing the full
      UUID, you can use a prefix (e.g., 'abc' matches 'abc123def456...').
    """
    pass


@source.command("list")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def source_list(ctx, notebook_id, json_output, client_auth):
    """List all sources in a notebook."""
    nb_id = require_notebook(notebook_id)

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            sources = await client.sources.list(nb_id_resolved)
            nb = None
            if json_output:
                nb = await client.notebooks.get(nb_id_resolved)

            if json_output:
                data = {
                    "notebook_id": nb_id_resolved,
                    "notebook_title": nb.title if nb else None,
                    "sources": [
                        {
                            "index": i,
                            "id": src.id,
                            "title": src.title,
                            "type": str(src.kind),
                            "url": src.url,
                            "status": source_status_to_str(src.status),
                            "status_id": src.status,
                            "created_at": src.created_at.isoformat() if src.created_at else None,
                        }
                        for i, src in enumerate(sources, 1)
                    ],
                    "count": len(sources),
                }
                json_output_response(data)
                return

            table = Table(title=f"Sources in {nb_id_resolved}")
            table.add_column("ID", style="cyan")
            table.add_column("Title", style="green")
            table.add_column("Type")
            table.add_column("Created", style="dim")
            table.add_column("Status", style="yellow")

            for src in sources:
                type_display = get_source_type_display(src.kind)
                created = src.created_at.strftime("%Y-%m-%d %H:%M") if src.created_at else "-"
                status = source_status_to_str(src.status)
                table.add_row(src.id, src.title or "-", type_display, created, status)

            console.print(table)

    return _run()


@source.command("add")
@click.argument("content")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--type",
    "source_type",
    type=click.Choice(["url", "text", "file", "youtube"]),
    default=None,
    help="Source type (auto-detected if not specified)",
)
@click.option("--title", help="Title for text sources")
@click.option("--mime-type", help="MIME type for file sources")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def source_add(ctx, content, notebook_id, source_type, title, mime_type, json_output, client_auth):
    """Add a source to a notebook.

    \b
    Source type is auto-detected:
      - URLs (http/https) -> url or youtube
      - Existing files (.txt, .md) -> text
      - Other content -> text (inline)
      - Use --type to override

    \b
    Examples:
      source add https://example.com              # URL
      source add ./doc.md                         # Local file upload
      source add https://youtube.com/...          # YouTube video
      source add "My notes here"                  # Inline text
      source add "My notes" --title "Research"   # Text with custom title
    """
    nb_id = require_notebook(notebook_id)

    # Auto-detect source type if not specified
    detected_type = source_type
    file_content = None
    file_title = title

    if detected_type is None:
        if content.startswith(("http://", "https://")):
            detected_type = "youtube" if is_youtube_url(content) else "url"
        elif Path(content).exists():
            file_path = Path(content).resolve()  # Resolve symlinks
            # Security: Ensure it's a regular file (not a symlink to sensitive file)
            if not file_path.is_file():
                raise click.ClickException(f"Not a regular file: {content}")
            # All files use add_file() for proper type detection
            detected_type = "file"
        else:
            detected_type = "text"
            file_title = title or "Pasted Text"

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            if detected_type == "url" or detected_type == "youtube":
                src = await client.sources.add_url(nb_id_resolved, content)
            elif detected_type == "text":
                text_content = file_content if file_content is not None else content
                text_title = file_title or "Untitled"
                src = await client.sources.add_text(nb_id_resolved, text_title, text_content)
            elif detected_type == "file":
                src = await client.sources.add_file(nb_id_resolved, content, mime_type)

            if json_output:
                data = {
                    "source": {
                        "id": src.id,
                        "title": src.title,
                        "type": str(src.kind),
                        "url": src.url,
                    }
                }
                json_output_response(data)
                return

            console.print(f"[green]Added source:[/green] {src.id}")

    if not json_output:
        with console.status(f"Adding {detected_type} source..."):
            return _run()
    return _run()


@source.command("add-research")
@click.argument("query")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--from",
    "search_source",
    type=click.Choice(["web", "drive"]),
    default="web",
    help="Search source (default: web)",
)
@click.option(
    "--mode",
    type=click.Choice(["fast", "deep"]),
    default="fast",
    help="Search mode (default: fast)",
)
@click.option("--import-all", is_flag=True, help="Import all found sources")
@click.option(
    "--no-wait",
    is_flag=True,
    help="Start research and return immediately (use 'research status/wait' to monitor)",
)
@with_client
def source_add_research(
    ctx, query, notebook_id, search_source, mode, import_all, no_wait, client_auth
):
    """Search web or drive and add sources from results.

    \b
    Examples:
      source add-research "machine learning"              # Search web
      source add-research "project docs" --from drive     # Search Google Drive
      source add-research "AI papers" --mode deep         # Deep search
      source add-research "tutorials" --import-all        # Auto-import all results
      source add-research "topic" --mode deep --no-wait   # Non-blocking deep search
    """
    nb_id = require_notebook(notebook_id)

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            console.print(f"[yellow]Starting {mode} research on {search_source}...[/yellow]")
            result = await client.research.start(nb_id_resolved, query, search_source, mode)
            if not result:
                console.print("[red]Research failed to start[/red]")
                raise SystemExit(1)

            task_id = result["task_id"]
            console.print(f"[dim]Task ID: {task_id}[/dim]")

            # Non-blocking mode: return immediately
            if no_wait:
                console.print(
                    "[green]Research started.[/green] "
                    "Use 'research status' or 'research wait' to monitor."
                )
                return

            status = None
            for _ in range(60):
                status = await client.research.poll(nb_id_resolved)
                if status.get("status") == "completed":
                    break
                elif status.get("status") == "no_research":
                    console.print("[red]Research failed to start[/red]")
                    raise SystemExit(1)
                await asyncio.sleep(5)
            else:
                status = {"status": "timeout"}

            if status.get("status") == "completed":
                sources = status.get("sources", [])
                console.print()
                display_research_sources(sources)

                if import_all and sources and task_id:
                    imported = await client.research.import_sources(
                        nb_id_resolved, task_id, sources
                    )
                    console.print(f"[green]Imported {len(imported)} sources[/green]")
            else:
                console.print(f"[yellow]Status: {status.get('status', 'unknown')}[/yellow]")

    return _run()


@source.command("wait")
@click.argument("source_id")
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--timeout",
    default=120,
    type=int,
    help="Maximum seconds to wait (default: 120)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@with_client
def source_wait(ctx, source_id, notebook_id, timeout, json_output, client_auth):
    """Wait for a source to finish processing.

    After adding a source, it needs to be processed before it can be used
    for chat or artifact generation. This command polls until the source
    is ready or fails.

    SOURCE_ID can be a full UUID or a partial prefix (e.g., 'abc' matches 'abc123...').

    \b
    Exit codes:
      0 - Source is ready
      1 - Source not found or processing failed
      2 - Timeout reached

    \b
    Examples:
      source wait abc123                    # Wait for source to be ready
      source wait abc123 --timeout 300      # Wait up to 5 minutes
      source wait abc123 --json             # Output status as JSON

    \b
    Subagent pattern for long-running operations:
      # In main conversation, add source then spawn subagent to wait:
      notebooklm source add https://example.com
      # Subagent runs: notebooklm source wait <source_id>
    """
    from ..types import SourceNotFoundError, SourceProcessingError, SourceTimeoutError

    nb_id = require_notebook(notebook_id)

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            resolved_id = await resolve_source_id(client, nb_id_resolved, source_id)

            if not json_output:
                console.print(f"[dim]Waiting for source {resolved_id}...[/dim]")

            try:
                source = await client.sources.wait_until_ready(
                    nb_id_resolved,
                    resolved_id,
                    timeout=float(timeout),
                )

                if json_output:
                    data = {
                        "source_id": source.id,
                        "title": source.title,
                        "status": "ready",
                        "status_code": source.status,
                    }
                    json_output_response(data)
                else:
                    console.print(f"[green]✓ Source ready:[/green] {source.id}")
                    if source.title:
                        console.print(f"[bold]Title:[/bold] {source.title}")

            except SourceNotFoundError as e:
                if json_output:
                    data = {
                        "source_id": e.source_id,
                        "status": "not_found",
                        "error": str(e),
                    }
                    json_output_response(data)
                else:
                    console.print(f"[red]✗ Source not found:[/red] {e.source_id}")
                raise SystemExit(1) from None

            except SourceProcessingError as e:
                if json_output:
                    data = {
                        "source_id": e.source_id,
                        "status": "error",
                        "status_code": e.status,
                        "error": str(e),
                    }
                    json_output_response(data)
                else:
                    console.print(f"[red]✗ Source processing failed:[/red] {e.source_id}")
                raise SystemExit(1) from None

            except SourceTimeoutError as e:
                if json_output:
                    data = {
                        "source_id": e.source_id,
                        "status": "timeout",
                        "last_status_code": e.last_status,
                        "timeout_seconds": int(e.timeout),
                        "error": str(e),
                    }
                    json_output_response(data)
                else:
                    console.print(f"[yellow]⚠ Timeout waiting for source:[/yellow] {e.source_id}")
                    console.print(f"[dim]Last status: {e.last_status}[/dim]")
                raise SystemExit(2) from None

    return _run()
