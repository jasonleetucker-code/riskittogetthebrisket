"""N-1: no games played and none scheduled must not mean 100% / 0%.

With an empty remaining schedule the simulation loop draws no games, so
every one of its 2000 "simulations" replays the current standings and
each team lands on exactly 1.0 or 0.0 — stamped ``converged: true``.
Measured on the live cache in August 2026, before a single game of the
season: ``playoffOdds`` were ``[1.0 x6, 0.0 x2]``.

The fix cannot simply refuse every empty schedule, because a FINISHED
season has exactly the same shape and there 1.0/0.0 is a *fact*.  The
two are separated on whether any games have actually been played, and
these tests pin both sides of that split — a fix that silenced the
finished season would trade one wrong answer for another.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.ros import playoff_sim


def _dists(owners):
    return {
        o: playoff_sim._TeamDist(owner_id=o, mean=110.0, sd=20.0, pf_to_date=0.0) for o in owners
    }


class _Harness(unittest.TestCase):
    """Drive ``simulate_playoff_odds`` without a real league snapshot."""

    owners = ["a", "b", "c", "d"]

    def _run(self, *, record, schedule, **kwargs):
        snap = SimpleNamespace(seasons=[], managers=SimpleNamespace(by_owner_id={}))
        # This harness has no league settings by construction, and since
        # V1-51 an unresolvable bracket is its own refusal — which would
        # fire ahead of the ones under test here. Pinning it explicitly
        # keeps each test about the thing it names; bracket resolution has
        # its own tests in tests/public_league/test_playoff_structure.py.
        kwargs.setdefault("playoff_seeds", 6)
        kwargs.setdefault("bye_seeds", 2)
        with (
            patch.object(
                playoff_sim,
                "_build_team_distributions",
                return_value=(_dists(self.owners), {o: 0.0 for o in self.owners}),
            ),
            patch.object(playoff_sim, "_current_record", return_value=record),
            patch.object(playoff_sim, "_remaining_schedule", return_value=schedule),
            patch.object(playoff_sim, "_load_ros_strength_map", return_value={}),
            patch.object(playoff_sim, "_league_best_ball", return_value=False),
        ):
            return playoff_sim.simulate_playoff_odds(snap, n_simulations=50, **kwargs)


class TestNothingPlayedAndNothingScheduled(_Harness):
    def test_returns_no_odds_at_all(self) -> None:
        out = self._run(
            record={o: {"wins": 0, "losses": 0} for o in self.owners},
            schedule=[],
        )
        self.assertEqual(out["playoffOdds"], [])
        self.assertEqual(out["n_simulations"], 0)

    def test_says_why_rather_than_going_quiet(self) -> None:
        """An empty list alone reads as 'no teams', which is a lie too."""
        out = self._run(
            record={o: {"wins": 0, "losses": 0} for o in self.owners},
            schedule=[],
        )
        self.assertEqual(out["unsimulable"]["reason"], "no_games_played_and_none_scheduled")
        self.assertIn("not a 0% chance", out["unsimulable"]["detail"])

    def test_is_never_stamped_converged(self) -> None:
        """Nothing was simulated, so there is nothing to be confident about."""
        out = self._run(
            record={o: {"wins": 0, "losses": 0} for o in self.owners},
            schedule=[],
        )
        self.assertNotIn("converged", out)

    def test_a_record_of_missing_keys_counts_as_nothing_played(self) -> None:
        """Absent wins/losses is unobserved, not a 0-0 start.

        Both readings lead here, but for opposite reasons, and the
        coercion that would collapse them is the one this whole batch
        exists to remove.
        """
        out = self._run(record={o: {} for o in self.owners}, schedule=[])
        self.assertEqual(out["playoffOdds"], [])


class TestAFinishedSeasonStillReportsItsResult(_Harness):
    """The control: 1.0/0.0 is correct once the games have been played."""

    def test_completed_season_still_simulates(self) -> None:
        out = self._run(
            record={
                "a": {"wins": 10, "losses": 4},
                "b": {"wins": 9, "losses": 5},
                "c": {"wins": 5, "losses": 9},
                "d": {"wins": 4, "losses": 10},
            },
            schedule=[],
        )
        self.assertEqual(len(out["playoffOdds"]), 4)
        self.assertNotIn("unsimulable", out)

    def test_a_season_in_progress_still_simulates(self) -> None:
        out = self._run(
            record={
                "a": {"wins": 3, "losses": 1},
                "b": {"wins": 2, "losses": 2},
                "c": {"wins": 2, "losses": 2},
                "d": {"wins": 1, "losses": 3},
            },
            schedule=[(5, "a", "b"), (5, "c", "d")],
        )
        self.assertEqual(len(out["playoffOdds"]), 4)
        self.assertNotIn("unsimulable", out)

    def test_a_preseason_league_with_a_schedule_still_simulates(self) -> None:
        """Week 1 has not been played, but the season is real."""
        out = self._run(
            record={o: {"wins": 0, "losses": 0} for o in self.owners},
            schedule=[(1, "a", "b"), (1, "c", "d")],
        )
        self.assertEqual(len(out["playoffOdds"]), 4)
        self.assertNotIn("unsimulable", out)


class TestNoScoredWeeksInLeague(unittest.TestCase):
    """V1-51 residual: the third refusal branch, ``if not distributions:``,
    used to return ``n_simulations: 0`` with no ``unsimulable`` block at
    all — the one state in this function that went unnamed while its two
    siblings in this same function (and both sibling engines,
    ``src.public_league.playoff_odds`` and ``src.ros.championship``) all
    stamp ``unsimulable: {reason: "no_scored_weeks_in_league"}`` for the
    identical underlying signal (``playoff_odds._season_weekly_scores``
    returning nothing for the league).

    Distinct from ``TestNothingPlayedAndNothingScheduled`` above: that
    class drives the ``not schedule and games_played <= 0`` branch with
    ``_build_team_distributions`` patched to always succeed. This class
    drives the earlier ``if not distributions:`` branch directly, which
    that harness structurally cannot reach.
    """

    owners = ["a", "b", "c", "d"]

    def _run(self, **kwargs):
        snap = SimpleNamespace(seasons=[], managers=SimpleNamespace(by_owner_id={}))
        kwargs.setdefault("playoff_seeds", 6)
        kwargs.setdefault("bye_seeds", 2)
        with (
            patch.object(
                playoff_sim,
                "_build_team_distributions",
                return_value=({}, {}),
            ),
            patch.object(playoff_sim, "_load_ros_strength_map", return_value={}),
            patch.object(playoff_sim, "_league_best_ball", return_value=False),
        ):
            return playoff_sim.simulate_playoff_odds(snap, n_simulations=50, **kwargs)

    def test_no_scored_weeks_yields_the_shared_unsimulable_reason(self) -> None:
        out = self._run()
        self.assertEqual(out["playoffOdds"], [])
        self.assertEqual(out["n_simulations"], 0)
        self.assertEqual(out["unsimulable"]["reason"], "no_scored_weeks_in_league")
        self.assertIn("not a 0% chance", out["unsimulable"]["detail"])

    def test_no_scored_weeks_state_is_never_stamped_converged(self) -> None:
        out = self._run()
        self.assertNotIn("converged", out)

    def test_no_scored_weeks_is_a_distinct_reason_from_nothing_scheduled(self) -> None:
        """The two refusal branches this function carries must not
        collapse into one code path — reached via a genuinely different
        precondition (empty distributions vs. an empty schedule with no
        games played), so their reasons must stay distinguishable."""
        out = self._run()
        self.assertNotEqual(
            out["unsimulable"]["reason"],
            "no_games_played_and_none_scheduled",
        )


class TestCompletedGamesHelper(unittest.TestCase):
    def test_ignores_non_numeric_and_boolean_values(self) -> None:
        self.assertEqual(playoff_sim._completed_games({"wins": 3, "losses": 2}), 5.0)
        self.assertEqual(playoff_sim._completed_games({"wins": None, "losses": "2"}), 0.0)
        self.assertEqual(playoff_sim._completed_games({"wins": True}), 0.0)
        self.assertEqual(playoff_sim._completed_games(None), 0.0)


if __name__ == "__main__":
    unittest.main()
