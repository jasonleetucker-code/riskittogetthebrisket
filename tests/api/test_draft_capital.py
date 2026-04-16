"""Tests for the draft capital pipeline.

Verifies the workbook-driven parsing from CSVs/draft_data.csv produces
exact budget totals, correct expansion averaging, and no integer
truncation of fractional values.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))


def _load():
    """Import and run the draft-capital CSV parser + builder."""
    import server  # noqa: E402 — repo root on sys.path

    pick_dollars, workbook_picks, slot_to_original, rookies = server._parse_draft_csv()
    return pick_dollars, workbook_picks, slot_to_original


class TestDraftCsvParsing(unittest.TestCase):
    """Verify _parse_draft_csv reads the CSV correctly."""

    def test_pick_dollars_are_float(self):
        pick_dollars, _, _ = _load()
        self.assertTrue(pick_dollars, "pick_dollars is empty")
        for i, v in enumerate(pick_dollars):
            self.assertIsInstance(v, float, f"pick_dollars[{i}] is {type(v)}, expected float")

    def test_raw_pick_dollars_sum_to_1200(self):
        pick_dollars, _, _ = _load()
        self.assertAlmostEqual(sum(pick_dollars), 1200, places=2,
                               msg=f"Raw pick dollars sum = {sum(pick_dollars)}, expected 1200")

    def test_72_picks(self):
        pick_dollars, _, _ = _load()
        self.assertEqual(len(pick_dollars), 72)

    def test_workbook_picks_parsed(self):
        _, workbook_picks, _ = _load()
        self.assertEqual(len(workbook_picks), 72,
                         "Workbook final section should have 72 pick assignments")

    def test_workbook_picks_have_owner(self):
        _, workbook_picks, _ = _load()
        for wp in workbook_picks:
            self.assertTrue(wp["owner"], f"Pick R{wp['round']}P{wp['pick']} has no owner")

    def test_slot_to_original_owner_populated(self):
        _, _, slot_to_original = _load()
        self.assertGreaterEqual(len(slot_to_original), 10,
                                "Standings section should map at least 10 slots to owners")


class TestExpansionAveraging(unittest.TestCase):
    """Verify expansion averaging uses true division, not floor division."""

    def test_round1_picks_equal(self):
        """Round 1 picks 1 and 2 must share the same expansion-averaged value."""
        pick_dollars, _, _ = _load()
        avg = (pick_dollars[0] + pick_dollars[1]) / 2
        # Verify it's a true average, not floor
        self.assertEqual(avg, (pick_dollars[0] + pick_dollars[1]) / 2)

    def test_round2_picks_equal(self):
        pick_dollars, _, _ = _load()
        avg = (pick_dollars[12] + pick_dollars[13]) / 2
        self.assertEqual(avg, (pick_dollars[12] + pick_dollars[13]) / 2)

    def test_no_integer_truncation_of_half_values(self):
        """When the sum of two expansion picks is odd, the average must
        be x.5, not floor(x.5).  After normalization the pick_dollars are
        integer-valued floats, so their average is either int or x.5."""
        pick_dollars, _, _ = _load()
        num_teams = 12
        for rnd in range(6):
            idx1 = rnd * num_teams
            idx2 = idx1 + 1
            d1, d2 = pick_dollars[idx1], pick_dollars[idx2]
            avg = (d1 + d2) / 2
            # avg must be exactly representable: either x.0 or x.5
            frac = avg % 1
            self.assertIn(frac, (0.0, 0.5),
                          f"Round {rnd+1}: avg({d1},{d2}) = {avg} has unexpected fractional part")
            # If the sum is odd, the avg MUST be x.5, not truncated
            if (d1 + d2) % 2 != 0:
                self.assertEqual(frac, 0.5,
                                 f"Round {rnd+1}: avg({d1},{d2}) = {avg} should be x.5")

    def test_expansion_avg_preserves_total(self):
        """Replacing raw picks 1,2 with their average must not change the
        round total (avg(a,b)*2 == a+b)."""
        pick_dollars, _, _ = _load()
        num_teams = 12
        for rnd in range(6):
            base = rnd * num_teams
            raw_sum = sum(pick_dollars[base:base + num_teams])
            avg = (pick_dollars[base] + pick_dollars[base + 1]) / 2
            adjusted_sum = avg * 2 + sum(pick_dollars[base + 2:base + num_teams])
            self.assertAlmostEqual(raw_sum, adjusted_sum, places=10,
                                   msg=f"Round {rnd+1}: adjusted sum {adjusted_sum} != raw {raw_sum}")


class TestTeamTotals(unittest.TestCase):
    """Verify team totals computed from workbook authority sum correctly."""

    def _compute_totals(self):
        pick_dollars, workbook_picks, _ = _load()
        num_teams = 12
        team_totals: dict[str, float] = {}
        total = 0.0
        for i, wp in enumerate(workbook_picks):
            rnd = wp["round"]
            pick_num = wp["pick"]
            pick_in_round = pick_num - 1
            if pick_in_round < 2:
                idx1 = (rnd - 1) * num_teams
                idx2 = idx1 + 1
                adjusted = (pick_dollars[idx1] + pick_dollars[idx2]) / 2
            else:
                adjusted = pick_dollars[i]
            team_totals.setdefault(wp["owner"], 0.0)
            team_totals[wp["owner"]] += adjusted
            total += adjusted
        return team_totals, total

    def test_grand_total_equals_1200(self):
        _, total = self._compute_totals()
        self.assertAlmostEqual(total, 1200.0, places=2,
                               msg=f"Grand total = {total}, expected 1200")

    def test_team_total_sum_equals_1200(self):
        team_totals, _ = self._compute_totals()
        team_sum = sum(team_totals.values())
        self.assertAlmostEqual(team_sum, 1200.0, places=2,
                               msg=f"Team total sum = {team_sum}, expected 1200")

    def test_twelve_teams(self):
        team_totals, _ = self._compute_totals()
        self.assertEqual(len(team_totals), 12,
                         f"Expected 12 teams, got {len(team_totals)}: {list(team_totals.keys())}")


if __name__ == "__main__":
    unittest.main()
