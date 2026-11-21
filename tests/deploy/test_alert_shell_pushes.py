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
    for a in "$@"; do
      if [[ "$prev" == "-d" ]]; then msg="$a"; fi
      if [[ "$prev" == "--data-binary" && "$a" == "@-" ]]; then msg="$(cat)"; fi
      prev="$a"
    done
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
        return [
            ln.removeprefix("POST ")
            for ln in self.push_log.read_text(encoding="utf-8").splitlines()
        ]

    def restarts(self) -> int:
        if not self.systemctl_log.exists():
            return 0
        return sum(
            1
            for ln in self.systemctl_log.read_text(encoding="utf-8").splitlines()
            if ln.startswith("restart")
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
    return q.read_text(encoding="utf-8").splitlines() if q.exists() else []


def test_uptime_retries_a_failed_push_while_the_outage_lasts(box):
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    assert _uptime(box, up=False, push_rc=22).returncode == 1
    assert (box.dir / "uptime.state").read_text(
        encoding="utf-8"
    ).strip() == "DOWN"  # status always recorded
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
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    _uptime(box, up=False, push_rc=22)
    _uptime(box, up=True, push_rc=0)
    msgs = box.push_messages()
    assert len(msgs) == 3
    assert "UP -> DOWN" in msgs[1] and "DOWN -> UP" in msgs[2], "queued first, in order"
    assert _queue(box, "webhook") == []


def test_uptime_a_failing_channel_never_makes_a_working_one_repeat(box, tmp_path):
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    bad = tmp_path / "bad_cmd.sh"
    bad.write_text("#!/usr/bin/env bash\ncat >/dev/null\nexit 1\n", encoding="utf-8")
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
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    for i in range(15):
        _uptime(box, up=(i % 2 == 1), push_rc=22)
    queue = _queue(box, "webhook")
    assert len(queue) == 10
    assert all("private-topic" not in m for m in queue)
    # The OLDEST are dropped.  Runs alternate DOWN, UP, ... from UP, so the 15
    # transitions alternate "UP -> DOWN", "DOWN -> UP", ...; the last ten start
    # at the 6th ("DOWN -> UP") and end at the 15th ("UP -> DOWN").  Keeping the
    # first ten instead would start and end the other way round.
    assert "DOWN -> UP" in queue[0] and "UP -> DOWN" in queue[-1]
    assert all(
        ("UP -> DOWN" in m) == (i % 2 == 1) for i, m in enumerate(queue)
    ), "in order, alternating"


def test_uptime_drops_the_queue_of_a_channel_no_longer_configured(box):
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    _uptime(box, up=False, push_rc=22)
    assert len(_queue(box, "webhook")) == 1
    _uptime(box, up=False, url=None)
    assert _queue(box, "webhook") == [] and box.pushes() == 1


def test_uptime_without_a_channel_still_records_state(box):
    state = box.dir / "uptime.state"
    box.run(UPTIME, url=None, PROBE_RC="7", SITE_URL="https://site.example.invalid")
    assert state.read_text(encoding="utf-8").strip() == "DOWN" and box.pushes() == 0


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://ntfy.example.invalid/private-topic-for-tests", "scheme"),
        ("HTTPS://ntfy.example.invalid/private-topic-for-tests", "scheme"),
        ("https://user:pw@ntfy.example.invalid/private-topic-for-tests", "userinfo"),
        ("https://ntfy.example.invalid/private topic", "whitespace"),
        ("https:///private-topic-for-tests", "no_host"),
        ("http://localhost.evil.example/private-topic-for-tests", "scheme"),
        ("http://127.0.0.1.evil.example/private-topic-for-tests", "scheme"),
        ("https://ntfy.example.invalid:99999/private-topic-for-tests", "malformed"),
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


def _shell_reasons(values: list[str]) -> list[str]:
    """``webhook_reject_reason`` for every value, in one bash process (``ok``
    for an accepted value)."""
    script = HEALTH.read_text(encoding="utf-8")
    fn = script[script.index("webhook_reject_reason() {") : script.index("notify_restart() {")]
    loop = (
        '\nwhile IFS= read -r -d "" u; do r="$(webhook_reject_reason "$u")"; '
        'printf "%s\\n" "${r:-ok}"; done'
    )
    out = subprocess.run(
        ["bash", "-c", fn + loop],
        input="\0".join(values) + "\0",
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout.splitlines()
    assert len(out) == len(values)
    return out


def _corpus() -> list[str]:
    import itertools

    schemes = ["https", "http", "HTTPS", "Http", "ftp", ""]
    seps = ["://", ":/", ":"]
    users = ["", "u@", "u:p@", "@"]
    hosts = [
        "h.example", "localhost", "LOCALHOST", "127.0.0.1", "127.0.0.1.evil",
        "localhost.evil", "[::1]", "[::1", "::1", "", "[2001:db8::1]",
        "[h.example]", "[127.0.0.1]", "h]x", "h[x", "a[::1]", "h[", "[",
    ]  # fmt: skip
    ports = [
        "", ":80", ":", ":abc", ":99999", ":65535", ":0", ":00080", ":000443",
        ":0000065535", ":0000065536", ":" + "9" * 21, ":+1",
    ]  # fmt: skip
    paths = ["", "/t", "?q", "#f", "/x@y"]
    return ["".join(p) for p in itertools.product(schemes, seps, users, hosts, ports, paths)]


def test_restart_push_shell_check_matches_owner_notify_validate():
    """Review 2026-11-20 (second round): prefix globs let
    http://localhost.evil.example through.  Over a generated corpus the shell
    check now gives validate()'s exact answer, except that it refuses every
    bracketed host other than [::1] (validate() accepts a valid IPv6 literal).
    Round 3: a lone "[" after the first character was accepted (validate()
    refuses it) and a zero-padded port was refused (validate() accepts it)."""
    from src.utils.owner_notify import validate

    corpus = _corpus()
    for value, shell in zip(corpus, _shell_reasons(corpus)):
        want = validate(value)
        want = "ok" if want == "ok" else want.removeprefix("rejected:")
        if "[" in value and "[::1]" not in value and shell == "malformed":
            continue  # the one deliberate difference: stricter, never looser
        assert shell == want, (value, shell, want)


def _shell_strip(values: list[str]) -> list[str]:
    """``py_strip`` from the healthcheck for every value (NUL-separated I/O)."""
    script = HEALTH.read_text(encoding="utf-8")
    fn = script[script.index("PY_STRIP_CHARS=(") : script.index("webhook_reject_reason() {")]
    loop = '\nwhile IFS= read -r -d "" u; do py_strip "$u"; printf "%s\\0" "$PY_STRIPPED"; done'
    out = subprocess.run(
        ["bash", "-c", fn + loop],
        input="\0".join(values).encode("utf-8") + b"\0",
        capture_output=True,
        timeout=120,
    ).stdout.decode("utf-8")
    parts = out.split("\0")[:-1]
    assert len(parts) == len(values)
    return parts


def test_restart_push_strips_exactly_what_validate_strips():
    """Round 3: bash's [[:space:]] left a trailing NBSP (or \\x1c-\\x1f) on the
    value, so signals_health reported the channel configured while the watchdog
    refused every push.  Every str.isspace() character, on either side."""
    spaces = [chr(c) for c in range(0x110000) if chr(c).isspace()]
    values = [URL + c for c in spaces] + [c + URL for c in spaces]
    values += [" \u00a0\t" + URL + "\u3000\x1f\n", "\u00a0", "\u2028\u2029"]
    values += [URL + "\u00a0x"]  # inside the value: kept (and then refused)
    for value, stripped in zip(values, _shell_strip(values)):
        assert stripped == value.strip(), repr(value)


def test_the_github_push_strips_exactly_what_validate_strips():
    text = (ROOT / "scripts/notify_owner.sh").read_text(encoding="utf-8")
    fn = text[text.index("py_strip_chars=(") : text.index('url="$(py_strip')]
    for value in [URL + "\u00a0", "\u2003" + URL + "\x1c", "\t" + URL + "\n"]:
        out = subprocess.run(
            ["bash", "-c", fn + '\npy_strip "$1"', "_", value],
            capture_output=True,
            timeout=30,
        ).stdout.decode("utf-8")
        assert out == value.strip(), repr(value)


def test_restart_push_shell_check_is_never_looser_on_odd_bytes():
    from src.utils.owner_notify import validate

    odd = ["\x01", "\x7f", "\u00e9", "\u00a0", "\t", "\v", "%00", "\\", '"', "'"]
    values = [f"https://h{c}.example/t" for c in odd] + [f"https://h.example/{c}t" for c in odd]
    for value, shell in zip(values, _shell_reasons(values)):
        if shell == "ok":
            assert validate(value) == "ok", value


def test_uptime_queue_never_hands_a_planted_line_to_curl(box, tmp_path):
    """Review 2026-11-20 (second round): the queue sits in a shared directory,
    and curl reads a -d value starting with "@" as a file name.  The body now
    goes on stdin, and only lines this script queued are replayed."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-CONTENT\n", encoding="utf-8")
    (box.dir / "uptime.state").write_text("DOWN\n", encoding="utf-8")
    (box.dir / "uptime.state.pending-webhook").write_text(
        f"@{secret}\nnot ours\n[riskit-uptime] UP -> DOWN at earlier: probes\n", encoding="utf-8"
    )
    _uptime(box, up=False)
    msgs = box.push_messages()
    assert msgs == ["[riskit-uptime] UP -> DOWN at earlier: probes"]
    assert "TOP-SECRET-CONTENT" not in box.push_log.read_text(encoding="utf-8")
    assert _queue(box, "webhook") == []


# -- queue storage hardening (2026-11-21 audit) ------------------------------------
UPTIME_UNIT = ROOT / "deploy/monitoring/riskit-uptime.service"


def test_uptime_refuses_a_shared_state_directory_and_uses_the_private_default(box, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o1777)  # like /var/tmp: sticky and world-writable
    home = tmp_path / "home"
    home.mkdir()
    cp = box.run(
        UPTIME, STATE_FILE=str(shared / "riskit-uptime.state"), HOME=str(home), **UPTIME_DOWN
    )
    assert "is not private" in (box.dir / "uptime.log").read_text(encoding="utf-8")
    private = home / ".local/state/riskit-uptime"
    assert (private / "state").read_text(encoding="utf-8").strip() == "DOWN"
    assert oct(private.stat().st_mode & 0o777) == "0o700"
    assert oct((private / "state").stat().st_mode & 0o777) == "0o600"
    assert list(shared.iterdir()) == [], "nothing is written to the shared directory"
    assert cp.returncode == 1


def test_uptime_never_follows_a_symlinked_queue_file(box, tmp_path):
    target = tmp_path / "victim.txt"
    target.write_text("[riskit-uptime] FORGED -> line from a symlink target\n", encoding="utf-8")
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    (box.dir / "uptime.state.pending-webhook").symlink_to(target)
    _uptime(box, up=False)
    msgs = box.push_messages()
    assert len(msgs) == 1 and "UP -> DOWN" in msgs[0], "the symlink target was not read"
    assert (
        target.read_text(encoding="utf-8")
        == "[riskit-uptime] FORGED -> line from a symlink target\n"
    )


def test_uptime_run_that_cannot_take_the_lock_records_nothing(box):
    import fcntl

    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    with open(box.dir / "lock", "a", encoding="utf-8") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        cp = _uptime(box, up=False)
    assert "holds the lock" in (box.dir / "uptime.log").read_text(encoding="utf-8")
    assert (box.dir / "uptime.state").read_text(encoding="utf-8").strip() == "UP"
    assert box.pushes() == 0 and cp.returncode == 1


def test_uptime_saves_progress_after_each_accepted_message(box, tmp_path):
    """Accept the first POST, then kill the run on the second (as the unit's
    timeout would): the accepted message already left the queue, so the next
    run re-sends only what was not accepted."""
    counter = tmp_path / "posts"
    (box.bin / "curl").write_text(
        "#!/usr/bin/env bash\n"
        'case " $* " in *" -X POST "*)\n'
        '  n=$(( $(cat "$POSTS" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$POSTS"\n'
        '  printf "POST %s\\n" "$(cat)" >> "$PUSH_LOG"; [ "$n" -eq 1 ] && exit 0\n'
        '  kill -9 "$PPID"; exit 22;;\n'
        "esac\nprintf 000; exit 7\n",
        encoding="utf-8",
    )
    (box.dir / "uptime.state").write_text("DOWN\n", encoding="utf-8")
    (box.dir / "uptime.state.pending-webhook").write_text(
        "[riskit-uptime] one\n[riskit-uptime] two\n[riskit-uptime] three\n", encoding="utf-8"
    )
    box.run(UPTIME, POSTS=str(counter), **UPTIME_DOWN)
    assert box.push_messages() == ["[riskit-uptime] one", "[riskit-uptime] two"]
    assert _queue(box, "webhook") == ["[riskit-uptime] two", "[riskit-uptime] three"]


def test_uptime_delivery_budget_keeps_the_queue(box):
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    _uptime(box, up=False, NOTIFY_BUDGET="0")
    assert box.pushes() == 0 and len(_queue(box, "webhook")) == 1
    assert "delivery budget spent" in (box.dir / "uptime.log").read_text(encoding="utf-8")


def test_uptime_drops_malformed_lines_and_unknown_status(box):
    (box.dir / "uptime.state").write_text("garbage\n", encoding="utf-8")
    (box.dir / "uptime.state.pending-webhook").write_text(
        "[riskit-uptime] " + "x" * 2000 + "\nno prefix\n\n", encoding="utf-8"
    )
    _uptime(box, up=True)
    assert box.pushes() == 0, "an unknown stored status reads as UP: no transition"
    assert _queue(box, "webhook") == []


def test_uptime_cleans_temp_files_left_by_a_killed_run(box):
    (box.dir / "uptime.state.tmp.ABC123").write_text("partial", encoding="utf-8")
    (box.dir / "uptime.state.pending-webhook.tmp.XYZ789").write_text("partial", encoding="utf-8")
    _uptime(box, up=True)
    assert not list(box.dir.glob("*.tmp.*"))


def test_uptime_unit_keeps_state_in_a_private_systemd_directory():
    unit = UPTIME_UNIT.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in unit.splitlines() if not ln.lstrip().startswith("#"))
    assert "StateDirectory=riskit-uptime" in code
    assert "StateDirectoryMode=0700" in code
    assert "UMask=0077" in code
    assert "/var/tmp" not in code


# -- delivery order and process hygiene (2026-11-21 delta review) ------------------
def _cmd_logger(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "cmd.log"
    cmd = tmp_path / "cmd.sh"
    cmd.write_text(f'#!/usr/bin/env bash\ncat >> "{log}"\nexit 0\n', encoding="utf-8")
    cmd.chmod(0o755)
    return cmd, log


def test_uptime_a_run_killed_during_the_webhook_send_still_alerts_the_cmd_channel(box, tmp_path):
    """The status used to be recorded before the cmd queue held the new message,
    so a run killed during the webhook POST lost the cmd alert for good."""
    cmd, cmd_log = _cmd_logger(tmp_path)
    killer = tmp_path / "killed_once"
    (box.bin / "curl").write_text(
        "#!/usr/bin/env bash\n"
        'case " $* " in *" -X POST "*)\n'
        '  body="$(cat)"; printf "POST %s\\n" "$body" >> "$PUSH_LOG"\n'
        '  if [ ! -e "$KILLER" ]; then : > "$KILLER"; kill -9 "$PPID"; fi; exit 0;;\n'
        'esac\nprintf \'%s\' "${PROBE_CODE:-000}"; exit "${PROBE_RC:-0}"\n',
        encoding="utf-8",
    )
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    box.run(UPTIME, NOTIFY_CMD=str(cmd), KILLER=str(killer), **UPTIME_DOWN)
    assert killer.exists() and not cmd_log.exists(), "killed before the cmd send"
    for _ in range(2):
        box.run(UPTIME, NOTIFY_CMD=str(cmd), KILLER=str(killer), **UPTIME_DOWN)
    assert "UP -> DOWN" in cmd_log.read_text(encoding="utf-8")
    assert cmd_log.read_text(encoding="utf-8").count("UP -> DOWN") == 1
    assert _queue(box, "cmd") == [] and _queue(box, "webhook") == []


def test_uptime_a_process_left_by_notify_cmd_never_holds_the_lock(box, tmp_path):
    pidfile = tmp_path / "child.pid"
    cmd = tmp_path / "leaves_child.sh"
    cmd.write_text(
        f'#!/usr/bin/env bash\ncat >/dev/null\nsleep 30 &\necho $! > "{pidfile}"\nexit 0\n',
        encoding="utf-8",
    )
    cmd.chmod(0o755)
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    try:
        box.run(UPTIME, url=None, NOTIFY_CMD=str(cmd), **UPTIME_DOWN)
        assert pidfile.exists()
        box.run(UPTIME, url=None, NOTIFY_CMD=str(cmd), **UPTIME_UP)
        log = (box.dir / "uptime.log").read_text(encoding="utf-8")
        assert "holds the lock" not in log
        assert (box.dir / "uptime.state").read_text(encoding="utf-8").strip() == "UP"
    finally:
        for line in pidfile.read_text(encoding="utf-8").split() if pidfile.exists() else []:
            try:
                os.kill(int(line), 9)
            except (ProcessLookupError, ValueError):
                pass


def test_uptime_notify_cmd_is_killed_if_it_ignores_sigterm():
    text = UPTIME.read_text(encoding="utf-8")
    assert 'timeout -k 2 "${SEND_TIMEOUT}" ${NOTIFY_CMD}' in text
    assert text.count("9>&-") >= 3, "no send inherits the lock descriptor"


def test_uptime_upgrade_reads_the_legacy_status_once_without_a_warning(box, tmp_path):
    legacy = tmp_path / "legacy-riskit-uptime.state"
    legacy.write_text("DOWN\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    env = {"UPTIME_LEGACY_STATE_FILE": str(legacy), "STATE_FILE": str(legacy), "HOME": str(home)}
    _uptime(box, up=True, **env)
    msgs = box.push_messages()
    assert len(msgs) == 1 and "DOWN -> UP" in msgs[0], "the recovery at upgrade is sent"
    assert "not private" not in (box.dir / "uptime.log").read_text(encoding="utf-8")
    private = home / ".local/state/riskit-uptime/state"
    assert private.read_text(encoding="utf-8").strip() == "UP"
    _uptime(box, up=True, **env)
    assert box.pushes() == 1, "the legacy file is read only while no private status exists"


def test_uptime_a_bad_budget_value_warns_and_uses_the_default(box):
    (box.dir / "uptime.state").write_text("UP\n", encoding="utf-8")
    cp = _uptime(box, up=False, NOTIFY_BUDGET="15s")
    assert "NOTIFY_BUDGET is not a whole number" in (box.dir / "uptime.log").read_text(
        encoding="utf-8"
    )
    assert box.pushes() == 1 and cp.returncode == 1


def test_uptime_replaces_a_symlink_to_a_directory_instead_of_writing_into_it(box, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (box.dir / "uptime.state").symlink_to(target, target_is_directory=True)
    _uptime(box, up=False)
    state = box.dir / "uptime.state"
    assert not state.is_symlink() and state.read_text(encoding="utf-8").strip() == "DOWN"
    assert list(target.iterdir()) == []


def test_uptime_unit_timeout_covers_probes_plus_delivery():
    unit = UPTIME_UNIT.read_text(encoding="utf-8")
    timeout = int(
        next(ln for ln in unit.splitlines() if ln.startswith("TimeoutStartSec=")).split("=")[1]
    )
    # 3 probes x CURL_TIMEOUT 20 + NOTIFY_BUDGET 15 + one send (10 + 2 kill) + 1
    assert 3 * 20 + 15 + 12 + 1 <= timeout
