"""Chat CLI commands.

Commands:
    ask        Ask a notebook a question
"""

import logging

import click

from ..client import NotebookLMClient
from .helpers import (
    console,
    get_current_conversation,
    get_current_notebook,
    json_output_response,
    require_notebook,
    resolve_notebook_id,
    resolve_source_ids,
    set_current_conversation,
    with_client,
)

logger = logging.getLogger(__name__)


def _determine_conversation_id(
    *,
    explicit_conversation_id: str | None,
    explicit_notebook_id: str | None,
    resolved_notebook_id: str,
    json_output: bool,
) -> str | None:
    """Determine which conversation ID to use for the ask command.

    Returns None if no cached conversation exists, otherwise returns
    the conversation ID to continue.
    """
    if explicit_conversation_id:
        return explicit_conversation_id

    # Check if user switched notebooks via --notebook flag
    cached_notebook = get_current_notebook()
    if explicit_notebook_id and cached_notebook and resolved_notebook_id != cached_notebook:
        if not json_output:
            console.print("[dim]Different notebook specified, starting new conversation...[/dim]")
        return None

    return get_current_conversation()


async def _get_latest_conversation_from_server(
    client, notebook_id: str, json_output: bool
) -> str | None:
    """Fetch the most recent conversation ID from the server.

    Returns None if unavailable or empty.
    """
    try:
        conv_id = await client.chat.get_conversation_id(notebook_id)
        if conv_id:
            if not json_output:
                console.print(f"[dim]Continuing conversation {conv_id[:8]}...[/dim]")
            return conv_id
    except Exception as e:
        logger.debug(
            "Failed to fetch last conversation (%s): %s",
            type(e).__name__,
            e,
        )
        if not json_output:
            console.print("[dim]Starting new conversation (history unavailable)[/dim]")
    return None


def register_chat_commands(cli):
    """Register chat commands on the main CLI group."""

    @cli.command("ask")
    @click.argument("question")
    @click.option(
        "-n",
        "--notebook",
        "notebook_id",
        default=None,
        help="Notebook ID (uses current if not set)",
    )
    @click.option("--conversation-id", "-c", default=None, help="Continue a specific conversation")
    @click.option(
        "--source",
        "-s",
        "source_ids",
        multiple=True,
        help="Limit to specific source IDs (can be repeated)",
    )
    @click.option(
        "--json", "json_output", is_flag=True, help="Output as JSON (includes references)"
    )
    @with_client
    def ask_cmd(
        ctx,
        question,
        notebook_id,
        conversation_id,
        source_ids,
        json_output,
        client_auth,
    ):
        """Ask a notebook a question.

        By default, the CLI continues the cached conversation for the current
        notebook when possible. If there is no cached conversation, it asks the
        server for the most recent conversation and resumes that thread when
        available. Use --conversation-id to continue a specific thread.

        The answer includes inline citations like [1], [2] that reference
        sources. Use --json to get structured output with source IDs for each
        reference.

        \b
        Example:
          notebooklm ask "what are the main themes?"
          notebooklm ask -c <id> "continue this one"
          notebooklm ask -s src_001 -s src_002 "question about specific sources"
          notebooklm ask "explain X" --json             # Get answer with source references
        """
        nb_id = require_notebook(notebook_id)

        async def _run():
            async with NotebookLMClient(client_auth) as client:
                nb_id_resolved = await resolve_notebook_id(client, nb_id)
                effective_conv_id = _determine_conversation_id(
                    explicit_conversation_id=conversation_id,
                    explicit_notebook_id=notebook_id,
                    resolved_notebook_id=nb_id_resolved,
                    json_output=json_output,
                )

                resumed_from_server = False
                if not effective_conv_id:
                    # If no conversation ID yet, try to get the most recent one from server
                    effective_conv_id = await _get_latest_conversation_from_server(
                        client, nb_id_resolved, json_output
                    )
                    if effective_conv_id:
                        resumed_from_server = True

                sources = await resolve_source_ids(client, nb_id_resolved, source_ids)
                result = await client.chat.ask(
                    nb_id_resolved,
                    question,
                    source_ids=sources,
                    conversation_id=effective_conv_id,
                )

                if result.conversation_id:
                    set_current_conversation(result.conversation_id)

                if json_output:
                    from dataclasses import asdict

                    data = asdict(result)
                    # Exclude raw_response from CLI output for brevity
                    del data["raw_response"]
                    json_output_response(data)
                    return
                else:
                    console.print("[bold cyan]Answer:[/bold cyan]")
                    console.print(result.answer)
                    if result.is_follow_up and resumed_from_server:
                        console.print(
                            f"\n[dim]Resumed conversation: {result.conversation_id}[/dim]"
                        )
                    elif result.is_follow_up:
                        console.print(
                            f"\n[dim]Conversation: {result.conversation_id} (turn {result.turn_number or '?'})[/dim]"
                        )
                    else:
                        console.print(f"\n[dim]New conversation: {result.conversation_id}[/dim]")

        return _run()
