"""#1530 finding B -- an unpaired (bye) week is not a 0-point loss.

``power_v2`` read ``actuals.get(oid, 0.0)``: a team that scored but had no
matchup (an odd team count) was charged a LOSS for a game it never played,
into its matchup-derived record, wins/losses, streak and luck-regression
input.  Latent today (both live leagues have even team counts), so the
fixture is a five-team league with a rotating bye.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ros import power_v2, team_strength
from tests.ros.test_power_v2 import _make_snapshot


def _week(pairs: list[tuple[int, int]], bye: int, points: dict[int, float]) -> list[dict]:
    rows = []
    for mid, (a, b) in enumerate(pairs, start=1):
        rows.append({"roster_id": a, "matchup_id": mid, "points": points[a]})
        rows.append({"roster_id": b, "matchup_id": mid, "points": points[b]})
    rows.append({"roster_id": bye, "matchup_id": None, "points": points[bye]})
    return rows


class TestPowerByeWeek(unittest.TestCase):
    ROSTERS = [{"roster_id": r, "owner_id": f"o{r}"} for r in range(1, 6)]
    # Week 1: o5 on bye (scores 150 -- would beat everyone); week 2: o5 beats o1.
    MATCHUPS = {
        1: _week([(1, 2), (3, 4)], 5, {1: 100.0, 2: 90.0, 3: 80.0, 4: 70.0, 5: 150.0}),
        2: _week([(5, 1), (2, 3)], 4, {1: 100.0, 2: 90.0, 3: 80.0, 4: 70.0, 5: 120.0}),
    }

    def _section(self):
        snapshot = _make_snapshot(
            rosters=self.ROSTERS, matchups_by_week=self.MATCHUPS, last_scored_leg=2
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(team_strength, "ROS_DATA_DIR", Path(tmp)):
                return power_v2.build_section(snapshot, lens=power_v2.LENS_RESULTS_ONLY)

    def test_a_bye_week_charges_no_phantom_loss(self) -> None:
        rows = {r["ownerId"]: r for r in self._section()["currentRanking"]}
        # o5 played exactly one game and won it.  Before the fix: "1-1".
        self.assertEqual(rows["o5"]["recordSource"], "matchups")
        self.assertEqual(rows["o5"]["record"], "1-0")
        # o4 (bye in week 2) played and lost once.  Before the fix: "0-2".
        self.assertEqual(rows["o4"]["record"], "0-1")
        # Teams that played both weeks are unaffected.
        self.assertEqual(rows["o1"]["record"], "1-1")
        self.assertEqual(rows["o2"]["record"], "1-1")

    def test_a_bye_week_is_still_a_scored_week(self) -> None:
        """A bye is a real week of scoring (PPG, all-play), just not a game:
        only the result-based quantities skip it."""
        rows = {r["ownerId"]: r for r in self._section()["currentRanking"]}
        self.assertEqual(rows["o5"]["gamesUsed"], 2)
        self.assertAlmostEqual(rows["o5"]["components"]["pointsPerGame"], 135.0, places=2)

    def test_the_win_loss_component_divides_by_games_played(self) -> None:
        rows = {r["ownerId"]: r for r in self._section()["currentRanking"]}
        # o5 is 1-0 and o4 is 0-1: the extremes of the W/L field.  Before
        # the fix o5 read 0.5 (1 win over 2 "games").
        self.assertEqual(rows["o5"]["components"]["wl_record"], 1.0)
        self.assertEqual(rows["o4"]["components"]["wl_record"], 0.0)


if __name__ == "__main__":
    unittest.main()
