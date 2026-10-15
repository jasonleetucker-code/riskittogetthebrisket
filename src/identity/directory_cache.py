"""Process-wide cache of the Sleeper directory index (request-path use).

``IdentityContext.load_default`` re-reads and re-indexes the whole Sleeper
``/players/nfl`` dump on every call — tens of thousands of entries, a
multi-second parse.  That is fine for a batch report and wrong for a request
handler.  This module keeps ONE :class:`SleeperDirectoryIndex` per process,
keyed on the source file's identity ``(path, mtime_ns, size)``, so:

* a request pays the parse at most once per directory refresh;
* a refreshed dump (``snapshot_store`` writes it atomically) is picked up on
  the next call, never served stale past a change on disk;
* concurrent first callers build it ONCE (the build runs under the lock, a
  deliberate single-flight — two threads parsing the same 10+ MB dump would
  double the memory spike for no gain).

Absence is a state, not an error: no file (or an unreadable one) returns
``None`` and every consumer must render "identity directory unavailable"
rather than guess.  Nothing here fetches from the network.

The index is treated as READ-ONLY by every consumer; per-request caches live
on ``IdentityContext`` instances, never on the shared index.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from src.identity.resolution import SleeperDirectoryIndex, build_sleeper_index

_LOGGER = logging.getLogger(__name__)

_lock = threading.Lock()
# (key, index) where key = (str(path), mtime_ns, size).
_cached: tuple[tuple[str, int, int], SleeperDirectoryIndex] | None = None
_build_count = 0


def default_directory_path() -> Path:
    """The app's cached Sleeper dump — the same file ``load_default`` reads."""
    from src.public_league import snapshot_store  # noqa: PLC0415

    return Path(snapshot_store.NFL_PLAYERS_PATH)


def _file_key(path: Path) -> tuple[str, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), int(st.st_mtime_ns), int(st.st_size))


def _read_directory(path: Path) -> dict[str, Any] | None:
    try:
        directory = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — absence is a state, not a crash
        _LOGGER.debug("sleeper directory unreadable: %s", type(exc).__name__)
        return None
    return directory if isinstance(directory, dict) and directory else None


def get_default_sleeper_index(path: Path | None = None) -> SleeperDirectoryIndex | None:
    """The shared index for ``path`` (default: the app's cached dump).

    Returns ``None`` when the file is missing, unreadable or empty.  A file
    whose mtime or size changed since the cached build is re-indexed.
    """
    global _cached, _build_count
    target = Path(path) if path is not None else default_directory_path()
    key = _file_key(target)
    if key is None:
        return None
    with _lock:
        if _cached is not None and _cached[0] == key:
            return _cached[1]
        directory = _read_directory(target)
        if directory is None:
            return None
        index = build_sleeper_index(directory)
        _cached = (key, index)
        _build_count += 1
        return index


def build_count() -> int:
    """How many times an index was built (observability + tests)."""
    with _lock:
        return _build_count


def reset_for_tests() -> None:
    global _cached, _build_count
    with _lock:
        _cached = None
        _build_count = 0
