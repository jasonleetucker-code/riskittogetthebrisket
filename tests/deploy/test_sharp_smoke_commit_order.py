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
