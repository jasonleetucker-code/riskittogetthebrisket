"""Heap attribution (WA-17): ``src/diagnostics/heap_report.py`` + its server wiring.

The report is diagnostics only.  What is pinned here: glibc's accounting is
read, not guessed (unknown stays ``None``); the arena count honours
``MALLOC_ARENA_MAX`` (the cap the service unit sets); the censuses name
this codebase's containers and live types and nothing else; records are
numbers and identifiers only; the box-local log stays bounded; and nothing
raises into a caller.
"""

from __future__ import annotations

import asyncio
import functools
import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from src.diagnostics import heap_report

GLIBC = sys.platform.startswith("linux") and heap_report.malloc_summary()["available"]
needs_glibc = pytest.mark.skipif(not GLIBC, reason="glibc mallinfo2 not available")


# ── glibc accounting ────────────────────────────────────────────────────


@needs_glibc
def test_malloc_summary_reads_glibc():
    m = heap_report.malloc_summary()
    assert m["available"] is True
    for key in ("arena_mib", "in_use_mib", "free_mib", "mmap_mib", "arenas"):
        assert isinstance(m[key], int) and m[key] >= 0, key
    assert m["arenas"] >= 1
    # in use + free is the arena total (each floored to whole MiB).
    assert m["in_use_mib"] + m["free_mib"] <= m["arena_mib"] + 1


def test_no_glibc_is_unknown_not_zero(monkeypatch):
    monkeypatch.setattr(heap_report, "_LIBC", False)
    m = heap_report.malloc_summary()
    assert m == heap_report.empty_malloc_summary()
    assert m["available"] is False
    assert all(v is None for k, v in m.items() if k != "available")
    assert heap_report.box_fields() == heap_report.empty_box_fields()


@needs_glibc
def test_malloc_summary_never_raises(monkeypatch):
    class Broken:
        @property
        def mallinfo2(self):
            raise AttributeError("no mallinfo2 in this libc")

    monkeypatch.setattr(heap_report, "_LIBC", Broken())
    assert heap_report.malloc_summary() == heap_report.empty_malloc_summary()


_ARENA_PROBE = textwrap.dedent(
    """
    import json, sys, threading
    sys.path.insert(0, sys.argv[1])
    from src.diagnostics import heap_report
    start = threading.Barrier(8)
    def churn():
        start.wait()
        for _ in range(300):
            blocks = [bytearray(4096) for _ in range(64)]
            del blocks
    threads = [threading.Thread(target=churn) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print(json.dumps(heap_report.malloc_summary()))
    """
)


@needs_glibc
@pytest.mark.parametrize("cap", [1, 2])
def test_arena_count_honours_malloc_arena_max(cap):
    """The service unit's ``MALLOC_ARENA_MAX=2`` is visible in the report: eight
    threads allocating at once cannot open more arenas than the cap."""
    repo = Path(__file__).resolve().parents[2]
    out = subprocess.run(
        [sys.executable, "-c", _ARENA_PROBE, str(repo)],
        env={"MALLOC_ARENA_MAX": str(cap), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    m = json.loads(out.stdout.strip().splitlines()[-1])
    assert m["available"] is True
    assert 1 <= m["arenas"] <= cap


# ── censuses ────────────────────────────────────────────────────────────


@pytest.fixture
def fake_module(monkeypatch):
    mod = types.ModuleType("src._heap_report_fixture")
    big = {i: i for i in range(5000)}
    mod.BIG = big
    mod.ALIAS = big  # the same object under a second name: counted once
    mod.SMALL = [1, 2, 3]
    mod.__private_dunder__ = list(range(9000))  # dunder: skipped

    @functools.lru_cache(maxsize=None)
    def cached(n):
        return n

    for n in range(700):
        cached(n)
    mod.cached = cached
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    outsider = types.ModuleType("not_this_codebase")
    outsider.HUGE = list(range(50_000))
    monkeypatch.setitem(sys.modules, outsider.__name__, outsider)
    return mod


def test_container_census_names_this_codebase_only(fake_module):
    rows = heap_report.container_census(limit=10_000)
    names = {r["name"]: r for r in rows}
    big = [
        n for n in names if n.startswith("src._heap_report_fixture.") and names[n]["len"] == 5000
    ]
    assert len(big) == 1, big  # BIG and ALIAS are one object
    assert names["src._heap_report_fixture.cached"] == {
        "name": "src._heap_report_fixture.cached",
        "kind": "lru_cache",
        "len": 700,
    }
    assert names["src._heap_report_fixture.SMALL"]["len"] == 3
    assert not any("__private_dunder__" in n for n in names)
    assert not any(n.startswith("not_this_codebase") for n in names)
    lens = [r["len"] for r in rows]
    assert lens == sorted(lens, reverse=True)


def test_container_census_limit(fake_module):
    assert len(heap_report.container_census(limit=2)) == 2
    assert heap_report.container_census(limit=0) == []


class _HeapFixtureThing:
    def __init__(self, n):
        self.n = n


def test_type_census_counts_live_objects():
    held = [_HeapFixtureThing(i) for i in range(20_000)]
    census = heap_report.type_census(limit=200)
    assert census["tracked_objects"] >= 20_000
    row = next(r for r in census["top"] if r["type"] == "_HeapFixtureThing")
    assert row["count"] >= 20_000
    assert row["mib"] > 0
    del held


def test_type_census_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("gc unavailable")

    monkeypatch.setattr(heap_report.gc, "get_objects", boom)
    assert heap_report.type_census() == {"tracked_objects": None, "top": []}


# ── records and the box-local log ───────────────────────────────────────


def _walk(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)
    else:
        yield value


def test_snapshot_is_numbers_and_identifiers_only(fake_module):
    rec = heap_report.snapshot(
        "unit test", include_types=True, extra={"trimRssAfterMib": 10, "secret": "drop me"}
    )
    json.dumps(rec)  # serialisable
    assert rec["reason"] == "unit_test"
    assert rec["extra"] == {"trimRssAfterMib": 10}
    assert rec["types"]["top"]
    for leaf in _walk(rec):
        assert leaf is None or isinstance(leaf, (bool, int, float, str))
        if isinstance(leaf, str):
            assert len(leaf) <= 160
            assert "\n" not in leaf and '"' not in leaf


def test_snapshot_without_types():
    rec = heap_report.snapshot("periodic")
    assert rec["types"] is None
    assert isinstance(rec["containers"], list)


def test_append_report_keeps_the_log_bounded(tmp_path, monkeypatch):
    path = tmp_path / "diag" / "heap_reports.jsonl"
    monkeypatch.setattr(heap_report, "MAX_REPORT_BYTES", 4096)
    for i in range(200):
        assert heap_report.append_report({"i": i, "pad": "x" * 50}, path) is True
    lines = path.read_text(encoding="utf-8").splitlines()
    assert path.stat().st_size <= 4096 + 200
    assert [json.loads(line)["i"] for line in lines] == sorted(
        json.loads(line)["i"] for line in lines
    )
    assert json.loads(lines[-1])["i"] == 199  # the newest survives a trim


def test_append_report_failure_is_false_not_raise(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory", encoding="utf-8")
    assert heap_report.append_report({"a": 1}, blocker / "sub" / "log.jsonl") is False


def test_record_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("probe failed")

    monkeypatch.setattr(heap_report, "snapshot", boom)
    assert heap_report.record("x") == {"written": False}


def test_tests_never_write_the_real_log():
    real = Path(heap_report.__file__).resolve().parents[2] / "data" / "diagnostics"
    assert real not in heap_report.REPORT_PATH.resolve().parents


def test_record_writes_one_line_to_the_isolated_log():
    summary = heap_report.record("unit", include_types=False)
    assert summary["written"] is True
    lines = heap_report.REPORT_PATH.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["reason"] == "unit"


# ── server wiring ───────────────────────────────────────────────────────


@pytest.fixture
def server_mod():
    import server  # noqa: PLC0415

    return server


def test_box_resources_carry_heap_fields(server_mod):
    box = server_mod._box_diagnostics(timeout=5)
    for key in heap_report.empty_box_fields():
        assert key in box
    if GLIBC:
        assert isinstance(box["heap_in_use_mib"], int)
        assert isinstance(box["heap_arenas"], int) and box["heap_arenas"] >= 1


def test_record_heap_snapshot_stores_the_trim_as_numbers(server_mod):
    summary = server_mod._record_heap_snapshot(
        "post_publish", False, {"available": True, "rssBeforeMib": 900, "rssAfterMib": 700}
    )
    assert summary["written"] is True
    rec = json.loads(heap_report.REPORT_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["reason"] == "post_publish"
    assert rec["extra"] == {"trimRssBeforeMib": 900, "trimRssAfterMib": 700}


def _run_loop_for(server_mod, seconds):
    async def run():
        task = asyncio.create_task(server_mod.heap_report_loop())
        await asyncio.sleep(seconds)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    path = heap_report.REPORT_PATH
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_heap_loop_cadence_and_type_census_schedule(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "HEAP_REPORT_INTERVAL_SEC", 0.02)
    monkeypatch.setattr(server_mod, "HEAP_REPORT_HIGH_RSS_MIB", 10**9)
    records = _run_loop_for(server_mod, 1.5)
    assert len(records) >= 5
    assert records[0]["reason"] == "startup"
    assert records[0]["types"] is not None  # baseline includes the census
    assert {r["reason"] for r in records[1:]} == {"periodic"}
    with_types = [i for i, r in enumerate(records) if r["types"] is not None]
    assert with_types[:2] == [0, server_mod.HEAP_REPORT_TYPES_EVERY]


def test_heap_loop_takes_the_census_when_rss_is_high(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "HEAP_REPORT_INTERVAL_SEC", 0.02)
    monkeypatch.setattr(server_mod, "HEAP_REPORT_HIGH_RSS_MIB", 0)
    records = _run_loop_for(server_mod, 0.6)
    assert records
    assert all(r["reason"] == "periodic_high_rss" and r["types"] is not None for r in records)


def test_heap_loop_disabled_by_zero(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "HEAP_REPORT_INTERVAL_SEC", 0)
    assert asyncio.run(asyncio.wait_for(server_mod.heap_report_loop(), timeout=2)) is None
    assert not heap_report.REPORT_PATH.exists()
