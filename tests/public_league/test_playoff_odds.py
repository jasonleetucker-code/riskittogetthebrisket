"""Unit tests for ``src/public_league/playoff_odds.py``.

Since C5-PLAY-01 this module is the public ``playoffOdds`` section laid over
the ONE canonical engine (``src.ros.playoff_sim``): it simulates nothing.
Covers:
* the section's shape, filled from the canonical forecast;
* probability collapse to 0/1 when the season is already complete;
* un-posted weeks are LABELLED (``posted_weeks_only``), never invented;
* the shared fact helpers (record, finished weeks, posted schedule, ties)
  the canonical engine itself reads.

The retired loop's own tests (round-robin and cycle-inferred schedules,
``MIN_SAMPLED_WEEKS``, ``num_sims`` guards, seeded determinism of the
empirical resampler) are deleted with it.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.public_league import playoff_odds
from src.ros import playoff_sim
from tests.public_league.fixtures import build_test_snapshot


def _offline_engine():
    """Patch the canonical engine's file/ROS reads so it runs on the snapshot
    alone: no cache file, no ROS strength, no best-ball roster reads."""
    return [
        patch.object(playoff_sim, "_load_cached_payload", lambda *a, **k: None),
        patch.object(playoff_sim, "_load_ros_strength_map", lambda *a, **k: {}),
        patch.object(playoff_sim, "_load_team_depth_ratios", lambda *a, **k: {}),
        patch.object(playoff_sim, "_league_best_ball", lambda *a, **k: False),
        patch("src.public_league.draft_order.league_draft_order_rule", lambda *a, **k: None),
    ]


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()

    def setUp(self) -> None:
        for p in _offline_engine():
            p.start()
            self.addCleanup(p.stop)
        # The live-run memo is keyed by snapshot identity, and every fixture
        # snapshot shares one; start each test from an empty memo.
        playoff_sim._LIVE_MEMO.clear()
        self.addCleanup(playoff_sim._LIVE_MEMO.clear)


class ShapeAndDeterminism(_Base):
    def test_output_shape(self) -> None:
        result = playoff_odds.compute_playoff_odds(self.snapshot)
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
            # Probability is a float in [0, 1], or None (never computed).
            p = owner["playoffProbability"]
            if p is not None:
                self.assertGreaterEqual(p, 0.0)
                self.assertLessEqual(p, 1.0)
        self.assertEqual(result["engine"], "src.ros.playoff_sim")

    def test_two_reads_of_one_snapshot_publish_one_answer(self) -> None:
        """The live fallback is computed once per snapshot and shared, so
        two reads (or two surfaces) cannot draw two Monte Carlos."""
        r1 = playoff_odds.compute_playoff_odds(self.snapshot)
        r2 = playoff_odds.compute_playoff_odds(self.snapshot)
        self.assertEqual(r1["owners"], r2["owners"])


class CompletedSeasonCollapse(_Base):
    def test_completed_season_collapses_to_zero_or_one(self) -> None:
        # The fixture's season-0 is marked completed.  When every
        # regular-season week is played, ``remainingWeeks == 0`` and
        # the simulator returns 0/1 probabilities deterministically.
        # The fixture's season has only two finished weeks, so without ROS
        # evidence the canonical engine refuses (team_strength_unavailable)
        # rather than replay a standings table it cannot tell apart.  Give
        # it real (positive) strength so the finished-season path is what is
        # exercised.
        owners = playoff_odds._owners_in_league(self.snapshot, self.snapshot.current_season)
        strengths = {o: 50.0 + i for i, o in enumerate(owners)}
        with patch.object(playoff_sim, "_load_ros_strength_map", lambda *a, **k: strengths):
            result = playoff_odds.compute_playoff_odds(self.snapshot)
        self.assertTrue(result["simulated"], result.get("unsimulable"))
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


class Thresholds(unittest.TestCase):
    def test_there_is_no_default_playoff_spot_count_any_more(self) -> None:
        """V1-51. ``DEFAULT_PLAYOFF_SPOTS = 6`` stood in for the league's
        own ``playoff_teams``, and the live league takes SEVEN — so the
        fallback was wrong for the league it served. Its absence is
        asserted rather than assumed, because a plausible default back in
        scope is how a guess gets re-adopted."""
        self.assertFalse(hasattr(playoff_odds, "DEFAULT_PLAYOFF_SPOTS"))

    def test_the_retired_engine_stays_retired(self) -> None:
        """C5-PLAY-01. Every piece of the second simulator is gone, so it
        cannot be wired back in without someone deciding to."""
        for name in (
            "DEFAULT_SIMS",
            "MIN_SAMPLED_WEEKS",
            "_round_robin_schedule",
            "_infer_schedule_from_posted",
            "_detect_cycle_length",
            "_all_posted_pair_lists",
        ):
            self.assertFalse(hasattr(playoff_odds, name), name)


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
            # Host clock: nothing finished yet (week 1 is live).
            league = {"settings": {"last_scored_leg": 0}}
            num_teams = 2
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


class PartialWeekPostedPairs(unittest.TestCase):
    """Regression for Codex PR #215 second-round P1 review:
    ``_posted_future_matchups`` must emit posted pairings for the
    unplayed matchups inside a partially-scored week, not drop the
    whole week.
    """

    def _make_season(self, entries_by_week, last_scored_leg=None):
        class _Season:
            league_id = "L1"
            league = {"settings": {"last_scored_leg": last_scored_leg}}
            num_teams = 4
            matchups_by_week = entries_by_week

            @property
            def regular_season_weeks(self):
                return sorted(entries_by_week.keys())

        return _Season()

    def setUp(self) -> None:
        self._original = playoff_odds.metrics.resolve_owner
        playoff_odds.metrics.resolve_owner = (  # type: ignore[attr-defined]
            lambda reg, league_id, rid: f"owner-{rid}"
        )

    def tearDown(self) -> None:
        playoff_odds.metrics.resolve_owner = self._original  # type: ignore[attr-defined]

    def test_partial_week_emits_every_pair_including_started_ones(self) -> None:
        """D4 (2026-09-26).  Week 3 is live: matchup 10 has points on both
        sides (a Thursday-night sliver), matchup 11 has not started.  A
        started matchup is not a finished one, so NEITHER counts toward the
        record and BOTH must be simulated.  This test used to assert only
        matchup 11 was emitted — the exact rule that froze 3 of 6 live
        best-ball matchups as finals on Thursday scores."""
        entries = {
            3: [
                {"roster_id": 1, "matchup_id": 10, "points": 110.2},
                {"roster_id": 2, "matchup_id": 10, "points": 95.7},
                {"roster_id": 3, "matchup_id": 11, "points": 0.0},
                {"roster_id": 4, "matchup_id": 11, "points": 0.0},
            ],
        }
        posted = playoff_odds._posted_future_matchups(
            self._make_season(entries, last_scored_leg=2), None
        )
        self.assertIn(3, posted)
        self.assertEqual(
            sorted(tuple(sorted(p)) for p in posted[3]),
            [("owner-1", "owner-2"), ("owner-3", "owner-4")],
        )

    def test_fully_unplayed_week_emits_all_pairs(self) -> None:
        entries = {
            5: [
                {"roster_id": 1, "matchup_id": 20, "points": 0.0},
                {"roster_id": 2, "matchup_id": 20, "points": 0.0},
                {"roster_id": 3, "matchup_id": 21, "points": 0.0},
                {"roster_id": 4, "matchup_id": 21, "points": 0.0},
            ],
        }
        posted = playoff_odds._posted_future_matchups(
            self._make_season(entries, last_scored_leg=4), None
        )
        self.assertEqual(len(posted[5]), 2)

    def test_fully_played_week_absent_from_posted(self) -> None:
        entries = {
            2: [
                {"roster_id": 1, "matchup_id": 30, "points": 100.0},
                {"roster_id": 2, "matchup_id": 30, "points": 90.0},
                {"roster_id": 3, "matchup_id": 31, "points": 115.0},
                {"roster_id": 4, "matchup_id": 31, "points": 105.0},
            ],
        }
        posted = playoff_odds._posted_future_matchups(
            self._make_season(entries, last_scored_leg=2), None
        )
        self.assertNotIn(2, posted)


class ZeroPointPastWeek(unittest.TestCase):
    """Regression for Codex PR #215 round-3 P2 (line 119): a matchup
    where one side legitimately scored 0 must still count toward
    current record once the week is provably in the past.
    """

    def _make_season(self, entries_by_week, last_scored_leg=None):
        class _Season:
            league_id = "L1"
            # The host clock is the canonical proof that admits a finished
            # week in which a roster genuinely scored 0.0
            # (metrics.final_regular_season_weeks).
            league = {"settings": {"last_scored_leg": last_scored_leg}}
            num_teams = 2
            matchups_by_week = entries_by_week

            @property
            def regular_season_weeks(self):
                return sorted(entries_by_week.keys())

        return _Season()

    def setUp(self) -> None:
        self._original = playoff_odds.metrics.resolve_owner
        playoff_odds.metrics.resolve_owner = (  # type: ignore[attr-defined]
            lambda reg, league_id, rid: f"owner-{rid}"
        )

    def tearDown(self) -> None:
        playoff_odds.metrics.resolve_owner = self._original  # type: ignore[attr-defined]

    def test_zero_point_game_in_past_week_counts(self) -> None:
        entries = {
            1: [
                {"roster_id": 1, "matchup_id": 10, "points": 110.0},
                {"roster_id": 2, "matchup_id": 10, "points": 0.0},
            ],
            2: [
                {"roster_id": 1, "matchup_id": 20, "points": 95.0},
                {"roster_id": 2, "matchup_id": 20, "points": 105.0},
            ],
        }
        rec = playoff_odds._regular_season_record_to_date(
            self._make_season(entries, last_scored_leg=2), None
        )
        # Owner-1: 1 win week 1, 1 loss week 2.
        self.assertEqual(rec["owner-1"]["wins"], 1)
        self.assertEqual(rec["owner-1"]["losses"], 1)
        # Owner-2: 1 loss week 1 (despite scoring 0), 1 win week 2.
        self.assertEqual(rec["owner-2"]["wins"], 1)
        self.assertEqual(rec["owner-2"]["losses"], 1)

    def test_zero_point_game_in_current_week_does_not_count(self) -> None:
        # Only week 1 in snapshot, half-scored.  No later weeks show
        # it as past, so the 0 could be either a real loss or a game
        # that hasn't been played.  Must not count.
        entries = {
            1: [
                {"roster_id": 1, "matchup_id": 10, "points": 110.0},
                {"roster_id": 2, "matchup_id": 10, "points": 0.0},
            ],
        }
        rec = playoff_odds._regular_season_record_to_date(
            self._make_season(entries, last_scored_leg=0), None
        )
        self.assertEqual(rec, {})


class TieHandling(unittest.TestCase):
    """Regression for Codex PR #215 round-3 P2 (line 414): exact-tie
    matchups must increment ties and sort correctly in standings.
    """

    def test_standings_rank_ties_above_losses(self) -> None:
        # 0-1-0 vs 0-0-1 — tier has 0.5 effective wins, loser 0.
        wins = {"loser": 0, "tier": 0}
        points = {"loser": 1000.0, "tier": 500.0}
        ties = {"loser": 0, "tier": 1}
        ordered = playoff_odds.standings_from_sim(wins, points, ["loser", "tier"], ties=ties)
        self.assertEqual(ordered, ["tier", "loser"])

    def test_standings_uses_pf_tiebreak_when_record_matches(self) -> None:
        wins = {"a": 5, "b": 5}
        points = {"a": 1500.0, "b": 1200.0}
        ties = {"a": 1, "b": 1}
        ordered = playoff_odds.standings_from_sim(wins, points, ["a", "b"], ties=ties)
        self.assertEqual(ordered, ["a", "b"])

    def test_record_counts_tied_matchup(self) -> None:
        original = playoff_odds.metrics.resolve_owner
        playoff_odds.metrics.resolve_owner = (  # type: ignore[attr-defined]
            lambda reg, league_id, rid: f"owner-{rid}"
        )

        class _Season:
            league_id = "L1"
            league = {"settings": {"last_scored_leg": 2}}
            num_teams = 2
            matchups_by_week = {
                1: [
                    {"roster_id": 1, "matchup_id": 10, "points": 100.0},
                    {"roster_id": 2, "matchup_id": 10, "points": 100.0},
                ],
                2: [
                    {"roster_id": 1, "matchup_id": 20, "points": 110.0},
                    {"roster_id": 2, "matchup_id": 20, "points": 95.0},
                ],
            }

            @property
            def regular_season_weeks(self):
                return [1, 2]

        try:
            rec = playoff_odds._regular_season_record_to_date(_Season(), None)
        finally:
            playoff_odds.metrics.resolve_owner = original  # type: ignore[attr-defined]

        self.assertEqual(rec["owner-1"]["ties"], 1)
        self.assertEqual(rec["owner-2"]["ties"], 1)
        self.assertEqual(rec["owner-1"]["wins"], 1)


class PreseasonState(unittest.TestCase):
    """Regression for Codex PR #215 round-4 P1: ``remaining_weeks == 0``
    with no weeks ever played must report preseason, not final.
    """

    def _make_preseason_snapshot(self):
        class _Season:
            season = "2027"
            league_id = "L_PRE"
            league = {"settings": {"playoff_teams": 6}}
            rosters = [{"roster_id": 1}, {"roster_id": 2}]
            matchups_by_week: dict = {}

            @property
            def regular_season_weeks(self):
                return []

        class _Manager:
            display_name = ""
            current_team_name = ""

        class _Registry:
            by_owner_id: dict = {}

        class _Snapshot:
            def __init__(self):
                self._s = _Season()
                self.managers = _Registry()

            @property
            def current_season(self):
                return self._s

        return _Snapshot()

    def test_preseason_returns_preseason_certainty_and_null_probs(self) -> None:
        original = playoff_odds.metrics.resolve_owner
        original_display = playoff_odds.metrics.display_name_for
        playoff_odds.metrics.resolve_owner = (  # type: ignore[attr-defined]
            lambda reg, league_id, rid: f"owner-{rid}"
        )
        playoff_odds.metrics.display_name_for = (  # type: ignore[attr-defined]
            lambda snapshot, owner_id: owner_id
        )
        try:
            result = playoff_odds.compute_playoff_odds(self._make_preseason_snapshot())
        finally:
            playoff_odds.metrics.resolve_owner = original  # type: ignore[attr-defined]
            playoff_odds.metrics.display_name_for = original_display  # type: ignore[attr-defined]

        self.assertEqual(result["scheduleCertainty"], "preseason")
        self.assertEqual(result["weeksPlayed"], 0)
        self.assertEqual(result["weeksRemaining"], 0)
        for owner in result["owners"]:
            # Critical: probabilities are None, NOT 0/1 from arbitrary
            # sort order.
            self.assertIsNone(owner["playoffProbability"])
            self.assertEqual(owner["currentWins"], 0)


class ZeroZeroPastWeek(unittest.TestCase):
    """Regression for Codex PR #215 round-4 P2 (line 134): a past-week
    matchup with both sides at 0 must be treated as a completed tie.
    """

    def test_zero_zero_in_past_week_counts_as_tie(self) -> None:
        class _Season:
            league_id = "L1"
            league = {"settings": {"last_scored_leg": 2}}
            num_teams = 2
            matchups_by_week = {
                1: [
                    {"roster_id": 1, "matchup_id": 10, "points": 0.0},
                    {"roster_id": 2, "matchup_id": 10, "points": 0.0},
                ],
                2: [
                    {"roster_id": 1, "matchup_id": 20, "points": 110.0},
                    {"roster_id": 2, "matchup_id": 20, "points": 95.0},
                ],
            }

            @property
            def regular_season_weeks(self):
                return [1, 2]

        original = playoff_odds.metrics.resolve_owner
        playoff_odds.metrics.resolve_owner = (  # type: ignore[attr-defined]
            lambda reg, league_id, rid: f"owner-{rid}"
        )
        try:
            rec = playoff_odds._regular_season_record_to_date(_Season(), None)
        finally:
            playoff_odds.metrics.resolve_owner = original  # type: ignore[attr-defined]

        self.assertEqual(rec["owner-1"]["ties"], 1)
        self.assertEqual(rec["owner-2"]["ties"], 1)
        self.assertEqual(rec["owner-1"]["wins"], 1)
        self.assertEqual(rec["owner-2"]["losses"], 1)


class CsvExportableKeys(unittest.TestCase):
    """Regression for Codex PR #215 round-4 P2 (public_contract line 82):
    lazy sections must not appear in the CSV allowlist.
    """

    def test_playoff_odds_absent_from_csv_allowlist(self) -> None:
        from src.public_league.public_contract import (
            PUBLIC_CSV_EXPORTABLE_KEYS,
            PUBLIC_SECTION_KEYS,
        )

        self.assertNotIn("playoffOdds", PUBLIC_CSV_EXPORTABLE_KEYS)
        # But the full section-keys list MUST still advertise it —
        # playoffOdds IS available via the single-section JSON endpoint.
        self.assertIn("playoffOdds", PUBLIC_SECTION_KEYS)


class LazySectionRouting(unittest.TestCase):
    """Regression for Codex PR #215 P2: ``playoffOdds`` must not be
    invoked as part of the aggregate ``build_public_contract`` walk
    (which would run a 10K-sim MC on every public-contract load)."""

    def test_playoff_odds_not_in_aggregate_builders(self) -> None:
        from src.public_league import public_contract

        self.assertNotIn("playoffOdds", public_contract._SECTION_BUILDERS)
        self.assertIn("playoffOdds", public_contract._LAZY_SECTION_BUILDERS)
        self.assertIn("playoffOdds", public_contract.PUBLIC_SECTION_KEYS)


class UnpostedWeeksAreLabelledNotInvented(unittest.TestCase):
    """The retired engine filled un-posted weeks with a cycle-inferred or
    round-robin schedule. The canonical engine simulates POSTED weeks only,
    so the section must say so (``posted_weeks_only`` + ``unpostedWeeks``)
    rather than keep the old labels for work nobody does any more.
    """

    @staticmethod
    def _pair_row(matchup_id: int, roster_id: int, points: float = 0.0) -> dict:
        return {"roster_id": roster_id, "matchup_id": matchup_id, "points": points}

    def test_unposted_weeks_are_reported_and_odds_are_the_engines(self) -> None:
        entries = {
            1: [
                self._pair_row(10, 1, 120.0),
                self._pair_row(10, 2, 110.0),
                self._pair_row(11, 3, 95.0),
                self._pair_row(11, 4, 105.0),
            ],
            2: [
                self._pair_row(20, 1, 130.0),
                self._pair_row(20, 3, 115.0),
                self._pair_row(21, 2, 140.0),
                self._pair_row(21, 4, 98.0),
            ],
            3: [
                self._pair_row(30, 1, 125.0),
                self._pair_row(30, 4, 108.0),
                self._pair_row(31, 2, 133.0),
                self._pair_row(31, 3, 112.0),
            ],
            4: [
                self._pair_row(40, 1, 118.0),
                self._pair_row(40, 2, 111.0),
                self._pair_row(41, 3, 97.0),
                self._pair_row(41, 4, 101.0),
            ],
        }
        for wk in range(5, 15):
            entries[wk] = []

        class _Season:
            season = "2026"
            league_id = "L1"
            league = {"settings": {"playoff_week_start": 15, "playoff_teams": 2}}
            rosters = [{"roster_id": r} for r in (1, 2, 3, 4)]
            # Read by the canonical finished-week gate
            # (``metrics.final_regular_season_weeks``) that the score
            # distributions now consume.
            num_teams = 4
            matchups_by_week = entries

            @property
            def regular_season_weeks(self):
                return sorted(w for w in entries if w < 15)

        class _Registry:
            by_owner_id: dict = {}

        class _Snapshot:
            def __init__(self) -> None:
                self._s = _Season()
                self.managers = _Registry()

            @property
            def current_season(self):
                return self._s

        orig_display = playoff_odds.metrics.display_name_for
        playoff_odds.metrics.display_name_for = (  # type: ignore[attr-defined]
            lambda snapshot, owner_id: owner_id
        )
        orig_resolve = playoff_odds.metrics.resolve_owner
        playoff_odds.metrics.resolve_owner = (  # type: ignore[attr-defined]
            lambda reg, league_id, rid: f"owner-{rid}"
        )
        forecast = {
            "n_simulations": 4000,
            "playoffOdds": [
                {"ownerId": f"owner-{r}", "playoffOdds": p}
                for r, p in ((1, 0.91), (2, 0.62), (3, 0.08), (4, 0.39))
            ],
        }
        try:
            result = playoff_odds.compute_playoff_odds(_Snapshot(), forecast=forecast)
        finally:
            playoff_odds.metrics.display_name_for = orig_display  # type: ignore[attr-defined]
            playoff_odds.metrics.resolve_owner = orig_resolve  # type: ignore[attr-defined]

        self.assertEqual(result["scheduleCertainty"], playoff_odds.CERTAINTY_POSTED_WEEKS_ONLY)
        self.assertEqual(result["unpostedWeeks"], list(range(5, 15)))
        self.assertEqual(result["weeksPlayed"], 4)
        self.assertEqual(result["numSims"], 4000)
        # The numbers are the engine's, owner for owner.
        self.assertEqual(
            {o["ownerId"]: o["playoffProbability"] for o in result["owners"]},
            {f"owner-{r}": p for r, p in ((1, 0.91), (2, 0.62), (3, 0.08), (4, 0.39))},
        )
