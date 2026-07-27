"""TE demand (Axis B) and KTC's measured uplift curve (Axis A).

Collaborative audit, finding F, as CORRECTED 2026-07-27.

The correction these tests exist to lock in: an earlier version measured
TE demand from scoring keys alone, found no ``bonus_rec_te``, and
concluded the league had no TE premium.  The league starts **two**
tight ends.  Structural demand is demand whether or not a scoring key
rewards the position, and reading one as the other would have translated
TE values DOWN off a basis they belong on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_intel.te_premium import (
    TE_BASES,
    convert_te_value,
    load_tep_curve,
    measure_te_demand,
    tep_uplift,
)

REPO = Path(__file__).resolve().parents[2]

# Read the operator's real league rather than retyping it, so these
# track the actual settings.
_SNAPSHOT = REPO / "config" / "league_intel" / "sleeper_league_snapshot_2026-07-26.json"
_REGISTRY = REPO / "config" / "leagues" / "registry.json"


def _league() -> dict:
    return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))


class TestAxisBStructuralDemandLeads:
    def test_two_te_league_targets_the_te_plus_plus_basis(self):
        """The correction, as an assertion.

        Scoring grants TEs nothing. The league still starts two of them,
        so the target basis is TE++.
        """
        league = _league()
        m = measure_te_demand(league, league.get("scoring_settings"))
        assert m.required_te_starters == 2
        assert m.target_basis == "tepp"

    def test_no_scoring_edge_does_not_lower_the_basis(self):
        """The exact inversion that made the first pass wrong."""
        league = _league()
        m = measure_te_demand(league, league.get("scoring_settings"))
        assert m.has_scoring_edge is False
        assert m.target_basis == "tepp", (
            "a 2-TE league must not fall back to the base basis just because "
            "no scoring key advantages TE — that confuses the mechanism with "
            "the demand"
        )

    def test_roster_structure_alone_is_enough(self):
        """Scoring is optional input; roster structure is not."""
        m = measure_te_demand({"roster_positions": ["QB", "TE", "TE", "FLEX"]})
        assert m.target_basis == "tepp"
        assert m.measured is True

    def test_one_te_league_stays_on_base(self):
        m = measure_te_demand({"roster_positions": ["QB", "RB", "WR", "TE", "FLEX"]})
        assert m.required_te_starters == 1
        assert m.target_basis == "base"

    def test_scoring_can_only_raise_the_basis(self):
        """A TE-only bonus on top of a 1-TE requirement moves it up one
        step; it can never move a 2-TE league down."""
        raised = measure_te_demand(
            {"roster_positions": ["QB", "TE"]},
            {"bonus_rec_te": 0.5, "bonus_rec_wr": 0.0, "bonus_rec_rb": 0.0},
        )
        assert raised.target_basis == "tep"  # base -> one step up

        two_te = measure_te_demand(
            {"roster_positions": ["QB", "TE", "TE"]},
            {"bonus_rec_te": 0.0, "bonus_rec_wr": 0.0},
        )
        assert two_te.target_basis == "tepp"

    def test_shared_first_down_bonus_is_not_a_te_edge(self):
        """``bonus_fd_te = 1.0`` looks like a TE premium until you notice
        ``bonus_fd_wr`` is also 1.0."""
        m = measure_te_demand(
            {"roster_positions": ["QB", "TE"]},
            {"bonus_fd_te": 1.0, "bonus_fd_wr": 1.0, "bonus_fd_rb": 1.0},
        )
        assert m.has_scoring_edge is False
        assert m.target_basis == "base"

    def test_repo_roster_settings_shape_also_works(self):
        """Both shapes exist in the tree; neither may be the only one
        understood."""
        registry = json.loads(_REGISTRY.read_text(encoding="utf-8"))
        main = next(x for x in registry["leagues"] if x["key"] == "dynasty_main")
        m = measure_te_demand(main["rosterSettings"])
        assert m.required_te_starters == 2
        assert m.te_flex_eligible is True
        assert m.target_basis == "tepp"

    def test_no_inputs_is_unmeasured_not_neutral(self):
        m = measure_te_demand(None, None)
        assert m.measured is False
        assert m.target_basis == "base"

    def test_measurement_carries_no_multiplier_field(self):
        """The structural guard. A multiplier invites a caller to stack
        it on the blend's existing source alignment; a basis cannot be
        multiplied into anything."""
        m = measure_te_demand(_league())
        assert not hasattr(m, "multiplier")
        assert "multiplier" not in m.to_dict()


class TestDoubleCountIsStructurallyImpossible:
    def test_converting_to_the_basis_a_value_is_already_on_is_a_no_op(self):
        """``ktcSfTep`` is already ``tepp``. Asking to put it on ``tepp``
        must change nothing — this is what stops KTC being lifted twice."""
        for v in (500, 3000, 9878):
            assert convert_te_value(v, from_basis="tepp", to_basis="tepp") == float(v)

    def test_conversion_is_idempotent(self):
        """Applying the same conversion twice cannot compound, because the
        second call sees from == to. A multiplier API cannot offer this."""
        once = convert_te_value(3000, from_basis="base", to_basis="tepp")
        twice = convert_te_value(once, from_basis="tepp", to_basis="tepp")
        assert once == twice

    def test_round_trip_returns_the_original(self):
        # 200 sits below KTC's measured range, where the uplift is the
        # flat observed-maximum cap — the inversion must hold there too.
        for v in (200, 490, 1000, 3000, 8169):
            up = convert_te_value(v, from_basis="base", to_basis="tepp")
            back = convert_te_value(up, from_basis="tepp", to_basis="base")
            assert back == pytest.approx(v, rel=1e-3)

    def test_round_trip_reproduces_a_real_ktc_pair(self):
        """Brock Bowers is base 8169 / TE++ 9878 on the live boards."""
        up = convert_te_value(8169, from_basis="base", to_basis="tepp")
        assert up == pytest.approx(9878, rel=0.01)

    def test_an_unmeasured_basis_pair_raises(self):
        """``tep`` and ``teppp`` have no fitted curve. Interpolating one
        would be exactly the unmeasured number this audit removes."""
        with pytest.raises(ValueError, match="no measured curve"):
            convert_te_value(3000, from_basis="base", to_basis="teppp")

    def test_an_unknown_basis_raises_rather_than_silently_skipping(self):
        with pytest.raises(ValueError, match="not one of"):
            convert_te_value(3000, from_basis="base", to_basis="TEP++")


class TestAxisATheKtcUpliftCurve:
    def test_uplift_never_drops_below_one(self):
        """A TE premium cannot lower a tight end's value. The rejected
        log-linear fit predicted 0.938 at the top of the board."""
        for v in (0, 1, 10, 500, 1000, 5000, 9999, 10**6):
            assert tep_uplift(v) >= 1.0

    def test_uplift_is_monotone_decreasing_in_value(self):
        values = [500, 1000, 2000, 3000, 5000, 8000, 9999]
        ratios = [tep_uplift(v) for v in values]
        assert ratios == sorted(ratios, reverse=True)

    def test_curve_never_reads_below_the_observed_minimum(self):
        curve = json.loads(
            (REPO / "config" / "weights" / "te_premium_curve.json").read_text(encoding="utf-8")
        )
        for v in (1, 500, 3000, 8169, 9999, 10**6):
            assert tep_uplift(v) >= curve["floor"] - 1e-9

    def test_curve_never_reads_above_the_observed_maximum(self):
        """The other end of the same argument.  KTC's board bottoms out
        around base ~480; below that the power form extrapolates
        unbounded (3.36x at base 100, 43x at base 1), and non-KTC
        sources DO produce TE contributions down there.  No tight end
        was ever observed above the config's ratio maximum, so the curve
        must not read past it — an extrapolated uplift is exactly the
        unmeasured number this module exists to remove."""
        curve = json.loads(
            (REPO / "config" / "weights" / "te_premium_curve.json").read_text(encoding="utf-8")
        )
        ceiling = curve["observed_ratio_range"][1]
        for v in (0, 1, 50, 100, 400, 482, 3000, 9999):
            assert tep_uplift(v) <= ceiling + 1e-9

    def test_live_blanket_constant_under_corrects_every_tight_end(self):
        """The finding that SURVIVES the Axis-B correction, and gets
        stronger under it.

        The target basis is TE++, so non-TEP boards must be lifted onto
        it. The live constant is a flat 1.15 and the smallest uplift KTC
        actually applies is 1.209 — so every TE is lifted too little, and
        correcting it moves TE values UP, not down.
        """
        from src.api.data_contract import _TE_BLANKET_NON_NATIVE_MULTIPLIER

        curve = json.loads(
            (REPO / "config" / "weights" / "te_premium_curve.json").read_text(encoding="utf-8")
        )
        assert _TE_BLANKET_NON_NATIVE_MULTIPLIER < curve["observed_ratio_range"][0]

    def test_config_and_fallback_agree(self):
        from src.league_intel import te_premium as tp

        a, k, floor, ceiling = load_tep_curve()
        assert a == pytest.approx(tp._FALLBACK_A, rel=1e-6)
        assert k == pytest.approx(tp._FALLBACK_K, rel=1e-6)
        assert floor == pytest.approx(tp._FALLBACK_FLOOR, rel=1e-4)
        assert ceiling == pytest.approx(tp._FALLBACK_CEILING, rel=1e-4)


class TestTheTwoAxesStaySeparate:
    def test_demand_measurement_does_not_consult_any_board(self):
        """Axis B must be a pure function of league configuration. If it
        read KTC, a board refresh would silently move the league's
        target basis."""
        import inspect

        from src.league_intel import te_premium as tp

        src = inspect.getsource(tp.measure_te_demand)
        for forbidden in ("ktc", "csv", "uplift", "load_tep_curve"):
            assert forbidden not in src.lower()

    def test_uplift_does_not_consult_league_config(self):
        import inspect

        from src.league_intel import te_premium as tp

        src = inspect.getsource(tp.tep_uplift)
        for forbidden in ("bonus_rec", "scoring", "roster", "starters"):
            assert forbidden not in src.lower()

    def test_bases_ladder_is_ordered_low_to_high(self):
        assert TE_BASES == ("base", "tep", "tepp", "teppp")
