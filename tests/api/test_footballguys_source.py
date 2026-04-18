"""Integration coverage for the FootballGuys Dynasty Rankings source.

Verifies:
    * The two CSV exports exist and are readable.
    * The parser's output shape matches what
      ``_enrich_from_source_csvs`` expects.
    * Both ``footballGuysSf`` and ``footballGuysIdp`` are registered
      in every place the rest of the pipeline looks for source keys.
    * The live export carries enriched ``canonicalSiteValues`` for
      players in both sub-boards.
"""
from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from src.api.data_contract import (
    _IDP_SIGNAL_KEYS,
    _OFFENSE_SIGNAL_KEYS,
    _RANKING_SOURCES,
    _SOURCE_CSV_PATHS,
    _DEFAULT_SOURCE_ROW_FLOORS,
    _SOURCE_MAX_AGE_HOURS,
    build_api_data_contract,
)

REPO = Path(__file__).resolve().parents[2]
SF_CSV = REPO / "CSVs" / "site_raw" / "footballGuysSf.csv"
IDP_CSV = REPO / "CSVs" / "site_raw" / "footballGuysIdp.csv"


class TestCsvExports(unittest.TestCase):
    """The parser's output lives on disk; every other test depends on it."""

    def test_sf_csv_exists_and_has_expected_columns(self) -> None:
        self.assertTrue(SF_CSV.exists(), f"Missing {SF_CSV}")
        with SF_CSV.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.assertIn("name", reader.fieldnames or [])
            self.assertIn("rank", reader.fieldnames or [])
            rows = list(reader)
        self.assertGreater(len(rows), 400, "SF CSV should have 400+ offensive rows")
        # Rank is 1..N contiguous.
        ranks = [int(r["rank"]) for r in rows]
        self.assertEqual(ranks, list(range(1, len(rows) + 1)))

    def test_idp_csv_exists_and_has_expected_columns(self) -> None:
        self.assertTrue(IDP_CSV.exists(), f"Missing {IDP_CSV}")
        with IDP_CSV.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.assertIn("name", reader.fieldnames or [])
            self.assertIn("rank", reader.fieldnames or [])
            rows = list(reader)
        self.assertGreater(len(rows), 300, "IDP CSV should have 300+ IDP rows")
        ranks = [int(r["rank"]) for r in rows]
        self.assertEqual(ranks, list(range(1, len(rows) + 1)))

    def test_csv_positions_split_correctly(self) -> None:
        import re

        def _family(pos: str) -> str:
            """Strip the trailing pos-rank number so "WR175" → "WR"."""
            m = re.match(r"^([A-Z]+)", pos)
            return m.group(1) if m else pos

        with SF_CSV.open("r", encoding="utf-8") as f:
            sf_families = {_family(row["position"]) for row in csv.DictReader(f)}
        with IDP_CSV.open("r", encoding="utf-8") as f:
            idp_families = {_family(row["position"]) for row in csv.DictReader(f)}
        # SF should be offense-only; IDP should be defense-only.
        self.assertTrue(sf_families <= {"QB", "RB", "WR", "TE"},
                        f"Non-offense families in SF: {sf_families - {'QB','RB','WR','TE'}}")
        self.assertTrue(idp_families <= {"DE", "DT", "LB", "CB", "S"},
                        f"Non-IDP families in IDP: {idp_families - {'DE','DT','LB','CB','S'}}")


class TestRegistryWiring(unittest.TestCase):
    """Both FBG sources must appear in every registration point so the
    enrichment path, floor checks, and staleness checks all recognize
    them.  Otherwise silent bugs like "source is loaded but no row
    floor means monitoring never fires" can slip in."""

    def test_both_keys_in_source_csv_paths(self) -> None:
        self.assertIn("footballGuysSf", _SOURCE_CSV_PATHS)
        self.assertIn("footballGuysIdp", _SOURCE_CSV_PATHS)

    def test_both_keys_in_source_max_age_hours(self) -> None:
        self.assertIn("footballGuysSf", _SOURCE_MAX_AGE_HOURS)
        self.assertIn("footballGuysIdp", _SOURCE_MAX_AGE_HOURS)

    def test_both_keys_have_row_count_floors(self) -> None:
        self.assertIn("footballGuysSf", _DEFAULT_SOURCE_ROW_FLOORS)
        self.assertIn("footballGuysIdp", _DEFAULT_SOURCE_ROW_FLOORS)

    def test_sf_key_in_offense_signal_keys(self) -> None:
        self.assertIn("footballGuysSf", _OFFENSE_SIGNAL_KEYS)

    def test_idp_key_in_idp_signal_keys(self) -> None:
        self.assertIn("footballGuysIdp", _IDP_SIGNAL_KEYS)

    def test_both_keys_in_ranking_sources_registry(self) -> None:
        keys = {s["key"] for s in _RANKING_SOURCES}
        self.assertIn("footballGuysSf", keys)
        self.assertIn("footballGuysIdp", keys)

    def test_sf_scope_is_overall_offense(self) -> None:
        entry = next(s for s in _RANKING_SOURCES if s["key"] == "footballGuysSf")
        self.assertEqual(entry["scope"], "overall_offense")
        self.assertFalse(entry["needs_shared_market_translation"])
        self.assertFalse(entry["excludes_rookies"])

    def test_idp_scope_is_overall_idp_with_shared_market_translation(self) -> None:
        entry = next(s for s in _RANKING_SOURCES if s["key"] == "footballGuysIdp")
        self.assertEqual(entry["scope"], "overall_idp")
        self.assertTrue(entry["needs_shared_market_translation"])
        self.assertFalse(entry["excludes_rookies"])


class TestLiveEnrichment(unittest.TestCase):
    """Roll the live contract and verify the new sources actually land
    on real players — catches name-normalization regressions that
    would silently drop match rates."""

    @classmethod
    def setUpClass(cls) -> None:
        export = REPO / "exports" / "latest"
        files = sorted(export.glob("dynasty_data_*.json"), reverse=True)
        if not files:
            cls.contract = None
            return
        with files[0].open("r", encoding="utf-8") as f:
            cls.raw = json.load(f)
        cls.contract = build_api_data_contract(cls.raw)

    def test_sf_source_matches_are_plausible(self) -> None:
        if self.contract is None:
            self.skipTest("No live data")
        pa = self.contract.get("playersArray") or []
        count = sum(
            1 for r in pa
            if isinstance((r.get("canonicalSiteValues") or {}).get("footballGuysSf"), (int, float))
            and (r.get("canonicalSiteValues") or {}).get("footballGuysSf") > 0
        )
        # Expect >= 400 matched rows (raw CSV is ~548, match rate ~85%).
        self.assertGreater(count, 400, f"Only {count} SF matches — likely a name-normalization regression")

    def test_idp_source_matches_are_plausible(self) -> None:
        if self.contract is None:
            self.skipTest("No live data")
        pa = self.contract.get("playersArray") or []
        count = sum(
            1 for r in pa
            if isinstance((r.get("canonicalSiteValues") or {}).get("footballGuysIdp"), (int, float))
            and (r.get("canonicalSiteValues") or {}).get("footballGuysIdp") > 0
        )
        # Expect >= 250 matched rows (raw CSV is ~406, match rate ~72%).
        self.assertGreater(count, 250, f"Only {count} IDP matches — likely a name-normalization regression")

    def test_source_ranks_stamped_for_elite_players(self) -> None:
        if self.contract is None:
            self.skipTest("No live data")
        pa = self.contract.get("playersArray") or []
        # Elite offensive player — must appear in FBG SF.
        allen = next((r for r in pa if r.get("canonicalName") == "Josh Allen"), None)
        self.assertIsNotNone(allen, "Josh Allen missing from live contract")
        ranks = allen.get("sourceRanks") or {}
        self.assertIn("footballGuysSf", ranks, "Josh Allen missing FBG SF rank")
        self.assertGreaterEqual(ranks["footballGuysSf"], 1)


if __name__ == "__main__":
    unittest.main()
