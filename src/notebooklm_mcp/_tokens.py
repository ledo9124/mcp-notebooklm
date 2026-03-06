"""Confirmation token helpers for 2-phase destructive actions."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from typing import Any

DEFAULT_TOKEN_TTL_SECONDS = 300
_DEFAULT_SECRET_KEY = os.urandom(32)
_USED_NONCES: dict[str, int] = {}
_USED_NONCES_LOCK = threading.Lock()


def _require_non_empty_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _resolve_secret_key(secret_key: bytes | None) -> bytes:
    if secret_key is None:
        return _DEFAULT_SECRET_KEY
    if not isinstance(secret_key, bytes) or not secret_key:
        raise ValueError("secret_key must be non-empty bytes")
    return secret_key


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padded = value + ("=" * ((4 - len(value) % 4) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _prune_used_nonces(now_ts: int) -> None:
    expired = [nonce for nonce, exp in _USED_NONCES.items() if exp < now_ts]
    for nonce in expired:
        _USED_NONCES.pop(nonce, None)


def _record_nonce_if_fresh(nonce: str, *, exp: int, now_ts: int) -> bool:
    with _USED_NONCES_LOCK:
        _prune_used_nonces(now_ts)
        existing_exp = _USED_NONCES.get(nonce)
        if existing_exp is not None and existing_exp >= now_ts:
            return False
        _USED_NONCES[nonce] = exp
    return True


def create_confirmation_token(
    action: str,
    notebook_id: str,
    source_id: str | None = None,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    secret_key: bytes | None = None,
) -> str:
    """Create a signed, expiring confirmation token."""
    clean_action = _require_non_empty_text(action, field="action")
    clean_notebook_id = _require_non_empty_text(notebook_id, field="notebook_id")
    clean_source_id = None
    if source_id is not None:
        clean_source_id = _require_non_empty_text(source_id, field="source_id")
    if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be a positive integer")

    now_ts = int(time.time())
    payload: dict[str, Any] = {
        "action": clean_action,
        "notebook_id": clean_notebook_id,
        "exp": now_ts + ttl_seconds,
        "nonce": uuid.uuid4().hex,
    }
    if clean_source_id is not None:
        payload["source_id"] = clean_source_id

    payload_segment = _urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(
        _resolve_secret_key(secret_key),
        payload_segment.encode("ascii"),
        hashlib.sha256,
    ).digest()
    signature_segment = _urlsafe_b64encode(signature)
    return f"{payload_segment}.{signature_segment}"


def verify_confirmation_token(
    token: str,
    expected_action: str,
    expected_notebook_id: str,
    expected_source_id: str | None = None,
    secret_key: bytes | None = None,
) -> bool:
    """Validate signature, expiry, action/target binding, and nonce replay use."""
    try:
        clean_action = _require_non_empty_text(expected_action, field="expected_action")
        clean_notebook_id = _require_non_empty_text(
            expected_notebook_id,
            field="expected_notebook_id",
        )
        clean_source_id = None
        if expected_source_id is not None:
            clean_source_id = _require_non_empty_text(
                expected_source_id,
                field="expected_source_id",
            )
        if not isinstance(token, str) or "." not in token:
            return False

        payload_segment, signature_segment = token.split(".", 1)
        if not payload_segment or not signature_segment:
            return False

        received_signature = _urlsafe_b64decode(signature_segment)
        expected_signature = hmac.new(
            _resolve_secret_key(secret_key),
            payload_segment.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(received_signature, expected_signature):
            return False

        payload_raw = _urlsafe_b64decode(payload_segment)
        payload = json.loads(payload_raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return False

        payload_action = payload.get("action")
        payload_notebook_id = payload.get("notebook_id")
        payload_source_id = payload.get("source_id")
        payload_exp = payload.get("exp")
        payload_nonce = payload.get("nonce")

        if payload_action != clean_action:
            return False
        if payload_notebook_id != clean_notebook_id:
            return False
        if clean_source_id is None and payload_source_id is not None:
            return False
        if clean_source_id is not None and payload_source_id != clean_source_id:
            return False
        if not isinstance(payload_exp, int):
            return False
        if not isinstance(payload_nonce, str) or not payload_nonce:
            return False

        now_ts = int(time.time())
        if payload_exp < now_ts:
            return False
        return _record_nonce_if_fresh(payload_nonce, exp=payload_exp, now_ts=now_ts)
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        return False


def _clear_nonce_replay_cache_for_tests() -> None:
    """Reset nonce replay state for deterministic tests."""
    with _USED_NONCES_LOCK:
        _USED_NONCES.clear()


__all__ = [
    "DEFAULT_TOKEN_TTL_SECONDS",
    "create_confirmation_token",
    "verify_confirmation_token",
]

