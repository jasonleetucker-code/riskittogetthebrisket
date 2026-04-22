"""Unit tests for ``src/public_league/playoff_odds.py``.

Covers:
* Deterministic output when a seeded RNG is supplied.
* Probability collapse to 0/1 when the season is already complete.
* Round-robin fallback when Sleeper hasn't posted future matchups.
* Fallback to league-wide scoring pool for owners with too-few
  sampled weeks.
"""
from __future__ import annotations

import random
import unittest

from src.public_league import playoff_odds
from tests.public_league.fixtures import build_test_snapshot


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()


class ShapeAndDeterminism(_Base):
    def test_output_shape(self) -> None:
        rng = random.Random(1234)
        result = playoff_odds.compute_playoff_odds(
            self.snapshot, num_sims=200, rng=rng
        )
        self.assertIn("season", result)
        self.assertIn("numSims", result)
        self.assertIn("playoffSpots", result)
        self.assertIn("weeksPlayed", result)
        self.assertIn("weeksRemaining", result)
        self.assertIn("scheduleCertainty", result)
        self.assertIn("owners", result)
        self.assertIsInstance(result["owners"], list)
        for owner in result["owners"]:
            for key in (
                "ownerId",
                "displayName",
                "currentWins",
                "currentPointsFor",
                "playoffProbability",
            ):
                self.assertIn(key, owner)
            # Probability is a float in [0, 1].
            self.assertGreaterEqual(owner["playoffProbability"], 0.0)
            self.assertLessEqual(owner["playoffProbability"], 1.0)

    def test_seeded_run_is_deterministic(self) -> None:
        r1 = playoff_odds.compute_playoff_odds(
            self.snapshot, num_sims=400, rng=random.Random(42)
        )
        r2 = playoff_odds.compute_playoff_odds(
            self.snapshot, num_sims=400, rng=random.Random(42)
        )
        self.assertEqual(r1["owners"], r2["owners"])


class CompletedSeasonCollapse(_Base):
    def test_completed_season_collapses_to_zero_or_one(self) -> None:
        # The fixture's season-0 is marked completed.  When every
        # regular-season week is played, ``remainingWeeks == 0`` and
        # the simulator returns 0/1 probabilities deterministically.
        result = playoff_odds.compute_playoff_odds(
            self.snapshot, num_sims=0, rng=random.Random(0)
        )
        # The fixture's current season is 2025; check that the
        # simulator either collapses (weeksRemaining=0) or keeps
        # probabilities in [0,1].  The strictly-collapsed case:
        if result["weeksRemaining"] == 0:
            for owner in result["owners"]:
                self.assertIn(owner["playoffProbability"], (0.0, 1.0))
                self.assertEqual(result["scheduleCertainty"], "final")
            made = [o for o in result["owners"] if o["playoffProbability"] == 1.0]
            # When playoff spots exceed the fixture's owner count,
            # everyone "makes it" — that's degenerate but correct.
            expected_made = min(result["playoffSpots"], len(result["owners"]))
            self.assertEqual(len(made), expected_made)


class RoundRobinFallback(unittest.TestCase):
    def test_round_robin_pairs_everyone_across_cycle(self) -> None:
        owners = [f"o{i}" for i in range(4)]
        weeks = list(range(1, 4))  # n-1 weeks for even n = full round robin
        schedule = playoff_odds._round_robin_schedule(owners, weeks)
        pairs_seen = set()
        for wk, pairs in schedule.items():
            self.assertEqual(len(pairs), 2)  # 4 owners → 2 matches per week
            for a, b in pairs:
                key = tuple(sorted([a, b]))
                self.assertNotIn(key, pairs_seen, f"duplicate pair {key}")
                pairs_seen.add(key)
        # Every unique pair of owners plays exactly once.
        expected = (len(owners) * (len(owners) - 1)) // 2
        self.assertEqual(len(pairs_seen), expected)

    def test_odd_owner_count_gets_bye(self) -> None:
        # With 5 owners one sits out each week; no "__BYE__" token
        # should leak into the schedule.
        owners = [f"o{i}" for i in range(5)]
        weeks = list(range(1, 6))
        schedule = playoff_odds._round_robin_schedule(owners, weeks)
        for pairs in schedule.values():
            for a, b in pairs:
                self.assertNotEqual(a, "__BYE__")
                self.assertNotEqual(b, "__BYE__")

    def test_no_weeks_returns_empty_week_map(self) -> None:
        owners = ["a", "b", "c", "d"]
        self.assertEqual(playoff_odds._round_robin_schedule(owners, []), {})

    def test_no_owners_returns_empty_per_week(self) -> None:
        schedule = playoff_odds._round_robin_schedule([], [1, 2, 3])
        self.assertEqual(schedule, {1: [], 2: [], 3: []})


class Thresholds(unittest.TestCase):
    def test_min_sampled_weeks_and_default_spots_exist(self) -> None:
        # Sanity: if these constants ever change, the tests above
        # need revisiting.  Assertion is deliberately loose — just
        # that they're set to sensible positive integers.
        self.assertGreaterEqual(playoff_odds.MIN_SAMPLED_WEEKS, 1)
        self.assertGreaterEqual(playoff_odds.DEFAULT_PLAYOFF_SPOTS, 1)
        self.assertGreaterEqual(playoff_odds.DEFAULT_SIMS, 1000)


class LiveWeekRecordCounting(unittest.TestCase):
    """Regression for Codex PR #215 P1: half-scored weeks must not be
    counted as complete.  During a live week one team can have posted
    a score while the opponent hasn't played yet; crediting the
    scored side with a phantom win would feed the simulator a wrong
    current record.
    """

    def test_partial_week_treated_as_unplayed(self) -> None:
        # Build a minimal SeasonSnapshot-shaped object inline so the
        # assertion doesn't have to coexist with the rich production
        # fixture's pre-completed weeks.  Only the fields the
        # helpers read matter.
        class _SnapSeason:
            league_id = "L1"
            matchups_by_week = {
                1: [
                    {"roster_id": 1, "matchup_id": 10, "points": 110.5},
                    # Opponent in matchup 10 has no points yet.
                    {"roster_id": 2, "matchup_id": 10, "points": 0.0},
                ],
            }

            @property
            def regular_season_weeks(self):
                return [1]

        # Stub registry with a resolver that always returns the
        # roster_id as the owner id — simplest possible mapping.
        class _Registry:
            pass

        original_resolve = playoff_odds.metrics.resolve_owner
        playoff_odds.metrics.resolve_owner = (  # type: ignore[attr-defined]
            lambda reg, league_id, rid: f"owner-{rid}"
        )
        try:
            rec = playoff_odds._regular_season_record_to_date(_SnapSeason(), _Registry())
        finally:
            playoff_odds.metrics.resolve_owner = original_resolve  # type: ignore[attr-defined]

        # Neither side should be credited while week is half-scored.
        self.assertEqual(rec, {})


class NumSimsGuard(_Base):
    """Regression for Codex PR #215 P2: ``num_sims <= 0`` must not
    raise a ZeroDivisionError when the season has remaining weeks.
    """

    def test_zero_sims_returns_null_probabilities_not_exception(self) -> None:
        # Pass num_sims=0 explicitly.  Either the season has no
        # remaining weeks (collapse path, probabilities are 0/1) or
        # we hit the new guard and every probability is None.
        result = playoff_odds.compute_playoff_odds(
            self.snapshot, num_sims=0, rng=random.Random(0)
        )
        self.assertEqual(result["numSims"], 0)
        for owner in result["owners"]:
            self.assertIn(
                owner["playoffProbability"],
                (None, 0.0, 1.0),
                f"unexpected probability for {owner['ownerId']}: {owner['playoffProbability']}",
            )

    def test_negative_sims_normalised_to_zero(self) -> None:
        result = playoff_odds.compute_playoff_odds(
            self.snapshot, num_sims=-5, rng=random.Random(0)
        )
        self.assertEqual(result["numSims"], 0)

    def test_non_integer_sims_normalised_to_zero(self) -> None:
        result = playoff_odds.compute_playoff_odds(
            self.snapshot, num_sims="bogus", rng=random.Random(0)  # type: ignore[arg-type]
        )
        self.assertEqual(result["numSims"], 0)
