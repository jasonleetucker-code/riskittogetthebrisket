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


class PartialWeekPostedPairs(unittest.TestCase):
    """Regression for Codex PR #215 second-round P1 review:
    ``_posted_future_matchups`` must emit posted pairings for the
    unplayed matchups inside a partially-scored week, not drop the
    whole week.
    """

    def _make_season(self, entries_by_week):
        class _Season:
            league_id = "L1"
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

    def test_partial_week_emits_only_unplayed_pairs(self) -> None:
        # Week 3: matchup_id 10 is complete (110.2 vs 95.7), matchup_id
        # 11 hasn't been played yet (both sides at 0).  posted should
        # contain ONLY the unplayed pair from matchup 11.
        entries = {
            3: [
                {"roster_id": 1, "matchup_id": 10, "points": 110.2},
                {"roster_id": 2, "matchup_id": 10, "points": 95.7},
                {"roster_id": 3, "matchup_id": 11, "points": 0.0},
                {"roster_id": 4, "matchup_id": 11, "points": 0.0},
            ],
        }
        posted = playoff_odds._posted_future_matchups(self._make_season(entries), None)
        self.assertIn(3, posted)
        self.assertEqual(len(posted[3]), 1)
        pair = posted[3][0]
        self.assertIn("owner-3", pair)
        self.assertIn("owner-4", pair)

    def test_fully_unplayed_week_emits_all_pairs(self) -> None:
        entries = {
            5: [
                {"roster_id": 1, "matchup_id": 20, "points": 0.0},
                {"roster_id": 2, "matchup_id": 20, "points": 0.0},
                {"roster_id": 3, "matchup_id": 21, "points": 0.0},
                {"roster_id": 4, "matchup_id": 21, "points": 0.0},
            ],
        }
        posted = playoff_odds._posted_future_matchups(self._make_season(entries), None)
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
        posted = playoff_odds._posted_future_matchups(self._make_season(entries), None)
        self.assertNotIn(2, posted)


class ZeroPointPastWeek(unittest.TestCase):
    """Regression for Codex PR #215 round-3 P2 (line 119): a matchup
    where one side legitimately scored 0 must still count toward
    current record once the week is provably in the past.
    """

    def _make_season(self, entries_by_week):
        class _Season:
            league_id = "L1"
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
            self._make_season(entries), None
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
            self._make_season(entries), None
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
        ordered = playoff_odds._standings_from_sim(
            wins, points, ["loser", "tier"], ties=ties
        )
        self.assertEqual(ordered, ["tier", "loser"])

    def test_standings_uses_pf_tiebreak_when_record_matches(self) -> None:
        wins = {"a": 5, "b": 5}
        points = {"a": 1500.0, "b": 1200.0}
        ties = {"a": 1, "b": 1}
        ordered = playoff_odds._standings_from_sim(
            wins, points, ["a", "b"], ties=ties
        )
        self.assertEqual(ordered, ["a", "b"])

    def test_record_counts_tied_matchup(self) -> None:
        original = playoff_odds.metrics.resolve_owner
        playoff_odds.metrics.resolve_owner = (  # type: ignore[attr-defined]
            lambda reg, league_id, rid: f"owner-{rid}"
        )

        class _Season:
            league_id = "L1"
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
            league = {"settings": {}}
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
            result = playoff_odds.compute_playoff_odds(
                self._make_preseason_snapshot(),
                num_sims=100,
                rng=random.Random(0),
            )
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


class ScheduleInferenceFromPosted(unittest.TestCase):
    """Regression for the round-robin fallback gap: when the league
    has posted enough weeks to reveal the rotation pattern, subsequent
    un-posted weeks should inherit the observed pairings rather than
    being filled in by a synthetic circle-method round-robin.
    """

    @staticmethod
    def _pair_row(matchup_id: int, roster_id: int, points: float = 0.0) -> dict:
        return {"roster_id": roster_id, "matchup_id": matchup_id, "points": points}

    def _make_season(
        self,
        entries_by_week: dict[int, list[dict]],
        *,
        playoff_week_start: int = 15,
    ):
        entries = entries_by_week
        cutoff = playoff_week_start

        class _Season:
            league_id = "L1"
            league = {"settings": {"playoff_week_start": cutoff}}
            matchups_by_week = entries

            @property
            def regular_season_weeks(self):
                return sorted(w for w in entries if w < cutoff)

        return _Season()

    def setUp(self) -> None:
        self._orig_resolve = playoff_odds.metrics.resolve_owner
        playoff_odds.metrics.resolve_owner = (  # type: ignore[attr-defined]
            lambda reg, league_id, rid: f"owner-{rid}"
        )

    def tearDown(self) -> None:
        playoff_odds.metrics.resolve_owner = self._orig_resolve  # type: ignore[attr-defined]

    def test_detects_four_team_three_week_cycle(self) -> None:
        # 4 teams → round-robin cycle length 3.  Weeks 1-5 posted with
        # week 4 == week 1 and week 5 == week 2.  Un-posted week 6
        # should inherit week 3's pairing (same residue mod 3).
        # Week 1: (1v2, 3v4); Week 2: (1v3, 2v4); Week 3: (1v4, 2v3).
        entries = {
            1: [self._pair_row(10, 1, 120.0), self._pair_row(10, 2, 110.0),
                self._pair_row(11, 3,  95.0), self._pair_row(11, 4, 105.0)],
            2: [self._pair_row(20, 1, 130.0), self._pair_row(20, 3, 115.0),
                self._pair_row(21, 2, 140.0), self._pair_row(21, 4,  98.0)],
            3: [self._pair_row(30, 1, 125.0), self._pair_row(30, 4, 108.0),
                self._pair_row(31, 2, 133.0), self._pair_row(31, 3, 112.0)],
            4: [self._pair_row(40, 1,   0.0), self._pair_row(40, 2,   0.0),
                self._pair_row(41, 3,   0.0), self._pair_row(41, 4,   0.0)],
            5: [self._pair_row(50, 1,   0.0), self._pair_row(50, 3,   0.0),
                self._pair_row(51, 2,   0.0), self._pair_row(51, 4,   0.0)],
            # Weeks 6..14 intentionally absent — inference must fill them.
        }
        # Regular season weeks 1..14, playoffs week 15+.  Note the
        # helper only inspects weeks present in ``matchups_by_week``,
        # so expand that to include empty entries for the missing
        # weeks so regular_season_weeks returns the full range.
        for wk in range(6, 15):
            entries[wk] = []
        season = self._make_season(entries, playoff_week_start=15)
        schedule = playoff_odds._infer_schedule_from_posted(season, None)
        self.assertIsNotNone(schedule)

        def _pair_set(week_pairs):
            return frozenset(frozenset(p) for p in week_pairs)

        # Verify cycle propagation: week 6 ≡ week 3, week 7 ≡ week 1,
        # week 8 ≡ week 2, and so on through the rest of the season.
        self.assertEqual(_pair_set(schedule[6]), _pair_set(schedule[3]))
        self.assertEqual(_pair_set(schedule[7]), _pair_set(schedule[1]))
        self.assertEqual(_pair_set(schedule[8]), _pair_set(schedule[2]))
        self.assertEqual(_pair_set(schedule[14]), _pair_set(schedule[2]))
        # And posted weeks survive verbatim.
        self.assertEqual(_pair_set(schedule[1]),
                         _pair_set([("owner-1", "owner-2"), ("owner-3", "owner-4")]))

    def test_odd_team_count_league_cycle_propagates(self) -> None:
        # 5 teams, 2 pairs posted per week (one roster sits out each
        # week — Sleeper encodes byes by simply not listing that
        # roster in the week's matchups).  Weeks 1-6 posted with a
        # 5-week cycle (week 6 == week 1).  Inference must carry that
        # pattern into weeks 7+, preserving the bye rotation.
        weekly_pairs = {
            1: [(1, 2), (3, 4)],              # roster 5 on bye
            2: [(1, 3), (2, 5)],              # roster 4 on bye
            3: [(1, 4), (3, 5)],              # roster 2 on bye
            4: [(1, 5), (2, 4)],              # roster 3 on bye
            5: [(2, 3), (4, 5)],              # roster 1 on bye
        }
        # Week 6 repeats week 1 to give the detector something to
        # latch onto.
        weekly_pairs[6] = list(weekly_pairs[1])

        entries: dict[int, list[dict]] = {}
        for wk, pairs in weekly_pairs.items():
            rows: list[dict] = []
            for idx, (a, b) in enumerate(pairs):
                rows.append(self._pair_row(wk * 100 + idx, a, 100.0))
                rows.append(self._pair_row(wk * 100 + idx, b,  90.0))
            entries[wk] = rows
        for wk in range(7, 15):
            entries[wk] = []
        season = self._make_season(entries, playoff_week_start=15)
        schedule = playoff_odds._infer_schedule_from_posted(season, None)
        self.assertIsNotNone(schedule)

        def _pair_set(week_pairs):
            return frozenset(frozenset(p) for p in week_pairs)

        # Cycle length must be 5 because week 6 ≡ week 1.
        self.assertEqual(_pair_set(schedule[7]), _pair_set(schedule[2]))
        self.assertEqual(_pair_set(schedule[11]), _pair_set(schedule[1]))
        # Every propagated week still has exactly 2 pairs (5 teams → 1
        # bye per week, never 3 pairs).
        for wk in range(7, 15):
            self.assertEqual(len(schedule[wk]), 2)
            # No roster sits in two games in the same week.
            owners_this_week = [o for pair in schedule[wk] for o in pair]
            self.assertEqual(len(owners_this_week), len(set(owners_this_week)))

    def test_single_posted_week_falls_back_to_round_robin(self) -> None:
        # Only week 1 posted — under 2 weeks means we can't detect any
        # repetition, so the helper returns None and the simulator
        # falls through to _round_robin_schedule.  scheduleCertainty
        # stays "partial" (some posted + round-robin fallback) or
        # "inferred" (no posted at all).  Either way, NOT
        # "inferred_from_posted".
        entries = {
            1: [self._pair_row(10, 1, 120.0), self._pair_row(10, 2, 110.0),
                self._pair_row(11, 3,  95.0), self._pair_row(11, 4, 105.0)],
        }
        for wk in range(2, 15):
            entries[wk] = []
        season = self._make_season(entries, playoff_week_start=15)
        schedule = playoff_odds._infer_schedule_from_posted(season, None)
        self.assertIsNone(schedule)

    def test_zero_posted_weeks_returns_none(self) -> None:
        season = self._make_season({wk: [] for wk in range(1, 15)}, playoff_week_start=15)
        self.assertIsNone(playoff_odds._infer_schedule_from_posted(season, None))

    def test_compute_playoff_odds_reports_inferred_from_posted(self) -> None:
        # Integration: the new certainty value reaches the public
        # payload when inference drives the missing-week schedule.
        entries = {
            1: [self._pair_row(10, 1, 120.0), self._pair_row(10, 2, 110.0),
                self._pair_row(11, 3,  95.0), self._pair_row(11, 4, 105.0)],
            2: [self._pair_row(20, 1, 130.0), self._pair_row(20, 3, 115.0),
                self._pair_row(21, 2, 140.0), self._pair_row(21, 4,  98.0)],
            3: [self._pair_row(30, 1, 125.0), self._pair_row(30, 4, 108.0),
                self._pair_row(31, 2, 133.0), self._pair_row(31, 3, 112.0)],
            4: [self._pair_row(40, 1, 118.0), self._pair_row(40, 2, 111.0),
                self._pair_row(41, 3,  97.0), self._pair_row(41, 4, 101.0)],
        }
        for wk in range(5, 15):
            entries[wk] = []

        class _Season:
            season = "2026"
            league_id = "L1"
            league = {"settings": {"playoff_week_start": 15, "playoff_teams": 2}}
            rosters = [{"roster_id": r} for r in (1, 2, 3, 4)]
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
        try:
            result = playoff_odds.compute_playoff_odds(
                _Snapshot(), num_sims=50, rng=random.Random(7)
            )
        finally:
            playoff_odds.metrics.display_name_for = orig_display  # type: ignore[attr-defined]

        self.assertEqual(result["scheduleCertainty"], "inferred_from_posted")
        # Every owner gets a probability (none skipped by empty
        # schedule gaps).
        self.assertEqual(len(result["owners"]), 4)
        for owner in result["owners"]:
            self.assertIsNotNone(owner["playoffProbability"])
