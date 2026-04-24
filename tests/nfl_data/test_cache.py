"""Tests for src.nfl_data.cache — the TTL file cache used by every
nflverse / ESPN ingest path."""
from __future__ import annotations

import time

from src.nfl_data import cache


def test_put_then_get_returns_same_value(tmp_path):
    cache.put("foo", {"a": 1, "b": [2, 3]}, cache_dir=tmp_path)
    got = cache.get("foo", ttl_seconds=60, cache_dir=tmp_path)
    assert got == {"a": 1, "b": [2, 3]}


def test_missing_key_returns_none(tmp_path):
    assert cache.get("absent", ttl_seconds=60, cache_dir=tmp_path) is None


def test_expired_entry_returns_none(tmp_path):
    cache.put("stale", [1, 2, 3], cache_dir=tmp_path)
    # Force a past fetched_at.
    _, meta = cache._entry_paths(tmp_path, "stale")  # noqa: SLF001
    import json
    meta.write_text(json.dumps({"fetched_at": time.time() - 3600, "key": "stale"}), encoding="utf-8")
    assert cache.get("stale", ttl_seconds=60, cache_dir=tmp_path) is None


def test_corrupt_data_is_evicted(tmp_path):
    cache.put("corrupt", {"ok": True}, cache_dir=tmp_path)
    data_path, _ = cache._entry_paths(tmp_path, "corrupt")  # noqa: SLF001
    data_path.write_text("{not valid json", encoding="utf-8")
    assert cache.get("corrupt", ttl_seconds=60, cache_dir=tmp_path) is None
    # After the miss, the corrupt file should be gone.
    assert not data_path.exists()


def test_evict_removes_entry(tmp_path):
    cache.put("bye", {"x": 1}, cache_dir=tmp_path)
    cache.evict("bye", cache_dir=tmp_path)
    assert cache.get("bye", ttl_seconds=60, cache_dir=tmp_path) is None


def test_put_writes_atomically(tmp_path):
    """A crashed write must not leave a half-written canonical file.

    We can't simulate a crash cleanly but we can verify the tmpfile
    doesn't persist after success."""
    cache.put("atom", {"x": 1}, cache_dir=tmp_path)
    for p in tmp_path.iterdir():
        assert ".tmp" not in p.name
