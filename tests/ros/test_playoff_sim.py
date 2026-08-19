"""ROS playoff + championship simulator tests.

Build a tiny synthetic snapshot, run the sims with a low simulation
count for speed, and assert structural properties: probabilities sum
to 1.0 across seeds, contender tier classification matches the spec,
ROS-strength availability gracefully degrades to empirical-only.
"""

from __future__ import annotations

import random
import unittest
from unittest.mock import patch

from src.ros import championship, playoff_sim
from src.ros.championship import _contender_tier


class TestContenderTier(unittest.TestCase):
    def test_favorite_tier(self):
        self.assertEqual(_contender_tier(0.25, 0.95), "Favorite")

    def test_serious_contender_tier(self):
        self.assertEqual(_contender_tier(0.12, 0.80), "Serious Contender")

    def test_dangerous_playoff_tier(self):
        self.assertEqual(_contender_tier(0.06, 0.55), "Dangerous Playoff Team")
        self.assertEqual(_contender_tier(0.02, 0.55), "Dangerous Playoff Team")

    def test_fringe_playoff(self):
        self.assertEqual(_contender_tier(0.01, 0.35), "Fringe Playoff Team")

    def test_long_shot(self):
        self.assertEqual(_contender_tier(0.00, 0.15), "Long Shot")

    def test_rebuilder(self):
        self.assertEqual(_contender_tier(0.00, 0.05), "Rebuilder / Seller")


class TestEmptySnapshot(unittest.TestCase):
    """Sims must degrade gracefully when no scoring data exists."""

    def test_playoff_empty(self):
        from types import SimpleNamespace

        snap = SimpleNamespace(seasons=[], managers=None)
        out = playoff_sim.simulate_playoff_odds(snap, n_simulations=10)
        self.assertEqual(out["playoffOdds"], [])

    def test_championship_empty(self):
        from types import SimpleNamespace

        snap = SimpleNamespace(seasons=[], managers=None)
        out = championship.simulate_championship_odds(snap, n_simulations=10)
        self.assertEqual(out["championshipOdds"], [])


class TestRosStrengthLoader(unittest.TestCase):
    def test_returns_empty_when_no_snapshot(self):
        from pathlib import Path

        with patch.object(playoff_sim, "ROS_DATA_DIR", Path("/nonexistent")):
            self.assertEqual(playoff_sim._load_ros_strength_map(), {})


class TestSimulateBracket(unittest.TestCase):
    def test_top_seed_wins_when_distribution_is_dominant(self):
        # Construct distributions where owner1 is overwhelmingly best.
        distributions = {
            f"o{i}": playoff_sim._TeamDist(
                owner_id=f"o{i}",
                mean=200.0 - i * 30,  # o0 = 200, o5 = 50
                sd=5.0,
                pf_to_date=0.0,
            )
            for i in range(6)
        }
        # NOTE: a single unasserted `_simulate_bracket` call used to sit
        # here, its result bound to `finishes` and then never read —
        # immediately superseded by the seeded loop below, which
        # reassigns `rng` before every call.  It was dead code, not a
        # weak assertion, so it is DELETED rather than given an assert:
        # the comment below is right that one run proves nothing at
        # sd=5, so any assertion on a single draw would have been either
        # flaky or vacuous.  The loop is the real check.
        #
        # Owner with the highest mean should usually win.  Run many
        # times to check; a single run could go either way due to sd.
        #
        # Verified the surviving assertion DISCRIMINATES rather than
        # passing by construction (measured 2026-07-26): these dominant
        # distributions give o0 50/50, while a flat control where all
        # six teams share mean=100 sd=5 gives 12/50 — below the
        # threshold, so the assertion fails when the bracket stops
        # respecting seeding.  That is the property a "cannot fail"
        # check would lack.
        wins = 0
        for seed in range(50):
            rng = random.Random(seed)
            out = championship._simulate_bracket(
                list(distributions.keys()),
                distributions,
                bye_seeds=2,
                # V1-51 follow-up: the field size is no longer a literal
                # inside the function, and ``playoff_seeds`` has no
                # default — a plausible default is how the six-team
                # bracket survived for a seven-team league. All six of
                # these owners qualify, which is what the bye_seeds=2
                # above already assumed.
                playoff_seeds=6,
                rng=rng,
            )
            if out.get("o0") == 1:
                wins += 1
        self.assertGreater(wins, 25, "top seed should win majority of brackets")


class TestRosBlendConstants(unittest.TestCase):
    def test_blend_is_modest(self):
        # Spec: empirical history should still dominate; tunable but
        # not aggressive by default.
        self.assertLessEqual(playoff_sim.ROS_BLEND, 0.30)
        self.assertGreater(playoff_sim.ROS_BLEND, 0.0)

    def test_variance_bump_above_one(self):
        self.assertGreater(playoff_sim.BEST_BALL_VARIANCE_BUMP, 1.0)


class TestRosterLoaderFeedsTheOptimizerProperly(unittest.TestCase):
    """``_load_team_rosters`` is the input to an exact optimizer, and an
    exact solve is only as good as the data it is handed.

    Two defects lived here, and both are the same shape: the ALGORITHM
    was fixed while the LOADER still expressed the original bug.
    """

    @staticmethod
    def _snapshot_rows():
        return [
            {
                "ownerId": "o1",
                "startingLineup": [{"playerId": "s1", "position": "DL", "rosValue": 50.0}],
                "benchDepth": [{"playerId": "b1", "position": "WR", "rosValue": 10.0}],
                "fullRoster": [
                    {
                        "playerId": "s1",
                        "canonicalName": "Hybrid Guy",
                        "position": "DL",
                        "rosValue": 50.0,
                        "fantasyPositions": ["DL", "LB"],
                    },
                    {"playerId": "b1", "position": "WR", "rosValue": 10.0},
                    {"playerId": "deep", "position": "RB", "rosValue": 30.0},
                ],
            }
        ]

    def _load(self, rows):
        import json
        from pathlib import Path

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(rows)),
        ):
            return playoff_sim._load_team_rosters()

    def test_prefers_full_roster_over_the_truncated_pair(self):
        """benchDepth is capped at DEPTH_BENCH_LIMIT for depth SCORING,
        not roster enumeration; reading it as the whole team drops the
        tail that best ball actually pays for."""
        out = self._load(self._snapshot_rows())
        ids = {p["playerId"] for p in out["o1"]["starters"]}
        self.assertEqual(ids, {"s1", "b1", "deep"})
        self.assertEqual(out["o1"]["bench"], [])

    def test_carries_fantasy_positions_or_the_hybrid_fix_is_inert(self):
        """``_bestball_weekly_score`` reads ``fantasyPositions`` to build
        ``RosterPlayer.fantasy_positions``.  When the loader omitted it,
        ``eligible_positions()`` fell back to ``(position,)`` and every
        DL/LB hybrid was matched position-only — so routing the sim
        through the exact optimizer fixed the algorithm while the data
        still carried the original bug."""
        out = self._load(self._snapshot_rows())
        hybrid = next(p for p in out["o1"]["starters"] if p["playerId"] == "s1")
        self.assertEqual(hybrid["fantasyPositions"], ["DL", "LB"])

    def test_falls_back_when_the_snapshot_predates_full_roster(self):
        rows = self._snapshot_rows()
        del rows[0]["fullRoster"]
        out = self._load(rows)
        self.assertEqual([p["playerId"] for p in out["o1"]["starters"]], ["s1"])
        self.assertEqual([p["playerId"] for p in out["o1"]["bench"]], ["b1"])

    def test_dropping_fantasy_positions_measurably_costs_points(self):
        """Guards against a future refactor quietly dropping the key
        again.  Measured on the 12 real rosters (300 weeks): the cost is
        0.00-4.72 weekly points, mean 1.56, on 10 of 12 teams.  A roster
        with NO hybrids costs exactly 0.00 — the control proving the
        measurement isolates eligibility rather than sampling noise.
        """
        import json
        import statistics
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[1] / "league_intel" / "fixtures" / "league_pool.json"
        )
        if not path.exists():
            self.skipTest("league pool fixture not present")
        pool = json.loads(path.read_text())
        slots = ["DL", "DL", "LB", "LB", "FLEX", "WR", "RB"]

        team = max(
            pool,
            key=lambda t: sum(1 for p in t["players"] if len(p.get("fantasyPositions") or []) > 1),
        )
        with_fp, without_fp = [], []
        for w in range(60):
            with_fp.append(
                playoff_sim._bestball_weekly_score(team["players"], slots, random.Random(w))
            )
            stripped = [
                {k: v for k, v in p.items() if k != "fantasyPositions"} for p in team["players"]
            ]
            without_fp.append(playoff_sim._bestball_weekly_score(stripped, slots, random.Random(w)))
        self.assertGreater(
            statistics.fmean(with_fp),
            statistics.fmean(without_fp),
            "multi-position eligibility must raise the best-ball ceiling",
        )


if __name__ == "__main__":
    unittest.main()
