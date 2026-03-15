"""Adapter helpers for change-radar source snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx


DEFAULT_WEB_TIMEOUT_SECONDS = 30.0
_READ_CHUNK_SIZE = 64 * 1024

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
AdapterKind = Literal["web", "local_file"]


@dataclass(frozen=True)
class RevisionSnapshot:
    """Normalized source-revision snapshot ready for later persistence."""

    adapter_kind: AdapterKind
    canonical_uri: str
    revision_key: str
    content_hash: str | None
    etag: str | None
    last_modified: str | None
    fetched_at: str
    metadata: dict[str, JsonValue]


def _utc_now(ts: datetime | None = None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _normalize_timestamp(ts: datetime | None = None) -> str:
    return _utc_now(ts).isoformat()


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _build_revision_key(*parts: str | None) -> str:
    filtered = [part for part in parts if part]
    if filtered:
        return "|".join(filtered)
    return "unknown"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_READ_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


async def _hash_response_body(response: httpx.Response) -> str:
    digest = hashlib.sha256()
    async for chunk in response.aiter_bytes():
        digest.update(chunk)
    return digest.hexdigest()


def detect_adapter_kind(target: str | Path) -> AdapterKind:
    """Infer which adapter should handle the target."""

    if isinstance(target, Path):
        return "local_file"

    parsed = urlparse(str(target))
    if parsed.scheme in {"http", "https"}:
        return "web"
    return "local_file"


def snapshot_local_file(
    path: str | Path,
    *,
    now: datetime | None = None,
) -> RevisionSnapshot:
    """Snapshot a local file using mtime, size, and SHA-256."""

    resolved_path = Path(path).expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"File not found: {resolved_path}")
    if not resolved_path.is_file():
        raise ValueError(f"Not a regular file: {resolved_path}")

    stat = resolved_path.stat()
    content_hash = _hash_file(resolved_path)
    last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    return RevisionSnapshot(
        adapter_kind="local_file",
        canonical_uri=resolved_path.as_uri(),
        revision_key=_build_revision_key(
            f"mtime_ns:{stat.st_mtime_ns}",
            f"size:{stat.st_size}",
            f"sha256:{content_hash}",
        ),
        content_hash=content_hash,
        etag=None,
        last_modified=last_modified,
        fetched_at=_normalize_timestamp(now),
        metadata={
            "adapter": "local_file",
            "path": str(resolved_path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
    )


async def snapshot_web_url(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_WEB_TIMEOUT_SECONDS,
    now: datetime | None = None,
) -> RevisionSnapshot:
    """Snapshot a web URL using HEAD metadata plus a streamed GET body hash."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme for web snapshot: {url}")

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient()

    try:
        head_status_code: int | None = None
        head_headers: httpx.Headers | None = None
        try:
            response = await client.head(url, follow_redirects=True, timeout=timeout)
            head_status_code = response.status_code
            if response.is_success:
                head_headers = response.headers
        except httpx.HTTPError:
            pass

        async with client.stream("GET", url, follow_redirects=True, timeout=timeout) as response:
            response.raise_for_status()
            content_hash = await _hash_response_body(response)
            get_status_code = response.status_code
            final_url = str(response.url)
            headers = response.headers

        etag = (head_headers or headers).get("etag")
        last_modified = (head_headers or headers).get("last-modified")
        content_length = _parse_content_length((head_headers or headers).get("content-length"))

        return RevisionSnapshot(
            adapter_kind="web",
            canonical_uri=final_url,
            revision_key=_build_revision_key(
                f"etag:{etag}" if etag else None,
                f"last-modified:{last_modified}" if last_modified else None,
                f"sha256:{content_hash}",
            ),
            content_hash=content_hash,
            etag=etag,
            last_modified=last_modified,
            fetched_at=_normalize_timestamp(now),
            metadata={
                "adapter": "web",
                "url": final_url,
                "head_status_code": head_status_code,
                "get_status_code": get_status_code,
                "content_type": headers.get("content-type"),
                "content_length": content_length,
            },
        )
    finally:
        if owns_client:
            await client.aclose()


async def snapshot_target(
    target: str | Path,
    *,
    adapter_kind: AdapterKind | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_WEB_TIMEOUT_SECONDS,
    now: datetime | None = None,
) -> RevisionSnapshot:
    """Dispatch to the appropriate adapter for a watched target."""

    resolved_kind = adapter_kind or detect_adapter_kind(target)
    if resolved_kind == "web":
        return await snapshot_web_url(
            str(target),
            client=client,
            timeout=timeout,
            now=now,
        )
    return snapshot_local_file(target, now=now)


__all__ = [
    "AdapterKind",
    "DEFAULT_WEB_TIMEOUT_SECONDS",
    "RevisionSnapshot",
    "detect_adapter_kind",
    "snapshot_local_file",
    "snapshot_target",
    "snapshot_web_url",
]
