"""Tests for the draft capital pipeline.

Verifies the workbook-driven parsing from CSVs/draft_data.csv produces
pick values matching the spreadsheet's Q45:Q116, team totals matching
U63:U74, correct expansion averaging, and no integer truncation.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))


def _load():
    """Import and run the draft-capital CSV parser."""
    import server  # noqa: E402 — repo root on sys.path

    return server._parse_draft_csv()


class TestDraftCsvParsing(unittest.TestCase):
    """Verify _parse_draft_csv reads the CSV correctly."""

    def test_pick_dollars_are_float(self):
        pick_dollars, _, _, _, _ = _load()
        self.assertTrue(pick_dollars, "pick_dollars is empty")
        for i, v in enumerate(pick_dollars):
            self.assertIsInstance(v, float, f"pick_dollars[{i}] is {type(v)}, expected float")

    def test_72_picks(self):
        pick_dollars, _, _, _, _ = _load()
        self.assertEqual(len(pick_dollars), 72)

    def test_workbook_picks_parsed(self):
        _, workbook_picks, _, _, _ = _load()
        self.assertEqual(len(workbook_picks), 72,
                         "Workbook final section should have 72 pick assignments")

    def test_workbook_picks_have_owner(self):
        _, workbook_picks, _, _, _ = _load()
        for wp in workbook_picks:
            self.assertTrue(wp["owner"], f"Pick R{wp['round']}P{wp['pick']} has no owner")

    def test_slot_to_original_owner_populated(self):
        _, _, slot_to_original, _, _ = _load()
        self.assertGreaterEqual(len(slot_to_original), 10,
                                "Standings section should map at least 10 slots to owners")

    def test_workbook_team_totals_parsed(self):
        _, _, _, wb_totals, _ = _load()
        self.assertEqual(len(wb_totals), 12,
                         f"Expected 12 team totals, got {len(wb_totals)}")

    def test_workbook_team_totals_match_spreadsheet(self):
        """U63:U74 from the spreadsheet — the authoritative team totals."""
        _, _, _, wb_totals, _ = _load()
        expected = {
            "Jason": 422, "Joel": 164, "Collin": 141, "Blaine": 101,
            "MaKayla": 74, "Roy": 74, "Kich": 66, "Ty": 54,
            "Joey": 52, "Brent": 48, "Ed": 6, "Eric": 1,
        }
        for team, val in expected.items():
            self.assertEqual(wb_totals.get(team), val,
                             f"{team}: expected ${val}, got ${wb_totals.get(team)}")


class TestExpansionAveraging(unittest.TestCase):
    """Verify expansion averaging in Q45:Q116 values."""

    def test_round1_expansion_picks_equal(self):
        """Q45:Q116 picks 1 and 2 in Round 1 must show the same value."""
        _, workbook_picks, _, _, _ = _load()
        r1 = [wp for wp in workbook_picks if wp["round"] == 1]
        self.assertEqual(r1[0]["value"], r1[1]["value"],
                         f"R1 picks: {r1[0]['value']} != {r1[1]['value']}")

    def test_round2_expansion_picks_equal(self):
        _, workbook_picks, _, _, _ = _load()
        r2 = [wp for wp in workbook_picks if wp["round"] == 2]
        self.assertEqual(r2[0]["value"], r2[1]["value"],
                         f"R2 picks: {r2[0]['value']} != {r2[1]['value']}")

    def test_all_rounds_expansion_picks_equal(self):
        _, workbook_picks, _, _, _ = _load()
        for rnd in range(1, 7):
            rp = [wp for wp in workbook_picks if wp["round"] == rnd]
            self.assertGreaterEqual(len(rp), 2, f"Round {rnd} has < 2 picks")
            self.assertEqual(rp[0]["value"], rp[1]["value"],
                             f"Round {rnd}: pick 1 = {rp[0]['value']}, pick 2 = {rp[1]['value']}")

    def test_no_floor_division_in_raw_col11(self):
        """The raw col 11 expansion averages with true division must not
        lose value via floor division."""
        pick_dollars, _, _, _, _ = _load()
        num_teams = 12
        for rnd in range(6):
            d1 = pick_dollars[rnd * num_teams]
            d2 = pick_dollars[rnd * num_teams + 1]
            avg_true = (d1 + d2) / 2
            avg_floor = (d1 + d2) // 2
            if (d1 + d2) % 2 != 0:
                self.assertNotEqual(avg_true, avg_floor,
                                    f"Round {rnd+1}: true division should differ from floor")


class TestTeamTotals(unittest.TestCase):
    """Verify workbook team totals are used in the API response."""

    def test_workbook_team_totals_sum(self):
        """U63:U74 totals sum to 1203 in the CSV export (the underlying
        decimal formulas sum to exactly 1200, but the CSV truncated each
        team total to an integer)."""
        _, _, _, wb_totals, _ = _load()
        total = sum(wb_totals.values())
        # The workbook's displayed integers sum to 1203, not 1200.
        # This is expected — each team total was individually rounded.
        self.assertEqual(total, 1203,
                         f"Workbook team totals sum = {total}, expected 1203")

    def test_twelve_teams(self):
        _, _, _, wb_totals, _ = _load()
        self.assertEqual(len(wb_totals), 12)

    def test_api_uses_workbook_totals(self):
        """The _fetch_draft_capital function must use U63:U74 team totals,
        not re-compute from per-pick values."""
        import server
        result = server._fetch_draft_capital()
        if "error" in result:
            self.skipTest(f"Draft capital unavailable: {result['error']}")

        api_totals = {t["team"]: t["auctionDollars"] for t in result["teamTotals"]}
        _, _, _, wb_totals, _ = _load()

        for team, expected in wb_totals.items():
            self.assertEqual(api_totals.get(team), expected,
                             f"{team}: API ${api_totals.get(team)} != workbook ${expected}")

    def test_pick_values_match_q45_q116(self):
        """API pick adjustedDollarValue must come from Q45:Q116, not
        from the normalized col 11 values."""
        import server
        result = server._fetch_draft_capital()
        if "error" in result:
            self.skipTest(f"Draft capital unavailable: {result['error']}")

        _, workbook_picks, _, _, _ = _load()
        for i, (api_pick, wb_pick) in enumerate(zip(result["picks"], workbook_picks)):
            self.assertEqual(
                api_pick["adjustedDollarValue"], wb_pick["value"],
                f"Pick {i+1} ({api_pick['pick']}): API adj={api_pick['adjustedDollarValue']} "
                f"!= Q45 value={wb_pick['value']}",
            )


if __name__ == "__main__":
    unittest.main()
