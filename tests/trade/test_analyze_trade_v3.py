"""#792 Batch 4 — Analyze Trade v3: sections, modifiers and the lineage rule.

What is pinned (methodology: ``docs/trade/ANALYZE_TRADE_V3_METHODOLOGY.md``):

* exactly two dimensions VOTE — canonical equity and roster utility; every
  other section is a MODIFIER (caps confidence, steps at most once on its own
  evidence) or CONTEXT (explains, never moves the decision);
* one evidence lineage never becomes two votes: the KTC Market benchmark and
  completed-trade comparables corroborate canonical value, they never vote;
  the confidence stamps cap confidence, they never flip direction; the posture
  LABEL alone never moves anything;
* missing is never zero: an asset KTC does not price is excluded from the
  benchmark, not counted as 0; an unstamped asset is unknown confidence;
* every section answers with the same fields, so "unavailable", "neutral" and
  "context only" never look alike.

The owner's §12 matrix runs as synthetic ``simulate_trade`` payloads here; the
engine feeds (Team Weakness, age portfolio, board keys) are pinned against the
real final-legal-roster path below.
"""

from __future__ import annotations

import pytest

from src.trade.analyze_trade import (
    RECOMMENDATIONS,
    ROLE_CONTEXT,
    ROLE_MODIFIER,
    ROLE_VOTE,
    analyze_trade,
)

SECTION_KEYS = {
    "canonicalEquity",
    "marketCorroboration",
    "valueUncertainty",
    "rosterImpact",
    "ageWindow",
    "currentSeasonEquity",
    "competitivePosture",
    "draftCapital",
    "feasibility",
}


def _asset(name, value, **extra):
    return {"name": name, "value": value, "confidenceBucket": "high", **extra}


def _utility(ppg, *, se=0.3, coverage="full"):
    return {
        "available": True,
        "impact": {"ppg": ppg, "standardError": se},
        "coverage": {
            "state": coverage,
            "tradedUnprojectedPlayerIds": ["x"] if coverage == "partial" else [],
        },
        "players": [],
        "depth": {"meanLossDeltaPpg": None},
        "cleanup": {"state": "none"},
    }


def _capacity(*, before=50, after=50, limit=58, requires=False, release=None, over=(0, 0)):
    return {
        "rosterLimit": limit,
        "sizeBefore": before,
        "sizeAfter": after,
        "openSpotsBefore": max(0, limit - before),
        "openSpotsAfter": max(0, limit - after),
        "overLimitBefore": over[0],
        "overLimitAfter": over[1],
        "requiresDrops": requires,
        "forcedDrops": [{"name": "Cut Guy", "position": "WR", "value": 900}] if requires else [],
        "forcedDropReleaseCost": release,
        "rungOrderWasTied": False,
        "ladderExhausted": False,
        "certainty": "exact",
    }


def _sim(recv, send, *, ppg=None, posture=None, season=None, capacity=None, **extra):
    payload = {
        "receiving": [
            a if isinstance(a, dict) else _asset(f"in{i}", a) for i, a in enumerate(recv)
        ],
        "sending": [a if isinstance(a, dict) else _asset(f"out{i}", a) for i, a in enumerate(send)],
        "boardAsOf": "2026-10-07T13:41:26Z",
    }
    if ppg is not None:
        payload["rosterUtility"] = _utility(ppg)
    if posture is not None:
        payload["competitivePosture"] = {
            "available": True,
            "label": posture,
            "probabilities": {posture: 1.0},
        }
    if season is not None:
        payload["seasonImpact"] = {"available": True, **season}
    if capacity is not None:
        payload["rosterCapacity"] = capacity
    payload.update(extra)
    return payload


# ── Contract shape ────────────────────────────────────────────────────────


class TestContract:
    def test_headline_fields_and_every_section(self):
        a = analyze_trade(_sim([6000], [3000], ppg=3.0))
        assert a["version"] == "analyze_trade_v3"
        assert a["decision"] in RECOMMENDATIONS
        assert a["decision"] == a["recommendation"]
        assert a["confidenceDetail"]["level"] == a["confidence"]
        assert a["confidenceDetail"]["reasons"]
        assert a["summary"].startswith(a["decisionLabel"])
        assert isinstance(a["strongestReasonsFor"], list)
        assert set(a["sections"]) == SECTION_KEYS
        for key, section in a["sections"].items():
            for field in ("available", "role", "lineage", "direction", "provenance", "freshness"):
                assert field in section, (key, field)
            if not section["available"]:
                assert section["unavailableReason"], key
            assert section["freshness"] == {"boardAsOf": "2026-10-07T13:41:26Z"}

    def test_exactly_two_sections_vote(self):
        a = analyze_trade(_sim([6000], [3000], ppg=3.0))
        roles = {k: s["role"] for k, s in a["sections"].items()}
        assert {k for k, r in roles.items() if r == ROLE_VOTE} == {
            "canonicalEquity",
            "rosterImpact",
        }
        assert roles["marketCorroboration"] == ROLE_MODIFIER
        assert roles["valueUncertainty"] == ROLE_MODIFIER
        assert roles["ageWindow"] == ROLE_CONTEXT
        assert roles["currentSeasonEquity"] == ROLE_CONTEXT
        assert roles["draftCapital"] == ROLE_CONTEXT


# ── §12 matrix ────────────────────────────────────────────────────────────


class TestOwnerMatrix:
    def test_balanced_fair_trade_is_too_close(self):
        a = analyze_trade(_sim([5000], [5050], ppg=0.2))
        assert a["decision"] == "TOO_CLOSE"

    def test_obvious_favorable_trade_is_make(self):
        a = analyze_trade(_sim([7000], [3000], ppg=4.0))
        assert a["decision"] == "MAKE"
        assert a["confidence"] == "HIGH"

    def test_obvious_unfavorable_trade_is_pass(self):
        a = analyze_trade(_sim([2000], [7000], ppg=-4.0))
        assert a["decision"] == "PASS"

    def test_raw_value_win_that_harms_the_roster_is_too_close(self):
        a = analyze_trade(_sim([6000], [4000], ppg=-3.0))
        assert a["decision"] == "TOO_CLOSE"
        assert a["strongestReasonsFor"] and a["strongestReasonsAgainst"]

    def test_push_raw_loss_with_material_title_gain_steps_toward_make(self):
        base = _sim([4500], [5000], ppg=0.2)
        plain = analyze_trade(base)
        a = analyze_trade(
            _sim(
                [4500],
                [5000],
                ppg=0.2,
                posture="PUSH",
                season={"titleDeltaPp": 4.0, "titleSignificant": True},
            )
        )
        assert RECOMMENDATIONS.index(a["decision"]) < RECOMMENDATIONS.index(plain["decision"])
        fit = a["sections"]["competitivePosture"]["strategicFit"]
        assert fit["step"] == 1 and "title odds" in fit["reason"]

    def test_push_paying_value_for_no_title_gain_steps_toward_pass(self):
        a = analyze_trade(
            _sim(
                [4500],
                [5000],
                ppg=0.2,
                posture="PUSH",
                season={"titleDeltaPp": 0.3, "titleSignificant": False},
            )
        )
        assert a["sections"]["competitivePosture"]["strategicFit"]["step"] == -1

    def test_rebuild_buying_an_aging_veteran_steps_toward_pass(self):
        vet = _asset("Old RB", 4000, age=30)
        young = _asset("Young WR", 4000, age=23)
        rebuild = analyze_trade(_sim([vet], [young], ppg=1.5, posture="REBUILD"))
        push = analyze_trade(_sim([vet], [young], ppg=1.5, posture="PUSH"))
        assert rebuild["sections"]["competitivePosture"]["strategicFit"]["step"] == -1
        assert RECOMMENDATIONS.index(rebuild["decision"]) > RECOMMENDATIONS.index(push["decision"])

    def test_push_buying_an_aging_veteran_is_not_penalised(self):
        vet = _asset("Old RB", 4000, age=30)
        young = _asset("Young WR", 4000, age=23)
        a = analyze_trade(_sim([vet], [young], ppg=1.5, posture="PUSH"))
        assert a["sections"]["competitivePosture"]["strategicFit"]["step"] == 0

    def test_forced_drop_package_steps_toward_pass(self):
        base = analyze_trade(_sim([5600], [5000], ppg=1.5))
        cut = analyze_trade(
            _sim(
                [5600],
                [5000],
                ppg=1.5,
                capacity=_capacity(before=58, after=59, requires=True, release=900),
            )
        )
        assert RECOMMENDATIONS.index(cut["decision"]) > RECOMMENDATIONS.index(base["decision"])
        assert any("cut" in r for r in cut["strongestReasonsAgainst"])

    def test_package_that_frees_a_spot_says_so(self):
        a = analyze_trade(
            _sim([6000], [3000, 2500], ppg=1.5, capacity=_capacity(before=58, after=57))
        )
        assert a["sections"]["feasibility"]["detail"]["state"] == "fits_cleanly"
        assert a["sections"]["feasibility"]["detail"]["openSpotsAfter"] == 1

    def test_already_over_limit_roster_resolved_is_favourable(self):
        a = analyze_trade(
            _sim(
                [5000], [3000, 2500], ppg=0.2, capacity=_capacity(before=59, after=58, over=(1, 0))
            )
        )
        assert a["sections"]["feasibility"]["direction"] == "favors"

    @pytest.mark.parametrize(
        "recv,send", [([6000], [3500, 3000]), ([5000, 3000], [4000, 2500, 2000])]
    )
    def test_two_for_one_and_three_for_two_use_value_adjustment(self, recv, send):
        a = analyze_trade(_sim(recv, send, ppg=1.0))
        eq = a["sections"]["canonicalEquity"]["detail"]
        # The package treatment is shown SEPARATELY from the raw difference.
        assert eq["rawGap"] == sum(recv) - sum(send)
        assert eq["vaAdjustedGap"] != eq["rawGap"]

    def test_pick_heavy_trade_reports_draft_capital_without_inventing_slots(self):
        picks = [
            _asset("2027 Early 1st", 5200, assetClass="pick", sourceLabel="2027 1st (own)"),
            _asset("2028 Mid 2nd", 1400, assetClass="pick", sourceLabel="2028 2nd (own)"),
        ]
        a = analyze_trade(_sim([_asset("Star", 7000)], picks, ppg=2.0))
        dc = a["sections"]["draftCapital"]
        assert dc["available"] is True
        assert [p["label"] for p in dc["detail"]["lost"]] == ["2027 1st (own)", "2028 2nd (own)"]
        assert dc["detail"]["slotProjection"]["state"] == "unvalidated"

    def test_early_mid_late_firsts_keep_their_board_grade(self):
        for grade, value in (("Early", 6000), ("Mid", 4800), ("Late", 4000)):
            pick = _asset(f"2027 {grade} 1st", value, assetClass="pick")
            a = analyze_trade(_sim([pick], [_asset("X", 4500)], ppg=0.0))
            assert a["sections"]["draftCapital"]["detail"]["acquired"][0]["boardGrade"] == (
                f"2027 {grade} 1st"
            )

    def test_a_pick_the_sender_does_not_own_is_named_never_counted(self):
        a = analyze_trade(
            _sim(
                [5000],
                [3000],
                ppg=1.0,
                ownedPickChecks={
                    "notOwnedBySender": [
                        {"label": "2027 1st (Team B)", "actualOwnerName": "Team B"}
                    ]
                },
            )
        )
        dc = a["sections"]["draftCapital"]["detail"]
        assert dc["notOwnedBySender"] == [
            {"label": "2027 1st (Team B)", "actualOwnerName": "Team B"}
        ]
        assert a["sections"]["canonicalEquity"]["detail"]["sendingValue"] == 3000

    def test_sparse_market_evidence_is_named_not_neutral(self):
        a = analyze_trade(_sim([5000], [3000], ppg=1.0))
        corr = a["sections"]["marketCorroboration"]
        assert corr["available"] is False
        assert corr["unavailableReason"] == "no_market_benchmark_for_traded_assets"

    def test_stale_board_freshness_travels_with_every_section(self):
        a = analyze_trade(_sim([5000], [3000], ppg=1.0, boardAsOf="2026-09-01T00:00:00Z"))
        assert {s["freshness"]["boardAsOf"] for s in a["sections"].values()} == {
            "2026-09-01T00:00:00Z"
        }

    def test_market_disagreement_caps_confidence_and_never_flips(self):
        agree = analyze_trade(
            _sim(
                [_asset("A", 7000, ktcMarketValue=7000)],
                [_asset("B", 3000, ktcMarketValue=3000)],
                ppg=4.0,
            )
        )
        disagree = analyze_trade(
            _sim(
                [_asset("A", 7000, ktcMarketValue=3000)],
                [_asset("B", 3000, ktcMarketValue=7000)],
                ppg=4.0,
            )
        )
        assert agree["decision"] == disagree["decision"] == "MAKE"
        assert agree["confidence"] == "HIGH"
        assert disagree["confidence"] == "MEDIUM"
        assert disagree["sections"]["marketCorroboration"]["direction"] == "disagrees"
        assert any("KTC Market" in u for u in disagree["uncertainty"])

    def test_idp_heavy_trade_without_benchmark_still_decides_on_the_votes(self):
        idp = [_asset("LB1", 3000, pos="IDP"), _asset("DL1", 2500, pos="IDP")]
        a = analyze_trade(_sim([_asset("Edge", 6500, pos="IDP")], idp, ppg=2.0))
        assert a["decision"] in ("MAKE", "LEAN_MAKE")
        assert a["sections"]["marketCorroboration"]["available"] is False

    def test_offense_idp_and_picks_together(self):
        recv = [
            _asset("WR", 5000, ktcMarketValue=5100),
            _asset("2027 Mid 1st", 4000, assetClass="pick"),
        ]
        send = [_asset("LB", 3000), _asset("QB", 5500, ktcMarketValue=5400)]
        a = analyze_trade(_sim(recv, send, ppg=0.5))
        corr = a["sections"]["marketCorroboration"]["detail"]
        assert corr["assetsWithoutBenchmark"] == ["2027 Mid 1st", "LB"]
        assert a["sections"]["draftCapital"]["available"] is True

    def test_missing_simulation_evidence_is_named(self):
        a = analyze_trade(_sim([5000], [3000], ppg=1.0))
        season = a["sections"]["currentSeasonEquity"]
        assert season["available"] is False
        assert season["unavailableReason"] == "counterfactual_not_wired"

    def test_missing_projections_abstain_the_roster_vote(self):
        a = analyze_trade(
            {**_sim([6000], [3000]), "rosterUtility": _utility(5.0, coverage="partial")}
        )
        assert a["sections"]["rosterImpact"]["available"] is False
        assert a["sections"]["rosterImpact"]["unavailableReason"] == "partial_projection_coverage"

    def test_comparables_section_reports_state_when_unwired(self):
        a = analyze_trade(_sim([5000], [3000], ppg=1.0))
        comps = a["sections"]["marketCorroboration"]["detail"]["comparables"]
        assert comps["state"] == "unavailable"


# ── Lineage and missingness ───────────────────────────────────────────────


class TestLineage:
    def test_benchmark_and_comparables_never_vote(self):
        # Same votes, wildly different market evidence: the DIRECTION is the
        # same; only confidence and the named uncertainty may differ.
        base = _sim([6000], [3000], ppg=3.0)
        with_comps = {
            **base,
            "marketComparables": {"state": "ok", "marketDirection": "proposed_side_overpays"},
        }
        assert analyze_trade(base)["decision"] == analyze_trade(with_comps)["decision"]

    def test_posture_label_alone_never_moves_the_decision(self):
        base = _sim([5000], [3000], ppg=2.0)
        plain = analyze_trade(base)["decision"]
        for label in ("PUSH", "HOLD", "RETOOL", "REBUILD"):
            assert analyze_trade(_sim([5000], [3000], ppg=2.0, posture=label))["decision"] == plain

    def test_strategic_fit_moves_at_most_one_step(self):
        vet = _asset("Old", 4000, age=33)
        a = analyze_trade(_sim([vet], [_asset("Y", 4000, age=22)], ppg=0.0, posture="REBUILD"))
        plain = analyze_trade(_sim([vet], [_asset("Y", 4000, age=22)], ppg=0.0))
        assert RECOMMENDATIONS.index(a["decision"]) - RECOMMENDATIONS.index(plain["decision"]) == 1

    def test_confidence_stamps_cap_and_never_flip(self):
        low = analyze_trade(_sim([_asset("A", 7000, confidenceBucket="low")], [3000], ppg=4.0))
        assert low["decision"] == "MAKE"
        assert low["confidence"] == "LOW"
        assert any("low-confidence" in r for r in low["confidenceDetail"]["reasons"])


class TestMissingIsNeverZero:
    def test_an_unpriced_benchmark_is_excluded_not_zero(self):
        a = analyze_trade(
            _sim(
                [_asset("A", 5000, ktcMarketValue=5000), _asset("IDP", 2000)],
                [_asset("B", 5000, ktcMarketValue=5000)],
                ppg=0.0,
            )
        )
        corr = a["sections"]["marketCorroboration"]["detail"]
        assert corr["benchmarkGap"] == 0
        assert corr["coverage"] == round(10000 / 12000, 3)

    def test_unstamped_confidence_is_unknown_not_high(self):
        a = analyze_trade(
            _sim([{"name": "A", "value": 7000}], [{"name": "B", "value": 3000}], ppg=4.0)
        )
        assert a["confidence"] == "MEDIUM"
        assert any("no confidence stamp" in r for r in a["confidenceDetail"]["reasons"])

    def test_missing_ages_leave_the_window_unavailable(self):
        a = analyze_trade(_sim([5000], [3000], ppg=1.0))
        assert a["sections"]["ageWindow"]["unavailableReason"] == "no_age_evidence"


# ── Engine feeds on the real final-legal-roster path ──────────────────────


class TestFinalRosterFeeds:
    def test_weakness_and_age_portfolio_on_the_final_legal_roster(self):
        from src.api.trade_simulator import roster_profile_inputs
        from src.trade.roster_capacity import assess_roster_capacity, simulate_final_legal_roster
        from tests.trade.test_trade_consumes_roster import _context, _row

        context = _context()
        capacity = assess_roster_capacity(context, incoming_players=["IN1"])
        board = [_row(n, v, p) for n, v, p in (("QB1", 5000.0, "QB"), ("IN1", 6000.0, "WR"))]
        for row, age in zip(board, (31, 24)):
            row["age"] = age
        profile = roster_profile_inputs({"playersArray": board, "sleeper": {"teams": [{}, {}]}})
        assert profile["team_count"] == 2
        assert profile["ages"] == {"qb1": 31.0, "in1": 24.0}

        final = simulate_final_legal_roster(context, capacity, incoming_players=["IN1"], **profile)
        assert isinstance(final["weaknessBefore"], dict)
        assert isinstance(final["weaknessAfter"], dict)
        assert final["agePortfolioBefore"]["available"] is True
        assert final["agePortfolioAfter"]["available"] is True

    def test_without_profile_inputs_the_shape_is_unchanged(self):
        from src.trade.roster_capacity import assess_roster_capacity, simulate_final_legal_roster
        from tests.trade.test_trade_consumes_roster import _context

        context = _context()
        capacity = assess_roster_capacity(context, incoming_players=["IN1"])
        final = simulate_final_legal_roster(context, capacity, incoming_players=["IN1"])
        assert final["weaknessBefore"] is None
        assert "agePortfolioBefore" not in final

    def test_a_single_team_league_measures_no_weakness(self):
        from src.api.trade_simulator import roster_profile_inputs

        assert (
            roster_profile_inputs({"playersArray": [], "sleeper": {"teams": [{}]}})["team_count"]
            is None
        )
