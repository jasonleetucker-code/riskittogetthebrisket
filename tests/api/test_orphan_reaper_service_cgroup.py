"""Service-cgroup reaping + numbers-only box diagnostics, on FAKE /proc trees.

Nothing here touches a real process: ``os.kill`` is replaced by a recorder and
``/proc`` + ``/sys/fs/cgroup`` are pointed at ``tmp_path``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import server
from src.diagnostics import proc_probe

CHROME = (
    "/home/u/.cache/ms-playwright/chromium-1/chrome-linux/chrome --headless --remote-debugging-pipe"
)
SELF = 4000


def _proc(root: Path, pid: int, ppid: int, cmd: str, cgroup: str) -> None:
    d = root / str(pid)
    d.mkdir()
    comm = "chrome" if cmd.split()[0].endswith("/chrome") else "python"
    (d / "stat").write_text(f"{pid} ({comm}) S {ppid} 0 0\n", encoding="utf-8")
    (d / "cmdline").write_bytes(cmd.replace(" ", "\0").encode())
    (d / "cgroup").write_text(f"0::{cgroup}\n", encoding="utf-8")


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    cg = tmp_path / "cg"
    proc.mkdir()
    svc = cg / "system.slice" / "dynasty.service"
    svc.mkdir(parents=True)
    monkeypatch.setattr(proc_probe, "PROC_ROOT", str(proc))
    monkeypatch.setattr(proc_probe, "CGROUP_ROOT", cg)
    monkeypatch.setattr(os, "getpid", lambda: SELF)
    monkeypatch.setenv("SCRAPE_REAP_SERVICE_CGROUP", "1")
    monkeypatch.delenv("SYSTEMD_EXEC_PID", raising=False)
    kills: list[int] = []
    monkeypatch.setattr(server.os, "kill", lambda pid, sig: kills.append(pid))
    svcname = "/system.slice/dynasty.service"
    _proc(proc, SELF, 1, "python server.py", svcname)
    _proc(proc, 4100, SELF, CHROME, svcname)  # descendant chromium
    _proc(proc, 4200, 1, CHROME, svcname)  # REPARENTED chromium, same cgroup
    _proc(proc, 4300, 1, "python other.py", svcname)  # non-chromium service member
    _proc(proc, 5000, 1, CHROME, "/user.slice/session-3.scope")  # foreign chromium
    (svc / "cgroup.procs").write_text("4000\n4100\n4200\n4300\n", encoding="utf-8")
    (svc / "memory.current").write_text("1048576\n", encoding="utf-8")
    (svc / "memory.max").write_text("3221225472\n", encoding="utf-8")
    (svc / "pids.current").write_text("7\n", encoding="utf-8")
    (svc / "pids.max").write_text("max\n", encoding="utf-8")
    return proc, svc, kills


def test_descendant_only_reaper_misses_reparented(fake):
    _, _, kills = fake
    assert server._reap_orphan_browsers(root_pid=SELF) == 1
    assert kills == [4100]


def test_cgroup_reaper_catches_reparented_and_spares_foreign(fake):
    _, _, kills = fake
    assert server._reap_orphan_browsers(root_pid=SELF, include_service_cgroup=True) == 2
    assert sorted(kills) == [4100, 4200]
    assert SELF not in kills and 4300 not in kills and 5000 not in kills


def test_non_service_cgroup_is_never_swept(fake, tmp_path):
    proc, svc, kills = fake
    scope = tmp_path / "cg" / "user.slice" / "session-3.scope"
    scope.mkdir(parents=True)
    (scope / "cgroup.procs").write_text("5000\n4000\n", encoding="utf-8")
    (proc / str(SELF) / "cgroup").write_text("0::/user.slice/session-3.scope\n", encoding="utf-8")
    assert proc_probe.service_cgroup_dir(SELF) is None
    server._reap_orphan_browsers(root_pid=SELF, include_service_cgroup=True)
    assert 5000 not in kills


def test_diagnostics_are_numbers_only(fake):
    d = proc_probe.service_diagnostics(SELF, tmp_dir=str(fake[1]), shm_dir=str(fake[1]))
    assert d["chromium_processes"] == 2
    assert d["chromium_reparented"] == 1
    assert d["cgroup_memory_current_mib"] == 1
    assert d["cgroup_memory_max_mib"] == 3072
    assert d["cgroup_pids_current"] == 7
    assert d["cgroup_pids_max"] is None  # "max" = unlimited, not a number
    assert all(v is None or isinstance(v, int) for v in d.values())


def test_diagnostics_report_the_throttling_line_and_the_process_alone(fake):
    """memory.high is where the kernel starts throttling the whole cgroup
    (website audit WA-05: 2.57 GiB against a 2.56 GiB high, Chromium could no
    longer launch); the cgroup total alone could not show it."""
    proc, svc, _ = fake
    (svc / "memory.high").write_text(str(2560 * 1024 * 1024) + "\n", encoding="utf-8")
    (svc / "memory.events").write_text("low 0\nhigh 4217\nmax 0\noom 0\n", encoding="utf-8")
    (proc / str(SELF) / "status").write_text(
        "Name:\tpython\nVmRSS:\t 2150400 kB\n", encoding="utf-8"
    )
    (svc / "memory.stat").write_text(
        f"anon {1800 * 1024 * 1024}\nfile {700 * 1024 * 1024}\nshmem 0\n", encoding="utf-8"
    )
    d = proc_probe.service_diagnostics(SELF, tmp_dir=str(svc), shm_dir=str(svc))
    assert d["cgroup_memory_high_mib"] == 2560
    assert d["cgroup_memory_high_events"] == 4217
    assert d["process_rss_mib"] == 2100
    # Heap the kernel cannot drop vs page cache it can.
    assert d["cgroup_memory_anon_mib"] == 1800
    assert d["cgroup_memory_file_mib"] == 700
    assert all(v is None or isinstance(v, int) for v in d.values())


def test_no_high_limit_and_no_events_are_unknown_not_zero(fake):
    proc, svc, _ = fake
    (svc / "memory.high").write_text("max\n", encoding="utf-8")
    d = proc_probe.service_diagnostics(SELF, tmp_dir=str(svc), shm_dir=str(svc))
    assert d["cgroup_memory_high_mib"] is None  # "max" = no throttling line
    assert d["cgroup_memory_high_events"] is None  # no memory.events file
    assert d["process_rss_mib"] is None  # no /proc/<pid>/status
    assert d["cgroup_memory_anon_mib"] is None  # no memory.stat
    assert d["cgroup_memory_file_mib"] is None


def test_the_headless_shell_counts_by_its_kernel_name(fake):
    """Playwright's headless browser is ``chrome-headless-shell``; the kernel
    keeps 15 characters of a process name, so ``comm`` reads
    ``chrome-headless``.  Measured 2026-11-12: ``chromium.launch()`` with the
    installed Playwright build left four processes, every one with ``comm``
    ``chrome-headless``."""
    proc, svc, _ = fake
    shell = proc / "4400"
    shell.mkdir()
    (shell / "stat").write_text(f"4400 (chrome-headless) S {SELF} 0 0\n", encoding="utf-8")
    (shell / "cmdline").write_bytes(
        b"/r/ms-playwright/chromium_headless_shell-1/chrome-headless-shell\0--headless"
    )
    (shell / "cgroup").write_text("0::/system.slice/dynasty.service\n", encoding="utf-8")
    (svc / "cgroup.procs").write_text("4000\n4100\n4200\n4300\n4400\n", encoding="utf-8")
    d = proc_probe.service_diagnostics(SELF, tmp_dir=str(svc), shm_dir=str(svc))
    assert d["chromium_processes"] == 3  # 4100, the reparented 4200, and 4400
    assert proc_probe.read_comm(4400) in proc_probe._BROWSER_COMMS


def test_diagnostics_never_raise_without_proc(monkeypatch, tmp_path):
    monkeypatch.setattr(proc_probe, "PROC_ROOT", str(tmp_path / "nope"))
    d = proc_probe.service_diagnostics(SELF)
    assert d["chromium_processes"] == 0
    assert d["cgroup_memory_current_mib"] is None


def test_prelaunch_reap_runs_inside_scrape_and_respects_switch(monkeypatch):
    import asyncio

    calls: list[bool] = []

    def fake_reap(*a, **kw):
        calls.append(bool(kw.get("include_service_cgroup")))
        return 0

    async def boom(*a, **kw):
        raise RuntimeError("stop after prelaunch")

    monkeypatch.setattr(server, "_reap_orphan_browsers", fake_reap)
    monkeypatch.setattr(server, "_box_diagnostics", lambda: {"chromium_processes": 0})
    monkeypatch.setattr(
        server, "_import_scraper_module", lambda: (_ for _ in ()).throw(RuntimeError("x"))
    )
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: None)

    monkeypatch.setattr(server, "SCRAPE_REAP_ORPHAN_BROWSERS", True)
    asyncio.run(server.run_scraper("test"))
    # once before launch, once in finalize -- both service-cgroup aware
    assert calls == [True, True]
    assert server.scrape_history[-1]["box"] == {"chromium_processes": 0}

    calls.clear()
    monkeypatch.setattr(server, "SCRAPE_REAP_ORPHAN_BROWSERS", False)
    asyncio.run(server.run_scraper("test"))
    assert calls == []


def test_no_opt_in_means_descendant_only(fake, monkeypatch):
    _, _, kills = fake
    monkeypatch.delenv("SCRAPE_REAP_SERVICE_CGROUP")
    assert proc_probe.sweep_cgroup_dir(SELF) is None
    assert server._reap_orphan_browsers(root_pid=SELF, include_service_cgroup=True) == 1
    assert kills == [4100]


def test_non_main_process_never_sweeps(fake, monkeypatch):
    _, _, kills = fake
    monkeypatch.setenv("SYSTEMD_EXEC_PID", "999")  # inherited from a parent service
    assert proc_probe.sweep_cgroup_dir(SELF) is None
    server._reap_orphan_browsers(root_pid=SELF, include_service_cgroup=True)
    assert kills == [4100]
    assert proc_probe.sweep_cgroup_dir(SELF + 1) is None  # not this process


def test_e2e_runner_and_node_are_never_killed(fake):
    proc, svc, kills = fake
    cg = "/system.slice/dynasty.service"
    _proc(
        proc, 4400, SELF, "node /w/node_modules/.bin/playwright test --project=mobile-chromium", cg
    )
    _proc(proc, 4500, 1, "/usr/bin/node /x/playwright/cli.js test --headless chromium", cg)
    _proc(proc, 4600, 1, "npx playwright test --project=mobile-chromium", cg)
    (svc / "cgroup.procs").write_text("4000\n4100\n4200\n4400\n4500\n4600\n", encoding="utf-8")
    server._reap_orphan_browsers(root_pid=SELF, include_service_cgroup=True)
    assert sorted(kills) == [4100, 4200]


@pytest.mark.parametrize(
    "cmd",
    [
        "node playwright test --project=mobile-chromium",
        "npx playwright test --headless",
        "/usr/bin/node /x/chromium-runner.js --headless",
        "python -m pytest --headless chrome",
    ],
)
def test_predicate_rejects_runners(cmd):
    assert not proc_probe.looks_like_playwright_chromium(cmd)


def test_predicate_accepts_headless_shell():
    assert proc_probe.looks_like_playwright_chromium(
        "/r/.cache/ms-playwright/chromium_headless_shell-1/chrome-linux/headless_shell --headless"
    )


def test_blocked_probe_returns_nulls_within_timeout(monkeypatch):
    import threading
    import time

    gate = threading.Event()
    monkeypatch.setattr(proc_probe, "service_diagnostics", lambda pid: gate.wait(10) or {})
    t0 = time.monotonic()
    out = server._box_diagnostics(timeout=0.2)
    assert time.monotonic() - t0 < 2
    assert out == proc_probe.empty_service_diagnostics()
    assert all(v is None for v in out.values())
    gate.set()


def test_box_at_failure_has_captured_at(monkeypatch):
    monkeypatch.setattr(server, "_box_diagnostics", lambda: {"chromium_processes": 0})
    server._mark_scrape_failure(RuntimeError("x"), 1.0)
    snap = server.scrape_status["box_at_failure"]
    assert snap["chromium_processes"] == 0
    assert snap["capturedAt"].startswith("20")
