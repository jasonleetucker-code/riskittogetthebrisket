""" "Not simulated" must not read as "0% chance".

`trade_deadline` collapsed a missing owner into `0.0` playoff and
championship odds with `or 0.0`. The lowest band in `classify_team` is
`playoff < 0.25 and championship < 0.02`, so an owner the simulator never
saw came out as **"Seller — sell aging win-now players"**, over a summary
line stating "Playoff odds 0%" as fact.

On the live board that hit four of twelve managers, and one of them held the
strongest rest-of-season roster in the league (100th-percentile ROS strength).
Audit findings W17-F002 and W20-F002, both P0, both upheld under adversarial
review.

The distinction these tests pin is between three states the old expression
made indistinguishable: owner absent from the map, key absent from the row,
and a real simulated 0.0. Only the last is a fact about the team.
"""

from __future__ import annotations

import unittest

from src.ros.direction import classify_team
from src.ros.trade_deadline import build_team_directions


class TestClassifierAbstains(unittest.TestCase):
    def test_none_odds_abstain_rather_than_sell(self):
        out = classify_team(
            playoff_odds_pct=None,
            championship_odds_pct=None,
            team_ros_strength_percentile=1.0,
            roster_age_profile={"vetCount": 6},
        )
        self.assertEqual(out["label"], "Not simulated")
        self.assertEqual(out["oddsSource"], "owner_not_in_simulation")
        self.assertNotIn("Seller", out["label"])
        # The summary must not STATE an odds figure it does not have.
        # It may mention 0% to deny it — "this is missing input, not a 0%
        # chance" is the distinction the whole fix is about — so assert on
        # the claim shape the old summary used, not on the digits.
        self.assertNotIn("Playoff odds 0%", out["summary"])
        self.assertNotIn("Championship odds 0.0%", out["summary"])

    def test_an_age_heavy_roster_is_still_not_a_rebuilder_without_odds(self):
        """Age alone must not tip an unsimulated team into Strong Seller."""
        out = classify_team(
            playoff_odds_pct=None,
            championship_odds_pct=0.0,
            team_ros_strength_percentile=0.9,
            roster_age_profile={"vetCount": 9},
        )
        self.assertEqual(out["label"], "Not simulated")

    def test_a_real_simulated_zero_still_classifies(self):
        """The fix must not make a genuine 0% unreachable."""
        out = classify_team(
            playoff_odds_pct=0.0,
            championship_odds_pct=0.0,
            team_ros_strength_percentile=0.1,
            roster_age_profile={"vetCount": 6},
        )
        self.assertEqual(out["label"], "Strong Seller / Rebuilder")

    def test_a_strong_team_still_classifies(self):
        out = classify_team(
            playoff_odds_pct=0.9,
            championship_odds_pct=0.2,
            team_ros_strength_percentile=1.0,
        )
        self.assertEqual(out["label"], "Strong Buyer")


class TestRowsDistinguishAbsentFromZero(unittest.TestCase):
    """The exact live shape: strong team present in strength, absent from sims."""

    def _rows(self):
        return build_team_directions(
            teams=[],
            playoff_odds_map={"simulated": {"playoffOdds": 0.80}},
            championship_map={"simulated": {"championshipOdds": 0.30}},
            team_strength_map={
                "simulated": {"ownerId": "simulated", "rank": 2, "teamName": "Sim"},
                # The strongest roster in the league, and the simulator
                # never saw it — this is the W20-F002 shape exactly.
                "unsimulated": {"ownerId": "unsimulated", "rank": 1, "teamName": "Best"},
            },
        )

    def test_the_unsimulated_owner_is_not_told_to_sell(self):
        row = next(r for r in self._rows() if r["ownerId"] == "unsimulated")
        self.assertEqual(row["label"], "Not simulated")
        self.assertNotIn("sell", row["recommendation"].lower())

    def test_absent_odds_serialize_as_null_not_zero(self):
        row = next(r for r in self._rows() if r["ownerId"] == "unsimulated")
        self.assertIsNone(row["playoffOdds"])
        self.assertIsNone(row["championshipOdds"])

    def test_the_simulated_owner_is_unaffected(self):
        row = next(r for r in self._rows() if r["ownerId"] == "simulated")
        self.assertEqual(row["playoffOdds"], 0.80)
        self.assertEqual(row["label"], "Strong Buyer")

    def test_unsimulated_rows_sort_last_and_do_not_crash_the_sort(self):
        rows = self._rows()
        self.assertEqual(rows[-1]["ownerId"], "unsimulated")

    def test_a_row_present_with_a_real_zero_is_not_treated_as_absent(self):
        rows = build_team_directions(
            teams=[],
            playoff_odds_map={"zero": {"playoffOdds": 0.0}},
            championship_map={"zero": {"championshipOdds": 0.0}},
            team_strength_map={"zero": {"ownerId": "zero", "rank": 1}},
        )
        self.assertEqual(rows[0]["playoffOdds"], 0.0)
        self.assertNotEqual(rows[0]["label"], "Not simulated")


if __name__ == "__main__":
    unittest.main()
