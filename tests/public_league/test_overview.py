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
        self.assertEqual(vitals["managers"], len(self.snapshot.managers.ordered_managers()))

    def test_league_vitals_managers_matches_directory_with_retiree_present(self) -> None:
        """V1-96 residual: leagueVitals is the CURRENT-STATE "At a glance"
        card and renders beside the same payload's ``league.managers``
        directory (``to_public_list()``, retirees excluded).  Its count
        must therefore be the directory's count — the all-time count
        including retirees is a different quantity and would need its own
        label.  A retiree is present so the assertion discriminates:
        counting ``by_owner_id`` (pre-fix) gives directory + retirees.
        """
        snapshot = build_test_snapshot()
        # owner-X held a roster in 2024 only — flag them retired the way
        # build_manager_registry models it (Manager.is_retired).
        snapshot.managers.by_owner_id["owner-X"].is_retired = True

        directory_count = len(snapshot.managers.ordered_managers())
        # Discrimination guard: with the retiree flagged, the all-time
        # count and the directory count genuinely differ.
        self.assertEqual(len(snapshot.managers.by_owner_id), directory_count + 1)

        payload = build_section_payload(snapshot, "overview")
        vitals = payload["data"]["leagueVitals"]
        self.assertEqual(
            vitals["managers"],
            directory_count,
            msg=(
                "leagueVitals.managers must count the forward-facing manager "
                "directory it renders beside, not by_owner_id (which includes "
                "retirees)"
            ),
        )

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

    # ── v2 Home callouts ─────────────────────────────────────────────
    def test_current_power_leader_reads_the_canonical_engine(self) -> None:
        """V1-52 item D: the landing card reads ``power_v2``, not the
        legacy ``public_league/power.py`` it used to.

        The shared fixture (``build_test_snapshot``) is a PRESEASON state
        with no ``team_ros_strength`` snapshot -- exactly the state
        ``power_v2``'s own refuse-to-rank contract (item B) exists for:
        every historical-results component is suppressed by preseason
        mode, and the forward-looking substitute is unavailable, so there
        is genuinely nothing to rank on. The legacy engine used to
        fabricate a score here regardless; this asserts the CORRECT
        behavior, not the old one -- the leader card still names an
        owner and a factual record (both real regardless of whether a
        score is computable), and is honest that no score exists rather
        than showing a fabricated one.
        """
        leader = self.overview["currentPowerLeader"]
        self.assertIsNotNone(leader)
        for key in ("ownerId", "displayName", "teamName", "record"):
            self.assertIn(key, leader)
            self.assertIsNotNone(leader[key], f"{key} is present but None")
        self.assertIsNone(
            leader["power"],
            "the fixture is preseason with no team-strength snapshot -- nothing "
            "is rankable, so a real (non-null) power score means something "
            "fabricated a number rather than refusing",
        )
        self.assertIsNone(
            leader["weekRankDelta"],
            "no per-week ROS-strength history exists for the forward-looking "
            "lens, so this must be unknown, never a fabricated 0",
        )

    def test_current_power_leader_is_populated_when_the_engine_can_rank(self) -> None:
        """The other half: refusal must not become the ONLY outcome.

        Same call this class exercises (``overview._current_power_leader``
        over a real ``power_v2`` section), against a fixture with real
        scored weeks -- proving the honest-refusal test above isn't
        passing because nothing here can ever produce a leader.
        """
        from src.public_league import overview
        from src.ros import power_v2
        from tests.ros.test_power_lenses import _scored_snapshot

        section = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
        leader = overview._current_power_leader(section)
        self.assertIsNotNone(leader)
        self.assertIsNotNone(leader["power"])
        self.assertGreaterEqual(leader["power"], 0)
        self.assertLessEqual(leader["power"], 100)
        self.assertIsNotNone(leader["record"])

    def test_lucky_unlucky_current_populated(self) -> None:
        lu = self.overview["luckyUnluckyCurrent"]
        self.assertIsNotNone(lu)
        self.assertEqual(lu["season"], "2025")
        self.assertIsNotNone(lu["lucky"])
        self.assertIsNotNone(lu["unlucky"])
        # Lucky luck delta >= unlucky luck delta.
        self.assertGreaterEqual(lu["lucky"]["luckDelta"], lu["unlucky"]["luckDelta"])

    def test_active_streak_highlight_populated(self) -> None:
        s = self.overview["activeStreakHighlight"]
        self.assertIsNotNone(s)
        self.assertIn("type", s)
        self.assertIn("length", s)
        self.assertGreater(s["length"], 0)

    def test_record_in_reach_has_holder_and_maybe_chaser(self) -> None:
        rec = self.overview["recordInReach"]
        if rec is None:
            # Fixture may not produce a chaser; skip.
            return
        self.assertIn("holder", rec)
        self.assertIn("category", rec)

    def test_upcoming_week_preview_populated(self) -> None:
        preview = self.overview["upcomingWeekPreview"]
        # Fixture's 2025 season is complete, so mode should be "recap".
        self.assertIsNotNone(preview)
        self.assertIn(preview["mode"], ("recap", "preview"))
        self.assertIn("home", preview)
        self.assertIn("away", preview)
        self.assertIn("h2h", preview)

    def test_latest_full_recap_populated(self) -> None:
        recap = self.overview["latestFullRecap"]
        self.assertIsNotNone(recap)
        for key in ("season", "week", "headline", "summary"):
            self.assertIn(key, recap)
        self.assertTrue(recap["headline"])
        self.assertTrue(recap["summary"])


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
