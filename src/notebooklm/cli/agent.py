"""Experimental natural-language routing command."""

from __future__ import annotations

import re
from typing import Any

import click

from ..contracts import Intent
from ..local.db import connect_db
from ..local.repositories import NotebookRepository
from ..profiles.manager import ProfileManager
from ..router.classify import classify_request
from ..router.execute import AgentExecutionPlan, build_execution_plan
from ..router.freshness import (
    CacheModeViolationError,
    MetadataScope,
    collect_freshness_snapshot,
    decide_cache_mode,
)
from ..router.resolve import NotebookResolutionCandidate, resolve_notebook_target
from ..router.structured import match_structured_command
from .helpers import console, get_current_notebook

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_RESEARCH_ID_RE = re.compile(r"\b(?:r|research)_[a-z0-9_-]+\b", re.IGNORECASE)


@click.command("agent")
@click.argument("request")
@click.option(
    "-n",
    "--notebook",
    "explicit_notebook_id",
    default=None,
    help="Optional notebook selector to feed into NL routing before execution.",
)
@click.option(
    "--cache-mode",
    type=click.Choice(["smart", "refresh", "offline", "network"], case_sensitive=False),
    default="smart",
    show_default=True,
    help="Evaluate the routed request under one cache mode before dispatch.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Pass --json through when the routed command supports it.",
)
@click.option(
    "--wait/--no-wait",
    "wait_for_completion",
    default=None,
    help="Override wait behavior for routed commands that support waiting.",
)
@click.pass_context
def agent(
    ctx: click.Context,
    request: str,
    explicit_notebook_id: str | None,
    cache_mode: str,
    json_output: bool,
    wait_for_completion: bool | None,
) -> Any:
    """Route one natural-language request onto an existing structured workflow."""

    root_ctx = ctx.find_root()
    root_command = root_ctx.command

    structured_match = match_structured_command(request, root=root_command)
    if structured_match is not None:
        if cache_mode.casefold() != "smart":
            raise click.ClickException(
                "`agent --cache-mode` only applies to natural-language routing. "
                "Pass cache-related flags directly on the structured command instead."
            )
        argv = list(structured_match.argv)
        argv = _append_flag(
            root_command,
            structured_match.command_path,
            argv,
            flag="--json",
            enabled=json_output,
        )
        argv = _append_notebook_option(
            root_command,
            structured_match.command_path,
            argv,
            notebook_id=explicit_notebook_id,
        )
        argv = _append_wait_flag(
            root_command,
            structured_match.command_path,
            argv,
            wait_for_completion=wait_for_completion,
        )
        if not json_output:
            console.print(
                "[dim]Structured command wins: "
                f"{' '.join(structured_match.command_path)}[/dim]"
            )
        return _invoke_root_command(root_ctx, argv)

    with connect_db() as connection:
        profile_id = _active_profile_id(connection)
        current_notebook_id = get_current_notebook()
        cached_candidates = _cached_notebook_candidates(connection, profile_id)
        classification = classify_request(request)
        resolution = resolve_notebook_target(
            request=request,
            explicit_notebook_id=explicit_notebook_id,
            current_notebook_id=current_notebook_id,
            cached_candidates=cached_candidates,
        )
        metadata_scope = _metadata_scope_for_request(
            intent=classification.intent,
            request=request,
            resolved_notebook_id=resolution.notebook_id,
        )
        freshness = collect_freshness_snapshot(
            connection,
            profile_id=profile_id,
            notebook_id=resolution.notebook_id,
        )

    try:
        plan = build_execution_plan(
            request=request,
            classification=classification,
            resolution=resolution,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    decision = None
    if classification.intent is not Intent.LOCAL_METADATA or metadata_scope is not None:
        try:
            decision = decide_cache_mode(
                classification.intent,
                snapshot=freshness,
                cache_mode=cache_mode,
                metadata_scope=metadata_scope,
            )
        except CacheModeViolationError as exc:
            raise click.ClickException(str(exc)) from exc

    argv, command_path = _argv_for_plan(
        root_command,
        plan,
        json_output=json_output,
        wait_for_completion=wait_for_completion,
        should_refresh_metadata=bool(decision and decision.should_sync_metadata),
    )
    if not json_output:
        console.print(
            "[dim]Routed "
            f"{classification.intent.value} request to {' '.join(command_path)}[/dim]"
        )
    return _invoke_root_command(root_ctx, argv)


def _active_profile_id(connection) -> str:
    manager = ProfileManager(connection)
    active = manager.get_active_profile()
    if active is not None:
        return active.profile_id
    profiles = manager.list_profiles()
    if len(profiles) == 1:
        return profiles[0].profile_id
    return "default"


def _cached_notebook_candidates(connection, profile_id: str) -> list[NotebookResolutionCandidate]:
    repository = NotebookRepository(connection)
    candidates: list[NotebookResolutionCandidate] = []
    for record in repository.list_for_profile(profile_id):
        if record.tombstoned_at is not None:
            continue
        candidates.append(
            NotebookResolutionCandidate(
                notebook_id=record.notebook_id,
                title=record.title,
                normalized_title=record.normalized_title,
            )
        )
    return candidates


def _metadata_scope_for_request(
    *,
    intent: Intent,
    request: str,
    resolved_notebook_id: str | None,
) -> MetadataScope | None:
    if intent is not Intent.LOCAL_METADATA:
        return None

    tokens = set(_TOKEN_RE.findall(request.casefold()))
    if {"source", "sources"} & tokens and resolved_notebook_id is None:
        return None
    if resolved_notebook_id is not None and (
        {"show", "source", "sources", "guide"} & tokens or "current" in tokens
    ):
        return "notebook_detail"
    return "notebook_index"


def _argv_for_plan(
    root_command: click.Group,
    plan: AgentExecutionPlan,
    *,
    json_output: bool,
    wait_for_completion: bool | None,
    should_refresh_metadata: bool,
) -> tuple[list[str], tuple[str, ...]]:
    if plan.command_name == "notebook.list":
        command_path = ("notebook", "list")
        argv = list(command_path)
        if should_refresh_metadata:
            argv = _append_flag(root_command, command_path, argv, flag="--refresh", enabled=True)
    elif plan.command_name == "source.list":
        command_path = ("source", "list")
        argv = list(command_path)
        if plan.notebook_id is not None:
            argv.extend(["--notebook", plan.notebook_id])
        if should_refresh_metadata:
            argv = _append_flag(root_command, command_path, argv, flag="--refresh", enabled=True)
    elif plan.command_name == "sync.notebooks":
        command_path = ("sync", "notebooks")
        argv = list(command_path)
        if bool(plan.arguments.get("sync_all", False)):
            argv.append("--all")
        elif plan.notebook_id is not None:
            argv.extend(["--notebook", plan.notebook_id])
    elif plan.command_name == "ask":
        command_path = ("ask",)
        argv = list(command_path)
        if plan.notebook_id is not None:
            argv.extend(["--notebook", plan.notebook_id])
        argv.append(str(plan.arguments["question"]))
    elif plan.command_name == "overview":
        command_path = ("overview",)
        argv = list(command_path)
        if plan.notebook_id is not None:
            argv.extend(["--notebook", plan.notebook_id])
    elif plan.command_name == "summarize":
        command_path = ("summarize",)
        argv = list(command_path)
        if plan.notebook_id is not None:
            argv.extend(["--notebook", plan.notebook_id])
        argv.append(str(plan.arguments["description"]))
    elif plan.command_name == "study-guide":
        command_path = ("study-guide",)
        argv = list(command_path)
        if plan.notebook_id is not None:
            argv.extend(["--notebook", plan.notebook_id])
        argv.append(str(plan.arguments["description"]))
    elif plan.command_name == "audio":
        command_path = ("audio",)
        argv = list(command_path)
        if plan.notebook_id is not None:
            argv.extend(["--notebook", plan.notebook_id])
        argv.append(str(plan.arguments["description"]))
    elif plan.command_name == "research.start":
        command_path = ("research", "start")
        argv = list(command_path)
        if plan.notebook_id is not None:
            argv.extend(["--notebook", plan.notebook_id])
        argv.extend(["--from", str(plan.arguments["search_source"])])
        argv.extend(["--mode", str(plan.arguments["mode"])])
        argv.append(str(plan.arguments["query"]))
    elif plan.command_name == "research.wait":
        command_path = ("research", "wait")
        argv = list(command_path)
        if plan.notebook_id is not None:
            argv.extend(["--notebook", plan.notebook_id])
        research_id = _extract_research_id(plan.request_text)
        if research_id is not None:
            argv.append(research_id)
        elif plan.notebook_id is None:
            raise click.ClickException(
                "research.wait routing requires either a research id in the request "
                "or a resolved notebook target."
            )
    elif plan.command_name == "research.import":
        command_path = ("research", "import")
        research_id = _extract_research_id(plan.request_text)
        if research_id is None:
            raise click.ClickException(
                "research.import routing requires an explicit research id in the request, "
                "for example 'import research results r_123'."
            )
        argv = list(command_path)
        if _wants_research_import_preview(plan.request_text):
            argv.append("--dry-run")
        argv.append(research_id)
    elif plan.command_name == "metadata.query":
        raise click.ClickException(
            "This LOCAL_METADATA request does not map to an executable structured workflow yet. "
            "Use 'notebooklm route explain ...' or an explicit structured command."
        )
    else:
        raise click.ClickException(f"Unsupported routed command target: {plan.command_name}")

    argv = _append_flag(root_command, command_path, argv, flag="--json", enabled=json_output)
    argv = _append_wait_flag(
        root_command,
        command_path,
        argv,
        wait_for_completion=wait_for_completion,
    )
    return argv, command_path


def _append_flag(
    root_command: click.Group,
    command_path: tuple[str, ...],
    argv: list[str],
    *,
    flag: str,
    enabled: bool,
) -> list[str]:
    if not enabled:
        return argv
    if flag in argv:
        return argv
    if not _command_accepts_flag(root_command, command_path, flag):
        raise click.ClickException(
            f"{' '.join(command_path)} does not support {flag}; route the request explicitly instead."
        )
    return [*argv, flag]


def _append_notebook_option(
    root_command: click.Group,
    command_path: tuple[str, ...],
    argv: list[str],
    *,
    notebook_id: str | None,
) -> list[str]:
    if notebook_id is None:
        return argv
    if "--notebook" in argv or "-n" in argv:
        return argv
    if not _command_accepts_flag(root_command, command_path, "--notebook"):
        return argv
    return [*argv, "--notebook", notebook_id]


def _append_wait_flag(
    root_command: click.Group,
    command_path: tuple[str, ...],
    argv: list[str],
    *,
    wait_for_completion: bool | None,
) -> list[str]:
    if wait_for_completion is None:
        return argv
    if "--wait" in argv or "--no-wait" in argv:
        return argv
    if not _command_accepts_flag(root_command, command_path, "--wait"):
        raise click.ClickException(f"{' '.join(command_path)} does not support wait overrides.")
    return [*argv, "--wait" if wait_for_completion else "--no-wait"]


def _command_accepts_flag(
    root_command: click.Group,
    command_path: tuple[str, ...],
    flag: str,
) -> bool:
    command = _resolve_command(root_command, command_path)
    for param in command.params:
        if isinstance(param, click.Option) and flag in (*param.opts, *param.secondary_opts):
            return True
    return False


def _resolve_command(root_command: click.Group, command_path: tuple[str, ...]) -> click.Command:
    command: click.Command = root_command
    ctx = click.Context(root_command, info_name=root_command.name or "notebooklm")
    for name in command_path:
        if not isinstance(command, click.Group):
            raise click.ClickException(f"Invalid routed command path: {' '.join(command_path)}")
        next_command = command.get_command(ctx, name)
        if next_command is None:
            raise click.ClickException(f"Unknown routed command path: {' '.join(command_path)}")
        command = next_command
        ctx = click.Context(command, info_name=name, parent=ctx)
    return command


def _root_prefix_argv(root_ctx: click.Context) -> list[str]:
    argv: list[str] = []
    verbose = int(root_ctx.params.get("verbose") or 0)
    argv.extend(["-v"] * max(0, verbose))

    storage_path = root_ctx.params.get("storage")
    if storage_path:
        argv.extend(["--storage", str(storage_path)])
    return argv


def _invoke_root_command(root_ctx: click.Context, argv: list[str]) -> Any:
    return root_ctx.command.main(
        args=[*_root_prefix_argv(root_ctx), *argv],
        prog_name=root_ctx.info_name or "notebooklm",
        standalone_mode=False,
    )


def _extract_research_id(request: str) -> str | None:
    match = _RESEARCH_ID_RE.search(request)
    if match is None:
        return None
    return match.group(0)


def _wants_research_import_preview(request: str) -> bool:
    normalized = request.casefold()
    return "dry run" in normalized or "dry-run" in normalized or "preview" in normalized


__all__ = ["agent"]
