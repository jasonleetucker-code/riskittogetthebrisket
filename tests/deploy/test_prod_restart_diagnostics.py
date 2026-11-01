"""The restart diagnostic prints lifecycle facts and counts, never app log lines.

``deploy/diagnostics/prod_restart_diagnostics.sh`` reads the production
journal around the 2026-10-19 stall (or any window).  This repository, its
Actions logs and their artifacts are PUBLIC, and the application journal
carries request lines with query strings, and can carry cookies, tokens and
bodies in tracebacks.  So the script prints only allowlisted LIFECYCLE lines
(systemd, kernel OOM, the watchdog's verdicts, uvicorn's start/stop banners)
and reduces everything else to per-minute integers.

These tests feed the real script synthetic journal text salted with secrets,
both through its filter entry points and through a full run against stubbed
``sudo`` / ``journalctl`` / ``systemctl``, and pin the workflow that runs it.
"""

from __future__ import annotations

import sys
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

# POSIX executable bit; Windows does not record file modes.
# Never skipped on Linux/CI.
_LINUX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="Linux-only: POSIX executable bit")


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "diagnostics" / "prod_restart_diagnostics.sh"
WORKFLOW = REPO / ".github" / "workflows" / "prod-restart-diagnostics.yml"

SECRET = "SECRETMARK"

# A mixed journal: the lifecycle story of a watchdog restart, plus every
# kind of application line that must never be echoed.
SERVICE_JOURNAL = f"""\
2026-10-19T08:39:31.000001+00:00 vps python[4242]: INFO:     127.0.0.1:5555 - "GET /api/health HTTP/1.1" 200 OK
2026-10-19T08:39:32.000001+00:00 vps python[4242]: INFO:     10.0.0.1:5555 - "POST /api/trade/analyze?token={SECRET}1 HTTP/1.1" 504 Gateway Timeout
2026-10-19T08:39:33.000001+00:00 vps python[4242]: 2026-10-19 08:39:33 [WARNING] Uptime check failed (2/2): TimeoutError: timed out
2026-10-19T08:39:34.000001+00:00 vps python[4242]: 2026-10-19 08:39:34 [INFO] Shutting down scrape, cookie jason_session={SECRET}2
2026-10-19T08:39:35.000001+00:00 vps python[4242]: Started GET /api/data?leagueKey={SECRET}3
2026-10-19T08:39:36.000001+00:00 vps python[4242]: INFO:     Started server process [1] extra {SECRET}4
2026-10-19T08:41:37.000001+00:00 vps python[4242]: 2026-10-19 08:41:37 [ERROR] Failed to send alert email: [Errno 110] Connection timed out
2026-10-19T08:41:38.000001+00:00 vps python[4242]: Traceback (most recent call last):
2026-10-19T08:41:38.100001+00:00 vps python[4242]:   File "server.py", line 1, in body={{"password": "{SECRET}5"}}
2026-10-19T08:42:15.200001+00:00 vps systemd[1]: Stopping dynasty.service - Dynasty Trade Calculator (dynasty)...
2026-10-19T08:42:15.300001+00:00 vps python[4242]: INFO:     Shutting down
2026-10-19T08:42:45.300001+00:00 vps systemd[1]: dynasty.service: State 'stop-sigterm' timed out. Killing.
2026-10-19T08:42:45.300002+00:00 vps systemd[1]: dynasty.service: Killing process 4242 (python) with signal SIGKILL.
2026-10-19T08:42:45.400001+00:00 vps systemd[1]: dynasty.service: Main process exited, code=killed, status=9/KILL
2026-10-19T08:42:45.400002+00:00 vps systemd[1]: dynasty.service: Failed with result 'timeout'.
2026-10-19T08:42:45.400003+00:00 vps systemd[1]: dynasty.service: Consumed 2h 1min CPU time, 2.7G memory peak.
2026-10-19T08:42:45.500001+00:00 vps systemd[1]: Started dynasty.service - Dynasty Trade Calculator (dynasty).
2026-10-19T08:42:46.000001+00:00 vps python[5151]: INFO:     Started server process [5151]
2026-10-19T08:42:46.100001+00:00 vps python[5151]: INFO:     Waiting for application startup.
2026-10-19T08:42:49.000001+00:00 vps python[5151]: INFO:     Application startup complete.
2026-10-19T08:42:49.100001+00:00 vps python[5151]: INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
"""

HEALTHCHECK_JOURNAL = f"""\
2026-10-19T08:40:00.000001+00:00 vps systemd[1]: Starting dynasty-healthcheck.service - Dynasty backend liveness watchdog...
2026-10-19T08:40:15.000001+00:00 vps dynasty-healthcheck.sh[900]: [healthcheck] LIVENESS FAIL 1/3: no HTTP response from http://127.0.0.1:8000/api/health (curl exit 28)
2026-10-19T08:40:16.000001+00:00 vps systemd[1]: dynasty-healthcheck.service: Deactivated successfully.
2026-10-19T08:41:15.000001+00:00 vps dynasty-healthcheck.sh[901]: [healthcheck] LIVENESS FAIL 2/3: no HTTP response from http://127.0.0.1:8000/api/health (curl exit 28)
2026-10-19T08:42:15.000001+00:00 vps dynasty-healthcheck.sh[902]: [healthcheck] LIVENESS FAIL 3/3: no HTTP response from http://127.0.0.1:8000/api/health (curl exit 28)
2026-10-19T08:42:15.100001+00:00 vps dynasty-healthcheck.sh[902]: [healthcheck] threshold reached — restarting dynasty.service
2026-10-19T08:42:15.250001+00:00 vps dynasty-healthcheck.sh[902]: [healthcheck] restart issued for dynasty.service
2026-10-19T08:42:16.000001+00:00 vps dynasty-healthcheck.sh[902]: debug cookie={SECRET}6
"""

KERNEL_JOURNAL = f"""\
2026-10-19T08:40:30.000001+00:00 vps kernel: python3 invoked oom-killer: gfp_mask=0xcc0(GFP_KERNEL), order=0, oom_score_adj=0
2026-10-19T08:40:30.000002+00:00 vps kernel: [  4242]  1000  4242   900000   700000  python3 {SECRET}7
2026-10-19T08:40:30.000003+00:00 vps kernel: Memory cgroup out of memory: Killed process 4242 (python3) total-vm:3600000kB
2026-10-19T08:40:31.000001+00:00 vps sshd[77]: Accepted publickey for dynasty {SECRET}8
"""

# Every line the script may print from the journal has one of these shapes.
_TS = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)? \S+ "
_ALLOWED_SHAPES = [
    re.compile(_TS + r"systemd\[1\]: "),
    re.compile(_TS + r"kernel: "),
    re.compile(_TS + r"systemd-oomd\[\d+\]: "),
    re.compile(_TS + r"\S+\[\d+\]: \[healthcheck\] "),
    re.compile(
        _TS + r"\S+\[\d+\]: (INFO|WARNING|ERROR):? +(Started server process \[\d+\]|"
        r"Waiting for application startup\.|Application startup complete\.|Shutting down|"
        r"Waiting for application shutdown\.|Application shutdown complete\.|"
        r"Finished server process \[\d+\]|Uvicorn running on \S+ \(Press CTRL\+C to quit\))$"
    ),
]
_COUNT_LINE = re.compile(r"^\d{2}:\d{2}( [a-z0-9_]+=\d+)+$")


def _run_filter(kind: str, text: str) -> list[str]:
    res = subprocess.run(
        ["bash", str(SCRIPT), "--filter", kind],
        input=text,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return [line for line in res.stdout.splitlines() if line]


def _assert_only_lifecycle(lines: list[str]) -> None:
    for line in lines:
        assert SECRET not in line, line
        assert any(p.match(line) for p in _ALLOWED_SHAPES), f"non-lifecycle line printed: {line}"
        assert len(line) <= 300


def test_script_parses():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


@_LINUX_ONLY
def test_script_is_executable():
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


@pytest.mark.parametrize("kind", ["service", "healthcheck", "kernel", "units"])
def test_every_filter_prints_lifecycle_lines_only(kind):
    corpus = SERVICE_JOURNAL + HEALTHCHECK_JOURNAL + KERNEL_JOURNAL
    _assert_only_lifecycle(_run_filter(kind, corpus))


def test_service_filter_keeps_the_restart_story():
    out = "\n".join(_run_filter("service", SERVICE_JOURNAL))
    for needle in (
        "Stopping dynasty.service",
        "State 'stop-sigterm' timed out",
        "Main process exited, code=killed, status=9/KILL",
        "Consumed 2h 1min CPU time, 2.7G memory peak",
        "Started dynasty.service",
        "INFO:     Started server process [5151]",
        "INFO:     Shutting down",
        "Uvicorn running on http://127.0.0.1:8000",
    ):
        assert needle in out, needle
    # Whole-message matching: an app line that merely CONTAINS a banner
    # phrase is not a banner.
    assert "Shutting down scrape" not in out
    assert "Started server process [1] extra" not in out
    assert "Uptime check failed" not in out


def test_healthcheck_filter_keeps_verdicts_and_drops_routine_runs():
    out = "\n".join(_run_filter("healthcheck", HEALTHCHECK_JOURNAL))
    assert out.count("LIVENESS FAIL") == 3
    assert "threshold reached" in out
    assert "restart issued" in out
    assert "Deactivated successfully" not in out
    assert "Starting dynasty-healthcheck" not in out


def test_kernel_filter_keeps_oom_verdicts_not_the_task_table():
    out = "\n".join(_run_filter("kernel", KERNEL_JOURNAL))
    assert "invoked oom-killer" in out
    assert "Memory cgroup out of memory: Killed process 4242" in out
    assert "900000" not in out
    assert "sshd" not in out


def test_long_lines_are_cut():
    long = "2026-10-19T08:42:45.4+00:00 vps systemd[1]: dynasty.service: Consumed " + "x" * 600
    (line,) = _run_filter("service", long + "\n")
    assert len(line) == 300


def test_counts_are_integers_only_and_zero_fill_the_gap():
    res = subprocess.run(
        ["bash", str(SCRIPT), "--counts", "08:39", "08:40", "08:41", "08:42", "08:43"],
        input=SERVICE_JOURNAL,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    lines = res.stdout.splitlines()
    assert [line[:5] for line in lines] == ["08:39", "08:40", "08:41", "08:42", "08:43"]
    for line in lines:
        assert _COUNT_LINE.match(line), line
    first = dict(kv.split("=") for kv in lines[0].split()[1:])
    assert first["http"] == "2" and first["health"] == "1" and first["http5xx"] == "1"
    assert first["uptime_fail"] == "1"
    gap = dict(kv.split("=") for kv in lines[1].split()[1:])
    assert gap["lines"] == "0" and gap["http"] == "0"
    assert dict(kv.split("=") for kv in lines[2].split()[1:])["alert_fail"] == "1"


# ── full run against stubbed tools ─────────────────────────────────────

_FAKE_SUDO = """#!/usr/bin/env bash
[[ "${1:-}" == "-n" ]] && shift
if [[ "${SUDO_MODE:-ok}" == "deny" ]]; then echo "sudo: a password is required" >&2; exit 1; fi
exec "$@"
"""

_FAKE_JOURNALCTL = """#!/usr/bin/env bash
[[ "${JOURNAL_MODE:-ok}" == "deny" ]] && exit 1
args=" $* "
case "$args" in
  *" -n 0 "*) exit 0 ;;
  *" --list-boots "*) echo " 0 abc123 Mon 2026-10-12 00:00:00 UTC Mon 2026-10-19 09:00:00 UTC"; exit 0 ;;
  *" -k "*) [[ "${WITH_OOM:-0}" == "1" ]] && cat "$FIXTURES/kernel.txt"; exit 0 ;;
  *" -u dynasty-healthcheck.service "*) cat "$FIXTURES/healthcheck.txt"; exit 0 ;;
  *" -u dynasty.service "*) [[ "${EMPTY_SERVICE:-0}" == "1" ]] || cat "$FIXTURES/service.txt"; exit 0 ;;
  *" _PID=1 "*) cat "$FIXTURES/service.txt" "$FIXTURES/healthcheck.txt"; exit 0 ;;
esac
exit 0
"""

_FAKE_SYSTEMCTL = """#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then echo "systemd 255 (stub)"; exit 0; fi
if [[ "${1:-}" == "show" ]]; then
  unit="$2"; shift 2
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-p" ]]; then
      case "$2" in
        Id) echo "Id=${unit}" ;;
        LoadState) echo "LoadState=loaded" ;;
        NRestarts) echo "NRestarts=0" ;;
        *) echo "$2=stub" ;;
      esac
      shift 2
    else
      shift
    fi
  done
  exit 0
fi
exit 1
"""


@pytest.fixture
def stub_env(tmp_path):
    bindir = tmp_path / "bin"
    fixtures = tmp_path / "fixtures"
    bindir.mkdir()
    fixtures.mkdir()
    for name, body in (
        ("sudo", _FAKE_SUDO),
        ("journalctl", _FAKE_JOURNALCTL),
        ("systemctl", _FAKE_SYSTEMCTL),
    ):
        path = bindir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    (fixtures / "service.txt").write_text(SERVICE_JOURNAL, encoding="utf-8")
    (fixtures / "healthcheck.txt").write_text(HEALTHCHECK_JOURNAL, encoding="utf-8")
    (fixtures / "kernel.txt").write_text(KERNEL_JOURNAL, encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "DIAG_JOURNALCTL": str(bindir / "journalctl"),
        "DIAG_SYSTEMCTL": str(bindir / "systemctl"),
        "FIXTURES": str(fixtures),
        "TZ": "UTC",
    }
    return env


def _full_run(env, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), "dynasty", "2026-10-19 08:38", "2026-10-19 08:44", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def test_full_run_reports_a_watchdog_restart_and_leaks_nothing(stub_env):
    res = _full_run(stub_env)
    assert res.returncode == 0, res.stderr
    assert SECRET not in res.stdout + res.stderr
    assert "journal_access: sudo" in res.stdout
    assert "HINT: liveness_watchdog_restart" in res.stdout
    assert "SIGKILLed" in res.stdout
    assert "liveness_failures=3 watchdog_restarts=1 oom_lines=0" in res.stdout
    # Six zero-filled minutes, 08:38..08:43.
    minutes = [line for line in res.stdout.splitlines() if _COUNT_LINE.match(line)]
    assert [m[:5] for m in minutes][:6] == ["08:38", "08:39", "08:40", "08:41", "08:42", "08:43"]
    # The property list never asks for anything that can carry a secret.
    assert "Environment=" not in res.stdout and "ExecStart=" not in res.stdout


def test_full_run_names_an_oom_kill(stub_env):
    res = _full_run({**stub_env, "WITH_OOM": "1"})
    assert res.returncode == 0, res.stderr
    assert "HINT: oom_kill" in res.stdout
    assert SECRET not in res.stdout + res.stderr


def test_full_run_fails_closed_when_the_journal_is_unreadable(stub_env):
    res = _full_run({**stub_env, "SUDO_MODE": "deny", "JOURNAL_MODE": "deny"})
    assert res.returncode == 5
    assert "journal unreadable" in res.stderr


def test_full_run_fails_closed_on_an_empty_window(stub_env):
    res = _full_run({**stub_env, "EMPTY_SERVICE": "1"})
    assert res.returncode == 5
    assert "no dynasty.service journal lines in the window" in res.stderr


@pytest.mark.parametrize(
    "since,until",
    [
        ("2026-10-19 08:50", "2026-10-19 08:20"),  # backwards
        ("2026-10-19 08:20", "2026-10-21 08:20"),  # > 24h
        ("08:20", "08:50"),  # no date
        ("2026-10-19 08:20; rm -rf /", "2026-10-19 08:50"),
    ],
)
def test_bad_windows_are_refused(stub_env, since, until):
    res = subprocess.run(
        ["bash", str(SCRIPT), "dynasty", since, until],
        capture_output=True,
        text=True,
        timeout=30,
        env=stub_env,
    )
    assert res.returncode == 2, res.stdout + res.stderr


# ── the workflow that runs it ─────────────────────────────────────────


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_is_read_only_and_never_holds_the_deploy_group():
    doc = _workflow()
    assert doc["permissions"] == {"contents": "read"}
    assert doc["concurrency"]["group"] == "production-diagnostics"
    assert doc["concurrency"]["cancel-in-progress"] is False
    for job in doc["jobs"].values():
        assert (job.get("concurrency") or {}).get("group") != "production-deploy"


def test_workflow_push_trigger_cannot_fire_from_ordinary_pushes():
    on = _workflow()[True]  # PyYAML reads the bare key `on` as True
    assert "workflow_dispatch" in on
    push = on.get("push")
    if push is None:
        return
    # Never the default branch, and only a sentinel path: pushing the
    # script, the workflow or anything else must not run it on the box.
    assert "main" not in (push.get("branches") or [])
    assert push.get("branches"), "an unscoped push trigger would run on every branch"
    paths = push.get("paths") or []
    assert paths, "without a paths filter every push to the branch runs the job"
    for path in paths:
        assert path.startswith("deploy/diagnostics/triggers/"), path
    assert not any(
        (REPO / p).exists() for p in paths
    ), "the sentinel must not be committed with the workflow, or that push fires it"


def test_workflow_runs_this_script_over_strict_ssh_and_propagates_its_status():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "< deploy/diagnostics/prod_restart_diagnostics.sh" in text
    assert "-o BatchMode=yes" in text and "-o StrictHostKeyChecking=yes" in text
    step = next(
        s
        for s in _workflow()["jobs"]["restart-diagnostics"]["steps"]
        if s.get("name") == "Collect restart evidence"
    )
    runnable = [ln for ln in step["run"].splitlines() if not ln.lstrip().startswith("#")]
    assert not any("|| true" in ln for ln in runnable)


def test_full_run_surfaces_the_watchdogs_cgroup_snapshots(stub_env, tmp_path):
    """The watchdog's pre-restart cgroup snapshots (dynasty-healthcheck.sh
    cgroup_snapshot) are the dead cgroup's only surviving counters, so the
    diagnostic must print them whole and count them; a snapshot-shaped line
    carrying a non-numeric value must still be dropped."""
    snap = (
        "2026-10-19T08:42:15.150001+00:00 vps dynasty-healthcheck.sh[902]: [healthcheck] "
        "snapshot mem reason=pre-restart cur=2791728742 peak=2791728742 high=2684354560 "
        "max=3221225472 ev_high=781 ev_max=0 ev_oom=0 ev_oom_kill=0\n"
        "2026-10-19T08:42:15.160001+00:00 vps dynasty-healthcheck.sh[902]: [healthcheck] "
        "snapshot psi_memory reason=pre-restart some_avg10=91.50 some_avg60=80.25 "
        "some_total=812345678 full_avg10=88.00 full_avg60=71.23 full_total=793685741\n"
        "2026-10-19T08:42:15.170001+00:00 vps dynasty-healthcheck.sh[902]: [healthcheck] "
        f"snapshot mem reason=pre-restart cur={SECRET}9\n"
    )
    fixtures = Path(stub_env["FIXTURES"])
    (fixtures / "healthcheck.txt").write_text(HEALTHCHECK_JOURNAL + snap, encoding="utf-8")
    res = _full_run(stub_env)
    assert res.returncode == 0, res.stderr
    assert SECRET not in res.stdout + res.stderr
    assert "ev_high=781 ev_max=0 ev_oom=0 ev_oom_kill=0" in res.stdout
    assert "full_total=793685741" in res.stdout
    assert "cgroup_snapshots=1 " in res.stdout
