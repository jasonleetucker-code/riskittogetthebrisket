"""Unit tests for src/adapters/scraper_bridge_adapter.py"""
from __future__ import annotations

import textwrap

import pytest

from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def value_adapter():
    return ScraperBridgeAdapter(
        source_id="KTC",
        source_bucket="offense_vet",
        signal_type="value",
    )


@pytest.fixture
def rank_adapter():
    return ScraperBridgeAdapter(
        source_id="IDPTRADECALC",
        source_bucket="idp_vet",
        signal_type="rank",
    )


@pytest.fixture
def value_csv(tmp_path):
    """Minimal value-based CSV matching legacy scraper export format."""
    content = textwrap.dedent("""\
        name,value
        Josh Allen,9050
        Ja'Marr Chase,8800
        Patrick Mahomes,8500
        2026 Early 1st,7000
    """)
    path = tmp_path / "ktc.csv"
    path.write_text(content)
    return path


@pytest.fixture
def rank_csv(tmp_path):
    """Minimal rank-based CSV."""
    content = textwrap.dedent("""\
        name,value
        Josh Allen,1
        Lamar Jackson,2
        Ja'Marr Chase,3
    """)
    path = tmp_path / "idpTradeCalc.csv"
    path.write_text(content)
    return path


# ── Constructor ───────────────────────────────────────────────────────

class TestConstructor:
    def test_valid_signal_types(self):
        ScraperBridgeAdapter("test", "test", signal_type="value")
        ScraperBridgeAdapter("test", "test", signal_type="rank")

    def test_invalid_signal_type_raises(self):
        with pytest.raises(ValueError, match="signal_type"):
            ScraperBridgeAdapter("test", "test", signal_type="invalid")


# ── Value-based loading ───────────────────────────────────────────────

class TestValueSignal:
    def test_loads_valid_csv(self, value_adapter, value_csv):
        result = value_adapter.load(value_csv)
        assert len(result.records) == 4
        assert not result.warnings

    def test_value_stored_as_value_raw(self, value_adapter, value_csv):
        result = value_adapter.load(value_csv)
        allen = result.records[0]
        assert allen.value_raw == 9050.0
        assert allen.rank_raw is None

    def test_record_fields(self, value_adapter, value_csv):
        result = value_adapter.load(value_csv)
        rec = result.records[0]
        assert rec.source == "KTC"
        assert rec.display_name == "Josh Allen"
        assert rec.name_normalized_guess == "josh allen"
        assert rec.asset_key == "player::josh allen"
        assert rec.universe == "offense_vet"
        assert rec.format_key == "dynasty_sf"
        assert rec.is_offense is True
        assert rec.is_idp is False
        assert rec.asset_type == "player"

    def test_apostrophe_name_normalized(self, value_adapter, value_csv):
        result = value_adapter.load(value_csv)
        chase = next(r for r in result.records if "Chase" in r.display_name)
        assert chase.name_normalized_guess == "ja marr chase"

    def test_metadata_contains_adapter_info(self, value_adapter, value_csv):
        result = value_adapter.load(value_csv)
        meta = result.records[0].metadata_json
        assert meta["adapter"] == "scraper_bridge"
        assert meta["signal_type"] == "value"
        assert "ktc.csv" in meta["profile_source"]


# ── Rank-based loading ────────────────────────────────────────────────

class TestRankSignal:
    def test_loads_valid_csv(self, rank_adapter, rank_csv):
        result = rank_adapter.load(rank_csv)
        assert len(result.records) == 3

    def test_value_stored_as_rank_raw(self, rank_adapter, rank_csv):
        result = rank_adapter.load(rank_csv)
        allen = result.records[0]
        assert allen.rank_raw == 1.0
        assert allen.value_raw is None

    def test_source_id_propagated(self, rank_adapter, rank_csv):
        result = rank_adapter.load(rank_csv)
        assert all(r.source == "IDPTRADECALC" for r in result.records)


# ── Edge cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_missing_file(self, value_adapter, tmp_path):
        result = value_adapter.load(tmp_path / "nonexistent.csv")
        assert len(result.records) == 0
        assert len(result.warnings) == 1
        assert "file not found" in result.warnings[0].lower()

    def test_empty_csv(self, value_adapter, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("name,value\n")
        result = value_adapter.load(path)
        assert len(result.records) == 0
        assert any("no usable rows" in w.lower() for w in result.warnings)

    def test_skips_rows_without_value(self, value_adapter, tmp_path):
        content = "name,value\nJosh Allen,\nLamar Jackson,8000\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = value_adapter.load(path)
        assert len(result.records) == 1
        assert result.records[0].display_name == "Lamar Jackson"

    def test_skips_rows_without_name(self, value_adapter, tmp_path):
        content = "name,value\n,9000\nJosh Allen,8000\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = value_adapter.load(path)
        assert len(result.records) == 1

    def test_utf8_bom_handled(self, value_adapter, tmp_path):
        content = "name,value\nJosh Allen,9000\n"
        path = tmp_path / "test.csv"
        path.write_text(content, encoding="utf-8-sig")
        result = value_adapter.load(path)
        assert len(result.records) == 1

    def test_idp_bucket_detection(self, tmp_path):
        adapter = ScraperBridgeAdapter("IDPTRADECALC", "idp_vet")
        content = "name,value\nMicah Parsons,5000\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert result.records[0].is_idp is True
        assert result.records[0].is_offense is False

    def test_non_numeric_value_skipped(self, value_adapter, tmp_path):
        content = "name,value\nJosh Allen,N/A\nLamar Jackson,8000\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = value_adapter.load(path)
        assert len(result.records) == 1

    def test_result_metadata(self, value_adapter, value_csv):
        result = value_adapter.load(value_csv)
        assert result.source_id == "KTC"
        assert result.source_bucket == "offense_vet"
        assert str(value_csv) in result.file_path


# ── Real KTC export ──────────────────────────────────────────────────

class TestRealKtcExport:
    """Test against the actual KTC CSV from the legacy scraper."""

    @pytest.fixture
    def real_csv(self):
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent.parent / "exports" / "latest" / "site_raw" / "ktc.csv"
        if not p.exists():
            pytest.skip("KTC export not available")
        return p

    def test_loads_real_export(self, value_adapter, real_csv):
        result = value_adapter.load(real_csv)
        assert len(result.records) > 100
        assert not result.warnings

    def test_top_players_have_high_values(self, value_adapter, real_csv):
        result = value_adapter.load(real_csv)
        top = sorted(result.records, key=lambda r: r.value_raw or 0, reverse=True)[:5]
        for rec in top:
            assert rec.value_raw > 5000

    def test_normalized_names_non_empty(self, value_adapter, real_csv):
        result = value_adapter.load(real_csv)
        for rec in result.records:
            assert rec.name_normalized_guess, f"Empty normalized name for {rec.display_name}"
            assert rec.asset_key.startswith("player::")
