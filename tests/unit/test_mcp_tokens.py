"""Unit tests for notebooklm_mcp._tokens."""

from __future__ import annotations

import pytest

from notebooklm_mcp import _tokens


@pytest.fixture(autouse=True)
def _clear_nonce_cache() -> None:
    _tokens._clear_nonce_replay_cache_for_tests()


def test_create_and_verify_round_trip_without_source() -> None:
    secret = b"test-secret"
    token = _tokens.create_confirmation_token(
        action="delete_notebook",
        notebook_id="nb-1",
        ttl_seconds=60,
        secret_key=secret,
    )

    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="delete_notebook",
            expected_notebook_id="nb-1",
            secret_key=secret,
        )
        is True
    )


def test_create_and_verify_round_trip_with_source() -> None:
    secret = b"test-secret"
    token = _tokens.create_confirmation_token(
        action="remove_source",
        notebook_id="nb-1",
        source_id="src-1",
        ttl_seconds=60,
        secret_key=secret,
    )

    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="remove_source",
            expected_notebook_id="nb-1",
            expected_source_id="src-1",
            secret_key=secret,
        )
        is True
    )


def test_verify_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tokens.time, "time", lambda: 1_000_000)
    token = _tokens.create_confirmation_token(
        action="delete_notebook",
        notebook_id="nb-1",
        ttl_seconds=10,
        secret_key=b"test-secret",
    )
    monkeypatch.setattr(_tokens.time, "time", lambda: 1_000_100)

    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="delete_notebook",
            expected_notebook_id="nb-1",
            secret_key=b"test-secret",
        )
        is False
    )


def test_verify_rejects_wrong_action_or_target() -> None:
    secret = b"test-secret"
    token = _tokens.create_confirmation_token(
        action="delete_notebook",
        notebook_id="nb-1",
        ttl_seconds=60,
        secret_key=secret,
    )

    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="remove_source",
            expected_notebook_id="nb-1",
            secret_key=secret,
        )
        is False
    )

    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="delete_notebook",
            expected_notebook_id="nb-2",
            secret_key=secret,
        )
        is False
    )


def test_verify_rejects_wrong_source_id_binding() -> None:
    secret = b"test-secret"
    token = _tokens.create_confirmation_token(
        action="remove_source",
        notebook_id="nb-1",
        source_id="src-1",
        ttl_seconds=60,
        secret_key=secret,
    )

    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="remove_source",
            expected_notebook_id="nb-1",
            expected_source_id="src-2",
            secret_key=secret,
        )
        is False
    )
    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="remove_source",
            expected_notebook_id="nb-1",
            expected_source_id=None,
            secret_key=secret,
        )
        is False
    )


def test_verify_rejects_tampered_token() -> None:
    secret = b"test-secret"
    token = _tokens.create_confirmation_token(
        action="delete_notebook",
        notebook_id="nb-1",
        ttl_seconds=60,
        secret_key=secret,
    )
    payload_segment, signature_segment = token.split(".", 1)
    tampered_payload = ("A" if payload_segment[0] != "A" else "B") + payload_segment[1:]
    tampered = f"{tampered_payload}.{signature_segment}"

    assert (
        _tokens.verify_confirmation_token(
            tampered,
            expected_action="delete_notebook",
            expected_notebook_id="nb-1",
            secret_key=secret,
        )
        is False
    )


def test_verify_rejects_replay_with_same_token() -> None:
    secret = b"test-secret"
    token = _tokens.create_confirmation_token(
        action="delete_notebook",
        notebook_id="nb-1",
        ttl_seconds=60,
        secret_key=secret,
    )

    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="delete_notebook",
            expected_notebook_id="nb-1",
            secret_key=secret,
        )
        is True
    )
    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="delete_notebook",
            expected_notebook_id="nb-1",
            secret_key=secret,
        )
        is False
    )


def test_verify_rejects_with_wrong_secret() -> None:
    token = _tokens.create_confirmation_token(
        action="delete_notebook",
        notebook_id="nb-1",
        ttl_seconds=60,
        secret_key=b"secret-a",
    )

    assert (
        _tokens.verify_confirmation_token(
            token,
            expected_action="delete_notebook",
            expected_notebook_id="nb-1",
            secret_key=b"secret-b",
        )
        is False
    )
