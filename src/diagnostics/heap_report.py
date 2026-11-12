"""Heap attribution for the backend process: what its memory is made of.

WA-17 (website audit 2026-11-12): the backend's heap reached 2.8 GB against
``memory.high`` 2.56 GB twice in one day; the kernel throttled the service
until the healthcheck watchdog restarted it.  The cgroup numbers say THAT the
heap grew, not WHAT it is.  Only the process can see its own heap, so this
module answers from inside it, cheaply enough to run on the production box:

* :func:`malloc_summary`: glibc's own accounting (``mallinfo2`` +
  ``malloc_info``): bytes in use, bytes free but retained in the arenas
  (fragmentation, what ``malloc_trim`` / ``MALLOC_ARENA_MAX`` act on),
  ``mmap`` bytes, and the arena count.
* :func:`container_census`: the largest module-level containers and
  ``functools.lru_cache`` caches in this codebase's modules, by length.
* :func:`type_census`: live Python objects by type: count and shallow bytes.
* :func:`deep_census`: bytes reachable from each module-level object, each
  object counted once.  This is what sees ``str`` / ``bytes`` payloads (the
  cached JSON and gzip views), which the garbage collector does not track
  and the type census therefore cannot see.

Cost, measured locally: the container census takes ~8 ms; the type and
deep censuses together take 1.5-2.5 s of a worker thread (pure Python, so
the GIL is shared), and the deep census's visited-set costs ~100 MiB per
million objects while it runs.  So the deep census is bounded
(:data:`DEEP_BUDGET`) and skipped when the service is within
:data:`DEEP_HEADROOM_MIB` of its throttling line.  The glibc walks hold the
arena locks for ~120 ms each on a 3 GB heap, so they run only inside a
snapshot; ``/api/status`` reads the last snapshot's figures
(:func:`box_fields`) and never walks the heap.

Every figure is a number or an identifier from this codebase (module,
attribute, class and type names); no values and no user data are read.
Nothing here raises.
"""

from __future__ import annotations

import collections
import ctypes
import gc
import json
import os
import re
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.diagnostics import proc_probe

#: Box-local JSONL log of heap snapshots (``data/`` is gitignored).  Tests
#: redirect it (``tests/runtime_data_isolation.py``).
REPORT_PATH = Path(__file__).resolve().parents[2] / "data" / "diagnostics" / "heap_reports.jsonl"
#: The log is trimmed to its newest half once it passes this size.
MAX_REPORT_BYTES = 2 * 1024 * 1024

_MIB = 1024 * 1024
_HEAP_NR = re.compile(rb"<heap nr=")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.()<>\[\]-]")


class _MallInfo2(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_size_t)
        for name in (
            "arena",
            "ordblks",
            "smblks",
            "hblks",
            "hblkhd",
            "usmblks",
            "fsmblks",
            "uordblks",
            "fordblks",
            "keepcost",
        )
    ]


_LIBC: Any = None  # resolved lazily; False when unavailable (non-glibc)


def _libc() -> Any:
    global _LIBC
    if _LIBC is None:
        try:
            _LIBC = ctypes.CDLL("libc.so.6")
        except OSError:
            _LIBC = False
    return _LIBC or None


def _mib(n: int | None) -> int | None:
    return None if n is None else int(n) // _MIB


def _arena_count(libc: Any) -> int | None:
    """Number of glibc arenas, from ``malloc_info``'s XML (one ``<heap>`` per
    arena), written to an in-memory stream: no file is touched."""
    try:
        buf = ctypes.c_char_p()
        size = ctypes.c_size_t()
        libc.open_memstream.restype = ctypes.c_void_p
        libc.open_memstream.argtypes = [
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        libc.malloc_info.argtypes = [ctypes.c_int, ctypes.c_void_p]
        libc.fclose.argtypes = [ctypes.c_void_p]
        libc.free.argtypes = [ctypes.c_void_p]
        stream = libc.open_memstream(ctypes.byref(buf), ctypes.byref(size))
        if not stream:
            return None
        rc = libc.malloc_info(0, stream)
        libc.fclose(stream)
        try:
            xml = ctypes.string_at(buf, size.value) if buf.value is not None else b""
        finally:
            libc.free(ctypes.cast(buf, ctypes.c_void_p))
        if rc != 0:
            return None
        return len(_HEAP_NR.findall(xml)) or None
    except (AttributeError, OSError, ValueError, TypeError):
        return None


def empty_malloc_summary() -> dict[str, Any]:
    return {
        "available": False,
        "arena_mib": None,
        "in_use_mib": None,
        "free_mib": None,
        "mmap_mib": None,
        "arenas": None,
    }


def malloc_summary() -> dict[str, Any]:
    """glibc heap accounting for this process; unknown stays ``None``.

    ``arena_mib`` is heap obtained from the system (all arenas), split into
    ``in_use_mib`` (allocated) and ``free_mib`` (freed but retained);
    ``mmap_mib`` is large blocks served by ``mmap`` directly.
    """
    out = empty_malloc_summary()
    try:
        libc = _libc()
        if libc is None:
            return out
        fn = libc.mallinfo2
        fn.restype = _MallInfo2
        fn.argtypes = []
        m = fn()
        out.update(
            available=True,
            arena_mib=_mib(m.arena),
            in_use_mib=_mib(m.uordblks),
            free_mib=_mib(m.fordblks),
            mmap_mib=_mib(m.hblkhd),
            arenas=_arena_count(libc),
        )
    except (AttributeError, OSError, ValueError, TypeError):
        return empty_malloc_summary()
    return out


def empty_box_fields() -> dict[str, None]:
    return {
        "heap_arenas": None,
        "heap_in_use_mib": None,
        "heap_free_mib": None,
        "heap_mmap_mib": None,
    }


#: The last snapshot's glibc figures, served by :func:`box_fields`.
_LAST_BOX: dict[str, int | None] = empty_box_fields()


def box_fields() -> dict[str, int | None]:
    """The last snapshot's glibc figures for ``box_resources`` (numbers only).

    Cached, never measured here: walking the heap holds glibc's arena locks
    (~120 ms on a 3 GB heap), and ``/api/status`` must not stall on it.
    All ``None`` until the first snapshot.
    """
    return dict(_LAST_BOX)


def _remember_box(m: dict[str, Any]) -> None:
    _LAST_BOX.update(
        heap_arenas=m.get("arenas"),
        heap_in_use_mib=m.get("in_use_mib"),
        heap_free_mib=m.get("free_mib"),
        heap_mmap_mib=m.get("mmap_mib"),
    )


def _safe(name: str) -> str:
    return _SAFE_NAME.sub("_", str(name))[:160]


def _container_len(value: Any) -> tuple[str, int] | None:
    if isinstance(value, (dict, list, set, frozenset, tuple, collections.deque)):
        return type(value).__name__, len(value)
    info = getattr(value, "cache_info", None)
    if callable(info):
        try:
            return "lru_cache", int(info().currsize)
        except Exception:  # noqa: BLE001 -- a foreign object's cache_info
            return None
    return None


def container_census(
    limit: int = 20,
    *,
    prefixes: tuple[str, ...] = ("src.",),
    modules: tuple[str, ...] = ("server",),
) -> list[dict[str, Any]]:
    """The largest module-level containers and ``lru_cache``s, by length.

    Only this codebase's modules (``src.*`` and the server module); dunder
    attributes are skipped, and an object re-exported under several names is
    counted once (first name seen).
    """
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    try:
        for mname, mod in list(sys.modules.items()):
            if not (mname in modules or mname.startswith(prefixes)):
                continue
            namespace = getattr(mod, "__dict__", None)
            if not isinstance(namespace, dict):
                continue
            for attr, value in list(namespace.items()):
                if attr.startswith("__"):
                    continue
                measured = _container_len(value)
                if measured is None or id(value) in seen:
                    continue
                seen.add(id(value))
                kind, length = measured
                rows.append({"name": _safe(f"{mname}.{attr}"), "kind": kind, "len": length})
    except Exception:  # noqa: BLE001 -- a module mutating mid-walk
        pass
    rows.sort(key=lambda r: r["len"], reverse=True)
    return rows[: max(0, int(limit))]


def type_census(limit: int = 20) -> dict[str, Any]:
    """Live gc-tracked objects by type: count and shallow bytes (top by bytes).

    Shallow means ``sys.getsizeof``: a dict's own table, not what it points
    to.  Untracked objects (most ints, floats, strings) are not in the walk,
    but the containers holding them are.
    """
    counts: collections.Counter[str] = collections.Counter()
    sizes: collections.Counter[str] = collections.Counter()
    total = 0
    try:
        objects = gc.get_objects()
        total = len(objects)
        for obj in objects:
            name = type(obj).__name__
            counts[name] += 1
            try:
                sizes[name] += sys.getsizeof(obj)
            except Exception:  # noqa: BLE001 -- exotic __sizeof__
                pass
        del objects
    except Exception:  # noqa: BLE001
        return {"tracked_objects": None, "top": []}
    top = [
        {"type": _safe(name), "count": counts[name], "mib": round(size / _MIB, 1)}
        for name, size in sizes.most_common(max(0, int(limit)))
    ]
    return {"tracked_objects": total, "top": top}


def _numbers_only(extra: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only numeric / boolean / null values under safe keys."""
    if not isinstance(extra, dict):
        return {}
    return {_safe(k): v for k, v in extra.items() if v is None or isinstance(v, (bool, int, float))}


# Not descended into by the deep walk: code and namespaces.  A function's
# referents include its module globals, so walking it would attribute a
# whole module to whichever root reached it first.
_DEEP_SKIP = (
    types.ModuleType,
    type,
    types.FunctionType,
    types.BuiltinFunctionType,
    types.MethodType,
    types.CodeType,
    types.FrameType,
)
#: Upper bound on objects one deep census visits.  Its visited-set costs
#: ~100 MiB per million objects while it runs (independent review, measured:
#: +292 MiB peak at 3 million), so the census is bounded and reports
#: ``truncated`` rather than growing with the heap it measures.  A primed
#: local server walks ~1.2 million.
DEEP_BUDGET = 1_500_000
#: The deep census is skipped when the service is closer than this to its
#: throttling line (``proc_probe.memory_headroom_mib``): a diagnostic must
#: not push the process into the condition it is diagnosing.
DEEP_HEADROOM_MIB = 512


def deep_census(
    limit: int = 20,
    *,
    budget: int | None = None,
    prefixes: tuple[str, ...] = ("src.",),
    modules: tuple[str, ...] = ("server",),
) -> dict[str, Any]:
    """Bytes reachable from each module-level object in this codebase.

    Roots are module attributes, walked in module-name order through
    ``gc.get_referents``; an object reachable from several roots is counted
    once, under the first.  Modules, functions and other modules' classes
    are not roots; a class defined in the module is, through its own
    attributes (class-level caches).  ``truncated`` says the walk stopped at
    ``budget`` objects, so the totals are lower bounds.
    """
    cap = DEEP_BUDGET if budget is None else int(budget)
    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    walked = 0
    total = 0
    truncated = False
    try:
        for mname in sorted(sys.modules):
            if not (mname in modules or mname.startswith(prefixes)):
                continue
            namespace = getattr(sys.modules.get(mname), "__dict__", None)
            if not isinstance(namespace, dict):
                continue
            for attr, root in list(namespace.items()):
                if attr.startswith("__") or id(root) in seen:
                    continue
                if isinstance(root, type):
                    if getattr(root, "__module__", None) != mname:
                        continue
                    stack = [v for k, v in vars(root).items() if not k.startswith("__")]
                    seen.add(id(root))
                elif isinstance(root, _DEEP_SKIP):
                    continue
                else:
                    stack = [root]
                size = 0
                count = 0
                while stack:
                    obj = stack.pop()
                    oid = id(obj)
                    if oid in seen or isinstance(obj, _DEEP_SKIP):
                        continue
                    seen.add(oid)
                    try:
                        size += sys.getsizeof(obj)
                    except Exception:  # noqa: BLE001 -- exotic __sizeof__
                        pass
                    count += 1
                    if walked + count >= cap:
                        truncated = True
                        break
                    stack.extend(gc.get_referents(obj))
                walked += count
                total += size
                if count:
                    rows.append(
                        {
                            "name": _safe(f"{mname}.{attr}"),
                            "kind": "class"
                            if isinstance(root, type)
                            else _safe(type(root).__name__),
                            "mib": round(size / _MIB, 1),
                            "objects": count,
                        }
                    )
                if truncated:
                    break
            if truncated:
                break
    except Exception:  # noqa: BLE001 -- a module mutating mid-walk
        pass
    finally:
        seen.clear()
    rows.sort(key=lambda r: r["mib"], reverse=True)
    return {
        "walked_objects": walked,
        "attributed_mib": round(total / _MIB, 1),
        "truncated": truncated,
        "top": rows[: max(0, int(limit))],
    }


def _deep_allowed() -> tuple[bool, int | None]:
    headroom = proc_probe.memory_headroom_mib(os.getpid())
    return (headroom is None or headroom >= DEEP_HEADROOM_MIB), headroom


def snapshot(
    reason: str, *, include_types: bool = False, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One heap record: process RSS, glibc accounting, gc state, containers,
    and (optionally) the type and deep censuses.  ``extra`` carries numbers
    only (e.g. a ``malloc_trim`` result); anything else is dropped.

    RSS and the glibc figures are read BEFORE the censuses, so the record
    describes the heap, not the census's own temporary allocations.
    """
    rss_kb = proc_probe.process_rss_kb(os.getpid())
    malloc = malloc_summary()
    _remember_box(malloc)
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "reason": _safe(reason),
        "pid": os.getpid(),
        "process_rss_mib": None if rss_kb is None else int(rss_kb) // 1024,
        "malloc": malloc,
        "gc": {
            "counts": list(gc.get_count()),
            "allocated_blocks": sys.getallocatedblocks(),
            "threads": len(sys._current_frames()),  # noqa: SLF001
        },
        "containers": container_census(),
        "types": None,
        "deep": None,
        "deep_skipped": None,
        "headroom_mib": None,
        "census_ms": None,
        "extra": _numbers_only(extra),
    }
    if include_types:
        started = time.perf_counter()
        record["types"] = type_census()
        allowed, headroom = _deep_allowed()
        record["headroom_mib"] = headroom
        if allowed:
            record["deep"] = deep_census()
        else:
            record["deep_skipped"] = "low_headroom"
        record["census_ms"] = int((time.perf_counter() - started) * 1000)
    return record


def append_report(record: dict[str, Any], path: Path | None = None) -> bool:
    """Append one JSON line; past :data:`MAX_REPORT_BYTES` keep the newest
    half.  Returns False (never raises) when the log cannot be written."""
    target = Path(path) if path is not None else REPORT_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, separators=(",", ":"), sort_keys=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if target.stat().st_size > MAX_REPORT_BYTES:
            lines = target.read_text(encoding="utf-8").splitlines()
            keep = lines[len(lines) // 2 :]
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
            os.replace(tmp, target)
        return True
    except (OSError, TypeError, ValueError):
        return False


def record(
    reason: str, *, include_types: bool = False, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Snapshot, append to the box log, and return the headline numbers
    (for a log line).  Call off the event loop.  Never raises."""
    try:
        rec = snapshot(reason, include_types=include_types, extra=extra)
        written = append_report(rec)
        m = rec["malloc"]
        return {
            "written": written,
            "processRssMib": rec["process_rss_mib"],
            "heapInUseMib": m["in_use_mib"],
            "heapFreeMib": m["free_mib"],
            "heapArenas": m["arenas"],
        }
    except Exception:  # noqa: BLE001 -- diagnostics never break a caller
        return {"written": False}
