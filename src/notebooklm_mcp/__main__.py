"""Module entrypoint for ``python -m notebooklm_mcp``."""

from __future__ import annotations

import argparse
import inspect
import logging
from typing import Sequence

from . import __version__, server

logger = logging.getLogger("notebooklm_mcp")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notebooklm-mcp")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse"),
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE transport (default: 8000)",
    )
    return parser


def _run_server(selected_transport: str, host: str, port: int) -> None:
    run = getattr(server, "run", None)
    if not callable(run):
        raise AttributeError("Exported server object has no callable run() method.")

    params = inspect.signature(run).parameters
    kwargs: dict[str, object] = {}
    if "transport" in params:
        kwargs["transport"] = selected_transport
    if selected_transport == "sse":
        if "host" in params:
            kwargs["host"] = host
        if "port" in params:
            kwargs["port"] = port

    if kwargs:
        run(**kwargs)
    else:
        run()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the notebooklm-mcp server entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        logger.info("notebooklm-mcp %s", __version__)
        return 0

    if server is None:
        logger.error(
            "MCP runtime unavailable. Install optional dependency with "
            "`pip install \"notebooklm-py[mcp]\"`."
        )
        return 1

    try:
        _run_server(args.transport, args.host, args.port)
    except Exception as exc:
        logger.error("Failed to run notebooklm-mcp server: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
