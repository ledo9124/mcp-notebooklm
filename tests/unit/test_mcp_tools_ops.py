"""Unit tests for notebooklm_mcp.tools.ops."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from notebooklm.exceptions import AuthError
from notebooklm_mcp._config import MCPConfig
from notebooklm_mcp._errors import MCPToolError
from notebooklm_mcp._stats import Stats
from notebooklm_mcp.tools import ops as ops_tools


class _AcquireSlot:
    def __init__(self, app: "_FakeAppContext") -> None:
        self._app = app

    async def __aenter__(self) -> None:
        self._app.slot_entries += 1
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@dataclass
class _FakeAppContext:
    client: Any
    stats: Any
    max_inflight: int = 5
    cache: Any | None = None
    slot_entries: int = 0

    def acquire_slot(self) -> _AcquireSlot:
        return _AcquireSlot(self)


def _ctx(app_context: _FakeAppContext, *, config: MCPConfig | None = None) -> Any:
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=app_context,
            server=SimpleNamespace(_notebooklm_mcp_config=config or MCPConfig()),
        )
    )


def _structured(result: dict[str, Any]) -> dict[str, Any]:
    return result["structuredContent"]


class _FakeStats:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)


@pytest.mark.asyncio
async def test_notebooklm_debug_stats_returns_expected_fields_with_recent_errors_and_cache() -> None:
    stats = _FakeStats(
        {
            "uptime_seconds": 12.5,
            "inflight": 2,
            "backoff_events_1h": 3,
            "requests_1h": 7,
            "errors_1h": [{"code": "auth_expired", "message": "sanitized"}],
            "errors_by_code": {"auth_expired": 1},
        }
    )
    cache = SimpleNamespace(stats=lambda: {"enabled": True, "hits_1h": 4, "misses_1h": 1})
    app = _FakeAppContext(
        client=SimpleNamespace(),
        stats=stats,
        cache=cache,
        max_inflight=9,
    )

    result = await ops_tools.notebooklm_debug_stats(
        _ctx(app),
        include_recent_errors=True,
        include_cache_stats=True,
    )

    payload = _structured(result)
    assert payload["uptime_ms"] == 12_500
    assert payload["inflight_requests"] == 2
    assert payload["backoff_events_1h"] == 3
    assert payload["requests_1h"] == 7
    assert payload["errors_1h"] == 1
    assert payload["recent_errors"] == [{"code": "auth_expired", "message": "sanitized"}]
    assert payload["cache"] == {"enabled": True, "hits_1h": 4, "misses_1h": 1}
    assert payload["limits"] == {"max_inflight": 9}


@pytest.mark.asyncio
async def test_notebooklm_diagnose_reports_auth_failures_without_throwing() -> None:
    class _NotebooksAPI:
        async def list(self) -> list[Any]:
            raise AuthError("expired token")

    stats = _FakeStats(
        {
            "backoff_events_1h": 0,
            "requests_1h": 0,
            "errors_1h": [],
            "errors_by_code": {},
            "inflight": 0,
            "uptime_seconds": 1.0,
        }
    )
    auth = SimpleNamespace(cookies={"EMAIL": "user@example.com"})
    client = SimpleNamespace(notebooks=_NotebooksAPI(), auth=auth)
    app = _FakeAppContext(client=client, stats=stats)

    result = await ops_tools.notebooklm_diagnose(_ctx(app), mode="quick")
    payload = _structured(result)

    assert payload["ok"] is False
    check_names = [item["name"] for item in payload["checks"]]
    assert "health" in check_names
    assert "list_notebooks" in check_names
    assert "whoami" in check_names
    assert any(item["name"] == "whoami" and item["ok"] for item in payload["checks"])
    assert any("notebooklm login" in rec.lower() for rec in payload["recommendations"])


@pytest.mark.asyncio
async def test_notebooklm_diagnose_success_path_has_all_checks_ok() -> None:
    class _NotebooksAPI:
        async def list(self) -> list[Any]:
            return [SimpleNamespace(id="nb-1"), SimpleNamespace(id="nb-2")]

    stats = _FakeStats(
        {
            "backoff_events_1h": 0,
            "requests_1h": 2,
            "errors_1h": [],
            "errors_by_code": {},
            "inflight": 0,
            "uptime_seconds": 3.0,
        }
    )
    client = SimpleNamespace(
        notebooks=_NotebooksAPI(),
        auth=SimpleNamespace(cookies={"EMAIL": "user@example.com"}),
    )
    app = _FakeAppContext(client=client, stats=stats)

    result = await ops_tools.notebooklm_diagnose(_ctx(app), mode="quick")
    payload = _structured(result)

    assert payload["ok"] is True
    assert payload["recommendations"] == []
    assert payload["summary"] == {"notebooks_count": 2}
    assert all(item.get("ok") is True for item in payload["checks"])


@pytest.mark.asyncio
async def test_notebooklm_diagnose_does_not_leak_credentials_in_checks() -> None:
    class _NotebooksAPI:
        async def list(self) -> list[Any]:
            raise AuthError("token=abc123 cookie=secret-value")

    stats = _FakeStats(
        {
            "backoff_events_1h": 0,
            "requests_1h": 0,
            "errors_1h": [],
            "errors_by_code": {},
            "inflight": 0,
            "uptime_seconds": 1.0,
        }
    )
    client = SimpleNamespace(
        notebooks=_NotebooksAPI(),
        auth=SimpleNamespace(cookies={"EMAIL": "user@example.com"}),
    )
    app = _FakeAppContext(client=client, stats=stats)

    result = await ops_tools.notebooklm_diagnose(_ctx(app), mode="quick")
    payload = _structured(result)
    payload_text = str(payload)
    assert "abc123" not in payload_text
    assert "secret-value" not in payload_text


@pytest.mark.asyncio
async def test_notebooklm_diagnose_full_mode_includes_settings_parse() -> None:
    class _NotebooksAPI:
        async def list(self) -> list[Any]:
            return [SimpleNamespace(id="nb-1")]

    class _ChatAPI:
        async def get_settings(self, notebook_id: str, *, strict: bool) -> Any:
            assert notebook_id == "nb-1"
            assert strict is True
            return SimpleNamespace(goal="default", response_length="longer")

    stats = _FakeStats(
        {
            "backoff_events_1h": 1,
            "requests_1h": 5,
            "errors_1h": [],
            "errors_by_code": {"rate_limited": 2},
            "inflight": 0,
            "uptime_seconds": 5.0,
        }
    )
    client = SimpleNamespace(
        notebooks=_NotebooksAPI(),
        chat=_ChatAPI(),
        auth=SimpleNamespace(cookies={}),
    )
    app = _FakeAppContext(client=client, stats=stats)

    result = await ops_tools.notebooklm_diagnose(
        _ctx(app),
        mode="full",
        notebook_id="nb-1",
    )
    payload = _structured(result)

    settings_check = next(item for item in payload["checks"] if item["name"] == "settings_parse")
    rate_limit_check = next(item for item in payload["checks"] if item["name"] == "rate_limit_signal")
    assert settings_check["ok"] is True
    assert rate_limit_check["ok"] is False
    assert any("rate limiting" in rec.lower() for rec in payload["recommendations"])
    assert app.slot_entries == 2


@pytest.mark.asyncio
async def test_notebooklm_debug_stats_surfaces_sanitized_error_messages() -> None:
    stats = Stats()
    stats.record_error(
        "notebooklm_ask",
        "server_error",
        "token=abc123 " + ("x" * 400),
    )
    app = _FakeAppContext(client=SimpleNamespace(), stats=stats, max_inflight=4)

    result = await ops_tools.notebooklm_debug_stats(
        _ctx(app),
        include_recent_errors=True,
        include_cache_stats=False,
    )
    payload = _structured(result)
    error_message = payload["recent_errors"][0]["message"]
    assert error_message is not None
    assert "abc123" not in error_message
    assert len(error_message) <= 200


@pytest.mark.asyncio
async def test_sources_remove_prepare_and_commit_round_trip() -> None:
    deleted: list[tuple[str, str]] = []

    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Any]:
            assert notebook_id == "nb-1"
            return [
                SimpleNamespace(id="src-1", title="Roadmap PDF"),
                SimpleNamespace(id="src-2", title="Notes"),
            ]

        async def delete(self, notebook_id: str, source_id: str) -> None:
            deleted.append((notebook_id, source_id))

    stats = _FakeStats({})
    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()), stats=stats)
    config = MCPConfig(enable_destructive_tools=True, destructive_2pc=True)
    ctx = _ctx(app, config=config)

    prepared = await ops_tools.notebooklm_sources_remove_prepare(
        ctx,
        notebook_id="nb-1",
        source_id="src-1",
    )
    prepared_payload = _structured(prepared)
    assert prepared_payload["summary"] == {
        "notebook_id": "nb-1",
        "source_id": "src-1",
        "source_title": "Roadmap PDF",
    }
    token = prepared_payload["confirmation_token"]
    assert isinstance(token, str)
    assert prepared_payload["expires_at"].endswith("+00:00")

    committed = await ops_tools.notebooklm_sources_remove_commit(
        ctx,
        confirm=True,
        confirmation_token=token,
    )
    assert _structured(committed) == {"success": True}
    assert deleted == [("nb-1", "src-1")]


@pytest.mark.asyncio
async def test_notebooks_delete_prepare_and_commit_round_trip() -> None:
    deleted: list[str] = []

    class _NotebooksAPI:
        async def list(self) -> list[Any]:
            return [
                SimpleNamespace(id="nb-1", title="Roadmap", sources_count=3),
                SimpleNamespace(id="nb-2", title="Ideas", sources_count=0),
            ]

        async def delete(self, notebook_id: str) -> None:
            deleted.append(notebook_id)

    stats = _FakeStats({})
    app = _FakeAppContext(client=SimpleNamespace(notebooks=_NotebooksAPI()), stats=stats)
    config = MCPConfig(enable_destructive_tools=True, destructive_2pc=True)
    ctx = _ctx(app, config=config)

    prepared = await ops_tools.notebooklm_notebooks_delete_prepare(ctx, notebook_id="nb-1")
    prepared_payload = _structured(prepared)
    assert prepared_payload["summary"] == {
        "notebook_id": "nb-1",
        "title": "Roadmap",
        "source_count": 3,
    }

    committed = await ops_tools.notebooklm_notebooks_delete_commit(
        ctx,
        confirm=True,
        confirmation_token=prepared_payload["confirmation_token"],
    )
    assert _structured(committed) == {"success": True}
    assert deleted == ["nb-1"]


@pytest.mark.asyncio
async def test_2pc_commit_rejects_tampered_token_and_requires_confirm() -> None:
    deleted: list[tuple[str, str]] = []

    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Any]:
            return [SimpleNamespace(id="src-1", title="Roadmap PDF")]

        async def delete(self, notebook_id: str, source_id: str) -> None:
            deleted.append((notebook_id, source_id))

    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()), stats=_FakeStats({}))
    config = MCPConfig(enable_destructive_tools=True, destructive_2pc=True)
    ctx = _ctx(app, config=config)

    prepared = await ops_tools.notebooklm_sources_remove_prepare(
        ctx,
        notebook_id="nb-1",
        source_id="src-1",
    )
    token = _structured(prepared)["confirmation_token"]

    with pytest.raises(MCPToolError, match="confirm must be true"):
        await ops_tools.notebooklm_sources_remove_commit(
            ctx,
            confirm=False,
            confirmation_token=token,
        )

    payload_segment, signature_segment = token.split(".", 1)
    tampered_signature = ("A" if signature_segment[0] != "A" else "B") + signature_segment[1:]
    tampered = f"{payload_segment}.{tampered_signature}"
    with pytest.raises(MCPToolError, match="Invalid or expired confirmation token"):
        await ops_tools.notebooklm_sources_remove_commit(
            ctx,
            confirm=True,
            confirmation_token=tampered,
        )

    assert deleted == []


@pytest.mark.asyncio
async def test_2pc_tools_require_destructive_and_2pc_flags() -> None:
    class _SourcesAPI:
        async def list(self, notebook_id: str) -> list[Any]:
            return [SimpleNamespace(id="src-1", title="Roadmap PDF")]

    app = _FakeAppContext(client=SimpleNamespace(sources=_SourcesAPI()), stats=_FakeStats({}))

    with pytest.raises(MCPToolError, match="NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1"):
        await ops_tools.notebooklm_sources_remove_prepare(
            _ctx(app, config=MCPConfig(enable_destructive_tools=False, destructive_2pc=False)),
            notebook_id="nb-1",
            source_id="src-1",
        )

    with pytest.raises(MCPToolError, match="NOTEBOOKLM_MCP_DESTRUCTIVE_2PC=1"):
        await ops_tools.notebooklm_sources_remove_prepare(
            _ctx(app, config=MCPConfig(enable_destructive_tools=True, destructive_2pc=False)),
            notebook_id="nb-1",
            source_id="src-1",
        )


def test_register_ops_tools_registers_all_tool_names() -> None:
    class _FakeServer:
        def __init__(self, config: MCPConfig | None = None) -> None:
            self._notebooklm_mcp_config = config or MCPConfig()
            self.registered: dict[str, Any] = {}

        def tool(self, *, name: str, description: str):
            assert isinstance(description, str)

            def _decorator(fn):
                self.registered[name] = fn
                return fn

            return _decorator

    server = _FakeServer()
    ops_tools.register_ops_tools(server)

    assert set(server.registered) == {
        "notebooklm_diagnose",
        "notebooklm_debug_stats",
    }


def test_register_ops_tools_registers_2pc_tools_when_enabled() -> None:
    class _FakeServer:
        def __init__(self, config: MCPConfig | None = None) -> None:
            self._notebooklm_mcp_config = config or MCPConfig()
            self.registered: dict[str, Any] = {}

        def tool(self, *, name: str, description: str):
            assert isinstance(description, str)

            def _decorator(fn):
                self.registered[name] = fn
                return fn

            return _decorator

    server = _FakeServer(MCPConfig(enable_destructive_tools=True, destructive_2pc=True))
    ops_tools.register_ops_tools(server)

    assert set(server.registered) == {
        "notebooklm_diagnose",
        "notebooklm_debug_stats",
        "notebooklm_sources_remove_prepare",
        "notebooklm_sources_remove_commit",
        "notebooklm_notebooks_delete_prepare",
        "notebooklm_notebooks_delete_commit",
    }
