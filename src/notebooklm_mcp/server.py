"""Server wiring for ``notebooklm_mcp``."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
import inspect
import logging
from typing import Any, AsyncIterator

from notebooklm import NotebookLMClient
from notebooklm.exceptions import ConfigurationError

from ._audit import AuditLog
from ._config import MCPConfig, load_config
from ._stats import Stats

logger = logging.getLogger("notebooklm_mcp")

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover - exercised in tests via fallback behavior
    FastMCP = None  # type: ignore[assignment]
    _FASTMCP_IMPORT_ERROR: Exception | None = exc
else:
    _FASTMCP_IMPORT_ERROR = None


@dataclass(slots=True)
class AppContext:
    """Typed application context shared via FastMCP lifespan."""

    client: NotebookLMClient
    semaphore: asyncio.Semaphore
    max_inflight: int
    stats: Stats = field(default_factory=Stats)
    audit: AuditLog | None = None
    cache: Any | None = None

    @asynccontextmanager
    async def acquire_slot(self) -> AsyncIterator[None]:
        """Acquire and release the shared concurrency semaphore."""
        async with self.semaphore:
            yield

    @property
    def inflight(self) -> int | None:
        """Best-effort count of currently in-flight operations."""
        current = getattr(self.semaphore, "_value", None)
        if isinstance(current, int):
            return max(self.max_inflight - current, 0)
        return None


def _startup_failure_message() -> str:
    return (
        "Failed to initialize NotebookLM client from storage. "
        "Run `notebooklm login` and verify NOTEBOOKLM_HOME/--storage configuration."
    )


@asynccontextmanager
async def app_lifespan(_server: Any) -> AsyncIterator[AppContext]:
    """Create and manage shared application context for MCP tool handlers."""
    runtime_config = _resolve_runtime_config(_server)
    max_inflight = runtime_config.max_inflight
    audit_log = _build_audit_log(runtime_config)

    try:
        client = await NotebookLMClient.from_storage()
    except Exception as exc:
        raise ConfigurationError(_startup_failure_message()) from exc

    async with client:
        yield AppContext(
            client=client,
            semaphore=asyncio.Semaphore(max_inflight),
            max_inflight=max_inflight,
            stats=Stats(),
            audit=audit_log,
            cache=None,
        )


def _package_version() -> str:
    try:
        return version("notebooklm-py")
    except PackageNotFoundError:
        return "0.0.0.dev0"


def _build_fastmcp_kwargs(config: MCPConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "name": "notebooklm-mcp",
        "lifespan": app_lifespan,
    }
    if FastMCP is None:
        return kwargs

    params = inspect.signature(FastMCP).parameters
    if "version" in params:
        kwargs["version"] = _package_version()
    if "stateless_http" in params:
        kwargs["stateless_http"] = True
    if "json_response" in params:
        kwargs["json_response"] = True
    if "host" in params:
        kwargs["host"] = config.host
    if "port" in params:
        kwargs["port"] = config.port
    return kwargs


def _register_components(server_instance: Any) -> None:
    # Import registration modules only after server construction to avoid
    # circular import issues while package globals initialize.
    from . import prompts, resources, tools

    registrars = (
        getattr(tools, "register_tools", None),
        getattr(resources, "register_resources", None),
        getattr(prompts, "register_prompts", None),
    )

    for registrar in registrars:
        if callable(registrar):
            registrar(server_instance)


def _resolve_runtime_config(server_instance: Any) -> MCPConfig:
    cfg = getattr(server_instance, "_notebooklm_mcp_config", None)
    if isinstance(cfg, MCPConfig):
        return cfg
    return load_config()


def _resolve_max_inflight(server_instance: Any) -> int:
    return _resolve_runtime_config(server_instance).max_inflight


def _build_audit_log(config: MCPConfig) -> AuditLog | None:
    if not config.audit_log_path:
        return None
    return AuditLog(file_path=config.audit_log_path)


def create_server(config: MCPConfig | None = None) -> Any | None:
    """Create and configure FastMCP server instance.

    Returns ``None`` when the optional MCP dependency is not available.
    """

    if FastMCP is None:
        logger.debug(
            "MCP runtime is unavailable. Install optional dependencies with "
            "`pip install \"notebooklm-py[mcp]\"`."
        )
        if _FASTMCP_IMPORT_ERROR is not None:
            logger.debug("FastMCP import failed: %s", _FASTMCP_IMPORT_ERROR)
        return None

    cfg = config or load_config()
    kwargs = _build_fastmcp_kwargs(cfg)
    logger.debug(
        "Creating FastMCP server with kwargs=%s (host=%s, port=%d, timeout_ms=%d, max_inflight=%d)",
        sorted(kwargs.keys()),
        cfg.host,
        cfg.port,
        cfg.timeout_ms,
        cfg.max_inflight,
    )
    server_instance = FastMCP(**kwargs)
    try:
        setattr(server_instance, "_notebooklm_mcp_config", cfg)
    except Exception:
        logger.debug("Unable to attach runtime config to server instance.")
    _register_components(server_instance)
    return server_instance


__all__ = ["AppContext", "app_lifespan", "create_server"]
