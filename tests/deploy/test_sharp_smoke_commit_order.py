"""The Sharp production smoke must be able to record its own result.

CI incident 2026-08-18.  ``Verify Sharp Production Population`` failed on
every run in ~16 s with::

    error: cannot pull with rebase: You have unstaged changes.
    error: Please commit or stash them.
    ##[error]Process completed with exit code 128.

The smoke step rewrites the tracked artifact
``data/ops/sharp-production-smoke.json``, so the tree is dirty when the
commit-back step runs, and a bare ``git pull --rebase`` aborts.  The
"Enforce healthy population" gate sits AFTER that step, so it never
executed — which is verbatim the defect the step's own ``AUDIT O-4``
comment describes one line earlier, recurring.

TWO things have to hold, and the obvious fix only gets one of them:

1. the pull must tolerate a dirty tree (``--autostash``); and
2. the pull must come BEFORE the ``git add``.

(2) is the subtle one and is why this file exists.  ``--autostash`` pops
with ``git stash apply`` semantics and does **not** restore the index, so
"stage first, then pull" returns the artifact to the working tree
UNSTAGED — ``git diff --cached --quiet`` then exits 0, the step takes its
"No change in smoke result — nothing to commit" branch, and the job goes
GREEN while silently never recording the smoke result.  Verified
empirically against real git before the fix was chosen.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "verify-sharp-production.yml"

ARTIFACT = "data/ops/sharp-production-smoke.json"


RUN_SCOPED = "sharp-smoke-current.json"


def _enforce_step() -> str:
    """The RUNNABLE lines of the 'Enforce healthy population' step.

    Comments stripped for the same reason ``_commit_step`` strips them —
    this step's own comments name the tracked artifact while explaining
    why the gate must NOT read it.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("Enforce healthy population")
    return "\n".join(
        line for line in text[start:].splitlines() if not line.lstrip().startswith("#")
    )


def _commit_step() -> str:
    """The RUNNABLE lines of the 'Commit production smoke result' step.

    Comment lines are stripped, and that is load-bearing rather than
    tidiness: the step's own comments quote ``git pull --rebase`` and
    ``git add -f data/ops/...`` while explaining why the order matters,
    so a naive substring search finds the PROSE and the ordering
    assertion compares two comments to each other.  Measured — with the
    comments left in, both mutants below (stage-before-pull, and
    dropping ``--autostash``) passed.  A guard that cannot fail is
    decoration.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("Commit production smoke result")
    end = text.index("Enforce healthy population", start)
    return "\n".join(
        line for line in text[start:end].splitlines() if not line.lstrip().startswith("#")
    )


def test_the_pull_tolerates_the_dirty_tree_the_smoke_step_leaves():
    step = _commit_step()
    assert "git pull --rebase" in step, "the step no longer pulls — this guard needs rewriting"
    assert "--autostash" in step, (
        "the smoke step above rewrites a TRACKED artifact, so the tree is dirty here; "
        "a bare `git pull --rebase` exits 128 and takes the enforce gate down with it"
    )


def test_the_pull_comes_before_the_add():
    """Order, not just flags — see the module docstring."""
    step = _commit_step()
    pull_at = step.index("git pull --rebase")
    add_at = step.index(f"git add -f {ARTIFACT}")
    assert pull_at < add_at, (
        "`git add` must come AFTER the pull: autostash does not restore the index, so staging "
        "first leaves the artifact unstaged, `git diff --cached --quiet` exits 0, and the step "
        "reports 'nothing to commit' — green, with the smoke result never recorded"
    )


def test_the_artifact_is_still_force_added():
    """AUDIT O-4: it lives under the gitignored ``data/``."""
    assert f"git add -f {ARTIFACT}" in _commit_step()


def test_the_enforce_gate_still_runs_after_the_commit_step():
    """The gate is the point of the workflow; it must not be reordered away."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.index("Commit production smoke result") < text.index("Enforce healthy population")


def test_unverifiable_is_reported_as_a_warning_not_a_pass_or_a_failure():
    """``unverifiable_unauthenticated`` is insufficient evidence, not bad news.

    The workflow holds no credential for ``/api/sharp/*`` (measured: 401
    from https://chaseupside.com/api/sharp/cohort on 2026-08-18 and on
    the last recorded result, 2026-08-05).  Failing on that would fail
    every push for a credential the workflow was never given; passing
    silently would let a real outage hide.  It warns.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    gate = text[text.index("Enforce healthy population") :]
    assert 'status == "unverifiable_unauthenticated"' in gate
    assert "::warning title=Sharp smoke cannot verify::" in gate
    assert (
        "Sharp production smoke is not healthy" in gate
    ), "a status that is neither healthy nor unverifiable must still fail the gate"


def test_the_gate_grades_this_run_and_not_the_committed_record():
    """CI reliability lane, 2026-08-20.

    ``data/ops/sharp-production-smoke.json`` is a RECORD.  It is tracked,
    so it survives between runs, so a gate that reads it grades whatever
    the last run to write it observed — not what this run measured.

    That was latent while every run rewrote the file unconditionally.  It
    goes live the moment the artifact stops being rewritten on an
    unchanged state (which is what the day-quantized heartbeat does), and
    the failure it produces is the worst kind: a stale ``healthy`` passing
    a run that measured nothing, invisible in review because the diff only
    removes a write.

    So the gate reads the run-scoped copy under ``RUNNER_TEMP``, and the
    tracked path must not appear in the step at all — not as a fallback,
    not as a second read.  A fallback is the defect with an extra step.
    """
    gate = _enforce_step()
    assert RUN_SCOPED in gate, (
        "the enforce gate no longer reads this run's own result; it must read "
        f"$RUNNER_TEMP/{RUN_SCOPED}, written by the smoke step above"
    )
    assert ARTIFACT not in gate, (
        f"the enforce gate reads the tracked record {ARTIFACT!r}. That file "
        "outlives the run that wrote it, so on any run that does not rewrite it "
        "the gate grades a previous run's measurement as this one's"
    )


def test_the_smoke_step_writes_the_run_scoped_result_the_gate_reads():
    """The two halves must agree, or the gate crashes on a missing file.

    Named explicitly because the smoke step and the gate are ~50 lines
    apart in the same file and nothing else couples them.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    smoke = text[
        text.index("Wait for deploy and Sharp population") : text.index(
            "Commit production smoke result"
        )
    ]
    smoke = "\n".join(line for line in smoke.splitlines() if not line.lstrip().startswith("#"))
    assert (
        RUN_SCOPED in smoke
    ), "the smoke step does not write the run-scoped result the enforce gate reads"
    assert 'os.environ["RUNNER_TEMP"]' in smoke, (
        "RUNNER_TEMP must be indexed, not defaulted: a fallback to the working "
        "directory would let the gate grade a file the runner never scoped to "
        "this run, which is the failure this pair exists to prevent"
    )


def test_the_record_is_written_only_when_it_has_something_new_to_say():
    """CI reliability lane, 2026-08-20 — the churn.

    ``checkedAt`` is a timestamp, so an unconditional rewrite of the
    tracked artifact commits on every run whether or not anything moved.
    Measured: **42 of 66 bot commits to main in 24 hours**, all recording
    the same ``unverifiable_unauthenticated``.  Each one moves ``main``
    under every open PR, which the repository's own HEAD FREEZE policy
    classifies as class-C drift and spends real effort bounding.

    The write decision lives in ``scripts/sharp_smoke_record.py`` so it
    can be unit-tested (``tests/ops/test_sharp_smoke_record.py``).  What
    this guard pins is the WIRING: that the workflow actually asks.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    smoke = text[
        text.index("Wait for deploy and Sharp population") : text.index(
            "Commit production smoke result"
        )
    ]
    smoke = "\n".join(line for line in smoke.splitlines() if not line.lstrip().startswith("#"))

    assert "sharp_smoke_record" in smoke, (
        "the smoke step no longer consults the record owner; an unconditional "
        "rewrite of the tracked artifact commits on every run because checkedAt "
        "always changes"
    )
    assert "decide_write" in smoke, (
        "the tracked record is written without asking whether it has anything new "
        "to say — that is the 42-commits-a-day defect"
    )

    write = smoke.index("output.write_text")
    decide = smoke.index("decide_write")
    assert decide < write, (
        "output.write_text runs before (or without) the decide_write check, so the "
        "condition does not gate the write it exists to gate"
    )


def test_every_run_still_reports_even_when_it_leaves_no_commit():
    """A quiet run must not be an invisible run.

    Once the tracked record stops being rewritten on an unchanged state,
    git history is no longer per-run evidence.  The job summary becomes
    the heartbeat, and it lives in the run ledger where a stale file
    cannot fake it — so it must be written unconditionally, outside the
    decide_write branch.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    smoke = text[
        text.index("Wait for deploy and Sharp population") : text.index(
            "Commit production smoke result"
        )
    ]
    lines = [line for line in smoke.splitlines() if not line.lstrip().startswith("#")]
    summary_lines = [index for index, line in enumerate(lines) if "GITHUB_STEP_SUMMARY" in line]
    assert summary_lines, "the smoke step no longer writes a per-run job summary"

    decide_line = next(index for index, line in enumerate(lines) if "decide_write" in line)
    decide_indent = len(lines[decide_line]) - len(lines[decide_line].lstrip())
    for index in summary_lines:
        indent = len(lines[index]) - len(lines[index].lstrip())
        assert index > decide_line and indent <= decide_indent, (
            "the job summary is written inside the decide_write branch, so a run "
            "that changes nothing would leave neither a commit nor a summary — "
            "invisible, which is how a workflow that stopped firing goes unnoticed"
        )


def _workflow_steps() -> dict:
    """Step name -> runnable script, for the whole workflow."""
    import yaml

    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = {}
    for step in document["jobs"]["verify"]["steps"]:
        if isinstance(step.get("run"), str):
            steps[str(step.get("name", "<unnamed>"))] = step
    return steps


def test_a_gate_that_can_never_measure_is_tracked_rather_than_only_warned():
    """CI reliability lane, 2026-08-20.

    The per-run disposition above is right and is not changed here: a
    ``::warning`` with ``exit 0``, because failing ~12x a day for a
    credential CI was never issued is how a gate gets deleted.

    But the CUMULATIVE fact is different from any single run's. This
    workflow has shown a green tick through every run in its recorded
    history while measuring nothing at all. Each run was honest; the
    series is a false green. "Loud once per run into a log nobody reads"
    does not discharge it.

    So the finding goes where this repository already puts findings CI
    cannot act on itself — a tracking issue that names the single action
    that would turn this into a real gate, and that drains itself the day
    that action is taken.
    """
    steps = _workflow_steps()
    tracker = next(
        (script for name, script in steps.items() if "Track that the Sharp gate" in name),
        None,
    )
    assert tracker is not None, (
        "the unmeasurable-gate tracker step is gone. Without it the only record "
        "that this gate has never measured anything is a per-run warning, and the "
        "workflow's green tick is the only thing anybody sees"
    )
    body = tracker["run"]
    assert "gh label create sharp-unverifiable" in body, (
        "the tracker's label is not created idempotently — the same defect that "
        "left the calibration trackers unable to find their own issues"
    )
    assert "_SELF_AUTHED_API_EXACT" in body, (
        "the tracker no longer names the action that fixes this. An alert that does "
        "not say what to do is noise"
    )


def test_the_tracker_identifies_its_issue_without_betting_on_a_login_spelling():
    """AUDIT F-23, third appearance — and this time the bet is not re-placed.

    The retired form of this guard pinned an author clause that normalised a
    ``[bot]`` SUFFIX away, on the theory that ``gh`` reports the login as
    ``github-actions`` via GraphQL and ``github-actions[bot]`` via REST.  Both
    of those spellings do in fact work.  The one that does NOT is
    ``app/github-actions`` -- the ``app/`` prefix ``gh`` puts on bot actors in
    ``--json author`` output -- and that is what production did: #951, #953,
    #955, #957, one new issue per run (issue #958).

    Two guesses at a spelling have now failed.  The invariant is therefore that
    the step does not depend on the spelling AT ALL: identity is the
    workflow-owned LABEL plus the exact TITLE.  ``test_sharp_tracker_dedup.py``
    proves the behaviour by executing this shell against real ``jq`` for all
    three spellings; this guard pins the structure so it cannot quietly regrow
    an author clause.
    """
    steps = _workflow_steps()
    seen = 0
    for name, step in steps.items():
        if "Sharp gate cannot measure" not in name and "unmeasurable-gate" not in name:
            continue
        seen += 1
        script = step["run"]
        assert "gh issue list" in script, f"{name}: no lookup, so it cannot dedup"
        # Backslashes removed: the jq filter reaches the shell escaped, so a
        # needle written against the readable form silently matches nothing.
        # That is how a guard ends up asserting a step it never examined.
        unescaped = script.replace("\\", "")
        assert ".title==" in script, (
            f"{name}: identifies its tracker by label alone. A human can apply a "
            "plain label to a hand-written issue, and this step would then comment "
            "on -- or close -- their bug report"
        )
        assert "select(.author" not in unescaped and ".author.login ==" not in unescaped, (
            f"{name}: the lookup branches on the author login again. Two spellings "
            "have already been guessed wrong (F-23, then issue #958); the login is "
            "fetched for the record but must not decide identity"
        )
    assert seen == 2, (
        f"expected both tracker steps, examined {seen} -- a renamed step would "
        "make this guard vacuous"
    )


def test_the_open_tracker_step_prefers_the_oldest_duplicate():
    """``gh`` sorts newest-first, so ``.[0]`` picks whichever duplicate was filed
    LAST.  That is the mechanism that let #753 displace the real tracker #732 in
    e2e.yml, and with four live duplicates it would keep hopping between them."""
    steps = _workflow_steps()
    opener = next(
        (step for name, step in steps.items() if "Sharp gate cannot measure" in name),
        None,
    )
    assert opener is not None, "the tracker-open step is gone"
    script = opener["run"]
    assert "min" in script, (
        "the open step no longer selects the OLDEST matching tracker, so a run "
        "can comment on a newer duplicate and leave the canonical one orphaned"
    )
    assert ".[0].number" not in script.replace(
        "\\", ""
    ), "`.[0]` off gh's newest-first sort is the F-23 displacement bug"


def test_the_tracker_drains_itself_when_the_gate_can_measure_again():
    """Otherwise the issue outlives the condition and becomes noise."""
    steps = _workflow_steps()
    closer = next(
        (step for name, step in steps.items() if "unmeasurable-gate tracker" in name),
        None,
    )
    assert closer is not None, (
        "nothing closes the unmeasurable-gate tracker. The day a token is "
        "provisioned the issue would sit open forever, and a tracker that never "
        "drains teaches people to ignore trackers"
    )
    assert "gh issue close" in closer["run"]
    condition = str(closer.get("if", ""))
    assert "measured" in condition, (
        "the closer does not gate on whether this run actually MEASURED "
        "production. Closing on anything weaker would retire the issue on a run "
        "that saw nothing"
    )
