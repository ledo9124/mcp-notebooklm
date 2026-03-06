"""Unit tests for notebooklm_mcp._config."""

from __future__ import annotations

import pytest

from notebooklm.exceptions import ConfigurationError
from notebooklm_mcp._config import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_MAX_INFLIGHT,
    DEFAULT_SOURCE_CONTENT_MAX_CHARS,
    DEFAULT_TIMEOUT_MS,
    ENV_CACHE_ENABLED,
    ENV_CACHE_TTL_SECONDS,
    ENV_DESTRUCTIVE_2PC,
    ENV_ENABLE_DESTRUCTIVE_TOOLS,
    ENV_LOG_LEVEL,
    ENV_MAX_INFLIGHT,
    ENV_NOTEBOOKLM_HOME,
    ENV_SOURCE_CONTENT_MAX_CHARS,
    ENV_TIMEOUT_MS,
    load_config,
)


def test_load_config_defaults() -> None:
    config = load_config({})

    assert config.enable_destructive_tools is False
    assert config.destructive_2pc is False
    assert config.log_level == "INFO"
    assert config.max_inflight == DEFAULT_MAX_INFLIGHT
    assert config.timeout_ms == DEFAULT_TIMEOUT_MS
    assert config.source_content_max_chars == DEFAULT_SOURCE_CONTENT_MAX_CHARS
    assert config.cache_enabled is False
    assert config.cache_ttl_seconds == DEFAULT_CACHE_TTL_SECONDS
    assert config.audit_log_path is None
    assert config.notebooklm_home is None


def test_load_config_parses_overrides() -> None:
    config = load_config(
        {
            ENV_ENABLE_DESTRUCTIVE_TOOLS: "TRUE",
            ENV_DESTRUCTIVE_2PC: "yes",
            ENV_LOG_LEVEL: "debug",
            ENV_MAX_INFLIGHT: "11",
            ENV_TIMEOUT_MS: "45000",
            ENV_SOURCE_CONTENT_MAX_CHARS: "70000",
            ENV_CACHE_ENABLED: "1",
            ENV_CACHE_TTL_SECONDS: "1200",
            ENV_NOTEBOOKLM_HOME: "/tmp/notebooklm-home",
        }
    )

    assert config.enable_destructive_tools is True
    assert config.destructive_2pc is True
    assert config.log_level == "DEBUG"
    assert config.max_inflight == 11
    assert config.timeout_ms == 45_000
    assert config.source_content_max_chars == 70_000
    assert config.cache_enabled is True
    assert config.cache_ttl_seconds == 1200
    assert config.notebooklm_home == "/tmp/notebooklm-home"


@pytest.mark.parametrize("value", ["", "maybe", "truish"])
def test_invalid_bool_raises(value: str) -> None:
    with pytest.raises(ConfigurationError, match=ENV_ENABLE_DESTRUCTIVE_TOOLS):
        load_config({ENV_ENABLE_DESTRUCTIVE_TOOLS: value})


@pytest.mark.parametrize(
    ("var_name", "value"),
    [
        (ENV_MAX_INFLIGHT, "0"),
        (ENV_TIMEOUT_MS, "0"),
        (ENV_SOURCE_CONTENT_MAX_CHARS, "-1"),
        (ENV_CACHE_TTL_SECONDS, "0"),
    ],
)
def test_invalid_integer_bounds_raise(var_name: str, value: str) -> None:
    with pytest.raises(ConfigurationError, match=var_name):
        load_config({var_name: value})


@pytest.mark.parametrize("var_name", [ENV_MAX_INFLIGHT, ENV_TIMEOUT_MS, ENV_CACHE_TTL_SECONDS])
def test_invalid_integer_format_raises(var_name: str) -> None:
    with pytest.raises(ConfigurationError, match=var_name):
        load_config({var_name: "not-an-int"})


def test_invalid_log_level_raises() -> None:
    with pytest.raises(ConfigurationError, match=ENV_LOG_LEVEL):
        load_config({ENV_LOG_LEVEL: "verbose"})


def test_destructive_2pc_requires_destructive_tools() -> None:
    with pytest.raises(ConfigurationError, match=ENV_DESTRUCTIVE_2PC):
        load_config(
            {
                ENV_ENABLE_DESTRUCTIVE_TOOLS: "false",
                ENV_DESTRUCTIVE_2PC: "true",
            }
        )

