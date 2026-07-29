"""Tripwire on the legacy rank-form Hill constants.

2026-07-29 audit, curve-governance follow-up.

WHY A TRIPWIRE AND NOT A REGISTRY MODEL
=======================================
The audit flagged these four constants as a governance gap: they sit
outside ``src/model_registry``, they are refit by a different script than
the percentile scope masters, and they have no out-of-sample gate.  The
proposed fix was to bring them under the model registry.

That proposal was WRONG, and this test is what replaced it.  The model
registry exists to gate AUTOMATED promotion — the percentile masters are
refit weekly by ``.github/workflows/refit-hill-curves.yml``, which is
why they need a challenger/champion flow.  These four are different:

  * ``scripts/fit_hill_curve_from_market.py`` is READ-ONLY.  It opens
    CSVs, grid-searches, and prints.  It contains no write of any kind.
  * Nothing runs it — not a workflow, not a systemd timer, not a
    Makefile target.  Verified by repo-wide grep: every reference is a
    docstring or a test.
  * Its own docstring says "Use the output to update
    ``player_valuation.py`` constants", i.e. a human edits them.

So there is no automated promotion to gate, and wrapping a
human-edited, manually-refit pair in challenger/champion machinery would
have been ceremony with no benefit.

WHAT THE ACTUAL RESIDUAL RISK IS
================================
That someone edits these constants and does not re-check whether the
curve still reproduces the board.  The two families drift independently,
and the drift is silent — nothing fails when the rank-form curve stops
matching the percentile-derived board.

This test makes that edit LOUD.  It pins the values, so any change fails
here and the failure message points at the drift check.  It is
deliberately a dumb equality assertion: the other tests in
``test_rank_to_value_scope.py`` import these constants symbolically (so
a legitimate refit does not break them), which is right for them and
exactly why none of them notices an edit.
"""

from __future__ import annotations

from src.canonical.player_valuation import (
    HILL_MIDPOINT,
    HILL_SLOPE,
    IDP_HILL_MIDPOINT,
    IDP_HILL_SLOPE,
)

# The values live in ``src/canonical/player_valuation.py``.  Measured
# fit against the live board on 2026-07-29
# (``scripts/backtest_legacy_rank_curve.py``): the offense pair scores
# RMSE 845.9 on offense rows, the IDP pair RMSE 78.7 on IDP rows, and a
# curve refit to that board would score 96.3 overall.  Those numbers are
# the context for any change here.
_PINNED = {
    "HILL_MIDPOINT": 48.44,
    "HILL_SLOPE": 1.149,
    "IDP_HILL_MIDPOINT": 69.50,
    "IDP_HILL_SLOPE": 0.945,
}

_GUIDANCE = """
The legacy rank-form Hill constants changed.

If that was DELIBERATE, do these two things and then update _PINNED in
this file:

  1. Re-run the drift check, which is the whole reason this tripwire
     exists:
         python scripts/backtest_legacy_rank_curve.py \\
             --out docs/measurements/<dated>.json
     Compare against docs/legacy-rank-curve-backtest.md.  These
     constants feed RECONSTRUCTION paths (terminal.py's value fallback
     and rank_history.py's historical backfill), so a change moves
     user-visible history values.

  2. Record the decision in docs/legacy-rank-curve-backtest.md, which
     carries the open question of whether this whole rank-form family
     should be retired in favour of the registry-managed percentile
     masters.

If it was NOT deliberate: revert it.  Nothing automated writes these —
``scripts/fit_hill_curve_from_market.py`` only prints — so an unexplained
change here is a hand edit.
"""


def test_rank_form_constants_are_unchanged():
    actual = {
        "HILL_MIDPOINT": HILL_MIDPOINT,
        "HILL_SLOPE": HILL_SLOPE,
        "IDP_HILL_MIDPOINT": IDP_HILL_MIDPOINT,
        "IDP_HILL_SLOPE": IDP_HILL_SLOPE,
    }
    drifted = {k: (v, actual[k]) for k, v in _PINNED.items() if actual[k] != v}
    assert not drifted, f"{_GUIDANCE}\nChanged (pinned -> actual): " + ", ".join(
        f"{k}: {was} -> {now}" for k, (was, now) in sorted(drifted.items())
    )


def test_the_refit_script_still_does_not_write():
    """The premise this test's design rests on.

    If ``fit_hill_curve_from_market.py`` ever gains the ability to write
    constants, it becomes an automated promotion path — and then it DOES
    need the registry gate, and the reasoning in this module's docstring
    has to be revisited rather than silently outgrown.
    """
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "fit_hill_curve_from_market.py"
    text = script.read_text()
    # Reading CSVs is expected; writing is not.
    for forbidden in ("write_text(", "write_committed_constants", ".writelines(", "json.dump("):
        assert forbidden not in text, (
            f"{script.name} now contains {forbidden!r} — it may write constants. "
            "This tripwire assumes it is print-only; see the module docstring."
        )
