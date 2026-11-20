"""Owner pushes from the two box shell watchdogs (stub ``curl``/``systemctl``).

* ``deploy/systemd/dynasty-healthcheck.sh`` -- ONE push per restart episode,
  none on a healthy probe, none when ``NOTIFY_WEBHOOK_URL`` is unset, a failed
  push retried at the next threshold crossing, the URL never printed.
* ``deploy/monitoring/uptime_check.sh`` -- the state file is written only after
  the push succeeded, so a failed push is retried by the next run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEALTH = ROOT / "deploy/systemd/dynasty-healthcheck.sh"
UPTIME = ROOT / "deploy/monitoring/uptime_check.sh"
URL = "https://ntfy.example.invalid/private-topic-for-tests"

# Probe URLs contain "127.0.0.1" / "chaseupside"; the webhook URL contains
# "ntfy.example.invalid".  Probes are answered by $PROBE_RC / $PROBE_CODE; a
# POST (-X POST) is logged and answered by $PUSH_RC_FILE.
CURL_STUB = r"""#!/usr/bin/env bash
case " $* " in
  *" -X POST "*)
    printf 'POST\n' >> "$PUSH_LOG"
    exit "$(cat "$PUSH_RC_FILE" 2>/dev/null || echo 0)"
    ;;
esac
printf '%s' "${PROBE_CODE:-000}"
exit "${PROBE_RC:-0}"
"""
SYSTEMCTL_STUB = '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$SYSTEMCTL_LOG"\nexit 0\n'


class Box:
    def __init__(self, tmp_path: Path):
        self.dir = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for name, body in (("curl", CURL_STUB), ("systemctl", SYSTEMCTL_STUB)):
            (self.bin / name).write_text(body, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.push_log = tmp_path / "push.log"
        self.push_rc = tmp_path / "push_rc"
        self.systemctl_log = tmp_path / "systemctl.log"
        self.state = tmp_path / "state"
        self.state.mkdir()

    def pushes(self) -> int:
        return len(self.push_log.read_text().splitlines()) if self.push_log.exists() else 0

    def restarts(self) -> int:
        if not self.systemctl_log.exists():
            return 0
        return sum(
            1 for ln in self.systemctl_log.read_text().splitlines() if ln.startswith("restart")
        )

    def run(self, script: Path, *, push_rc: int = 0, url: str | None = URL, **extra: str):
        self.push_rc.write_text(str(push_rc), encoding="utf-8")
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "PUSH_LOG": str(self.push_log),
            "PUSH_RC_FILE": str(self.push_rc),
            "SYSTEMCTL_LOG": str(self.systemctl_log),
            "HEALTH_STATE_DIR": str(self.state),
            "HEALTH_FAIL_THRESHOLD": "2",
            "HEALTH_PYSPY": "0",
            "HEALTH_CGROUP_ROOT": str(self.dir / "cg"),
            "HEALTH_PROC_ROOT": str(self.dir / "proc"),
            "LOG_FILE": str(self.dir / "uptime.log"),
            "STATE_FILE": str(self.dir / "uptime.state"),
            "CHECK_LOCAL": "false",
            **extra,
        }
        if url is not None:
            env["NOTIFY_WEBHOOK_URL"] = url
        return subprocess.run(
            ["bash", str(script)], env=env, capture_output=True, text=True, timeout=60, cwd=self.dir
        )


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def _down(box, **kw):
    return box.run(HEALTH, PROBE_RC="7", **kw)


def test_one_push_per_restart_not_one_per_probe(box):
    assert _down(box).returncode == 0
    assert box.restarts() == 0 and box.pushes() == 0  # below the threshold
    cp = _down(box)
    assert box.restarts() == 1 and box.pushes() == 1
    assert "private-topic" not in cp.stdout + cp.stderr
    # still down: the next window restarts again but does not push again
    _down(box)
    _down(box)
    assert box.restarts() == 2 and box.pushes() == 1


def test_recovery_rearms_the_push(box):
    _down(box)
    _down(box)
    assert box.pushes() == 1
    assert box.run(HEALTH, PROBE_RC="0", PROBE_CODE="200").returncode == 0
    _down(box)
    _down(box)
    assert box.pushes() == 2


def test_no_push_on_a_healthy_probe_even_degraded(box):
    for code in ("200", "503"):
        box.run(HEALTH, PROBE_RC="0", PROBE_CODE=code)
    assert box.pushes() == 0 and box.restarts() == 0


def test_no_push_when_the_url_is_unset(box):
    _down(box, url=None)
    cp = _down(box, url=None)
    assert box.restarts() == 1 and box.pushes() == 0
    assert cp.returncode == 0


def test_a_failed_push_is_retried_and_names_only_a_reason_class(box):
    _down(box, push_rc=22)
    cp = _down(box, push_rc=22)
    assert cp.returncode == 0 and box.restarts() == 1  # the restart never depends on the push
    assert "reason=curl_exit_22" in cp.stdout
    assert "private-topic" not in cp.stdout + cp.stderr
    assert box.pushes() == 1
    _down(box, push_rc=0)
    _down(box, push_rc=0)
    assert box.pushes() == 2  # delivered at the next threshold crossing
    _down(box)
    _down(box)
    assert box.pushes() == 2  # and then once only


def test_uptime_state_is_written_only_after_the_push_succeeded(box):
    state = box.dir / "uptime.state"
    state.write_text("UP\n")
    kw = {"PROBE_RC": "7", "SITE_URL": "https://site.example.invalid"}
    cp = box.run(UPTIME, push_rc=22, **kw)
    assert cp.returncode == 1
    assert state.read_text().strip() == "UP", "a failed push must not record the new state"
    assert box.pushes() == 1
    cp = box.run(UPTIME, push_rc=0, **kw)
    assert state.read_text().strip() == "DOWN" and box.pushes() == 2
    box.run(UPTIME, push_rc=0, **kw)  # no transition now: no further push
    assert box.pushes() == 2


def test_uptime_without_a_channel_still_records_state(box):
    state = box.dir / "uptime.state"
    box.run(UPTIME, url=None, PROBE_RC="7", SITE_URL="https://site.example.invalid")
    assert state.read_text().strip() == "DOWN" and box.pushes() == 0
