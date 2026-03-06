"""Optional TTL cache helpers for notebooklm-mcp metadata responses."""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
import threading
import time
from typing import Any

DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_CACHE_MAX_ENTRIES = 100
DEFAULT_STATS_WINDOW_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class CacheStats:
    """One-hour cache hit/miss snapshot for diagnostics."""

    enabled: bool
    hits_1h: int
    misses_1h: int
    hit_rate_1h: float
    entries: int


class TTLCache:
    """Thread-safe TTL cache with bounded entry count and rolling stats."""

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
        *,
        enabled: bool = False,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        if max_entries <= 0:
            raise ValueError("max_entries must be > 0")

        self._ttl_seconds = int(ttl_seconds)
        self._max_entries = int(max_entries)
        self._enabled = bool(enabled)
        self._time_fn = time_fn or time.time
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._hits_window: deque[float] = deque()
        self._misses_window: deque[float] = deque()

    def get(self, key: str) -> Any | None:
        """Return a cached value or ``None`` if missing/expired/disabled."""
        if not self._enabled:
            return None

        with self._lock:
            now = self._time_fn()
            self._prune(now)
            entry = self._entries.get(key)
            if entry is None:
                self._record_miss(now)
                return None

            self._record_hit(now)
            return entry[1]

    def set(self, key: str, value: Any) -> None:
        """Store a value with TTL; evict oldest entries once capacity is reached."""
        if not self._enabled:
            return

        with self._lock:
            now = self._time_fn()
            self._prune(now)
            expires_at = now + float(self._ttl_seconds)
            if key in self._entries:
                self._entries.pop(key, None)
            self._entries[key] = (expires_at, value)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def invalidate(self, key: str) -> None:
        """Drop one cache key if present."""
        if not self._enabled:
            return

        with self._lock:
            now = self._time_fn()
            self._prune(now)
            self._entries.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        """Drop all keys that start with ``prefix``."""
        if not self._enabled:
            return

        with self._lock:
            now = self._time_fn()
            self._prune(now)
            to_delete = [cache_key for cache_key in self._entries if cache_key.startswith(prefix)]
            for cache_key in to_delete:
                self._entries.pop(cache_key, None)

    def stats(self) -> dict[str, Any]:
        """Return diagnostics snapshot consumable by ops debug tools."""
        with self._lock:
            now = self._time_fn()
            self._prune(now)
            hits = len(self._hits_window)
            misses = len(self._misses_window)
            total = hits + misses
            payload = CacheStats(
                enabled=self._enabled,
                hits_1h=hits,
                misses_1h=misses,
                hit_rate_1h=(hits / total) if total else 0.0,
                entries=len(self._entries) if self._enabled else 0,
            )
            return asdict(payload)

    def _prune(self, now: float) -> None:
        self._prune_entries(now)
        self._prune_windows(now)

    def _prune_entries(self, now: float) -> None:
        if not self._entries:
            return

        stale_keys = [
            cache_key
            for cache_key, (expires_at, _) in self._entries.items()
            if expires_at <= now
        ]
        for cache_key in stale_keys:
            self._entries.pop(cache_key, None)

    def _prune_windows(self, now: float) -> None:
        cutoff = now - DEFAULT_STATS_WINDOW_SECONDS
        while self._hits_window and self._hits_window[0] < cutoff:
            self._hits_window.popleft()
        while self._misses_window and self._misses_window[0] < cutoff:
            self._misses_window.popleft()

    def _record_hit(self, now: float) -> None:
        self._hits_window.append(now)
        self._prune_windows(now)

    def _record_miss(self, now: float) -> None:
        self._misses_window.append(now)
        self._prune_windows(now)


__all__ = [
    "CacheStats",
    "DEFAULT_CACHE_MAX_ENTRIES",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_STATS_WINDOW_SECONDS",
    "TTLCache",
]
