"""Unit tests for scripts/fetch_flock_fantasy_rookies.py.

Covers:
  * JSON schema probe (non-dict / malformed response)
  * Player parsing with position filtering (offense only)
  * Draft pick filtering (isDraftPick == true excluded)
  * averageRank values are present and reasonable (rank signal format)
  * End-to-end fixture build: ``--from-file`` with a tiny JSON blob
  * Exit-code behaviour for schema regressions and row-count floors
  * Registry metadata: rookie translation, scope, non-TEP, non-retail
  * Dry-run mode
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import fetch_flock_fantasy_rookies as ffr


def _make_api_response(
    *entries: tuple[str, str, float, bool],
) -> dict:
    """Build a Flock Fantasy PROSPECTS_SF API response shape.

    entries = (playerName, position, averageRank, isDraftPick).
    """
    return {
        "format": "PROSPECTS_SF",
        "year": 2026,
        "data": [
            {
                "playerName": name,
                "position": pos,
                "averageRank": rank,
                "isDraftPick": is_pick,
                "isRookie": True,
            }
            for name, pos, rank, is_pick in entries
        ],
    }


class TestParsePlayersSchemaProbe(unittest.TestCase):
    def test_non_dict_raises_schema_error(self):
        with self.assertRaises(ffr.FlockFantasyRookiesSchemaError):
            ffr._parse_players([{"playerName": "Test"}])

    def test_missing_data_key_raises_schema_error(self):
        with self.assertRaises(ffr.FlockFantasyRookiesSchemaError):
            ffr._parse_players({"format": "PROSPECTS_SF"})

    def test_data_not_list_raises_schema_error(self):
        with self.assertRaises(ffr.FlockFantasyRookiesSchemaError):
            ffr._parse_players({"data": "not a list"})

    def test_empty_data_returns_empty(self):
        self.assertEqual(ffr._parse_players({"data": []}), [])


class TestParsePlayersPositionFilter(unittest.TestCase):
    def test_only_offense_positions_kept(self):
        data = _make_api_response(
            ("Jeremiyah Love", "RB", 1.0, False),
            ("Carnell Tate", "WR", 2.71, False),
            ("Fernando Mendoza", "QB", 4.43, False),
            ("Lake McRee", "TE", 93.0, False),
            ("Some IDP Prospect", "DE", 50.0, False),
            ("Another IDP Prospect", "LB", 55.0, False),
        )
        rows = ffr._parse_players(data)
        self.assertEqual(len(rows), 4)
        names = {r["name"] for r in rows}
        self.assertEqual(
            names,
            {"Jeremiyah Love", "Carnell Tate", "Fernando Mendoza", "Lake McRee"},
        )

    def test_draft_picks_filtered_out(self):
        data = _make_api_response(
            ("Jeremiyah Love", "RB", 1.0, False),
            ("2026 1.01", "QB", 5.0, True),
            ("2026 1.02", "RB", 8.0, True),
        )
        rows = ffr._parse_players(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Jeremiyah Love")

    def test_non_rookies_filtered_out(self):
        """Defensive ``isRookie=False`` filter — the rookie ladder
        downstream would mis-scale any veteran row that slipped through."""
        data = {
            "data": [
                {
                    "playerName": "Jeremiyah Love",
                    "position": "RB",
                    "averageRank": 1.0,
                    "isDraftPick": False,
                    "isRookie": True,
                },
                {
                    "playerName": "Some Veteran",
                    "position": "WR",
                    "averageRank": 5.0,
                    "isDraftPick": False,
                    "isRookie": False,
                },
            ]
        }
        rows = ffr._parse_players(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Jeremiyah Love")

    def test_missing_isRookie_field_is_rejected(self):
        """Strict ``isRookie is True`` filter — rows lacking the flag
        are dropped to preserve the rookie-only invariant the
        downstream rookie ladder depends on."""
        data = {
            "data": [
                {
                    "playerName": "Jeremiyah Love",
                    "position": "RB",
                    "averageRank": 1.0,
                    "isDraftPick": False,
                    "isRookie": True,
                },
                {
                    "playerName": "No Flag Player",
                    "position": "WR",
                    "averageRank": 2.0,
                    "isDraftPick": False,
                    # isRookie deliberately omitted
                },
                {
                    "playerName": "Null Flag Player",
                    "position": "WR",
                    "averageRank": 3.0,
                    "isDraftPick": False,
                    "isRookie": None,
                },
            ]
        }
        rows = ffr._parse_players(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Jeremiyah Love")

    def test_non_dict_entries_are_skipped(self):
        """Malformed rows (e.g. ``null``) in the ``data`` array must
        not abort the whole fetch — skip them and keep the valid rows."""
        data = {
            "data": [
                None,
                {
                    "playerName": "Jeremiyah Love",
                    "position": "RB",
                    "averageRank": 1.0,
                    "isDraftPick": False,
                    "isRookie": True,
                },
                "string instead of dict",
                42,
                {
                    "playerName": "Carnell Tate",
                    "position": "WR",
                    "averageRank": 2.71,
                    "isDraftPick": False,
                    "isRookie": True,
                },
            ]
        }
        rows = ffr._parse_players(data)
        self.assertEqual(len(rows), 2)
        names = {r["name"] for r in rows}
        self.assertEqual(names, {"Jeremiyah Love", "Carnell Tate"})

    def test_none_averageRank_filtered_out(self):
        data = {
            "data": [
                {
                    "playerName": "Jeremiyah Love",
                    "position": "RB",
                    "averageRank": 1.0,
                    "isDraftPick": False,
                    "isRookie": True,
                },
                {
                    "playerName": "Ghost Player",
                    "position": "WR",
                    "averageRank": None,
                    "isDraftPick": False,
                    "isRookie": True,
                },
            ]
        }
        rows = ffr._parse_players(data)
        self.assertEqual(len(rows), 1)

    def test_rows_sorted_by_rank_ascending(self):
        data = _make_api_response(
            ("Third", "WR", 45.0, False),
            ("First", "RB", 1.0, False),
            ("Second", "QB", 12.5, False),
        )
        rows = ffr._parse_players(data)
        ranks = [r["Rank"] for r in rows]
        self.assertEqual(ranks, [1.0, 12.5, 45.0])


class TestCsvOutputShape(unittest.TestCase):
    def test_csv_has_name_rank_columns(self):
        """CSV columns should be name,Rank (rank signal, not value)."""
        data = _make_api_response(
            ("Jeremiyah Love", "RB", 1.0, False),
            ("Carnell Tate", "WR", 2.71, False),
            ("Fernando Mendoza", "QB", 4.43, False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "flock_rookies.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = ffr._FF_ROOKIE_ROW_COUNT_FLOOR
            ffr._FF_ROOKIE_ROW_COUNT_FLOOR = 1
            try:
                rc = ffr.main(
                    ["--from-file", str(json_path), "--dest", str(dest)]
                )
            finally:
                ffr._FF_ROOKIE_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertTrue(dest.exists())

            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 3)
            self.assertIn("name", rows[0])
            self.assertIn("Rank", rows[0])
            self.assertNotIn("value", rows[0])
            self.assertAlmostEqual(float(rows[0]["Rank"]), 1.0, places=2)


class TestFromFileEndToEnd(unittest.TestCase):
    def test_from_file_writes_csv(self):
        data = _make_api_response(
            ("Jeremiyah Love", "RB", 1.0, False),
            ("Makai Lemon", "WR", 2.57, False),
            ("Carnell Tate", "WR", 2.71, False),
            ("Fernando Mendoza", "QB", 4.43, False),
            ("Lake McRee", "TE", 93.0, False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "flock_rookies.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = ffr._FF_ROOKIE_ROW_COUNT_FLOOR
            ffr._FF_ROOKIE_ROW_COUNT_FLOOR = 1
            try:
                rc = ffr.main(
                    ["--from-file", str(json_path), "--dest", str(dest)]
                )
            finally:
                ffr._FF_ROOKIE_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 5)
            names = {r["name"] for r in rows}
            self.assertIn("Jeremiyah Love", names)
            self.assertIn("Lake McRee", names)


class TestMainExitCodes(unittest.TestCase):
    def test_main_exits_2_on_non_dict_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "bad.json"
            json_path.write_text('["not", "a dict"]', encoding="utf-8")
            dest = tmp / "out.csv"
            rc = ffr.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 2)
            self.assertFalse(dest.exists())

    def test_main_exits_2_on_row_count_floor_violation(self):
        # 2 players — below the default 60-row floor.
        data = _make_api_response(
            ("Jeremiyah Love", "RB", 1.0, False),
            ("Carnell Tate", "WR", 2.71, False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "small.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"
            rc = ffr.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 2)

    def test_main_exits_1_on_empty_data_array(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "empty.json"
            json_path.write_text('{"data": []}', encoding="utf-8")
            dest = tmp / "out.csv"
            rc = ffr.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 1)

    def test_main_exits_1_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "invalid.json"
            json_path.write_text("not json at all", encoding="utf-8")
            dest = tmp / "out.csv"
            rc = ffr.main(["--from-file", str(json_path), "--dest", str(dest)])
            self.assertEqual(rc, 1)


class TestDryRun(unittest.TestCase):
    def test_dry_run_does_not_write_csv(self):
        data = _make_api_response(
            ("Jeremiyah Love", "RB", 1.0, False),
            ("Carnell Tate", "WR", 2.71, False),
            ("Fernando Mendoza", "QB", 4.43, False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "flock_rookies.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = ffr._FF_ROOKIE_ROW_COUNT_FLOOR
            ffr._FF_ROOKIE_ROW_COUNT_FLOOR = 1
            try:
                rc = ffr.main(
                    [
                        "--from-file",
                        str(json_path),
                        "--dest",
                        str(dest),
                        "--dry-run",
                    ]
                )
            finally:
                ffr._FF_ROOKIE_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertFalse(dest.exists())


class TestRegistryMetadata(unittest.TestCase):
    """Pin the source's registry shape: scope, rookie-translation, flags."""

    def _entry(self):
        from src.api.data_contract import get_ranking_source_registry

        for src in get_ranking_source_registry():
            if src["key"] == "flockFantasySfRookies":
                return src
        return None

    def test_source_registered(self):
        self.assertIsNotNone(
            self._entry(), "flockFantasySfRookies not in registry"
        )

    def test_scope_overall_offense(self):
        entry = self._entry()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.get("scope"), "overall_offense")

    def test_not_tep_premium(self):
        entry = self._entry()
        self.assertIsNotNone(entry)
        self.assertFalse(entry.get("isTepPremium"))

    def test_not_retail(self):
        entry = self._entry()
        self.assertIsNotNone(entry)
        self.assertFalse(entry.get("isRetail"))

    def test_scraper_export_registered(self):
        from src.api.data_contract import _SOURCE_CSV_PATHS

        self.assertIn("flockFantasySfRookies", _SOURCE_CSV_PATHS)
        cfg = _SOURCE_CSV_PATHS["flockFantasySfRookies"]
        self.assertEqual(cfg.get("signal"), "rank")
        self.assertEqual(
            cfg.get("path"), "CSVs/site_raw/flockFantasySfRookies.csv"
        )

    def test_needs_rookie_translation_flag(self):
        from src.api.data_contract import _RANKING_SOURCES

        for src in _RANKING_SOURCES:
            if src.get("key") == "flockFantasySfRookies":
                self.assertTrue(
                    src.get("needs_rookie_translation"),
                    "flockFantasySfRookies must declare needs_rookie_translation=True",
                )
                return
        self.fail("flockFantasySfRookies not found in _RANKING_SOURCES")


if __name__ == "__main__":
    unittest.main()
