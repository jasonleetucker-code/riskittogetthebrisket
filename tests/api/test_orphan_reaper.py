"""Tests for the orphaned-Chromium reaper.

Safety-critical: this code SIGKILLs processes on the production box.
The suite pins the conservative cmdline predicate, the descendant
scoping (it must never select a non-descendant), a real kill of a
spawned child, and the finalize-path wiring + kill-switch.
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest

import server


# ── cmdline predicate ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "cmd",
    [
        "/root/.cache/ms-playwright/chromium-1124/chrome-linux/chrome "
        "--headless --no-sandbox --remote-debugging-pipe",
        "chromium --headless=new --disable-gpu",
        "/ms-playwright/chromium-1124/chrome-linux/chrome --type=renderer",
        "/usr/bin/chrome --remote-debugging-port=0 --headless",
    ],
)
def test_predicate_matches_playwright_chromium(cmd):
    assert server._looks_like_playwright_chromium(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "/home/dynasty/.venvs/trade-calculator/bin/python server.py",
        "node /app/.next/standalone/server.js",
        "chrome",  # bare binary, no automation marker → conservative no
        'bash -c "echo chromium is great"',
        "sleep 30",
        "",
    ],
)
def test_predicate_rejects_unrelated(cmd):
    assert server._looks_like_playwright_chromium(cmd) is False


# ── descendant scoping ───────────────────────────────────────────────
def test_collect_descendants_includes_child_excludes_init():
    proc = subprocess.Popen(["sleep", "30"])
    try:
        time.sleep(0.2)
        kids = server._collect_descendant_pids(os.getpid())
        assert proc.pid in kids
        assert 1 not in kids  # init/systemd is never our descendant
        assert os.getpid() not in kids  # the root itself is excluded
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_collect_descendants_bogus_root_is_empty():
    # A PID that almost certainly has no children (or doesn't exist).
    assert server._collect_descendant_pids(2**31 - 1) == set()


# ── real kill path ───────────────────────────────────────────────────
def test_reaper_kills_matching_descendant():
    proc = subprocess.Popen(["sleep", "300"])
    try:
        time.sleep(0.2)
        killed = server._reap_orphan_browsers(match=lambda c: "sleep" in c and "300" in c)
        assert killed >= 1
        # Process must actually be dead.
        assert proc.wait(timeout=5) != 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_reaper_spares_non_matching_descendant():
    proc = subprocess.Popen(["sleep", "5"])
    try:
        time.sleep(0.2)
        killed = server._reap_orphan_browsers(match=lambda c: False)
        assert killed == 0
        assert proc.poll() is None  # still alive
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_reaper_never_raises_on_bad_root():
    # Must be best-effort: no descendants, returns 0, no exception.
    assert server._reap_orphan_browsers(root_pid=2**31 - 1) == 0


# ── finalize wiring + kill-switch ────────────────────────────────────
def test_finalize_invokes_reaper_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_reap_orphan_browsers", lambda: calls.append(1) or 0)
    monkeypatch.setattr(server, "SCRAPE_REAP_ORPHAN_BROWSERS", True)
    monkeypatch.setitem(server.scrape_status, "worker_id", "wid-test")
    server._finalize_scrape_run("wid-test")
    assert calls == [1]


def test_finalize_skips_reaper_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_reap_orphan_browsers", lambda: calls.append(1) or 0)
    monkeypatch.setattr(server, "SCRAPE_REAP_ORPHAN_BROWSERS", False)
    monkeypatch.setitem(server.scrape_status, "worker_id", "wid-test")
    server._finalize_scrape_run("wid-test")
    assert calls == []


def test_finalize_wrong_worker_id_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_reap_orphan_browsers", lambda: calls.append(1) or 0)
    monkeypatch.setattr(server, "SCRAPE_REAP_ORPHAN_BROWSERS", True)
    monkeypatch.setitem(server.scrape_status, "worker_id", "owner")
    server._finalize_scrape_run("not-the-owner")
    assert calls == []  # guard returns before the reaper
