"""Tests for the overview section + contract integration."""
from __future__ import annotations

import unittest

from src.public_league import build_public_contract, build_section_payload
from src.public_league.public_contract import (
    OVERVIEW_SECTION,
    PUBLIC_SECTION_KEYS,
    assert_public_payload_safe,
)

from tests.public_league.fixtures import build_test_snapshot


class OverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.contract = build_public_contract(cls.snapshot)
        cls.overview = cls.contract["sections"][OVERVIEW_SECTION]

    def test_overview_is_first_section_key(self) -> None:
        # Overview is the front door — always appears first.
        self.assertEqual(PUBLIC_SECTION_KEYS[0], OVERVIEW_SECTION)

    def test_current_champion_is_most_recent_champ(self) -> None:
        champ = self.overview["currentChampion"]
        self.assertIsNotNone(champ)
        self.assertEqual(champ["ownerId"], "owner-B")
        self.assertEqual(champ["season"], "2025")

    def test_season_range_label(self) -> None:
        label = self.overview["seasonRangeLabel"]
        self.assertIn("2024", label)
        self.assertIn("2025", label)

    def test_featured_rivalry_populated(self) -> None:
        rivalry = self.overview["featuredRivalry"]
        self.assertIsNotNone(rivalry)
        self.assertIn("rivalryIndex", rivalry)
        self.assertEqual(set(rivalry["ownerIds"]), {"owner-A", "owner-B"})

    def test_top_record_callouts_have_headline_kinds(self) -> None:
        kinds = {c["kind"] for c in self.overview["topRecordCallouts"]}
        self.assertIn("highest_single_week", kinds)
        self.assertIn("biggest_margin", kinds)
        self.assertIn("most_points_in_season", kinds)

    def test_recent_trades_limited_to_five(self) -> None:
        recent = self.overview["recentTrades"]
        self.assertLessEqual(len(recent), 5)
        for t in recent:
            self.assertIn("transactionId", t)
            self.assertIn("sides", t)

    def test_draft_capital_leader_populated(self) -> None:
        leader = self.overview["draftCapitalLeader"]
        self.assertIsNotNone(leader)
        self.assertIn("weightedScore", leader)

    def test_league_vitals_totals_match_snapshot(self) -> None:
        vitals = self.overview["leagueVitals"]
        self.assertEqual(vitals["seasonsCovered"], 2)
        self.assertGreaterEqual(vitals["totalTrades"], 2)

    def test_most_decorated_franchise(self) -> None:
        top = self.overview["mostDecoratedFranchise"]
        self.assertIsNotNone(top)
        self.assertEqual(top["ownerId"], "owner-B")
        self.assertEqual(top["championships"], 2)

    def test_hottest_trade_is_blockbuster(self) -> None:
        head = self.overview["hottestTrade"]
        self.assertIsNotNone(head)
        self.assertEqual(head["transactionId"], "tx-2025-a")

    def test_latest_weekly_recap_populated(self) -> None:
        recap = self.overview["latestWeeklyRecap"]
        self.assertIsNotNone(recap)
        self.assertIn("season", recap)
        self.assertIn("week", recap)


class OverviewSectionEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()

    def test_build_section_payload_accepts_overview_key(self) -> None:
        payload = build_section_payload(self.snapshot, "overview")
        self.assertEqual(payload["section"], "overview")
        self.assertIn("currentChampion", payload["data"])
        assert_public_payload_safe(payload)


if __name__ == "__main__":
    unittest.main()
