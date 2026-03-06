"""Unit tests for notebooklm_mcp._cache."""

from __future__ import annotations

import pytest

from notebooklm_mcp._cache import TTLCache


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_cache_disabled_by_default_and_noops() -> None:
    cache = TTLCache()
    cache.set("notebooks:list", ["a"])
    assert cache.get("notebooks:list") is None
    assert cache.stats() == {
        "enabled": False,
        "hits_1h": 0,
        "misses_1h": 0,
        "hit_rate_1h": 0.0,
        "entries": 0,
    }


def test_set_get_and_stats_hit_rate() -> None:
    clock = _FakeClock(start=10.0)
    cache = TTLCache(enabled=True, ttl_seconds=30, max_entries=10, time_fn=clock.now)

    cache.set("notebooks:list", ["n1"])
    assert cache.get("notebooks:list") == ["n1"]
    assert cache.get("notebooks:missing") is None

    stats = cache.stats()
    assert stats["enabled"] is True
    assert stats["hits_1h"] == 1
    assert stats["misses_1h"] == 1
    assert stats["hit_rate_1h"] == 0.5
    assert stats["entries"] == 1


def test_ttl_expiry_turns_get_into_miss() -> None:
    clock = _FakeClock(start=0.0)
    cache = TTLCache(enabled=True, ttl_seconds=5, max_entries=10, time_fn=clock.now)
    cache.set("notebooks:list", ["n1"])

    clock.advance(6.0)
    assert cache.get("notebooks:list") is None

    stats = cache.stats()
    assert stats["hits_1h"] == 0
    assert stats["misses_1h"] == 1
    assert stats["entries"] == 0


def test_invalidate_exact_and_prefix() -> None:
    clock = _FakeClock(start=100.0)
    cache = TTLCache(enabled=True, ttl_seconds=300, max_entries=10, time_fn=clock.now)
    cache.set("notebooks:list", ["n1", "n2"])
    cache.set("notebooks:nb1:sources", ["s1"])
    cache.set("notebooks:nb1:settings", {"goal": "default"})
    cache.set("notebooks:nb2:sources", ["s2"])

    cache.invalidate("notebooks:list")
    cache.invalidate_prefix("notebooks:nb1")

    assert cache.get("notebooks:list") is None
    assert cache.get("notebooks:nb1:sources") is None
    assert cache.get("notebooks:nb1:settings") is None
    assert cache.get("notebooks:nb2:sources") == ["s2"]
    assert cache.stats()["entries"] == 1


def test_max_entries_evicts_oldest_inserted_key() -> None:
    clock = _FakeClock(start=0.0)
    cache = TTLCache(enabled=True, ttl_seconds=300, max_entries=2, time_fn=clock.now)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)

    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert cache.stats()["entries"] == 2


def test_hit_miss_windows_prune_after_one_hour() -> None:
    clock = _FakeClock(start=0.0)
    cache = TTLCache(enabled=True, ttl_seconds=5000, max_entries=10, time_fn=clock.now)

    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None
    assert cache.stats()["hit_rate_1h"] == 0.5

    clock.advance(3601.0)
    stats = cache.stats()
    assert stats["hits_1h"] == 0
    assert stats["misses_1h"] == 0
    assert stats["hit_rate_1h"] == 0.0


def test_invalid_constructor_values_raise() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        TTLCache(ttl_seconds=0, enabled=True)
    with pytest.raises(ValueError, match="max_entries"):
        TTLCache(max_entries=0, enabled=True)
