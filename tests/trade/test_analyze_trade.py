"""V1-43 / C7-DESK-01 — Analyze Trade, V1 depth.

``src.trade.analyze_trade`` composes two already-canonical, already-VERIFIED
dimensions (KTC VA equity, V1-42 roster marginal impact) into one recommendation
via an explicit rule table — never a tuned numeric weight, never a second
implementation of either dimension's own math.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.trade.analyze_trade import (
    RECOMMENDATIONS,
    analyze_trade,
    _equity_dimension,
    _roster_impact_dimension,
)
from src.trade.ktc_va import adjusted_pair_totals


def _sim(receiving_values, sending_values, *, strength_before=None, strength_after=None, fr=None):
    payload = {
        "receiving": [{"value": v} for v in receiving_values],
        "sending": [{"value": v} for v in sending_values],
    }
    if fr is not None:
        payload["finalRosterSimulation"] = fr
    elif strength_before is not None and strength_after is not None:
        payload["finalRosterSimulation"] = {
            "available": True,
            "strengthBefore": {"total": strength_before},
            "strengthAfter": {"total": strength_after},
        }
    return payload


class TestEquityDimensionUsesTheCanonicalOwner:
    def test_gap_matches_ktc_va_directly(self):
        """The equity dimension must be arithmetic-identical to calling
        adjusted_pair_totals directly — no re-derivation of KTC's VA."""
        sending = [3000.0, 500.0]
        receiving = [5000.0]
        send_adj, recv_adj, _, _ = adjusted_pair_totals(sending, receiving)
        expected_gap = recv_adj - send_adj

        dim = _equity_dimension(sending, receiving)

        assert dim.available is True
        assert dim.detail["vaAdjustedGap"] == int(round(expected_gap))

    def test_no_priced_assets_is_unavailable_not_zero(self):
        dim = _equity_dimension([], [])
        assert dim.available is False
        assert dim.direction is None


class TestRosterImpactDimensionReadsV142Verbatim:
    def test_favors_when_team_strength_rises(self):
        dim = _roster_impact_dimension(
            {"available": True, "strengthBefore": {"total": 1000}, "strengthAfter": {"total": 1200}}
        )
        assert dim.available is True
        assert dim.direction == "favors"
        assert dim.detail["teamStrengthDelta"] == 200.0

    def test_opposes_when_team_strength_falls(self):
        dim = _roster_impact_dimension(
            {"available": True, "strengthBefore": {"total": 1200}, "strengthAfter": {"total": 1000}}
        )
        assert dim.direction == "opposes"

    def test_unavailable_when_no_final_roster_simulation(self):
        """No team selected -> /api/trade/simulate omits finalRosterSimulation
        entirely.  Missing must read as unavailable, never as neutral/zero."""
        dim = _roster_impact_dimension(None)
        assert dim.available is False
        assert dim.direction is None

    def test_unavailable_when_capacity_uncertain(self):
        """Taxi-bracket ambiguity: available=False with a named reason
        (see src.api.trade_simulator's own capacity_uncertain shape)."""
        dim = _roster_impact_dimension(
            {"available": False, "unavailableReason": "capacity_uncertain"}
        )
        assert dim.available is False
        assert dim.unavailable_reason == "capacity_uncertain"


class TestDimensionsReadDisjointCanonicalFields:
    def test_equity_and_roster_impact_touch_no_common_field(self):
        """Structural no-double-count guard: the two dimensions must be
        computed from disjoint source fields of the simulate_trade payload,
        so one signal cannot silently feed both dimensions."""
        sim = _sim([5000], [3000], strength_before=100000, strength_after=101500)
        analysis = analyze_trade(sim)
        equity_keys = set(analysis["dimensions"][0]["detail"].keys())
        roster_keys = set(analysis["dimensions"][1]["detail"].keys())
        assert equity_keys.isdisjoint(roster_keys)

    def test_source_reads_no_shared_helper_between_dimensions(self):
        """AST guard: _roster_impact_dimension must never call
        adjusted_pair_totals (or vice versa) — each dimension owns exactly
        one canonical source, so a future edit cannot quietly blend them."""
        tree = ast.parse(Path("src/trade/analyze_trade.py").read_text())
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        roster_fn = funcs["_roster_impact_dimension"]
        called_names = {
            n.func.id
            for n in ast.walk(roster_fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "adjusted_pair_totals" not in called_names


class TestRecommendationIsARuleTableNotAWeightedSum:
    def test_agreement_favors_is_make_or_lean_make(self):
        sim = _sim([5000], [3000], strength_before=100000, strength_after=101500)
        analysis = analyze_trade(sim)
        assert analysis["recommendation"] in ("MAKE", "LEAN_MAKE")
        assert analysis["confidence"] == "HIGH"

    def test_agreement_opposes_is_pass_or_lean_pass(self):
        sim = _sim([1000], [4000], strength_before=100000, strength_after=98500)
        analysis = analyze_trade(sim)
        assert analysis["recommendation"] in ("PASS", "LEAN_PASS")

    def test_disagreement_is_too_close_never_a_confident_verdict(self):
        """Plan requirement: 'must not force false certainty when strong
        independent dimensions disagree.'"""
        sim = _sim([5000], [3000], strength_before=100000, strength_after=98000)
        analysis = analyze_trade(sim)
        assert analysis["recommendation"] == "TOO_CLOSE"
        assert analysis["confidence"] != "HIGH"

    def test_roster_unavailable_caps_confidence_below_high(self):
        sim = _sim([5000], [3000])
        analysis = analyze_trade(sim)
        assert analysis["confidence"] != "HIGH"

    def test_no_priced_assets_is_too_close_low_confidence(self):
        analysis = analyze_trade(_sim([], []))
        assert analysis["recommendation"] == "TOO_CLOSE"
        assert analysis["confidence"] == "LOW"

    def test_every_recommendation_is_in_the_declared_vocabulary(self):
        cases = [
            _sim([5000], [3000], strength_before=100, strength_after=200),
            _sim([1000], [4000], strength_before=200, strength_after=100),
            _sim([5000], [3000], strength_before=200, strength_after=100),
            _sim([3000], [3000], strength_before=100, strength_after=100),
        ]
        for sim in cases:
            analysis = analyze_trade(sim)
            assert analysis["recommendation"] in RECOMMENDATIONS


class TestUnavailableDimensionsAreNamedNotSilent:
    def test_market_corroboration_and_uncertainty_are_stamped_absent(self):
        """Missing is never zero: the plan's fuller dimension set (market
        corroboration, MC uncertainty) is named as NOT included, rather than
        silently absent from the response shape."""
        analysis = analyze_trade(_sim([5000], [3000]))
        names = {d["dimension"] for d in analysis["unavailableDimensions"]}
        assert names == {"marketCorroboration", "uncertainty"}
        for d in analysis["unavailableDimensions"]:
            assert d["reason"]
            assert d["notes"]


class TestReasonsCiteMeasuredNumbersNotFabrication:
    def test_reasons_for_include_the_actual_gap_and_delta(self):
        sim = _sim([5000], [3000], strength_before=100000, strength_after=101500)
        analysis = analyze_trade(sim)
        joined = " ".join(analysis["reasonsFor"])
        assert "2000" in joined
        assert "1500" in joined

    def test_unavailable_roster_dimension_is_named_in_reasons(self):
        analysis = analyze_trade(_sim([5000], [3000]))
        joined = " ".join(analysis["reasonsAgainst"])
        assert "unavailable" in joined.lower()
