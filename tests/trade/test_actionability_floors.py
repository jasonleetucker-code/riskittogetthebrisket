"""The actionability floors, and which of them actually do anything.

WHY THIS EXISTS
===============
Three constants read like the gate that keeps roster clog out of trade
and waiver advice. Measured against the board they filter (pinned
2026-07-30 contract, 812 priced rows, structural floor **757**):

    constant                value   removes
    MIN_RELEVANT_VALUE        500     0 of 812
    MIN_WAIVER_VALUE          500     0 of 812
    MIN_ACTIONABLE_VALUE    2,000   477 of 812   <-- doing real work

The first two are class 4 of this audit — a threshold whose population
sits entirely on one side of it. ``MIN_RELEVANT_VALUE`` is inert twice
over: every one of its 14 call sites runs AFTER
``BOARD_TOP_N_FILTER`` (150), and the 150th row is worth **3,217**.
The gate its name describes is really enforced by the top-N filter.

``MIN_ACTIONABLE_VALUE`` was raised as the same finding and is
**REFUTED** — it binds hard, on more than half the board. It is pinned
here so the next audit does not re-raise it.

WHAT THIS ASSERTS, AND WHY NOT "IT REMOVES NOTHING"
===================================================
Pinning inertness would be the wrong guard: it goes red when someone
legitimately fixes the thing, and the cheap way back to green is to
re-break it. That is the green-by-construction habit ADR-008
(``docs/roster-trade-intelligence/DECISIONS.md``) exists to stop.

So this pins the two facts a future editor actually needs:

1. **The dominance relationship.** ``MIN_RELEVANT_VALUE`` sits below
   the board floor, which sits below the top-N cut. State that and the
   reader knows which knob is the gate.
2. **That the dial is not free.** The tempting edit — "it does nothing,
   so raising it is harmless" — is wrong: 900 removes 31 rows, 1,200
   removes 124, 1,500 removes 292. A change here has a blast radius its
   current inertness completely hides.

Both are asserted against a distribution built to mirror the live
board, so the numbers in the failure messages are the ones an editor
would actually see.

NOT ``livedata``-marked: pure arithmetic over a synthetic distribution,
must block.
"""

from __future__ import annotations

import unittest

from src.trade.suggestions import (
    BOARD_TOP_N_FILTER,
    MIN_ACTIONABLE_VALUE,
    MIN_RELEVANT_VALUE,
)
from src.trade.waiver import MIN_WAIVER_VALUE

# The live board's shape, measured on the pinned 2026-07-30 contract.
# Quantiles rather than the full 812 rows: enough to reproduce every
# claim above without carrying a fixture that rots.
BOARD_FLOOR = 757
BOARD_P01 = 875
BOARD_P05 = 934
BOARD_MEDIAN = 1785
BOARD_TOP_N_CUT = 3217  # value of the 150th row
PRICED_ROWS = 812

# (threshold, rows it would remove) — measured, not modelled.
REMOVAL_CURVE = {
    500: 0,
    800: 1,
    900: 31,
    1000: 51,
    1200: 124,
    1500: 292,
    2000: 477,
}


class TestTheMeasurementsAreSelfConsistent(unittest.TestCase):
    """Non-vacuity: the constants below are compared against these
    numbers, so the numbers must at least describe a coherent board."""

    def test_the_quantiles_are_ordered(self) -> None:
        self.assertLess(BOARD_FLOOR, BOARD_P01)
        self.assertLess(BOARD_P01, BOARD_P05)
        self.assertLess(BOARD_P05, BOARD_MEDIAN)
        self.assertLess(BOARD_MEDIAN, BOARD_TOP_N_CUT)

    def test_the_removal_curve_is_monotonic(self) -> None:
        thresholds = sorted(REMOVAL_CURVE)
        removals = [REMOVAL_CURVE[t] for t in thresholds]
        self.assertEqual(removals, sorted(removals))
        self.assertLess(removals[-1], PRICED_ROWS)


class TestWhichGateIsTheRealOne(unittest.TestCase):
    def test_min_relevant_value_sits_below_the_board_floor(self) -> None:
        self.assertLess(
            MIN_RELEVANT_VALUE,
            BOARD_FLOOR,
            msg=(
                f"MIN_RELEVANT_VALUE is now {MIN_RELEVANT_VALUE}, at or above the "
                f"board's structural floor of {BOARD_FLOOR}. That is a real change "
                f"in behaviour, not a no-op: it starts removing players from every "
                f"one of its 14 call sites. If that is intended, re-measure against "
                f"the current board and update this test with the new numbers "
                f"rather than relaxing the assertion."
            ),
        )

    def test_min_waiver_value_sits_below_the_board_floor(self) -> None:
        self.assertLess(MIN_WAIVER_VALUE, BOARD_FLOOR, msg="see the message above")

    def test_the_top_n_filter_is_the_operative_gate_for_suggestions(self) -> None:
        """The claim the docstring makes, asserted rather than asserted
        in prose: the top-N cut is an order of magnitude stricter."""
        self.assertGreater(
            BOARD_TOP_N_CUT,
            MIN_RELEVANT_VALUE * 6,
            msg=(
                f"the {BOARD_TOP_N_FILTER}th row is worth {BOARD_TOP_N_CUT}, which no "
                f"longer dominates MIN_RELEVANT_VALUE ({MIN_RELEVANT_VALUE}) by the "
                f"margin this module documents. Re-measure before trusting either."
            ),
        )


class TestTheDialIsNotFree(unittest.TestCase):
    """The trap: 'it removes nothing, so raising it is harmless.'"""

    def test_small_increases_remove_real_players(self) -> None:
        self.assertEqual(REMOVAL_CURVE[500], 0)
        self.assertGreater(REMOVAL_CURVE[900], 25)
        self.assertGreater(REMOVAL_CURVE[1500], PRICED_ROWS * 0.30)

    def test_the_inert_range_is_narrow(self) -> None:
        """Only ~250 points of headroom before the floor starts biting —
        the constant is inert by a thin margin, not a comfortable one."""
        headroom = BOARD_FLOOR - MIN_RELEVANT_VALUE
        self.assertLess(headroom, 300)


class TestMinActionableValueIsRefuted(unittest.TestCase):
    """Recorded so the next audit does not re-raise it as dead."""

    def test_it_binds_on_more_than_half_the_board(self) -> None:
        self.assertEqual(MIN_ACTIONABLE_VALUE, 2000)
        removed = REMOVAL_CURVE[MIN_ACTIONABLE_VALUE]
        self.assertGreater(
            removed / PRICED_ROWS,
            0.5,
            msg=(
                f"MIN_ACTIONABLE_VALUE removes {removed} of {PRICED_ROWS} rows "
                f"({removed / PRICED_ROWS:.1%}). It was raised as a dead threshold "
                "alongside MIN_RELEVANT_VALUE and refuted by measurement — it is "
                "the one that works. Do not 'fix' it."
            ),
        )

    def test_it_is_the_only_one_of_the_three_that_binds(self) -> None:
        binding = {
            name: REMOVAL_CURVE.get(value, 0)
            for name, value in (
                ("MIN_RELEVANT_VALUE", MIN_RELEVANT_VALUE),
                ("MIN_WAIVER_VALUE", MIN_WAIVER_VALUE),
                ("MIN_ACTIONABLE_VALUE", MIN_ACTIONABLE_VALUE),
            )
        }
        self.assertEqual(
            {k for k, v in binding.items() if v > 0},
            {"MIN_ACTIONABLE_VALUE"},
            msg=f"removal counts: {binding}",
        )


class TestTheApiDefaultTracksTheConstant(unittest.TestCase):
    """``server.py`` typed ``500`` twice instead of importing
    ``MIN_WAIVER_VALUE``, so changing the engine default would have left
    the API's default behind — a mirrored constant, one hop away from
    the one it mirrors."""

    def test_the_waiver_endpoint_does_not_hardcode_the_floor(self) -> None:
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2] / "server.py").read_text(encoding="utf-8")
        start = src.index("/api/waiver/suggestions")
        window = src[start : start + 4000]
        self.assertIn("MIN_WAIVER_VALUE", window)
        self.assertNotIn(
            'body.get("minValue", 500)',
            window,
            msg=(
                "the waiver endpoint re-types the floor instead of importing "
                "MIN_WAIVER_VALUE. Changing the constant would move the engine "
                "default and leave the API default behind it."
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
