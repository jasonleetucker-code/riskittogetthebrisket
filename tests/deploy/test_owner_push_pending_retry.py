"""A push that does not go out is retried by the next run, never lost.

COV-DEPLOYLAG / COV-REFRESH.  Every tracker pushes the owner when it is
CREATED and on RECOVERY.  Later failing runs take the comment branch, which
does not push -- so before this change a failed first push (an ntfy blip, a
10 s timeout) was a ``::warning`` in a log and the owner never heard of the
incident at all.  Now the shared script leaves ``<!-- owner-push: pending -->``
on the tracker and the next run retries it.

These run each workflow's REAL tracker shell (extracted from the YAML) against
the ``gh`` stub of ``test_sharp_tracker_dedup.py`` and a ``curl`` stub, with
real ``jq`` and the real ``scripts/notify_owner.sh``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.deploy.test_sharp_tracker_dedup import SPECS, Harness, Spec, _step_script

MARKER = "<!-- owner-push: pending -->"
URL = "https://ntfy.example.invalid/private-topic-for-tests"

CURL_STUB = """#!/usr/bin/env bash
{ printf 'ARGS:'; printf ' %s' "$@"; printf '\\n'; } >> "$CURL_LOG"
cat > /dev/null
exit "$(cat "$CURL_EXIT_FILE" 2>/dev/null || echo 0)"
"""

HEALTH = Spec(
    "health-check.yml",
    "production-health",
    "Production health check failing",
    "Open or update the tracking issue on failure",
    "Close the tracking issue on a green run",
)
REFRESH = next(s for s in SPECS if s.workflow.name == "scheduled-refresh.yml")
SMOKE = next(s for s in SPECS if s.workflow.name == "prod-e2e-smoke.yml")


@pytest.fixture(autouse=True)
def _needs_jq():
    if shutil.which("jq") is None:  # pragma: no cover - environment guard
        pytest.skip("jq is required: the trackers' own jq programs are under test")


class PushHarness(Harness):
    def __init__(self, tmp_path: Path, spec: Spec, seed=None):
        super().__init__(tmp_path, spec, "app/github-actions", seed=seed)
        curl = self.bindir / "curl"
        curl.write_text(CURL_STUB, encoding="utf-8")
        curl.chmod(0o755)
        self.curl_log = tmp_path / "curl.log"
        self.curl_exit = tmp_path / "curl_exit"

    def step(self, name: str, *, curl_exit: int = 0, extra=None):
        self.curl_exit.write_text(str(curl_exit), encoding="utf-8")
        env = {
            "NOTIFY_WEBHOOK_URL": URL,
            "CURL_LOG": str(self.curl_log),
            "CURL_EXIT_FILE": str(self.curl_exit),
            "TMPDIR": str(self.dir),
        }
        env.update(extra or {})
        result = self.run(_step_script(self.spec, name), env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "private-topic" not in result.stdout + result.stderr
        return result

    def pushes(self) -> list[str]:
        if not self.curl_log.exists():
            return []
        return [ln for ln in self.curl_log.read_text(encoding="utf-8").splitlines()]

    def seed_api(self, payload: dict) -> None:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["api"] = {"repos/o/r/actions/runs/1/attempts/1/jobs": payload}
        self.state_path.write_text(json.dumps(state), encoding="utf-8")


def _jobs(*failing: str) -> dict:
    steps = [{"name": "Checkout", "conclusion": "success"}]
    steps += [{"name": name, "conclusion": "failure"} for name in failing]
    return {"jobs": [{"steps": steps}]}


@pytest.mark.parametrize("spec", [HEALTH, SMOKE, REFRESH], ids=lambda s: s.workflow.name)
def test_a_failed_first_push_is_marked_then_delivered_by_the_next_run(tmp_path, spec):
    h = PushHarness(tmp_path, spec)
    h.step(spec.open_step, curl_exit=7)  # ntfy is down when the incident opens
    (tracker,) = h.open_trackers()
    assert MARKER in tracker["body"], "the undelivered push must be recorded on the tracker"
    assert len(h.pushes()) == 1

    h.step(spec.open_step)  # next failing run: ntfy is back
    (tracker,) = h.open_trackers()
    assert len(h.pushes()) == 2, "the next run must deliver the pending push"
    assert "Title: Risk It:" in h.pushes()[-1]
    assert MARKER not in tracker["body"]

    h.step(spec.open_step)  # and nothing more after that
    assert len(h.pushes()) == 2, "a delivered push is not repeated on every run"


@pytest.mark.parametrize("spec", [HEALTH, SMOKE, REFRESH], ids=lambda s: s.workflow.name)
def test_pushes_happen_on_create_and_recovery_only(tmp_path, spec):
    h = PushHarness(tmp_path, spec)
    for _ in range(3):
        h.step(spec.open_step)
    assert len(h.pushes()) == 1, "one push per incident, not one per failing run"
    assert "failing" in h.pushes()[0]
    h.step(spec.close_step)
    assert len(h.pushes()) == 2 and "recovered" in h.pushes()[-1]
    h.step(spec.close_step)  # an all-green run with nothing open: quiet
    assert len(h.pushes()) == 2


@pytest.mark.parametrize("spec", [HEALTH, SMOKE, REFRESH], ids=lambda s: s.workflow.name)
def test_an_undelivered_recovery_push_is_retried_from_the_closed_tracker(tmp_path, spec):
    h = PushHarness(tmp_path, spec)
    h.step(spec.open_step)
    h.step(spec.close_step, curl_exit=7)  # recovery push lost
    closed = [i for i in h.issues if i["title"] == spec.title]
    assert closed[0]["state"] == "closed" and MARKER in closed[0]["body"]
    h.step(spec.close_step)  # next green run
    assert len(h.pushes()) == 3 and "recovered" in h.pushes()[-1]
    closed = [i for i in h.issues if i["title"] == spec.title]
    assert MARKER not in closed[0]["body"]
    h.step(spec.close_step)
    assert len(h.pushes()) == 3


def test_an_unset_secret_never_marks_anything(tmp_path):
    h = PushHarness(tmp_path, HEALTH)
    h.step(HEALTH.open_step, extra={"NOTIFY_WEBHOOK_URL": ""})
    (tracker,) = h.open_trackers()
    assert MARKER not in tracker["body"]
    assert h.pushes() == []


# --------------------------------------------------------------------------
# CI-3c: the refresh tracker comments only when its STATE changes
# --------------------------------------------------------------------------


def test_refresh_tracker_comments_once_per_state_and_names_the_failing_steps(tmp_path):
    h = PushHarness(tmp_path, REFRESH)
    (h.runner_temp / "dlf_stale_boards.txt").write_text("dlfRookieSf dlfRookieIdp\n", "utf-8")
    h.seed_api(_jobs("Assert DLF freshness"))
    h.step(REFRESH.open_step)
    (tracker,) = h.open_trackers()
    assert "Failing steps: Assert DLF freshness" in tracker["body"]
    assert "dlfRookieSf,dlfRookieIdp" in tracker["body"]
    assert "journalctl -u dynasty-dlf-fetch.service" in tracker["body"]
    assert "repo secrets" not in tracker["body"]

    h.step(REFRESH.open_step)
    h.step(REFRESH.open_step)
    assert h.open_trackers()[0]["comments"] == 0, "same state, same tracker, no comment"

    # A second cause appears: that is news, once.
    (h.runner_temp / "staleness.log").write_text(
        "::error title=Stale source: ktcCrowdSfTep::Last fetched x (30.0h ago)\n"
        "\nfail: 1 stale source(s), 0 unmeasurable, 20 fresh.  Stale: ktcCrowdSfTep\n",
        encoding="utf-8",
    )
    h.seed_api(_jobs("Assert DLF freshness", "Staleness watchdog"))
    h.step(REFRESH.open_step)
    h.step(REFRESH.open_step)
    (tracker,) = h.open_trackers()
    assert tracker["comments"] == 1
    comment = tracker["comment_bodies"][-1]
    assert "Failing steps: Assert DLF freshness; Staleness watchdog" in comment
    assert "ktcCrowdSfTep" in comment
    assert len(h.pushes()) == 1, "a changed state comments; it does not push again"


def test_refresh_state_ignores_ages_that_change_every_run(tmp_path):
    h = PushHarness(tmp_path, REFRESH)
    h.seed_api(_jobs("Staleness watchdog"))
    log = h.runner_temp / "staleness.log"
    for age in ("30.0", "32.0", "34.0"):
        log.write_text(
            f"::error title=Stale source: dlfSf::Last fetched x ({age}h ago, threshold 24.0h)\n"
            f"fail: 1 stale source(s), 0 unmeasurable, 20 fresh.  Stale: dlfSf\n",
            encoding="utf-8",
        )
        h.step(REFRESH.open_step)
    assert h.open_trackers()[0]["comments"] == 0


def test_refresh_tracker_that_predates_the_marker_gets_one_comment_then_quiet(tmp_path):
    seed = [
        {
            "number": 2261,
            "title": REFRESH.title,
            "author": "app/github-actions",
            "state": "open",
            "labels": [REFRESH.label],
            "comments": 3,
            "body": "Scheduled data refresh failed. (legacy body, no state marker)",
            "comment_bodies": ["Likely causes: ..."] * 3,
        }
    ]
    h = PushHarness(tmp_path, REFRESH, seed=seed)
    h.seed_api(_jobs("Assert DLF freshness"))
    for _ in range(3):
        h.step(REFRESH.open_step)
    assert h.open_trackers()[0]["comments"] == 4
    assert h.pushes() == [], "an existing tracker is not a new incident"


def test_refresh_unreadable_step_list_is_unknown_not_none(tmp_path):
    h = PushHarness(tmp_path, REFRESH)
    h.step(REFRESH.open_step)  # no api seeded: the jobs call fails
    (tracker,) = h.open_trackers()
    assert "Failing steps: unknown (the run's step list could not be read)" in tracker["body"]


# --------------------------------------------------------------------------
# the SLO tracker rewrites its body every run: the marker must survive that
# --------------------------------------------------------------------------


def _slo_report(h: PushHarness, breached: list[str]) -> None:
    (h.dir / "slo_report.json").write_text(
        json.dumps({"breached": breached, "unknown": []}), encoding="utf-8"
    )
    (h.dir / "slo_report.txt").write_text("BREACHED: " + ",".join(breached), encoding="utf-8")


SLO = Spec(
    "health-check.yml",
    "production-health",
    "Production SLO alert",
    "Sync the rolling SLO tracking issue",
    "Sync the rolling SLO tracking issue",
)


def test_slo_push_lost_at_creation_survives_the_body_rewrite_and_is_retried(tmp_path):
    h = PushHarness(tmp_path, SLO)
    _slo_report(h, ["deploy_lag"])
    h.step(SLO.open_step, curl_exit=7, extra={"RC": "1"})
    (tracker,) = h.open_trackers()
    assert MARKER in tracker["body"]

    h.step(SLO.open_step, curl_exit=7, extra={"RC": "1"})  # still down
    (tracker,) = h.open_trackers()
    assert MARKER in tracker["body"], "the in-place body rewrite must carry the marker"
    assert "slo-signature: deploy_lag" in tracker["body"]

    h.step(SLO.open_step, extra={"RC": "1"})  # ntfy back, same conditions
    (tracker,) = h.open_trackers()
    assert MARKER not in tracker["body"]
    assert len(h.pushes()) == 3
    h.step(SLO.open_step, extra={"RC": "1"})
    assert len(h.pushes()) == 3, "same conditions, delivered: no further push"


def test_slo_changed_conditions_still_push_and_recovery_pushes(tmp_path):
    h = PushHarness(tmp_path, SLO)
    _slo_report(h, ["deploy_lag"])
    h.step(SLO.open_step, extra={"RC": "1"})
    _slo_report(h, ["deploy_lag", "refresh_pipeline"])
    h.step(SLO.open_step, extra={"RC": "1"})
    assert len(h.pushes()) == 2 and "conditions changed" in h.pushes()[-1]
    h.step(SLO.open_step, extra={"RC": "0"})
    assert len(h.pushes()) == 3 and "recovered" in h.pushes()[-1]
    assert h.open_trackers() == []
