"""Every IDP position-reading site in the repo must resolve multi-position
Sleeper players under the same priority: DL > DB > LB. These tests pin
the shared helper behaviour. Every site-level test below (in the other
test modules) asserts the *integration* with this helper."""
from __future__ import annotations

import pytest

from src.utils.name_clean import (
    IDP_PRIORITY,
    normalize_position_family,
    resolve_idp_position,
)


class TestResolveIdpPosition:
    def test_priority_order_constant(self):
        # The priority tuple is the documented contract; don't change
        # it without updating docs/idp_calibration_lab.md.
        assert IDP_PRIORITY == ("DL", "DB", "LB")

    @pytest.mark.parametrize(
        "inputs,expected",
        [
            # DL beats LB no matter which side or notation.
            (("DL", "LB"), "DL"),
            (("LB", "DL"), "DL"),
            (("DE", "OLB"), "DL"),            # DE → DL; OLB → LB
            (("EDGE", "ILB"), "DL"),
            # DB beats LB.
            (("LB", "DB"), "DB"),
            (("CB", "OLB"), "DB"),
            (("S", "ILB"), "DB"),
            (("FS", "LB"), "DB"),
            # DL beats DB (product decision).
            (("DL", "DB"), "DL"),
            (("DE", "CB"), "DL"),
            # LB is emitted only when exclusive.
            (("LB",), "LB"),
            (("ILB",), "LB"),
            (("OLB",), "LB"),
            # Non-IDP inputs return empty string.
            (("QB",), ""),
            (("WR",), ""),
            (("PICK",), ""),
        ],
    )
    def test_canonical_priority(self, inputs, expected):
        assert resolve_idp_position(*inputs) == expected

    def test_accepts_list_candidate_like_sleeper_fantasy_positions(self):
        # Sleeper's players/nfl dump exposes `fantasy_positions` as an
        # array, e.g. ["DL", "LB"]. The helper must accept that shape
        # directly, not just comma-joined strings.
        assert resolve_idp_position(["DL", "LB"]) == "DL"
        assert resolve_idp_position(["LB", "DB"]) == "DB"
        assert resolve_idp_position(["LB"]) == "LB"
        assert resolve_idp_position(["QB"]) == ""

    def test_accepts_slash_joined_pair(self):
        # Some CSV sources emit "DL/LB" rather than a list.
        assert resolve_idp_position("DL/LB") == "DL"
        assert resolve_idp_position("LB/DB") == "DB"
        assert resolve_idp_position("DL/DB") == "DL"

    def test_mixed_inputs_also_collapse_under_same_priority(self):
        # A single call that carries both a single-string primary
        # position and an auxiliary list (Sleeper gives us both).
        assert resolve_idp_position("LB", ["DL"]) == "DL"
        assert resolve_idp_position("LB", ["CB", "S"]) == "DB"

    def test_strips_trailing_digits(self):
        # DLF IDP CSVs sometimes emit "LB1", "DL7" for positional rank.
        assert resolve_idp_position("LB1") == "LB"
        assert resolve_idp_position("DL7") == "DL"

    def test_empty_and_none_inputs_are_safe(self):
        assert resolve_idp_position(None) == ""
        assert resolve_idp_position("") == ""
        assert resolve_idp_position([]) == ""
        assert resolve_idp_position(None, "", []) == ""

    @pytest.mark.parametrize(
        "inputs",
        [
            ("QB", "LB"),          # mixed offense + LB
            ("LB", "QB"),          # reversed order
            (["QB", "LB"],),       # list form
            ("QB/LB",),            # slash form
            ("LB,WR",),            # comma form
            ("LB|TE",),            # pipe form
            ("LB", ["RB"]),        # split across candidates
            ("K", "LB"),           # kicker + LB
        ],
    )
    def test_lb_is_refused_when_any_non_idp_is_present(self, inputs):
        # Product rule: LB must be emitted only when the player is
        # exclusively LB-eligible. Non-IDP context (QB/RB/WR/TE/K/PICK)
        # disqualifies the LB fallback.
        assert resolve_idp_position(*inputs) == ""

    @pytest.mark.parametrize(
        "inputs,expected",
        [
            # DL / DB still win even when offensive context is mixed in —
            # those are unambiguous IDP signals and the product rule
            # only requires exclusivity for LB.
            (("QB", "DL"), "DL"),
            (("WR", "CB"), "DB"),
            (("TE", "EDGE"), "DL"),
            (("RB", "S"), "DB"),
        ],
    )
    def test_dl_and_db_win_even_with_non_idp_context(self, inputs, expected):
        assert resolve_idp_position(*inputs) == expected


class TestNormalizePositionFamily:
    def test_slash_pairs_route_through_idp_priority(self):
        assert normalize_position_family("DL/LB") == "DL"
        assert normalize_position_family("LB/DB") == "DB"
        assert normalize_position_family("OLB/CB") == "DB"

    def test_single_positions_unchanged(self):
        assert normalize_position_family("DE") == "DL"
        assert normalize_position_family("OLB") == "LB"
        assert normalize_position_family("CB") == "DB"
        assert normalize_position_family("QB") == "QB"

    def test_exclusive_lb_still_lb(self):
        assert normalize_position_family("LB") == "LB"
        assert normalize_position_family("ILB") == "LB"

    def test_non_idp_slash_pair_falls_through(self):
        # "WR/KR" — not an IDP pair, so the helper should fall back to
        # the offense handling (first part wins).
        assert normalize_position_family("WR/KR") == "WR"
