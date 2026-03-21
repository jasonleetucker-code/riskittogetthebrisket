"""Unit tests for src/adapters/dlf_csv_adapter.py"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.adapters.dlf_csv_adapter import DlfCsvAdapter, _first_present, _parse_rank


# ── Helper function tests ────────────────────────────────────────────

class TestFirstPresent:
    def test_finds_first_match(self):
        row = {"Name": "Josh Allen", "Pos": "QB"}
        assert _first_present(row, "name") == "Josh Allen"

    def test_case_insensitive(self):
        row = {"NAME": "Josh Allen"}
        assert _first_present(row, "name") == "Josh Allen"

    def test_falls_through_empty(self):
        row = {"name": "", "player": "Josh Allen"}
        assert _first_present(row, "name", "player") == "Josh Allen"

    def test_returns_empty_when_missing(self):
        row = {"team": "BUF"}
        assert _first_present(row, "name", "player") == ""


class TestParseRank:
    def test_valid_float(self):
        assert _parse_rank("1.5") == 1.5

    def test_valid_int(self):
        assert _parse_rank("42") == 42.0

    def test_empty_string(self):
        assert _parse_rank("") is None

    def test_non_numeric(self):
        assert _parse_rank("N/A") is None


# ── Adapter integration tests ────────────────────────────────────────

@pytest.fixture
def adapter():
    return DlfCsvAdapter(source_id="dlf_sf", source_bucket="offense_vet")


@pytest.fixture
def csv_file(tmp_path):
    """Create a minimal valid DLF CSV."""
    content = textwrap.dedent("""\
        name,pos,team,avg
        Patrick Mahomes,QB,KC,1.5
        Josh Allen,QB,BUF,2.3
        Ja'Marr Chase,WR,CIN,3.0
    """)
    path = tmp_path / "dlf_superflex.csv"
    path.write_text(content)
    return path


class TestDlfCsvAdapter:
    def test_loads_valid_csv(self, adapter, csv_file):
        result = adapter.load(csv_file)
        assert len(result.records) == 3
        assert not result.warnings

    def test_record_fields(self, adapter, csv_file):
        result = adapter.load(csv_file)
        rec = result.records[0]
        assert rec.source == "dlf_sf"
        assert rec.display_name == "Patrick Mahomes"
        assert rec.rank_raw == 1.5
        assert rec.asset_type == "player"
        assert rec.name_normalized_guess == "patrick mahomes"
        assert rec.position_normalized_guess == "QB"
        assert rec.team_normalized_guess == "KC"
        assert rec.asset_key == "player::patrick mahomes"
        assert rec.universe == "offense_vet"

    def test_apostrophe_name_normalized(self, adapter, csv_file):
        result = adapter.load(csv_file)
        chase = result.records[2]
        # Apostrophe in Ja'Marr becomes space
        assert chase.name_normalized_guess == "ja marr chase"

    def test_missing_file(self, adapter, tmp_path):
        result = adapter.load(tmp_path / "nonexistent.csv")
        assert len(result.records) == 0
        assert len(result.warnings) == 1
        assert "Missing file" in result.warnings[0]

    def test_skips_empty_name_rows(self, adapter, tmp_path):
        content = textwrap.dedent("""\
            name,pos,team,avg
            ,QB,KC,1.0
            Josh Allen,QB,BUF,2.0
        """)
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert len(result.records) == 1

    def test_alternative_column_names(self, adapter, tmp_path):
        content = textwrap.dedent("""\
            player_name,position,team,rank
            Lamar Jackson,QB,BAL,1.0
        """)
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert len(result.records) == 1
        assert result.records[0].display_name == "Lamar Jackson"
        assert result.records[0].rank_raw == 1.0

    def test_idp_bucket_sets_flag(self, tmp_path):
        adapter = DlfCsvAdapter(source_id="dlf_idp", source_bucket="idp_vet")
        content = textwrap.dedent("""\
            name,pos,team,avg
            Micah Parsons,EDGE,DAL,1.0
        """)
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert result.records[0].is_idp is True
        assert result.records[0].is_offense is False

    def test_malformed_csv_tolerant_parse(self, adapter, tmp_path):
        # DictReader handles unclosed quotes by concatenating lines, so the
        # normal parser may not fail. Verify we still get records either way.
        content = "name,pos,team,avg\n"
        content += "Josh Allen,QB,BUF,2.0\n"
        content += '"Broken Row\n'
        content += "Lamar Jackson,QB,BAL,3.0\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert len(result.records) >= 1

    def test_result_metadata(self, adapter, csv_file):
        result = adapter.load(csv_file)
        assert result.source_id == "dlf_sf"
        assert result.source_bucket == "offense_vet"
        assert result.file_path == str(csv_file)

    def test_format_key_passthrough(self, tmp_path):
        adapter = DlfCsvAdapter(source_id="dlf_sf", source_bucket="offense_vet", format_key="dynasty_1qb")
        content = "name,pos,team,avg\nPatrick Mahomes,QB,KC,1.0\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert result.records[0].format_key == "dynasty_1qb"

    def test_rank_column_fallback_order(self, adapter, tmp_path):
        """avg takes priority over rank column."""
        content = "name,pos,team,avg,rank\nJosh Allen,QB,BUF,2.5,10.0\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert result.records[0].rank_raw == 2.5

    def test_row_without_rank_still_loads(self, adapter, tmp_path):
        """Rows without any rank-like column still produce records with rank_raw=None."""
        content = "name,pos,team\nJosh Allen,QB,BUF\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert len(result.records) == 1
        assert result.records[0].rank_raw is None

    def test_utf8_bom_handled(self, adapter, tmp_path):
        """Files with BOM should parse correctly (utf-8-sig encoding)."""
        content = "name,pos,team,avg\nJosh Allen,QB,BUF,1.0\n"
        path = tmp_path / "test.csv"
        # Write with utf-8-sig which prepends the BOM byte sequence
        path.write_text(content, encoding="utf-8-sig")
        result = adapter.load(path)
        assert len(result.records) == 1
        assert result.records[0].display_name == "Josh Allen"

    def test_duplicate_player_names_both_kept(self, adapter, tmp_path):
        """Two rows with same name should produce two records."""
        content = "name,pos,team,avg\nJosh Allen,QB,BUF,1.0\nJosh Allen,LB,JAX,50.0\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert len(result.records) == 2

    def test_metadata_json_contains_raw_values(self, adapter, csv_file):
        result = adapter.load(csv_file)
        meta = result.records[0].metadata_json
        assert meta["raw_avg"] == "1.5"
        assert meta["raw_pos"] == "QB"
        assert meta["raw_team"] == "KC"
        assert "dlf_superflex.csv" in meta["profile_source"]

    def test_rookie_bucket_detection(self, tmp_path):
        adapter = DlfCsvAdapter(source_id="dlf_rk", source_bucket="offense_rookie")
        content = "name,pos,team,avg\nCaleb Williams,QB,CHI,1.0\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert result.records[0].is_offense is True
        assert result.records[0].is_idp is False

    def test_empty_csv_returns_no_records(self, adapter, tmp_path):
        """CSV with only header row."""
        content = "name,pos,team,avg\n"
        path = tmp_path / "test.csv"
        path.write_text(content)
        result = adapter.load(path)
        assert len(result.records) == 0
        assert not result.warnings
