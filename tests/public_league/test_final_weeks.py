"""Unit coverage for the completed-league-week predicate.

``metrics.final_regular_season_weeks`` is the gate that decides which weeks
may be aggregated into a per-game rate.  It exists because the previous
answer — every regular-season week, filtered per roster-entry on
``points > 0`` — admitted an IN-PROGRESS week for whichever rosters happened
to have a Thursday-night player and dropped it for the rest, so one table
averaged some teams over two games and others over one (PRIOR-A03-F03).

The gate is a union of two independent proofs, and these tests pin both
directions plus the tri-state read of the host clock.
"""

from __future__ import annotations

import unittest

from src.public_league import metrics
from src.public_league.snapshot import SeasonSnapshot


def _season(
    matchups_by_week: dict[int, list[dict]],
    *,
    last_scored_leg: object = "omit",
    total_rosters: int = 4,
    playoff_week_start: int = 15,
) -> SeasonSnapshot:
    settings: dict = {"playoff_week_start": playoff_week_start}
    if last_scored_leg != "omit":
        settings["last_scored_leg"] = last_scored_leg
    return SeasonSnapshot(
        season="2026",
        league_id="L",
        league={
            "league_id": "L",
            "season": "2026",
            "season_type": "regular",
            "total_rosters": total_rosters,
            "settings": settings,
        },
        users=[],
        rosters=[{"roster_id": i, "owner_id": f"o{i}"} for i in range(1, total_rosters + 1)],
        matchups_by_week=matchups_by_week,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _week(*points: float | None) -> list[dict]:
    return [
        {"matchup_id": (i + 1) // 2, "roster_id": i, "points": p}
        for i, p in enumerate(points, start=1)
    ]


_FULL = (110.0, 100.0, 120.0, 90.0)
#: Live shape: two rosters have a Thursday-night partial, two sit at 0.0.
_IN_PROGRESS = (0.0, 18.0, 0.0, 25.0)


class LastScoredWeekTests(unittest.TestCase):
    """The host clock is tri-state and must never be coerced."""

    def test_reads_the_hosts_own_stamp(self):
        self.assertEqual(metrics.last_scored_week(_season({}, last_scored_leg=7)), 7)

    def test_zero_is_a_real_answer_not_an_absence(self):
        # "Nothing is final yet" is a statement; None is the lack of one.
        self.assertEqual(metrics.last_scored_week(_season({}, last_scored_leg=0)), 0)

    def test_absent_is_unverified_not_zero(self):
        self.assertIsNone(metrics.last_scored_week(_season({})))

    def test_unparseable_is_unverified(self):
        for bad in ("", "week two", None, [], {}, True):
            self.assertIsNone(metrics.last_scored_week(_season({}, last_scored_leg=bad)), repr(bad))

    def test_an_integer_string_is_accepted(self):
        self.assertEqual(metrics.last_scored_week(_season({}, last_scored_leg="3")), 3)


class FinalRegularSeasonWeeksTests(unittest.TestCase):
    def test_an_in_progress_week_is_withheld_by_both_proofs(self):
        season = _season({1: _week(*_FULL), 2: _week(*_IN_PROGRESS)}, last_scored_leg=1)
        self.assertEqual(metrics.final_regular_season_weeks(season), [1])

    def test_host_clock_absent_falls_back_to_data_completeness(self):
        season = _season({1: _week(*_FULL), 2: _week(*_IN_PROGRESS)})
        self.assertEqual(metrics.final_regular_season_weeks(season), [1])

    def test_a_stale_host_clock_does_not_withhold_a_fully_scored_week(self):
        """Union, not intersection: either proof alone admits a week."""
        season = _season({1: _week(*_FULL), 2: _week(*_FULL)}, last_scored_leg=1)
        self.assertEqual(metrics.final_regular_season_weeks(season), [1, 2])

    def test_only_the_host_clock_can_admit_a_genuine_zero(self):
        """A real 0.0 is indistinguishable from "hasn't played" in the data.

        So the completeness proof must withhold it, and the host clock is
        the only thing that can say the week is done.
        """
        matchups = {1: _week(110.0, 100.0, 120.0, 0.0)}
        self.assertEqual(metrics.final_regular_season_weeks(_season(matchups)), [])
        self.assertEqual(
            metrics.final_regular_season_weeks(_season(matchups, last_scored_leg=1)), [1]
        )

    def test_a_short_week_is_withheld_by_the_completeness_proof(self):
        """8 rows where 12 are expected would reinstate split denominators."""
        season = _season({1: _week(110.0, 100.0)}, total_rosters=4)
        self.assertEqual(metrics.final_regular_season_weeks(season), [])

    def test_a_scored_but_unpaired_roster_is_still_a_finished_week(self):
        """Deliberately not a pairing check.

        A bye, an odd team count or a malformed matchup row leaves a roster
        scored but unpaired; the week is still finished, and ``luck.py``
        already handles that owner by charging them no record while keeping
        them in the all-play pool.  Some callers carry no ``matchup_id`` at
        all.
        """
        rows = [
            {"matchup_id": 1, "roster_id": 1, "points": 120.0},
            {"matchup_id": 1, "roster_id": 2, "points": 100.0},
            {"matchup_id": 2, "roster_id": 3, "points": 110.0},
            {"roster_id": 4, "points": 90.0},
        ]
        self.assertEqual(metrics.final_regular_season_weeks(_season({1: rows})), [1])

    def test_playoff_weeks_are_never_included(self):
        season = _season(
            {1: _week(*_FULL), 15: _week(*_FULL)}, last_scored_leg=15, playoff_week_start=15
        )
        self.assertEqual(metrics.final_regular_season_weeks(season), [1])

    def test_a_completed_season_returns_every_regular_week_unchanged(self):
        """The no-history-churn guarantee.

        A finished season reports ``last_scored_leg`` above its
        ``playoff_week_start`` (measured: the real 2025 season reports 17
        against a start of 14), so applying this gate must leave published
        history byte-identical.
        """
        weeks = {wk: _week(*_FULL) for wk in range(1, 18)}
        season = _season(weeks, last_scored_leg=17, playoff_week_start=14)
        self.assertEqual(
            metrics.final_regular_season_weeks(season), list(season.regular_season_weeks)
        )
        self.assertEqual(metrics.final_regular_season_weeks(season), list(range(1, 14)))

    def test_an_empty_season_is_empty_not_an_error(self):
        self.assertEqual(metrics.final_regular_season_weeks(_season({})), [])


class WeekIsFullyScoredTests(unittest.TestCase):
    def test_no_entries_is_not_complete(self):
        self.assertFalse(metrics.week_is_fully_scored([]))

    def test_a_fully_stubbed_future_week_is_not_complete(self):
        """Sleeper pre-generates future weeks entirely at 0.0."""
        self.assertFalse(metrics.week_is_fully_scored(_week(0.0, 0.0, 0.0, 0.0)))

    def test_an_unknown_roster_count_skips_the_count_check(self):
        self.assertTrue(metrics.week_is_fully_scored(_week(*_FULL), expected_rosters=None))
        self.assertTrue(metrics.week_is_fully_scored(_week(*_FULL), expected_rosters=0))


if __name__ == "__main__":
    unittest.main()
