"""Unit tests for scripts/fetch_flock_fantasy.py.

Covers:
  * JSON schema probe (non-dict / malformed response)
  * Player parsing with position filtering
  * Draft pick filtering (isDraftPick == true excluded)
  * averageRank values are present and reasonable (rank signal format)
  * End-to-end fixture build: ``--from-file`` with a tiny JSON blob
  * Exit-code behaviour for schema regressions and row-count floors
  * Non-TEP metadata (standard SF scoring)
  * Dry-run mode
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import fetch_flock_fantasy as ff


def _make_api_response(
    *entries: tuple[str, str, float, bool],
) -> dict:
    """Build a Flock Fantasy API response shape.

    entries = (playerName, position, averageRank, isDraftPick).
    """
    return {
        "format": "superflex",
        "year": 2026,
        "data": [
            {
                "playerName": name,
                "position": pos,
                "averageRank": rank,
                "isDraftPick": is_pick,
            }
            for name, pos, rank, is_pick in entries
        ],
    }


class TestParsePlayersSchemaProbe(unittest.TestCase):
    def test_non_dict_raises_schema_error(self):
        with self.assertRaises(ff.FlockFantasySchemaError):
            ff._parse_players([{"playerName": "Test"}])

    def test_missing_data_key_raises_schema_error(self):
        with self.assertRaises(ff.FlockFantasySchemaError):
            ff._parse_players({"format": "superflex"})

    def test_data_not_list_raises_schema_error(self):
        with self.assertRaises(ff.FlockFantasySchemaError):
            ff._parse_players({"data": "not a list"})

    def test_empty_data_returns_empty(self):
        self.assertEqual(ff._parse_players({"data": []}), [])


class TestParsePlayersPositionFilter(unittest.TestCase):
    def test_only_offense_positions_kept(self):
        data = _make_api_response(
            ("Patrick Mahomes", "QB", 1.63, False),
            ("Saquon Barkley", "RB", 12.5, False),
            ("CeeDee Lamb", "WR", 3.50, False),
            ("Travis Kelce", "TE", 45.0, False),
            ("Nick Bosa", "DE", 50.0, False),
            ("T.J. Watt", "LB", 55.0, False),
        )
        rows = ff._parse_players(data)
        self.assertEqual(len(rows), 4)
        names = {r["name"] for r in rows}
        self.assertEqual(names, {"Patrick Mahomes", "Saquon Barkley", "CeeDee Lamb", "Travis Kelce"})

    def test_draft_picks_filtered_out(self):
        data = _make_api_response(
            ("Patrick Mahomes", "QB", 1.63, False),
            ("2026 1.01", "QB", 5.0, True),
            ("2026 1.02", "RB", 8.0, True),
        )
        rows = ff._parse_players(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Patrick Mahomes")

    def test_none_averageRank_filtered_out(self):
        data = {
            "data": [
                {"playerName": "Patrick Mahomes", "position": "QB", "averageRank": 1.63, "isDraftPick": False},
                {"playerName": "Ghost Player", "position": "RB", "averageRank": None, "isDraftPick": False},
            ]
        }
        rows = ff._parse_players(data)
        self.assertEqual(len(rows), 1)

    def test_rows_sorted_by_rank_ascending(self):
        data = _make_api_response(
            ("Third", "WR", 45.0, False),
            ("First", "QB", 1.63, False),
            ("Second", "RB", 12.5, False),
        )
        rows = ff._parse_players(data)
        ranks = [r["Rank"] for r in rows]
        self.assertEqual(ranks, [1.63, 12.5, 45.0])


class TestCsvOutputShape(unittest.TestCase):
    def test_csv_has_name_rank_columns(self):
        """CSV columns should be name,Rank (rank signal, not value)."""
        data = _make_api_response(
            ("Patrick Mahomes", "QB", 1.63, False),
            ("Saquon Barkley", "RB", 12.5, False),
            ("CeeDee Lamb", "WR", 3.50, False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "flock_fantasy.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = ff._FF_ROW_COUNT_FLOOR
            ff._FF_ROW_COUNT_FLOOR = 1
            try:
                rc = ff.main(
                    ["--from-file", str(json_path), "--dest", str(dest)]
                )
            finally:
                ff._FF_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertTrue(dest.exists())

            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 3)
            # Verify CSV columns are name,Rank (rank signal, not value).
            self.assertIn("name", rows[0])
            self.assertIn("Rank", rows[0])
            self.assertNotIn("value", rows[0])
            # Verify ranks are present and numeric with decimal precision.
            self.assertAlmostEqual(float(rows[0]["Rank"]), 1.63, places=2)


class TestFromFileEndToEnd(unittest.TestCase):
    def test_from_file_writes_csv(self):
        data = _make_api_response(
            ("Patrick Mahomes", "QB", 1.63, False),
            ("Saquon Barkley", "RB", 12.5, False),
            ("CeeDee Lamb", "WR", 3.50, False),
            ("Travis Kelce", "TE", 45.0, False),
            ("Ja'Marr Chase", "WR", 2.13, False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "flock_fantasy.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = ff._FF_ROW_COUNT_FLOOR
            ff._FF_ROW_COUNT_FLOOR = 1
            try:
                rc = ff.main(
                    ["--from-file", str(json_path), "--dest", str(dest)]
                )
            finally:
                ff._FF_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertTrue(dest.exists())

            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 5)
            names = {r["name"] for r in rows}
            self.assertIn("Patrick Mahomes", names)
            self.assertIn("Ja'Marr Chase", names)

    def test_idp_positions_filtered_out(self):
        """IDP positions should be silently dropped."""
        data = _make_api_response(
            ("Patrick Mahomes", "QB", 1.63, False),
            ("Nick Bosa", "DE", 50.0, False),
            ("CeeDee Lamb", "WR", 3.50, False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "flock_fantasy.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = ff._FF_ROW_COUNT_FLOOR
            ff._FF_ROW_COUNT_FLOOR = 1
            try:
                rc = ff.main(
                    ["--from-file", str(json_path), "--dest", str(dest)]
                )
            finally:
                ff._FF_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 2)
            names = {r["name"] for r in rows}
            self.assertNotIn("Nick Bosa", names)


class TestMainExitCodes(unittest.TestCase):
    def test_main_exits_2_on_non_dict_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "bad.json"
            json_path.write_text('["not", "a dict"]', encoding="utf-8")
            dest = tmp / "out.csv"
            rc = ff.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 2)
            self.assertFalse(dest.exists())

    def test_main_exits_2_on_row_count_floor_violation(self):
        # 2 players — below the default 250-row floor.
        data = _make_api_response(
            ("Patrick Mahomes", "QB", 1.63, False),
            ("Saquon Barkley", "RB", 12.5, False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "small.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"
            # Use default floor (250) so this trips.
            rc = ff.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 2)

    def test_main_exits_1_on_empty_data_array(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "empty.json"
            json_path.write_text('{"data": []}', encoding="utf-8")
            dest = tmp / "out.csv"
            rc = ff.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 1)

    def test_main_exits_1_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "invalid.json"
            json_path.write_text("not json at all", encoding="utf-8")
            dest = tmp / "out.csv"
            rc = ff.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 1)


class TestDryRun(unittest.TestCase):
    def test_dry_run_does_not_write_csv(self):
        data = _make_api_response(
            ("Patrick Mahomes", "QB", 1.63, False),
            ("Saquon Barkley", "RB", 12.5, False),
            ("CeeDee Lamb", "WR", 3.50, False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "flock_fantasy.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = ff._FF_ROW_COUNT_FLOOR
            ff._FF_ROW_COUNT_FLOOR = 1
            try:
                rc = ff.main(
                    [
                        "--from-file",
                        str(json_path),
                        "--dest",
                        str(dest),
                        "--dry-run",
                    ]
                )
            finally:
                ff._FF_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertFalse(dest.exists())


class TestNonTepMetadata(unittest.TestCase):
    """Flock Fantasy is standard SF — NOT TE premium."""

    def test_source_is_not_tep_premium(self):
        from src.api.data_contract import get_ranking_source_registry

        registry = get_ranking_source_registry()
        ff_entry = None
        for src in registry:
            if src["key"] == "flockFantasySf":
                ff_entry = src
                break
        self.assertIsNotNone(ff_entry, "flockFantasySf not found in registry")
        self.assertFalse(
            ff_entry.get("isTepPremium"),
            "flockFantasySf must NOT be flagged as TEP premium",
        )

    def test_source_is_not_retail(self):
        from src.api.data_contract import get_ranking_source_registry

        registry = get_ranking_source_registry()
        ff_entry = None
        for src in registry:
            if src["key"] == "flockFantasySf":
                ff_entry = src
                break
        self.assertIsNotNone(ff_entry, "flockFantasySf not found in registry")
        self.assertFalse(
            ff_entry.get("isRetail"),
            "flockFantasySf must NOT be flagged as retail",
        )

    def test_source_scope_is_overall_offense(self):
        from src.api.data_contract import get_ranking_source_registry

        registry = get_ranking_source_registry()
        ff_entry = None
        for src in registry:
            if src["key"] == "flockFantasySf":
                ff_entry = src
                break
        self.assertIsNotNone(ff_entry, "flockFantasySf not found in registry")
        self.assertEqual(ff_entry.get("scope"), "overall_offense")


if __name__ == "__main__":
    unittest.main()
