"""A Sharp smoke that measured nothing must SAY so, in the run, every time.

Audit RPA-F-019 / RPA-COL-036 / RPA-OPS-009, 2026-10-25.
``Verify Sharp Production Population`` has never once measured production:
``/api/sharp/*`` answers 401, the repository has no ``SHARP_SMOKE_TOKEN``
secret, and ``data/ops/sharp-production-smoke.json`` says
``measured: false`` / ``lastMeasuredOn: null``.  The workflow nevertheless
concludes ``success`` on those runs, and a green tick reads as verification.

THE CONCLUSION IS A DECISION, AND THIS FILE PINS IT
===================================================
The repository's rule for "a credential is missing" is
``test_no_workflow_exits_green_on_missing_secrets.py``: refuse with
``::error`` + ``exit 1``, because a green tick for a run that could not look
is indistinguishable from one that looked and found health.

That guard is mechanical — it fires on a shell ``-z "$SECRET"`` branch that
reaches ``exit 0`` — and this workflow does not have that shape: the secret
is read by the smoke step's Python and reaches the gate as a recorded fact.
So the guard neither forbids nor exempts it, and nobody had decided.

The decision recorded here is the one ``test_sharp_smoke_commit_order.py``
has pinned since 2026-08-20 (warning, not failure), made explicit and made
LOUD: an unprovisioned token ends GREEN but never quietly.  Red on every
push to ``main`` for a credential only the owner can issue is how a gate
gets deleted, and the audit's own repair line allows the owner to "accept an
unmeasured gate".  If the owner would rather have red, ``test_the_conclusion_
for_an_unprovisioned_token_is_green_by_decision`` is the single test to flip.

These tests EXECUTE the workflow's own gate script (extracted from the YAML
at run time, so they cannot drift from the shipped logic).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "verify-sharp-production.yml"

sys.path.insert(0, str(ROOT / "scripts"))
import sharp_smoke_record as record  # noqa: E402

ANNOTATION_ABSENT = (
    "::warning title=Sharp smoke UNVERIFIABLE::"
    "SHARP_SMOKE_TOKEN is not provisioned — nothing was measured"
)

UNAUTHENTICATED = {
    "status": "unverifiable_unauthenticated",
    "cohort": {},
    "ffpcMarket": {},
    "errors": [
        {
            "attempt": 1,
            "type": "Unauthenticated",
            "message": "401 from https://chaseupside.com/api/sharp/cohort",
        }
    ],
    "checkedAt": "2026-10-26T16:55:17+00:00",
    "eventName": "push",
    "deployConclusion": "pending",
    "deployRunId": "",
    "deployHeadSha": "abedb3a3676c95d594da7ac375e951e958d15050",
    "attempts": 1,
}


def _gate_body() -> str:
    """The 'Enforce healthy population' step's python, straight from the YAML."""
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in document["jobs"]["verify"]["steps"]:
        if step.get("name") == "Enforce healthy population":
            script = step["run"]
            return script.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0] + "\n"
    raise AssertionError("the 'Enforce healthy population' step is gone")


def _run_gate(tmp_path: Path, result: dict) -> tuple[subprocess.CompletedProcess, str, str]:
    """Execute the gate over ``result``; return (process, summary text, outputs text)."""
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    (runner_temp / "sharp-smoke-current.json").write_text(json.dumps(result), encoding="utf-8")
    summary = tmp_path / "summary.md"
    outputs = tmp_path / "outputs.txt"
    script = tmp_path / "gate.py"
    script.write_text(_gate_body(), encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_STEP_SUMMARY": str(summary),
            "GITHUB_OUTPUT": str(outputs),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    proc = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return (
        proc,
        summary.read_text(encoding="utf-8") if summary.exists() else "",
        outputs.read_text(encoding="utf-8") if outputs.exists() else "",
    )


def _run_scoped(result: dict, *, previous=None) -> dict:
    """What the smoke step would hand the gate for this run."""
    return record.build_record(
        previous, result, now_iso="2026-10-26T16:55:17+00:00", today="2026-10-26"
    )


def test_the_gate_script_was_actually_extracted_and_is_not_trivial():
    """Vacuity guard: every assertion below executes this."""
    body = _gate_body()
    assert "unverifiable_unauthenticated" in body and "SystemExit" in body
    compile(body, "<gate>", "exec")


# --------------------------------------------------------------------------
# token absent
# --------------------------------------------------------------------------


def test_an_unprovisioned_token_emits_the_exact_unverifiable_warning(tmp_path):
    result = _run_scoped(dict(UNAUTHENTICATED, tokenProvisioned=False))
    proc, _summary, _outputs = _run_gate(tmp_path, result)
    assert ANNOTATION_ABSENT in proc.stdout.splitlines(), proc.stdout + proc.stderr


def test_an_unprovisioned_token_is_written_to_the_job_summary(tmp_path):
    result = _run_scoped(dict(UNAUTHENTICATED, tokenProvisioned=False))
    proc, summary, _outputs = _run_gate(tmp_path, result)
    assert proc.returncode == 0, proc.stderr
    assert "Sharp smoke UNVERIFIABLE" in summary
    assert "SHARP_SMOKE_TOKEN is not provisioned — nothing was measured" in summary
    assert "Green here is not verification" in summary
    assert "Last time it could measure: `never`" in summary
    # The one action that fixes it travels with the finding.
    assert "restart the `dynasty` service" in summary


def test_the_conclusion_for_an_unprovisioned_token_is_green_by_decision(tmp_path):
    """The recorded decision (see module docstring).  Flip this to flip the policy."""
    result = _run_scoped(dict(UNAUTHENTICATED, tokenProvisioned=False))
    proc, _summary, outputs = _run_gate(tmp_path, result)
    assert proc.returncode == 0, (
        "an unprovisioned token no longer exits 0.  That may be the right call, but "
        "it contradicts test_sharp_smoke_commit_order.py's standing warning-not-failure "
        "pin and must be an owner decision, not a drive-by"
    )
    # ...and it is green WITHOUT claiming to have measured anything.
    assert "measured=false" in outputs
    assert "status=unverifiable_unauthenticated" in outputs


# --------------------------------------------------------------------------
# the other two token states say different things
# --------------------------------------------------------------------------


def test_a_provisioned_but_rejected_token_is_not_described_as_unprovisioned(tmp_path):
    result = _run_scoped(dict(UNAUTHENTICATED, tokenProvisioned=True))
    proc, summary, _outputs = _run_gate(tmp_path, result)
    assert proc.returncode == 0, proc.stderr
    assert "::warning title=Sharp smoke UNVERIFIABLE::" in proc.stdout
    assert "is not provisioned" not in proc.stdout + summary, (
        "a token that WAS presented and refused is a different problem with a different "
        "owner action (match production's .env and restart); calling it 'not provisioned' "
        "sends the owner to set a secret that already exists"
    )
    assert "provisioned but /api/sharp/* rejected it" in proc.stdout


def test_an_unrecorded_token_state_is_unknown_not_absent(tmp_path):
    """Missing is not False: a record that never stated it must not claim 'absent'."""
    legacy = dict(UNAUTHENTICATED)  # no tokenProvisioned key at all
    result = _run_scoped(legacy)
    assert result["tokenProvisioned"] is None
    proc, summary, _outputs = _run_gate(tmp_path, result)
    assert proc.returncode == 0, proc.stderr
    assert "is not provisioned" not in proc.stdout + summary
    assert "::warning title=Sharp smoke UNVERIFIABLE::" in proc.stdout


# --------------------------------------------------------------------------
# nothing else got quieter or louder
# --------------------------------------------------------------------------


def test_losing_a_credential_that_once_worked_is_still_red(tmp_path):
    measured = _run_scoped(
        {
            "status": "healthy",
            "cohort": {"qualifiedManagers": 12},
            "ffpcMarket": {"assetRows": 100},
            "errors": [],
        }
    )
    lost = _run_scoped(dict(UNAUTHENTICATED, tokenProvisioned=True), previous=measured)
    assert lost["credentialRegression"] is True
    proc, _summary, _outputs = _run_gate(tmp_path, lost)
    assert proc.returncode != 0
    assert "::error title=Sharp smoke lost its credential" in proc.stderr


def test_a_healthy_run_does_not_emit_the_unverifiable_warning(tmp_path):
    healthy = _run_scoped(
        {
            "status": "healthy",
            "cohort": {"qualifiedManagers": 12},
            "ffpcMarket": {"assetRows": 100},
            "errors": [],
            "tokenProvisioned": True,
        }
    )
    proc, summary, _outputs = _run_gate(tmp_path, healthy)
    assert proc.returncode == 0, proc.stderr
    assert "UNVERIFIABLE" not in proc.stdout + summary


def test_a_failed_deploy_is_still_red_and_is_not_called_unverifiable(tmp_path):
    failed = _run_scoped({"status": "deploy_failed", "cohort": {}, "ffpcMarket": {}, "errors": []})
    proc, summary, _outputs = _run_gate(tmp_path, failed)
    assert proc.returncode != 0
    assert "UNVERIFIABLE" not in proc.stdout + summary


def test_a_superseded_deploy_makes_no_unverifiable_claim(tmp_path):
    """No probe ran, so there is no 'token' finding to announce — a notice only.

    Found while writing this file: the gate's ``deploy_superseded`` branch
    interpolated ``deploy_conclusion``, which is defined in the SMOKE step's
    python and not in the gate's, so every superseded run died with
    ``NameError`` and concluded FAILURE.  12 of the 15 red ``workflow_run``
    runs retained on 2026-10-26 were this, not a deploy failure.  The two
    no-verdict branches were always meant to exit 0 with a notice
    (``test_the_two_no_verdict_statuses_are_handled_downstream``), and until
    something EXECUTED them nothing could tell they never could.
    """
    superseded = _run_scoped(
        {
            "status": "deploy_superseded",
            "cohort": {},
            "ffpcMarket": {},
            "errors": [],
            "tokenProvisioned": False,
            "deployConclusion": "cancelled",
        }
    )
    proc, summary, _outputs = _run_gate(tmp_path, superseded)
    assert proc.returncode == 0, proc.stderr
    assert "UNVERIFIABLE" not in proc.stdout + summary
    assert "NameError" not in proc.stderr
    assert "::notice title=Sharp smoke made no production claim::" in proc.stdout
    assert "concluded 'cancelled'" in proc.stdout


def test_an_unmeasured_deploy_exits_zero_with_a_warning_and_no_traceback(tmp_path):
    unmeasured = _run_scoped(
        {
            "status": "deploy_unmeasured",
            "cohort": {},
            "ffpcMarket": {},
            "errors": [],
            "tokenProvisioned": False,
            "deployConclusion": "skipped",
        }
    )
    proc, _summary, _outputs = _run_gate(tmp_path, unmeasured)
    assert proc.returncode == 0, proc.stderr
    assert "NameError" not in proc.stderr
    assert "::warning title=Sharp smoke has no deploy conclusion::" in proc.stdout
    assert "concluded 'skipped'" in proc.stdout


# --------------------------------------------------------------------------
# the token fact reaches the gate through the wiring
# --------------------------------------------------------------------------


def _smoke_step_source() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("Wait for deploy and Sharp population")
    end = text.index("Commit production smoke result")
    return "\n".join(
        line for line in text[start:end].splitlines() if not line.lstrip().startswith("#")
    )


def test_the_smoke_step_records_whether_a_token_was_presented():
    assert '"tokenProvisioned": bool(smoke_token)' in _smoke_step_source(), (
        "the smoke step no longer records whether SHARP_SMOKE_TOKEN was presented, so the "
        "gate cannot tell 'not provisioned' from 'provisioned and rejected'"
    )


def test_the_token_value_itself_is_never_written_to_the_record():
    """Only a boolean crosses into the result.  A bearer token in a tracked
    file on a public repository would be a credential leak."""
    source = _smoke_step_source()
    assert '"tokenProvisioned": bool(smoke_token)' in source
    assert '"tokenProvisioned": smoke_token' not in source
    built = _run_scoped(dict(UNAUTHENTICATED, tokenProvisioned=True))
    assert built["tokenProvisioned"] is True
    assert "Bearer" not in json.dumps(built)


# --------------------------------------------------------------------------
# the SHIPPED smoke step, executed end to end (network stubbed to answer 401)
# --------------------------------------------------------------------------
#
# The unit tests above cover the decision functions.  What they cannot show is
# that the workflow's heredoc actually calls them in the right order with the
# right inputs -- the exact gap that let the gate's NameError ship.  So the
# real step is extracted from the YAML and run.

_SMOKE_HARNESS = """
import datetime as _dt
import os
import runpy
import sys
import urllib.error
import urllib.request

class _Fixed(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromisoformat(os.environ["FAKE_NOW"])

_dt.datetime = _Fixed

def _answer_401(request, timeout=None):
    raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

urllib.request.urlopen = _answer_401
runpy.run_path(sys.argv[1], run_name="__main__")
"""


def _smoke_body() -> str:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in document["jobs"]["verify"]["steps"]:
        if str(step.get("name", "")).startswith("Wait for deploy and Sharp population"):
            return step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0] + "\n"
    raise AssertionError("the smoke step is gone")


class _SmokeRepo:
    """A scratch checkout holding just what the smoke step reads and writes."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "checkout"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "scripts" / "sharp_smoke_record.py").write_text(
            (ROOT / "scripts" / "sharp_smoke_record.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (self.root / "data" / "ops").mkdir(parents=True)
        (tmp_path / "harness.py").write_text(_SMOKE_HARNESS, encoding="utf-8")
        (tmp_path / "step.py").write_text(_smoke_body(), encoding="utf-8")
        self.tmp = tmp_path
        self.runs = 0

    @property
    def tracked(self) -> Path:
        return self.root / "data" / "ops" / "sharp-production-smoke.json"

    def tracked_text(self) -> str | None:
        return self.tracked.read_text(encoding="utf-8") if self.tracked.exists() else None

    def run(
        self, *, event, deploy_conclusion, now, token="", deploy_run_id="", deploy_sha="abc"
    ) -> dict:
        self.runs += 1
        runner_temp = self.tmp / f"runner_temp_{self.runs}"
        runner_temp.mkdir()
        summary = self.tmp / f"summary_{self.runs}.md"
        env = os.environ.copy()
        env.update(
            {
                "EVENT_NAME": event,
                "DEPLOY_CONCLUSION": deploy_conclusion,
                "DEPLOY_RUN_ID": deploy_run_id,
                "DEPLOY_HEAD_SHA": deploy_sha,
                "SHARP_SMOKE_TOKEN": token,
                "RUNNER_TEMP": str(runner_temp),
                "GITHUB_STEP_SUMMARY": str(summary),
                "FAKE_NOW": now,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        proc = subprocess.run(
            [sys.executable, str(self.tmp / "harness.py"), str(self.tmp / "step.py")],
            env=env,
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return {
            "stdout": proc.stdout,
            "current": json.loads(
                (runner_temp / "sharp-smoke-current.json").read_text(encoding="utf-8")
            ),
            "summary": summary.read_text(encoding="utf-8"),
        }


def test_the_shipped_smoke_step_does_not_flap_or_recommit_across_a_realistic_day(tmp_path):
    """push, superseded-deploy, push, skipped-deploy, push -- the 16-a-day pattern."""
    repo = _SmokeRepo(tmp_path)

    first = repo.run(event="push", deploy_conclusion="pending", now="2026-10-26T16:10:00+00:00")
    assert "recording: state changed or the day rolled over" in first["stdout"]
    written = repo.tracked_text()
    assert written is not None
    on_disk = json.loads(written)
    assert on_disk["status"] == "unverifiable_unauthenticated"
    assert on_disk["tokenProvisioned"] is False
    assert on_disk["measured"] is False

    for minute, (event, conclusion) in enumerate(
        [
            ("workflow_run", "cancelled"),
            ("push", "pending"),
            ("workflow_run", "skipped"),
            ("push", "pending"),
        ],
        start=11,
    ):
        out = repo.run(
            event=event,
            deploy_conclusion=conclusion,
            now=f"2026-10-26T16:{minute:02d}:00+00:00",
            deploy_run_id="40357247756" if event == "workflow_run" else "",
        )
        assert "not recording" in out["stdout"], out["stdout"]
        assert repo.tracked_text() == written, (
            f"the tracked record changed on a {event}/{conclusion} run with nothing new to say; "
            "that is a commit to main"
        )
        if event == "workflow_run":
            # ...and the GATE's input still reports what this run actually was.
            expected = "deploy_superseded" if conclusion == "cancelled" else "deploy_unmeasured"
            assert out["current"]["status"] == expected
        assert "Standing record: `unverifiable_unauthenticated`" in out["summary"]


def test_the_shipped_smoke_step_still_records_a_genuine_change_and_the_day_rollover(tmp_path):
    repo = _SmokeRepo(tmp_path)
    repo.run(event="push", deploy_conclusion="pending", now="2026-10-26T16:10:00+00:00")
    before = repo.tracked_text()

    # The owner provisions a token that production then refuses: a different
    # problem with a different fix, so it is news.
    changed = repo.run(
        event="push",
        deploy_conclusion="pending",
        now="2026-10-26T17:00:00+00:00",
        token="sentinel-bearer-value",
    )
    assert "recording: state changed" in changed["stdout"]
    assert repo.tracked_text() != before
    assert json.loads(repo.tracked_text())["tokenProvisioned"] is True

    # Nothing changed the next day: exactly one heartbeat write.
    next_day = repo.run(
        event="push",
        deploy_conclusion="pending",
        now="2026-10-27T01:00:00+00:00",
        token="sentinel-bearer-value",
    )
    assert "recording: state changed or the day rolled over" in next_day["stdout"]
    assert json.loads(repo.tracked_text())["lastObservedOn"] == "2026-10-27"


def test_the_shipped_smoke_step_never_writes_the_token_anywhere(tmp_path):
    repo = _SmokeRepo(tmp_path)
    out = repo.run(
        event="push",
        deploy_conclusion="pending",
        now="2026-10-26T16:10:00+00:00",
        token="sentinel-bearer-value",
    )
    everything = out["stdout"] + out["summary"] + json.dumps(out["current"])
    everything += repo.tracked_text() or ""
    assert "sentinel-bearer-value" not in everything
    assert out["current"]["tokenProvisioned"] is True
