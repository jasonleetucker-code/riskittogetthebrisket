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

RANK_BASED_EXPORTS = {"draftSharks.csv", "draftSharksIdp.csv", "dynastyNerds.csv", "pffIdp.csv", "fantasyProsIdp.csv"}


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


class TestTepSfFlags:
    """Verify TEP/SF flags in source config match legacy scraper behavior."""

    # Legacy scraper _tep_sites: these sources natively include TEP
    LEGACY_TEP_SITES = {"ktc", "fantasyCalc", "fantasyPros", "draftSharks",
                        "yahoo", "dynastyNerds", "idpTradeCalc"}

    def test_tep_flags_match_legacy_scraper(self, config):
        """Sources the legacy scraper considers TEP-native must have includes_tep=true."""
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            fname = Path(src.get("file", "")).stem
            is_tep_in_legacy = fname in self.LEGACY_TEP_SITES

            # IDP-only sources are exempt (TEP doesn't apply to IDP)
            universe = src.get("universe", "")
            if "idp" in universe.lower() and src["source"] not in ("IDPTRADECALC",):
                continue

            # DLF sources use rank_avg mode and are always non-TEP
            if src.get("adapter") == "dlf_csv":
                assert src.get("includes_tep") is False, (
                    f"{src['source']}: DLF rank-based sources should have includes_tep=false"
                )
                continue

            if is_tep_in_legacy:
                assert src.get("includes_tep") is True, (
                    f"{src['source']} (file={fname}): legacy scraper lists this in _tep_sites, "
                    f"but includes_tep={src.get('includes_tep')}"
                )

    def test_all_sources_have_tep_sf_flags(self, config):
        """Every enabled source must declare includes_tep and includes_sf."""
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            assert "includes_tep" in src, f"{src['source']}: missing includes_tep flag"
            assert "includes_sf" in src, f"{src['source']}: missing includes_sf flag"

    def test_offense_vet_sources_are_sf(self, config):
        """All offense_vet sources should be scraped in SF mode."""
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            if src.get("universe") == "offense_vet":
                assert src.get("includes_sf") is True, (
                    f"{src['source']}: offense_vet source should have includes_sf=true"
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
