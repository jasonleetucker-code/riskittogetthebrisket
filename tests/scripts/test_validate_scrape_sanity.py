"""Unit tests for the pre-commit scrape sanity gate (roadmap 1.4).

Exercises the pure ``evaluate()`` decision function — no git / IO.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "validate_scrape_sanity",
    Path(__file__).resolve().parents[2] / "scripts" / "validate_scrape_sanity.py",
)
vss = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vss)


def _csv(rows: list[str], header: str = "name,value") -> str:
    return "\n".join([header, *rows]) + "\n"


class EvaluateTests(unittest.TestCase):
    def test_healthy_value_csv_ok(self) -> None:
        cur = _csv([f"Player {i},{100 + i}" for i in range(200)])
        prev = _csv([f"Player {i},{100 + i}" for i in range(205)])
        level, _ = vss.evaluate("ktc", cur, prev)
        self.assertEqual(level, "ok")

    def test_rank_only_csv_ok(self) -> None:
        # name,Rank,position,team — value column is NOT last; the
        # any-numeric-signal check must still see the rank.
        rows = [f"Player {i},{i + 1},QB,BUF" for i in range(120)]
        cur = _csv(rows, header="name,Rank,position,team")
        level, msg = vss.evaluate("fantasyProsSf", cur, None)
        self.assertEqual(level, "ok", msg)

    def test_below_min_lines_errors(self) -> None:
        cur = _csv([f"P{i},{i+1}" for i in range(20)])  # 20 rows, ktc needs 100
        level, msg = vss.evaluate("ktc", cur, None)
        self.assertEqual(level, "error")
        self.assertIn("required", msg)

    def test_all_zero_no_signal_errors(self) -> None:
        rows = [f"Player {i},0" for i in range(150)]
        cur = _csv(rows)
        level, msg = vss.evaluate("ktc", cur, None)
        self.assertEqual(level, "error")
        self.assertIn("no numeric signal", msg)

    def test_empty_values_no_signal_errors(self) -> None:
        rows = [f"Player {i},,," for i in range(60)]
        cur = _csv(rows, header="name,a,b,c")
        level, _ = vss.evaluate("dynastyNerdsSfTep", cur, None)
        self.assertEqual(level, "error")

    def test_row_collapse_over_50pct_errors(self) -> None:
        prev = _csv([f"P{i},{i+1}" for i in range(400)])
        cur = _csv([f"P{i},{i+1}" for i in range(150)])  # 37.5% of prior
        level, msg = vss.evaluate("otcffbSf", cur, prev)
        self.assertEqual(level, "error")
        self.assertIn("collapsed", msg)

    def test_row_drop_30_to_50pct_warns(self) -> None:
        prev = _csv([f"P{i},{i+1}" for i in range(400)])
        cur = _csv([f"P{i},{i+1}" for i in range(240)])  # 60% of prior
        level, msg = vss.evaluate("otcffbSf", cur, prev)
        self.assertEqual(level, "warn")
        self.assertIn("dropped", msg)

    def test_minor_drift_ok(self) -> None:
        prev = _csv([f"P{i},{i+1}" for i in range(400)])
        cur = _csv([f"P{i},{i+1}" for i in range(395)])
        level, _ = vss.evaluate("otcffbSf", cur, prev)
        self.assertEqual(level, "ok")

    def test_exempt_source_skips_collapse(self) -> None:
        prev = _csv([f"P{i},{i+1}" for i in range(900)])
        cur = _csv([f"P{i},{i+1}" for i in range(5)])  # huge collapse
        level, _ = vss.evaluate("draftSharksRosSf", cur, prev)
        self.assertEqual(level, "ok")  # ROS is allowlisted

    def test_unreadable_current_errors(self) -> None:
        level, msg = vss.evaluate("ktc", None, None)
        self.assertEqual(level, "error")
        self.assertIn("unreadable", msg)

    def test_new_file_no_prev_only_min_check(self) -> None:
        cur = _csv([f"P{i},{i+1}" for i in range(120)])
        level, _ = vss.evaluate("ktc", cur, None)
        self.assertEqual(level, "ok")


if __name__ == "__main__":
    unittest.main()
