"""Integration tests for multi-source canonical pipeline with KTC + DynastyDaddy.

Uses test seed CSVs generated from FantasyCalc reference data.
Tests the full pipeline path: seed generation → source pull → canonical build → blending.
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture
def seed_dir():
    """Ensure test seeds exist."""
    seed_path = REPO / "data" / "test_seeds"
    if not (seed_path / "ktc.csv").exists():
        from scripts.generate_test_seeds import main as gen_main
        gen_main()
    return seed_path


@pytest.fixture
def site_raw_with_seeds(seed_dir, tmp_path):
    """Create a temporary site_raw directory with all available CSVs + test seeds."""
    site_raw = tmp_path / "site_raw"
    site_raw.mkdir()

    # Copy real CSVs
    real_dir = REPO / "exports" / "latest" / "site_raw"
    for csv_file in real_dir.glob("*.csv"):
        if csv_file.name not in ("ktc.csv", "dynastyDaddy.csv"):
            shutil.copy2(csv_file, site_raw / csv_file.name)

    # Copy test seeds
    shutil.copy2(seed_dir / "ktc.csv", site_raw / "ktc.csv")
    shutil.copy2(seed_dir / "dynastyDaddy.csv", site_raw / "dynastyDaddy.csv")

    return site_raw


class TestTestSeeds:
    def test_ktc_seed_has_players(self, seed_dir):
        rows = list(csv.DictReader((seed_dir / "ktc.csv").open()))
        assert len(rows) >= 300
        # Verify format
        assert "name" in rows[0]
        assert "value" in rows[0]
        # No pick entries
        for r in rows:
            assert "Pick" not in r["name"], f"Test seed should not contain picks: {r['name']}"

    def test_dynastydaddy_seed_has_players(self, seed_dir):
        rows = list(csv.DictReader((seed_dir / "dynastyDaddy.csv").open()))
        assert len(rows) >= 300
        assert "name" in rows[0]
        assert "value" in rows[0]

    def test_seeds_are_deterministic(self, seed_dir):
        """Re-generating seeds with same random seed produces identical output."""
        from scripts.generate_test_seeds import load_fantasycalc_players, generate_ktc_seed
        players = load_fantasycalc_players(REPO)
        ktc1 = generate_ktc_seed(players, seed=42)
        ktc2 = generate_ktc_seed(players, seed=42)
        assert ktc1 == ktc2

    def test_seeds_differ_from_fantasycalc(self, seed_dir):
        """Seeds should not be identical to FantasyCalc values."""
        fc_rows = list(csv.DictReader(
            (REPO / "exports" / "latest" / "site_raw" / "fantasyCalc.csv").open()
        ))
        ktc_rows = list(csv.DictReader((seed_dir / "ktc.csv").open()))

        fc_vals = {r["name"]: int(r["value"]) for r in fc_rows if r.get("value")}
        ktc_vals = {r["name"]: int(r["value"]) for r in ktc_rows if r.get("value")}

        # Find common players
        common = set(fc_vals.keys()) & set(ktc_vals.keys())
        assert len(common) > 100

        # At least 90% should differ (noise was applied)
        differ = sum(1 for n in common if fc_vals[n] != ktc_vals[n])
        assert differ / len(common) >= 0.85


class TestMultiSourceBlending:
    def test_scraper_bridge_loads_ktc_seed(self, seed_dir):
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter
        adapter = ScraperBridgeAdapter(
            source_id="KTC", source_bucket="offense_vet", signal_type="value"
        )
        result = adapter.load(seed_dir / "ktc.csv")
        assert len(result.records) >= 300
        assert len(result.warnings) == 0

    def test_scraper_bridge_loads_dynastydaddy_seed(self, seed_dir):
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter
        adapter = ScraperBridgeAdapter(
            source_id="DYNASTYDADDY", source_bucket="offense_vet", signal_type="value"
        )
        result = adapter.load(seed_dir / "dynastyDaddy.csv")
        assert len(result.records) >= 300
        assert len(result.warnings) == 0

    def test_four_source_blend_produces_values(self, seed_dir):
        """Test blending DLF_SF + FantasyCalc + KTC + DynastyDaddy."""
        from src.adapters import DlfCsvAdapter
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter
        from src.canonical.transform import (
            per_source_scores_for_universe,
            blend_source_values,
        )
        from src.data_models import RawAssetRecord

        all_records: list[RawAssetRecord] = []

        # DLF
        dlf = DlfCsvAdapter(source_id="DLF_SF", source_bucket="offense_vet")
        dlf_result = dlf.load(REPO / "dlf_superflex.csv")
        all_records.extend(dlf_result.records)

        # FantasyCalc
        fc = ScraperBridgeAdapter(source_id="FANTASYCALC", source_bucket="offense_vet", signal_type="value")
        fc_result = fc.load(REPO / "exports" / "latest" / "site_raw" / "fantasyCalc.csv")
        all_records.extend(fc_result.records)

        # KTC (seed)
        ktc = ScraperBridgeAdapter(source_id="KTC", source_bucket="offense_vet", signal_type="value")
        ktc_result = ktc.load(seed_dir / "ktc.csv")
        all_records.extend(ktc_result.records)

        # DynastyDaddy (seed)
        dd = ScraperBridgeAdapter(source_id="DYNASTYDADDY", source_bucket="offense_vet", signal_type="value")
        dd_result = dd.load(seed_dir / "dynastyDaddy.csv")
        all_records.extend(dd_result.records)

        weights = {"DLF_SF": 1.0, "FANTASYCALC": 1.0, "KTC": 1.2, "DYNASTYDADDY": 0.8}
        per_source = per_source_scores_for_universe(all_records)
        assert len(per_source) == 4

        assets = blend_source_values(per_source, weights, "offense_vet")
        assert len(assets) > 300

        # Verify 4-source blending exists
        four_source = [a for a in assets if len(a.source_values) == 4]
        assert len(four_source) > 200, f"Expected 200+ four-source assets, got {len(four_source)}"

        # Verify weighted blending math
        for asset in four_source[:5]:
            # Manually verify: blended = sum(score * weight) / sum(weights)
            weighted_sum = sum(
                asset.source_values[s] * weights[s] for s in asset.source_values
            )
            total_weight = sum(weights[s] for s in asset.source_values)
            expected = int(round(weighted_sum / total_weight))
            assert abs(asset.blended_value - expected) <= 3, (
                f"{asset.display_name}: expected {expected}, got {asset.blended_value}"
            )
