"""Tests for the extended awards engine.

These tests exercise every award formula against the fixture in
``tests/public_league/fixtures.py`` and extend the fixture with
``players_points`` where a calculation depends on per-player scoring
data (Trader of the Year, Waiver King, Playoff MVP).
"""
from __future__ import annotations

import copy
import unittest

from src.public_league import awards
from src.public_league.awards import (
    AWARD_DESCRIPTIONS,
    _bad_beat_scores,
    _chaos_agent_scores,
    _most_active_scores,
    _pick_hoarder_scores,
    _playoff_mvp_scores,
    _rivalry_of_the_year,
    _silent_assassin_scores,
    _trader_of_the_year_scores,
    _waiver_king_scores,
    _weekly_hammer_scores,
    _best_rebuild_scores,
)
from src.public_league.public_contract import assert_public_payload_safe, build_public_contract

from tests.public_league.fixtures import build_test_snapshot


def _with_player_points(snapshot):
    """Return a deep-copy of snapshot with rich players_points / starters
    stamps so awards relying on per-player scoring have data."""
    snap = copy.deepcopy(snapshot)

    # 2025 season — manufacture per-player scoring for each matchup so
    # trader/waiver/playoff-MVP calculations have numbers to crunch.
    def _stamp(entry, players_points, starters=None):
        entry["players_points"] = players_points
        if starters is not None:
            entry["starters"] = starters

    s2025 = snap.seasons[0]
    # wk1 roster 1 started p-qb1 (40pts), p-rb1 (30), p-wr1 (20) etc.
    for wk, per_rid in {
        1: {
            1: ({"p-qb1": 40.0, "p-rb1": 30.0, "p-wr1": 20.0, "p-te1": 15.0, "p-rookie-a": 15.5}, ["p-qb1","p-rb1","p-wr1","p-te1","p-rookie-a"]),
            2: ({"p-qb2": 45.0, "p-rb3": 35.0, "p-wr2": 25.0, "p-te1": 15.0, "p-rookie-b": 15.2}, ["p-qb2","p-rb3","p-wr2","p-te1","p-rookie-b"]),
            3: ({"p-wr1": 20.0, "p-wr2": 20.0, "p-wr3": 15.0, "p-rb1": 20.0, "p-qb1": 20.0}, ["p-wr1","p-wr2","p-wr3","p-rb1","p-qb1"]),
            4: ({"p-te1": 15.0, "p-te2": 20.0, "p-idp1": 15.0, "p-idp2": 20.0, "p-idp3": 25.0, "p-qb2": 15.3}, ["p-te1","p-te2","p-idp1","p-idp2","p-idp3","p-qb2"]),
        },
        2: {
            1: ({"p-qb1": 40.0, "p-rb1": 35.0, "p-wr1": 25.8, "p-te1": 20.0, "p-rookie-a": 25.0}, ["p-qb1","p-rb1","p-wr1","p-te1","p-rookie-a"]),
            3: ({"p-wr1": 25.0, "p-wr2": 25.0, "p-wr3": 30.0, "p-rb1": 32.1, "p-qb1": 30.0}, ["p-wr1","p-wr2","p-wr3","p-rb1","p-qb1"]),
            2: ({"p-qb2": 50.0, "p-rb2": 40.0, "p-wr2": 35.0, "p-te1": 20.0, "p-rookie-b": 20.0}, ["p-qb2","p-rb2","p-wr2","p-te1","p-rookie-b"]),
            4: ({"p-te1": 15.0, "p-te2": 20.0, "p-idp1": 15.0, "p-idp2": 15.0, "p-idp3": 15.0, "p-qb2": 15.6}, ["p-te1","p-te2","p-idp1","p-idp2","p-idp3","p-qb2"]),
        },
        15: {
            2: ({"p-rb2": 55.5, "p-wr2": 35.0, "p-qb2": 40.0, "p-te1": 15.0, "p-rookie-b": 10.0}, ["p-rb2","p-wr2","p-qb2","p-te1","p-rookie-b"]),
            4: ({"p-te1": 15.0, "p-te2": 30.0, "p-idp1": 30.0, "p-idp2": 25.0, "p-idp3": 20.0, "p-qb2": 10.0}, ["p-te1","p-te2","p-idp1","p-idp2","p-idp3","p-qb2"]),
            1: ({"p-qb1": 40.0, "p-rb1": 30.0, "p-wr1": 35.0, "p-te1": 20.0, "p-rookie-a": 25.0}, ["p-qb1","p-rb1","p-wr1","p-te1","p-rookie-a"]),
            3: ({"p-wr1": 40.0, "p-wr2": 30.0, "p-wr3": 25.0, "p-rb1": 25.0, "p-qb1": 20.0}, ["p-wr1","p-wr2","p-wr3","p-rb1","p-qb1"]),
        },
        16: {
            2: ({"p-rb2": 50.0, "p-wr2": 30.0, "p-qb2": 35.0, "p-te1": 15.0, "p-rookie-b": 15.0}, ["p-rb2","p-wr2","p-qb2","p-te1","p-rookie-b"]),
            1: ({"p-qb1": 30.0, "p-rb1": 25.0, "p-wr1": 25.0, "p-te1": 15.0, "p-rookie-a": 25.0}, ["p-qb1","p-rb1","p-wr1","p-te1","p-rookie-a"]),
        },
    }.items():
        entries = s2025.matchups_by_week.get(wk, [])
        for e in entries:
            rid = int(e.get("roster_id"))
            if rid in per_rid:
                pp, st = per_rid[rid]
                _stamp(e, pp, starters=st)

    # 2024 season — simpler but sufficient for tests.
    s2024 = snap.seasons[1]
    for wk in s2024.matchups_by_week.keys():
        for entry in s2024.matchups_by_week[wk]:
            total = entry.get("points") or 0.0
            pp = {"p-te1": round(float(total) / 2, 2), "p-wr1": round(float(total) / 2, 2)}
            _stamp(entry, pp, starters=["p-te1", "p-wr1"])
    return snap


class AwardDescriptionsTests(unittest.TestCase):
    def test_every_award_has_a_description(self):
        for key in (
            "trader_of_the_year", "best_trade_of_the_year", "waiver_king",
            "chaos_agent", "most_active", "pick_hoarder", "silent_assassin",
            "weekly_hammer", "playoff_mvp", "bad_beat", "best_rebuild",
            "rivalry_of_the_year",
        ):
            self.assertIn(key, AWARD_DESCRIPTIONS)
            self.assertTrue(AWARD_DESCRIPTIONS[key])


class TraderAndBestTradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_trader_rows_sort_by_points_gained(self) -> None:
        rows, best = _trader_of_the_year_scores(self.snapshot, self.snapshot.seasons[0])
        self.assertTrue(rows)
        # Descending order by pointsGained.
        for a, b in zip(rows, rows[1:]):
            self.assertGreaterEqual(a["pointsGained"], b["pointsGained"])
        # Every row includes human-friendly display name.
        for r in rows:
            self.assertTrue(r["displayName"])

    def test_best_trade_has_a_winner_when_trade_exists(self) -> None:
        _, best = _trader_of_the_year_scores(self.snapshot, self.snapshot.seasons[0])
        self.assertIsNotNone(best)
        gain, owner_id, payload = best
        self.assertIn(owner_id, {"owner-A", "owner-B"})
        self.assertIn("transactionId", payload)


class WaiverKingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_waiver_rows_have_faab_efficiency_when_bid_present(self) -> None:
        rows = _waiver_king_scores(self.snapshot, self.snapshot.seasons[0])
        cole = next((r for r in rows if r["ownerId"] == "owner-C"), None)
        self.assertIsNotNone(cole)
        self.assertIsNotNone(cole["faabEfficiency"])

    def test_missing_bids_do_not_crash(self) -> None:
        rows = _waiver_king_scores(self.snapshot, self.snapshot.seasons[1])
        # 2024 season has a free_agent add with no bid — should not explode.
        for r in rows:
            self.assertIn("faabEfficiency", r)


class ChaosAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_chaos_formula_matches_spec(self) -> None:
        rows = _chaos_agent_scores(self.snapshot, self.snapshot.seasons[0])
        # 2025 has one trade (owner-A ↔ owner-B).  Each side should earn:
        #   3 * 1 trade + 1 * 1 partner + 1 * 1 player + 1 * 1 pick = 6
        # plus owner-A's side has 1 pick received; owner-B has 1 pick too.
        owner_a = next(r for r in rows if r["ownerId"] == "owner-A")
        self.assertEqual(owner_a["trades"], 1)
        self.assertEqual(owner_a["distinctPartners"], 1)
        # players_moved includes received players only — 1 for each side.
        self.assertEqual(owner_a["playersMoved"], 1)
        self.assertEqual(owner_a["picksMoved"], 1)
        self.assertEqual(owner_a["score"], 3 * 1 + 1 * 1 + 1 * 1 + 1 * 1)

    def test_sort_descending(self) -> None:
        rows = _chaos_agent_scores(self.snapshot, self.snapshot.seasons[0])
        for a, b in zip(rows, rows[1:]):
            self.assertGreaterEqual(a["score"], b["score"])


class MostActiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_total_sums_all_activity(self) -> None:
        rows = _most_active_scores(self.snapshot, self.snapshot.seasons[0])
        for r in rows:
            self.assertEqual(r["total"], r["trades"] + r["waivers"] + r["freeAgents"] + r["drops"])


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
        # No row should ever record a loss from a blowout as a "close game".
        for r in rows:
            self.assertLessEqual(r["avgCloseMargin"], 10.0 + 1e-6)


class WeeklyHammerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_high_score_finishes_count(self) -> None:
        rows = _weekly_hammer_scores(self.snapshot, self.snapshot.seasons[0])
        by_owner = {r["ownerId"]: r for r in rows}
        # Weeks 1 & 2 regular season.  Week 1 top: owner-B 135.2,
        # week 2 top: owner-B 165.0.  Owner-B should have 2 high-score
        # finishes.  No one else should have 2.
        self.assertEqual(by_owner["owner-B"]["highScoreFinishes"], 2)
        for owner_id, r in by_owner.items():
            if owner_id != "owner-B":
                self.assertLessEqual(r["highScoreFinishes"], 1)


class PlayoffMvpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_playoff_points_accumulate(self) -> None:
        rows = _playoff_mvp_scores(self.snapshot, self.snapshot.seasons[0])
        by_owner = {r["ownerId"]: r for r in rows}
        # owner-B played week 15 (155.5) + week 16 (145.0) = 300.5.
        self.assertAlmostEqual(by_owner["owner-B"]["playoffPoints"], 300.5, places=1)

    def test_top_player_populated(self) -> None:
        rows = _playoff_mvp_scores(self.snapshot, self.snapshot.seasons[0])
        by_owner = {r["ownerId"]: r for r in rows}
        # owner-B's stamp has p-rb2 as 55.5 in wk15; we overwrite
        # starters/players_points so the top player should be p-rb2.
        self.assertTrue(by_owner["owner-B"]["topPlayerName"])


class BadBeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_points_in_loss_only(self) -> None:
        rows = _bad_beat_scores(self.snapshot, self.snapshot.seasons[0])
        by_owner = {r["ownerId"]: r for r in rows}
        # owner-C lost wk1 (95.0 vs owner-D 110.3) and wk2 (142.1 vs
        # owner-A 145.8).  biggestLoss=142.1.
        self.assertAlmostEqual(by_owner["owner-C"]["biggestLoss"], 142.1, places=1)


class PickHoarderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_weighted_score_nonzero(self) -> None:
        rows = _pick_hoarder_scores(self.snapshot)
        self.assertTrue(rows)
        self.assertGreater(rows[0]["weightedScore"], 0)

    def test_sort_descending(self) -> None:
        rows = _pick_hoarder_scores(self.snapshot)
        for a, b in zip(rows, rows[1:]):
            self.assertGreaterEqual(a["weightedScore"], b["weightedScore"])


class BestRebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_composite_populated_for_known_owners(self) -> None:
        rows = _best_rebuild_scores(
            self.snapshot,
            self.snapshot.seasons[0],
            self.snapshot.seasons[1],
        )
        owners = {r["ownerId"] for r in rows}
        # Only owners present in BOTH seasons should appear.
        self.assertEqual(owners, {"owner-A", "owner-B", "owner-C"})


class RivalryOfTheYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_rivalry_has_playoff_boost(self) -> None:
        r = _rivalry_of_the_year(self.snapshot, self.snapshot.seasons[0])
        self.assertIsNotNone(r)
        self.assertIn("rivalryIndex", r)
        # A vs C meets in wk2 (margin 3.7 — both close-bands) and wk15
        # playoff semifinal (margin 10.0 — within 10-band).  Their
        # rivalry_index 14 beats A-B's 7 (one playoff game, no close
        # bands).
        self.assertEqual(sorted(r["ownerIds"]), sorted(["owner-A", "owner-C"]))


class AwardsSectionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())
        cls.section = awards.build_section(cls.snapshot)

    def test_each_historical_award_has_required_fields(self) -> None:
        for season_row in self.section["bySeason"]:
            for a in season_row["awards"]:
                self.assertIn("key", a)
                self.assertIn("label", a)
                self.assertIn("description", a)
                self.assertIn("ownerId", a)

    def test_live_races_empty_when_current_season_complete(self) -> None:
        # Fixture marks both seasons "complete" → zero live races.
        self.assertEqual(self.section["awardRaces"], [])

    def test_every_award_has_a_description_in_the_payload(self) -> None:
        for season_row in self.section["bySeason"]:
            for a in season_row["awards"]:
                self.assertEqual(
                    a["description"],
                    AWARD_DESCRIPTIONS.get(a["key"], ""),
                )

    def test_no_private_fields_leak(self) -> None:
        contract = build_public_contract(self.snapshot)
        assert_public_payload_safe(contract)


class AwardsLiveRaceTests(unittest.TestCase):
    """In-progress season → live races populated + top-3 only."""

    @classmethod
    def setUpClass(cls) -> None:
        base = _with_player_points(build_test_snapshot())
        # Mark 2025 as in_progress so the live-race branch fires.
        base.seasons[0].league["status"] = "in_season"
        cls.section = awards.build_section(base)

    def test_has_award_races(self) -> None:
        self.assertGreater(len(self.section["awardRaces"]), 0)

    def test_race_top_three_only(self) -> None:
        for race in self.section["awardRaces"]:
            self.assertLessEqual(len(race["leaders"]), 3)
            for i, leader in enumerate(race["leaders"]):
                self.assertEqual(leader["rank"], i + 1)

    def test_hottest_race_populated(self) -> None:
        self.assertIsNotNone(self.section["hottestRace"])
        self.assertIn("topLeader", self.section["hottestRace"])

    def test_race_catalog_covers_expected_keys(self) -> None:
        keys = {r["key"] for r in self.section["awardRaces"]}
        expected = {
            "trader_of_the_year", "waiver_king", "chaos_agent",
            "most_active", "weekly_hammer", "bad_beat", "pick_hoarder",
        }
        # silent_assassin and playoff_mvp are conditional (eligibility /
        # playoff-only).  Must still include the core races above.
        self.assertTrue(expected.issubset(keys))


class EdgeCaseTests(unittest.TestCase):
    """Defensive tests: renamed teams, missing FAAB, tied values."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_renamed_team_attributes_to_single_owner(self) -> None:
        # owner-A renamed team between 2024 and 2025.  The Trader of
        # the Year row must appear ONCE per season, keyed by owner-A.
        section = awards.build_section(self.snapshot)
        for season_row in section["bySeason"]:
            owners_in_toy = [
                a["ownerId"] for a in season_row["awards"] if a["key"] == "trader_of_the_year"
            ]
            # Either one winner or none (if no trades that season).
            self.assertLessEqual(len(owners_in_toy), 1)

    def test_no_faab_bid_returns_none_efficiency(self) -> None:
        rows = _waiver_king_scores(self.snapshot, self.snapshot.seasons[1])
        for r in rows:
            if r["faabSpent"] == 0:
                self.assertIsNone(r["faabEfficiency"])

    def test_ties_are_deterministic(self) -> None:
        # Running twice must produce identical ordering.
        a = _most_active_scores(self.snapshot, self.snapshot.seasons[0])
        b = _most_active_scores(self.snapshot, self.snapshot.seasons[0])
        self.assertEqual([r["ownerId"] for r in a], [r["ownerId"] for r in b])


if __name__ == "__main__":
    unittest.main()
