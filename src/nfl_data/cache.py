"""TTL file cache for NFL data pulls.

We don't want to hammer nflverse on every request (and we
certainly don't want to hammer ESPN's undocumented endpoints),
so every ingest call goes through this cache.

Cache entries are stored as JSON under ``data/nfl_data_cache/``
with a filename hash of the cache key and a sidecar JSON with
the fetched-at timestamp.  Keeping them as JSON (not pickle)
means they're inspectable + portable across Python versions.

Nothing here imports pandas — the cache stores raw Python
primitives (list[dict], dict) that any caller can shape as
needed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

_CACHE_DIR_LOCK = threading.Lock()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_cache_dir() -> Path:
    return _repo_root() / "data" / "nfl_data_cache"


def _ensure_dir(path: Path) -> None:
    with _CACHE_DIR_LOCK:
        path.mkdir(parents=True, exist_ok=True)


def _key_hash(key: str) -> str:
    """Stable filename-safe hash of an arbitrary key string."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _entry_paths(cache_dir: Path, key: str) -> tuple[Path, Path]:
    h = _key_hash(key)
    return cache_dir / f"{h}.json", cache_dir / f"{h}.meta.json"


def get(
    key: str,
    *,
    ttl_seconds: float,
    cache_dir: Path | None = None,
) -> Any | None:
    """Return the cached value for ``key`` if fresh, else None.

    Malformed / corrupted entries are deleted and treated as cache
    misses so a partial write from a crashed process doesn't wedge
    the cache.
    """
    cache_dir = cache_dir or _default_cache_dir()
    if not cache_dir.exists():
        return None
    data_path, meta_path = _entry_paths(cache_dir, key)
    if not data_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        fetched_at = float(meta.get("fetched_at") or 0.0)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("nfl_data_cache: corrupt meta for %s; evicting", key)
        try:
            meta_path.unlink()
            data_path.unlink()
        except OSError:
            pass
        return None
    if (time.time() - fetched_at) > ttl_seconds:
        return None
    try:
        return json.loads(data_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        _LOGGER.warning("nfl_data_cache: corrupt data for %s; evicting", key)
        try:
            data_path.unlink()
            meta_path.unlink()
        except OSError:
            pass
        return None


def put(
    key: str,
    value: Any,
    *,
    cache_dir: Path | None = None,
) -> None:
    """Persist ``value`` under ``key``.  Atomic-ish: write to a
    tempfile and rename so a partial write can't land at the
    canonical path."""
    cache_dir = cache_dir or _default_cache_dir()
    _ensure_dir(cache_dir)
    data_path, meta_path = _entry_paths(cache_dir, key)
    tmp_data = data_path.with_suffix(".json.tmp")
    tmp_meta = meta_path.with_suffix(".meta.json.tmp")
    try:
        tmp_data.write_text(
            json.dumps(value, default=str, sort_keys=True), encoding="utf-8",
        )
        tmp_meta.write_text(
            json.dumps({"fetched_at": time.time(), "key": key}), encoding="utf-8",
        )
        tmp_data.replace(data_path)
        tmp_meta.replace(meta_path)
    except Exception:  # noqa: BLE001
        # Best-effort cleanup; swallow so a full disk doesn't kill
        # the ingest flow.
        for p in (tmp_data, tmp_meta):
            try:
                p.unlink()
            except OSError:
                pass
        raise


def evict(key: str, *, cache_dir: Path | None = None) -> None:
    """Remove ``key`` from the cache.  No-op if absent."""
    cache_dir = cache_dir or _default_cache_dir()
    data_path, meta_path = _entry_paths(cache_dir, key)
    for p in (data_path, meta_path):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
