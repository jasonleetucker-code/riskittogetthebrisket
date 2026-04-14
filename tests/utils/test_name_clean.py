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

    def test_known_suffix_players_all_normalize_identically(self):
        """Players with Jr/Sr/III suffixes must all collapse to the same key."""
        assert normalize_player_name("Kenneth Walker III") == normalize_player_name("Kenneth Walker")
        assert normalize_player_name("Marvin Harrison Jr.") == normalize_player_name("Marvin Harrison")
        assert normalize_player_name("Marvin Harrison Jr") == normalize_player_name("Marvin Harrison")
        assert normalize_player_name("Brian Thomas Jr.") == normalize_player_name("Brian Thomas")
        assert normalize_player_name("Brian Thomas Jr") == normalize_player_name("Brian Thomas")
        assert normalize_player_name("Omar Cooper Jr.") == normalize_player_name("Omar Cooper")
        assert normalize_player_name("Omar Cooper Jr") == normalize_player_name("Omar Cooper")
        assert normalize_player_name("Michael Penix Jr.") == normalize_player_name("Michael Penix")
        assert normalize_player_name("Michael Penix Jr") == normalize_player_name("Michael Penix")

    def test_ascii_folds_accents(self):
        # Jérémy -> jeremy
        assert normalize_player_name("Jérémy Chinn") == "jeremy chinn"

    def test_ampersand_replacement(self):
        assert normalize_player_name("Bert & Ernie") == "bert and ernie"

    def test_strips_non_alphanumeric(self):
        # Apostrophes are dropped *without* inserting a space so
        # "D'Andre" / "DAndre" / "D\u2019Andre" all collide on the
        # same key.  Hyphens and periods continue to split tokens.
        assert normalize_player_name("D'Andre Swift") == "dandre swift"
        assert normalize_player_name("DAndre Swift") == "dandre swift"
        assert normalize_player_name("D\u2019Andre Swift") == "dandre swift"

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


# ── Dynasty-specific name edge cases ─────────────────────────────────

class TestDynastyNameEdgeCases:
    """Real player names that have historically caused matching failures."""

    def test_hyphenated_first_name(self):
        # Amon-Ra St. Brown — hyphen becomes space, period stripped
        result = normalize_player_name("Amon-Ra St. Brown")
        assert "amon" in result
        assert "ra" in result
        assert "brown" in result

    def test_period_initials(self):
        # T.J. Hockenson — periods become spaces
        result = normalize_player_name("T.J. Hockenson")
        assert "hockenson" in result
        assert "t" in result
        assert "j" in result

    def test_apostrophe_variants(self):
        # Straight, curly, and modifier-letter apostrophes all collapse
        # the token without inserting a space so "Ja'Marr Chase",
        # "Ja\u2019Marr Chase", and "JaMarr Chase" all match.
        base = normalize_player_name("Ja'Marr Chase")
        assert base == "jamarr chase"
        assert normalize_player_name("Ja\u2019Marr Chase") == base
        assert normalize_player_name("JaMarr Chase") == base
        # Backtick is still non-alphanumeric and is treated as a
        # separator (it's not an apostrophe).
        assert normalize_player_name("Ja`Marr Chase") == "ja marr chase"

    def test_suffix_iv(self):
        assert normalize_player_name("Chris Olave IV") == "chris olave"

    def test_suffix_v_alone(self):
        # "V" as suffix — regex \bv\b should match
        assert normalize_player_name("Player Name V") == "player name"

    def test_pick_string_preserved(self):
        # Pick tokens should survive normalization intact
        result = normalize_player_name("2026 Early 1st")
        assert "2026" in result
        assert "1st" in result

    def test_compound_hyphenated_last_name(self):
        # Jaxon Smith-Njigba — hyphen becomes space
        result = normalize_player_name("Jaxon Smith-Njigba")
        assert "jaxon" in result
        assert "smith" in result
        assert "njigba" in result

    def test_double_suffix_stripped(self):
        # Edge case: name has both Jr and III (shouldn't happen but shouldn't crash)
        result = normalize_player_name("Player Name Jr. III")
        assert result == "player name"

    def test_non_ascii_name(self):
        # José -> jose
        assert normalize_player_name("José Rodríguez") == "jose rodriguez"

    def test_all_whitespace(self):
        assert normalize_player_name("   ") == ""


class TestNormalizePositionFamilyEdgeCases:
    """Position strings seen across different data sources."""

    @pytest.mark.parametrize("input_pos,expected", [
        ("NT", "DL"),       # Nose tackle — maps to DL in canonical aliases
        ("FLEX", "FLEX"),   # Fantasy position
        ("SUPER_FLEX", "SUPER"),  # startswith check takes first token
    ])
    def test_fantasy_and_rare_positions(self, input_pos, expected):
        assert normalize_position_family(input_pos) == expected

    def test_lowercase_edge(self):
        assert normalize_position_family("edge") == "DL"

    def test_mixed_case_ilb(self):
        assert normalize_position_family("Ilb") == "LB"

    def test_position_with_number_suffix(self):
        # "QB1" — startswith("QB") is true
        assert normalize_position_family("QB1") == "QB"

    def test_slash_separated_position(self):
        # "DE/DT" — non-alnum becomes space, takes first token
        result = normalize_position_family("DE/DT")
        assert result == "DL"


class TestNormalizeTeamEdgeCases:
    def test_three_letter_abbreviation(self):
        assert normalize_team("buf") == "BUF"
        assert normalize_team("SF") == "SF"

    def test_full_team_name_passthrough(self):
        # Full names just get uppercased
        assert normalize_team("Kansas City") == "KANSAS CITY"

    def test_none_returns_empty(self):
        assert normalize_team(None) == ""


# ── normalize_position_family ──────────────────────────────────────

class TestNormalizePositionFamily:
    # Standard positions
    def test_qb(self):
        assert normalize_position_family("QB") == "QB"

    def test_rb(self):
        assert normalize_position_family("RB") == "RB"

    def test_wr(self):
        assert normalize_position_family("WR") == "WR"

    def test_te(self):
        assert normalize_position_family("TE") == "TE"

    # IDP positions
    def test_dl(self):
        assert normalize_position_family("DL") == "DL"

    def test_de_maps_to_dl(self):
        assert normalize_position_family("DE") == "DL"

    def test_dt_maps_to_dl(self):
        assert normalize_position_family("DT") == "DL"

    def test_edge_maps_to_dl(self):
        assert normalize_position_family("EDGE") == "DL"

    def test_lb(self):
        assert normalize_position_family("LB") == "LB"

    def test_ilb_maps_to_lb(self):
        assert normalize_position_family("ILB") == "LB"

    def test_olb_maps_to_lb(self):
        assert normalize_position_family("OLB") == "LB"

    def test_db(self):
        assert normalize_position_family("DB") == "DB"

    def test_cb_maps_to_db(self):
        assert normalize_position_family("CB") == "DB"

    def test_s_maps_to_db(self):
        assert normalize_position_family("S") == "DB"

    def test_ss_maps_to_db(self):
        assert normalize_position_family("SS") == "DB"

    def test_fs_maps_to_db(self):
        assert normalize_position_family("FS") == "DB"

    # Sleeper dual positions — DL or DB always win over LB
    def test_dl_lb_prefers_dl(self):
        assert normalize_position_family("DL/LB") == "DL"

    def test_lb_dl_prefers_dl(self):
        assert normalize_position_family("LB/DL") == "DL"

    def test_de_lb_prefers_dl(self):
        assert normalize_position_family("DE/LB") == "DL"

    def test_db_lb_prefers_db(self):
        assert normalize_position_family("DB/LB") == "DB"

    def test_lb_db_prefers_db(self):
        assert normalize_position_family("LB/DB") == "DB"

    def test_cb_lb_prefers_db(self):
        assert normalize_position_family("CB/LB") == "DB"

    def test_s_lb_prefers_db(self):
        assert normalize_position_family("S/LB") == "DB"

    def test_edge_lb_prefers_dl(self):
        assert normalize_position_family("EDGE/LB") == "DL"

    # Edge cases
    def test_empty(self):
        assert normalize_position_family("") == ""

    def test_none(self):
        assert normalize_position_family(None) == ""

    def test_lowercase(self):
        assert normalize_position_family("qb") == "QB"

    def test_dl_lb_lowercase(self):
        assert normalize_position_family("dl/lb") == "DL"
