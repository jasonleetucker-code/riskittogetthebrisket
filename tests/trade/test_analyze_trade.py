"""#792 / C7-DESK-01 — the Analyze Trade decision packet (v2).

``src.trade.analyze_trade`` synthesizes separate LENSES by an explicit rule
table: market (canonical values + exact KTC VA), roster (#1173 best-ball
utility on league-scored projections), feasibility (#843 capacity), plus an
evidence lens that never votes.  What is pinned:

* each lens reads its own canonical owner (VA identical to the owner);
* LINEAGE: at most one vote per evidence lineage — Team Strength and the
  canonical value's contributing sources never become extra votes;
* the market and the roster can disagree, and that is TOO_CLOSE with both
  sides' reasons shown;
* feasibility can flip an otherwise favorable deal;
* missing is never neutral: unavailable lenses and dimensions are named;
* Team Context OFF (#842) removes roster/feasibility without touching values.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from src.trade.analyze_trade import (
    RECOMMENDATIONS,
    _feasibility_state,
    _market_lens,
    analyze_trade,
)
from src.trade.ktc_va import adjusted_pair_totals


def _utility(ppg, *, se=0.3, coverage="full", players=None, depth=None, cleanup=None, pre=None):
    return {
        "available": True,
        "unit": "expected best-ball points per week (exact league scoring)",
        "impact": {"ppg": ppg, "standardError": se, "ppgBeforeCleanup": pre},
        "coverage": {
            "state": coverage,
            "tradedUnprojectedPlayerIds": ["x"] if coverage == "partial" else [],
        },
        "players": players or [],
        "depth": {"meanLossDeltaPpg": depth},
        "cleanup": cleanup or {"state": "none", "forcedDropIds": [], "candidatesTied": False},
        "before": {"expectedLineupPpg": 150.0},
        "after": {"expectedLineupPpg": 150.0 + ppg},
    }


def _capacity(
    *,
    limit=58,
    before=57,
    after=57,
    drops=(),
    release=None,
    requires=False,
    over_before=0,
    over_after=0,
    tied=False,
    exhausted=False,
):
    return {
        "rosterLimit": limit,
        "sizeBefore": before,
        "sizeAfter": after,
        "openSpotsBefore": None if limit is None else max(0, limit - before),
        "openSpotsAfter": None if limit is None else max(0, limit - after),
        "overLimitBefore": over_before,
        "overLimitAfter": over_after,
        "requiresDrops": requires,
        "forcedDrops": [{"name": n, "position": "WR", "value": 900} for n in drops],
        "forcedDropReleaseCost": release,
        "rungOrderWasTied": tied,
        "ladderExhausted": exhausted,
        "certainty": "exact",
    }


def _sim(recv, send, *, utility=None, capacity=None, strength=None, context=None, assets=None):
    payload = {
        "receiving": [{"name": f"in{i}", "value": v, **(assets or {})} for i, v in enumerate(recv)],
        "sending": [{"name": f"out{i}", "value": v, **(assets or {})} for i, v in enumerate(send)],
    }
    if utility is not None:
        payload["rosterUtility"] = utility
    if capacity is not None:
        payload["rosterCapacity"] = capacity
    if strength is not None:
        payload["finalRosterSimulation"] = {
            "available": True,
            "strengthBefore": {"total": strength[0]},
            "strengthAfter": {"total": strength[1]},
        }
    if context is not None:
        payload["teamContext"] = {"applied": context}
    return payload


# ── Lens owners ──────────────────────────────────────────────────────────


class TestMarketLensUsesTheCanonicalOwner:
    def test_gap_matches_ktc_va_directly(self):
        sending, receiving = [3000.0, 500.0], [5000.0]
        send_adj, recv_adj, _, _ = adjusted_pair_totals(sending, receiving)
        lens = _market_lens(_sim(receiving, sending))
        assert lens.available is True
        assert lens.detail["vaAdjustedGap"] == int(round(recv_adj - send_adj))
        assert lens.detail["rawGap"] == 1500
        assert lens.lineage == "canonical_value"

    def test_no_priced_assets_is_unavailable_not_zero(self):
        lens = _market_lens(_sim([], []))
        assert lens.available is False
        assert lens.direction is None

    def test_an_even_gap_is_neutral_whatever_its_sign(self):
        lens = _market_lens(_sim([3010], [3000]))
        assert lens.detail["magnitude"] == "even"
        assert lens.direction == "neutral"


class TestKtcVaIsItsOwnMarketLens:
    def test_va_is_published_separately_from_the_roster_lens(self):
        a = analyze_trade(_sim([5000], [2000, 1500], utility=_utility(2.0)))
        market = a["lenses"]["market"]["detail"]
        roster = a["lenses"]["roster"]["detail"]
        assert "vaAdjustedGap" in market and "valueAdjustment" in market
        assert "vaAdjustedGap" not in roster and "ppg" in roster

    def test_roster_lens_never_calls_the_va_owner(self):
        tree = ast.parse(Path("src/trade/analyze_trade.py").read_text(encoding="utf-8"))
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for name in ("_roster_lens", "_feasibility_lens", "_evidence_lens"):
            called = {
                n.func.id
                for n in ast.walk(funcs[name])
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            assert "adjusted_pair_totals" not in called, name


# ── Lineage / double counting ────────────────────────────────────────────


class TestNoDoubleCounting:
    def test_at_most_one_vote_per_lineage(self):
        a = analyze_trade(
            _sim([5000], [3000], utility=_utility(3.0), capacity=_capacity(), strength=(100, 200))
        )
        voting = [d for d in a["dimensions"] if d["votes"]]
        lineages = [d["lineage"] for d in voting]
        assert len(lineages) == len(set(lineages))
        assert "canonical_value" in lineages  # the market lens, once

    def test_team_strength_is_context_not_a_vote(self):
        # Team Strength says the roster improved a lot; the projection-based
        # roster lens says it did not move.  Strength must not rescue the
        # decision — it shares the market lens's canonical-value lineage.
        with_strength = analyze_trade(
            _sim([3010], [3000], utility=_utility(0.2), strength=(100_000, 110_000))
        )
        without = analyze_trade(_sim([3010], [3000], utility=_utility(0.2)))
        assert with_strength["recommendation"] == without["recommendation"] == "TOO_CLOSE"
        ts = with_strength["lenses"]["roster"]["detail"]["teamStrength"]
        assert ts["countedAsVote"] is False
        assert ts["lineage"] == "canonical_value"

    def test_evidence_never_votes(self):
        a = analyze_trade(_sim([5000], [3000], utility=_utility(2.0)))
        evidence = a["lenses"]["evidence"]
        assert evidence["votes"] is False
        assert "direction" in evidence and evidence["direction"] is None

    def test_source_agreement_cannot_manufacture_confidence(self):
        # Every traded asset high-confidence with many agreeing sources is
        # still ONE market lens: it cannot turn LEAN into MAKE.
        agree = {"confidenceBucket": "high", "hasSourceDisagreement": False}
        a = analyze_trade(_sim([6000], [3000], utility=_utility(0.1), assets=agree))
        b = analyze_trade(_sim([6000], [3000], utility=_utility(0.1)))
        assert a["recommendation"] == b["recommendation"] == "LEAN_MAKE"


# ── The rule table ───────────────────────────────────────────────────────


class TestRuleTable:
    def test_market_and_roster_agree_favors_is_make(self):
        a = analyze_trade(_sim([6000], [3000], utility=_utility(3.0)))
        assert a["recommendation"] == "MAKE"
        assert a["confidence"] == "HIGH"

    def test_agree_opposes_is_pass(self):
        a = analyze_trade(_sim([2000], [6000], utility=_utility(-3.0)))
        assert a["recommendation"] == "PASS"

    def test_roster_can_disagree_with_the_market(self):
        # Market favors (you receive more value), roster opposes (the lineup
        # gets worse): "depends", and both sides' reasons are shown.
        a = analyze_trade(_sim([6000], [3000], utility=_utility(-3.0)))
        assert a["recommendation"] == "TOO_CLOSE"
        assert a["confidence"] != "HIGH"
        assert a["reasonsFor"] and a["reasonsAgainst"]

    def test_roster_utility_can_carry_a_market_even_trade(self):
        a = analyze_trade(_sim([3010], [3000], utility=_utility(2.5)))
        assert a["recommendation"] == "LEAN_MAKE"
        assert any("best-ball points per week" in r for r in a["reasonsFor"])

    def test_a_change_inside_the_estimates_own_noise_is_neutral(self):
        # +1.2 ppg is past the 1.0 PRIOR but inside 2 x its standard error.
        a = analyze_trade(_sim([3010], [3000], utility=_utility(1.2, se=0.8)))
        assert a["lenses"]["roster"]["direction"] == "neutral"

    def test_every_recommendation_is_in_the_declared_vocabulary(self):
        for ppg in (-5.0, -1.5, 0.0, 1.5, 5.0):
            for recv in (1000, 3000, 6000):
                a = analyze_trade(_sim([recv], [3000], utility=_utility(ppg)))
                assert a["recommendation"] in RECOMMENDATIONS


class TestFeasibility:
    @pytest.mark.parametrize(
        "cap,state",
        [
            (_capacity(before=55, after=56), "fits_cleanly"),
            (_capacity(before=57, after=58), "uses_final_spot"),
            (
                _capacity(before=58, after=59, requires=True, drops=["X"], release=400),
                "cut_required",
            ),
            (
                _capacity(before=59, after=58, over_before=1, over_after=0),
                "resolves_overage",
            ),
            (
                _capacity(before=60, after=59, over_before=2, over_after=1, requires=True),
                "reduces_overage",
            ),
            (
                _capacity(before=59, after=60, over_before=1, over_after=2, requires=True),
                "worsens_overage",
            ),
            (_capacity(requires=None), "uncertain"),
            (_capacity(limit=None), "unknown_limit"),
        ],
    )
    def test_state_mapping(self, cap, state):
        assert _feasibility_state(cap) == state

    def test_a_forced_cut_flips_an_otherwise_favorable_deal(self):
        clean = analyze_trade(_sim([6000], [3000], utility=_utility(0.2), capacity=_capacity()))
        cut = analyze_trade(
            _sim(
                [6000],
                [3000],
                utility=_utility(0.2),
                capacity=_capacity(before=58, after=59, requires=True, drops=["X"], release=900),
            )
        )
        assert clean["recommendation"] == "LEAN_MAKE"
        assert cut["recommendation"] == "TOO_CLOSE"
        assert any("1 cut required" in r for r in cut["reasonsAgainst"])

    def test_resolving_an_overage_is_a_real_benefit(self):
        a = analyze_trade(
            _sim(
                [3010],
                [3000],
                utility=_utility(0.1),
                capacity=_capacity(before=59, after=58, over_before=1, over_after=0),
            )
        )
        assert a["recommendation"] == "LEAN_MAKE"
        assert any("back under the limit" in r for r in a["reasonsFor"])

    def test_no_legal_cleanup_caps_the_recommendation(self):
        a = analyze_trade(
            _sim(
                [8000],
                [3000],
                utility=_utility(4.0),
                capacity=_capacity(before=58, after=59, requires=True, exhausted=True),
            )
        )
        assert RECOMMENDATIONS.index(a["recommendation"]) >= RECOMMENDATIONS.index("TOO_CLOSE")

    def test_uncertain_capacity_is_named_not_neutral(self):
        a = analyze_trade(
            _sim([5000], [3000], utility=_utility(2.0), capacity=_capacity(requires=None))
        )
        feas = a["lenses"]["feasibility"]
        assert feas["available"] is False
        assert feas["unavailableReason"] == "uncertain"
        assert any("Taxi occupancy" in u for u in a["uncertainty"])

    def test_picks_never_occupy_spots(self):
        a = analyze_trade(_sim([5000], [3000], utility=_utility(2.0), capacity=_capacity()))
        assert a["lenses"]["feasibility"]["detail"]["picksOccupySpots"] is False


# ── Missing is never neutral ─────────────────────────────────────────────


class TestMissingIsNamed:
    def test_partial_projection_coverage_abstains(self):
        a = analyze_trade(_sim([3010], [3000], utility=_utility(6.0, coverage="partial")))
        roster = a["lenses"]["roster"]
        assert roster["available"] is False
        assert roster["unavailableReason"] == "partial_projection_coverage"
        # The partial number is still shown, labelled — just not counted.
        assert roster["detail"]["ppg"] == 6.0
        assert a["recommendation"] == "TOO_CLOSE"
        assert a["topUncertainty"].startswith("No league-scored projection")

    def test_unavailable_roster_lens_keeps_its_reason(self):
        a = analyze_trade(
            _sim(
                [5000],
                [3000],
                utility={"available": False, "unavailableReason": "season_unresolved"},
            )
        )
        assert a["lenses"]["roster"]["unavailableReason"] == "season_unresolved"
        assert a["confidence"] != "HIGH"

    def test_posture_and_current_season_equity_are_named_absent(self):
        a = analyze_trade(_sim([5000], [3000], utility=_utility(2.0)))
        names = {d["dimension"] for d in a["unavailableDimensions"]}
        assert {
            "marketCorroboration",
            "valueUncertainty",
            "strategicPosture",
            "currentSeasonEquity",
        } <= names
        for d in a["unavailableDimensions"]:
            assert d["reason"] and d["notes"]
        # Never smuggled in as a neutral lens.
        assert "strategicPosture" not in a["lenses"]

    def test_no_priced_assets_is_too_close_low_confidence(self):
        a = analyze_trade(_sim([], []))
        assert a["recommendation"] == "TOO_CLOSE"
        assert a["confidence"] == "LOW"


# ── Team Context (#842) ──────────────────────────────────────────────────


class TestTeamContext:
    def test_off_removes_roster_and_feasibility_without_touching_values(self):
        sim = _sim([3010], [3000], utility=_utility(4.0), capacity=_capacity(before=55, after=55))
        on = analyze_trade(copy.deepcopy(sim))
        off = analyze_trade({**copy.deepcopy(sim), "teamContext": {"applied": False}})
        assert off["teamContext"] == {"applied": False, "mode": "asset_only"}
        for lens in ("roster", "feasibility"):
            assert off["lenses"][lens]["available"] is False
            assert off["lenses"][lens]["unavailableReason"] == "asset_only_mode"
            assert off["lenses"][lens]["detail"]["note"] == "not included in Asset-Only analysis"
        # The market lens — canonical values and VA — is byte-identical.
        assert off["lenses"]["market"] == on["lenses"]["market"]
        assert off["recommendation"] == "TOO_CLOSE"  # market-even, nothing else counts
        assert on["recommendation"] == "LEAN_MAKE"  # the roster lens carries it

    def test_default_is_on(self):
        a = analyze_trade(_sim([5000], [3000], utility=_utility(2.0)))
        assert a["teamContext"]["applied"] is True


# ── Reasons cite measured numbers ────────────────────────────────────────


class TestReasons:
    def test_reasons_cite_the_actual_gap_ppg_and_entry_rate(self):
        players = [
            {"playerId": "a", "name": "Star WR", "role": "incoming", "lineupEntryPctAfter": 91.0},
            {"playerId": "b", "name": "Bench WR", "role": "outgoing", "lineupEntryPctBefore": 22.0},
            {"playerId": "c", "name": "Depth WR", "role": "outgoing", "lineupEntryPctBefore": 11.0},
        ]
        a = analyze_trade(_sim([5000], [3000], utility=_utility(2.4, players=players)))
        joined = " ".join(a["reasonsFor"])
        assert "2,000" in joined
        assert "+2.4 expected best-ball points per week" in joined
        assert "Star WR enters the optimal lineup in 91% of simulated weeks" in joined
        assert "Bench WR 22%" in joined

    def test_lost_bench_insurance_is_a_reason_against(self):
        a = analyze_trade(_sim([5000], [3000], utility=_utility(2.0, depth=0.9)))
        assert any("Bench insurance declines" in r for r in a["reasonsAgainst"])


class TestReasonsNeverTreatMissingAsZero:
    def test_unmeasured_outgoing_usage_is_not_reported(self):
        players = [
            {
                "playerId": "u",
                "name": "Unprojected RB",
                "role": "outgoing",
                "lineupEntryPctBefore": None,
            },
        ]
        a = analyze_trade(_sim([5000], [3000], utility=_utility(2.0, players=players)))
        assert not any("Unprojected RB" in r for r in a["reasonsFor"] + a["reasonsAgainst"])

    def test_an_abstaining_roster_lens_gives_no_roster_reasons(self):
        players = [
            {"playerId": "a", "name": "Star", "role": "incoming", "lineupEntryPctAfter": 95.0}
        ]
        a = analyze_trade(
            _sim(
                [3010],
                [3000],
                utility=_utility(5.0, coverage="partial", players=players, depth=2.0),
            )
        )
        text = " ".join(a["reasonsFor"] + a["reasonsAgainst"])
        assert "Star enters" not in text
        assert "Bench insurance" not in text
        assert "best-ball points per week" not in text

    def test_available_utility_without_a_number_is_unavailable_not_zero(self):
        broken = {**_utility(0.0), "impact": {"ppg": None, "standardError": None}}
        a = analyze_trade(_sim([5000], [3000], utility=broken))
        assert a["lenses"]["roster"]["unavailableReason"] == "impact_missing"

    def test_known_limit_with_unstated_overage_is_uncertain(self):
        cap = {**_capacity(), "overLimitBefore": None}
        assert _feasibility_state(cap) == "uncertain"

    def test_unpriced_forced_drop_is_not_claimed_as_a_cost(self):
        cap = _capacity(before=58, after=59, requires=True, drops=["X"], release=None)
        a = analyze_trade(_sim([3010], [3000], utility=_utility(0.1), capacity=cap))
        assert a["lenses"]["feasibility"]["direction"] == "neutral"
        assert any("1 cut required" in r for r in a["reasonsAgainst"])
