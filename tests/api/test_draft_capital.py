"""Tests for the draft capital pipeline.

Values come from the workbook (rounded to integers summing to 1200).
Ownership comes from the Sleeper API (live traded-pick data).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))


def _load():
    import server
    return server._parse_draft_data()


class TestDraftDataParsing(unittest.TestCase):

    def test_72_picks(self):
        pick_dollars, _, _, _, _ = _load()
        self.assertEqual(len(pick_dollars), 72)

    def test_workbook_picks_parsed(self):
        _, workbook_picks, _, _, _ = _load()
        self.assertEqual(len(workbook_picks), 72)

    def test_pick_values_are_float(self):
        pick_dollars, _, _, _, _ = _load()
        for i, v in enumerate(pick_dollars):
            self.assertIsInstance(v, float, f"pick_dollars[{i}] is {type(v)}")

    def test_workbook_has_decimals(self):
        """Workbook values (97.5, 88.5 etc.) confirm xlsx is being read."""
        _, workbook_picks, _, _, _ = _load()
        has_decimal = any(wp["value"] % 1 != 0 for wp in workbook_picks)
        self.assertTrue(has_decimal, "No decimals — likely reading stale CSV")


class TestIntegerRounding(unittest.TestCase):

    def test_round_to_budget_sums_to_1200(self):
        import server
        _, workbook_picks, _, _, _ = _load()
        values = [wp["value"] for wp in workbook_picks]
        rounded = server._round_to_budget(values, 1200)
        self.assertEqual(sum(rounded), 1200,
                         f"Rounded sum = {sum(rounded)}, expected 1200")

    def test_round_to_budget_all_ints(self):
        import server
        _, workbook_picks, _, _, _ = _load()
        values = [wp["value"] for wp in workbook_picks]
        rounded = server._round_to_budget(values, 1200)
        for i, v in enumerate(rounded):
            self.assertIsInstance(v, int, f"rounded[{i}] is {type(v)}")

    def test_expansion_picks_equal_after_rounding(self):
        """Picks 1 and 2 in each round should be equal (same input value
        produces same rounded output)."""
        import server
        _, workbook_picks, _, _, _ = _load()
        values = [wp["value"] for wp in workbook_picks]
        rounded = server._round_to_budget(values, 1200)
        for rnd in range(6):
            idx = rnd * 12
            self.assertEqual(rounded[idx], rounded[idx + 1],
                             f"R{rnd+1}: pick1={rounded[idx]} != pick2={rounded[idx+1]}")


class TestApiOutput(unittest.TestCase):

    def test_api_values_are_integers(self):
        import server
        result = server._fetch_draft_capital()
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        for p in result["picks"]:
            self.assertIsInstance(p["adjustedDollarValue"], int,
                                 f"{p['pick']}: {p['adjustedDollarValue']} is not int")

    def test_api_total_budget_1200(self):
        import server
        result = server._fetch_draft_capital()
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        self.assertEqual(result["totalBudget"], 1200)

    def test_api_team_totals_sum_to_1200(self):
        import server
        result = server._fetch_draft_capital()
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        total = sum(t["auctionDollars"] for t in result["teamTotals"])
        self.assertEqual(total, 1200, f"Team total sum = {total}")


if __name__ == "__main__":
    unittest.main()
