"""Unit tests for notebooklm_mcp.server."""

from __future__ import annotations

import asyncio
import importlib

import pytest

from notebooklm.exceptions import ConfigurationError
from notebooklm_mcp.server import AppContext, app_lifespan

mcp_server = importlib.import_module("notebooklm_mcp.server")


class _FakeClient:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> "_FakeClient":
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited = True


def test_app_context_holds_client_reference() -> None:
    marker = object()
    context = AppContext(  # type: ignore[arg-type]
        client=marker,
        semaphore=asyncio.Semaphore(3),
        max_inflight=3,
    )
    assert context.client is marker
    assert context.max_inflight == 3


@pytest.mark.asyncio
async def test_app_lifespan_yields_context_and_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeClient()

    class _FakeNotebookLMClient:
        @classmethod
        async def from_storage(cls) -> _FakeClient:
            return fake_client

    monkeypatch.setattr(mcp_server, "NotebookLMClient", _FakeNotebookLMClient)
    monkeypatch.setattr(
        mcp_server,
        "_resolve_runtime_config",
        lambda _server: mcp_server.MCPConfig(max_inflight=2),
    )

    async with app_lifespan(object()) as context:
        assert isinstance(context, AppContext)
        assert context.client is fake_client
        assert context.max_inflight == 2
        assert context.stats is not None
        assert context.audit is None
        assert context.cache is None
        assert fake_client.entered is True
        assert fake_client.exited is False

    assert fake_client.exited is True


@pytest.mark.asyncio
async def test_app_lifespan_raises_configuration_error_on_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingNotebookLMClient:
        @classmethod
        async def from_storage(cls) -> _FakeClient:
            raise FileNotFoundError("storage_state.json not found")

    monkeypatch.setattr(mcp_server, "NotebookLMClient", _FailingNotebookLMClient)

    with pytest.raises(ConfigurationError, match="notebooklm login"):
        async with app_lifespan(object()):
            pass


def test_create_server_returns_none_without_mcp_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "FastMCP", None)
    monkeypatch.setattr(
        mcp_server, "_FASTMCP_IMPORT_ERROR", ModuleNotFoundError("No module named 'mcp'")
    )

    server_instance = mcp_server.create_server()
    assert server_instance is None


def test_build_fastmcp_kwargs_includes_host_port_when_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FastMCPWithNetwork:
        def __init__(
            self,
            *,
            name: str,
            lifespan,
            version: str,
            stateless_http: bool,
            json_response: bool,
            host: str,
            port: int,
        ) -> None:
            pass

    monkeypatch.setattr(mcp_server, "FastMCP", _FastMCPWithNetwork)
    monkeypatch.setattr(mcp_server, "_package_version", lambda: "9.9.9")

    config = mcp_server.MCPConfig(host="0.0.0.0", port=9101)
    kwargs = mcp_server._build_fastmcp_kwargs(config)

    assert kwargs["name"] == "notebooklm-mcp"
    assert kwargs["lifespan"] is app_lifespan
    assert kwargs["version"] == "9.9.9"
    assert kwargs["stateless_http"] is True
    assert kwargs["json_response"] is True
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9101


def test_build_fastmcp_kwargs_omits_host_port_when_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LegacyFastMCP:
        def __init__(self, *, name: str, lifespan) -> None:
            pass

    monkeypatch.setattr(mcp_server, "FastMCP", _LegacyFastMCP)

    kwargs = mcp_server._build_fastmcp_kwargs(mcp_server.MCPConfig(host="0.0.0.0", port=9101))

    assert kwargs["name"] == "notebooklm-mcp"
    assert kwargs["lifespan"] is app_lifespan
    assert "host" not in kwargs
    assert "port" not in kwargs


def test_create_server_builds_fastmcp_and_registers_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeFastMCP:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    captured: dict[str, object] = {}

    def _fake_register_components(server_instance: object) -> None:
        captured["server"] = server_instance

    monkeypatch.setattr(mcp_server, "FastMCP", _FakeFastMCP)
    monkeypatch.setattr(mcp_server, "_FASTMCP_IMPORT_ERROR", None)
    monkeypatch.setattr(mcp_server, "_register_components", _fake_register_components)

    config = mcp_server.MCPConfig(max_inflight=7)
    server_instance = mcp_server.create_server(config)

    assert isinstance(server_instance, _FakeFastMCP)
    assert server_instance.kwargs["name"] == "notebooklm-mcp"
    assert server_instance.kwargs["lifespan"] is app_lifespan
    assert getattr(server_instance, "_notebooklm_mcp_config") is config
    assert captured["server"] is server_instance


@pytest.mark.asyncio
async def test_app_lifespan_enables_audit_when_path_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    fake_client = _FakeClient()

    class _FakeNotebookLMClient:
        @classmethod
        async def from_storage(cls) -> _FakeClient:
            return fake_client

    monkeypatch.setattr(mcp_server, "NotebookLMClient", _FakeNotebookLMClient)
    monkeypatch.setattr(
        mcp_server,
        "_resolve_runtime_config",
        lambda _server: mcp_server.MCPConfig(
            max_inflight=3,
            audit_log_path=str(tmp_path / "audit.jsonl"),
        ),
    )

    async with app_lifespan(object()) as context:
        assert context.max_inflight == 3
        assert context.audit is not None


@pytest.mark.asyncio
async def test_app_context_acquire_slot_queues_with_limit_one() -> None:
    context = AppContext(  # type: ignore[arg-type]
        client=object(),
        semaphore=asyncio.Semaphore(1),
        max_inflight=1,
    )
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        async with context.acquire_slot():
            order.append("first-enter")
            first_entered.set()
            assert context.inflight == 1
            await release_first.wait()
            order.append("first-exit")

    async def second() -> None:
        await first_entered.wait()
        order.append("second-wait")
        async with context.acquire_slot():
            order.append("second-enter")

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())

    await first_entered.wait()
    await asyncio.sleep(0)
    assert order == ["first-enter", "second-wait"]

    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert order == ["first-enter", "second-wait", "first-exit", "second-enter"]
    assert context.inflight == 0
