"""Generate content CLI commands.

Commands:
    audio        Generate audio overview (podcast)
    report       Generate briefing-doc or study-guide reports
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import click

from ..client import NotebookLMClient
from ..types import (
    AudioFormat,
    AudioLength,
    GenerationStatus,
    ReportFormat,
)
from .helpers import (
    console,
    json_error_response,
    json_output_response,
    require_notebook,
    resolve_notebook_id,
    resolve_source_ids,
    with_client,
)
from .language import SUPPORTED_LANGUAGES, get_language
from .options import json_option, retry_option

DEFAULT_LANGUAGE = "en"

# Retry constants
RETRY_INITIAL_DELAY = 60.0  # seconds
RETRY_MAX_DELAY = 300.0  # 5 minutes
RETRY_BACKOFF_MULTIPLIER = 2.0


def calculate_backoff_delay(
    attempt: int,
    initial_delay: float = RETRY_INITIAL_DELAY,
    max_delay: float = RETRY_MAX_DELAY,
    multiplier: float = RETRY_BACKOFF_MULTIPLIER,
) -> float:
    """Calculate exponential backoff delay for a retry attempt.

    Args:
        attempt: The current attempt number (0-indexed).
        initial_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        multiplier: Backoff multiplier.

    Returns:
        Delay in seconds for this attempt.
    """
    delay = initial_delay * (multiplier**attempt)
    return min(delay, max_delay)


async def generate_with_retry(
    generate_fn: Callable[[], Awaitable[GenerationStatus | None]],
    max_retries: int,
    artifact_type: str,
    json_output: bool = False,
) -> GenerationStatus | None:
    """Generate artifact with retry on rate limit.

    Retries the generation call with exponential backoff when rate limited.
    Always makes at least one attempt, even when max_retries=0.

    Args:
        generate_fn: Async function that performs the generation.
        max_retries: Maximum number of retries (0 = no retry, just one attempt).
        artifact_type: Display name for progress messages.
        json_output: Whether to suppress console output.

    Returns:
        GenerationStatus or None if generation failed.
    """
    for attempt in range(max_retries + 1):
        result = await generate_fn()

        # Return immediately if not rate limited (success or other failure)
        if not isinstance(result, GenerationStatus) or not result.is_rate_limited:
            return result

        # Rate limited with no retries left
        if attempt >= max_retries:
            return result

        # Wait before retry
        delay = calculate_backoff_delay(attempt)
        if not json_output:
            console.print(
                f"[yellow]{artifact_type.title()} rate limited. "
                f"Retrying in {int(delay)}s (attempt {attempt + 2}/{max_retries + 1})...[/yellow]"
            )
        await asyncio.sleep(delay)

    # Unreachable, but satisfies type checker
    return None


def resolve_language(language: str | None) -> str:
    """Resolve language from CLI flag, config, or default.

    Priority: CLI flag > config file > "en" default.
    Uses explicit None checks to avoid treating empty string as falsy.
    Validates that the language code is supported.
    """
    if language is not None:
        if language not in SUPPORTED_LANGUAGES:
            raise click.BadParameter(
                f"Unknown language code: {language}\n"
                "Use one of the supported codes, for example: en, zh_Hans, ja, fr, de, ko.",
                param_hint="'--language'",
            )
        return language
    config_lang = get_language()
    if config_lang is not None:
        return config_lang
    return DEFAULT_LANGUAGE


async def handle_generation_result(
    client: NotebookLMClient,
    notebook_id: str,
    result: Any,
    artifact_type: str,
    wait: bool = False,
    json_output: bool = False,
    timeout: float = 300.0,
) -> GenerationStatus | None:
    """Handle generation result with optional waiting and output formatting.

    Consolidates common pattern across all generate commands:
    - Check for None/failed result
    - Optionally wait for completion
    - Output status in JSON or console format

    Args:
        client: The NotebookLM client.
        notebook_id: The notebook ID.
        result: The generation result from artifacts API.
        artifact_type: Display name for the artifact type (e.g., "audio", "video").
        wait: Whether to wait for completion.
        json_output: Whether to output as JSON.
        timeout: Timeout for waiting (default: 300s).

    Returns:
        Final GenerationStatus, or None if generation failed.
    """
    # Handle failed generation or rate limiting
    if not result:
        if json_output:
            json_error_response(
                "GENERATION_FAILED",
                f"{artifact_type.title()} generation failed",
            )
        else:
            console.print(f"[red]{artifact_type.title()} generation failed.[/red]")
        return None

    # Check for rate limiting (result exists but failed due to rate limit)
    if isinstance(result, GenerationStatus) and result.is_rate_limited:
        if json_output:
            json_error_response(
                "RATE_LIMITED",
                f"{artifact_type.title()} generation rate limited by Google",
            )
        else:
            console.print(
                f"[red]{artifact_type.title()} generation rate limited by Google.[/red]\n"
                "[yellow]Daily quota may be exceeded. Try again in 1-24 hours, "
                "or use --retry N to retry automatically.[/yellow]"
            )
        return result

    # Extract task_id from various result formats
    task_id: str | None = None
    status: Any = result
    if isinstance(result, GenerationStatus):
        task_id = result.task_id
        status = result
    elif isinstance(result, dict):
        task_id = result.get("artifact_id") or result.get("task_id")
        status = result
    elif isinstance(result, list) and len(result) > 0:
        task_id = result[0] if isinstance(result[0], str) else None
        status = result

    # Wait for completion if requested
    if wait and task_id:
        if not json_output:
            console.print(f"[yellow]Generating {artifact_type}...[/yellow] Task: {task_id}")
        status = await client.artifacts.wait_for_completion(notebook_id, task_id, timeout=timeout)

    # Output status
    _output_generation_status(status, artifact_type, json_output)

    return status if isinstance(status, GenerationStatus) else None


def _extract_task_id(status: Any) -> str | None:
    """Extract task ID from various status formats.

    Handles GenerationStatus objects, dicts with task_id/artifact_id keys,
    and lists where the first element is an ID string.
    """
    if hasattr(status, "task_id"):
        return status.task_id
    if isinstance(status, dict):
        return status.get("task_id") or status.get("artifact_id")
    if isinstance(status, list) and len(status) > 0 and isinstance(status[0], str):
        return status[0]
    return None


def _output_generation_status(status: Any, artifact_type: str, json_output: bool) -> None:
    """Output generation status in appropriate format."""
    is_complete = hasattr(status, "is_complete") and status.is_complete
    is_failed = hasattr(status, "is_failed") and status.is_failed

    if json_output:
        if is_complete:
            json_output_response(
                {
                    "task_id": getattr(status, "task_id", None),
                    "status": "completed",
                    "url": getattr(status, "url", None),
                }
            )
        elif is_failed:
            json_error_response(
                "GENERATION_FAILED",
                getattr(status, "error", None) or f"{artifact_type.title()} generation failed",
            )
        else:
            task_id = _extract_task_id(status)
            json_output_response({"task_id": task_id, "status": "pending"})
    else:
        if is_complete:
            url = getattr(status, "url", None)
            if url:
                console.print(f"[green]{artifact_type.title()} ready:[/green] {url}")
            else:
                console.print(f"[green]{artifact_type.title()} ready[/green]")
        elif is_failed:
            console.print(f"[red]Failed:[/red] {getattr(status, 'error', 'Unknown error')}")
        else:
            task_id = _extract_task_id(status)
            console.print(f"[yellow]Started:[/yellow] {task_id or status}")


@click.group()
def generate():
    """Generate content from notebook.

    \b
    LLM-friendly design: Describe what you want in natural language.

    \b
    Examples:
      notebooklm use nb123
      notebooklm generate audio "deep dive focusing on chapter 3"
      notebooklm generate report --format study-guide
      notebooklm generate report "focus on the key decisions"

    \b
    Types:
      audio        Audio overview (podcast)
      report       Report (briefing-doc or study-guide)
    """
    pass


@generate.command("audio")
@click.argument("description", default="", required=False)
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option(
    "--format",
    "audio_format",
    type=click.Choice(["deep-dive", "brief", "critique", "debate"]),
    default="deep-dive",
)
@click.option(
    "--length",
    "audio_length",
    type=click.Choice(["short", "default", "long"]),
    default="default",
)
@click.option("--language", default=None, help="Output language (default: from config or 'en')")
@click.option("--source", "-s", "source_ids", multiple=True, help="Limit to specific source IDs")
@click.option("--wait/--no-wait", default=False, help="Wait for completion (default: no-wait)")
@retry_option
@json_option
@with_client
def generate_audio(
    ctx,
    description,
    notebook_id,
    audio_format,
    audio_length,
    language,
    source_ids,
    wait,
    max_retries,
    json_output,
    client_auth,
):
    """Generate audio overview (podcast).

    \b
    Use --json for machine-readable output.

    \b
    Examples:
      notebooklm generate audio "deep dive focusing on key themes"
      notebooklm generate audio "make it funny and casual" --format debate
      notebooklm generate audio -s src_001 -s src_002 "from specific sources"
    """
    nb_id = require_notebook(notebook_id)
    format_map = {
        "deep-dive": AudioFormat.DEEP_DIVE,
        "brief": AudioFormat.BRIEF,
        "critique": AudioFormat.CRITIQUE,
        "debate": AudioFormat.DEBATE,
    }
    length_map = {
        "short": AudioLength.SHORT,
        "default": AudioLength.DEFAULT,
        "long": AudioLength.LONG,
    }

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            sources = await resolve_source_ids(client, nb_id_resolved, source_ids)

            async def _generate():
                return await client.artifacts.generate_audio(
                    nb_id_resolved,
                    source_ids=sources,
                    language=resolve_language(language),
                    instructions=description or None,
                    audio_format=format_map[audio_format],
                    audio_length=length_map[audio_length],
                )

            result = await generate_with_retry(_generate, max_retries, "audio", json_output)
            await handle_generation_result(
                client, nb_id_resolved, result, "audio", wait, json_output
            )

    return _run()


@generate.command("report")
@click.argument("description", default="", required=False)
@click.option(
    "--format",
    "report_format",
    type=click.Choice(["briefing-doc", "study-guide"]),
    default="briefing-doc",
    help="Report format (default: briefing-doc)",
)
@click.option(
    "-n",
    "--notebook",
    "notebook_id",
    default=None,
    help="Notebook ID (uses current if not set)",
)
@click.option("--source", "-s", "source_ids", multiple=True, help="Limit to specific source IDs")
@click.option("--language", default=None, help="Output language (default: from config or 'en')")
@click.option(
    "--append",
    "append_instructions",
    default=None,
    help="Append extra instructions to the built-in report prompt.",
)
@click.option("--wait/--no-wait", default=False, help="Wait for completion (default: no-wait)")
@retry_option
@json_option
@with_client
def generate_report_cmd(
    ctx,
    description,
    report_format,
    notebook_id,
    source_ids,
    language,
    append_instructions,
    wait,
    max_retries,
    json_output,
    client_auth,
):
    """Generate a report (briefing doc or study guide).

    \b
    Use --json for machine-readable output.

    \b
    Examples:
      notebooklm generate report                              # briefing-doc (default)
      notebooklm generate report --format study-guide         # study guide
      notebooklm generate report -s src_001 -s src_002        # from specific sources
      notebooklm generate report "Focus on AI trends"         # append focus instructions
      notebooklm generate report --format study-guide --append "Target audience: beginners"
    """
    nb_id = require_notebook(notebook_id)
    extra_parts = [part for part in (description, append_instructions) if part]
    extra_instructions = "\n\n".join(extra_parts) if extra_parts else None

    format_map = {
        "briefing-doc": ReportFormat.BRIEFING_DOC,
        "study-guide": ReportFormat.STUDY_GUIDE,
    }
    report_format_enum = format_map[report_format]

    format_display = {
        "briefing-doc": "briefing document",
        "study-guide": "study guide",
    }[report_format]

    async def _run():
        async with NotebookLMClient(client_auth) as client:
            nb_id_resolved = await resolve_notebook_id(client, nb_id)
            sources = await resolve_source_ids(client, nb_id_resolved, source_ids)

            async def _generate():
                return await client.artifacts.generate_report(
                    nb_id_resolved,
                    source_ids=sources,
                    language=resolve_language(language),
                    report_format=report_format_enum,
                    extra_instructions=extra_instructions,
                )

            result = await generate_with_retry(_generate, max_retries, format_display, json_output)
            await handle_generation_result(
                client, nb_id_resolved, result, format_display, wait, json_output
            )

    return _run()
