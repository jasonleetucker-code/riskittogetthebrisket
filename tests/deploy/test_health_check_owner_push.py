"""The GitHub-side production alerts reach the owner's phone through ONE script.

STAB-2 gave ``health-check.yml`` an owner push (repo secret
``NOTIFY_WEBHOOK_URL``, a private ntfy topic) as an inline ``notify_owner``
function -- three copies in one file.  COV-REFRESH / COV-DECISION added the
same push to ``scheduled-refresh.yml`` and ``prod-e2e-smoke.yml``, so the copy
was factored into ``scripts/notify_owner.sh`` before it could become five.

What is pinned here:

* the script itself: https-only, a ``Title`` header, a 10 s cap, the URL never
  printed, a NON-ZERO exit when a push does not go out, and a silent-but-noted
  no-op (exit 0 + ``::notice``) when the secret is unset;
* the pending marker: a push that does not go out leaves
  ``<!-- owner-push: pending -->`` on its tracker, and ``--retry-pending``
  delivers it later (COV-DEPLOYLAG: a failed push used to be a warning nobody
  retried, because the tracker now existed and the next run only commented);
* the wiring: every workflow that pushes calls the shared script, no inline
  copy survives, and the push happens only at lifecycle points.

The end-to-end "a failed push is retried by the next run" behaviour, through
each workflow's real tracker shell, is in ``test_owner_push_pending_retry.py``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "notify_owner.sh"
WORKFLOWS = ROOT / ".github" / "workflows"
MARKER = "<!-- owner-push: pending -->"
URL = "https://ntfy.example.invalid/private-topic-for-tests"

PUSHING_WORKFLOWS = ("health-check.yml", "scheduled-refresh.yml", "prod-e2e-smoke.yml")

CURL_STUB = """#!/usr/bin/env bash
# Records argv and the request body; exits with the code in $CURL_EXIT_FILE.
{ printf 'ARGS:'; printf ' %s' "$@"; printf '\\n'; } >> "$CURL_LOG"
body=$(cat)
printf 'BODY:%s\\n' "$body" >> "$CURL_LOG"
exit "$(cat "$CURL_EXIT_FILE" 2>/dev/null || echo 0)"
"""

GH_STUB = r"""#!/usr/bin/env python3
import json, os, sys

STATE = os.environ["GH_STUB_STATE"]
with open(STATE, encoding="utf-8") as fh:
    state = json.load(fh)
argv = sys.argv[1:]
state.setdefault("calls", []).append(argv[:2])
if state.get("broken"):
    sys.exit(7)
if argv[:2] == ["issue", "view"]:
    body = state["bodies"].get(argv[2])
    if body is None:
        sys.exit(1)
    sys.stdout.write(body)  # the script asks for --jq '.body // ""'
elif argv[:2] == ["issue", "edit"]:
    with open(argv[argv.index("--body-file") + 1], encoding="utf-8") as fh:
        state["bodies"][argv[2]] = fh.read()
else:
    sys.exit(3)
with open(STATE, "w", encoding="utf-8") as fh:
    json.dump(state, fh)
"""


class Box:
    """A scratch PATH with curl and gh stubs, and the real script."""

    def __init__(self, tmp_path: Path):
        self.dir = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        (self.bin / "curl").write_text(CURL_STUB, encoding="utf-8")
        (self.bin / "gh").write_text(GH_STUB, encoding="utf-8")
        for stub in ("curl", "gh"):
            (self.bin / stub).chmod(0o755)
        self.curl_log = tmp_path / "curl.log"
        self.curl_exit = tmp_path / "curl_exit"
        self.state = tmp_path / "gh_state.json"
        self.state.write_text(json.dumps({"bodies": {}}), encoding="utf-8")

    def seed_body(self, number: int, body: str) -> None:
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["bodies"][str(number)] = body
        self.state.write_text(json.dumps(state), encoding="utf-8")

    def body(self, number: int) -> str:
        return json.loads(self.state.read_text(encoding="utf-8"))["bodies"][str(number)]

    def gh_calls(self) -> list:
        return json.loads(self.state.read_text(encoding="utf-8")).get("calls", [])

    def pushes(self) -> list[str]:
        if not self.curl_log.exists():
            return []
        return [
            ln for ln in self.curl_log.read_text(encoding="utf-8").splitlines() if ln[:5] == "ARGS:"
        ]

    def run(self, *args: str, url: str | None = URL, curl_exit: int = 0):
        self.curl_exit.write_text(str(curl_exit), encoding="utf-8")
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "CURL_LOG": str(self.curl_log),
            "CURL_EXIT_FILE": str(self.curl_exit),
            "GH_STUB_STATE": str(self.state),
            "TMPDIR": str(self.dir),
        }
        if url is not None:
            env["NOTIFY_WEBHOOK_URL"] = url
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=self.dir,
        )


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


# --------------------------------------------------------------------------
# the script
# --------------------------------------------------------------------------


def test_unset_secret_is_a_noted_no_op(box):
    cp = box.run("Title X", "Body Y", url=None)
    assert cp.returncode == 0, cp.stderr
    assert "::notice title=Owner push not configured::" in cp.stdout
    assert box.pushes() == []
    assert box.gh_calls() == [], "an unconfigured channel must not touch the tracker"


def test_unset_secret_with_an_issue_neither_pushes_nor_marks(box):
    box.seed_body(7, "tracker body")
    cp = box.run("--issue", "7", "Title X", "Body Y", url="")
    assert cp.returncode == 0
    assert box.body(7) == "tracker body"
    assert box.pushes() == []


def test_a_push_carries_the_title_header_and_the_cap_and_never_prints_the_url(box):
    cp = box.run("Risk It: something", "Body Y")
    assert cp.returncode == 0, cp.stderr
    assert "owner push sent: Risk It: something" in cp.stdout
    (args,) = box.pushes()
    assert "-H Title: Risk It: something" in args
    assert "--max-time 10" in args
    assert URL in args, "the stub must have been handed the URL"
    assert "private-topic" not in cp.stdout + cp.stderr
    assert "BODY:Body Y" in box.curl_log.read_text(encoding="utf-8")


def test_a_failed_push_exits_non_zero_without_printing_the_url(box):
    cp = box.run("Title X", "Body Y", curl_exit=22)
    assert cp.returncode == 1
    assert "::warning title=Owner push failed::" in cp.stdout
    assert "curl exit 22" in cp.stdout
    assert "private-topic" not in cp.stdout + cp.stderr


def test_a_non_https_url_is_refused_and_never_contacted(box):
    cp = box.run("Title X", "Body Y", url="http://ntfy.example.invalid/topic")
    assert cp.returncode == 2
    assert "::error title=Owner push misconfigured::" in cp.stdout
    assert box.pushes() == []
    assert "ntfy.example.invalid" not in cp.stdout + cp.stderr


def test_a_message_starting_with_at_is_sent_literally_not_read_as_a_file(box):
    secret_file = box.dir / "x"
    secret_file.write_text("FILE CONTENT", encoding="utf-8")
    cp = box.run("Title X", "@x")
    assert cp.returncode == 0
    log = box.curl_log.read_text(encoding="utf-8")
    assert "BODY:@x" in log and "FILE CONTENT" not in log


def test_a_line_break_cannot_end_the_title_header_early(box):
    cp = box.run("line one\nInjected: yes", "Body")
    assert cp.returncode == 0
    (args,) = box.pushes()
    assert "Title: line one Injected: yes" in args


def test_usage_errors_are_not_silent(box):
    assert box.run("only-one-arg").returncode == 64
    assert box.run("--issue", "abc", "T", "B").returncode == 64
    assert box.run("--retry-pending").returncode == 64


def test_a_failed_push_marks_the_tracker_and_a_later_success_clears_it(box):
    box.seed_body(42, "Production health check failed.")
    fail = box.run("--issue", "https://github.com/o/r/issues/42", "T", "B", curl_exit=7)
    assert fail.returncode == 1
    assert box.body(42).endswith(MARKER)
    assert box.body(42).startswith("Production health check failed.")
    again = box.run("--issue", "42", "T", "B", curl_exit=7)
    assert again.returncode == 1
    assert box.body(42).count(MARKER) == 1, "the marker is added once, not per failure"
    ok = box.run("--issue", "42", "T", "B")
    assert ok.returncode == 0
    assert MARKER not in box.body(42)
    assert box.body(42) == "Production health check failed."


def test_a_misconfigured_url_also_leaves_the_push_pending(box):
    box.seed_body(5, "body")
    cp = box.run("--issue", "5", "T", "B", url="http://ntfy.example.invalid/t")
    assert cp.returncode == 2
    assert MARKER in box.body(5)


def test_retry_pending_pushes_only_when_the_marker_is_there(box):
    box.seed_body(9, "body without marker")
    quiet = box.run("--retry-pending", "9", "T", "B")
    assert quiet.returncode == 0 and box.pushes() == []
    box.seed_body(9, "body\n\n" + MARKER)
    still_down = box.run("--retry-pending", "9", "T", "B", curl_exit=6)
    assert still_down.returncode == 1 and MARKER in box.body(9)
    delivered = box.run("--retry-pending", "9", "T", "B")
    assert delivered.returncode == 0
    assert len(box.pushes()) == 2
    assert MARKER not in box.body(9)


def test_retry_pending_that_cannot_read_the_issue_says_so(box):
    cp = box.run("--retry-pending", "404", "T", "B")
    assert cp.returncode == 1
    assert "::warning title=Owner push retry skipped::" in cp.stdout
    assert box.pushes() == []


# --------------------------------------------------------------------------
# the wiring
# --------------------------------------------------------------------------


def _documents():
    for name in PUSHING_WORKFLOWS:
        yield name, yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _steps_calling_the_script():
    for name, document in _documents():
        for job_id, job in document["jobs"].items():
            steps = job.get("steps") or []
            for index, step in enumerate(steps):
                if "scripts/notify_owner.sh" in (step.get("run") or ""):
                    yield name, job_id, steps, index, step


def test_no_workflow_keeps_an_inline_push():
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        assert "notify_owner() {" not in text, f"{path.name} defines its own notify_owner"
        for line in text.splitlines():
            if "curl" in line:
                assert "NOTIFY_WEBHOOK_URL" not in line, f"{path.name}: inline push: {line}"


def test_every_pushing_workflow_uses_the_shared_script():
    found = {name for name, *_ in _steps_calling_the_script()}
    assert found == set(PUSHING_WORKFLOWS)


def test_every_step_that_pushes_receives_the_secret_and_a_checkout_precedes_it():
    seen = 0
    for name, job_id, steps, index, step in _steps_calling_the_script():
        seen += 1
        assert (step.get("env") or {}).get(
            "NOTIFY_WEBHOOK_URL"
        ) == "${{ secrets.NOTIFY_WEBHOOK_URL }}", f"{name}::{job_id}::{step.get('name')}"
        checkouts = [s for s in steps[:index] if "actions/checkout" in str(s.get("uses") or "")]
        assert checkouts, f"{name}::{job_id}: the script is not on disk without a checkout"
    assert seen >= 8


def test_the_health_job_checks_out_only_the_script_and_the_validator():
    doc = yaml.safe_load((WORKFLOWS / "health-check.yml").read_text(encoding="utf-8"))
    first = doc["jobs"]["health"]["steps"][0]
    assert "actions/checkout" in first["uses"]
    assert first["with"]["sparse-checkout"].split() == [
        "scripts/notify_owner.sh",
        "src/utils/owner_notify.py",
    ]


def test_every_tracker_push_is_tied_to_its_issue():
    """A push from a tracker step names its issue (``--issue`` on create /
    recovery / a changed SLO set, ``--retry-pending`` everywhere else), so a
    push that does not go out is always left pending somewhere a later run
    looks.  The manual TEST push is the one untied call."""
    calls = 0
    for name, document in _documents():
        for job in document["jobs"].values():
            for step in job.get("steps") or []:
                for line in (step.get("run") or "").splitlines():
                    if "scripts/notify_owner.sh" not in line or line.lstrip().startswith("#"):
                        continue
                    calls += 1
                    if "[TEST]" in line:
                        continue
                    assert (
                        "--issue" in line or "--retry-pending" in line
                    ), f"{name}::{step.get('name')}: a push not tied to a tracker: {line}"
    assert calls >= 13, calls


def test_the_url_value_is_never_echoed():
    expansion = re.compile(r"\$\{?NOTIFY_WEBHOOK_URL")
    for path in [*(WORKFLOWS / name for name in PUSHING_WORKFLOWS), SCRIPT]:
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"\b(echo|printf)\b", line):
                assert not expansion.search(line), f"{path.name}: {line}"


def test_the_script_discards_curl_stderr():
    text = SCRIPT.read_text(encoding="utf-8")
    curl = [ln for ln in text.splitlines() if ln.strip().startswith("curl ")]
    assert curl, "the POST moved; re-pin this guard"
    joined = text[text.index(curl[0].strip()) :]
    assert ">/dev/null 2>&1" in joined.split("||", 1)[0]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_the_script_is_valid_bash():
    cp = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr


def test_a_rejected_url_is_named_by_reason_code_and_never_echoed(box):
    for value, reason in (
        ("https://user:pw@ntfy.example.invalid/private-topic-x", "userinfo"),
        ("HTTPS://ntfy.example.invalid/private-topic-x", "scheme"),
    ):
        cp = box.run("Title X", "Body Y", url=value)
        assert cp.returncode == 2, cp.stdout
        assert f"rejected ({reason})" in cp.stdout
        assert box.pushes() == []
        assert "private-topic" not in cp.stdout + cp.stderr


def test_without_the_validator_file_the_https_test_still_applies(box):
    """health-check.yml carries the validator; the other workflows' sparse
    checkouts hold only this script and must keep working."""
    lone = box.dir / "lone" / "scripts"
    lone.mkdir(parents=True)
    shutil.copy(SCRIPT, lone / "notify_owner.sh")
    env = {
        "PATH": f"{box.bin}{os.pathsep}{os.environ['PATH']}",
        "CURL_LOG": str(box.curl_log),
        "TMPDIR": str(box.dir),
        "NOTIFY_WEBHOOK_URL": "http://ntfy.example.invalid/private-topic-x",
    }
    cp = subprocess.run(
        ["bash", str(lone / "notify_owner.sh"), "T", "B"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=box.dir,
    )
    assert cp.returncode == 2 and "rejected (scheme)" in cp.stdout
    assert "private-topic" not in cp.stdout + cp.stderr
