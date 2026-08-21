"""The Sharp smoke must not call a SUPERSEDED deploy a FAILED one.

`verify-sharp-production.yml` classified the triggering deploy with a bare
``deploy_conclusion != "success"``, which collapses four distinct outcomes
into ``deploy_failed``.  The one it got most wrong is ``cancelled``.

``cancelled`` is the NORMAL outcome when the deploy concurrency group
supersedes a run — it happens on every merge that lands while an earlier
deploy is still running, and the superseding deploy usually succeeds
moments later.  So the durable record was asserting a production FAILURE
about deploys that shipped fine, and the alternating fingerprint that
produced looked like smoke-commit churn while actually being a
misclassification upstream of the writer.

Absence of a deploy is absence of evidence.  It is neither health nor
failure, and the record must not claim either.

These tests execute the workflow's OWN classifier, extracted from the
YAML at run time, so they cannot drift from the shipped logic the way a
transcribed copy would.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "verify-sharp-production.yml"
)


def _gate_script() -> str:
    """The `Verify` step's inline python, straight out of the shipped YAML."""
    doc = yaml.safe_load(WORKFLOW.read_text())
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run") or ""
            if "deployConclusion" in run and "deploy_failed" in run:
                return run
    raise AssertionError("could not find the gate step in the workflow")


def classify(event_name: str, deploy_conclusion: str) -> str:
    """Run the workflow's real branch ladder over one (event, conclusion)."""
    script = _gate_script()
    # Take the classifier block verbatim: from the first branch through the
    # line before the `else:` that starts the polling loop.
    start = script.index('if event_name == "workflow_run"')
    end = script.index("\nelse:", start)
    block = script[start:end]
    ns = {
        "event_name": event_name,
        "deploy_conclusion": deploy_conclusion,
        "result": {"status": "waiting"},
    }
    exec(compile(block, "<gate>", "exec"), ns)  # noqa: S102 — the shipped logic is the subject
    return ns["result"]["status"]


def test_the_classifier_block_was_actually_found_and_is_not_empty():
    """Vacuity guard: an empty block would make every assertion below pass."""
    script = _gate_script()
    start = script.index('if event_name == "workflow_run"')
    end = script.index("\nelse:", start)
    assert script[start:end].count('result["status"]') >= 3


def test_a_cancelled_deploy_is_superseded_not_failed():
    """THE REGRESSION TEST. Reintroducing `!= success` for cancelled REDs here."""
    assert classify("workflow_run", "cancelled") == "deploy_superseded"


@pytest.mark.parametrize("conclusion", ["skipped", "", "pending"])
def test_an_absent_deploy_conclusion_is_unmeasured_not_failed(conclusion):
    assert classify("workflow_run", conclusion) == "deploy_unmeasured"


def test_a_real_failure_keeps_its_teeth():
    """The repair must not weaken genuine failures."""
    assert classify("workflow_run", "failure") == "deploy_failed"
    assert classify("workflow_run", "timed_out") == "deploy_failed"


def test_a_successful_deploy_proceeds_to_normal_verification():
    """`waiting` means the polling loop runs — a real production check."""
    assert classify("workflow_run", "success") == "waiting"


def test_a_push_triggered_smoke_is_never_classified_off_a_deploy():
    """Push-triggered runs start alongside the deploy and own no conclusion."""
    for conclusion in ("cancelled", "failure", "skipped", "success"):
        assert classify("push", conclusion) == "waiting"


def test_the_two_no_verdict_statuses_are_handled_downstream():
    """A status the gate cannot render would exit non-zero on a non-failure."""
    script = WORKFLOW.read_text()
    for status in ("deploy_superseded", "deploy_unmeasured"):
        assert f'status == "{status}"' in script, (
            f"{status} is produced but never handled — it would fall through "
            "to the generic 'not healthy' exit and re-create the defect"
        )


def test_the_smoke_writer_was_not_throttled_and_the_fingerprint_not_widened():
    """The repair is the CLASSIFIER only, per the finding's own scope.

    Note the first draft of this test matched the bare word "sleep" and hit
    the comment "background Sleeper/FFPC collection" — a false positive in
    the test, not a throttle in the workflow.  It now looks for an actual
    ``time.sleep(`` call ahead of the polling loop, which is what a throttle
    would be.
    """
    script = _gate_script()
    before_loop = script.split("for attempt")[0]
    assert "time.sleep(" not in before_loop, "a throttle was added to the writer"
    assert "stateFingerprint" not in before_loop, "the fingerprint was widened"
