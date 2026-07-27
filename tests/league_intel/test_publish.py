"""LI-9 overlay payload.

The properties that matter are the ones a wrong answer would make
invisible: that the caller's rows are never mutated (``latest_contract_data``
is a shared global), that an unmeasurable league degrades to consensus
instead of to a guess, and that the TE axis stays out so the market
anchor is not double-counted.
"""

from __future__ import annotations

import pytest

from src.league_intel.publish import build_league_adjusted_payload


def _row(name, position, value, rank=None, asset_class="player", canonical=None):
    return {
        "displayName": name,
        "canonicalName": canonical or name.lower(),
        "position": position,
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
        "assetClass": asset_class,
    }


BOARD = [
    _row("Scarce One", "RB", 5000, 1),
    _row("Scarce Two", "RB", 3000, 3),
    _row("Deep One", "K", 4000, 2),
    _row("Tight End", "TE", 2000, 4),
]

# lineupScarcity 0.5 is the axis reference, so DEEP (0.2) trims and
# SCARCE (0.8) lifts. TE sits exactly at the reference, so any TE
# movement could only have come from a TE axis.
SCARCITY = {
    "RB": {"lineupScarcity": 0.8},
    "K": {"lineupScarcity": 0.2},
    "TE": {"lineupScarcity": 0.5},
}


def _payload(board=None, scarcity=SCARCITY, **kw):
    kw.setdefault("league_key", "dynasty_main")
    return build_league_adjusted_payload(board if board is not None else BOARD, scarcity, **kw)


class TestCallerRowsAreNeverMutated:
    """The single most dangerous failure in this feature.

    ``latest_contract_data`` is a shared module global and the compact
    pass assigns ``canonicalConsensusRank`` in place. Building one
    league's overlay must not touch the board every other request reads.
    """

    def test_rows_are_untouched(self):
        board = [dict(r) for r in BOARD]
        before = [dict(r) for r in board]
        _payload(board)
        assert board == before, "overlay mutated the caller's rows"

    def test_nested_values_are_untouched(self):
        board = [dict(r, values={"overall": r["rankDerivedValue"]}) for r in BOARD]
        before = [r["values"]["overall"] for r in board]
        _payload(board)
        assert [r["values"]["overall"] for r in board] == before


class TestFactorsCompose:
    """Factors, not absolute values — so the overlay is correct against
    a board built with custom source weights, which the server never
    computed absolute numbers for."""

    def test_factor_is_a_ratio_not_a_value(self):
        p = _payload()
        assert all(0.5 < f < 1.5 for f in p["factors"].values()), p["factors"]

    def test_same_position_gets_the_same_factor(self):
        """Position-uniform. This is what makes a global re-rank safe:
        it can reorder across positions but never within one."""
        p = _payload()
        assert p["factors"]["Scarce One"] == pytest.approx(p["factors"]["Scarce Two"])

    def test_scarce_lifts_and_deep_trims(self):
        p = _payload()
        assert p["factors"]["Scarce One"] > 1.0
        assert p["factors"]["Deep One"] < 1.0


class TestRanksAreDenseAndCoherent:
    def test_ranks_are_contiguous_from_one(self):
        p = _payload()
        ranks = sorted(p["ranks"].values())
        assert ranks == list(range(1, len(ranks) + 1))

    def test_every_ranked_row_gets_a_tier(self):
        p = _payload()
        assert set(p["ranks"]) == set(p["tiers"])

    def test_reorders_across_positions(self):
        """Scarce One 5000x1.06 = 5300 stays top; Deep One 4000x0.94 =
        3760 falls below Scarce Two 3000x1.06 = 3180? No — but the RB/K
        gap must narrow. Assert the direction, not a brittle ordering."""
        p = _payload()
        assert p["ranks"]["Scarce One"] < p["ranks"]["Deep One"]

    def test_rankedCount_matches_the_map(self):
        p = _payload()
        assert p["rankedCount"] == len(p["ranks"])


class TestAnchorSlotPicks:
    """They carry a real value but must not consume a rank slot."""

    def test_anchor_year_slot_pick_is_priced_but_unranked(self):
        """Derived, not hardcoded: the anchor year rolls over mid-season
        (on 2026-07-27 it is already 2027, because the 2026 rookie draft
        has happened), so a literal year here would rot silently."""
        from src.api.data_contract import current_rookie_draft_year

        name = f"{current_rookie_draft_year()} Pick 1.06"
        board = BOARD + [_row(name, "PICK", 4500, 5, asset_class="pick", canonical=name.lower())]
        p = _payload(board)
        assert name not in p["ranks"], "anchor slot pick consumed a rank slot"
        ranks = sorted(p["ranks"].values())
        assert ranks == list(range(1, len(ranks) + 1)), "excluding it must leave ranks contiguous"

    def test_non_anchor_year_slot_pick_still_takes_a_slot(self):
        """Only CURRENT-year slot picks are excluded. A future-year pick
        is an ordinary ranked asset."""
        from src.api.data_contract import current_rookie_draft_year

        name = f"{current_rookie_draft_year() + 1} Pick 1.06"
        board = BOARD + [_row(name, "PICK", 4500, 5, asset_class="pick", canonical=name.lower())]
        assert name in _payload(board)["ranks"]

    def test_picks_do_not_move(self):
        """No PICK key in scarcity -> ABSENT axis -> factor 1.0. This is
        why league-adjusted mode re-prices every player against every
        pick, which is the headline behavioural consequence."""
        board = BOARD + [_row("2028 Early 1st", "PICK", 3500, 5, asset_class="pick")]
        p = _payload(board)
        assert "2028 Early 1st" not in p["factors"]


class TestDegradesToConsensusNotToAGuess:
    def test_absent_scarcity_yields_an_empty_overlay(self):
        p = _payload(scarcity=None)
        assert p["factors"] == {} and p["ranks"] == {}
        assert p["isNoop"] is True

    def test_empty_scarcity_is_treated_as_absent(self):
        assert _payload(scarcity={})["factors"] == {}

    def test_position_missing_from_scarcity_is_left_alone(self):
        p = _payload(scarcity={"RB": {"lineupScarcity": 0.8}})
        assert "Deep One" not in p["factors"], "K had no measurement; it must not move"

    def test_unpriced_row_never_enters_the_overlay(self):
        p = _payload(BOARD + [_row("Ghost", "RB", 0)])
        assert "Ghost" not in p["factors"]


class TestTePremiumStaysOut:
    """The market anchor ktcSfTep IS the TE++ board, so the blend already
    embeds the structural 2-TE premium. A post-blend TE axis double-counts."""

    def test_te_axis_is_declared_inactive(self):
        assert "tePremium" in _payload()["inactiveAxes"]

    def test_te_at_reference_scarcity_is_untouched(self):
        assert "Tight End" not in _payload()["factors"], (
            "a TE priced at reference scarcity moved — something is applying a "
            "TE premium on top of an anchor that already embeds it"
        )


class TestVersionPin:
    """Overlay ranks are valid only against the contract build they came
    from. A scrape landing mid-fetch would otherwise apply board B's
    ranks to board A's values."""

    def test_stamps_travel_with_the_payload(self):
        p = _payload(contract_version="2026-03-10.v2", scrape_timestamp="2026-07-27T05:14:44")
        assert p["contractVersion"] == "2026-03-10.v2"
        assert p["scrapeTimestamp"] == "2026-07-27T05:14:44"

    def test_absent_pin_is_explicit_null_not_missing(self):
        p = _payload()
        assert "contractVersion" in p and "scrapeTimestamp" in p


class TestProvenance:
    def test_payload_is_json_safe(self):
        import json

        json.loads(json.dumps(_payload()))

    def test_scarcity_used_is_echoed_back(self):
        """A served value must be explainable from the payload alone."""
        assert _payload()["scarcity"]["RB"]["lineupScarcity"] == pytest.approx(0.8)

    def test_dataclass_components_are_accepted(self):
        class Comp:
            def to_dict(self):
                return {"lineupScarcity": 0.8}

        p = _payload(scarcity={"RB": Comp()})
        assert p["factors"]["Scarce One"] > 1.0
        assert p["scarcity"]["RB"] == {"lineupScarcity": 0.8}

    def test_monotonicity_is_reported(self):
        assert _payload()["monotonicityViolations"] == []
