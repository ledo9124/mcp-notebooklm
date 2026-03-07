"""Unit tests for notebooklm_mcp.__main__."""

from __future__ import annotations

import importlib

import pytest

from notebooklm_mcp._config import MCPConfig

mcp_main = importlib.import_module("notebooklm_mcp.__main__")


def test_main_version_flag_returns_zero() -> None:
    assert mcp_main.main(["--version"]) == 0


def test_main_defaults_to_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeServer:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    monkeypatch.setattr(mcp_main, "load_config", lambda: MCPConfig())
    monkeypatch.setattr(mcp_main, "create_server", lambda _cfg: _FakeServer())

    result = mcp_main.main([])
    assert result == 0
    assert captured["transport"] == "stdio"


def test_main_serve_subcommand_defaults_to_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeServer:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    monkeypatch.setattr(mcp_main, "load_config", lambda: MCPConfig())
    monkeypatch.setattr(mcp_main, "create_server", lambda _cfg: _FakeServer())

    result = mcp_main.main(["serve"])
    assert result == 0
    assert captured["transport"] == "stdio"


def test_main_http_flag_selects_streamable_http(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeServer:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    monkeypatch.setattr(mcp_main, "load_config", lambda: MCPConfig())
    monkeypatch.setattr(mcp_main, "create_server", lambda _cfg: _FakeServer())

    result = mcp_main.main(["serve", "--http"])
    assert result == 0
    assert captured["transport"] == "streamable-http"


def test_main_sse_flag_selects_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeServer:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    monkeypatch.setattr(mcp_main, "load_config", lambda: MCPConfig())
    monkeypatch.setattr(mcp_main, "create_server", lambda _cfg: _FakeServer())

    result = mcp_main.main(["serve", "--sse"])
    assert result == 0
    assert captured["transport"] == "sse"


def test_main_returns_error_when_server_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_main, "load_config", lambda: MCPConfig())
    monkeypatch.setattr(mcp_main, "create_server", lambda _cfg: None)

    assert mcp_main.main([]) == 1


def test_main_creates_fresh_server_with_cli_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    base_config = MCPConfig(host="127.0.0.1", port=8764)

    class _FakeServer:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    def _fake_create_server(cfg: MCPConfig) -> _FakeServer:
        captured["config"] = cfg
        return _FakeServer()

    monkeypatch.setattr(mcp_main, "load_config", lambda: base_config)
    monkeypatch.setattr(mcp_main, "create_server", _fake_create_server)

    result = mcp_main.main(["serve", "--transport", "sse", "--host", "0.0.0.0", "--port", "9101"])
    assert result == 0
    assert captured["transport"] == "sse"
    assert isinstance(captured["config"], MCPConfig)
    assert captured["config"] is not base_config
    assert captured["config"].host == "0.0.0.0"
    assert captured["config"].port == 9101


def test_run_server_only_passes_transport() -> None:
    captured: dict[str, object] = {}

    class _FakeServer:
        def run(self, *, transport: str, host: str = "x", port: int = 1) -> None:
            captured["transport"] = transport
            captured["host"] = host
            captured["port"] = port

    mcp_main._run_server(_FakeServer(), "streamable-http")
    assert captured == {"transport": "streamable-http", "host": "x", "port": 1}


def test_main_runs_legacy_server_without_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"called": False}

    class _LegacyServer:
        def run(self) -> None:
            state["called"] = True

    monkeypatch.setattr(mcp_main, "load_config", lambda: MCPConfig())
    monkeypatch.setattr(mcp_main, "create_server", lambda _cfg: _LegacyServer())

    result = mcp_main.main([])

    assert result == 0
    assert state["called"] is True


def test_resolve_transport_http_flag() -> None:
    assert mcp_main._resolve_transport("stdio", http=True, sse=False) == "streamable-http"


def test_resolve_transport_sse_flag() -> None:
    assert mcp_main._resolve_transport("stdio", http=False, sse=True) == "sse"


def test_resolve_transport_no_flags_passes_through() -> None:
    assert mcp_main._resolve_transport("stdio", http=False, sse=False) == "stdio"
    assert mcp_main._resolve_transport("sse", http=False, sse=False) == "sse"
