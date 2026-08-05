"""Odds must not be published from an unscored season (W30-F002, W19-F008).

Sleeper posts every regular-season matchup row before week 1 with
``points: 0``.  ``remaining_weeks`` is therefore the full schedule and the
existing empty-schedule preseason branch never fires — but ``league_pool``
is empty, so every owner pool falls back to the flat ``[100.0]``
placeholder.  ``rng.choice`` over a one-element list is a point mass: all
10,000 simulations return the identical standings, every probability comes
out exactly 1.0 or 0.0, and the v2 convergence check certifies the
degenerate result with a standard error of 0.0.
"""

from __future__ import annotations

import copy
import random
import unittest

from src.public_league import playoff_odds
from tests.public_league.fixtures import build_test_snapshot


def _unscored(snapshot):
    """Zero out every matchup score in the newest season, keeping the rows."""
    snap = copy.deepcopy(snapshot)
    season = snap.seasons[0]
    season.league = dict(season.league, status="in_season")
    for entries in season.matchups_by_week.values():
        for m in entries:
            m["points"] = 0.0
            m["custom_points"] = None
    for roster in season.rosters:
        roster.setdefault("settings", {}).update(
            wins=0, losses=0, ties=0, fpts=0, fpts_decimal=0
        )
    return snap, season


class PreseasonOddsGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot, cls.season = _unscored(build_test_snapshot())
        cls.result = playoff_odds.compute_playoff_odds(
            cls.snapshot, num_sims=500, rng=random.Random(7)
        )

    def test_the_schedule_is_still_full(self):
        # Guards the premise: this is NOT the empty-schedule branch.
        self.assertTrue(self.season.regular_season_weeks)
        self.assertGreater(sum(len(v) for v in self.season.matchups_by_week.values()), 0)

    def test_no_probability_is_published(self):
        probs = {o["playoffProbability"] for o in self.result["owners"]}
        self.assertEqual(probs, {None})

    def test_payload_says_why_and_does_not_claim_simulations(self):
        self.assertEqual(self.result["scheduleCertainty"], "preseason")
        self.assertEqual(self.result["unsimulatedReason"], "no_scored_weeks")
        self.assertEqual(self.result["numSims"], 0)
        self.assertEqual(self.result["weeksPlayed"], 0)

    def test_owner_set_is_intact(self):
        # Abstaining on the number must not drop the league's managers.
        played = playoff_odds.compute_playoff_odds(
            build_test_snapshot(), num_sims=200, rng=random.Random(7)
        )
        self.assertEqual(
            {o["ownerId"] for o in self.result["owners"]},
            {o["ownerId"] for o in played["owners"]},
        )

    def test_a_scored_season_still_simulates(self):
        played = playoff_odds.compute_playoff_odds(
            build_test_snapshot(), num_sims=200, rng=random.Random(7)
        )
        self.assertNotEqual(played["scheduleCertainty"], "preseason")
        self.assertTrue(all(o["playoffProbability"] is not None for o in played["owners"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
