"""End-to-end tests for every metric engine.

These assertions pin concrete expected values against the rich
fixture in ``tests/public_league/fixtures.py``.  Changing the
fixture (or a metric) will fail here — by design.
"""
from __future__ import annotations

import unittest

from src.public_league import activity, archives, awards, draft, franchise, history, records, rivalries, superlatives, weekly
from src.public_league.metrics import (
    matchup_pairs,
    playoff_placement,
    pre_week_standings,
    season_champion,
    season_runner_up,
    season_standings,
    top_seed,
)
from src.public_league.snapshot_store import (
    CONTRACT_PATH,
    SNAPSHOT_PATH,
    load_snapshot,
    persist_snapshot,
    snapshot_to_dict,
    snapshot_from_dict,
)

from tests.public_league.fixtures import build_test_snapshot


class _BaseFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()


# ── History / Hall of Fame ─────────────────────────────────────────────────
class HistoryTests(_BaseFixture):
    def test_champion_and_runner_up(self) -> None:
        s_2025 = self.snapshot.seasons[0]
        self.assertEqual(season_champion(s_2025), 2)
        self.assertEqual(season_runner_up(s_2025), 1)

    def test_top_seed_uses_win_pct_then_pf(self) -> None:
        s_2025 = self.snapshot.seasons[0]
        standings = season_standings(s_2025, self.snapshot.managers)
        ts = top_seed(standings)
        self.assertEqual(ts["ownerId"], "owner-B")
        self.assertAlmostEqual(ts["winPct"], 11 / 14, places=4)

    def test_playoff_placement_full_bracket(self) -> None:
        s_2025 = self.snapshot.seasons[0]
        placements = playoff_placement(s_2025.winners_bracket)
        # 2 won title, 1 was runner-up, 4 took 3rd, 3 took 4th.
        self.assertEqual(placements[2], 1)
        self.assertEqual(placements[1], 2)
        self.assertEqual(placements[4], 3)
        self.assertEqual(placements[3], 4)

    def test_hall_of_fame_aggregates(self) -> None:
        section = history.build_section(self.snapshot)
        hof = {row["ownerId"]: row for row in section["hallOfFame"]}
        # owner-B champion in both seasons.
        self.assertEqual(hof["owner-B"]["championships"], 2)
        self.assertEqual(hof["owner-B"]["finalsAppearances"], 2)
        self.assertEqual(hof["owner-B"]["regularSeasonFirstPlace"], 2)
        # owner-A runner-up in both, no titles.
        self.assertEqual(hof["owner-A"]["championships"], 0)
        self.assertEqual(hof["owner-A"]["finalsAppearances"], 2)
        # Best-finish invariant: owner-B's best finish should be 1.
        self.assertEqual(hof["owner-B"]["bestFinish"], 1)

    def test_owner_x_and_owner_d_never_merge(self) -> None:
        section = history.build_section(self.snapshot)
        hof_owners = {row["ownerId"] for row in section["hallOfFame"]}
        self.assertIn("owner-X", hof_owners)
        self.assertIn("owner-D", hof_owners)


# ── Rivalries ──────────────────────────────────────────────────────────────
class RivalryTests(_BaseFixture):
    def test_rivalry_index_favors_playoff_meetings(self) -> None:
        section = rivalries.build_section(self.snapshot)
        rows = {tuple(r["ownerIds"]): r for r in section["rivalries"]}
        ab = rows[("owner-A", "owner-B")]
        # owner-A vs owner-B meetings across fixtures:
        #   2025 wk1 (reg, margin 14.7)
        #   2025 wk16 (playoff final, margin 25.0)
        #   2024 wk2 (reg, margin 25.0)
        #   2024 wk3 (reg, margin 5.0)
        self.assertEqual(ab["totalMeetings"], 4)
        self.assertEqual(ab["playoffMeetings"], 1)
        # 2024 wk3 margin 5.0 triggers both <=5 and <=10 bands.
        self.assertEqual(ab["gamesDecidedByFive"], 1)
        self.assertEqual(ab["gamesDecidedByTen"], 1)
        # In 2024 the series splits (A won wk3, B won wk2).  In 2025 B won both.
        self.assertEqual(ab["seasonsWhereSeriesSplit"], 1)
        # Meetings in most recent season (2025) = wk1 + wk16 = 2.
        self.assertEqual(ab["meetingsInMostRecentSeason"], 2)
        expected = 5 * 1 + 3 * 1 + 2 * 1 + 2 * 1 + 1 * 4 + 2 * 2
        self.assertEqual(ab["rivalryIndex"], expected)

    def test_last_meeting_is_most_recent(self) -> None:
        section = rivalries.build_section(self.snapshot)
        rows = {tuple(r["ownerIds"]): r for r in section["rivalries"]}
        ab = rows[("owner-A", "owner-B")]
        # Most recent meeting is 2025 week 16 (championship).
        self.assertEqual(ab["lastMeeting"]["season"], "2025")
        self.assertEqual(ab["lastMeeting"]["week"], 16)
        self.assertTrue(ab["lastMeeting"]["isPlayoff"])

    def test_biggest_and_closest_distinct(self) -> None:
        section = rivalries.build_section(self.snapshot)
        rows = {tuple(r["ownerIds"]): r for r in section["rivalries"]}
        ac = rows[("owner-A", "owner-C")]
        # A vs C: 2025 wk2 (margin 3.7), 2025 wk15 (margin 10.0)
        self.assertAlmostEqual(ac["closestGame"]["margin"], 3.7, places=2)
        self.assertAlmostEqual(ac["biggestBlowout"]["margin"], 10.0, places=2)


# ── Records ────────────────────────────────────────────────────────────────
class RecordTests(_BaseFixture):
    def test_highest_and_lowest_single_week(self) -> None:
        section = records.build_section(self.snapshot)
        self.assertEqual(section["singleWeekHighest"][0]["points"], 165.0)
        self.assertEqual(section["singleWeekHighest"][0]["ownerId"], "owner-B")
        self.assertEqual(section["singleWeekLowest"][0]["points"], 80.5)
        self.assertEqual(section["singleWeekLowest"][0]["ownerId"], "owner-X")

    def test_biggest_and_narrowest_margin(self) -> None:
        section = records.build_section(self.snapshot)
        self.assertEqual(section["biggestMargin"][0]["margin"], 69.4)
        self.assertEqual(section["narrowestVictory"][0]["margin"], 2.0)

    def test_most_points_in_loss_and_fewest_in_win(self) -> None:
        section = records.build_section(self.snapshot)
        # Best losing score in the fixture: owner-C 142.1 vs owner-A 145.8.
        top_loss = section["mostPointsInLoss"][0]
        self.assertEqual(top_loss["points"], 142.1)
        # Fewest-in-win: owner-D wins at 110.3 in 2025 wk1 (lowest
        # winning score in the fixture).
        few_win = section["fewestPointsInWin"][0]
        self.assertEqual(few_win["points"], 110.3)

    def test_longest_win_streak(self) -> None:
        section = records.build_section(self.snapshot)
        # owner-B chronological: 2024 W, W, L (to A in wk3), 2025 W, W, W, W.
        # Longest streak after the L = 4.
        ws = {r["ownerId"]: r for r in section["longestWinStreaks"]}
        self.assertEqual(ws["owner-B"]["length"], 4)

    def test_trades_and_waivers_per_season(self) -> None:
        section = records.build_section(self.snapshot)
        counts_by_season = {r["season"]: r for r in section["tradeCountsBySeason"]}
        self.assertEqual(counts_by_season["2025"]["tradeCount"], 1)
        self.assertEqual(counts_by_season["2025"]["waiverCount"], 1)
        self.assertEqual(counts_by_season["2024"]["tradeCount"], 1)
        # Waivers + free-agent pickups count together.
        self.assertEqual(counts_by_season["2024"]["waiverCount"], 2)

    def test_largest_faab_bid(self) -> None:
        section = records.build_section(self.snapshot)
        # Biggest bid is 42 (owner-C / p-wr3 in 2025 wk1).
        top = section["largestFaabBid"][0]
        self.assertEqual(top["bid"], 42)
        self.assertEqual(top["ownerId"], "owner-C")

    def test_playoff_records_populated(self) -> None:
        section = records.build_section(self.snapshot)
        playoff = section["playoffRecords"]
        self.assertTrue(playoff["mostPointsInPlayoffs"])
        self.assertGreater(playoff["mostPointsInPlayoffs"][0]["points"], 0)


# ── Franchise ─────────────────────────────────────────────────────────────
class FranchiseTests(_BaseFixture):
    def test_franchise_detail_totals(self) -> None:
        section = franchise.build_section(self.snapshot)
        owner_b = section["detail"]["owner-B"]
        self.assertEqual(owner_b["cumulative"]["championships"], 2)
        self.assertEqual(owner_b["cumulative"]["wins"], 11 + 12)
        self.assertGreaterEqual(owner_b["tradeCount"], 1)
        self.assertEqual(owner_b["awardShelf"], [])

    def test_best_finish(self) -> None:
        section = franchise.build_section(self.snapshot)
        self.assertEqual(section["detail"]["owner-B"]["cumulative"]["bestFinish"], 1)
        # owner-X never made finals; best is their 2024 standing.
        self.assertGreaterEqual(section["detail"]["owner-X"]["cumulative"]["bestFinish"], 2)

    def test_top_rival(self) -> None:
        section = franchise.build_section(self.snapshot)
        a_detail = section["detail"]["owner-A"]
        # A-B leads on the rivalry index (4 meetings, 1 playoff,
        # 1 season split, 2 meetings in the most recent season).
        self.assertEqual(a_detail["topRival"]["ownerId"], "owner-B")
        self.assertGreater(a_detail["topRival"]["rivalryIndex"], 15)

    def test_draft_capital_summary(self) -> None:
        section = franchise.build_section(self.snapshot)
        capital = section["detail"]["owner-A"]["draftCapital"]
        self.assertIn("totalPicks", capital)
        self.assertIn("weightedScore", capital)
        self.assertGreater(capital["totalPicks"], 0)

    def test_weekly_scoring_trajectory(self) -> None:
        # Every franchise detail must carry a per-week scoring list
        # derived from the scored matchups across every season.  Shape
        # is pinned so the frontend FranchiseTrajectory chart can rely
        # on {season, week, isPlayoff, pointsFor} without defensive
        # fallbacks.
        section = franchise.build_section(self.snapshot)
        owner_a = section["detail"]["owner-A"]
        weekly = owner_a.get("weeklyScoring")
        self.assertIsInstance(weekly, list)
        self.assertGreater(len(weekly), 0)
        for row in weekly:
            self.assertIn("season", row)
            self.assertIn("week", row)
            self.assertIn("isPlayoff", row)
            self.assertIn("pointsFor", row)
            self.assertIsInstance(row["pointsFor"], (int, float))
        # Sorted chronologically by (season, week).
        keys = [(r["season"], r["week"]) for r in weekly]
        self.assertEqual(keys, sorted(keys))


# ── Trade Activity ─────────────────────────────────────────────────────────
class ActivityTests(_BaseFixture):
    def test_feed_counts_and_blockbusters(self) -> None:
        section = activity.build_section(self.snapshot)
        self.assertEqual(section["totalCount"], 2)
        self.assertEqual(len(section["biggestBlockbusters"]), 2)
        # tx-2025-a has 2 players + 2 picks = 4 total assets; tx-2024-a has 1.
        first = section["biggestBlockbusters"][0]
        self.assertEqual(first["transactionId"], "tx-2025-a")
        self.assertEqual(first["totalAssets"], 4)

    def test_position_mix_counts_players(self) -> None:
        section = activity.build_section(self.snapshot)
        mix = section["positionMixMoved"]
        # 2025 trade moved p-rb2 + p-wr2 → 1 RB + 1 WR.
        # 2024 trade moved p-wr3 → 1 WR.  Total WR=2, RB=1.
        self.assertEqual(mix.get("WR"), 2)
        self.assertEqual(mix.get("RB"), 1)

    def test_most_active_and_partner_pair(self) -> None:
        section = activity.build_section(self.snapshot)
        self.assertIsNotNone(section["mostActiveTrader"])
        self.assertIsNotNone(section["mostFrequentPartnerPair"])

    def test_picks_moved_count_matches_fixture(self) -> None:
        section = activity.build_section(self.snapshot)
        # Two picks in tx-2025-a.
        self.assertEqual(section["picksMovedCount"], 2)
        # Players moved: tx-2025-a has 2 received players, tx-2024-a has 1.
        self.assertEqual(section["playersMovedCount"], 3)


# ── Draft ──────────────────────────────────────────────────────────────────
class DraftTests(_BaseFixture):
    def test_pick_weights(self) -> None:
        self.assertEqual(draft.pick_weight(1), 4)
        self.assertEqual(draft.pick_weight(2), 3)
        self.assertEqual(draft.pick_weight(3), 2)
        self.assertEqual(draft.pick_weight(4), 1)
        self.assertEqual(draft.pick_weight(None), 0)

    def test_pick_ownership_applies_traded_picks(self) -> None:
        section = draft.build_section(self.snapshot)
        owner_a_picks = {(p["season"], p["round"], p["isTraded"]) for p in section["pickOwnership"]["owner-A"]}
        # owner-A traded away their 2026 R2 (to owner-B) and received 2026 R4 from owner-B.
        self.assertNotIn(("2026", 2, False), owner_a_picks)
        self.assertIn(("2026", 4, True), owner_a_picks)
        owner_b_picks = {(p["season"], p["round"]) for p in section["pickOwnership"]["owner-B"]}
        self.assertIn(("2026", 2), owner_b_picks)

    def test_stockpile_leaderboard_sorted(self) -> None:
        section = draft.build_section(self.snapshot)
        board = section["stockpileLeaderboard"]
        scores = [row["weightedScore"] for row in board]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_rookie_draft_recap(self) -> None:
        section = draft.build_section(self.snapshot)
        picks = [p for d in section["drafts"] for p in d["firstRoundRecap"]]
        names = {p["playerName"] for p in picks}
        self.assertIn("Rudy Rook", names)
        self.assertIn("Sal Stud", names)

    def test_most_traded_pick(self) -> None:
        section = draft.build_section(self.snapshot)
        self.assertIsNotNone(section["mostTradedPick"])

    def test_pick_movement_trail_has_sources(self) -> None:
        section = draft.build_section(self.snapshot)
        # Three traded picks in the fixture.
        self.assertEqual(len(section["pickMovementTrail"]), 3)


# ── Weekly recap ──────────────────────────────────────────────────────────
class WeeklyTests(_BaseFixture):
    def test_week_highlights_populated(self) -> None:
        section = weekly.build_section(self.snapshot)
        weeks = {(w["season"], w["week"]): w for w in section["weeks"]}
        wk2_2025 = weeks[("2025", 2)]
        self.assertIsNotNone(wk2_2025["highlights"]["gameOfTheWeek"])
        self.assertIsNotNone(wk2_2025["highlights"]["blowoutOfTheWeek"])
        self.assertAlmostEqual(wk2_2025["highlights"]["gameOfTheWeek"]["margin"], 3.7, places=2)
        self.assertAlmostEqual(wk2_2025["highlights"]["blowoutOfTheWeek"]["margin"], 69.4, places=2)

    def test_upset_detection(self) -> None:
        section = weekly.build_section(self.snapshot)
        weeks = {(w["season"], w["week"]): w for w in section["weeks"]}
        # 2024 wk3 contains two upsets:
        #   A (1-1, winPct=0.5) beats B (2-0, winPct=1.0) by 5.0
        #   C (0-2, winPct=0.0) beats X (1-1, winPct=0.5) by 20.0
        # Tiebreak 1: largest gap (C vs X, gap=0.5).
        wk3_2024 = weeks[("2024", 3)]
        upset = wk3_2024["highlights"]["upsetOfTheWeek"]
        self.assertIsNotNone(upset)
        self.assertEqual(upset["winnerOwnerId"], "owner-C")

    def test_pre_week_standings_zero_for_week_one(self) -> None:
        season = self.snapshot.seasons[0]
        standings = pre_week_standings(season, self.snapshot.managers, 1)
        # No games completed before week 1 — every row should be zeros.
        for row in standings:
            self.assertEqual(row["wins"] + row["losses"] + row["ties"], 0)


# ── Superlatives ──────────────────────────────────────────────────────────
class SuperlativeTests(_BaseFixture):
    def test_qb_heavy_winner(self) -> None:
        section = superlatives.build_section(self.snapshot)
        # Roster A is the only one with 2 QBs in the fixture.
        winner = section["mostQbHeavy"]["winner"]
        self.assertEqual(winner["ownerId"], "owner-A")
        self.assertEqual(winner["qb"], 2)

    def test_wr_heavy_winner(self) -> None:
        section = superlatives.build_section(self.snapshot)
        winner = section["mostWrHeavy"]["winner"]
        self.assertEqual(winner["ownerId"], "owner-C")
        self.assertEqual(winner["wr"], 3)

    def test_most_idp_heavy(self) -> None:
        section = superlatives.build_section(self.snapshot)
        winner = section["mostIdpHeavy"]["winner"]
        self.assertEqual(winner["ownerId"], "owner-D")
        self.assertGreaterEqual(winner["idp"], 3)

    def test_most_rookie_heavy(self) -> None:
        section = superlatives.build_section(self.snapshot)
        winner = section["mostRookieHeavy"]["winner"]
        # Rosters A & B each have 2 rookies — tiebreak via rosterSize
        # then weightedPickScore.  Either is acceptable; both should
        # have rookies=2.
        self.assertGreaterEqual(winner["rookies"], 1)

    def test_most_pick_heavy_uses_weighted_score(self) -> None:
        section = superlatives.build_section(self.snapshot)
        winner = section["mostPickHeavy"]["winner"]
        # owner-B netted an extra 2026 R2 via the wk3 trade, bumping
        # their weighted pick score above everyone else.
        self.assertEqual(winner["ownerId"], "owner-B")

    def test_most_active_prefers_high_activity(self) -> None:
        section = superlatives.build_section(self.snapshot)
        winner = section["mostActive"]["winner"]
        # owner-A participates in 2 trades in 2024+2025; A or B.
        self.assertIn(winner["ownerId"], {"owner-A", "owner-B"})


# ── Archives ──────────────────────────────────────────────────────────────
class ArchiveTests(_BaseFixture):
    def test_trades_waivers_rookie_drafts_populated(self) -> None:
        section = archives.build_section(self.snapshot)
        self.assertEqual(len(section["trades"]), 2)
        self.assertEqual(len(section["waivers"]), 3)  # 2 waivers + 1 FA
        self.assertEqual(len(section["rookieDrafts"]), 2)

    def test_weekly_matchup_archive_covers_playoff(self) -> None:
        section = archives.build_section(self.snapshot)
        playoffs = [m for m in section["weeklyMatchups"] if m["isPlayoff"]]
        # Two semifinals in wk15 + one final in wk16 = 3 playoff matchups.
        self.assertEqual(len(playoffs), 3)
        self.assertTrue(all("playoff" in m["tags"] for m in playoffs))

    def test_season_results_tag_champion(self) -> None:
        section = archives.build_section(self.snapshot)
        champs = [r for r in section["seasonResults"] if "champion" in r["tags"]]
        self.assertEqual({r["ownerId"] for r in champs}, {"owner-B"})

    def test_waiver_archive_exposes_faab_bid_and_player_position(self) -> None:
        section = archives.build_section(self.snapshot)
        bids = {w["transactionId"]: w for w in section["waivers"]}
        self.assertEqual(bids["wv-2025-a"]["bid"], 42)
        added_positions = [p["position"] for p in bids["wv-2025-a"]["added"]]
        self.assertEqual(added_positions, ["WR"])


# ── Awards ────────────────────────────────────────────────────────────────
class AwardsTests(_BaseFixture):
    def test_every_award_key_present(self) -> None:
        section = awards.build_section(self.snapshot)
        for season_row in section["bySeason"]:
            keys = {a["key"] for a in season_row["awards"]}
            for expected in (
                "champion",
                "runner_up",
                "top_seed",
                "regular_season_crown",
                "points_king",
                "points_black_hole",
                "toilet_bowl",
                "highest_single_week",
                "lowest_single_week",
            ):
                self.assertIn(expected, keys)


# ── Persistence ──────────────────────────────────────────────────────────
class SnapshotPersistenceTests(_BaseFixture):
    def test_round_trip_dict(self) -> None:
        as_dict = snapshot_to_dict(self.snapshot)
        restored = snapshot_from_dict(as_dict)
        self.assertEqual(restored.root_league_id, self.snapshot.root_league_id)
        self.assertEqual(len(restored.seasons), len(self.snapshot.seasons))
        self.assertEqual(
            restored.managers.by_owner_id.keys(),
            self.snapshot.managers.by_owner_id.keys(),
        )

    def test_persist_and_load(self) -> None:
        import tempfile
        import os as _os
        from src.public_league import snapshot_store as store

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = store.DATA_DIR
            try:
                store.DATA_DIR = store.Path(tmp)
                store.SNAPSHOT_PATH = store.DATA_DIR / "snapshot.json"
                store.IDENTITY_PATH = store.DATA_DIR / "identity.json"
                store.CONTRACT_PATH = store.DATA_DIR / "contract.json"
                store.NFL_PLAYERS_PATH = store.DATA_DIR / "nfl_players.json"
                store.persist_snapshot(self.snapshot)
                self.assertTrue(store.SNAPSHOT_PATH.exists())
                loaded = store.load_snapshot()
                self.assertIsNotNone(loaded)
                self.assertEqual(len(loaded.seasons), len(self.snapshot.seasons))
            finally:
                store.DATA_DIR = tmp_path
                store.SNAPSHOT_PATH = store.DATA_DIR / "snapshot.json"
                store.IDENTITY_PATH = store.DATA_DIR / "identity.json"
                store.CONTRACT_PATH = store.DATA_DIR / "contract.json"
                store.NFL_PLAYERS_PATH = store.DATA_DIR / "nfl_players.json"


if __name__ == "__main__":
    unittest.main()
