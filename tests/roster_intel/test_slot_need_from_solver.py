""""Is a slot empty" has one answer: the solver's own assignment.

Audit W20-F011.  The need test was
``PositionMarginal.entered_lineup < required[pos]`` — a count of players
whose BASE position is ``pos`` who entered ANY slot, compared against a
count of DEDICATED slots for ``pos``.  Those are different quantities
the moment slot eligibility is multi-position, which is every IDP
league: a hybrid classified LB filling a DL slot makes DL's entered
count 2 against 3 required with no slot empty at all.

Measured on the live board: five teams were told "only 2 of 3 dedicated
DL/LB slots filled" while the same payload reported ``filledSlots`` 21
of 21, and four of those rows simultaneously reported a non-zero
``tradeableSurplus`` at the position they called an urgent need.

``solve_summary`` already returns ``slot_assignment`` — the per-slot
answer.  It just was not read.
"""

from __future__ import annotations

import unittest

from src.roster_intel.marginal import solve_summary
from src.roster_intel.profiles import build_position_profiles
from src.ros.lineup import RosterPlayer


def _p(pid: str, position: str, value: float, eligible: tuple[str, ...] | None = None):
    return RosterPlayer(
        player_id=pid,
        canonical_name=pid,
        position=position,
        ros_value=value,
        fantasy_positions=tuple(eligible or (position,)),
    )


# Three dedicated DL slots, three LB, one QB. The roster carries two
# base-DL and four base-LB, and two of the LBs are DL-eligible — the
# exact shape that produced the false alarm.
SLOTS = ["QB", "DL", "DL", "DL", "LB", "LB", "LB"]
POOL = [
    _p("qb1", "QB", 90.0),
    _p("dl1", "DL", 70.0),
    _p("dl2", "DL", 68.0),
    _p("lb1", "LB", 66.0, ("LB", "DL")),
    _p("lb2", "LB", 64.0, ("LB", "DL")),
    _p("lb3", "LB", 62.0),
    _p("lb4", "LB", 60.0),
]


class SlotNeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = build_position_profiles(POOL, SLOTS)
        self.solution = solve_summary(POOL, SLOTS)

    def test_the_fixture_actually_fills_every_dedicated_slot(self) -> None:
        """Guard the premise: without this the test proves nothing."""
        self.assertEqual(self.solution.filled_slots, 7)
        self.assertEqual(self.profile.filled_slots, 7)

    def test_a_hybrid_covering_a_slot_is_not_an_unfilled_slot(self) -> None:
        dl = self.profile.positions["DL"]
        # Only two base-DL players entered — the old test's number.
        self.assertEqual(dl.entered_lineup, 2)
        self.assertEqual(dl.required_slots, 3)
        # ...but all three DL slots are filled, so there is no gap.
        self.assertEqual(dl.filled_slots, 3)
        self.assertNotIn(
            "only 2 of 3 dedicated DL slots filled",
            dl.need_reasons,
            "the need reason is still counting base positions, not slots",
        )

    def test_no_position_claims_an_unfilled_slot_when_the_lineup_is_full(self) -> None:
        """The invariant the live payload violated on five of twelve teams."""
        self.assertEqual(self.profile.filled_slots, self.profile.total_slots)
        offenders = [
            (pos, prof.need_reasons)
            for pos, prof in self.profile.positions.items()
            if any("slots filled" in r for r in prof.need_reasons)
        ]
        self.assertEqual(offenders, [])

    def test_a_genuinely_empty_slot_still_reports(self) -> None:
        """The check must still fire when a slot really goes unfilled."""
        thin = [p for p in POOL if p.player_id not in {"lb1", "lb2", "lb3", "lb4"}]
        profile = build_position_profiles(thin, SLOTS)
        lb = profile.positions.get("LB")
        self.assertIsNotNone(lb)
        self.assertEqual(lb.filled_slots, 0)
        self.assertEqual(lb.required_slots, 3)
        self.assertTrue(lb.urgent_need)
        self.assertIn("no LB rostered", lb.need_reasons)
        dl = profile.positions["DL"]
        self.assertEqual(dl.filled_slots, 2)
        self.assertIn("only 2 of 3 dedicated DL slots filled", dl.need_reasons)

    def test_both_quantities_are_emitted_so_they_cannot_be_confused(self) -> None:
        payload = self.profile.positions["DL"].to_dict()
        self.assertEqual(payload["enteredLineup"], 2)
        self.assertEqual(payload["filledSlots"], 3)
        self.assertEqual(payload["requiredSlots"], 3)


class FlexSlotsAreNotAttributedTests(unittest.TestCase):
    """Flex slots stay out of BOTH sides of the comparison.

    ``_required_slots`` excludes them because who fills them is
    endogenous; the filled-slot count has to exclude them on the same
    rule, or a QB taking SUPER_FLEX would read as a second filled QB
    slot against a required count of one.
    """

    def test_a_flex_fill_does_not_inflate_a_dedicated_count(self) -> None:
        slots = ["QB", "SUPER_FLEX", "RB", "FLEX"]
        pool = [
            _p("qb1", "QB", 90.0),
            _p("qb2", "QB", 80.0),
            _p("rb1", "RB", 70.0),
            _p("rb2", "RB", 60.0),
        ]
        profile = build_position_profiles(pool, slots)
        qb = profile.positions["QB"]
        self.assertEqual(qb.required_slots, 1)
        self.assertEqual(qb.filled_slots, 1)
        self.assertEqual(qb.entered_lineup, 2)  # one in QB, one in SUPER_FLEX
        # Fragility can still flag this position; an unfilled DEDICATED
        # slot cannot, because there isn't one.
        self.assertEqual([r for r in qb.need_reasons if "slots filled" in r], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
