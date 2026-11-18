"""A renamed or conditional required check would brick every merge to ``main``.

GitHub matches ``required_status_checks`` by the JOB ``name`` a workflow emits.
Rename ``Validate PR`` and every PR waits forever for a check that never reports.
These tests pin the payload to what the workflows actually emit (owner admin pack,
2026-11-18), and exercise ``apply-branch-protection.sh --dry-run`` offline.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
PAYLOAD = REPO / "deploy" / "github" / "main-protection-ruleset.json"
SCRIPT = REPO / "deploy" / "github" / "apply-branch-protection.sh"
GITHUB_ACTIONS_APP_ID = 15368

# Observed on a merged PR's head commit (2026-11-18): both reported by app 15368.
OBSERVED_REQUIRED = {"Validate PR", "Receipt check"}


def _required() -> list[dict]:
    for rule in json.loads(PAYLOAD.read_text("utf-8"))["rules"]:
        if rule["type"] == "required_status_checks":
            return rule["parameters"]["required_status_checks"]
    raise AssertionError("no required_status_checks rule")


def _emitted_job_names() -> Counter:
    names: Counter = Counter()
    for path in WORKFLOWS.glob("*.yml"):
        wf = yaml.safe_load(path.read_text("utf-8"))
        for key, job in (wf.get("jobs") or {}).items():
            names[str(job.get("name", key))] += 1
    return names


def test_required_checks_are_exactly_the_observed_pr_checks():
    assert {c["context"] for c in _required()} == OBSERVED_REQUIRED


def test_each_required_check_is_emitted_by_exactly_one_static_job():
    emitted = _emitted_job_names()
    for check in _required():
        ctx = check["context"]
        assert emitted[ctx] == 1, f"{ctx!r} must be emitted by exactly one workflow job"
        assert "${{" not in ctx
        assert check["integration_id"] == GITHUB_ACTIONS_APP_ID


def test_required_jobs_run_on_every_pull_request():
    for ctx, wf_name in (
        ("Validate PR", "pr-validation.yml"),
        ("Receipt check", "pr-verification-receipt.yml"),
    ):
        wf = yaml.safe_load((WORKFLOWS / wf_name).read_text("utf-8"))
        on = wf.get(True) or wf.get("on")
        assert "pull_request" in on
        job = next(j for j in wf["jobs"].values() if j.get("name") == ctx)
        # A job-level `if` that can skip makes GitHub count the check as satisfied.
        cond = str(job.get("if", "")).replace(" ", "")
        assert cond in ("", "${{always()}}"), f"{ctx}: conditional job {cond!r}"


def test_no_main_pusher_relies_on_a_bypass_the_payload_lacks():
    """Refresh workflows push with GITHUB_TOKEN; the payload must bypass app 15368."""
    payload = json.loads(PAYLOAD.read_text("utf-8"))
    actors = {
        (a["actor_type"], a.get("actor_id"), a["bypass_mode"]) for a in payload["bypass_actors"]
    }
    assert ("Integration", GITHUB_ACTIONS_APP_ID, "always") in actors
    assert ("DeployKey", None, "always") in actors
    # Merging a green PR (Integration flow / owner) goes through the PR path, which
    # admin `pull_request` bypass permits even with red checks (emergency only).
    assert ("RepositoryRole", 5, "pull_request") in actors


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_dry_run_prints_call_and_diff_and_sends_nothing(tmp_path):
    live = {
        "id": 19976839,
        "name": "main-protection",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [
            {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"},
            {"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "always"},
        ],
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
    }
    listing = tmp_path / "list.json"
    listing.write_text(json.dumps([{"id": 19976839, "name": "main-protection"}]), encoding="utf-8")
    live_file = tmp_path / "live.json"
    live_file.write_text(json.dumps(live), encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for tool in ("curl", "gh"):  # any network call would hit these and fail the test
        (fakebin / tool).write_text(
            "#!/bin/sh\necho NETWORK-CALL-ATTEMPTED >&2\nexit 9\n", encoding="utf-8"
        )
        (fakebin / tool).chmod(0o755)
    env = {
        "PATH": f"{fakebin}:/usr/bin:/bin",
        "RULESETS_LIST_FILE": str(listing),
        "RULESET_LIVE_FILE": str(live_file),
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"], env=env, capture_output=True, text=True, check=False
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "NETWORK-CALL-ATTEMPTED" not in out
    assert "WOULD CALL: PUT" in out and "rulesets/19976839" in out
    assert "+ rule required_status_checks" in out
    assert "+ rule pull_request" in out
    assert "+ bypass Integration id=15368 mode=always" in out
    assert "~ " in out  # admin bypass_mode always -> pull_request shows as remove/add
    assert "- bypass RepositoryRole id=5 mode=always" in out
    assert "nothing sent" in out


def test_diff_helper_reports_identical():
    sys.path.insert(0, str(REPO / "deploy" / "github"))
    try:
        import ruleset_diff
    finally:
        sys.path.pop(0)
    payload = json.loads(PAYLOAD.read_text("utf-8"))
    live = {k: v for k, v in payload.items() if k != "_comment"}
    assert ruleset_diff.describe_diff(payload, live)[0].startswith("identical")
