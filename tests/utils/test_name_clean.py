"""Unit tests for src/utils/name_clean.py"""

from __future__ import annotations

import pytest

from src.utils.name_clean import (
    CANONICAL_NAME_ALIASES,
    compact_name_key,
    normalize_player_name,
    normalize_position_family,
    normalize_team,
    resolve_canonical_name,
)


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
        assert normalize_player_name("Kenneth Walker III") == normalize_player_name(
            "Kenneth Walker"
        )
        assert normalize_player_name("Marvin Harrison Jr.") == normalize_player_name(
            "Marvin Harrison"
        )
        assert normalize_player_name("Marvin Harrison Jr") == normalize_player_name(
            "Marvin Harrison"
        )
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
    @pytest.mark.parametrize(
        "input_pos,expected",
        [
            ("QB", "QB"),
            ("qb", "QB"),
            ("RB", "RB"),
            ("WR", "WR"),
            ("TE", "TE"),
        ],
    )
    def test_offensive_positions(self, input_pos, expected):
        assert normalize_position_family(input_pos) == expected

    @pytest.mark.parametrize(
        "input_pos,expected",
        [
            ("DE", "DL"),
            ("DT", "DL"),
            ("DL", "DL"),
            ("EDGE", "DL"),
        ],
    )
    def test_defensive_line(self, input_pos, expected):
        assert normalize_position_family(input_pos) == expected

    @pytest.mark.parametrize(
        "input_pos,expected",
        [
            ("LB", "LB"),
            ("ILB", "LB"),
            ("OLB", "LB"),
        ],
    )
    def test_linebackers(self, input_pos, expected):
        assert normalize_position_family(input_pos) == expected

    @pytest.mark.parametrize(
        "input_pos,expected",
        [
            ("S", "DB"),
            ("SS", "DB"),
            ("FS", "DB"),
            ("CB", "DB"),
            ("DB", "DB"),
        ],
    )
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
        # Truly-unknown tokens pass through unchanged...
        assert normalize_position_family("K") == "K"
        # ...but punter collapses into the kicker family by design
        # (POSITION_ALIASES "P" -> "K" / _KICKER_FAMILIES). This
        # expectation was stale: a duplicate test class (F811) had
        # shadowed this suite so the assertion never ran.
        assert normalize_position_family("P") == "K"


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

    @pytest.mark.parametrize(
        "input_pos,expected",
        [
            ("NT", "DL"),  # Nose tackle — maps to DL in canonical aliases
            ("FLEX", "FLEX"),  # Fantasy position
            ("SUPER_FLEX", "SUPER"),  # startswith check takes first token
        ],
    )
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


class TestNormalizePositionFamilyStandardCases:
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


# ── 2026-07 identity-sweep aliases ───────────────────────────────────
# Each pair below is a vendor spelling that used to drop the player's
# vote at the CSV → pool join (see docs/identity-audit-2026-07.md).
# The alias table must collapse the vendor form onto the pool form.


class TestIdentitySweepAliases:
    RECOVERED = [
        # (vendor spelling as it appears in the source CSV, pool spelling)
        ("Kenneth Gainwell", "Kenny Gainwell"),
        ("Gabriel Davis", "Gabe Davis"),
        ("Alim McNeil", "Alim McNeill"),
        ("Andru Phillips", "Dru Phillips"),
        ("Camryn Bynum", "Cam Bynum"),
        ("Nickolas Martin", "Nick Martin"),
        ("Josh Palmer", "Joshua Palmer"),
        ("Cameron Skattebo", "Cam Skattebo"),
        ("Cameron Ward", "Cam Ward"),
        ("Nathan Landman", "Nate Landman"),
        ("Patrick Surtain II", "Pat Surtain"),
        ("Daxton Hill", "Dax Hill"),
        ("Donaven McCulley", "Donoven McCulley"),
        ("Chauncey Gardner-Johnson", "C.J. Gardner-Johnson"),
        ("Michael Jackson", "Mike Jackson"),
        ("Ahmad Gardner", "Sauce Gardner"),
        ("Justin Madubuike", "Nnamdi Madubuike"),
        ("Robert Henry Jr.", "Rob Henry"),
    ]

    @pytest.mark.parametrize("vendor,pool", RECOVERED)
    def test_vendor_spelling_collapses_to_pool_spelling(self, vendor, pool):
        assert resolve_canonical_name(vendor) == resolve_canonical_name(pool)
        # ... and the shared key is the pool form's normalized name so
        # the CSV join lands on the existing pool row.
        assert resolve_canonical_name(vendor) == normalize_player_name(pool)

    def test_alias_keys_are_normalize_stable(self):
        # Every key must be the output of normalize_player_name for
        # some raw spelling — i.e. renormalizing the key is a no-op.
        # A non-stable key can never be hit by the join and is dead.
        for key in CANONICAL_NAME_ALIASES:
            assert normalize_player_name(key) == key, key

    def test_alias_values_are_fixed_points(self):
        # No chained aliases: resolving a value must return itself.
        # A chain (a → b, b → c) would make the join key depend on
        # how many times the resolver runs.
        for key, value in CANONICAL_NAME_ALIASES.items():
            assert normalize_player_name(value) == value, (key, value)
            assert CANONICAL_NAME_ALIASES.get(value, value) == value, (key, value)


# ── compact_name_key (key family 2) ──────────────────────────────────


class TestCompactNameKey:
    """The compact key is a DIFFERENT family from ``normalize_player_name``.

    It was previously defined twice, character-identically, in
    ``src/adapters/ktc_crowd_faab.py`` and
    ``src/roster_intel/roster_source.py``; both now delegate here.  These
    tests pin the properties that make it non-interchangeable with the
    strict key, so a future "consolidation" cannot quietly collapse the
    two families.
    """

    def test_drops_punctuation_and_spaces(self):
        assert compact_name_key("D.J. Moore") == "djmoore"
        assert compact_name_key("DJ Moore") == "djmoore"
        assert compact_name_key("djmoore") == "djmoore"
        assert compact_name_key("Ja'Marr Chase") == "jamarrchase"

    def test_null_and_empty(self):
        assert compact_name_key(None) == ""
        assert compact_name_key("") == ""
        assert compact_name_key("   ") == ""

    def test_does_not_strip_generational_suffixes(self):
        # This is the property that makes it NOT a drop-in for the
        # strict key.  Swapping the two changes which roster rows
        # collide.
        assert compact_name_key("Kenneth Walker III") == "kennethwalkeriii"
        assert compact_name_key("Kenneth Walker") == "kennethwalker"
        assert compact_name_key("Kenneth Walker III") != compact_name_key("Kenneth Walker")
        assert normalize_player_name("Kenneth Walker III") == normalize_player_name(
            "Kenneth Walker"
        )

    def test_does_not_ascii_fold(self):
        # ``str.isalnum()`` is Unicode-aware, so accented characters
        # survive.  The frontend's ``waiver-logic.normalizeNameCompact``
        # strips them (``[^a-z0-9]``), which is why the two are
        # documented as INDEPENDENT rather than as a parity pair — three
        # docstrings used to claim byte-for-byte agreement and were
        # wrong.  Changing this would move the roster_intel value join
        # and the KTC crowd FAAB map for every accented name; measure
        # first.
        assert compact_name_key("Juanyéh Thomas") == "juanyéhthomas"
        assert normalize_player_name("Juanyéh Thomas") == "juanyeh thomas"

    def test_the_merged_call_sites_still_share_this_definition(self):
        """``roster_source.normalize_name`` is a PUBLIC deprecated alias
        (it is in that module's ``__all__``), so it is pinned here.

        ``ktc_crowd_faab`` used to carry an equivalent ``_normalize_name``
        alias and it is deliberately gone: private, unused by its own
        module, and referenced only by this test — i.e. kept alive purely
        by being asserted.  What actually matters there is that the
        producer keys with this function, which
        ``test_faab_producer_and_consumer_agree`` below pins directly.
        """
        from src.adapters import ktc_crowd_faab
        from src.roster_intel import roster_source

        assert roster_source.normalize_name is compact_name_key
        assert not hasattr(
            ktc_crowd_faab, "_normalize_name"
        ), "the dead private alias is back; nothing should re-export it"

    def test_faab_producer_and_consumer_agree(self):
        """Regression for the live defect this consolidation surfaced.

        ``build_crowd_bid_map`` keys with the compact key; the
        recommender used to look up with ``strip().lower()``, so the
        crowd calibration factor never fired for any name containing a
        space — i.e. every real player.

        The consumer moved when the FAAB engine landed: the crowd bid
        is no longer blended into the bid as a multiplier (that was one
        of four separate readings of the same demand signal).  It is
        now surfaced as demand EVIDENCE by
        ``_demand_evidence_factors``.  The name-key parity this test
        exists for is unchanged, so the assertion follows the consumer
        rather than being deleted with the old blender.
        """
        from src.adapters.ktc_crowd_faab import build_crowd_bid_map
        from src.trade.faab_recommender import _demand_evidence_factors

        crowd = build_crowd_bid_map(
            {
                "waivers": [
                    {"added": "T.J. Watt", "bid": 20, "settings": {"waiver_budget": 100}},
                    {"added": "T.J. Watt", "bid": 20, "settings": {"waiver_budget": 100}},
                ]
            }
        )
        assert crowd == {"tjwatt": 20.0}

        rows = _demand_evidence_factors(None, crowd, "T.J. Watt")
        # A missing row here would mean the spaced, punctuated display
        # name failed to join the compact-keyed map.
        crowd_rows = [r for r in rows if r["label"] == "Crowd-sourced bid"]
        assert len(crowd_rows) == 1
        assert "20%" in crowd_rows[0]["contribution"]
