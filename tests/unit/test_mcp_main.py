"""Unit tests for notebooklm_mcp.__main__."""

from __future__ import annotations

import importlib

import pytest

mcp_main = importlib.import_module("notebooklm_mcp.__main__")


def test_main_version_flag_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_main, "server", None)
    assert mcp_main.main(["--version"]) == 0


def test_main_returns_error_when_server_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_main, "server", None)
    assert mcp_main.main([]) == 1


def test_main_runs_server_with_sse_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeServer:
        def run(self, *, transport: str, host: str, port: int) -> None:
            captured["transport"] = transport
            captured["host"] = host
            captured["port"] = port

    monkeypatch.setattr(mcp_main, "server", _FakeServer())

    result = mcp_main.main(["--transport", "sse", "--host", "0.0.0.0", "--port", "9101"])

    assert result == 0
    assert captured == {"transport": "sse", "host": "0.0.0.0", "port": 9101}


def test_main_runs_legacy_server_without_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"called": False}

    class _LegacyServer:
        def run(self) -> None:
            state["called"] = True

    monkeypatch.setattr(mcp_main, "server", _LegacyServer())

    result = mcp_main.main([])

    assert result == 0
    assert state["called"] is True
