"""Tests for the draft capital pipeline.

Verifies the workbook-driven parsing (from .xlsx or CSV fallback)
produces pick values and team totals that match the Draft Data
workbook exactly, with no rounding or normalization loss.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))


def _load():
    """Import and run the draft-capital parser."""
    import server
    return server._parse_draft_data()


class TestDraftDataParsing(unittest.TestCase):

    def test_pick_dollars_are_float(self):
        pick_dollars, _, _, _, _ = _load()
        self.assertTrue(pick_dollars, "pick_dollars is empty")
        for i, v in enumerate(pick_dollars):
            self.assertIsInstance(v, float, f"pick_dollars[{i}] is {type(v)}")

    def test_72_picks(self):
        pick_dollars, _, _, _, _ = _load()
        self.assertEqual(len(pick_dollars), 72)

    def test_workbook_picks_parsed(self):
        _, workbook_picks, _, _, _ = _load()
        self.assertEqual(len(workbook_picks), 72)

    def test_workbook_picks_have_owner(self):
        _, workbook_picks, _, _, _ = _load()
        for wp in workbook_picks:
            self.assertTrue(wp["owner"], f"R{wp['round']}P{wp['pick']} has no owner")

    def test_slot_to_original_owner_populated(self):
        _, _, slot_to_original, _, _ = _load()
        self.assertGreaterEqual(len(slot_to_original), 10)

    def test_workbook_team_totals_parsed(self):
        _, _, _, wb_totals, _ = _load()
        self.assertGreaterEqual(len(wb_totals), 10)

    def test_workbook_team_totals_sum_to_1200(self):
        _, _, _, wb_totals, _ = _load()
        total = sum(wb_totals.values())
        self.assertAlmostEqual(total, 1200.0, places=2,
                               msg=f"Team totals sum = {total}, expected 1200")

    def test_pick_values_preserve_decimals(self):
        """Values like 97.5, 88.5 must not be truncated to int."""
        _, workbook_picks, _, _, _ = _load()
        has_decimal = any(wp["value"] % 1 != 0 for wp in workbook_picks)
        self.assertTrue(has_decimal,
                        "No decimal values found — likely reading truncated CSV")


class TestExpansionAveraging(unittest.TestCase):

    def test_all_rounds_expansion_picks_equal(self):
        _, workbook_picks, _, _, _ = _load()
        for rnd in range(1, 7):
            rp = [wp for wp in workbook_picks if wp["round"] == rnd]
            if len(rp) < 2:
                continue
            self.assertEqual(rp[0]["value"], rp[1]["value"],
                             f"Round {rnd}: {rp[0]['value']} != {rp[1]['value']}")

    def test_grid_avg_matches_expansion_value(self):
        pick_dollars, workbook_picks, _, _, _ = _load()
        num_teams = 12
        for rnd in range(6):
            d1 = pick_dollars[rnd * num_teams]
            d2 = pick_dollars[rnd * num_teams + 1]
            avg_true = (d1 + d2) / 2
            rp = [wp for wp in workbook_picks if wp["round"] == rnd + 1]
            if len(rp) >= 2:
                self.assertAlmostEqual(rp[0]["value"], avg_true, places=4,
                    msg=f"R{rnd+1}: expansion={rp[0]['value']}, grid avg={avg_true}")


class TestTeamTotals(unittest.TestCase):

    def test_api_uses_workbook_totals(self):
        import server
        result = server._fetch_draft_capital()
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        api_totals = {t["team"]: t["auctionDollars"] for t in result["teamTotals"]}
        _, _, _, wb_totals, _ = _load()
        for team, expected in wb_totals.items():
            self.assertEqual(api_totals.get(team), expected,
                             f"{team}: API ${api_totals.get(team)} != workbook ${expected}")

    def test_pick_values_match_workbook(self):
        import server
        result = server._fetch_draft_capital()
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        _, workbook_picks, _, _, _ = _load()
        for i, (api_pick, wb_pick) in enumerate(zip(result["picks"], workbook_picks)):
            self.assertEqual(api_pick["adjustedDollarValue"], wb_pick["value"],
                f"Pick {i+1}: API={api_pick['adjustedDollarValue']} != wb={wb_pick['value']}")

    def test_total_budget(self):
        import server
        result = server._fetch_draft_capital()
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        _, _, _, wb_totals, _ = _load()
        self.assertAlmostEqual(result["totalBudget"], sum(wb_totals.values()), places=2)


if __name__ == "__main__":
    unittest.main()
