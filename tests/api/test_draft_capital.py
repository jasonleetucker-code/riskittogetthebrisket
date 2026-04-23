"""Tests for the draft capital pipeline.

The Draft Data workbook is the authoritative source for BOTH pick
values (Q45:Q116) and pick ownership (R45:R116).  Sleeper is used only
to resolve first-name owners to display team names.
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


class TestTeamTotalsMirrorSheet(unittest.TestCase):
    """The pipeline must mirror the sheet: accumulating R45:R116
    ownership against Q45:Q116 values must equal the authoritative
    per-owner decimals in T63:U74, and the API's integer totals must
    sum to exactly 1200 via largest-remainder rounding of those
    decimals."""

    def test_decimal_totals_match_sheet_per_owner(self):
        from collections import defaultdict
        _, workbook_picks, _, wb_team_totals, _ = _load()
        computed = defaultdict(float)
        for wp in workbook_picks:
            computed[wp["owner"]] += wp["value"]
        for owner, total in computed.items():
            self.assertAlmostEqual(
                total, wb_team_totals.get(owner, 0.0), places=2,
                msg=f"{owner}: computed={total}, sheet={wb_team_totals.get(owner)}",
            )

    def test_api_team_totals_match_largest_remainder_of_sheet_decimals(self):
        """Sorted API dollar totals must equal largest-remainder
        rounding of the sheet's per-owner decimals (regardless of the
        Sleeper display-name mapping used to label each row)."""
        import server
        from collections import defaultdict
        _, workbook_picks, _, _, _ = _load()
        decimals = defaultdict(float)
        for wp in workbook_picks:
            decimals[wp["owner"]] += wp["value"]

        result = server._fetch_draft_capital()
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")

        # Pad with zero-total rows for any teams Sleeper reports that
        # don't appear as owners in R45:R116 (e.g. expansion franchises
        # with no picks yet).
        api_totals = sorted(
            [t["auctionDollars"] for t in result["teamTotals"]], reverse=True,
        )
        decimal_vals = sorted(decimals.values(), reverse=True)
        pad = max(0, len(api_totals) - len(decimal_vals))
        decimal_vals += [0.0] * pad
        expected = sorted(
            server._round_to_budget(decimal_vals, 1200), reverse=True,
        )
        self.assertEqual(api_totals, expected,
                         f"api={api_totals} expected={expected}")


if __name__ == "__main__":
    unittest.main()
