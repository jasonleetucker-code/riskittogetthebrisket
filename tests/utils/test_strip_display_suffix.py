"""``strip_display_suffix`` — display-name cleanup, not a join key.

N3, 2026-07-29 audit round 2.

``sleeper_overlay._resolve_player_label`` falls back to the raw Sleeper
``full_name`` when the loaded contract's id map misses a player id.
Sleeper keeps generational suffixes; the contract's vocabulary — built
by ``Dynasty Scraper.py::clean_name`` — does not.  Measured on the live
payload: **0 of 1076** contract keys carry ``Jr.`` / ``III`` or a
trailing parenthetical.

So that fallback emitted a label in a foreign vocabulary into
``sleeper.teams[].players``, which is name-keyed and read by waiver
ownership, angle, replacement and FAAB contention.

This helper is deliberately the ODD ONE OUT in ``name_clean``: every
other function there lowercases, because they build join keys.  This
one preserves case and spacing because its output is rendered.
"""

from __future__ import annotations

import pytest

from src.utils.name_clean import normalize_player_name, strip_display_suffix


class TestStripsWhatSleeperAdds:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Marvin Harrison Jr.", "Marvin Harrison"),
            ("Marvin Harrison Jr", "Marvin Harrison"),
            ("Kenneth Walker III", "Kenneth Walker"),
            ("Robert Griffin III", "Robert Griffin"),
            ("Some Player Sr.", "Some Player"),
            ("Player Name II", "Player Name"),
            ("Player Name IV", "Player Name"),
            ("Odell Beckham Jr.", "Odell Beckham"),
            # Comma form
            ("Marvin Harrison, Jr.", "Marvin Harrison"),
        ],
    )
    def test_generational_suffixes(self, raw, expected):
        assert strip_display_suffix(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Michael Pittman (WR)", "Michael Pittman"),
            ("Some Guy (IR)", "Some Guy"),
            ("Name Here  (DEN)  ", "Name Here"),
        ],
    )
    def test_trailing_parentheticals(self, raw, expected):
        assert strip_display_suffix(raw) == expected


class TestPreservesEverythingElse:
    def test_preserves_case(self):
        """The output is DISPLAYED. Lowercasing it would be a bug."""
        assert strip_display_suffix("Ja'Marr Chase") == "Ja'Marr Chase"
        assert strip_display_suffix("Amon-Ra St. Brown") == "Amon-Ra St. Brown"

    def test_preserves_apostrophes_hyphens_and_periods(self):
        assert strip_display_suffix("D.J. Moore") == "D.J. Moore"
        assert strip_display_suffix("De'Von Achane") == "De'Von Achane"

    def test_preserves_accents(self):
        """Unlike the join-key helpers, this must not ASCII-fold."""
        assert strip_display_suffix("Juanyéh Thomas") == "Juanyéh Thomas"

    def test_does_not_eat_a_real_name_token(self):
        """'Vea' ends in a suffix-like fragment; 'V' is a valid roman
        numeral. Neither may be stripped from a legitimate surname."""
        assert strip_display_suffix("Vita Vea") == "Vita Vea"
        assert strip_display_suffix("Jimmie Ward") == "Jimmie Ward"

    def test_only_strips_at_the_end(self):
        assert strip_display_suffix("Jr Smith Jones") == "Jr Smith Jones"

    @pytest.mark.parametrize("raw", ["", None, "   "])
    def test_empty_inputs(self, raw):
        assert strip_display_suffix(raw) == ""


class TestItIsNotAJoinKey:
    def test_differs_from_normalize_player_name(self):
        """Guards against someone 'simplifying' this into the lowercased
        key helper, which would change every rendered label."""
        raw = "Marvin Harrison Jr."
        assert strip_display_suffix(raw) == "Marvin Harrison"
        assert normalize_player_name(raw) == "marvin harrison"
        assert strip_display_suffix(raw) != normalize_player_name(raw)

    def test_output_lands_in_the_contract_vocabulary(self):
        """The point of the helper: after stripping, the display name
        normalizes to the same key the contract row would."""
        sleeper_raw = "Kenneth Walker III"
        contract_style = "Kenneth Walker"
        assert normalize_player_name(strip_display_suffix(sleeper_raw)) == normalize_player_name(
            contract_style
        )


class TestOverlayFallbackUsesIt:
    def test_resolve_player_label_cleans_the_sleeper_fallback(self, monkeypatch):
        from src.api import sleeper_overlay

        monkeypatch.setattr(
            sleeper_overlay,
            "_sleeper_fallback_name_map",
            lambda: {"7058": "Marvin Harrison Jr."},
        )
        label = sleeper_overlay._resolve_player_label("7058", {})
        assert label == "Marvin Harrison"

    def test_contract_map_wins_and_is_untouched(self, monkeypatch):
        """The first branch already returns a contract-vocabulary name;
        it must pass through verbatim, suffix or not."""
        from src.api import sleeper_overlay

        monkeypatch.setattr(sleeper_overlay, "_sleeper_fallback_name_map", lambda: {})
        label = sleeper_overlay._resolve_player_label("123", {"123": "Some Player Jr."})
        assert label == "Some Player Jr."

    def test_unknown_id_still_degrades_to_the_raw_id(self, monkeypatch):
        from src.api import sleeper_overlay

        monkeypatch.setattr(sleeper_overlay, "_sleeper_fallback_name_map", lambda: {})
        assert sleeper_overlay._resolve_player_label("9999", {}) == "9999"

    def test_a_name_that_is_only_a_suffix_does_not_become_empty(self, monkeypatch):
        """Degenerate input must not blank the row out — the fallback
        keeps the original when stripping would leave nothing."""
        from src.api import sleeper_overlay

        monkeypatch.setattr(sleeper_overlay, "_sleeper_fallback_name_map", lambda: {"1": "Jr."})
        assert sleeper_overlay._resolve_player_label("1", {}) == "Jr."
