"""Tests that the source config covers the allowed sources (KTC +
IDPTradeCalc + DLF IDP) and that missing CSVs are handled gracefully."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO / "config" / "sources" / "dlf_sources.template.json"
WEIGHTS_PATH = REPO / "config" / "weights" / "default_weights.json"

# The sources allowed after scope reduction.  KTC + IDPTradeCalc are the
# value-based market sources; DLF_IDP is a rank-based expert panel added
# as a second opinion on the overall_idp scope; FANTASYPROS_SF is a
# rank-based offense expert consensus (dynasty superflex).
ALLOWED_SOURCES = {"KTC", "IDPTRADECALC", "DLF_IDP", "FANTASYPROS_SF"}

EXPECTED_SCRAPER_EXPORTS = {
    "ktc.csv",
    "idpTradeCalc.csv",
    "dlfIdp.csv",
    "fantasyProsSf.csv",
}

# Sources whose scraper_bridge export is a ``name,value`` CSV (signal=value).
# DLF_IDP and FANTASYPROS_SF are the rank-signal exceptions.
VALUE_SIGNAL_SOURCES = {"KTC", "IDPTRADECALC"}
RANK_SIGNAL_SOURCES = {"DLF_IDP", "FANTASYPROS_SF"}


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
    def test_only_allowed_sources_enabled(self, config):
        enabled = {s["source"] for s in config["sources"] if s.get("enabled")}
        assert enabled == ALLOWED_SOURCES, f"Expected only {ALLOWED_SOURCES}, got {enabled}"

    def test_all_scraper_exports_have_config_entries(self, config):
        bridge_files = {
            Path(s["file"]).name for s in _enabled_bridge_sources(config)
        }
        missing = EXPECTED_SCRAPER_EXPORTS - bridge_files
        assert not missing, f"Missing config entries for scraper exports: {missing}"

    def test_every_source_declares_expected_signal_type(self, config):
        for src in _enabled_bridge_sources(config):
            source_id = src["source"]
            signal = src.get("signal_type")
            if source_id in VALUE_SIGNAL_SOURCES:
                assert signal == "value", (
                    f"{source_id} should be signal_type=value, got {signal!r}"
                )
            elif source_id in RANK_SIGNAL_SOURCES:
                assert signal == "rank", (
                    f"{source_id} should be signal_type=rank, got {signal!r}"
                )
            else:
                raise AssertionError(
                    f"Unknown source {source_id!r} in enabled bridge sources"
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

    def test_idptradecalc_has_idp_universe(self, config):
        """IDPTRADECALC canonical pipeline universe is idp_vet.
        The source covers offense via autocomplete, but the canonical pipeline
        uses idp_vet for record bucketing. The unified ranking model handles
        cross-universe sorting independently via canonicalSiteValues."""
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            if src["source"] == "IDPTRADECALC":
                assert "idp" in src.get("universe", "").lower(), (
                    f"IDPTRADECALC universe should contain 'idp', got {src.get('universe')}"
                )

    def test_weights_only_contain_allowed_sources(self, weights):
        source_weights = set(weights.get("sources", {}).keys())
        assert source_weights == ALLOWED_SOURCES, (
            f"Weights should only contain {ALLOWED_SOURCES}, got {source_weights}"
        )

    def test_dlf_idp_has_idp_universe(self, config):
        """DLF_IDP is a full-board IDP source; its canonical universe is
        idp_vet so its records get bucketed alongside IDPTradeCalc in the
        canonical pipeline."""
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            if src["source"] == "DLF_IDP":
                assert "idp" in src.get("universe", "").lower(), (
                    f"DLF_IDP universe should contain 'idp', got {src.get('universe')}"
                )


class TestTepSfFlags:
    """Verify TEP/SF flags in source config."""

    def test_all_sources_have_tep_sf_flags(self, config):
        """Every enabled source must declare includes_tep and includes_sf."""
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            assert "includes_tep" in src, f"{src['source']}: missing includes_tep flag"
            assert "includes_sf" in src, f"{src['source']}: missing includes_sf flag"

    def test_tep_native_sources_include_tep(self, config):
        """KTC and IDPTRADECALC natively include TEP; FANTASYPROS_SF does not."""
        tep_expected = {"KTC", "IDPTRADECALC", "DLF_IDP"}
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            if src["source"] in tep_expected:
                assert src.get("includes_tep") is True, (
                    f"{src['source']}: should have includes_tep=true"
                )
            else:
                # Sources that are NOT TEP-native must still declare the flag.
                assert "includes_tep" in src, (
                    f"{src['source']}: missing includes_tep flag"
                )

    def test_all_sources_include_sf(self, config):
        """All enabled sources natively include SF pricing."""
        for src in config["sources"]:
            if not src.get("enabled"):
                continue
            assert src.get("includes_sf") is True, (
                f"{src['source']}: should have includes_sf=true"
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
