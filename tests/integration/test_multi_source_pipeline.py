"""Integration tests for the two-source canonical pipeline (KTC + IDPTradeCalc).

Tests the pipeline path: source pull -> canonical build -> blending with only
the two allowed sources.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class TestTwoSourceBlending:
    def test_scraper_bridge_loads_ktc(self):
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter
        ktc_path = REPO / "CSVs" / "site_raw" / "ktc.csv"
        if not ktc_path.exists():
            pytest.skip("ktc.csv not present in exports")
        adapter = ScraperBridgeAdapter(
            source_id="KTC", source_bucket="offense_vet", signal_type="value"
        )
        result = adapter.load(ktc_path)
        assert len(result.records) >= 100
        assert len(result.warnings) == 0

    def test_scraper_bridge_loads_idptradecalc(self):
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter
        idp_path = REPO / "CSVs" / "site_raw" / "idpTradeCalc.csv"
        if not idp_path.exists():
            pytest.skip("idpTradeCalc.csv not present in exports")
        adapter = ScraperBridgeAdapter(
            source_id="IDPTRADECALC", source_bucket="idp_vet", signal_type="value"
        )
        result = adapter.load(idp_path)
        assert len(result.records) >= 100
        assert len(result.warnings) == 0

    def test_two_source_blend_produces_values(self):
        """Test blending KTC + IDPTradeCalc."""
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter
        from src.canonical.transform import (
            per_source_scores_for_universe,
            blend_source_values,
        )
        from src.data_models import RawAssetRecord

        ktc_path = REPO / "CSVs" / "site_raw" / "ktc.csv"
        idp_path = REPO / "CSVs" / "site_raw" / "idpTradeCalc.csv"
        if not ktc_path.exists() or not idp_path.exists():
            pytest.skip("Required CSV exports not present")

        # KTC
        ktc = ScraperBridgeAdapter(source_id="KTC", source_bucket="offense_vet", signal_type="value")
        ktc_result = ktc.load(ktc_path)

        # IDPTradeCalc
        idp = ScraperBridgeAdapter(source_id="IDPTRADECALC", source_bucket="idp_vet", signal_type="value")
        idp_result = idp.load(idp_path)

        # Blend offense_vet (KTC only for this universe)
        weights = {"KTC": 1.2, "IDPTRADECALC": 1.0}
        per_source_offense = per_source_scores_for_universe(ktc_result.records)
        assert "KTC" in per_source_offense

        offense_assets = blend_source_values(per_source_offense, weights, "offense_vet")
        assert len(offense_assets) > 100

        # Blend idp_vet (IDPTradeCalc only for this universe)
        per_source_idp = per_source_scores_for_universe(idp_result.records)
        assert "IDPTRADECALC" in per_source_idp

        idp_assets = blend_source_values(per_source_idp, weights, "idp_vet")
        assert len(idp_assets) > 50
