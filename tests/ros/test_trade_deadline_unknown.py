"""N-2: a manager absent from the sim must not be told to sell.

The audit's worst single finding. ``build_team_directions`` unions three
maps, so an owner present in only one of them still gets a row; the odds
were read with ``or 0.0``; and 0% playoff odds routes to "Seller":
*"Sell aging win-now players. Prioritize 2026/2027 picks."*

Measured on the live cache, ``data/ros/sims/latest_playoff.json`` holds
8 rows for a 12-team league — so four managers received that
instruction for no reason but absence from a file, and one of them was
ranked **#1 in the league** on ROS strength.
"""

from __future__ import annotations

import unittest

from src.ros.trade_deadline import build_team_directions

_SELL_VERBS = ("Seller", "Sell")


class TestAbsentManagerGetsNoRecommendation(unittest.TestCase):
    def _maps(self):
        """Two owners measured, one present only in team strength."""
        playoffs = {
            "measured_buyer": {"playoffOdds": 0.90},
            "measured_seller": {"playoffOdds": 0.02},
        }
        champs = {
            "measured_buyer": {"championshipOdds": 0.30},
            "measured_seller": {"championshipOdds": 0.00},
        }
        strengths = {
            "measured_buyer": {"teamName": "Measured Buyer", "rank": 2},
            "measured_seller": {"teamName": "Measured Seller", "rank": 3},
            # The N-2 case: strongest roster in the league, absent from
            # both sims.
            "absent_but_best": {"teamName": "Absent But Best", "rank": 1},
        }
        return playoffs, champs, strengths

    def test_the_absent_manager_is_not_told_to_sell(self) -> None:
        playoffs, champs, strengths = self._maps()
        rows = build_team_directions(
            playoff_odds_map=playoffs, championship_map=champs, team_strength_map=strengths
        )
        absent = next(r for r in rows if r["ownerId"] == "absent_but_best")
        self.assertNotIn(
            absent["label"],
            [v for v in _SELL_VERBS],
            "an absent manager must not receive a sell instruction",
        )
        for verb in _SELL_VERBS:
            self.assertNotIn(verb, absent["label"])

    def test_the_absent_manager_reports_insufficient_evidence(self) -> None:
        playoffs, champs, strengths = self._maps()
        rows = build_team_directions(
            playoff_odds_map=playoffs, championship_map=champs, team_strength_map=strengths
        )
        absent = next(r for r in rows if r["ownerId"] == "absent_but_best")
        self.assertEqual(absent["label"], "Insufficient evidence")
        self.assertFalse(absent["measurable"])

    def test_odds_are_null_with_a_reason_not_zero(self) -> None:
        """0% is a measurement. Absence is not, and must not render as one."""
        playoffs, champs, strengths = self._maps()
        rows = build_team_directions(
            playoff_odds_map=playoffs, championship_map=champs, team_strength_map=strengths
        )
        absent = next(r for r in rows if r["ownerId"] == "absent_but_best")
        self.assertIsNone(absent["playoffOdds"])
        self.assertIsNone(absent["championshipOdds"])
        self.assertEqual(absent["playoffOddsUnknown"]["reason"], "team_absent_from_sim")
        self.assertIn("playoffOdds", absent["playoffOddsUnknown"]["context"]["missingInputs"])

    def test_a_genuinely_measured_zero_still_sells(self) -> None:
        """The fix must not silence real signal.

        A team the sim covered and put at 2% playoff odds is a real
        seller, and must keep saying so.
        """
        playoffs, champs, strengths = self._maps()
        rows = build_team_directions(
            playoff_odds_map=playoffs, championship_map=champs, team_strength_map=strengths
        )
        seller = next(r for r in rows if r["ownerId"] == "measured_seller")
        self.assertTrue(any(v in seller["label"] for v in _SELL_VERBS))
        self.assertEqual(seller["playoffOdds"], 0.02)

    def test_the_absent_manager_is_still_listed(self) -> None:
        """Dropping them would replace one wrong answer with another."""
        playoffs, champs, strengths = self._maps()
        rows = build_team_directions(
            playoff_odds_map=playoffs, championship_map=champs, team_strength_map=strengths
        )
        self.assertEqual(len(rows), 3)
        self.assertIn("absent_but_best", {r["ownerId"] for r in rows})

    def test_unmeasurable_rows_sort_last(self) -> None:
        """A null championship chance must not sort as the worst one."""
        playoffs, champs, strengths = self._maps()
        rows = build_team_directions(
            playoff_odds_map=playoffs, championship_map=champs, team_strength_map=strengths
        )
        self.assertEqual(rows[-1]["ownerId"], "absent_but_best")

    def test_live_data_no_longer_tells_four_managers_to_sell(self) -> None:
        """The regression this batch exists to prevent, on real files.

        ``data/ros/`` is the tracked exception to the data/ gitignore, so
        this is checkable in CI rather than only on prod.
        """
        rows = build_team_directions()
        if not rows:
            self.skipTest("no ROS snapshot available in this checkout")
        unmeasurable = [r for r in rows if r.get("measurable") is False]
        for row in unmeasurable:
            with self.subTest(team=row["displayName"]):
                self.assertIsNone(row["playoffOdds"])
                for verb in _SELL_VERBS:
                    self.assertNotIn(verb, row["label"])


if __name__ == "__main__":
    unittest.main()
