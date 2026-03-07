"""Module entrypoint for ``python -m notebooklm_mcp``."""

from __future__ import annotations

import inspect
import logging
import os
import signal
import sys
from dataclasses import replace
from typing import Sequence

import click

from . import __version__, configure_stderr_logging, create_server, load_config

logger = logging.getLogger("notebooklm_mcp")


def _resolve_transport(
    transport: str, *, http: bool, sse: bool
) -> str:
    """Resolve the effective transport from flags and --transport."""
    shortcuts = [name for flag, name in ((http, "streamable-http"), (sse, "sse")) if flag]

    if len(shortcuts) > 1:
        raise click.UsageError("Use only one of --http or --sse.")
    if shortcuts and transport != "stdio":
        raise click.UsageError(
            f"Use either --transport or --{shortcuts[0].split('-')[0]}, not both."
        )
    if shortcuts:
        return shortcuts[0]
    return transport


def _install_sigint_handler() -> None:
    """Install a SIGINT handler that exits immediately.

    The default Python ``KeyboardInterrupt`` mechanism cannot cleanly unwind
    blocking stdin reads used by the stdio transport.  A second Ctrl-C during
    thread shutdown causes the fatal "could not acquire lock" error.  Using
    ``os._exit`` avoids thread-join issues entirely.
    """
    def _handler(signum: int, frame: object) -> None:  # noqa: ANN401
        os._exit(0)

    try:
        signal.signal(signal.SIGINT, _handler)
    except (OSError, ValueError):
        pass


def _run_server(server_instance: object, selected_transport: str) -> None:
    run = getattr(server_instance, "run", None)
    if not callable(run):
        raise AttributeError("Exported server object has no callable run() method.")

    _install_sigint_handler()

    params = inspect.signature(run).parameters
    kwargs: dict[str, object] = {}
    if "transport" in params:
        kwargs["transport"] = selected_transport

    if kwargs:
        run(**kwargs)
    else:
        run()


def _log_startup_banner(
    transport: str, host: str, port: int
) -> None:
    """Emit a concise startup banner to stderr."""
    if transport == "stdio":
        logger.info("NotebookLM MCP \u2022 stdio")
    elif transport == "streamable-http":
        url = f"http://{host}:{port}/mcp"
        logger.info("NotebookLM MCP \u2022 streamable-http \u2022 %s", url)
    elif transport == "sse":
        url = f"http://{host}:{port}/sse"
        logger.info("NotebookLM MCP \u2022 sse \u2022 %s", url)
    else:
        logger.info("NotebookLM MCP \u2022 %s", transport)


def _serve(
    transport: str,
    http: bool,
    sse: bool,
    host: str | None,
    port: int | None,
    verbose: bool,
) -> int:
    """Shared implementation for the ``serve`` subcommand and root fallback."""
    effective_transport = _resolve_transport(transport, http=http, sse=sse)

    if verbose:
        configure_stderr_logging(level=logging.DEBUG, verbose=True)

    try:
        config = load_config()
        if host is not None:
            config = replace(config, host=host)
        if port is not None:
            config = replace(config, port=port)

        if not verbose:
            level = getattr(logging, config.log_level)
            configure_stderr_logging(level=level, verbose=(level <= logging.DEBUG))

        _log_startup_banner(effective_transport, config.host, config.port)

        server_instance = create_server(config)
        if server_instance is None:
            logger.error(
                "MCP runtime unavailable. Install optional dependency with "
                '`pip install "notebooklm-py[mcp]"`.'
            )
            return 1

        _run_server(server_instance, effective_transport)
    except KeyboardInterrupt:
        logger.debug("Interrupted")
        return 0
    except click.UsageError:
        raise
    except Exception as exc:
        logger.error("Failed to run notebooklm-mcp server: %s", exc)
        return 1
    return 0


_serve_options = [
    click.option(
        "--transport",
        type=click.Choice(["stdio", "sse", "streamable-http"]),
        default="stdio",
        help="Transport mode (default: stdio).",
    ),
    click.option(
        "--http", "http", is_flag=True, default=False,
        help="Shortcut for --transport streamable-http.",
    ),
    click.option(
        "--sse", "sse", is_flag=True, default=False,
        help="Shortcut for --transport sse.",
    ),
    click.option(
        "--host", default=None,
        help="Host for HTTP transports (default: 127.0.0.1).",
    ),
    click.option(
        "--port", type=int, default=None,
        help="Port for HTTP transports (default: 8764).",
    ),
    click.option(
        "-v", "--verbose", is_flag=True, default=False,
        help="Enable DEBUG logging with timestamps.",
    ),
]


def _apply_serve_options(fn):  # noqa: ANN001, ANN202
    for decorator in reversed(_serve_options):
        fn = decorator(fn)
    return fn


@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="notebooklm-mcp")
@_apply_serve_options
@click.pass_context
def cli(ctx, **kwargs):  # noqa: ANN001, ANN003
    """NotebookLM MCP server."""
    if ctx.invoked_subcommand is None:
        ctx.exit(_serve(**kwargs))


@cli.command()
@_apply_serve_options
def serve(**kwargs):  # noqa: ANN003
    """Start the MCP server.

    \b
    Examples:
      notebooklm-mcp serve              # stdio (default)
      notebooklm-mcp serve --http       # streamable-http on 127.0.0.1:8764
      notebooklm-mcp serve --sse        # legacy SSE
      notebooklm-mcp serve -v           # verbose debug logging
    """
    raise SystemExit(_serve(**kwargs))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the notebooklm-mcp server entrypoint."""
    try:
        result = cli.main(
            args=list(argv) if argv is not None else None,
            prog_name="notebooklm-mcp",
            standalone_mode=False,
        )
        if isinstance(result, int):
            return result
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    except (KeyboardInterrupt, click.exceptions.Abort):
        return 0
    except click.ClickException as exc:
        exc.show(file=sys.stderr)
        return exc.exit_code
    except click.exceptions.Exit as exc:
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
