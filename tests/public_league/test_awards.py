"""Tests for the reworked awards engine.

Covers the 2026 rework: removed awards, season-scoped (no date
cutoff) trader/waiver, starting-lineup-only Waiver King, champion-only
Playoff MVP, the weighted Manager of the Year, Off/Def Rookie of the
Year, Mr. Consistent, and canonical award ordering.
"""
from __future__ import annotations

import copy
import unittest
import contextlib

from src.public_league import awards
from src.public_league.awards import (
    AWARD_DESCRIPTIONS,
    _bad_beat_scores,
    _manager_of_the_year_scores,
    _manager_unit_points,
    _mr_consistent_scores,
    _order_awards,
    _playoff_mvp_player_rows,
    _rivalry_of_the_year,
    _rookie_of_year_rows,
    _is_rookie_in_season,
    _snapshot_anchor_year,
    _silent_assassin_scores,
    _starter_scoring_walk,
    _top_nfl_team_scores,
    _trader_of_the_year_scores,
    _vorp_rows,
    _vorp_starter_slots,
    _waiver_king_scores,
    _weekly_hammer_scores,
    _best_rebuild_scores,
    _OFF_ROY_POSITIONS,
    _DEF_ROY_POSITIONS,
    _TOP_OFFENSE_POSITIONS,
    _DEFENSIVE_POSITIONS,
    _VORP_FIXED_STARTER_SLOTS,
    _FLEX_RBWR_POOL,
)
from src.public_league.public_contract import assert_public_payload_safe, build_public_contract

from tests.public_league.fixtures import build_test_snapshot


# Transaction awards are season-scoped (no date cutoff), like every
# other award.  This null context keeps the historical call sites
# readable without rewriting each one.
_NO_CUTOFF = contextlib.nullcontext()

_REMOVED_KEYS = {
    "chaos_agent", "most_active", "pick_hoarder",
    "runner_up", "points_black_hole", "toilet_bowl",
}


def _with_player_points(snapshot):
    """Deep-copy snapshot with rich players_points / starters stamps."""
    snap = copy.deepcopy(snapshot)

    def _stamp(entry, players_points, starters=None):
        entry["players_points"] = players_points
        if starters is not None:
            entry["starters"] = starters

    s2025 = snap.seasons[0]
    for wk, per_rid in {
        1: {
            1: ({"p-qb1": 40.0, "p-rb1": 30.0, "p-wr1": 20.0, "p-te1": 15.0, "p-rookie-a": 15.5}, ["p-qb1", "p-rb1", "p-wr1", "p-te1", "p-rookie-a"]),
            2: ({"p-qb2": 45.0, "p-rb3": 35.0, "p-wr2": 25.0, "p-te1": 15.0, "p-rookie-b": 15.2}, ["p-qb2", "p-rb3", "p-wr2", "p-te1", "p-rookie-b"]),
            3: ({"p-wr1": 20.0, "p-wr2": 20.0, "p-wr3": 15.0, "p-rb1": 20.0, "p-qb1": 20.0}, ["p-wr1", "p-wr2", "p-wr3", "p-rb1", "p-qb1"]),
            4: ({"p-te1": 15.0, "p-te2": 20.0, "p-idp1": 15.0, "p-idp2": 20.0, "p-idp3": 25.0, "p-qb2": 15.3}, ["p-te1", "p-te2", "p-idp1", "p-idp2", "p-idp3", "p-qb2"]),
        },
        2: {
            1: ({"p-qb1": 40.0, "p-rb1": 35.0, "p-wr1": 25.8, "p-te1": 20.0, "p-rookie-a": 25.0}, ["p-qb1", "p-rb1", "p-wr1", "p-te1", "p-rookie-a"]),
            3: ({"p-wr1": 25.0, "p-wr2": 25.0, "p-wr3": 30.0, "p-rb1": 32.1, "p-qb1": 30.0}, ["p-wr1", "p-wr2", "p-wr3", "p-rb1", "p-qb1"]),
            2: ({"p-qb2": 50.0, "p-rb2": 40.0, "p-wr2": 35.0, "p-te1": 20.0, "p-rookie-b": 20.0}, ["p-qb2", "p-rb2", "p-wr2", "p-te1", "p-rookie-b"]),
            4: ({"p-te1": 15.0, "p-te2": 20.0, "p-idp1": 15.0, "p-idp2": 15.0, "p-idp3": 15.0, "p-qb2": 15.6}, ["p-te1", "p-te2", "p-idp1", "p-idp2", "p-idp3", "p-qb2"]),
        },
        15: {
            2: ({"p-rb2": 55.5, "p-wr2": 35.0, "p-qb2": 40.0, "p-te1": 15.0, "p-rookie-b": 10.0}, ["p-rb2", "p-wr2", "p-qb2", "p-te1", "p-rookie-b"]),
            4: ({"p-te1": 15.0, "p-te2": 30.0, "p-idp1": 30.0, "p-idp2": 25.0, "p-idp3": 20.0, "p-qb2": 10.0}, ["p-te1", "p-te2", "p-idp1", "p-idp2", "p-idp3", "p-qb2"]),
            1: ({"p-qb1": 40.0, "p-rb1": 30.0, "p-wr1": 35.0, "p-te1": 20.0, "p-rookie-a": 25.0}, ["p-qb1", "p-rb1", "p-wr1", "p-te1", "p-rookie-a"]),
            3: ({"p-wr1": 40.0, "p-wr2": 30.0, "p-wr3": 25.0, "p-rb1": 25.0, "p-qb1": 20.0}, ["p-wr1", "p-wr2", "p-wr3", "p-rb1", "p-qb1"]),
        },
        16: {
            2: ({"p-rb2": 50.0, "p-wr2": 30.0, "p-qb2": 35.0, "p-te1": 15.0, "p-rookie-b": 15.0}, ["p-rb2", "p-wr2", "p-qb2", "p-te1", "p-rookie-b"]),
            1: ({"p-qb1": 30.0, "p-rb1": 25.0, "p-wr1": 25.0, "p-te1": 15.0, "p-rookie-a": 25.0}, ["p-qb1", "p-rb1", "p-wr1", "p-te1", "p-rookie-a"]),
        },
    }.items():
        for e in s2025.matchups_by_week.get(wk, []):
            rid = int(e.get("roster_id"))
            if rid in per_rid:
                pp, st = per_rid[rid]
                _stamp(e, pp, starters=st)

    s2024 = snap.seasons[1]
    for wk in s2024.matchups_by_week.keys():
        for entry in s2024.matchups_by_week[wk]:
            total = entry.get("points") or 0.0
            pp = {"p-te1": round(float(total) / 2, 2), "p-wr1": round(float(total) / 2, 2)}
            _stamp(entry, pp, starters=["p-te1", "p-wr1"])
    return snap


class AwardDescriptionsTests(unittest.TestCase):
    def test_active_awards_have_descriptions(self) -> None:
        for key in (
            "champion", "manager_of_the_year", "trader_of_the_year",
            "best_trade_of_the_year", "waiver_king", "silent_assassin",
            "weekly_hammer", "playoff_mvp", "bad_beat", "mr_consistent",
            "best_rebuild", "rivalry_of_the_year", "off_roy", "def_roy",
            "league_mvp", "top_qb", "top_offense", "top_defense",
        ):
            self.assertIn(key, AWARD_DESCRIPTIONS)
            self.assertTrue(AWARD_DESCRIPTIONS[key])

    def test_removed_awards_have_no_description(self) -> None:
        for key in _REMOVED_KEYS:
            self.assertNotIn(key, AWARD_DESCRIPTIONS)


class SeasonScopedTransactionTests(unittest.TestCase):
    """Trader / Best Trade / Waiver King are bounded by their Sleeper
    season — no date cutoff, consistent with every other award."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_season_transactions_count(self) -> None:
        rows, best = _trader_of_the_year_scores(self.snapshot, self.snapshot.seasons[0])
        self.assertTrue(rows)
        self.assertIsNotNone(best)
        self.assertTrue(_waiver_king_scores(self.snapshot, self.snapshot.seasons[0]))

    def test_section_includes_trader_waiver_for_season_with_txns(self) -> None:
        section = awards.build_section(self.snapshot)
        by_year = {s["season"]: {a["key"] for a in s["awards"]}
                   for s in section["bySeason"]}
        k2025 = by_year.get("2025", set())
        self.assertIn("trader_of_the_year", k2025)
        self.assertIn("waiver_king", k2025)
        self.assertIn("best_trade_of_the_year", k2025)


class TraderAndBestTradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_trader_rows_sort_by_points_gained(self) -> None:
        with _NO_CUTOFF:
            rows, _ = _trader_of_the_year_scores(self.snapshot, self.snapshot.seasons[0])
        self.assertTrue(rows)
        for a, b in zip(rows, rows[1:]):
            self.assertGreaterEqual(a["pointsGained"], b["pointsGained"])
        for r in rows:
            self.assertTrue(r["displayName"])

    def test_best_trade_is_four_tuple_with_tx(self) -> None:
        with _NO_CUTOFF:
            _, best = _trader_of_the_year_scores(self.snapshot, self.snapshot.seasons[0])
        self.assertIsNotNone(best)
        gain, owner_id, payload, tx = best
        self.assertIn(owner_id, {"owner-A", "owner-B"})
        self.assertIn("transactionId", payload)
        self.assertEqual(tx.get("type"), "trade")

    def test_best_trade_award_carries_full_trade_detail(self) -> None:
        with _NO_CUTOFF:
            section = awards.build_section(self.snapshot)
        found = None
        for season_row in section["bySeason"]:
            for a in season_row["awards"]:
                if a["key"] == "best_trade_of_the_year":
                    found = a
        self.assertIsNotNone(found)
        trade = found["value"].get("trade")
        self.assertIsNotNone(trade)
        self.assertIn("sides", trade)
        self.assertGreaterEqual(len(trade["sides"]), 2)
        self.assertIn("receivedAssets", trade["sides"][0])


class WaiverKingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_value_shape_has_no_faab(self) -> None:
        with _NO_CUTOFF:
            rows = _waiver_king_scores(self.snapshot, self.snapshot.seasons[0])
        self.assertTrue(rows)
        for r in rows:
            self.assertIn("pointsGained", r)
            self.assertIn("usefulAdds", r)
            self.assertNotIn("faabEfficiency", r)
            self.assertNotIn("faabSpent", r)

    def test_only_started_weeks_count(self) -> None:
        # wv-2025-a adds p-wr3 to roster 3 at leg 1.  Post-add weeks are
        # >1: roster 3 starts p-wr3 in wk2 (30.0) and wk15 (25.0) only —
        # week 1 is pre-add and bench weeks never count → exactly 55.0.
        with _NO_CUTOFF:
            rows = _waiver_king_scores(self.snapshot, self.snapshot.seasons[0])
        cole = next((r for r in rows if r["ownerId"] == "owner-C"), None)
        self.assertIsNotNone(cole)
        self.assertEqual(cole["pointsGained"], 55.0)
        self.assertEqual(cole["usefulAdds"], 1)


class SilentAssassinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_min_eligible_gate(self) -> None:
        rows = _silent_assassin_scores(self.snapshot, self.snapshot.seasons[0], min_eligible=4)
        for r in rows:
            if r["eligible"]:
                self.assertGreaterEqual(r["closeGames"], 4)

    def test_close_games_only_count_under_ten(self) -> None:
        rows = _silent_assassin_scores(self.snapshot, self.snapshot.seasons[0], min_eligible=1)
        for r in rows:
            self.assertLessEqual(r["avgCloseMargin"], 10.0 + 1e-6)


class WeeklyHammerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_high_score_finishes_count(self) -> None:
        rows = _weekly_hammer_scores(self.snapshot, self.snapshot.seasons[0])
        by_owner = {r["ownerId"]: r for r in rows}
        self.assertEqual(by_owner["owner-B"]["highScoreFinishes"], 2)
        for owner_id, r in by_owner.items():
            if owner_id != "owner-B":
                self.assertLessEqual(r["highScoreFinishes"], 1)


class PlayoffMvpChampionOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_only_champion_roster_players(self) -> None:
        # 2025 champion = roster 2 (owner-B).  Every candidate must
        # attribute to owner-B.
        rows = _playoff_mvp_player_rows(self.snapshot, self.snapshot.seasons[0])
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["ownerId"], "owner-B")
        # Sorted by VORP desc.
        for a, b in zip(rows, rows[1:]):
            self.assertGreaterEqual(a["vorp"], b["vorp"])

    def test_no_champion_returns_empty(self) -> None:
        snap = copy.deepcopy(self.snapshot)
        snap.seasons[0].winners_bracket = []
        self.assertEqual(_playoff_mvp_player_rows(snap, snap.seasons[0]), [])


class TopOffenseExcludesKickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_offense_defense_partition_matches_position_sets(self) -> None:
        season = self.snapshot.seasons[0]
        units = _manager_unit_points(self.snapshot, season, regular_season_only=True)
        expected: dict[str, dict[str, float]] = {}
        for _wk, _rid, owner_id, _pid, pos, pts, _is_p in _starter_scoring_walk(
            self.snapshot, season, regular_season_only=True
        ):
            rec = expected.setdefault(owner_id, {"offense": 0.0, "defense": 0.0})
            if pos in _TOP_OFFENSE_POSITIONS:
                rec["offense"] += pts
            elif pos in _DEFENSIVE_POSITIONS:
                rec["defense"] += pts
            # K / unmapped contribute to neither.
        for owner_id, rec in units.items():
            self.assertAlmostEqual(rec["offense"], expected[owner_id]["offense"], places=2)
            self.assertAlmostEqual(rec["defense"], expected[owner_id]["defense"], places=2)

    def test_kicker_excluded_from_offense_and_off_roy(self) -> None:
        self.assertNotIn("K", _TOP_OFFENSE_POSITIONS)
        self.assertNotIn("K", _OFF_ROY_POSITIONS)


class ManagerOfTheYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_composite_in_unit_range_and_sorted(self) -> None:
        with _NO_CUTOFF:
            trader_rows, _ = _trader_of_the_year_scores(self.snapshot, self.snapshot.seasons[0])
            waiver_rows = _waiver_king_scores(self.snapshot, self.snapshot.seasons[0])
            rows = _manager_of_the_year_scores(
                self.snapshot, self.snapshot.seasons[0], trader_rows, waiver_rows
            )
        self.assertTrue(rows)
        for r in rows:
            self.assertGreaterEqual(r["compositeScore"], 0.0)
            self.assertLessEqual(r["compositeScore"], 1.0)
            self.assertIn("finishRank", r)
            self.assertIn("tradePointsGained", r)
            self.assertIn("waiverPointsGained", r)
        for a, b in zip(rows, rows[1:]):
            self.assertGreaterEqual(a["compositeScore"], b["compositeScore"])

    def test_champion_has_best_finish_rank(self) -> None:
        rows = _manager_of_the_year_scores(
            self.snapshot, self.snapshot.seasons[0], [], []
        )
        by_owner = {r["ownerId"]: r for r in rows}
        # 2025 champion = owner-B → finishRank 1.
        self.assertEqual(by_owner["owner-B"]["finishRank"], 1)


class RookieOfTheYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_off_roy_only_offensive_rookies(self) -> None:
        rows = _rookie_of_year_rows(
            self.snapshot, self.snapshot.seasons[0], _OFF_ROY_POSITIONS
        )
        for r in rows:
            self.assertIn(r["position"], _OFF_ROY_POSITIONS)
            meta = self.snapshot.nfl_players.get(r["playerId"]) or {}
            self.assertEqual(int(meta.get("years_exp")), 0)

    def test_def_roy_only_defensive_rookies(self) -> None:
        rows = _rookie_of_year_rows(
            self.snapshot, self.snapshot.seasons[0], _DEF_ROY_POSITIONS
        )
        for r in rows:
            self.assertIn(r["position"], _DEF_ROY_POSITIONS)
            meta = self.snapshot.nfl_players.get(r["playerId"]) or {}
            self.assertEqual(int(meta.get("years_exp")), 0)

    def test_anchor_year_is_newest_season(self) -> None:
        # Fixture seasons are [2025, 2024]; current_season -> 2025.
        self.assertEqual(_snapshot_anchor_year(self.snapshot), 2025)

    def test_rookie_detection_is_season_relative(self) -> None:
        s2025, s2024 = self.snapshot.seasons[0], self.snapshot.seasons[1]
        # p-rb2 years_exp=0 -> rookie in 2025 (anchor), NOT in 2024.
        self.assertTrue(_is_rookie_in_season(self.snapshot, "p-rb2", s2025))
        self.assertFalse(_is_rookie_in_season(self.snapshot, "p-rb2", s2024))
        # p-te2 years_exp=1 -> rookie in 2024 (1 == 2025-2024), NOT 2025.
        # This is the bug fix: past-season ROY was previously impossible.
        self.assertTrue(_is_rookie_in_season(self.snapshot, "p-te2", s2024))
        self.assertFalse(_is_rookie_in_season(self.snapshot, "p-te2", s2025))
        # Veteran (years_exp=5) is a rookie in no tracked season.
        self.assertFalse(_is_rookie_in_season(self.snapshot, "p-qb1", s2025))
        self.assertFalse(_is_rookie_in_season(self.snapshot, "p-qb1", s2024))
        # Unknown player / missing years_exp -> not a rookie (guarded).
        self.assertFalse(_is_rookie_in_season(self.snapshot, "p-nope", s2025))


class MrConsistentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_sorted_ascending_cv_and_nonnegative(self) -> None:
        rows = _mr_consistent_scores(self.snapshot, self.snapshot.seasons[0], min_weeks=1)
        self.assertTrue(rows)
        for r in rows:
            self.assertGreaterEqual(r["cv"], 0.0)
            self.assertGreater(r["meanScore"], 0.0)
        for a, b in zip(rows, rows[1:]):
            self.assertLessEqual(a["cv"], b["cv"])


class BadBeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_points_in_loss_only(self) -> None:
        rows = _bad_beat_scores(self.snapshot, self.snapshot.seasons[0])
        by_owner = {r["ownerId"]: r for r in rows}
        self.assertAlmostEqual(by_owner["owner-C"]["biggestLoss"], 142.1, places=1)


class BestRebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_composite_populated_for_known_owners(self) -> None:
        rows = _best_rebuild_scores(
            self.snapshot, self.snapshot.seasons[0], self.snapshot.seasons[1]
        )
        owners = {r["ownerId"] for r in rows}
        self.assertEqual(owners, {"owner-A", "owner-B", "owner-C"})


class RivalryOfTheYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_rivalry_has_playoff_boost(self) -> None:
        r = _rivalry_of_the_year(self.snapshot, self.snapshot.seasons[0])
        self.assertIsNotNone(r)
        self.assertIn("rivalryIndex", r)
        self.assertEqual(sorted(r["ownerIds"]), sorted(["owner-A", "owner-C"]))


class VorpFloorAndSlotsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_no_negative_vorp_regular_season(self) -> None:
        rows = _vorp_rows(self.snapshot, self.snapshot.seasons[0], regular_season_only=True)
        self.assertTrue(rows)
        for r in rows:
            self.assertGreaterEqual(r["vorp"], 0.0)

    def test_no_negative_vorp_playoffs(self) -> None:
        rows = _playoff_mvp_player_rows(self.snapshot, self.snapshot.seasons[0])
        for r in rows:
            self.assertGreaterEqual(r["vorp"], 0.0)

    def test_fixed_slots_exact(self) -> None:
        slots = _vorp_starter_slots({})
        self.assertEqual(slots["QB"], 24)
        self.assertEqual(slots["TE"], 24)
        self.assertEqual(slots["K"], 12)
        self.assertEqual(slots["DL"], 36)
        self.assertEqual(slots["LB"], 36)
        self.assertEqual(slots["DB"], 36)
        self.assertEqual(_VORP_FIXED_STARTER_SLOTS["QB"], 24)

    def test_rbwr_split_from_top_84(self) -> None:
        rb = [{"position": "RB", "starterPoints": float(200 - i)} for i in range(60)]
        wr = [{"position": "WR", "starterPoints": float(150 - i)} for i in range(60)]
        slots = _vorp_starter_slots({"RB": rb, "WR": wr})
        # 120 RB+WR total → top 84 by points splits into RB+WR == 84.
        self.assertEqual(slots["RB"] + slots["WR"], _FLEX_RBWR_POOL)
        self.assertGreater(slots["RB"], 0)
        self.assertGreater(slots["WR"], 0)

    def test_rbwr_split_smaller_than_pool(self) -> None:
        rb = [{"position": "RB", "starterPoints": 50.0} for _ in range(10)]
        wr = [{"position": "WR", "starterPoints": 40.0} for _ in range(5)]
        slots = _vorp_starter_slots({"RB": rb, "WR": wr})
        self.assertEqual(slots["RB"], 10)
        self.assertEqual(slots["WR"], 5)


class TopNflTeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        snap = _with_player_points(build_test_snapshot())
        # Fixture stub has no NFL team tags — assign a few so the
        # aggregation has data (nfl_players is deep-copied, safe).
        for pid, team in {
            "p-qb1": "DET", "p-rb1": "DET", "p-wr1": "SF",
            "p-qb2": "KC", "p-rb2": "KC",
        }.items():
            if pid in snap.nfl_players:
                snap.nfl_players[pid] = {**snap.nfl_players[pid], "team": team}
        cls.snapshot = snap

    def test_scores_sorted_and_positive(self) -> None:
        rows = _top_nfl_team_scores(self.snapshot, self.snapshot.seasons[0])
        self.assertTrue(rows)
        for r in rows:
            self.assertGreater(r["points"], 0)
            self.assertTrue(r["team"])
        for a, b in zip(rows, rows[1:]):
            self.assertGreaterEqual(a["points"], b["points"])

    def test_award_emitted_with_team_value(self) -> None:
        section = awards.build_section(self.snapshot)
        found = None
        for season_row in section["bySeason"]:
            for a in season_row["awards"]:
                if a["key"] == "top_nfl_team":
                    found = a
        self.assertIsNotNone(found)
        self.assertEqual(found["ownerId"], "")
        self.assertIn("team", found["value"])
        self.assertIn("points", found["value"])
        self.assertEqual(found["displayName"], found["value"]["team"])


class AwardOrderingTests(unittest.TestCase):
    def test_champion_then_moty_lead(self) -> None:
        keys = [
            "rivalry_of_the_year", "manager_of_the_year", "top_qb",
            "champion", "bad_beat",
        ]
        awarded = [{"key": k} for k in keys]
        ordered = [a["key"] for a in _order_awards(awarded)]
        self.assertEqual(ordered[0], "champion")
        self.assertEqual(ordered[1], "manager_of_the_year")

    def test_section_orders_champion_first_moty_second(self) -> None:
        snapshot = _with_player_points(build_test_snapshot())
        section = awards.build_section(snapshot)
        for season_row in section["bySeason"]:
            ks = [a["key"] for a in season_row["awards"]]
            if "champion" in ks and "manager_of_the_year" in ks:
                self.assertEqual(ks[0], "champion")
                self.assertEqual(ks[1], "manager_of_the_year")


class FeaturedSeasonRolloverTests(unittest.TestCase):
    """Sleeper flips dynasty leagues to ``in_season`` in the offseason —
    before any NFL games.  The last completed season's full award board
    must stay featured until the new season actually plays games."""

    def test_in_season_but_no_games_keeps_prior_complete_featured(self) -> None:
        # Deep-copy: build_test_snapshot() shares module-level fixture
        # dicts/lists; mutating them in place would pollute other tests.
        snap = copy.deepcopy(build_test_snapshot())  # [2025 complete, 2024 complete]
        newest = snap.seasons[0]
        # Simulate the live 2026 offseason: status in_season, zero games.
        newest.league["status"] = "in_season"
        for entries in newest.matchups_by_week.values():
            for m in entries:
                m["points"] = 0
                m.pop("players_points", None)
                m.pop("starters", None)
        section = awards.build_section(snap)
        # Fixture seasons are [2025, 2024]; treating the newest (2025)
        # as the empty offseason league, the prior complete season
        # (2024) must be featured, with 2025 marked upcoming.
        self.assertEqual(section["featuredSeason"], snap.seasons[1].season)
        self.assertEqual(section["upcomingSeason"], newest.season)

    def test_played_games_promote_new_season(self) -> None:
        snap = _with_player_points(build_test_snapshot())
        snap.seasons[0].league["status"] = "in_season"  # has real points
        section = awards.build_section(snap)
        self.assertEqual(section["featuredSeason"], snap.seasons[0].season)


class AwardsSectionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())
        cls.section = awards.build_section(cls.snapshot)

    def test_each_award_has_required_fields(self) -> None:
        for season_row in self.section["bySeason"]:
            for a in season_row["awards"]:
                self.assertIn("key", a)
                self.assertIn("label", a)
                self.assertIn("description", a)
                self.assertIn("ownerId", a)

    def test_removed_awards_absent(self) -> None:
        for season_row in self.section["bySeason"]:
            for a in season_row["awards"]:
                self.assertNotIn(a["key"], _REMOVED_KEYS)

    def test_descriptions_match(self) -> None:
        for season_row in self.section["bySeason"]:
            for a in season_row["awards"]:
                self.assertEqual(a["description"], AWARD_DESCRIPTIONS.get(a["key"], ""))

    def test_featured_season_keys_present(self) -> None:
        self.assertIn("featuredSeason", self.section)
        self.assertIn("upcomingSeason", self.section)

    def test_no_private_fields_leak(self) -> None:
        contract = build_public_contract(self.snapshot)
        assert_public_payload_safe(contract)


class AwardsLiveRaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = _with_player_points(build_test_snapshot())
        base.seasons[0].league["status"] = "in_season"
        with _NO_CUTOFF:
            cls.section = awards.build_section(base)

    def test_has_award_races(self) -> None:
        self.assertGreater(len(self.section["awardRaces"]), 0)

    def test_race_top_three_only(self) -> None:
        for race in self.section["awardRaces"]:
            self.assertLessEqual(len(race["leaders"]), 3)
            for i, leader in enumerate(race["leaders"]):
                self.assertEqual(leader["rank"], i + 1)

    def test_race_catalog_covers_expected_and_excludes_removed(self) -> None:
        keys = {r["key"] for r in self.section["awardRaces"]}
        # mr_consistent / silent_assassin / playoff_mvp are conditional
        # (week-count / eligibility / champion); the core set is always
        # present for a season that has trades/waivers.
        self.assertTrue(
            {"trader_of_the_year", "waiver_king", "weekly_hammer",
             "bad_beat", "manager_of_the_year"}.issubset(keys)
        )
        self.assertEqual(keys & _REMOVED_KEYS, set())


if __name__ == "__main__":
    unittest.main()
