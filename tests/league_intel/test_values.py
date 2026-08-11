"""LI-4 — parallel value schema + the single selector.

Pins the contract downstream R-phase pages will adopt, and the no-op
guarantee that keeps an unvalidated league-adjusted number from ever
reaching a UI before LI-7.
"""

from __future__ import annotations

import pytest

from src.league_intel.values import (
    LEAGUE_ADJUSTED_IS_NOOP,
    MARKET_ANCHOR_BY_ASSET_CLASS,
    MODEL_VERSION,
    VALUE_SCHEMA_VERSION,
    PlayerValues,
    ValuationMode,
    build_player_values,
    get_active_value,
)


def _row(**over):
    row = {
        "displayName": "Test Player",
        "assetClass": "offense",
        "rankDerivedValue": 7200,
        "canonicalSiteValues": {"ktcSfTep": 6800, "idpTradeCalc": 100},
        "values": {"displayValue": 7200, "finalAdjusted": 7200, "overall": 7200},
    }
    row.update(over)
    return row


class TestSchema:
    def test_versions_are_stamped(self):
        v = build_player_values(_row(), config_version=1, data_through="2026-07-26")
        assert v.schema_version == VALUE_SCHEMA_VERSION == 1
        assert v.model_version == MODEL_VERSION
        assert v.config_version == 1
        assert v.data_through == "2026-07-26"

    def test_to_dict_shape_is_the_published_contract(self):
        d = build_player_values(_row(), config_version=1, data_through="2026-07-26").to_dict()
        assert set(d) == {
            "displayName",
            "marketValue",
            "consensusValue",
            "leagueAdjustedDynastyValue",
            "assetClass",
            "marketAnchorSource",
            "schemaVersion",
            "modelVersion",
            "configVersion",
            "dataThrough",
            "leagueAdjustedIsNoop",
        }
        assert d["consensusValue"] == 7200
        assert d["marketValue"] == 6800
        assert d["marketAnchorSource"] == "ktcSfTep"

    def test_market_anchor_registry_matches_the_other_live_consumer(self):
        """Parity guard, now two-way rather than three.

        ``data_contract`` no longer defines an anchor map: its copy
        existed only for the market-corridor clamp, removed under
        #794/#795/#796 because the anchor was a voter in the blend it
        corrected. The remaining two definitions are genuine consumers —
        league-adjusted values here, the mispricing signal in
        ``consensus_edge.fair_value`` — and still have to agree.
        """
        from src.api import data_contract as dc
        from src.consensus_edge.fair_value import (
            MARKET_ANCHOR_BY_ASSET_CLASS as FV_ANCHORS,
        )

        assert MARKET_ANCHOR_BY_ASSET_CLASS == FV_ANCHORS
        assert not hasattr(dc, "_MARKET_ANCHOR_BY_ASSET_CLASS"), (
            "the contract pipeline re-grew a market anchor; if deliberate, "
            "restore the third parity leg"
        )


class TestNoOpGuarantee:
    """LI-7 narrowed this guarantee rather than removing it.

    Before LI-7 no adjusted value existed anywhere. Now one exists, but
    only where board-level scarcity was actually measured — a row on
    its own still cannot produce one, because the adjustment is a
    function of all twelve rosters.
    """

    def test_a_lone_row_still_gets_consensus(self):
        """No board context in, no adjustment out. This is the rule
        that keeps a manufactured number from reaching a caller."""
        assert LEAGUE_ADJUSTED_IS_NOOP is False, "LI-7 wired the model"
        v = build_player_values(_row())
        assert v.league_adjusted_dynasty_value == v.consensus_value == 7200

    def test_supplied_adjustment_is_used(self):
        v = build_player_values(_row(), league_adjusted=7500)
        assert v.league_adjusted_dynasty_value == 7500
        assert v.consensus_value == 7200, "consensus must not be overwritten"

    @pytest.mark.parametrize("bad", [0, -1, None, "abc"])
    def test_unusable_supplied_adjustment_falls_back_to_consensus(self, bad):
        """A non-positive or unparseable adjustment is discarded, not
        published — a zero here would read as 'worthless player'."""
        v = build_player_values(_row(), league_adjusted=bad)
        assert v.league_adjusted_dynasty_value == 7200

    def test_noop_holds_for_unpriced_rows(self):
        v = build_player_values(_row(rankDerivedValue=None, values={}))
        assert v.consensus_value is None
        assert v.league_adjusted_dynasty_value is None

    def test_selecting_league_adjusted_is_safe_today(self):
        v = build_player_values(_row())
        assert get_active_value(v, ValuationMode.LEAGUE_ADJUSTED) == get_active_value(
            v, ValuationMode.CONSENSUS
        )


class TestValueResolution:
    def test_market_falls_to_idp_anchor_for_idp_rows(self):
        v = build_player_values(_row(assetClass="idp"))
        assert v.market_value == 100
        assert v.market_anchor_source == "idpTradeCalc"

    def test_missing_market_anchor_is_none_not_consensus(self):
        v = build_player_values(_row(canonicalSiteValues={"dynastyDaddySf": 5000}))
        assert v.market_value is None
        assert v.market_anchor_source is None
        assert v.consensus_value == 7200

    def test_unknown_asset_class_has_no_anchor(self):
        v = build_player_values(_row(assetClass="pick"))
        assert v.market_value is None

    def test_consensus_prefers_rank_derived_value(self):
        v = build_player_values(_row(rankDerivedValue=9000, values={"displayValue": 1}))
        assert v.consensus_value == 9000

    def test_consensus_falls_back_through_values_bundle(self):
        v = build_player_values(_row(rankDerivedValue=None, values={"finalAdjusted": 4321}))
        assert v.consensus_value == 4321

    def test_non_positive_values_treated_as_unpriced(self):
        v = build_player_values(
            _row(rankDerivedValue=0, values={}, canonicalSiteValues={"ktcSfTep": -5})
        )
        assert v.consensus_value is None
        assert v.market_value is None


class TestSelector:
    def test_defaults_to_consensus(self):
        assert get_active_value(_row()) == 7200

    def test_accepts_wire_strings_and_enum(self):
        row = _row()
        assert get_active_value(row, "market") == 6800
        assert get_active_value(row, ValuationMode.MARKET) == 6800
        assert get_active_value(row, "leagueAdjusted") == 7200
        assert get_active_value(row, "CONSENSUS") == 7200

    def test_rejects_unknown_mode(self):
        with pytest.raises(ValueError, match="unknown valuation mode"):
            get_active_value(_row(), "vibes")

    def test_rejects_bad_player_type(self):
        with pytest.raises(TypeError):
            get_active_value(42, "consensus")

    def test_round_trips_through_serialized_bundle(self):
        bundle = build_player_values(_row(), config_version=1).to_dict()
        assert get_active_value(bundle, "market") == 6800
        assert get_active_value(bundle, "consensus") == 7200
        assert get_active_value(bundle, "leagueAdjusted") == 7200

    def test_context_supplies_provenance_for_raw_rows(self):
        v = build_player_values(_row(), config_version=3, data_through="2026-07-01")
        assert (v.config_version, v.data_through) == (3, "2026-07-01")
        # Same provenance reachable through the selector's context arg.
        assert (
            get_active_value(_row(), "consensus", {"configVersion": 3, "dataThrough": "2026-07-01"})
            == 7200
        )

    def test_never_substitutes_one_lens_for_another(self):
        """A row with no market anchor returns None for MARKET — it must
        not silently fall back to consensus."""
        row = _row(canonicalSiteValues={})
        assert get_active_value(row, "market") is None
        assert get_active_value(row, "consensus") == 7200

    def test_player_values_value_for_matches_selector(self):
        v = PlayerValues(
            display_name="X",
            market_value=10.0,
            consensus_value=20.0,
            league_adjusted_dynasty_value=20.0,
        )
        for mode in ValuationMode:
            assert v.value_for(mode) == get_active_value(v, mode)
