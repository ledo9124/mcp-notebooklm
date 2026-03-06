"""Operational MCP tools (diagnostics + stats)."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any

try:
    from mcp.server.fastmcp import Context as MCPContext
except Exception:  # pragma: no cover - optional dependency
    MCPContext = Any


from notebooklm.exceptions import ValidationError

from .._config import MCPConfig, load_config
from .._errors import handle_mcp_errors, map_exception, sanitize_error_message
from .._result import make_tool_result
from .._tokens import (
    DEFAULT_TOKEN_TTL_SECONDS,
    create_confirmation_token,
    verify_confirmation_token,
)

logger = logging.getLogger("notebooklm_mcp.tools.ops")


def _get_app_context(ctx: MCPContext) -> Any:
    candidate = None

    if hasattr(ctx, "request_context"):
        request_context = getattr(ctx, "request_context")
        candidate = getattr(request_context, "lifespan_context", None)
    elif hasattr(ctx, "lifespan_context"):
        candidate = getattr(ctx, "lifespan_context")
    else:
        candidate = ctx

    if candidate is None or not hasattr(candidate, "client"):
        raise ValidationError("MCP tool context does not provide AppContext.client")
    return candidate


def _resolve_runtime_config(ctx: MCPContext, fallback: MCPConfig) -> MCPConfig:
    request_context = getattr(ctx, "request_context", None)
    server = getattr(request_context, "server", None)
    config = getattr(server, "_notebooklm_mcp_config", None)
    if isinstance(config, MCPConfig):
        return config
    return fallback


def _resolve_server_config(server: Any) -> MCPConfig:
    config = getattr(server, "_notebooklm_mcp_config", None)
    if isinstance(config, MCPConfig):
        return config
    return load_config()


def _require_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_2pc_enabled(config: MCPConfig, *, action_name: str) -> None:
    if not config.enable_destructive_tools:
        raise ValidationError(
            f"{action_name} is disabled. Set NOTEBOOKLM_MCP_ENABLE_DESTRUCTIVE_TOOLS=1 to enable."
        )
    if not config.destructive_2pc:
        raise ValidationError(
            f"{action_name} requires NOTEBOOKLM_MCP_DESTRUCTIVE_2PC=1."
        )


def _token_expiry_iso(ttl_seconds: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    return expires_at.isoformat()


def _decode_token_payload(token: str) -> dict[str, Any] | None:
    if not isinstance(token, str) or "." not in token:
        return None

    payload_segment, _sep, _signature_segment = token.partition(".")
    if not payload_segment:
        return None

    try:
        padded = payload_segment + ("=" * ((4 - len(payload_segment) % 4) % 4))
        raw_payload = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, binascii.Error, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    return payload


def _parse_and_verify_token(
    token: str,
    *,
    expected_action: str,
    requires_source: bool,
) -> tuple[str, str | None]:
    payload = _decode_token_payload(token)
    if payload is None:
        raise ValidationError("Invalid or expired confirmation token.")

    notebook_id = payload.get("notebook_id")
    source_id = payload.get("source_id")
    if not isinstance(notebook_id, str) or not notebook_id.strip():
        raise ValidationError("Invalid or expired confirmation token.")
    clean_notebook_id = notebook_id.strip()

    clean_source_id: str | None = None
    if requires_source:
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValidationError("Invalid or expired confirmation token.")
        clean_source_id = source_id.strip()

    verified = verify_confirmation_token(
        token,
        expected_action=expected_action,
        expected_notebook_id=clean_notebook_id,
        expected_source_id=clean_source_id,
    )
    if not verified:
        raise ValidationError("Invalid or expired confirmation token.")

    return clean_notebook_id, clean_source_id


def _parse_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in {"quick", "full"}:
        raise ValidationError("mode must be one of: quick, full")
    return normalized


def _mask_email(value: str) -> str | None:
    if "@" not in value:
        return None

    local, _, domain = value.partition("@")
    if not local or not domain:
        return None

    masked_local = local[0] + ("*" * min(max(len(local) - 1, 1), 6))
    return f"{masked_local}@{domain}"


def _extract_identity(client: Any) -> str | None:
    auth = getattr(client, "auth", None)
    if auth is None:
        return None

    email = getattr(auth, "email", None)
    if isinstance(email, str):
        masked = _mask_email(email.strip())
        if masked:
            return masked

    cookies = getattr(auth, "cookies", None)
    if isinstance(cookies, dict):
        for key in ("EMAIL", "email", "ACCOUNT_EMAIL", "account_email"):
            value = cookies.get(key)
            if isinstance(value, str):
                masked = _mask_email(value.strip())
                if masked:
                    return masked

    return None


def _stats_snapshot(app_context: Any) -> dict[str, Any]:
    stats = getattr(app_context, "stats", None)
    if stats is not None and callable(getattr(stats, "snapshot", None)):
        try:
            snapshot = stats.snapshot()
            if isinstance(snapshot, dict):
                return snapshot
        except Exception:
            logger.debug("Failed to collect stats snapshot", exc_info=True)
    return {
        "uptime_seconds": 0.0,
        "inflight": 0,
        "backoff_events_1h": 0,
        "requests_1h": 0,
        "errors_1h": [],
        "errors_by_code": {},
    }


def _cache_snapshot(app_context: Any) -> dict[str, Any]:
    cache = getattr(app_context, "cache", None)
    if cache is None:
        return {"enabled": False}

    stats_fn = getattr(cache, "stats", None)
    if callable(stats_fn):
        try:
            raw = stats_fn()
            if isinstance(raw, dict):
                payload = dict(raw)
                payload.setdefault("enabled", True)
                return payload
        except Exception:
            logger.debug("Failed to read cache stats", exc_info=True)

    return {"enabled": True}


def _recommendations_for_checks(checks: list[dict[str, Any]]) -> list[str]:
    recommendations: list[str] = []
    for check in checks:
        if check.get("ok") is True:
            continue

        name = check.get("name")
        details = check.get("details", {})
        error_code = details.get("error_code") if isinstance(details, dict) else None

        if error_code == "auth_expired":
            rec = "Run `notebooklm login` to refresh authentication."
            if rec not in recommendations:
                recommendations.append(rec)
            continue

        if error_code == "rate_limited" or name == "rate_limit_signal":
            rec = "Rate limiting detected. Lower concurrency and retry with backoff."
            if rec not in recommendations:
                recommendations.append(rec)
            continue

        if error_code == "invalid_params" and name == "settings_parse":
            rec = "Verify `notebook_id` points to an accessible notebook."
            if rec not in recommendations:
                recommendations.append(rec)
            continue

        if name == "whoami":
            rec = "Account identity is unavailable from auth tokens; verify credentials manually."
            if rec not in recommendations:
                recommendations.append(rec)

    return recommendations


@handle_mcp_errors
async def notebooklm_sources_remove_prepare(
    ctx: MCPContext,
    notebook_id: str,
    source_id: str,
) -> dict[str, Any]:
    """Prepare source removal and return a short-lived confirmation token."""
    app_context = _get_app_context(ctx)
    config = _resolve_runtime_config(ctx, fallback=load_config())
    _require_2pc_enabled(config, action_name="Source removal")
    clean_notebook_id = _require_text(notebook_id, field_name="notebook_id")
    clean_source_id = _require_text(source_id, field_name="source_id")

    async with app_context.acquire_slot():
        sources = await app_context.client.sources.list(clean_notebook_id)

    source_match = next((item for item in sources if getattr(item, "id", None) == clean_source_id), None)
    if source_match is None:
        raise ValidationError("source_id not found in notebook.")

    summary: dict[str, Any] = {
        "notebook_id": clean_notebook_id,
        "source_id": clean_source_id,
    }
    source_title = getattr(source_match, "title", None)
    if isinstance(source_title, str) and source_title.strip():
        summary["source_title"] = source_title.strip()

    token = create_confirmation_token(
        action="remove_source",
        notebook_id=clean_notebook_id,
        source_id=clean_source_id,
        ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS,
    )
    return make_tool_result(
        {
            "confirmation_token": token,
            "expires_at": _token_expiry_iso(DEFAULT_TOKEN_TTL_SECONDS),
            "summary": summary,
        }
    )


@handle_mcp_errors
async def notebooklm_sources_remove_commit(
    ctx: MCPContext,
    confirm: bool,
    confirmation_token: str,
) -> dict[str, Any]:
    """Commit source removal using a valid confirmation token."""
    app_context = _get_app_context(ctx)
    config = _resolve_runtime_config(ctx, fallback=load_config())
    _require_2pc_enabled(config, action_name="Source removal")
    if confirm is not True:
        raise ValidationError("confirm must be true to commit source removal.")
    clean_token = _require_text(confirmation_token, field_name="confirmation_token")
    notebook_id, source_id = _parse_and_verify_token(
        clean_token,
        expected_action="remove_source",
        requires_source=True,
    )
    if source_id is None:  # pragma: no cover - guarded by requires_source=True
        raise ValidationError("Invalid or expired confirmation token.")

    async with app_context.acquire_slot():
        await app_context.client.sources.delete(notebook_id, source_id)

    return make_tool_result({"success": True})


@handle_mcp_errors
async def notebooklm_notebooks_delete_prepare(
    ctx: MCPContext,
    notebook_id: str,
) -> dict[str, Any]:
    """Prepare notebook deletion and return a short-lived confirmation token."""
    app_context = _get_app_context(ctx)
    config = _resolve_runtime_config(ctx, fallback=load_config())
    _require_2pc_enabled(config, action_name="Notebook deletion")
    clean_notebook_id = _require_text(notebook_id, field_name="notebook_id")

    async with app_context.acquire_slot():
        notebooks = await app_context.client.notebooks.list()

    notebook_match = next(
        (item for item in notebooks if getattr(item, "id", None) == clean_notebook_id),
        None,
    )
    if notebook_match is None:
        raise ValidationError("notebook_id not found.")

    summary: dict[str, Any] = {
        "notebook_id": clean_notebook_id,
    }
    notebook_title = getattr(notebook_match, "title", None)
    if isinstance(notebook_title, str) and notebook_title.strip():
        summary["title"] = notebook_title.strip()
    source_count = getattr(notebook_match, "sources_count", None)
    if isinstance(source_count, int):
        summary["source_count"] = source_count

    token = create_confirmation_token(
        action="delete_notebook",
        notebook_id=clean_notebook_id,
        ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS,
    )
    return make_tool_result(
        {
            "confirmation_token": token,
            "expires_at": _token_expiry_iso(DEFAULT_TOKEN_TTL_SECONDS),
            "summary": summary,
        }
    )


@handle_mcp_errors
async def notebooklm_notebooks_delete_commit(
    ctx: MCPContext,
    confirm: bool,
    confirmation_token: str,
) -> dict[str, Any]:
    """Commit notebook deletion using a valid confirmation token."""
    app_context = _get_app_context(ctx)
    config = _resolve_runtime_config(ctx, fallback=load_config())
    _require_2pc_enabled(config, action_name="Notebook deletion")
    if confirm is not True:
        raise ValidationError("confirm must be true to commit notebook deletion.")
    clean_token = _require_text(confirmation_token, field_name="confirmation_token")
    notebook_id, _ = _parse_and_verify_token(
        clean_token,
        expected_action="delete_notebook",
        requires_source=False,
    )

    async with app_context.acquire_slot():
        await app_context.client.notebooks.delete(notebook_id)

    return make_tool_result({"success": True})


@handle_mcp_errors
async def notebooklm_diagnose(
    ctx: MCPContext,
    mode: str = "quick",
    notebook_id: str | None = None,
) -> dict[str, Any]:
    """Run lightweight self-tests and return actionable diagnostics."""
    app_context = _get_app_context(ctx)
    selected_mode = _parse_mode(mode)
    checks: list[dict[str, Any]] = []

    identity = _extract_identity(app_context.client)
    if identity:
        checks.append(
            {
                "name": "whoami",
                "ok": True,
                "details": {"identity": identity},
            }
        )
    else:
        checks.append(
            {
                "name": "whoami",
                "ok": False,
                "message": "Could not infer account identity from auth tokens.",
            }
        )

    list_notebooks_error: dict[str, Any] | None = None
    notebook_count = 0
    try:
        async with app_context.acquire_slot():
            notebooks = await app_context.client.notebooks.list()
        notebook_count = len(notebooks)
        checks.append(
            {
                "name": "health",
                "ok": True,
                "details": {"api": "reachable"},
            }
        )
        checks.append(
            {
                "name": "list_notebooks",
                "ok": True,
                "details": {"count": notebook_count},
            }
        )
    except Exception as exc:
        mapped = map_exception(exc)
        list_notebooks_error = {
            "error_code": mapped.error_code,
        }
        message = sanitize_error_message(mapped.message)
        checks.append(
            {
                "name": "health",
                "ok": False,
                "message": message,
                "details": list_notebooks_error,
            }
        )
        checks.append(
            {
                "name": "list_notebooks",
                "ok": False,
                "message": message,
                "details": list_notebooks_error,
            }
        )

    if selected_mode == "full" and notebook_id:
        try:
            async with app_context.acquire_slot():
                settings = await app_context.client.chat.get_settings(notebook_id, strict=True)
            checks.append(
                {
                    "name": "settings_parse",
                    "ok": True,
                    "details": {
                        "goal": str(getattr(settings, "goal", "")),
                        "response_length": str(getattr(settings, "response_length", "")),
                    },
                }
            )
        except Exception as exc:
            mapped = map_exception(exc)
            checks.append(
                {
                    "name": "settings_parse",
                    "ok": False,
                    "message": sanitize_error_message(mapped.message),
                    "details": {"error_code": mapped.error_code},
                }
            )

    stats = _stats_snapshot(app_context)
    rate_limited_total = 0
    errors_by_code = stats.get("errors_by_code")
    if isinstance(errors_by_code, dict):
        value = errors_by_code.get("rate_limited", 0)
        if isinstance(value, int):
            rate_limited_total = value

    backoff_events = stats.get("backoff_events_1h", 0)
    if not isinstance(backoff_events, int):
        backoff_events = 0

    has_rate_limit_signal = rate_limited_total > 0 or backoff_events > 0
    checks.append(
        {
            "name": "rate_limit_signal",
            "ok": not has_rate_limit_signal,
            "message": (
                "Recent rate limiting detected." if has_rate_limit_signal else "No recent rate limiting."
            ),
            "details": {
                "rate_limited_errors_total": rate_limited_total,
                "backoff_events_1h": backoff_events,
            },
        }
    )

    recommendations = _recommendations_for_checks(checks)
    payload = {
        "ok": all(item.get("ok") is True for item in checks),
        "checks": checks,
        "recommendations": recommendations,
    }
    if list_notebooks_error is None:
        payload["summary"] = {"notebooks_count": notebook_count}

    return make_tool_result(payload)


@handle_mcp_errors
async def notebooklm_debug_stats(
    ctx: MCPContext,
    include_recent_errors: bool = True,
    include_cache_stats: bool = True,
) -> dict[str, Any]:
    """Return redacted operational counters and limits."""
    app_context = _get_app_context(ctx)
    stats = _stats_snapshot(app_context)
    recent_errors = stats.get("errors_1h", [])
    if not isinstance(recent_errors, list):
        recent_errors = []

    payload: dict[str, Any] = {
        "uptime_ms": int(float(stats.get("uptime_seconds", 0.0)) * 1000),
        "inflight_requests": int(stats.get("inflight", 0)),
        "backoff_events_1h": int(stats.get("backoff_events_1h", 0)),
        "requests_1h": int(stats.get("requests_1h", 0)),
        "errors_1h": len(recent_errors),
        "limits": {
            "max_inflight": int(getattr(app_context, "max_inflight", 0)),
        },
    }

    if include_recent_errors:
        payload["recent_errors"] = recent_errors

    if include_cache_stats:
        payload["cache"] = _cache_snapshot(app_context)

    return make_tool_result(payload)


def register_ops_tools(server: Any) -> None:
    """Register operational tools with a FastMCP-like server instance."""
    tool = getattr(server, "tool", None)
    if not callable(tool):
        return

    registrations: list[tuple[str, Any, str]] = [
        ("notebooklm_diagnose", notebooklm_diagnose, "Run notebooklm-mcp diagnostics"),
        ("notebooklm_debug_stats", notebooklm_debug_stats, "Return redacted operational stats"),
    ]
    config = _resolve_server_config(server)
    if config.enable_destructive_tools and config.destructive_2pc:
        registrations.extend(
            [
                (
                    "notebooklm_sources_remove_prepare",
                    notebooklm_sources_remove_prepare,
                    "Prepare source removal and return confirmation token",
                ),
                (
                    "notebooklm_sources_remove_commit",
                    notebooklm_sources_remove_commit,
                    "Commit source removal using confirmation token",
                ),
                (
                    "notebooklm_notebooks_delete_prepare",
                    notebooklm_notebooks_delete_prepare,
                    "Prepare notebook deletion and return confirmation token",
                ),
                (
                    "notebooklm_notebooks_delete_commit",
                    notebooklm_notebooks_delete_commit,
                    "Commit notebook deletion using confirmation token",
                ),
            ]
        )

    for name, fn, description in registrations:
        decorator = tool(name=name, description=description)
        decorator(fn)


__all__ = [
    "notebooklm_notebooks_delete_commit",
    "notebooklm_notebooks_delete_prepare",
    "notebooklm_debug_stats",
    "notebooklm_diagnose",
    "notebooklm_sources_remove_commit",
    "notebooklm_sources_remove_prepare",
    "register_ops_tools",
]
