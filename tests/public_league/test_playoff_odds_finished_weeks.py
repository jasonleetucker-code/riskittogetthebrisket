"""Playoff Odds samples ONLY finished weeks, and keeps a real 0.0.

The simulator's empirical score distributions used to come from their own
per-entry rule: every regular-season week, filtered on ``points > 0``. That
had two measured failure modes (owner report 2026-09-23):

* an IN-PROGRESS week's Thursday-night partial scores entered the
  distributions as if they were completed games;
* a roster that genuinely scored ``0.0`` in a FINISHED week was dropped,
  because "scored" was defined as "positive".

The canonical completed-score definition is ``luck._season_weekly_scores``
(``metrics.final_regular_season_weeks`` + ``points is None`` is missing),
shared with Luck and Power. Playoff Odds must consume it, not re-derive it.
"""

from __future__ import annotations

import unittest

from src.public_league import luck, playoff_odds
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import SeasonSnapshot

_OWNERS = ["owner-A", "owner-B", "owner-C", "owner-D"]
_USERS = [{"user_id": o, "display_name": o[-1], "metadata": {}} for o in _OWNERS]
_ROSTERS = [
    {"roster_id": i, "owner_id": o, "players": [], "settings": {}}
    for i, o in enumerate(_OWNERS, start=1)
]


def _league(last_scored_leg: int | None) -> dict:
    settings: dict = {"playoff_week_start": 15, "playoff_teams": 2}
    if last_scored_leg is not None:
        settings["last_scored_leg"] = last_scored_leg
    return {
        "league_id": "L1",
        "season": "2026",
        "season_type": "regular",
        "status": "in_season",
        "total_rosters": 4,
        "settings": settings,
    }


def _week(a: float | None, b: float | None, c: float | None, d: float | None) -> list[dict]:
    return [
        {"matchup_id": 1, "roster_id": 1, "points": a},
        {"matchup_id": 1, "roster_id": 2, "points": b},
        {"matchup_id": 2, "roster_id": 3, "points": c},
        {"matchup_id": 2, "roster_id": 4, "points": d},
    ]


def _season_and_registry(matchups_by_week: dict[int, list[dict]], last_scored_leg: int | None):
    league = _league(last_scored_leg)
    season = SeasonSnapshot(
        season="2026",
        league_id="L1",
        league=league,
        users=_USERS,
        rosters=_ROSTERS,
        matchups_by_week=matchups_by_week,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    registry = build_manager_registry([{"league": league, "users": _USERS, "rosters": _ROSTERS}])
    return season, registry


class InProgressWeekTests(unittest.TestCase):
    """A live week's partial scores are not completed games."""

    def setUp(self):
        # Weeks 1-2 final (host clock says 2); week 3 is Thursday night:
        # two rosters carry partial scores, two sit at a literal 0.0.
        self.season, self.registry = _season_and_registry(
            {
                1: _week(110.0, 100.0, 120.0, 90.0),
                2: _week(105.0, 95.0, 115.0, 85.0),
                3: _week(18.0, 0.0, 25.0, 0.0),
            },
            last_scored_leg=2,
        )

    def test_partial_scores_never_enter_the_distributions(self):
        per_owner, pool = playoff_odds._season_weekly_scores(self.season, self.registry)
        self.assertEqual(per_owner["owner-A"], [110.0, 105.0])
        self.assertEqual(per_owner["owner-C"], [120.0, 115.0])
        self.assertNotIn(18.0, pool)
        self.assertNotIn(25.0, pool)
        self.assertEqual(len(pool), 8)  # 4 rosters x 2 finished weeks

    def test_every_owner_has_the_same_denominator(self):
        # The old rule gave A and C three samples and B and D two: the
        # PRIOR-A03-F03 defect class, inside the simulator.
        per_owner, _pool = playoff_odds._season_weekly_scores(self.season, self.registry)
        self.assertEqual({o: len(v) for o, v in per_owner.items()}, {o: 2 for o in _OWNERS})


class FinishedZeroTests(unittest.TestCase):
    """0.0 in a finished week is an observation; None is missing."""

    def setUp(self):
        self.season, self.registry = _season_and_registry(
            {
                1: _week(110.0, 100.0, 120.0, 90.0),
                # Finished week in which owner-B genuinely scored nothing and
                # owner-D's row carries no score at all.
                2: _week(105.0, 0.0, 115.0, None),
            },
            last_scored_leg=2,
        )

    def test_a_finished_zero_stays_in_the_sample(self):
        per_owner, pool = playoff_odds._season_weekly_scores(self.season, self.registry)
        self.assertEqual(per_owner["owner-B"], [100.0, 0.0])
        self.assertIn(0.0, pool)

    def test_a_missing_score_is_missing_not_zero(self):
        per_owner, pool = playoff_odds._season_weekly_scores(self.season, self.registry)
        self.assertEqual(per_owner["owner-D"], [90.0])
        self.assertEqual(len(pool), 7)


class OneDefinitionTests(unittest.TestCase):
    """Playoff Odds reads the canonical owner rather than a copy of it."""

    def test_matches_the_canonical_completed_score_definition(self):
        season, registry = _season_and_registry(
            {
                1: _week(110.0, 100.0, 120.0, 90.0),
                2: _week(105.0, 0.0, 115.0, None),
                3: _week(18.0, 0.0, 25.0, 0.0),
            },
            last_scored_leg=2,
        )
        per_owner, pool = playoff_odds._season_weekly_scores(season, registry)
        canonical = luck._season_weekly_scores(season, registry)
        expected_pool = [pts for wk in sorted(canonical) for _o, pts in canonical[wk]]
        self.assertEqual(pool, expected_pool)
        self.assertEqual(sum(len(v) for v in per_owner.values()), len(expected_pool))


if __name__ == "__main__":
    unittest.main()
