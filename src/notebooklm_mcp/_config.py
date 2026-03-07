"""Environment variable configuration for ``notebooklm_mcp``.

Supported variables:
- NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS (bool, default false)
- NOTEBOOKLM_MCP_DESTRUCTIVE_2PC (bool, default false)
- NOTEBOOKLM_MCP_LOG_LEVEL (str, default INFO)
- NOTEBOOKLM_MCP_HOST (str, default 127.0.0.1)
- NOTEBOOKLM_MCP_PORT (int, default 8764)
- NOTEBOOKLM_MCP_MAX_INFLIGHT (int, default 5)
- NOTEBOOKLM_MCP_TIMEOUT_MS (int, default 30000)
- NOTEBOOKLM_MCP_SOURCE_CONTENT_MAX_CHARS (int, default 50000)
- NOTEBOOKLM_MCP_AUDIT_LOG_PATH (str, optional)
- NOTEBOOKLM_MCP_CACHE_ENABLED (bool, default false)
- NOTEBOOKLM_MCP_CACHE_TTL_SECONDS (int, default 300)
- NOTEBOOKLM_HOME (str, optional)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from notebooklm.exceptions import ConfigurationError

logger = logging.getLogger("notebooklm_mcp.config")

ENV_ENABLE_DESTRUCTIVE_TOOLS = "NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS"
ENV_DESTRUCTIVE_2PC = "NOTEBOOKLM_MCP_DESTRUCTIVE_2PC"
ENV_LOG_LEVEL = "NOTEBOOKLM_MCP_LOG_LEVEL"
ENV_HOST = "NOTEBOOKLM_MCP_HOST"
ENV_PORT = "NOTEBOOKLM_MCP_PORT"
ENV_MAX_INFLIGHT = "NOTEBOOKLM_MCP_MAX_INFLIGHT"
ENV_TIMEOUT_MS = "NOTEBOOKLM_MCP_TIMEOUT_MS"
ENV_SOURCE_CONTENT_MAX_CHARS = "NOTEBOOKLM_MCP_SOURCE_CONTENT_MAX_CHARS"
ENV_AUDIT_LOG_PATH = "NOTEBOOKLM_MCP_AUDIT_LOG_PATH"
ENV_CACHE_ENABLED = "NOTEBOOKLM_MCP_CACHE_ENABLED"
ENV_CACHE_TTL_SECONDS = "NOTEBOOKLM_MCP_CACHE_TTL_SECONDS"
ENV_NOTEBOOKLM_HOME = "NOTEBOOKLM_HOME"

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8764
DEFAULT_MAX_INFLIGHT = 5
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_SOURCE_CONTENT_MAX_CHARS = 50_000
DEFAULT_CACHE_TTL_SECONDS = 300

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_ALLOWED_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"})


@dataclass(frozen=True, slots=True)
class MCPConfig:
    """Validated runtime configuration for notebooklm-mcp."""

    enable_destructive_tools: bool = False
    destructive_2pc: bool = False
    log_level: str = DEFAULT_LOG_LEVEL
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    max_inflight: int = DEFAULT_MAX_INFLIGHT
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    source_content_max_chars: int = DEFAULT_SOURCE_CONTENT_MAX_CHARS
    audit_log_path: str | None = None
    cache_enabled: bool = False
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    notebooklm_home: str | None = None


def _parse_bool(
    environ: Mapping[str, str], var_name: str, default: bool
) -> bool:
    raw = environ.get(var_name)
    if raw is None:
        return default

    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False

    raise ConfigurationError(
        f"{var_name} must be a boolean string "
        f"({sorted(_TRUE_VALUES | _FALSE_VALUES)}), got: {raw!r}"
    )


def _parse_int(
    environ: Mapping[str, str],
    var_name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = environ.get(var_name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ConfigurationError(f"{var_name} must be an integer, got: {raw!r}") from exc

    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{var_name} must be >= {minimum}, got: {value}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{var_name} must be <= {maximum}, got: {value}")

    return value


def _parse_log_level(environ: Mapping[str, str]) -> str:
    raw = environ.get(ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL).strip().upper()
    if raw not in _ALLOWED_LOG_LEVELS:
        raise ConfigurationError(
            f"{ENV_LOG_LEVEL} must be one of {sorted(_ALLOWED_LOG_LEVELS)}, got: {raw!r}"
        )
    return raw


def _parse_non_empty_text(
    environ: Mapping[str, str],
    var_name: str,
    default: str,
) -> str:
    raw = environ.get(var_name)
    if raw is None:
        return default

    value = raw.strip()
    if not value:
        raise ConfigurationError(f"{var_name} must be a non-empty string")

    return value


def load_config(environ: Mapping[str, str] | None = None) -> MCPConfig:
    """Load and validate notebooklm-mcp configuration."""
    env = os.environ if environ is None else environ

    config = MCPConfig(
        enable_destructive_tools=_parse_bool(env, ENV_ENABLE_DESTRUCTIVE_TOOLS, False),
        destructive_2pc=_parse_bool(env, ENV_DESTRUCTIVE_2PC, False),
        log_level=_parse_log_level(env),
        host=_parse_non_empty_text(env, ENV_HOST, DEFAULT_HOST),
        port=_parse_int(
            env,
            ENV_PORT,
            DEFAULT_PORT,
            minimum=1,
            maximum=65_535,
        ),
        max_inflight=_parse_int(
            env,
            ENV_MAX_INFLIGHT,
            DEFAULT_MAX_INFLIGHT,
            minimum=1,
        ),
        timeout_ms=_parse_int(
            env,
            ENV_TIMEOUT_MS,
            DEFAULT_TIMEOUT_MS,
            minimum=1,
        ),
        source_content_max_chars=_parse_int(
            env,
            ENV_SOURCE_CONTENT_MAX_CHARS,
            DEFAULT_SOURCE_CONTENT_MAX_CHARS,
            minimum=1,
        ),
        audit_log_path=(env.get(ENV_AUDIT_LOG_PATH) or "").strip() or None,
        cache_enabled=_parse_bool(env, ENV_CACHE_ENABLED, False),
        cache_ttl_seconds=_parse_int(
            env,
            ENV_CACHE_TTL_SECONDS,
            DEFAULT_CACHE_TTL_SECONDS,
            minimum=1,
        ),
        notebooklm_home=(env.get(ENV_NOTEBOOKLM_HOME) or "").strip() or None,
    )

    if config.destructive_2pc and not config.enable_destructive_tools:
        raise ConfigurationError(
            f"{ENV_DESTRUCTIVE_2PC}=true requires {ENV_ENABLE_DESTRUCTIVE_TOOLS}=true"
        )

    logger.debug(
        "Loaded MCP config: destructive_tools=%s destructive_2pc=%s host=%s port=%d cache_enabled=%s "
        "max_inflight=%d timeout_ms=%d source_content_max_chars=%d audit_log_path_set=%s",
        config.enable_destructive_tools,
        config.destructive_2pc,
        config.host,
        config.port,
        config.cache_enabled,
        config.max_inflight,
        config.timeout_ms,
        config.source_content_max_chars,
        bool(config.audit_log_path),
    )

    return config
