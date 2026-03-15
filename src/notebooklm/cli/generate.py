"""Generate content CLI commands.

Commands:
    audio        Generate audio overview (podcast)
    report       Generate briefing-doc or study-guide reports
"""

import asyncio
from collections.abc import Awaitable, Callable
import time
from typing import Any

import click

from ..client import NotebookLMClient
from ..contracts import CacheUpdates, Diagnostics, Envelope, Intent, Route, Transport
from ..contracts.rpc_map import RPC_MAP
from ..local.db import connect_db
from ..sync import invalidate_notebook_detail, seed_pending_artifact
from ..types import (
    AudioFormat,
    AudioLength,
    GenerationStatus,
    ReportFormat,
)
from ..workflows import run_summarize_workflow
from ..workflows.runtime import (
    RETRY_BACKOFF_MULTIPLIER,
    RETRY_INITIAL_DELAY,
    RETRY_MAX_DELAY,
    calculate_backoff_delay,
    retry_with_backoff,
)
from .helpers import (
    console,
    emit_compatibility_warning,
    json_error_response,
    json_output_response,
    require_notebook,
    resolve_notebook_id,
    resolve_source_ids,
    with_client,
)
from .language import SUPPORTED_LANGUAGES, get_language
from .options import json_option, retry_option
from .session import _inspect_auth_state, _trace_and_run_id

DEFAULT_LANGUAGE = "en"
_AUDIO_RPC_BINDING = RPC_MAP[(Intent.GENERATION.value, "audio")]
_BRIEFING_DOC_RPC_BINDING = RPC_MAP[(Intent.GENERATION.value, "briefing_doc")]
_STUDY_GUIDE_RPC_BINDING = RPC_MAP[(Intent.GENERATION.value, "study_guide")]
_PENDING_GENERATION_TABLES = ["artifacts", "notebooks", "sync_runs"]


def _audio_format_map() -> dict[str, AudioFormat]:
    return {
        "deep-dive": AudioFormat.DEEP_DIVE,
        "brief": AudioFormat.BRIEF,
        "critique": AudioFormat.CRITIQUE,
        "debate": AudioFormat.DEBATE,
    }


def _audio_length_map() -> dict[str, AudioLength]:
    return {
        "short": AudioLength.SHORT,
        "default": AudioLength.DEFAULT,
        "long": AudioLength.LONG,
    }


def _report_format_map() -> dict[str, ReportFormat]:
    return {
        "briefing-doc": ReportFormat.BRIEFING_DOC,
        "study-guide": ReportFormat.STUDY_GUIDE,
    }


def _should_seed_pending_artifact(result: Any) -> bool:
    return bool(result) and not (
        isinstance(result, GenerationStatus) and result.is_rate_limited
    )


def _record_pending_artifact(
    *,
    notebook_id: str,
    task_id: str,
    artifact_type: str,
    storage_path,
    reason: str,
) -> None:
    connection = connect_db()
    try:
        seed_pending_artifact(
            connection,
            notebook_id,
            task_id,
            artifact_type=artifact_type,
            storage_path=storage_path,
        )
        invalidate_notebook_detail(
            connection,
            notebook_id,
            storage_path=storage_path,
            reason=reason,
        )
    finally:
        connection.close()


def _profile_id(ctx: click.Context) -> str:
    try:
        _, profile_id = _inspect_auth_state(ctx)
    except Exception:
        profile_id = "default"
    return profile_id


def _generation_status_value(status: Any) -> str:
    raw_status = None
    if isinstance(status, dict):
        raw_status = status.get("status")
    else:
        raw_status = getattr(status, "status", None)

    if isinstance(raw_status, str):
        normalized = raw_status.casefold()
        if normalized == "completed":
            return "completed"
        if normalized == "failed":
            return "failed"
        if normalized in {"pending", "in_progress", "processing"}:
            return "pending"

    return "pending"


def _generation_status_url(status: Any) -> str | None:
    if isinstance(status, dict):
        value = status.get("url")
    else:
        value = getattr(status, "url", None)
    return str(value) if value is not None else None


def _generation_result_payload(status: Any) -> dict[str, Any]:
    payload = {
        "task_id": _extract_task_id(status),
        "status": _generation_status_value(status),
    }
    url = _generation_status_url(status)
    if url is not None:
        payload["url"] = url
    return payload


def _generation_cache_updates(
    notebook_id: str,
    *,
    seeded_pending_artifact: bool,
) -> CacheUpdates:
    if not seeded_pending_artifact:
        return CacheUpdates()
    return CacheUpdates(
        tables_touched=list(_PENDING_GENERATION_TABLES),
        invalidated=[f"notebook_detail:{notebook_id}"],
    )


def _generation_json_envelope(
    ctx: click.Context,
    *,
    binding,
    notebook_id: str,
    status: Any,
    elapsed_ms: int,
    route_reason: str,
    cache_updates: CacheUpdates | None = None,
) -> dict[str, Any]:
    trace_id, run_id = _trace_and_run_id(ctx, binding.mode)
    return Envelope(
        ok=True,
        trace_id=trace_id,
        run_id=run_id,
        route=Route(
            intent=Intent(binding.intent),
            mode=binding.mode,
            notebook_id=notebook_id,
            profile_id=_profile_id(ctx),
            source_of_truth="remote_http",
            cache_mode="network",
            reason=route_reason,
            transport=Transport(
                kind=binding.transport_kind,
                endpoint=binding.endpoint,
                rpcid=binding.rpcid,
            ),
        ),
        result=_generation_result_payload(status),
        freshness=None,
        cache_updates=cache_updates or CacheUpdates(),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    ).to_dict()


def _status_flag(status: Any, name: str) -> bool:
    return getattr(status, name, False) is True


def _generation_error_details(status: Any, artifact_type: str) -> tuple[str, str] | None:
    if _status_flag(status, "is_rate_limited"):
        return ("RATE_LIMITED", f"{artifact_type.title()} generation rate limited by Google")
    if _status_flag(status, "is_failed"):
        return (
            "GENERATION_FAILED",
            getattr(status, "error", None) or f"{artifact_type.title()} generation failed",
        )
    return None


def _generation_elapsed_ms(started_at: float | None) -> int:
    if started_at is None:
        return 0
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _emit_generation_json_error(
    *,
    ctx: click.Context,
    binding,
    notebook_id: str,
    code: str,
    message: str,
    route_reason: str,
    elapsed_ms: int,
    cache_updates: CacheUpdates | None = None,
) -> None:
    json_error_response(
        code,
        message,
        ctx=ctx,
        binding=binding,
        profile_id=_profile_id(ctx),
        notebook_id=notebook_id,
        source_of_truth="remote_http",
        cache_mode="network",
        reason=route_reason,
        cache_updates=cache_updates or CacheUpdates(),
        diagnostics=Diagnostics(retries=0, auth_refreshed=False, elapsed_ms=elapsed_ms),
    )


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
    def _should_retry(result: GenerationStatus | None) -> bool:
        return isinstance(result, GenerationStatus) and result.is_rate_limited

    def _on_retry(attempt: int, total_attempts: int, delay: float) -> None:
        if json_output:
            return
        console.print(
            f"[yellow]{artifact_type.title()} rate limited. "
            f"Retrying in {int(delay)}s (attempt {attempt + 1}/{total_attempts})...[/yellow]"
        )

    return await retry_with_backoff(
        generate_fn,
        max_retries=max_retries,
        should_retry=_should_retry,
        on_retry=_on_retry,
        sleep=asyncio.sleep,
    )


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
    *,
    ctx: click.Context | None = None,
    binding=None,
    started_at: float | None = None,
    cache_updates: CacheUpdates | None = None,
    route_reason: str | None = None,
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
    route_reason = (
        route_reason
        or f"Start remote NotebookLM {artifact_type} generation and optionally wait for completion."
    )
    elapsed_ms = _generation_elapsed_ms(started_at)
    if json_output and (ctx is None or binding is None):
        raise ValueError("ctx and binding are required for generation JSON output")

    # Handle failed generation or rate limiting
    if not result:
        if json_output:
            _emit_generation_json_error(
                ctx=ctx,
                binding=binding,
                notebook_id=notebook_id,
                code="GENERATION_FAILED",
                message=f"{artifact_type.title()} generation failed",
                route_reason=route_reason,
                elapsed_ms=elapsed_ms,
                cache_updates=cache_updates,
            )
        else:
            console.print(f"[red]{artifact_type.title()} generation failed.[/red]")
        return None

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

    if json_output:
        error_details = _generation_error_details(status, artifact_type)
        if error_details is not None:
            code, message = error_details
            _emit_generation_json_error(
                ctx=ctx,
                binding=binding,
                notebook_id=notebook_id,
                code=code,
                message=message,
                route_reason=route_reason,
                elapsed_ms=elapsed_ms,
                cache_updates=cache_updates,
            )
        json_output_response(
            _generation_json_envelope(
                ctx,
                binding=binding,
                notebook_id=notebook_id,
                status=status,
                elapsed_ms=elapsed_ms,
                route_reason=route_reason,
                cache_updates=cache_updates,
            )
        )
        return status if isinstance(status, GenerationStatus) else None

    # Output status
    _output_generation_status(status, artifact_type, json_output=False)

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
    is_complete = _status_flag(status, "is_complete")
    is_rate_limited = _status_flag(status, "is_rate_limited")
    is_failed = _status_flag(status, "is_failed")

    if json_output:
        if is_complete:
            json_output_response(
                {
                    "task_id": getattr(status, "task_id", None),
                    "status": "completed",
                    "url": getattr(status, "url", None),
                }
            )
        elif is_rate_limited:
            json_error_response(
                "RATE_LIMITED",
                f"{artifact_type.title()} generation rate limited by Google",
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
        elif is_rate_limited:
            console.print(
                f"[red]{artifact_type.title()} generation rate limited by Google.[/red]\n"
                "[yellow]Daily quota may be exceeded. Try again in 1-24 hours, "
                "or use --retry N to retry automatically.[/yellow]"
            )
        elif is_failed:
            console.print(f"[red]Failed:[/red] {getattr(status, 'error', 'Unknown error')}")
        else:
            task_id = _extract_task_id(status)
            console.print(f"[yellow]Started:[/yellow] {task_id or status}")


def _run_audio_generation(
    *,
    ctx: click.Context,
    client_auth,
    notebook_id: str | None,
    description: str,
    audio_format: str,
    audio_length: str,
    language: str | None,
    source_ids: tuple[str, ...],
    wait: bool,
    max_retries: int,
    json_output: bool,
    compatibility_warning_command: str | None = None,
):
    nb_id = require_notebook(notebook_id)
    format_map = _audio_format_map()
    length_map = _audio_length_map()
    if compatibility_warning_command is not None:
        emit_compatibility_warning(
            compatibility_warning_command,
            enabled=not json_output,
        )

    async def _run():
        started_at = time.perf_counter()
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
            task_id = _extract_task_id(result)
            seeded_pending_artifact = False
            if task_id is not None and _should_seed_pending_artifact(result):
                _record_pending_artifact(
                    notebook_id=nb_id_resolved,
                    task_id=task_id,
                    artifact_type="audio",
                    storage_path=client_auth.storage_path,
                    reason="artifact.create",
                )
                seeded_pending_artifact = True
            await handle_generation_result(
                client,
                nb_id_resolved,
                result,
                "audio",
                wait,
                json_output,
                ctx=ctx,
                binding=_AUDIO_RPC_BINDING,
                started_at=started_at,
                cache_updates=_generation_cache_updates(
                    nb_id_resolved,
                    seeded_pending_artifact=seeded_pending_artifact,
                ),
                route_reason=(
                    "Start remote NotebookLM audio overview generation and optionally wait "
                    "for completion."
                ),
            )

    return _run()


def _run_report_generation(
    *,
    ctx: click.Context,
    client_auth,
    notebook_id: str | None,
    description: str,
    report_format: str,
    source_ids: tuple[str, ...],
    language: str | None,
    append_instructions: str | None,
    wait: bool,
    max_retries: int,
    json_output: bool,
    compatibility_warning_command: str | None = None,
):
    nb_id = require_notebook(notebook_id)
    report_format_enum = _report_format_map()[report_format]
    binding = (
        _STUDY_GUIDE_RPC_BINDING
        if report_format == "study-guide"
        else _BRIEFING_DOC_RPC_BINDING
    )
    if compatibility_warning_command is not None:
        emit_compatibility_warning(
            compatibility_warning_command,
            enabled=not json_output,
        )

    async def _run():
        started_at = time.perf_counter()
        async with NotebookLMClient(client_auth) as client:
            workflow_result = await run_summarize_workflow(
                client,
                notebook_id=nb_id,
                source_ids=source_ids,
                language=resolve_language(language),
                report_format=report_format_enum,
                description=description or None,
                append_instructions=append_instructions,
                max_retries=max_retries,
                json_output=json_output,
                resolve_notebook_id=resolve_notebook_id,
                resolve_source_ids=resolve_source_ids,
                generate_with_retry=generate_with_retry,
            )

            task_id = _extract_task_id(workflow_result.result)
            seeded_pending_artifact = False
            if task_id is not None and _should_seed_pending_artifact(workflow_result.result):
                _record_pending_artifact(
                    notebook_id=workflow_result.resolved_notebook_id,
                    task_id=task_id,
                    artifact_type="report",
                    storage_path=client_auth.storage_path,
                    reason="artifact.create",
                )
                seeded_pending_artifact = True
            await handle_generation_result(
                client,
                workflow_result.resolved_notebook_id,
                workflow_result.result,
                workflow_result.format_display,
                wait,
                json_output,
                ctx=ctx,
                binding=binding,
                started_at=started_at,
                cache_updates=_generation_cache_updates(
                    workflow_result.resolved_notebook_id,
                    seeded_pending_artifact=seeded_pending_artifact,
                ),
                route_reason=(
                    f"Start remote NotebookLM {workflow_result.format_display} generation "
                    "and optionally wait for completion."
                ),
            )

    return _run()


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
    return _run_audio_generation(
        ctx=ctx,
        client_auth=client_auth,
        notebook_id=notebook_id,
        description=description,
        audio_format=audio_format,
        audio_length=audio_length,
        language=language,
        source_ids=source_ids,
        wait=wait,
        max_retries=max_retries,
        json_output=json_output,
        compatibility_warning_command="notebooklm audio",
    )


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
    return _run_report_generation(
        ctx=ctx,
        client_auth=client_auth,
        notebook_id=notebook_id,
        description=description,
        report_format=report_format,
        source_ids=source_ids,
        language=language,
        append_instructions=append_instructions,
        wait=wait,
        max_retries=max_retries,
        json_output=json_output,
        compatibility_warning_command=(
            "notebooklm study-guide"
            if report_format == "study-guide"
            else "notebooklm summarize"
        ),
    )


@click.command("summarize")
@click.argument("description", default="", required=False)
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
def summarize_cmd(
    ctx,
    description,
    notebook_id,
    source_ids,
    language,
    append_instructions,
    wait,
    max_retries,
    json_output,
    client_auth,
):
    """Generate a briefing document."""
    return _run_report_generation(
        ctx=ctx,
        client_auth=client_auth,
        notebook_id=notebook_id,
        description=description,
        report_format="briefing-doc",
        source_ids=source_ids,
        language=language,
        append_instructions=append_instructions,
        wait=wait,
        max_retries=max_retries,
        json_output=json_output,
    )


@click.command("study-guide")
@click.argument("description", default="", required=False)
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
def study_guide_cmd(
    ctx,
    description,
    notebook_id,
    source_ids,
    language,
    append_instructions,
    wait,
    max_retries,
    json_output,
    client_auth,
):
    """Generate a study guide."""
    return _run_report_generation(
        ctx=ctx,
        client_auth=client_auth,
        notebook_id=notebook_id,
        description=description,
        report_format="study-guide",
        source_ids=source_ids,
        language=language,
        append_instructions=append_instructions,
        wait=wait,
        max_retries=max_retries,
        json_output=json_output,
    )


@click.command("audio")
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
def audio_cmd(
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
    """Generate an audio overview."""
    return _run_audio_generation(
        ctx=ctx,
        client_auth=client_auth,
        notebook_id=notebook_id,
        description=description,
        audio_format=audio_format,
        audio_length=audio_length,
        language=language,
        source_ids=source_ids,
        wait=wait,
        max_retries=max_retries,
        json_output=json_output,
    )


def register_generate_workflow_commands(cli) -> None:
    """Register normalized workflow roots that reuse the retained generate flows."""
    cli.add_command(summarize_cmd)
    cli.add_command(study_guide_cmd)
    cli.add_command(audio_cmd)
