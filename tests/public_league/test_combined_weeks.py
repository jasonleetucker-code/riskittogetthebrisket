"""Multi-week playoff championship combine rule.

Sleeper leagues can configure a 2-week championship (e.g. weeks 16 +
17 count as a single final).  For record bookkeeping purposes the
pipeline must treat those as ONE matchup — one W/L entry in
rivalries, one meeting in the record book — with combined points
deciding the winner.  Scoring math (weekly hammers) still skips
playoff weeks entirely so weekly-high attribution is unaffected.

These tests pin the combine behavior at the iterator layer
(``walk_matchup_pairs``) and verify it propagates into the record +
rivalry engines.
"""
from __future__ import annotations

import unittest

from src.public_league import records, rivalries
from src.public_league.identity import Manager, ManagerRegistry, TeamAlias
from src.public_league.metrics import walk_matchup_pairs
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _mk_registry() -> ManagerRegistry:
    reg = ManagerRegistry()
    for owner, rid in (("owner-A", 1), ("owner-B", 2)):
        mgr = Manager(
            owner_id=owner,
            display_name=owner.title(),
            current_roster_id=rid,
            current_team_name=f"Team {owner[-1]}",
            current_league_id="L-TEST",
            aliases=[
                TeamAlias(
                    season="2025",
                    league_id="L-TEST",
                    team_name=f"Team {owner[-1]}",
                    display_name=owner.title(),
                    roster_id=rid,
                )
            ],
        )
        reg.by_owner_id[owner] = mgr
        reg.roster_to_owner[("L-TEST", rid)] = owner
    return reg


def _mk_snapshot(matchups_by_week: dict[int, list[dict]]) -> PublicLeagueSnapshot:
    season = SeasonSnapshot(
        season="2025",
        league_id="L-TEST",
        league={
            "league_id": "L-TEST",
            "season": "2025",
            "status": "complete",
            "total_rosters": 2,
            "settings": {"playoff_week_start": 15},
        },
        users=[],
        rosters=[
            {"roster_id": 1, "owner_id": "owner-A", "players": [], "settings": {}},
            {"roster_id": 2, "owner_id": "owner-B", "players": [], "settings": {}},
        ],
        matchups_by_week=matchups_by_week,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    return PublicLeagueSnapshot(
        root_league_id="L-TEST",
        generated_at="2026-04-19T00:00:00+00:00",
        seasons=[season],
        managers=_mk_registry(),
        nfl_players={},
    )


class CombinedWeeksIteratorTests(unittest.TestCase):
    """walk_matchup_pairs must fuse 2-week playoff finals into one pair."""

    def test_two_week_championship_yields_one_combined_pair(self) -> None:
        # Weeks 16+17 championship (A vs B with combined scoring).
        # A wins on combined points (220 vs 210) even though B won
        # week 17 individually.  No semifinal — we only need two
        # contiguous playoff weeks of the same pair to trigger the
        # combine.
        snap = _mk_snapshot(
            {
                16: [
                    {"matchup_id": 1, "roster_id": 1, "points": 130.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 105.0},
                ],
                17: [
                    {"matchup_id": 1, "roster_id": 1, "points": 90.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 105.0},
                ],
            }
        )
        results = list(walk_matchup_pairs(snap))
        # One combined championship entry only.
        self.assertEqual(len(results), 1)

        season, week, a, b, is_playoff = results[0]
        self.assertEqual(week, 16)
        self.assertTrue(is_playoff)
        self.assertEqual(a["_combinedWeeks"], [16, 17])
        self.assertEqual(b["_combinedWeeks"], [16, 17])
        # roster_id=1 (owner-A) combined: 130 + 90 = 220.0
        # roster_id=2 (owner-B) combined: 105 + 105 = 210.0
        pts_by_rid = {a["roster_id"]: a["points"], b["roster_id"]: b["points"]}
        self.assertAlmostEqual(pts_by_rid[1], 220.0, places=2)
        self.assertAlmostEqual(pts_by_rid[2], 210.0, places=2)

    def test_single_week_championship_not_combined(self) -> None:
        # Only one playoff week exists → nothing to combine with.
        snap = _mk_snapshot(
            {
                1: [
                    {"matchup_id": 1, "roster_id": 1, "points": 100.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 105.0},
                ],
                16: [
                    # Lone championship week — no wk17 paired with it.
                    {"matchup_id": 1, "roster_id": 1, "points": 130.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 145.0},
                ],
            }
        )
        results = list(walk_matchup_pairs(snap))
        self.assertEqual(len(results), 2)
        wk16 = next(r for r in results if r[1] == 16)
        _, _, a, b, _ = wk16
        self.assertNotIn("_combinedWeeks", a)
        self.assertNotIn("_combinedWeeks", b)
        self.assertAlmostEqual(a["points"] + b["points"], 275.0, places=2)

    def test_semifinal_and_championship_same_pair_not_combined(self) -> None:
        # Rule must be narrow: even if the same two rosters appear in
        # wk15 (semi) and wk16 (championship), those stay separate.
        # Combine only fires for the final two contiguous playoff
        # weeks.  Here: playoff weeks are 15, 16 — the last two; they
        # ARE contiguous; BUT the scenario simulates a semi with the
        # same rosters as the championship (unusual but legal under
        # our rule — we DO combine since we can't distinguish without
        # bracket context).  See
        # ``test_three_playoff_weeks_only_final_two_combine`` below
        # for the real three-week scenario.
        #
        # This test simply documents what happens when only 2 playoff
        # weeks exist and they share a pair.  The user's scenario has
        # THREE playoff weeks (semi wk15 + champ wk16+17), which the
        # next test covers.
        snap = _mk_snapshot(
            {
                15: [
                    {"matchup_id": 1, "roster_id": 1, "points": 150.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 140.0},
                ],
                16: [
                    {"matchup_id": 1, "roster_id": 1, "points": 130.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 125.0},
                ],
            }
        )
        results = list(walk_matchup_pairs(snap))
        # With only 2 playoff weeks, the last two contiguous + same
        # pair → combined into one.  That's the legitimate
        # 2-week-final case where no semi exists.
        self.assertEqual(len(results), 1)

    def test_trailing_empty_playoff_week_does_not_hide_final(self) -> None:
        # Sleeper snapshots frequently include a trailing wk 18 with
        # roster rows but no matchup_ids (consolation / leftover
        # scoring).  The real 2-week championship is 16+17 and must
        # still fuse even though 18 is technically the last "playoff
        # week" by week number.
        snap = _mk_snapshot(
            {
                14: [
                    # Bye-ish: unpaired rows (no matchup_id).
                    {"matchup_id": None, "roster_id": 1, "points": 100.0},
                    {"matchup_id": None, "roster_id": 2, "points": 110.0},
                ],
                15: [
                    # Semi with different bracket (rid 1 vs rid 2
                    # happen to appear but as solo entries, no
                    # matchup_id → not paired).
                    {"matchup_id": None, "roster_id": 1, "points": 200.0},
                    {"matchup_id": None, "roster_id": 2, "points": 210.0},
                ],
                16: [
                    # Championship game 1.
                    {"matchup_id": 1, "roster_id": 1, "points": 130.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 125.0},
                ],
                17: [
                    # Championship game 2.
                    {"matchup_id": 1, "roster_id": 1, "points": 115.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 140.0},
                ],
                18: [
                    # Sleeper trailing empty week — roster rows
                    # exist but no matchup_ids.
                    {"matchup_id": None, "roster_id": 1, "points": 180.0},
                    {"matchup_id": None, "roster_id": 2, "points": 195.0},
                ],
            }
        )
        results = list(walk_matchup_pairs(snap))
        # Only the combined championship matchup emits (wks 14, 15,
        # 18 have no real pairings; wks 16 + 17 fuse).
        self.assertEqual(len(results), 1)
        _, week, a, b, is_playoff = results[0]
        self.assertEqual(week, 16)
        self.assertTrue(is_playoff)
        self.assertEqual(a["_combinedWeeks"], [16, 17])
        # rid 1: 130 + 115 = 245; rid 2: 125 + 140 = 265.
        pts_by_rid = {a["roster_id"]: a["points"], b["roster_id"]: b["points"]}
        self.assertAlmostEqual(pts_by_rid[1], 245.0, places=2)
        self.assertAlmostEqual(pts_by_rid[2], 265.0, places=2)

    def test_three_playoff_weeks_only_final_two_combine(self) -> None:
        # The real user scenario: wk15 semi (rosters 1 vs 2), wk16+17
        # championship between different rosters.  Set up a case
        # where the same pair appears in BOTH the semi and the final.
        # Because we only combine the *last two* playoff weeks, the
        # semi stays separate.
        snap = _mk_snapshot(
            {
                15: [
                    # Semi with rid 1 vs 2.
                    {"matchup_id": 1, "roster_id": 1, "points": 150.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 140.0},
                ],
                16: [
                    # Championship game 1.
                    {"matchup_id": 1, "roster_id": 1, "points": 130.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 125.0},
                ],
                17: [
                    # Championship game 2.
                    {"matchup_id": 1, "roster_id": 1, "points": 115.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 140.0},
                ],
            }
        )
        results = list(walk_matchup_pairs(snap))
        # wk15 semi emits on its own; wk16+17 combine into one entry.
        weeks = sorted(r[1] for r in results)
        self.assertEqual(weeks, [15, 16])

        # Semi stays uncombined.
        wk15 = next(r for r in results if r[1] == 15)
        _, _, a, b, _ = wk15
        self.assertNotIn("_combinedWeeks", a)
        self.assertNotIn("_combinedWeeks", b)

        # Championship is combined.
        wk16 = next(r for r in results if r[1] == 16)
        _, _, a, b, _ = wk16
        self.assertEqual(a["_combinedWeeks"], [16, 17])
        # Combined totals: rid 1 = 130+115 = 245; rid 2 = 125+140 = 265.
        pts_by_rid = {a["roster_id"]: a["points"], b["roster_id"]: b["points"]}
        self.assertAlmostEqual(pts_by_rid[1], 245.0, places=2)
        self.assertAlmostEqual(pts_by_rid[2], 265.0, places=2)

    def test_regular_season_consecutive_same_pair_not_combined(self) -> None:
        # Two reg-season meetings between same rosters in consecutive
        # weeks must remain separate (combine rule is playoff-only).
        snap = _mk_snapshot(
            {
                1: [
                    {"matchup_id": 1, "roster_id": 1, "points": 100.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 105.0},
                ],
                2: [
                    {"matchup_id": 1, "roster_id": 1, "points": 110.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 115.0},
                ],
            }
        )
        results = list(walk_matchup_pairs(snap))
        self.assertEqual(len(results), 2)
        weeks = sorted(r[1] for r in results)
        self.assertEqual(weeks, [1, 2])
        # Neither week combined.
        for _, _, a, b, _ in results:
            self.assertNotIn("_combinedWeeks", a)


class CombinedWeeksRivalryTests(unittest.TestCase):
    """Rivalry engine must count a 2-week final as ONE meeting."""

    def _snap_with_combined_final(self) -> PublicLeagueSnapshot:
        return _mk_snapshot(
            {
                16: [
                    {"matchup_id": 1, "roster_id": 1, "points": 130.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 105.0},
                ],
                17: [
                    {"matchup_id": 1, "roster_id": 1, "points": 90.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 105.0},
                ],
            }
        )

    def test_one_meeting_not_two(self) -> None:
        snap = self._snap_with_combined_final()
        section = rivalries.build_section(snap)
        rows = section["rivalries"]
        self.assertEqual(len(rows), 1)
        ab = rows[0]
        self.assertEqual(ab["totalMeetings"], 1)
        self.assertEqual(ab["playoffMeetings"], 1)
        # Combined points: A = 130+90 = 220, B = 105+105 = 210. A wins on total.
        winner = ab["winsA"] + ab["winsB"]
        self.assertEqual(winner, 1)
        # Last meeting surfaces combinedWeeks for frontend labelling.
        last = ab["lastMeeting"]
        self.assertEqual(last["combinedWeeks"], [16, 17])
        self.assertAlmostEqual(last["margin"], 10.0, places=2)

    def test_sum_points_decide_winner(self) -> None:
        """Winner is decided by combined points across both weeks,
        even if one week individually went to the other side."""
        snap = _mk_snapshot(
            {
                16: [
                    # Week 16: A clobbers B by 40.
                    {"matchup_id": 1, "roster_id": 1, "points": 180.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 140.0},
                ],
                17: [
                    # Week 17: B wins by 10 — but combined A still
                    # wins by 30.  Single W for A.
                    {"matchup_id": 1, "roster_id": 1, "points": 90.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 100.0},
                ],
            }
        )
        section = rivalries.build_section(snap)
        ab = section["rivalries"][0]
        # Canonical pair ordering is by tuple sort — ('owner-A','owner-B').
        # A is in position 0 so winsA is A's total.
        self.assertEqual(ab["winsA"], 1)
        self.assertEqual(ab["winsB"], 0)


class CombinedWeeksRecordsTests(unittest.TestCase):
    """Record-book weekly rows must stamp combinedWeeks on a combined
    final so the UI can label it 'Weeks 16-17' instead of 'Week 16'."""

    def test_combined_row_carries_weeks_marker(self) -> None:
        snap = _mk_snapshot(
            {
                16: [
                    {"matchup_id": 1, "roster_id": 1, "points": 130.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 105.0},
                ],
                17: [
                    {"matchup_id": 1, "roster_id": 1, "points": 90.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 105.0},
                ],
            }
        )
        rows = records._weekly_side_rows(snap)
        # One entry per side of the combined matchup (not 4).
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["week"], 16)
            self.assertEqual(row["combinedWeeks"], [16, 17])
            self.assertTrue(row["isPlayoff"])

    def test_single_week_playoff_row_has_no_combined_marker(self) -> None:
        snap = _mk_snapshot(
            {
                16: [
                    {"matchup_id": 1, "roster_id": 1, "points": 130.0},
                    {"matchup_id": 1, "roster_id": 2, "points": 105.0},
                ],
            }
        )
        rows = records._weekly_side_rows(snap)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertNotIn("combinedWeeks", row)


if __name__ == "__main__":
    unittest.main()
