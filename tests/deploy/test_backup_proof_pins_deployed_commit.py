"""The retention backup proof must run the proof script of the DEPLOYED commit.

A ``workflow_run`` checkout lands on the default branch's current HEAD, which
is routinely newer than what the box runs.  Run 36970578552 (2026-10-02)
FAILED nine AL-P2 artifacts because a newer proof script asserted stores the
deployed writer did not produce yet; the next run on matching code proved them
intact.  Skew can just as easily fake a pass, so the workflow reads the proof
script from the box's own HEAD.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "retention-backup-proof.yml"


def _steps() -> list[dict]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc["jobs"]["prove"]["steps"]


def _step(name: str) -> dict:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} missing")


def test_checkout_has_full_history_for_the_deployed_commit() -> None:
    assert _step("Checkout")["with"]["fetch-depth"] == 0


def test_proof_script_is_read_from_the_box_head() -> None:
    pin = _step("Pin the proof script to the deployed commit")["run"]
    assert "rev-parse HEAD" in pin
    assert "^[0-9a-f]{40}$" in pin
    assert 'git cat-file -e "${box_sha}^{commit}"' in pin
    assert "${box_sha}:deploy/diagnostics/retention_backup_restore_proof.sh" in pin
    assert "PROOF_SCRIPT=" in pin


def test_pin_runs_before_the_proof_and_the_proof_uses_it() -> None:
    names = [s.get("name") for s in _steps()]
    assert names.index("Pin the proof script to the deployed commit") < names.index(
        "Run backup and prove restore on production"
    )
    run = _step("Run backup and prove restore on production")["run"]
    assert '< "$PROOF_SCRIPT"' in run
    assert "< deploy/diagnostics/retention_backup_restore_proof.sh" not in run
