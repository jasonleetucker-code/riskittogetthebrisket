"""Unit tests for scripts/fetch_dynasty_daddy.py.

Covers:
  * JSON schema probe (non-array / malformed response)
  * Player parsing with position filtering
  * Value signal filtering (zero / None values excluded)
  * End-to-end fixture build: ``--from-file`` with a tiny JSON blob
  * Exit-code behaviour for schema regressions and row-count floors
  * Non-TEP metadata (standard SF scoring)
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import fetch_dynasty_daddy as dd


def _make_players(
    *entries: tuple[str, str, int],
) -> list[dict]:
    """entries = (name, position, sf_trade_value)."""
    return [
        {
            "full_name": n,
            "position": pos,
            "sf_trade_value": val,
            "sf_overall_rank": i + 1,
            "sf_position_rank": i + 1,
        }
        for i, (n, pos, val) in enumerate(entries)
    ]


class TestParsePlayersSchemaProbe(unittest.TestCase):
    def test_non_array_raises_schema_error(self):
        with self.assertRaises(dd.DynastyDaddySchemaError):
            dd._parse_players({"players": []})

    def test_non_list_string_raises_schema_error(self):
        with self.assertRaises(dd.DynastyDaddySchemaError):
            dd._parse_players("not a list")

    def test_empty_array_returns_empty(self):
        self.assertEqual(dd._parse_players([]), [])


class TestParsePlayersPositionFilter(unittest.TestCase):
    def test_only_offense_positions_kept(self):
        data = _make_players(
            ("Patrick Mahomes", "QB", 9500),
            ("Saquon Barkley", "RB", 8200),
            ("CeeDee Lamb", "WR", 9000),
            ("Travis Kelce", "TE", 5500),
            ("Nick Bosa", "DE", 4000),
            ("T.J. Watt", "LB", 3500),
            ("Sauce Gardner", "CB", 3000),
        )
        rows = dd._parse_players(data)
        # Only QB/RB/WR/TE should pass through.
        self.assertEqual(len(rows), 4)
        names = {r["name"] for r in rows}
        self.assertEqual(names, {"Patrick Mahomes", "Saquon Barkley", "CeeDee Lamb", "Travis Kelce"})

    def test_zero_value_filtered_out(self):
        data = _make_players(
            ("Patrick Mahomes", "QB", 9500),
            ("Nobody", "RB", 0),
        )
        rows = dd._parse_players(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Patrick Mahomes")

    def test_none_value_filtered_out(self):
        data = [
            {"full_name": "Patrick Mahomes", "position": "QB", "sf_trade_value": 9500},
            {"full_name": "Ghost Player", "position": "RB", "sf_trade_value": None},
        ]
        rows = dd._parse_players(data)
        self.assertEqual(len(rows), 1)

    def test_rows_sorted_by_value_descending(self):
        data = _make_players(
            ("Third", "WR", 3000),
            ("First", "QB", 9500),
            ("Second", "RB", 7000),
        )
        rows = dd._parse_players(data)
        values = [r["value"] for r in rows]
        self.assertEqual(values, [9500, 7000, 3000])


class TestCsvOutputShape(unittest.TestCase):
    def test_csv_has_name_value_columns(self):
        data = _make_players(
            ("Patrick Mahomes", "QB", 9500),
            ("Saquon Barkley", "RB", 8200),
            ("CeeDee Lamb", "WR", 9000),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "dynasty_daddy.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = dd._DD_ROW_COUNT_FLOOR
            dd._DD_ROW_COUNT_FLOOR = 1
            try:
                rc = dd.main(
                    ["--from-file", str(json_path), "--dest", str(dest)]
                )
            finally:
                dd._DD_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertTrue(dest.exists())

            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 3)
            # Verify CSV columns are name,value (value signal, not rank).
            self.assertIn("name", rows[0])
            self.assertIn("value", rows[0])
            self.assertNotIn("Rank", rows[0])
            # Verify values are present and numeric.
            self.assertTrue(int(rows[0]["value"]) > 0)


class TestFromFileEndToEnd(unittest.TestCase):
    def test_from_file_writes_csv(self):
        data = _make_players(
            ("Patrick Mahomes", "QB", 9500),
            ("Saquon Barkley", "RB", 8200),
            ("CeeDee Lamb", "WR", 9000),
            ("Travis Kelce", "TE", 5500),
            ("Ja'Marr Chase", "WR", 9200),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "dynasty_daddy.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = dd._DD_ROW_COUNT_FLOOR
            dd._DD_ROW_COUNT_FLOOR = 1
            try:
                rc = dd.main(
                    ["--from-file", str(json_path), "--dest", str(dest)]
                )
            finally:
                dd._DD_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertTrue(dest.exists())

            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 5)
            names = {r["name"] for r in rows}
            self.assertIn("Patrick Mahomes", names)
            self.assertIn("Ja'Marr Chase", names)

    def test_idp_positions_filtered_out(self):
        """IDP positions should be silently dropped."""
        data = _make_players(
            ("Patrick Mahomes", "QB", 9500),
            ("Nick Bosa", "DE", 4000),
            ("CeeDee Lamb", "WR", 9000),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "dynasty_daddy.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = dd._DD_ROW_COUNT_FLOOR
            dd._DD_ROW_COUNT_FLOOR = 1
            try:
                rc = dd.main(
                    ["--from-file", str(json_path), "--dest", str(dest)]
                )
            finally:
                dd._DD_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 2)
            names = {r["name"] for r in rows}
            self.assertNotIn("Nick Bosa", names)


class TestMainExitCodes(unittest.TestCase):
    def test_main_exits_2_on_non_array_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "bad.json"
            json_path.write_text('{"not": "an array"}', encoding="utf-8")
            dest = tmp / "out.csv"
            rc = dd.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 2)
            self.assertFalse(dest.exists())

    def test_main_exits_2_on_row_count_floor_violation(self):
        # 2 players — below the default 400-row floor.
        data = _make_players(
            ("Patrick Mahomes", "QB", 9500),
            ("Saquon Barkley", "RB", 8200),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "small.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"
            # Use default floor (400) so this trips.
            rc = dd.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 2)

    def test_main_exits_1_on_empty_array(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "empty.json"
            json_path.write_text("[]", encoding="utf-8")
            dest = tmp / "out.csv"
            rc = dd.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 1)

    def test_main_exits_1_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "invalid.json"
            json_path.write_text("not json at all", encoding="utf-8")
            dest = tmp / "out.csv"
            rc = dd.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 1)


class TestDryRun(unittest.TestCase):
    def test_dry_run_does_not_write_csv(self):
        data = _make_players(
            ("Patrick Mahomes", "QB", 9500),
            ("Saquon Barkley", "RB", 8200),
            ("CeeDee Lamb", "WR", 9000),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "dynasty_daddy.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = dd._DD_ROW_COUNT_FLOOR
            dd._DD_ROW_COUNT_FLOOR = 1
            try:
                rc = dd.main(
                    [
                        "--from-file",
                        str(json_path),
                        "--dest",
                        str(dest),
                        "--dry-run",
                    ]
                )
            finally:
                dd._DD_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertFalse(dest.exists())


class TestNonTepMetadata(unittest.TestCase):
    """Dynasty Daddy is standard SF — NOT TE premium."""

    def test_source_is_not_tep_premium(self):
        from src.api.data_contract import get_ranking_source_registry

        registry = get_ranking_source_registry()
        dd_entry = None
        for src in registry:
            if src["key"] == "dynastyDaddySf":
                dd_entry = src
                break
        self.assertIsNotNone(dd_entry, "dynastyDaddySf not found in registry")
        self.assertFalse(
            dd_entry.get("isTepPremium"),
            "dynastyDaddySf must NOT be flagged as TEP premium",
        )

    def test_source_is_not_retail(self):
        from src.api.data_contract import get_ranking_source_registry

        registry = get_ranking_source_registry()
        dd_entry = None
        for src in registry:
            if src["key"] == "dynastyDaddySf":
                dd_entry = src
                break
        self.assertIsNotNone(dd_entry, "dynastyDaddySf not found in registry")
        self.assertFalse(
            dd_entry.get("isRetail"),
            "dynastyDaddySf must NOT be flagged as retail",
        )

    def test_source_scope_is_overall_offense(self):
        from src.api.data_contract import get_ranking_source_registry

        registry = get_ranking_source_registry()
        dd_entry = None
        for src in registry:
            if src["key"] == "dynastyDaddySf":
                dd_entry = src
                break
        self.assertIsNotNone(dd_entry, "dynastyDaddySf not found in registry")
        self.assertEqual(dd_entry.get("scope"), "overall_offense")


if __name__ == "__main__":
    unittest.main()
