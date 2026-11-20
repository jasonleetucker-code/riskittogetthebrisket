"""Owner pushes from the two box shell watchdogs (stub ``curl``/``systemctl``).

* ``deploy/systemd/dynasty-healthcheck.sh`` -- ONE push per restart episode,
  none on a healthy probe, none when ``NOTIFY_WEBHOOK_URL`` is unset, a failed
  push retried at the next threshold crossing, the URL never printed.
* ``deploy/monitoring/uptime_check.sh`` -- the observed status is recorded every
  run; each channel queues what it failed to deliver and retries it in order,
  so a failed push survives an outage that clears before the next run, and a
  working channel never repeats a message because another channel failed.
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
    msg=""; prev=""
    for a in "$@"; do [[ "$prev" == "-d" ]] && msg="$a"; prev="$a"; done
    printf 'POST %s\n' "${msg//$'\n'/ }" >> "$PUSH_LOG"
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
        return len(self.push_messages())

    def push_messages(self) -> list[str]:
        if not self.push_log.exists():
            return []
        return [ln.removeprefix("POST ") for ln in self.push_log.read_text().splitlines()]

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


UPTIME_DOWN = {"PROBE_RC": "7", "SITE_URL": "https://site.example.invalid"}
UPTIME_UP = {"PROBE_RC": "0", "PROBE_CODE": "200", "SITE_URL": "https://site.example.invalid"}


def _uptime(box, up: bool, push_rc: int = 0, **kw):
    return box.run(UPTIME, push_rc=push_rc, **(UPTIME_UP if up else UPTIME_DOWN), **kw)


def _queue(box, channel: str) -> list[str]:
    q = box.dir / f"uptime.state.pending-{channel}"
    return q.read_text().splitlines() if q.exists() else []


def test_uptime_retries_a_failed_push_while_the_outage_lasts(box):
    (box.dir / "uptime.state").write_text("UP\n")
    assert _uptime(box, up=False, push_rc=22).returncode == 1
    assert (box.dir / "uptime.state").read_text().strip() == "DOWN"  # status always recorded
    assert box.pushes() == 1 and len(_queue(box, "webhook")) == 1
    _uptime(box, up=False, push_rc=0)
    msgs = box.push_messages()
    assert len(msgs) == 2 and "UP -> DOWN" in msgs[1]  # the retry
    assert _queue(box, "webhook") == []
    _uptime(box, up=False, push_rc=0)
    assert box.pushes() == 2  # no transition, nothing queued: no push


def test_uptime_reports_an_outage_that_cleared_before_the_retry(box):
    """Review 2026-11-20: recording the state only after a delivered push lost a
    short outage completely when its DOWN push failed."""
    (box.dir / "uptime.state").write_text("UP\n")
    _uptime(box, up=False, push_rc=22)
    _uptime(box, up=True, push_rc=0)
    msgs = box.push_messages()
    assert len(msgs) == 3
    assert "UP -> DOWN" in msgs[1] and "DOWN -> UP" in msgs[2], "queued first, in order"
    assert _queue(box, "webhook") == []


def test_uptime_a_failing_channel_never_makes_a_working_one_repeat(box, tmp_path):
    (box.dir / "uptime.state").write_text("UP\n")
    bad = tmp_path / "bad_cmd.sh"
    bad.write_text("#!/usr/bin/env bash\ncat >/dev/null\nexit 1\n")
    bad.chmod(0o755)
    for _ in range(3):
        _uptime(box, up=False, NOTIFY_CMD=str(bad))
    assert box.pushes() == 1, "the webhook got its one message"
    assert len(_queue(box, "cmd")) == 1 and _queue(box, "webhook") == []
    _uptime(box, up=True, NOTIFY_CMD=str(bad))
    msgs = box.push_messages()
    assert len(msgs) == 2 and "DOWN -> UP" in msgs[1]  # the recovery still goes out
    assert len(_queue(box, "cmd")) == 2


def test_uptime_queue_is_bounded(box):
    (box.dir / "uptime.state").write_text("UP\n")
    for i in range(15):
        _uptime(box, up=(i % 2 == 1), push_rc=22)
    assert len(_queue(box, "webhook")) == 10
    assert all("private-topic" not in m for m in _queue(box, "webhook"))


def test_uptime_drops_the_queue_of_a_channel_no_longer_configured(box):
    (box.dir / "uptime.state").write_text("UP\n")
    _uptime(box, up=False, push_rc=22)
    assert len(_queue(box, "webhook")) == 1
    _uptime(box, up=False, url=None)
    assert _queue(box, "webhook") == [] and box.pushes() == 1


def test_uptime_without_a_channel_still_records_state(box):
    state = box.dir / "uptime.state"
    box.run(UPTIME, url=None, PROBE_RC="7", SITE_URL="https://site.example.invalid")
    assert state.read_text().strip() == "DOWN" and box.pushes() == 0


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://ntfy.example.invalid/private-topic-for-tests", "scheme"),
        ("HTTPS://ntfy.example.invalid/private-topic-for-tests", "scheme"),
        ("https://user:pw@ntfy.example.invalid/private-topic-for-tests", "userinfo"),
        ("https://ntfy.example.invalid/private topic", "whitespace"),
        ("https:///private-topic-for-tests", "no_host"),
    ],
)
def test_restart_push_refuses_the_urls_the_validator_refuses(box, url, reason):
    """The restart push and signals_health's healthcheckNtfyConfigured judge the
    same drop-in value; a value the reporter calls unconfigured is never sent."""
    _down(box, url=url)
    cp = _down(box, url=url)
    assert box.restarts() == 1 and box.pushes() == 0
    assert f"reason=webhook_rejected:{reason}" in cp.stdout
    assert "private-topic" not in cp.stdout + cp.stderr


def test_restart_push_shell_check_agrees_with_owner_notify_validate():
    from src.utils.owner_notify import validate

    cases = [
        URL,
        "  " + URL + "  ",
        "http://127.0.0.1:8080/topic",
        "http://ntfy.example.invalid/t",
        "HTTPS://ntfy.example.invalid/t",
        "https://u:p@ntfy.example.invalid/t",
        "https://ntfy.example.invalid/a b",
        "https:///t",
    ]
    script = HEALTH.read_text(encoding="utf-8")
    fn = script[script.index("webhook_reject_reason() {") : script.index("notify_restart() {")]
    for raw in cases:
        value = raw.strip()
        shell = subprocess.run(
            ["bash", "-c", fn + '\nwebhook_reject_reason "$1"', "_", value],
            capture_output=True,
            text=True,
        ).stdout.strip()
        want = validate(raw)
        assert (shell == "") == (want == "ok"), (raw, shell, want)
        if want != "ok":
            assert want == "rejected:" + shell, (raw, shell, want)
