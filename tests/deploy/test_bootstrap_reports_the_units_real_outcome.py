"""Bootstrap Sharp Records must report what the unit actually did.

CI reliability lane, 2026-08-20.  **This guard changes no behaviour.**
It exists to make one specific false-green conversion impossible, because
that conversion is the obvious-looking fix for a workflow that is red
0-for-19 and it would be a disaster.

THE STANDING FAILURE, AND WHY IT IS CORRECT
===========================================
``Bootstrap Sharp Records`` has failed on every one of its last 19
concluded runs (latest ``32333756888`` @ ``72835abf``).  On production,
``*-ffpc-sharp.service`` is ``Type=oneshot`` with
``TimeoutStartSec=1800``; ``run_oneshot`` calls a BLOCKING
``systemctl start``, the unit burns ~29 min 53 s of CPU, systemd
``SIGTERM``s it at the 30-minute mark, and the workflow exits 1.  The
2026-08-18 incident record traced this to a runaway collector on the box
and ruled the workflow "correctly reporting a real failure — it must not
be retired, silenced, or made non-fatal."

THE TEMPTING FIX, AND WHY IT IS FORBIDDEN
=========================================
``systemctl start --no-block`` returns 0 when the job is **enqueued**,
not when it succeeds.  The unit would still burn the same CPU and still
be killed at the same timeout — the only thing that would change is that
this workflow goes 19/19 GREEN with the production incident intact and
now invisible.  That is an unconditional-success path.

It is an easy mistake to make in good faith, because ``--no-block`` IS
the right call two files over: ``deploy/install-systemd-service.sh`` uses
it for these same units, pinned by
``tests/deploy/test_sharp_population_jobs.py``.  The difference is what
the caller is claiming.  A deploy kicks a collector and does not assert
it finished.  This workflow's entire output IS the assertion that it
finished.  ``--no-block`` there is correct and here is a lie.

WHAT THIS PINS
==============
The invariant, not the implementation: whatever ``run_oneshot`` does, the
script's exit status must still depend on the unit REACHING A TERMINAL
STATE.  A blocking ``start`` satisfies that.  So would ``--no-block``
followed by a completion poll.  ``--no-block`` alone does not, and that
is the only thing forbidden here — the owner's real fix for the runaway
collector is left completely open.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "bootstrap-sharp-records.sh"

#: Evidence that the script waits for a terminal state rather than for
#: the job to be queued.  Any one of these is enough.
_COMPLETION_EVIDENCE = (
    "--wait",
    "is-active",
    "is-failed",
    "show -p Result",
    "show --property=Result",
)


def _run_oneshot_body() -> str:
    """``run_oneshot``'s runnable lines.

    Comments are stripped for the reason
    ``test_sharp_smoke_commit_order.py`` records: this file's own prose
    quotes ``--no-block`` while explaining why it must not appear, and a
    naive substring search would find the explanation.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("run_oneshot() {")
    end = text.index("\n}", start)
    return "\n".join(
        line for line in text[start:end].splitlines() if not line.lstrip().startswith("#")
    )


def test_the_bootstrap_script_still_has_the_oneshot_runner():
    """Non-vacuity: everything below is silent if this helper is renamed."""
    assert SCRIPT.exists(), "deploy/bootstrap-sharp-records.sh is gone"
    assert "run_oneshot() {" in SCRIPT.read_text(encoding="utf-8"), (
        "run_oneshot has been renamed or removed — this guard is now vacuous "
        "and must be re-pointed at whatever starts the sharp units"
    )


def test_the_units_completion_and_not_its_enqueueing_decides_the_exit_status():
    body = _run_oneshot_body()

    # The script invokes systemctl through ``"${SYSTEMCTL_BIN}"``, not by
    # a bare name, so match either spelling.  Getting this wrong makes the
    # guard fail on correct code — which it did, on the first run.
    starts = [
        line
        for line in body.splitlines()
        if re.search(r"(systemctl|SYSTEMCTL_BIN)", line)
        and re.search(r"\bstart\b", line)
        and "reset-failed" not in line
    ]
    assert starts, (
        "run_oneshot no longer starts a unit — either it was refactored or this "
        "guard's command matching is wrong; re-point it rather than deleting it"
    )

    non_blocking = [line for line in starts if "--no-block" in line]
    if not non_blocking:
        # Blocking start: the exit status already depends on completion.
        return

    waits = any(marker in body for marker in _COMPLETION_EVIDENCE)
    assert waits, (
        "run_oneshot starts the unit with --no-block and never waits for it to "
        "reach a terminal state:\n  "
        + "\n  ".join(non_blocking)
        + "\n\n`systemctl start --no-block` returns 0 when the job is ENQUEUED. "
        "The unit would still burn ~30 CPU-minutes and still be SIGTERMed at "
        "TimeoutStartSec=1800 -- the only change is that Bootstrap Sharp Records "
        "goes green with the production incident intact and now invisible. That "
        "is an unconditional-success path, and the 2026-08-18 incident record "
        "ruled this workflow 'must not be retired, silenced, or made non-fatal'. "
        "If --no-block is genuinely wanted, follow it with a completion poll "
        "(--wait, or is-active/is-failed until terminal)."
    )


def test_a_failed_unit_still_returns_non_zero():
    """The other half: waiting is useless if the result is discarded."""
    body = _run_oneshot_body()
    assert "is-failed" in body, (
        "run_oneshot no longer inspects whether the unit entered a failed state; "
        "a oneshot can exit non-zero without `systemctl start` saying so"
    )
    assert re.search(r"(^|\s)return 1(\s|$)", body, re.MULTILINE), (
        "run_oneshot no longer returns non-zero on failure, so the SSH step's "
        "exit code -- which is the workflow's entire signal -- would be 0 "
        "whatever the unit did"
    )
