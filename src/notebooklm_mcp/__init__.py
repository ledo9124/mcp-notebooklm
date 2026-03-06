"""NotebookLM MCP package bootstrap."""

from __future__ import annotations

import logging
import sys
from importlib.metadata import PackageNotFoundError, version

from ._config import MCPConfig, load_config
from .server import AppContext, app_lifespan, create_server

LOGGER_NAME = "notebooklm_mcp"



def configure_stderr_logging(level: int = logging.INFO) -> None:
    """Configure package logging to stderr only.

    STDIO MCP transport reserves stdout for JSON-RPC frames, so this package
    must never emit logs on stdout.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if any(isinstance(handler, logging.StreamHandler) and handler.stream is sys.stderr for handler in logger.handlers):
        logger.setLevel(level)
        logger.propagate = False
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


configure_stderr_logging()
logger = logging.getLogger(LOGGER_NAME)

CONFIG = load_config()
configure_stderr_logging(level=getattr(logging, CONFIG.log_level))

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
