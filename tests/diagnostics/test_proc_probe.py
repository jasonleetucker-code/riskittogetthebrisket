"""Pin the /proc probes that both server.py and the sampler depend on.

These parse kernel-format text. The parsing is where a silent wrong
answer would hide (a mis-indexed /proc/<pid>/stat field yields a
plausible-looking number that is actually something else), so the tests
drive real synthetic fixtures rather than asserting "did not crash".
"""

from __future__ import annotations

import os

import pytest

from src.diagnostics import proc_probe


class TestChromiumPredicate:
    @pytest.mark.parametrize(
        "cmdline",
        [
            "/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome --headless --no-first-run",
            "/usr/bin/chromium --remote-debugging-pipe --disable-dev-shm-usage",
            "/opt/playwright/chrome --remote-debugging-port=0",
        ],
    )
    def test_matches_playwright_chromium(self, cmdline):
        assert proc_probe.looks_like_playwright_chromium(cmdline)

    @pytest.mark.parametrize(
        "cmdline",
        [
            "/usr/bin/python3 server.py",
            "nginx: worker process",
            # A real user's desktop browser must never match: the reaper
            # SIGKILLs whatever this predicate accepts.
            "/usr/bin/google-chrome-stable",
            "",
        ],
    )
    def test_rejects_everything_else(self, cmdline):
        assert not proc_probe.looks_like_playwright_chromium(cmdline)


class TestMeminfo:
    def test_parses_selected_keys_as_kb(self, tmp_path, monkeypatch):
        meminfo = tmp_path / "meminfo"
        meminfo.write_text(
            "MemTotal:        4030164 kB\n"
            "MemFree:          210484 kB\n"
            "MemAvailable:     982340 kB\n"
            "Buffers:           31280 kB\n"
            "SwapTotal:       2097148 kB\n"
            "SwapFree:        1048576 kB\n"
            "Hugepagesize:       2048 kB\n"
        )
        monkeypatch.setattr(
            proc_probe, "_read_text", lambda p: meminfo.read_text() if "meminfo" in str(p) else None
        )
        out = proc_probe.read_meminfo()
        assert out["MemTotal"] == 4030164
        assert out["MemAvailable"] == 982340
        assert out["SwapFree"] == 1048576
        assert "Hugepagesize" not in out  # not in the wanted set

    def test_missing_file_yields_empty(self, monkeypatch):
        monkeypatch.setattr(proc_probe, "_read_text", lambda p: None)
        assert proc_probe.read_meminfo() == {}


class TestCpuAndPressure:
    def test_total_cpu_ticks_sums_and_isolates_idle(self, monkeypatch):
        # user nice system idle iowait irq softirq
        line = "cpu  100 20 50 700 30 5 5\n" "cpu0 1 1 1 1 1 1 1\n"
        monkeypatch.setattr(proc_probe, "_read_text", lambda p: line)
        out = proc_probe.read_total_cpu_ticks()
        assert out == {"total": 910, "idle": 730}  # idle 700 + iowait 30

    def test_pressure_parsed_into_scoped_keys(self, monkeypatch):
        psi = "some avg10=12.34 avg60=5.00 avg300=1.00 total=123456\n"
        psi += "full avg10=6.00 avg60=2.00 avg300=0.50 total=654321\n"
        monkeypatch.setattr(proc_probe, "_read_text", lambda p: psi)
        out = proc_probe.read_pressure("memory")
        assert out["some_avg10"] == 12.34
        assert out["full_total"] == 654321.0

    def test_pressure_absent_on_kernels_without_psi(self, monkeypatch):
        monkeypatch.setattr(proc_probe, "_read_text", lambda p: None)
        assert proc_probe.read_pressure("memory") is None


class TestCgroupMetrics:
    def test_reads_limits_and_the_decisive_oom_counters(self, tmp_path):
        cg = tmp_path / "dynasty.service"
        cg.mkdir()
        (cg / "memory.current").write_text("2684354560\n")
        (cg / "memory.max").write_text("3221225472\n")
        (cg / "memory.peak").write_text("3221225472\n")
        (cg / "memory.events").write_text("low 0\nhigh 4211\nmax 97\noom 3\noom_kill 2\n")
        (cg / "cpu.stat").write_text(
            "usage_usec 12345\nnr_periods 10\nnr_throttled 4\nthrottled_usec 999\n"
        )

        out = proc_probe.read_cgroup_metrics(cg)
        assert out["memory.current"] == 2684354560
        assert out["memory.max"] == 3221225472
        # These two are the fields that settle the OOM question outright.
        assert out["memory.events"]["oom_kill"] == 2
        assert out["memory.events"]["max"] == 97
        assert out["cpu.stat"]["nr_throttled"] == 4

    def test_unlimited_memory_max_stays_distinguishable_from_a_number(self, tmp_path):
        cg = tmp_path / "unlimited"
        cg.mkdir()
        (cg / "memory.max").write_text("max\n")
        assert proc_probe.read_cgroup_metrics(cg)["memory.max"] == "max"

    def test_no_cgroup_yields_empty(self):
        assert proc_probe.read_cgroup_metrics(None) == {}


class TestProcessTree:
    def test_reads_this_process(self):
        me = os.getpid()
        assert proc_probe.pid_alive(me)
        assert (proc_probe.process_rss_kb(me) or 0) > 0
        assert proc_probe.process_cpu_ticks(me) is not None

    def test_vanished_pid_reports_absent_without_raising(self):
        # PID 0 never exists as a /proc entry on Linux.
        assert not proc_probe.pid_alive(0)
        assert proc_probe.process_rss_kb(0) is None
        assert proc_probe.process_cpu_ticks(0) is None

    def test_sample_process_tree_shape_and_self_inclusion(self):
        out = proc_probe.sample_process_tree(os.getpid())
        assert out["pid_alive"] is True
        assert out["app_proc_count"] >= 1
        assert out["app_rss_kb"] > 0
        # No Playwright running under pytest.
        assert out["chromium_proc_count"] == 0
        assert out["chromium_rss_kb"] == 0

    def test_sample_process_tree_on_dead_pid_is_not_an_exception(self):
        out = proc_probe.sample_process_tree(0)
        assert out["pid_alive"] is False
        assert out["app_rss_kb"] == 0

    def test_descendant_walk_finds_a_real_child(self):
        import subprocess
        import sys
        import time

        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            deadline = time.time() + 5
            while time.time() < deadline:
                if child.pid in proc_probe.collect_descendant_pids(os.getpid()):
                    break
                time.sleep(0.05)
            assert child.pid in proc_probe.collect_descendant_pids(os.getpid())
        finally:
            child.kill()
            child.wait(timeout=5)
