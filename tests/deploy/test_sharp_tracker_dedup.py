"""The Sharp unverifiable tracker must open ONE issue, then reuse it.

Issue #958, 2026-08-20.  A regression from #948, measured in production:
``verify-sharp-production.yml`` opened a NEW ``sharp-unverifiable`` issue on
every run — #951, #953, #955, #957 in 67 minutes, one per run, 1:1 — while
three matching open issues sat there unfound.  Projected ~85 issues/day,
against the ~48 smoke commits/day the same PR correctly removed.  The churn
moved medium; it did not stop.

This is the THIRD appearance of one defect.  ``e2e.yml``'s AUDIT F-23 note
records the first (14 undrained trackers, 0 comments between them); #948
inherited that file's predicate verbatim and so inherited the bug.

WHY THE EARLIER FIXES DID NOT HOLD
==================================
Both previous attempts guessed at the author spelling and pinned a
transformation for it — first the bare ``github-actions``, then normalising a
``[bot]`` SUFFIX away.  Neither was ever reproduced against real ``gh``
output; F-23's own note calls the spelling question "a bet".

So this test does not bet.  It runs the workflow's REAL shell against a ``gh``
stub and REAL ``jq``, and it does so for every spelling ``gh`` is known or
suspected to emit — ``github-actions``, ``github-actions[bot]`` and
``app/github-actions`` (``gh`` prefixes bot actors with ``app/`` in its
``--json author`` output).  A predicate that survives all three is correct
whichever one is real, which is a stronger property than identifying the
spelling and pinning it a third time.

NON-VACUITY
===========
These tests FAIL against the predicate on ``main`` at the time of writing:
under ``app/github-actions`` the author clause rejects the tracker, the lookup
returns ``null`` without erroring, and the second run creates a second issue.
That is the production behaviour reproduced in a test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


class Spec:
    """One workflow's tracker pair.  Both carried the identical predicate, so
    both carried the identical defect — e2e.yml first (F-23, 14 duplicates),
    verify-sharp-production.yml by inheritance (#958, 4 in 67 minutes)."""

    def __init__(self, workflow, label, title, open_step, close_step):
        self.workflow = WORKFLOWS / workflow
        self.label = label
        self.title = title
        self.open_step = open_step
        self.close_step = close_step

    def __repr__(self):  # pragma: no cover - test ids only
        return self.workflow.name


SPECS = [
    Spec(
        "verify-sharp-production.yml",
        "sharp-unverifiable",
        "Sharp production gate cannot measure: /api/sharp/* has no credential",
        "Track that the Sharp gate cannot measure",
        "Close the unmeasurable-gate tracker once the smoke can measure",
    ),
    Spec(
        "e2e.yml",
        "e2e-failures",
        "E2E safety net failing",
        "Alert on workflow failure",
        "Close the tracking issue when the suite is green",
    ),
]

# Every spelling `gh` is known or suspected to emit for this bot.
BOT_LOGINS = ("github-actions", "github-actions[bot]", "app/github-actions")


def _step_script(spec: "Spec", name: str) -> str:
    document = yaml.safe_load(spec.workflow.read_text(encoding="utf-8")) or {}
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == name:
                script = step.get("run")
                assert isinstance(script, str), f"step {name!r} has no run: block"
                return script
    raise AssertionError(f"step {name!r} not found in {spec.workflow.name}")


GH_STUB = r"""#!/usr/bin/env python3
import json, os, sys, subprocess

STATE = os.environ["GH_STUB_STATE"]

def load():
    with open(STATE) as fh:
        return json.load(fh)

def save(s):
    with open(STATE, "w") as fh:
        json.dump(s, fh)

argv = sys.argv[1:]
state = load()

if argv[:2] == ["label", "create"]:
    sys.exit(0)

if argv[:2] == ["issue", "list"]:
    label = None
    want_state = None
    jq_expr = None
    i = 2
    while i < len(argv):
        if argv[i] == "--label":
            label = argv[i + 1]; i += 2
        elif argv[i] == "--state":
            want_state = argv[i + 1]; i += 2
        elif argv[i] == "--json":
            i += 2
        elif argv[i] == "--jq":
            jq_expr = argv[i + 1]; i += 2
        else:
            i += 1
    rows = [
        {"number": it["number"], "title": it["title"],
         "author": {"login": it["author"], "is_bot": True}}
        for it in state["issues"]
        if (want_state is None or it["state"] == want_state)
        and (label is None or label in it["labels"])
    ]
    state["list_calls"] = state.get("list_calls", 0) + 1
    save(state)
    payload = json.dumps(rows)
    if jq_expr is None:
        sys.stdout.write(payload)
        sys.exit(0)
    proc = subprocess.run(["jq", "-r", jq_expr], input=payload,
                          capture_output=True, text=True)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        sys.exit(proc.returncode)
    out = proc.stdout.strip()
    sys.stdout.write("" if out == "null" else out)
    sys.exit(0)

if argv[:2] == ["issue", "create"]:
    title = argv[argv.index("--title") + 1]
    labels = [argv[argv.index("--label") + 1]] if "--label" in argv else []
    number = state["next_number"]
    state["next_number"] += 1
    state["issues"].append({"number": number, "title": title,
                            "author": state["bot_login"], "state": "open",
                            "labels": labels, "comments": 0})
    save(state)
    print(f"https://github.com/o/r/issues/{number}")
    sys.exit(0)

if argv[:2] == ["issue", "comment"]:
    n = int(argv[2])
    for it in state["issues"]:
        if it["number"] == n:
            it["comments"] += 1
    save(state)
    print(f"https://github.com/o/r/issues/{n}#issuecomment-1")
    sys.exit(0)

if argv[:2] == ["issue", "close"]:
    n = int(argv[2])
    for it in state["issues"]:
        if it["number"] == n:
            it["state"] = "closed"
    save(state)
    sys.exit(0)

sys.stderr.write(f"gh stub: unhandled {argv}\n")
sys.exit(3)
"""


class Harness:
    def __init__(self, tmp_path: Path, spec: Spec, bot_login: str, seed: list[dict] | None = None):
        self.spec = spec
        self.dir = tmp_path
        self.state_path = tmp_path / "state.json"
        self.state_path.write_text(
            json.dumps(
                {
                    "issues": seed or [],
                    "next_number": 951,
                    "bot_login": bot_login,
                    "list_calls": 0,
                }
            )
        )
        bindir = tmp_path / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(GH_STUB)
        gh.chmod(0o755)
        self.bindir = bindir

    def run(self, script: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.bindir}:{env['PATH']}",
                "GH_STUB_STATE": str(self.state_path),
                "GH_TOKEN": "stub",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "o/r",
                "GITHUB_RUN_ID": "1",
                "STATE_SINCE": "2026-08-20T07:40:06.649789+00:00",
                "LAST_MEASURED_ON": "",
                "GITHUB_SHA": "0" * 40,
                "GITHUB_WORKFLOW": "E2E Safety Net",
                "GITHUB_EVENT_NAME": "schedule",
            }
        )
        return subprocess.run(
            ["bash", "-c", script], env=env, capture_output=True, text=True, cwd=self.dir
        )

    @property
    def issues(self) -> list[dict]:
        return json.loads(self.state_path.read_text())["issues"]

    def open_trackers(self) -> list[dict]:
        return [i for i in self.issues if i["state"] == "open" and i["title"] == self.spec.title]


@pytest.fixture(autouse=True)
def _needs_jq():
    if shutil.which("jq") is None:  # pragma: no cover - environment guard
        pytest.skip("jq is required: the point of this test is the REAL jq program")


@pytest.mark.parametrize("spec", SPECS, ids=repr)
@pytest.mark.parametrize("bot_login", BOT_LOGINS)
def test_first_run_opens_exactly_one_tracker(tmp_path, spec, bot_login):
    h = Harness(tmp_path, spec, bot_login)
    result = h.run(_step_script(spec, spec.open_step))
    assert result.returncode == 0, result.stderr
    assert len(h.open_trackers()) == 1, f"first run should open one tracker: {h.issues}"


@pytest.mark.parametrize("spec", SPECS, ids=repr)
@pytest.mark.parametrize("bot_login", BOT_LOGINS)
def test_second_identical_run_reuses_the_tracker_and_does_not_duplicate(tmp_path, spec, bot_login):
    """THE REGRESSION.  Fails on the pre-#958 predicate for app/github-actions."""
    h = Harness(tmp_path, spec, bot_login)
    script = _step_script(spec, spec.open_step)

    first = h.run(script)
    assert first.returncode == 0, first.stderr
    second = h.run(script)
    assert second.returncode == 0, second.stderr

    trackers = h.open_trackers()
    assert len(trackers) == 1, (
        f"second identical run must reuse the tracker, not open another "
        f"(login {bot_login!r}): {h.issues}"
    )
    assert trackers[0]["comments"] == 1, "the second run must COMMENT on the tracker"


@pytest.mark.parametrize("spec", SPECS, ids=repr)
@pytest.mark.parametrize("bot_login", BOT_LOGINS)
def test_recovery_closes_every_tracker_it_opened(tmp_path, spec, bot_login):
    h = Harness(tmp_path, spec, bot_login)
    h.run(_step_script(spec, spec.open_step))
    assert len(h.open_trackers()) == 1

    result = h.run(_step_script(spec, spec.close_step))
    assert result.returncode == 0, result.stderr
    assert h.open_trackers() == [], f"recovery must close the tracker: {h.issues}"


@pytest.mark.parametrize("spec", SPECS, ids=repr)
@pytest.mark.parametrize("bot_login", BOT_LOGINS)
def test_recovery_drains_the_duplicates_that_already_accumulated(tmp_path, spec, bot_login):
    """#951/#953/#955/#957 are real and open.  Recovery must drain all of them."""
    seed = [
        {
            "number": n,
            "title": spec.title,
            "author": bot_login,
            "state": "open",
            "labels": [spec.label],
            "comments": 0,
        }
        for n in (951, 953, 955, 957)
    ]
    h = Harness(tmp_path, spec, bot_login, seed=seed)
    result = h.run(_step_script(spec, spec.close_step))
    assert result.returncode == 0, result.stderr
    assert h.open_trackers() == [], f"all four duplicates must close: {h.issues}"


@pytest.mark.parametrize("spec", SPECS, ids=repr)
@pytest.mark.parametrize("bot_login", BOT_LOGINS)
def test_an_existing_tracker_is_reused_rather_than_a_second_one_opened(tmp_path, spec, bot_login):
    """Seeded state, no prior run in this process: the step must still find it."""
    seed = [
        {
            "number": 951,
            "title": spec.title,
            "author": bot_login,
            "state": "open",
            "labels": [spec.label],
            "comments": 0,
        }
    ]
    h = Harness(tmp_path, spec, bot_login, seed=seed)
    result = h.run(_step_script(spec, spec.open_step))
    assert result.returncode == 0, result.stderr
    assert len(h.open_trackers()) == 1, f"must reuse #951: {h.issues}"
    assert h.open_trackers()[0]["number"] == 951


@pytest.mark.parametrize("spec", SPECS, ids=repr)
def test_the_oldest_tracker_is_the_canonical_one(tmp_path, spec):
    """`.[0]` off gh's newest-first sort picked the WRONG issue — the F-23
    mechanism that let #753 displace the real tracker #732.  Pin the choice."""
    seed = [
        {
            "number": n,
            "title": spec.title,
            "author": "github-actions",
            "state": "open",
            "labels": [spec.label],
            "comments": 0,
        }
        for n in (957, 955, 953, 951)  # newest-first, as gh returns them
    ]
    h = Harness(tmp_path, spec, "github-actions", seed=seed)
    result = h.run(_step_script(spec, spec.open_step))
    assert result.returncode == 0, result.stderr
    commented = [i for i in h.issues if i["comments"] > 0]
    assert [i["number"] for i in commented] == [
        951
    ], f"the OLDEST tracker is canonical, not whichever gh sorted first: {h.issues}"


@pytest.mark.parametrize("spec", SPECS, ids=repr)
def test_a_human_issue_carrying_the_label_is_not_hijacked(tmp_path, spec):
    """The author clause is dropped, so TITLE is what protects a human's issue.
    A hand-labelled issue with a different title must not be commented on or
    closed."""
    seed = [
        {
            "number": 900,
            "title": "Sharp cohort looks wrong to me",
            "author": "jasonleetucker-code",
            "state": "open",
            "labels": [spec.label],
            "comments": 0,
        }
    ]
    h = Harness(tmp_path, spec, "github-actions", seed=seed)

    h.run(_step_script(spec, spec.open_step))
    human = [i for i in h.issues if i["number"] == 900][0]
    assert human["comments"] == 0, "must not comment on a human's issue"
    assert len(h.open_trackers()) == 1, "must still open its own tracker"

    h.run(_step_script(spec, spec.close_step))
    human = [i for i in h.issues if i["number"] == 900][0]
    assert human["state"] == "open", "recovery must not close a human's issue"


@pytest.mark.parametrize("spec", SPECS, ids=repr)
def test_lookup_failure_stays_actionable_and_is_not_silently_healthy(tmp_path, spec):
    """A lookup that FAILS must not read like one that found nothing."""
    h = Harness(tmp_path, spec, "github-actions")
    broken = h.bindir / "gh"
    broken.write_text("#!/bin/bash\nexit 7\n")
    broken.chmod(0o755)

    opened = h.run(_step_script(spec, spec.open_step))
    assert "::error title=Tracker lookup failed" in opened.stdout + opened.stderr

    closed = h.run(_step_script(spec, spec.close_step))
    assert "::error title=Tracker lookup failed" in closed.stdout + closed.stderr
    assert closed.returncode != 0, "the all-clear must FAIL, not pass silently"
