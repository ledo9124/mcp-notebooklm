"""NotebookLM MCP package bootstrap."""

from __future__ import annotations

import logging
import sys
from importlib.metadata import PackageNotFoundError, version

from ._config import MCPConfig, load_config
from .server import AppContext, app_lifespan, create_server

LOGGER_NAME = "notebooklm_mcp"

DEFAULT_LOG_FORMAT = "%(message)s"
VERBOSE_LOG_FORMAT = "[%(asctime)s] %(levelname)-8s %(name)s %(message)s"


def configure_stderr_logging(
    level: int = logging.INFO, *, verbose: bool = False
) -> None:
    """Configure package logging to stderr only.

    STDIO MCP transport reserves stdout for JSON-RPC frames, so this package
    must never emit logs on stdout.

    Args:
        level: Logging level (e.g. ``logging.INFO``).
        verbose: When *True*, use a detailed formatter with timestamps and
            logger names; otherwise use a minimal message-only format.
    """
    logger = logging.getLogger(LOGGER_NAME)

    handler = next(
        (
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
        ),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
        logger.addHandler(handler)

    handler.setFormatter(
        logging.Formatter(
            VERBOSE_LOG_FORMAT if verbose else DEFAULT_LOG_FORMAT,
            datefmt="%H:%M:%S",
        )
    )
    logger.setLevel(level)
    logger.propagate = False


configure_stderr_logging()
logger = logging.getLogger(LOGGER_NAME)

CONFIG = load_config()
_cfg_level = getattr(logging, CONFIG.log_level)
configure_stderr_logging(level=_cfg_level, verbose=(_cfg_level <= logging.DEBUG))

try:
    __version__ = version("notebooklm-py")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

server = create_server(CONFIG)



def main() -> int:
    """Run the notebooklm-mcp module entrypoint."""
    from .__main__ import main as module_main

    return module_main()


__all__ = [
    "__version__",
    "AppContext",
    "CONFIG",
    "MCPConfig",
    "app_lifespan",
    "configure_stderr_logging",
    "create_server",
    "load_config",
    "logger",
    "main",
    "server",
]
