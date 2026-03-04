"""Chat and conversation CLI commands.

Commands:
    ask        Ask a notebook a question
    configure  Configure chat persona and response settings
    history    Get conversation history or clear local cache
"""

import logging

import click
from rich.table import Table

from ..client import NotebookLMClient
from ..exceptions import ChatSettingsUpdateError
from ..rpc import ChatGoal, ChatResponseLength
from ..types import UNSET, ChatMode, ChatSettings
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

_MODE_TO_BASELINE: dict[str, tuple[ChatGoal, ChatResponseLength]] = {
    "default": (ChatGoal.DEFAULT, ChatResponseLength.DEFAULT),
    "learning-guide": (ChatGoal.LEARNING_GUIDE, ChatResponseLength.DEFAULT),
    "concise": (ChatGoal.DEFAULT, ChatResponseLength.SHORTER),
    "detailed": (ChatGoal.DEFAULT, ChatResponseLength.LONGER),
}

_STYLE_TO_GOAL: dict[str, ChatGoal] = {
    "default": ChatGoal.DEFAULT,
    "learning-guide": ChatGoal.LEARNING_GUIDE,
    "custom": ChatGoal.CUSTOM,
}

_GOAL_TO_STYLE: dict[ChatGoal, str] = {
    ChatGoal.DEFAULT: "default",
    ChatGoal.LEARNING_GUIDE: "learning-guide",
    ChatGoal.CUSTOM: "custom",
}

_LENGTH_TO_ENUM: dict[str, ChatResponseLength] = {
    "default": ChatResponseLength.DEFAULT,
    "longer": ChatResponseLength.LONGER,
    "shorter": ChatResponseLength.SHORTER,
}

_ENUM_TO_LENGTH: dict[ChatResponseLength, str] = {
    ChatResponseLength.DEFAULT: "default",
    ChatResponseLength.LONGER: "longer",
    ChatResponseLength.SHORTER: "shorter",
}


def _prompt_preview(prompt: str | None, max_chars: int = 60) -> str | None:
    """Return a truncated prompt preview suitable for terminal output."""
    if not prompt:
        return None
    if len(prompt) <= max_chars:
        return prompt
    return f"{prompt[:max_chars]}..."


def _settings_to_json(notebook_id: str, settings: ChatSettings) -> dict:
    """Render chat settings using a stable machine-readable schema."""
    preview = _prompt_preview(settings.custom_prompt)
    return {
        "notebook_id": notebook_id,
        "goal": _GOAL_TO_STYLE[settings.goal],
        "response_length": _ENUM_TO_LENGTH[settings.response_length],
        "custom_prompt": preview,
        "custom_prompt_len": len(settings.custom_prompt or ""),
        "source": settings.source,
    }


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
    @click.option("--save-as-note", is_flag=True, help="Save response as a note")
    @click.option("--note-title", default=None, help="Note title (use with --save-as-note)")
    @with_client
    def ask_cmd(
        ctx,
        question,
        notebook_id,
        conversation_id,
        source_ids,
        json_output,
        save_as_note,
        note_title,
        client_auth,
    ):
        """Ask a notebook a question.

        By default, continues the last conversation. Use --new to start fresh.
        The answer includes inline citations like [1], [2] that reference sources.
        Use --json to get structured output with source IDs for each reference.

        \b
        Example:
          notebooklm ask "what are the main themes?"
          notebooklm ask -c <id> "continue this one"
          notebooklm ask -s src_001 -s src_002 "question about specific sources"
          notebooklm ask "explain X" --json             # Get answer with source references
          notebooklm ask "explain X" --save-as-note     # Save response as a note
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
                    if not save_as_note:
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

                if save_as_note:
                    if not result.answer:
                        console.print("[yellow]Warning: No answer to save as note[/yellow]")
                        return
                    try:
                        title = note_title or f"Chat: {question[:50]}"
                        note = await client.notes.create(nb_id_resolved, title, result.answer)
                        console.print(
                            f"\n[dim]Saved as note: {note.title} ({note.id[:8]}...)[/dim]"
                        )
                    except Exception as e:
                        console.print(f"[yellow]Warning: Failed to save note: {e}[/yellow]")

        return _run()

    @cli.command("configure")
    @click.option(
        "-n",
        "--notebook",
        "notebook_id",
        default=None,
        help="Notebook ID (uses current if not set)",
    )
    @click.option(
        "--mode",
        "chat_mode",
        type=click.Choice(["default", "learning-guide", "concise", "detailed"]),
        default=None,
        help="Legacy shorthand baseline (sets style + length together)",
    )
    @click.option(
        "--style",
        type=click.Choice(["default", "learning-guide", "custom"]),
        default=None,
        help="Conversational style (Web UI style axis)",
    )
    @click.option(
        "--length",
        "--response-length",
        "length",
        type=click.Choice(["default", "longer", "shorter"]),
        default=None,
        help="Response length (Web UI length axis)",
    )
    @click.option(
        "--custom-instructions",
        "--persona",
        "custom_instructions",
        default=None,
        help="Custom instructions text (implies --style custom if style not given)",
    )
    @click.option("--show", is_flag=True, help="Show current chat settings")
    @click.option("--reset", is_flag=True, help="Reset to default/default")
    @click.option("--json", "json_output", is_flag=True, help="Output structured JSON")
    @click.option(
        "--force",
        is_flag=True,
        help="Allow absolute set fallback when PATCH fails to read current settings",
    )
    @with_client
    def configure_cmd(
        ctx,
        notebook_id,
        chat_mode,
        style,
        length,
        custom_instructions,
        show,
        reset,
        json_output,
        force,
        client_auth,
    ):
        """Configure notebook chat settings with web-parity semantics.

        \b
        Axes:
          --style  : default | learning-guide | custom
          --length : shorter | default | longer

        \b
        Examples:
          notebooklm configure --show
          notebooklm configure --style learning-guide
          notebooklm configure --length longer
          notebooklm configure --custom-instructions "Act as a chemistry tutor"
          notebooklm configure --mode detailed --length shorter
          notebooklm configure --reset
        """
        nb_id = require_notebook(notebook_id)

        async def _run():
            async with NotebookLMClient(client_auth) as client:
                nb_id_resolved = await resolve_notebook_id(client, nb_id)

                if show and reset:
                    raise click.UsageError("--show and --reset cannot be used together.")

                if custom_instructions is not None and style is not None and style != "custom":
                    raise click.UsageError(
                        "--custom-instructions/--persona can only be used with --style custom."
                    )

                if show:
                    settings = await client.chat.get_settings(nb_id_resolved, strict=False)
                    payload = _settings_to_json(nb_id_resolved, settings)
                    if json_output:
                        json_output_response(payload)
                    else:
                        preview = payload["custom_prompt"]
                        if preview:
                            prompt_line = (
                                f"[set] ({payload['custom_prompt_len']} chars) {preview}"
                            )
                        else:
                            prompt_line = "[none]"

                        console.print("[bold cyan]Chat settings[/bold cyan]")
                        console.print(f"Notebook: {nb_id_resolved}")
                        console.print(f"Style: {payload['goal']}")
                        console.print(f"Length: {payload['response_length']}")
                        console.print(f"Custom instructions: {prompt_line}")
                        console.print(f"Source: {payload['source']}")
                    return

                if reset:
                    await client.chat.reset_settings(nb_id_resolved)
                    if json_output:
                        json_output_response(
                            {
                                "notebook_id": nb_id_resolved,
                                "action": "reset",
                                "goal": "default",
                                "response_length": "default",
                                "custom_prompt": None,
                            }
                        )
                    else:
                        console.print("[green]Chat settings reset to default/default[/green]")
                    return

                if (
                    chat_mode
                    and style is None
                    and length is None
                    and custom_instructions is None
                ):
                    mode_map = {
                        "default": ChatMode.DEFAULT,
                        "learning-guide": ChatMode.LEARNING_GUIDE,
                        "concise": ChatMode.CONCISE,
                        "detailed": ChatMode.DETAILED,
                    }
                    await client.chat.set_mode(nb_id_resolved, mode_map[chat_mode])
                    if json_output:
                        baseline_goal, baseline_length = _MODE_TO_BASELINE[chat_mode]
                        json_output_response(
                            {
                                "notebook_id": nb_id_resolved,
                                "action": "set_mode",
                                "mode": chat_mode,
                                "goal": _GOAL_TO_STYLE[baseline_goal],
                                "response_length": _ENUM_TO_LENGTH[baseline_length],
                            }
                        )
                    else:
                        console.print(f"[green]Chat mode set to: {chat_mode}[/green]")
                    return

                baseline_goal: ChatGoal | None = None
                baseline_length: ChatResponseLength | None = None
                if chat_mode:
                    baseline_goal, baseline_length = _MODE_TO_BASELINE[chat_mode]

                resolved_goal = baseline_goal
                resolved_length = baseline_length

                if style is not None:
                    resolved_goal = _STYLE_TO_GOAL[style]
                if length is not None:
                    resolved_length = _LENGTH_TO_ENUM[length]

                if custom_instructions is not None and resolved_goal != ChatGoal.CUSTOM:
                    resolved_goal = ChatGoal.CUSTOM

                has_goal_input = chat_mode is not None or style is not None or custom_instructions is not None
                has_length_input = chat_mode is not None or length is not None

                if not has_goal_input and not has_length_input:
                    if json_output:
                        json_output_response(
                            {
                                "notebook_id": nb_id_resolved,
                                "updated": False,
                                "message": "No changes specified",
                            }
                        )
                    else:
                        console.print(
                            "[yellow]No changes specified. Use --show to inspect current settings.[/yellow]"
                        )
                    return

                updated_settings: ChatSettings
                action = "update_settings"

                if has_goal_input and has_length_input:
                    if resolved_goal is None or resolved_length is None:
                        raise click.ClickException(
                            "Internal resolution error: missing goal/length for absolute set."
                        )
                    if resolved_goal == ChatGoal.CUSTOM and custom_instructions is None:
                        raise click.UsageError(
                            "Setting style=custom with absolute set requires "
                            "--custom-instructions/--persona."
                        )

                    updated_settings = ChatSettings(
                        goal=resolved_goal,
                        response_length=resolved_length,
                        custom_prompt=custom_instructions if resolved_goal == ChatGoal.CUSTOM else None,
                        source="default",
                    )
                    await client.chat.set_settings(nb_id_resolved, updated_settings)
                    action = "set_settings"
                else:
                    goal_arg = resolved_goal if has_goal_input else UNSET
                    length_arg = resolved_length if has_length_input else UNSET
                    prompt_arg = custom_instructions if custom_instructions is not None else UNSET

                    try:
                        updated_settings = await client.chat.update_settings(
                            nb_id_resolved,
                            goal=goal_arg,
                            response_length=length_arg,
                            custom_prompt=prompt_arg,
                            strict=True,
                        )
                    except ChatSettingsUpdateError as exc:
                        if not force:
                            raise
                        if resolved_goal is None or resolved_length is None:
                            raise click.ClickException(
                                "--force requires explicit style and length (or --mode) "
                                "to perform an absolute set."
                            ) from exc
                        if resolved_goal == ChatGoal.CUSTOM and custom_instructions is None:
                            raise click.UsageError(
                                "--force absolute set with style=custom requires "
                                "--custom-instructions/--persona."
                            ) from exc

                        updated_settings = ChatSettings(
                            goal=resolved_goal,
                            response_length=resolved_length,
                            custom_prompt=custom_instructions if resolved_goal == ChatGoal.CUSTOM else None,
                            source="default",
                        )
                        await client.chat.set_settings(nb_id_resolved, updated_settings)
                        action = "force_set_settings"

                payload = _settings_to_json(nb_id_resolved, updated_settings)
                payload["action"] = action

                if json_output:
                    json_output_response(payload)
                    return

                prompt_preview = payload["custom_prompt"]
                if prompt_preview:
                    prompt_text = f"[set] ({payload['custom_prompt_len']} chars)"
                else:
                    prompt_text = "[none]"
                console.print(
                    "[green]Chat settings updated[/green]: "
                    f"style={payload['goal']}, length={payload['response_length']}, "
                    f"custom_instructions={prompt_text}"
                )

        return _run()

    @cli.command("history")
    @click.option(
        "-n",
        "--notebook",
        "notebook_id",
        default=None,
        help="Notebook ID (uses current if not set)",
    )
    @click.option("--limit", "-l", default=100, help="Maximum number of Q&A turns to show")
    @click.option("--clear", "clear_cache", is_flag=True, help="Clear local conversation cache")
    @click.option("--save", "save_as_note", is_flag=True, help="Save history as a note")
    @click.option("-t", "--note-title", "note_title", default=None, help="Note title (with --save)")
    @click.option("--json", "json_output", is_flag=True, help="Output as JSON")
    @click.option("--show-all", is_flag=True, help="Show full Q&A content instead of preview")
    @with_client
    def history_cmd(
        ctx,
        notebook_id,
        limit,
        clear_cache,
        save_as_note,
        note_title,
        json_output,
        show_all,
        client_auth,
    ):
        """Get conversation history or save it as a note.

        Shows all Q&A turns from the most recent conversation.

        \b
        Example:
          notebooklm history                      # Show Q&A history
          notebooklm history -n nb123             # Show history for specific notebook
          notebooklm history --clear              # Clear local cache
          notebooklm history --save               # Save history as a note
          notebooklm history --save --note-title "Summary"  # Save with custom title
          notebooklm history --json               # Machine-readable JSON output
          notebooklm history --show-all           # Full Q&A content
        """

        async def _run():
            async with NotebookLMClient(client_auth) as client:
                if clear_cache:
                    result = client.chat.clear_cache()
                    if result:
                        console.print("[green]Local conversation cache cleared[/green]")
                    else:
                        console.print("[yellow]No cache to clear[/yellow]")
                    return

                nb_id = require_notebook(notebook_id)
                nb_id_resolved = await resolve_notebook_id(client, nb_id)
                conv_id = await client.chat.get_conversation_id(nb_id_resolved)
                qa_pairs = await client.chat.get_history(
                    nb_id_resolved, limit=limit, conversation_id=conv_id
                )

                if save_as_note:
                    if not qa_pairs:
                        raise click.ClickException(
                            "No conversation history found for this notebook."
                        )
                    content = _format_history(qa_pairs)
                    title = note_title or "Chat History"
                    note = await client.notes.create(nb_id_resolved, title, content)
                    console.print(f"[green]Saved as note: {note.title} ({note.id[:8]}...)[/green]")
                    return

                if json_output:
                    data = {
                        "notebook_id": nb_id_resolved,
                        "conversation_id": conv_id,
                        "count": len(qa_pairs),
                        "qa_pairs": [
                            {"turn": i, "question": q, "answer": a}
                            for i, (q, a) in enumerate(qa_pairs, 1)
                        ],
                    }
                    json_output_response(data)
                    return

                if not qa_pairs:
                    console.print("[yellow]No conversation history[/yellow]")
                    return

                console.print("[bold cyan]Conversation History:[/bold cyan]")

                if show_all:
                    if conv_id:
                        console.print(f"\n[bold]── {conv_id} ──[/bold]")
                    for i, (question, answer) in enumerate(qa_pairs, 1):
                        console.print(f"[bold]#{i} Q:[/bold] {question}")
                        console.print(f"   A: {answer}\n")
                    return

                if conv_id:
                    console.print(f"\n[dim]── {conv_id} ──[/dim]")
                table = Table()
                table.add_column("#", style="dim", width=4)
                table.add_column("Question", style="white", max_width=50)
                table.add_column("Answer preview", style="dim", max_width=50)
                for i, (question, answer) in enumerate(qa_pairs, 1):
                    table.add_row(str(i), question[:50], answer[:50])
                console.print(table)
                console.print("\n[dim]Use 'notebooklm history --save' to save as a note.[/dim]")

        return _run()


def _format_single_qa(question: str, answer: str) -> str:
    """Format one Q&A pair as note content."""
    parts = []
    if question:
        parts.append(f"**Q:** {question}")
    if answer:
        parts.append(f"**A:** {answer}")
    return "\n\n".join(parts)


def _format_history(qa_pairs: list[tuple[str, str]]) -> str:
    """Format Q&A history as note content."""
    turns = []
    for i, (question, answer) in enumerate(qa_pairs, 1):
        turns.append(f"### Turn {i}\n\n{_format_single_qa(question, answer)}")
    return "\n\n---\n\n".join(turns)
