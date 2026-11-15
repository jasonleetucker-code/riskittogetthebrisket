"""The liveness watchdog records the backend cgroup's counters before they die.

The 2026-10-19 08:42 UTC restart was ``dynasty-healthcheck`` (three
no-response probes, SIGTERM ignored, SIGKILL).  Why the process stopped
answering stayed at LIKELY memory throttling, not proven, because the dead
process's ``memory.events`` / ``memory.pressure`` vanished with its cgroup.
``deploy/systemd/dynasty-healthcheck.sh`` now logs those counters on every
LIVENESS FAIL and immediately before it restarts.

These tests run the REAL script against a fake cgroup tree, a fake /proc and
stubbed ``curl`` / ``systemctl`` / ``py-spy``, and pin:

* the snapshot lines carry the cgroup's values, in order, before the restart;
* nothing about the restart decision changed (same calls, same counter);
* missing or hostile files degrade to ``na`` and never break the script;
* every snapshot line passes the public restart-diagnostics allowlist and
  fits its 300-character cut, and a non-numeric value cannot pass it.
"""

from __future__ import annotations

import sys
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "systemd" / "dynasty-healthcheck.sh"
DIAG = REPO / "deploy" / "diagnostics" / "prod_restart_diagnostics.sh"

# A realistic journal prefix (timestamp, hostname, unit[pid]) as the
# diagnostics workflow sees it; its 300-character cut applies to the whole
# line.
JOURNAL_PREFIX = "2026-10-19T08:42:13.818000+00:00 vmi3454985 dynasty-healthcheck.sh[1234567]: "

# A PID that does not exist, so fd_watch reads nothing from the real /proc.
FAKE_PID = "3999999"

CGROUP_FILES = {
    "memory.current": "2791728742\n",
    "memory.peak": "2791728742\n",
    "memory.high": "2684354560\n",
    "memory.max": "3221225472\n",
    "memory.events": "low 0\nhigh 781\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n",
    "memory.stat": "anon 2400000000\nfile 300000000\nkernel 80000000\nsock 1000\nshmem 4096\n",
    "memory.pressure": (
        "some avg10=91.50 avg60=80.25 avg300=40.00 total=812345678\n"
        "full avg10=88.00 avg60=71.23 avg300=35.00 total=793685741\n"
    ),
    "cpu.pressure": (
        "some avg10=12.00 avg60=10.00 avg300=5.00 total=31918902\n"
        "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
    ),
    "io.pressure": (
        "some avg10=1.00 avg60=2.00 avg300=3.00 total=24329813\n"
        "full avg10=0.50 avg60=1.00 avg300=1.50 total=18393293\n"
    ),
}


def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def host(tmp_path):
    """A fake host: stub binaries, a cgroup tree, a /proc and a state dir."""
    if sys.platform == "win32":
        # Every test using this fixture runs the production healthcheck through
        # bash against stub binaries addressed by POSIX path.  Git Bash on
        # Windows strips the backslashes from those paths: the stubs are never
        # found, some tests pass for the wrong reason, and the script writes
        # stray ``C:Users...systemctl.calls`` files into the checkout.  Linux-only;
        # never skipped on Linux/CI.
        pytest.skip("Linux-only: drives the production healthcheck shell script")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "systemctl.calls"
    curl_rc = tmp_path / "curl.rc"
    curl_rc.write_text("28", encoding="utf-8")
    _write_exec(
        bin_dir / "curl",
        f'rc="$(cat {curl_rc})"\n' 'if [[ "$rc" == "0" ]]; then printf 200; fi\n' 'exit "$rc"\n',
    )
    _write_exec(
        bin_dir / "systemctl",
        f'printf "%s\\n" "$*" >> {calls}\n'
        'case "$*" in\n'
        '  *"-p ControlGroup --value"*) echo /system.slice/dynasty.service ;;\n'
        f'  *"-p MainPID --value"*) echo {FAKE_PID} ;;\n'
        "esac\n"
        "exit 0\n",
    )
    cg_root = tmp_path / "cgroup"
    cg = cg_root / "system.slice" / "dynasty.service"
    cg.mkdir(parents=True)
    for name, text in CGROUP_FILES.items():
        (cg / name).write_text(text, encoding="utf-8")
    proc = tmp_path / "proc"
    (proc / "pressure").mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal:        8131764 kB\nMemFree:         6059952 kB\nMemAvailable:    4710000 kB\n",
        encoding="utf-8",
    )
    (proc / "pressure" / "memory").write_text(
        "some avg10=60.00 avg60=58.00 avg300=70.00 total=800000000\n"
        "full avg10=55.00 avg60=54.89 avg300=71.23 total=793685741\n",
        encoding="utf-8",
    )
    state = tmp_path / "state"

    class Host:
        root = tmp_path

        def __init__(self):
            self.bin = bin_dir
            self.cg = cg
            self.cg_root = cg_root
            self.proc = proc
            self.state = state
            self.calls = calls
            self.curl_rc = curl_rc

        def run(self, **extra_env):
            env = {
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
                "HEALTH_STATE_DIR": str(state),
                "HEALTH_CGROUP_ROOT": str(cg_root),
                "HEALTH_PROC_ROOT": str(proc),
                "HEALTH_SERVICE": "dynasty",
            }
            env.update(extra_env)
            res = subprocess.run(
                ["bash", str(SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return res

        def systemctl_actions(self):
            if not self.calls.exists():
                return []
            return [
                line
                for line in self.calls.read_text(encoding="utf-8").splitlines()
                if not line.startswith("show ")
            ]

    return Host()


def _snapshot_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("[healthcheck] snapshot ")]


def _kv(line: str) -> dict[str, str]:
    return dict(tok.split("=", 1) for tok in line.split()[2:] if "=" in tok)


def test_script_parses():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_alive_probe_logs_no_snapshot(host):
    host.curl_rc.write_text("0", encoding="utf-8")
    res = host.run()
    assert res.returncode == 0, res.stderr
    assert _snapshot_lines(res.stdout) == []
    assert host.systemctl_actions() == []


def test_every_liveness_fail_records_the_cgroup_counters(host):
    res = host.run()
    assert res.returncode == 0, res.stderr
    lines = _snapshot_lines(res.stdout)
    kinds = [line.split()[2] for line in lines]
    assert kinds == ["mem", "stat", "psi_memory", "psi_cpu", "psi_io", "host"]
    assert all("reason=liveness-fail-1" in line for line in lines)
    by_kind = {line.split()[2]: _kv(line) for line in lines}
    assert by_kind["mem"] == {
        "reason": "liveness-fail-1",
        "cur": "2791728742",
        "peak": "2791728742",
        "high": "2684354560",
        "max": "3221225472",
        "ev_high": "781",
        "ev_max": "0",
        "ev_oom": "0",
        "ev_oom_kill": "0",
    }
    assert by_kind["stat"]["anon"] == "2400000000"
    assert by_kind["stat"]["file"] == "300000000"
    assert by_kind["psi_memory"]["full_total"] == "793685741"
    assert by_kind["psi_memory"]["full_avg60"] == "71.23"
    assert by_kind["psi_cpu"]["some_total"] == "31918902"
    assert by_kind["psi_io"]["full_avg10"] == "0.50"
    assert by_kind["host"]["mem_available_kb"] == "4710000"
    assert by_kind["host"]["h_full_total"] == "793685741"
    # The FAIL line comes first, and no restart below the threshold.
    out = res.stdout
    assert out.index("LIVENESS FAIL 1/3") < out.index("[healthcheck] snapshot mem")
    assert host.systemctl_actions() == []


def test_snapshot_precedes_the_restart_and_the_restart_is_unchanged(host):
    for _ in range(2):
        assert host.run().returncode == 0
    res = host.run()
    assert res.returncode == 0, res.stderr
    out = res.stdout
    lines = _snapshot_lines(out)
    assert sum("reason=liveness-fail-3" in line for line in lines) == 6
    assert sum("reason=pre-restart" in line for line in lines) == 6
    # Order: FAIL 3/3 -> its snapshot -> threshold -> pre-restart snapshot
    # -> the restart.
    i_fail = out.index("LIVENESS FAIL 3/3")
    i_threshold = out.index("threshold reached")
    i_pre = out.index("snapshot mem reason=pre-restart")
    i_issued = out.index("restart issued for dynasty.service")
    assert i_fail < out.index("snapshot mem reason=liveness-fail-3") < i_threshold < i_pre
    assert i_pre < i_issued
    # The restart decision itself: exactly what it always was.
    assert host.systemctl_actions() == [
        "reset-failed dynasty.service",
        "restart dynasty.service",
    ]
    assert (host.state / "consecutive-failures").read_text(encoding="utf-8").strip() == "0"


def test_missing_cgroup_files_degrade_to_na_and_never_block_the_restart(host):
    for f in host.cg.iterdir():
        f.unlink()
    host.cg.rmdir()
    (host.proc / "meminfo").unlink()
    (host.proc / "pressure" / "memory").unlink()
    for _ in range(3):
        res = host.run()
        assert res.returncode == 0, res.stderr
    lines = _snapshot_lines(res.stdout)
    assert lines, "snapshot lines are still emitted"
    for line in lines:
        values = [v for k, v in _kv(line).items() if k != "reason"]
        assert values and all(v == "na" for v in values), line
    assert host.systemctl_actions() == [
        "reset-failed dynasty.service",
        "restart dynasty.service",
    ]


def test_unexpected_file_content_is_never_echoed(host):
    (host.cg / "memory.current").write_text("SECRETMARK=1 cookie\n", encoding="utf-8")
    (host.cg / "memory.events").write_text("high SECRETMARK\nmax 1;rm\n", encoding="utf-8")
    (host.cg / "memory.pressure").write_text("some avg10=$(id) total=x\n", encoding="utf-8")
    res = host.run()
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "SECRETMARK" not in out and "$(id)" not in out and ";rm" not in out
    mem = _kv(next(line for line in _snapshot_lines(out) if " mem " in line))
    assert mem["cur"] == "na" and mem["ev_high"] == "na" and mem["ev_max"] == "na"


def test_unlimited_cgroup_knob_logs_max(host):
    (host.cg / "memory.high").write_text("max\n", encoding="utf-8")
    res = host.run()
    mem = _kv(next(line for line in _snapshot_lines(res.stdout) if " mem " in line))
    assert mem["high"] == "max"


def test_pyspy_dump_only_when_installed_and_only_before_restart(host):
    _write_exec(
        host.bin / "py-spy",
        'printf "Thread 1 (idle): MainThread\\n    run (asyncio/base_events.py:600)\\n"\n',
    )
    for _ in range(2):
        host.run()
    assert not list(host.state.glob("pyspy-*.txt")), "no dump below the threshold"
    res = host.run()
    assert res.returncode == 0, res.stderr
    dumps = list(host.state.glob("pyspy-*.txt"))
    assert len(dumps) == 1
    assert "MainThread" in dumps[0].read_text(encoding="utf-8")
    receipt = [line for line in _snapshot_lines(res.stdout) if " pyspy " in line]
    assert len(receipt) == 1 and _kv(receipt[0])["rc"] == "0"
    # Stack frames stay in the state dir, out of the journal.
    assert "MainThread" not in res.stdout
    assert res.stdout.index("snapshot pyspy") < res.stdout.index("restart issued")


def test_pyspy_that_ignores_sigterm_is_killed_and_never_blocks_the_restart(host):
    # A plain ``timeout`` only SENDS SIGTERM; a py-spy that ignores it would
    # hold the restart open past the unit's TimeoutStartSec.  ``-k`` makes the
    # bound hard: SIGTERM at HEALTH_PYSPY_TIMEOUT, SIGKILL after the grace.
    _write_exec(host.bin / "py-spy", "trap '' TERM\nexec sleep 30\n")
    for _ in range(2):
        host.run(HEALTH_PYSPY_TIMEOUT="1", HEALTH_PYSPY_KILL_AFTER="1")
    started = time.monotonic()
    res = host.run(HEALTH_PYSPY_TIMEOUT="1", HEALTH_PYSPY_KILL_AFTER="1")
    elapsed = time.monotonic() - started
    assert res.returncode == 0, res.stderr
    assert elapsed < 15, f"py-spy held the restart for {elapsed:.1f}s"
    receipt = [line for line in _snapshot_lines(res.stdout) if " pyspy " in line]
    assert len(receipt) == 1 and _kv(receipt[0])["rc"] == "137"
    assert "restart issued" in res.stdout
    assert any(a.startswith("restart ") for a in host.systemctl_actions())


def test_pyspy_can_be_disabled(host):
    _write_exec(host.bin / "py-spy", "echo should-not-run\n")
    for _ in range(3):
        host.run(HEALTH_PYSPY="0")
    assert not list(host.state.glob("pyspy-*.txt"))


def test_pyspy_absent_is_silent(host):
    for _ in range(3):
        res = host.run()
    assert " pyspy " not in res.stdout


def _diag_filter(text: str) -> list[str]:
    res = subprocess.run(
        ["bash", str(DIAG), "--filter", "healthcheck"],
        input=text,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return [line for line in res.stdout.splitlines() if line]


def test_snapshot_lines_pass_the_public_diagnostics_allowlist_whole(host):
    # Worst-case widths: 13-digit counters and 100.00 averages.
    big = "9" * 13
    (host.cg / "memory.current").write_text(big + "\n", encoding="utf-8")
    (host.cg / "memory.peak").write_text(big + "\n", encoding="utf-8")
    (host.cg / "memory.events").write_text(
        f"high {big}\nmax {big}\noom {big}\noom_kill {big}\n", encoding="utf-8"
    )
    (host.cg / "memory.stat").write_text(
        "".join(f"{k} {big}\n" for k in ("anon", "file", "shmem", "kernel", "sock")),
        encoding="utf-8",
    )
    psi = f"some avg10=100.00 avg60=100.00 avg300=100.00 total={big}\n" * 1 + (
        f"full avg10=100.00 avg60=100.00 avg300=100.00 total={big}\n"
    )
    for f in ("memory.pressure", "cpu.pressure", "io.pressure"):
        (host.cg / f).write_text(psi, encoding="utf-8")
    (host.proc / "pressure" / "memory").write_text(psi, encoding="utf-8")
    _write_exec(host.bin / "py-spy", "echo frame\n")
    for _ in range(3):
        res = host.run()
    lines = _snapshot_lines(res.stdout)
    assert len(lines) == 13  # 6 fail + 6 pre-restart + pyspy receipt
    journal = "".join(JOURNAL_PREFIX + line + "\n" for line in lines)
    kept = _diag_filter(journal)
    assert kept == [JOURNAL_PREFIX + line for line in lines], "every line kept, uncut"
    assert all(len(line) <= 300 for line in kept)


@pytest.mark.parametrize(
    "line",
    [
        "[healthcheck] snapshot mem reason=pre-restart cur=1 token=SECRETMARK",
        "[healthcheck] snapshot mem reason=pre-restart cur=1 note=a b",
        "[healthcheck] snapshot mem reason=evil cur=1",
        "[healthcheck] snapshot shell reason=pre-restart cur=1",
        "[healthcheck] snapshot mem reason=pre-restart",
    ],
)
def test_diagnostics_allowlist_rejects_non_numeric_snapshot_lines(line):
    assert _diag_filter(JOURNAL_PREFIX + line + "\n") == []
