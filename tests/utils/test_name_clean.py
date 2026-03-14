"""Unit tests for src/utils/name_clean.py"""
from __future__ import annotations

import pytest

from src.utils.name_clean import normalize_player_name, normalize_position_family, normalize_team


# ── normalize_player_name ────────────────────────────────────────────

class TestNormalizePlayerName:
    def test_basic_name(self):
        assert normalize_player_name("Patrick Mahomes") == "patrick mahomes"

    def test_strips_suffix_jr(self):
        assert normalize_player_name("Marvin Harrison Jr.") == "marvin harrison"
        assert normalize_player_name("Marvin Harrison Jr") == "marvin harrison"

    def test_strips_suffix_sr(self):
        assert normalize_player_name("Some Player Sr.") == "some player"

    def test_strips_suffix_roman_numerals(self):
        assert normalize_player_name("Robert Griffin III") == "robert griffin"
        assert normalize_player_name("Kenneth Walker III") == "kenneth walker"
        assert normalize_player_name("Player Name II") == "player name"

    def test_ascii_folds_accents(self):
        # Jérémy -> jeremy
        assert normalize_player_name("Jérémy Chinn") == "jeremy chinn"

    def test_ampersand_replacement(self):
        assert normalize_player_name("Bert & Ernie") == "bert and ernie"

    def test_strips_non_alphanumeric(self):
        # Apostrophe becomes space, then collapses
        assert normalize_player_name("D'Andre Swift") == "d andre swift"

    def test_collapses_whitespace(self):
        assert normalize_player_name("  Travis    Kelce  ") == "travis kelce"

    def test_empty_input(self):
        assert normalize_player_name("") == ""
        assert normalize_player_name(None) == ""

    def test_only_suffix(self):
        # Edge case: name is just "Jr."
        assert normalize_player_name("Jr.") == ""

    def test_preserves_numbers_in_names(self):
        # Pick names like "2026 1st" should keep numbers
        assert normalize_player_name("2026 1st Round") == "2026 1st round"


# ── normalize_team ───────────────────────────────────────────────────

class TestNormalizeTeam:
    def test_basic_team(self):
        assert normalize_team("kc") == "KC"

    def test_strips_whitespace(self):
        assert normalize_team("  dal  ") == "DAL"

    def test_empty_input(self):
        assert normalize_team("") == ""
        assert normalize_team(None) == ""

    def test_ascii_folds(self):
        assert normalize_team("Montréal") == "MONTREAL"


# ── normalize_position_family ────────────────────────────────────────

class TestNormalizePositionFamily:
    @pytest.mark.parametrize("input_pos,expected", [
        ("QB", "QB"),
        ("qb", "QB"),
        ("RB", "RB"),
        ("WR", "WR"),
        ("TE", "TE"),
    ])
    def test_offensive_positions(self, input_pos, expected):
        assert normalize_position_family(input_pos) == expected

    @pytest.mark.parametrize("input_pos,expected", [
        ("DE", "DL"),
        ("DT", "DL"),
        ("DL", "DL"),
        ("EDGE", "DL"),
    ])
    def test_defensive_line(self, input_pos, expected):
        assert normalize_position_family(input_pos) == expected

    @pytest.mark.parametrize("input_pos,expected", [
        ("LB", "LB"),
        ("ILB", "LB"),
        ("OLB", "LB"),
    ])
    def test_linebackers(self, input_pos, expected):
        assert normalize_position_family(input_pos) == expected

    @pytest.mark.parametrize("input_pos,expected", [
        ("S", "DB"),
        ("SS", "DB"),
        ("FS", "DB"),
        ("CB", "DB"),
        ("DB", "DB"),
    ])
    def test_defensive_backs(self, input_pos, expected):
        assert normalize_position_family(input_pos) == expected

    def test_empty_input(self):
        assert normalize_position_family("") == ""
        assert normalize_position_family(None) == ""

    def test_parenthesized_position(self):
        # Some sources use "(QB)" or "QB (Starter)"
        assert normalize_position_family("(QB)") == "QB"

    def test_multi_token_takes_first(self):
        assert normalize_position_family("QB WR") == "QB"

    def test_unknown_position_passthrough(self):
        assert normalize_position_family("K") == "K"
        assert normalize_position_family("P") == "P"
