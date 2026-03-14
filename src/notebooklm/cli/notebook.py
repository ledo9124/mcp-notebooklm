"""Notebook management CLI commands.

Commands:
    list       List all notebooks
    create     Create a new notebook
    summary    Get notebook summary with AI-generated insights
"""

import click
from rich.table import Table

from ..client import NotebookLMClient
from .helpers import (
    console,
    json_output_response,
    require_notebook,
    resolve_notebook_id,
    with_client,
)


def register_notebook_commands(cli):
    """Register notebook commands on the main CLI group."""

    @cli.command("list")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @with_client
    def list_cmd(ctx, json_output, client_auth):
        """List all notebooks."""

        async def _run():
            async with NotebookLMClient(client_auth) as client:
                notebooks = await client.notebooks.list()

                if json_output:
                    data = {
                        "notebooks": [
                            {
                                "index": i,
                                "id": nb.id,
                                "title": nb.title,
                                "is_owner": nb.is_owner,
                                "created_at": nb.created_at.isoformat() if nb.created_at else None,
                            }
                            for i, nb in enumerate(notebooks, 1)
                        ],
                        "count": len(notebooks),
                    }
                    json_output_response(data)
                    return

                table = Table(title="Notebooks")
                table.add_column("ID", style="cyan")
                table.add_column("Title", style="green")
                table.add_column("Owner")
                table.add_column("Created", style="dim")

                for nb in notebooks:
                    created = nb.created_at.strftime("%Y-%m-%d") if nb.created_at else "-"
                    owner_status = "Owner" if nb.is_owner else "Shared"
                    table.add_row(nb.id, nb.title, owner_status, created)

                console.print(table)

        return _run()

    @cli.command("create")
    @click.argument("title")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @with_client
    def create_cmd(ctx, title, json_output, client_auth):
        """Create a new notebook."""

        async def _run():
            async with NotebookLMClient(client_auth) as client:
                nb = await client.notebooks.create(title)

                if json_output:
                    data = {
                        "notebook": {
                            "id": nb.id,
                            "title": nb.title,
                            "created_at": nb.created_at.isoformat() if nb.created_at else None,
                        }
                    }
                    json_output_response(data)
                    return

                console.print(f"[green]Created notebook:[/green] {nb.id} - {nb.title}")

        return _run()

    @cli.command("summary")
    @click.option(
        "-n",
        "--notebook",
        "notebook_id",
        default=None,
        help="Notebook ID (uses current if not set). Supports partial IDs.",
    )
    @click.option("--topics", is_flag=True, help="Include suggested topics")
    @with_client
    def summary_cmd(ctx, notebook_id, topics, client_auth):
        """Get notebook summary with AI-generated insights.

        NOTEBOOK_ID supports partial matching (e.g., 'abc' matches 'abc123...').

        \b
        Examples:
          notebooklm summary              # Summary only
          notebooklm summary --topics     # With suggested topics
        """
        notebook_id = require_notebook(notebook_id)

        async def _run():
            async with NotebookLMClient(client_auth) as client:
                resolved_id = await resolve_notebook_id(client, notebook_id)
                description = await client.notebooks.get_description(resolved_id)
                if description and description.summary:
                    console.print("[bold cyan]Summary:[/bold cyan]")
                    console.print(description.summary)

                    if topics and description.suggested_topics:
                        console.print("\n[bold cyan]Suggested Topics:[/bold cyan]")
                        for i, topic in enumerate(description.suggested_topics, 1):
                            console.print(f"  {i}. {topic.question}")
                else:
                    console.print("[yellow]No summary available[/yellow]")

        return _run()
