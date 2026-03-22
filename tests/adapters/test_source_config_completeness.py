"""Tests that the source config covers all expected scraper exports
and that missing CSVs are handled gracefully."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO / "config" / "sources" / "dlf_sources.template.json"
WEIGHTS_PATH = REPO / "config" / "weights" / "default_weights.json"

# Every CSV filename the scraper's site_key_map would produce
EXPECTED_SCRAPER_EXPORTS = {
    "fantasyCalc.csv",
    "ktc.csv",
    "dynastyDaddy.csv",
    "fantasyPros.csv",
    "draftSharks.csv",
    "yahoo.csv",
    "dynastyNerds.csv",
    "flock.csv",
    "idpTradeCalc.csv",
    "pffIdp.csv",
    "draftSharksIdp.csv",
    "fantasyProsIdp.csv",
}

RANK_BASED_EXPORTS = {"draftSharks.csv", "dynastyNerds.csv", "pffIdp.csv", "fantasyProsIdp.csv"}


@pytest.fixture
def config():
    return json.loads(CONFIG_PATH.read_text())


@pytest.fixture
def weights():
    return json.loads(WEIGHTS_PATH.read_text())


def _enabled_bridge_sources(cfg):
    return [
        s for s in cfg["sources"]
        if s.get("enabled") and s.get("adapter") in ("scraper_bridge", "bridge")
    ]


class TestSourceConfigCompleteness:
    def test_all_scraper_exports_have_config_entries(self, config):
        bridge_files = {
            Path(s["file"]).name for s in _enabled_bridge_sources(config)
        }
        missing = EXPECTED_SCRAPER_EXPORTS - bridge_files
        assert not missing, f"Missing config entries for scraper exports: {missing}"

    def test_rank_based_sources_have_correct_signal_type(self, config):
        for src in _enabled_bridge_sources(config):
            fname = Path(src["file"]).name
            if fname in RANK_BASED_EXPORTS:
                assert src.get("signal_type") == "rank", (
                    f"{src['source']} ({fname}) should be signal_type=rank"
                )
            else:
                assert src.get("signal_type") == "value", (
                    f"{src['source']} ({fname}) should be signal_type=value"
                )

    def test_every_enabled_source_has_a_weight(self, config, weights):
        source_weights = weights.get("sources", {})
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            source_id = src["source"]
            assert source_id in source_weights, (
                f"Source {source_id} is enabled but has no weight entry"
            )

    def test_no_duplicate_source_ids(self, config):
        enabled = [s["source"] for s in config["sources"] if s.get("enabled")]
        assert len(enabled) == len(set(enabled)), (
            f"Duplicate source IDs: {[s for s in enabled if enabled.count(s) > 1]}"
        )

    def test_idp_sources_have_idp_universe(self, config):
        idp_sources = {"IDPTRADECALC", "PFF_IDP", "DRAFTSHARKS_IDP", "FANTASYPROS_IDP", "DLF_IDP", "DLF_RIDP"}
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            if src["source"] in idp_sources:
                assert "idp" in src.get("universe", "").lower(), (
                    f"IDP source {src['source']} should have an IDP universe, got {src.get('universe')}"
                )


class TestScraperBridgeGracefulMissing:
    def test_missing_csv_produces_warning_not_error(self):
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter
        adapter = ScraperBridgeAdapter(
            source_id="TEST_MISSING",
            source_bucket="offense_vet",
            signal_type="value",
        )
        result = adapter.load(Path("/nonexistent/path/test.csv"))
        assert len(result.records) == 0
        assert len(result.warnings) > 0
        assert "not found" in result.warnings[0].lower()

    def test_empty_path_produces_warning_not_error(self):
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter
        adapter = ScraperBridgeAdapter(
            source_id="TEST_EMPTY",
            source_bucket="offense_vet",
            signal_type="value",
        )
        result = adapter.load(Path(""))
        assert len(result.records) == 0
        assert len(result.warnings) > 0

    def test_directory_path_produces_warning_not_error(self, tmp_path):
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter
        adapter = ScraperBridgeAdapter(
            source_id="TEST_DIR",
            source_bucket="offense_vet",
            signal_type="value",
        )
        result = adapter.load(tmp_path)
        assert len(result.records) == 0
        assert len(result.warnings) > 0
