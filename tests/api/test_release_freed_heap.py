"""``_release_freed_heap``: hand freed glibc heap back to the OS each scrape.

Website audit WA-05 (2026-11-12): the service cgroup crept above its
``MemoryHigh`` and Chromium could no longer launch.  Replaying 14 publish
cycles showed no Python leak (live objects constant) but an allocator
high-water RSS of 684 MB, 498 MB with a ``malloc_trim(0)`` after each cycle.
"""

from __future__ import annotations

import inspect
import sys

import pytest

import server


def test_unavailable_libc_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(server, "_LIBC_MALLOC_TRIM", False)
    assert server._release_freed_heap() == {
        "available": False,
        "rssBeforeMib": None,
        "rssAfterMib": None,
    }


def test_trims_once_and_reports_rss_around_it(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(server, "_LIBC_MALLOC_TRIM", lambda pad: calls.append(pad) or 1)
    readings = iter([2_000_000, 1_500_000])  # kB
    monkeypatch.setattr(server._proc_probe, "process_rss_kb", lambda pid: next(readings))
    out = server._release_freed_heap()
    assert calls == [0]
    assert out == {"available": True, "rssBeforeMib": 1953, "rssAfterMib": 1464}


def test_unreadable_rss_stays_unknown(monkeypatch):
    monkeypatch.setattr(server, "_LIBC_MALLOC_TRIM", lambda pad: 1)
    monkeypatch.setattr(server._proc_probe, "process_rss_kb", lambda pid: None)
    out = server._release_freed_heap()
    assert out["available"] is True
    assert out["rssBeforeMib"] is None and out["rssAfterMib"] is None


def test_a_failing_trim_never_raises(monkeypatch):
    def boom(_pad):
        raise RuntimeError("allocator says no")

    monkeypatch.setattr(server, "_LIBC_MALLOC_TRIM", boom)
    assert server._release_freed_heap()["available"] is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="glibc malloc_trim")
def test_the_real_call_works_on_glibc(monkeypatch):
    monkeypatch.setattr(server, "_LIBC_MALLOC_TRIM", None)
    out = server._release_freed_heap()
    assert out["available"] is True
    assert isinstance(out["rssAfterMib"], int)


def test_the_scrape_releases_the_heap_before_launch_and_after_publish():
    src = inspect.getsource(server.run_scraper)
    publish = src.index("_prime_latest_payload, result, is_fresh_scrape=True")
    assert "_release_freed_heap" in src[publish : publish + 400]
    first = src.index("_release_freed_heap")
    assert first < src.index('source="import_scraper"'), "release must precede the scraper run"
