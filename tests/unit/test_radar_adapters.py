"""Unit tests for change-radar adapter snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib

import httpx
import pytest

from notebooklm.radar import (
    detect_adapter_kind,
    snapshot_local_file,
    snapshot_target,
    snapshot_web_url,
)


def test_detect_adapter_kind_prefers_web_scheme_and_local_paths(tmp_path):
    local_path = tmp_path / "notes.txt"
    local_path.write_text("hello", encoding="utf-8")

    assert detect_adapter_kind("https://example.com/source") == "web"
    assert detect_adapter_kind(local_path) == "local_file"
    assert detect_adapter_kind(str(local_path)) == "local_file"


def test_snapshot_local_file_returns_mtime_size_and_hash(tmp_path):
    target = tmp_path / "notes.txt"
    body = "radar snapshot\n"
    target.write_text(body, encoding="utf-8")
    stat = target.stat()
    snapshot = snapshot_local_file(
        target,
        now=datetime(2026, 3, 15, 4, 20, tzinfo=timezone.utc),
    )

    assert snapshot.adapter_kind == "local_file"
    assert snapshot.canonical_uri == target.resolve().as_uri()
    assert snapshot.content_hash == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert snapshot.etag is None
    assert snapshot.last_modified == datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    assert snapshot.fetched_at == "2026-03-15T04:20:00+00:00"
    assert snapshot.metadata == {
        "adapter": "local_file",
        "path": str(target.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    assert f"mtime_ns:{stat.st_mtime_ns}" in snapshot.revision_key
    assert f"size:{stat.st_size}" in snapshot.revision_key
    assert f"sha256:{snapshot.content_hash}" in snapshot.revision_key


def test_snapshot_local_file_rejects_missing_or_non_file_targets(tmp_path):
    missing = tmp_path / "missing.txt"

    with pytest.raises(FileNotFoundError):
        snapshot_local_file(missing)

    with pytest.raises(ValueError):
        snapshot_local_file(tmp_path)


@pytest.mark.asyncio
async def test_snapshot_web_url_uses_head_metadata_and_get_body_hash():
    body = b"material change"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(
                200,
                request=request,
                headers={
                    "etag": '"v2"',
                    "last-modified": "Sat, 15 Mar 2026 04:21:00 GMT",
                    "content-length": str(len(body)),
                    "content-type": "text/plain; charset=utf-8",
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/plain; charset=utf-8"},
                content=body,
            )
        raise AssertionError(f"unexpected method: {request.method}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        snapshot = await snapshot_web_url(
            "https://example.com/source.txt",
            client=client,
            now=datetime(2026, 3, 15, 4, 22, tzinfo=timezone.utc),
        )

    expected_hash = hashlib.sha256(body).hexdigest()
    assert snapshot.adapter_kind == "web"
    assert snapshot.canonical_uri == "https://example.com/source.txt"
    assert snapshot.content_hash == expected_hash
    assert snapshot.etag == '"v2"'
    assert snapshot.last_modified == "Sat, 15 Mar 2026 04:21:00 GMT"
    assert snapshot.fetched_at == "2026-03-15T04:22:00+00:00"
    assert snapshot.metadata == {
        "adapter": "web",
        "url": "https://example.com/source.txt",
        "head_status_code": 200,
        "get_status_code": 200,
        "content_type": "text/plain; charset=utf-8",
        "content_length": len(body),
    }
    assert snapshot.revision_key == (
        f'etag:"v2"|last-modified:Sat, 15 Mar 2026 04:21:00 GMT|sha256:{expected_hash}'
    )


@pytest.mark.asyncio
async def test_snapshot_web_url_falls_back_to_get_headers_when_head_is_unavailable():
    body = b"body-only"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(405, request=request)
        if request.method == "GET":
            return httpx.Response(
                200,
                request=request,
                headers={
                    "etag": "etag-3",
                    "last-modified": "Sat, 15 Mar 2026 04:23:00 GMT",
                    "content-length": str(len(body)),
                    "content-type": "text/markdown",
                },
                content=body,
            )
        raise AssertionError(f"unexpected method: {request.method}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        snapshot = await snapshot_web_url("https://example.com/fallback", client=client)

    assert snapshot.etag == "etag-3"
    assert snapshot.last_modified == "Sat, 15 Mar 2026 04:23:00 GMT"
    assert snapshot.metadata["head_status_code"] == 405
    assert snapshot.metadata["content_length"] == len(body)
    assert snapshot.revision_key.startswith("etag:etag-3|last-modified:Sat, 15 Mar 2026 04:23:00 GMT")


@pytest.mark.asyncio
async def test_snapshot_target_dispatches_to_requested_adapter(tmp_path):
    local_path = tmp_path / "doc.md"
    local_path.write_text("# NotebookLM\n", encoding="utf-8")

    local_snapshot = await snapshot_target(local_path)
    assert local_snapshot.adapter_kind == "local_file"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, request=request)
        if request.method == "GET":
            return httpx.Response(200, request=request, content=b"hello")
        raise AssertionError(f"unexpected method: {request.method}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        web_snapshot = await snapshot_target(
            "https://example.com/dispatch",
            client=client,
        )

    assert web_snapshot.adapter_kind == "web"
    assert web_snapshot.canonical_uri == "https://example.com/dispatch"
