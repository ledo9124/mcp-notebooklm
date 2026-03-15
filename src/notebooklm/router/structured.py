"""Helpers for giving explicit CLI commands precedence over NL routing."""

from __future__ import annotations

from dataclasses import dataclass
import shlex

import click


@dataclass(frozen=True)
class StructuredCommandMatch:
    """One request that cleanly parses as an existing structured CLI command."""

    command_path: tuple[str, ...]
    argv: tuple[str, ...]
    arguments: tuple[str, ...]


def match_structured_command(
    request: str,
    *,
    root: click.Group | None = None,
) -> StructuredCommandMatch | None:
    """Return the structured CLI match when a request parses cleanly."""
    tokens = _tokenize_request(request)
    if not tokens:
        return None

    cli_root = root or _load_cli_root()
    return _match_group(
        cli_root,
        info_name=cli_root.name or "notebooklm",
        args=tokens,
        full_argv=tokens,
        path=(),
        parent=None,
    )


def is_structured_command_request(
    request: str,
    *,
    root: click.Group | None = None,
) -> bool:
    """Return True when the request is already a valid structured CLI command."""
    return match_structured_command(request, root=root) is not None


def _tokenize_request(request: str) -> list[str]:
    try:
        tokens = shlex.split(request)
    except ValueError:
        return []

    if tokens and tokens[0] == "notebooklm":
        return tokens[1:]
    return tokens


def _load_cli_root() -> click.Group:
    from notebooklm.notebooklm_cli import cli

    return cli


def _match_group(
    group: click.Group,
    *,
    info_name: str,
    args: list[str],
    full_argv: list[str],
    path: tuple[str, ...],
    parent: click.Context | None,
) -> StructuredCommandMatch | None:
    try:
        ctx = group.make_context(
            info_name,
            list(args),
            parent=parent,
            resilient_parsing=False,
        )
    except (click.ClickException, click.exceptions.Exit):
        return None

    protected = list(_protected_args(ctx))
    if not protected:
        if not group.invoke_without_command or not path:
            return None
        return StructuredCommandMatch(
            command_path=path,
            argv=tuple(full_argv),
            arguments=tuple(args),
        )

    command_name = protected[0]
    command = group.get_command(ctx, command_name)
    if command is None:
        return None

    component = _visible_path_component(group, command_name, command)
    next_path = path + ((component,) if component is not None else ())
    remaining = list(ctx.args)

    if isinstance(command, click.Group):
        return _match_group(
            command,
            info_name=command_name,
            args=remaining,
            full_argv=full_argv,
            path=next_path,
            parent=ctx,
        )

    try:
        command.make_context(
            command_name,
            list(remaining),
            parent=ctx,
            resilient_parsing=False,
        )
    except (click.ClickException, click.exceptions.Exit):
        return None

    return StructuredCommandMatch(
        command_path=next_path,
        argv=tuple(full_argv),
        arguments=tuple(remaining),
    )


def _visible_path_component(
    group: click.Group,
    command_name: str,
    command: click.Command,
) -> str | None:
    default_name = getattr(group, "default_command_name", None)
    if command.hidden and command_name == default_name:
        return None
    return command_name


def _protected_args(ctx: click.Context) -> list[str]:
    raw = getattr(ctx, "_protected_args", None)
    if raw is not None:
        return list(raw)
    return list(ctx.protected_args)


__all__ = [
    "StructuredCommandMatch",
    "is_structured_command_request",
    "match_structured_command",
]
