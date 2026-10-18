"""TC-C -- the ONE canonical trade decision (owner decisions 1, 2, 5; 2026-10-18).

Driven through ``analyze_trade`` with synthetic simulation payloads, so every
case exercises the real lenses feeding ``src.trade.trade_decision.decide``.
"""

from __future__ import annotations

import copy

import pytest

from src.trade.analyze_trade import analyze_trade
from src.trade.trade_decision import HEADLINE_TEXT, POSTURE_TO_GOAL

ORDER = {"NO": 0, "NO_TOO_CLOSE": 1, "YES": 2}


def _utility(ppg, *, se=0.3, coverage="full"):
    return {
        "available": True,
        "unit": "expected best-ball points per week (exact league scoring)",
        "impact": {"ppg": ppg, "standardError": se},
        "coverage": {
            "state": coverage,
            "tradedUnprojectedPlayerIds": ["p9"] if coverage == "partial" else [],
        },
        "players": [],
        "depth": {"meanLossDeltaPpg": None},
        "cleanup": {"state": "none", "forcedDropIds": [], "candidatesTied": False},
    }


def _capacity(**kw):
    base = {
        "rosterLimit": 58,
        "sizeBefore": 57,
        "sizeAfter": 57,
        "openSpotsBefore": 1,
        "openSpotsAfter": 1,
        "overLimitBefore": 0,
        "overLimitAfter": 0,
        "requiresDrops": False,
        "forcedDrops": [],
        "forcedDropReleaseCost": None,
        "rungOrderWasTied": False,
        "ladderExhausted": False,
        "certainty": "exact",
    }
    base.update(kw)
    return base


def _posture(label="PUSH", evidence="measured"):
    return {
        "available": True,
        "label": label,
        "evidence": evidence,
        "probabilities": {"PUSH": 0.7, "HOLD": 0.1, "RETOOL": 0.1, "REBUILD": 0.1},
        "confidence": 0.7,
        "paramsVersion": "posture_v1_prior",
    }


def _sim(recv, send, *, ppg=0.0, team=True, posture="PUSH", capacity=None, assets=None, **extra):
    sim = {
        "receiving": [
            {"name": f"in{i}", "value": v, "confidenceBucket": "high", **(assets or {})}
            for i, v in enumerate(recv)
        ],
        "sending": [
            {"name": f"out{i}", "value": v, "confidenceBucket": "high"} for i, v in enumerate(send)
        ],
    }
    if team:
        sim["rosterUtility"] = _utility(ppg) if ppg is not None else None
        sim["rosterCapacity"] = capacity or _capacity()
        if posture:
            sim["competitivePosture"] = _posture(posture)
    else:
        sim["teamContext"] = {"applied": False}
    sim.update(extra)
    return sim


def _decision(sim, **kw):
    return analyze_trade(sim, **kw)["decision"]


# ── Owner decision 1: near tie vs not enough evidence ───────────────────────


def test_near_tie_with_complete_evidence_is_no_too_close():
    d = _decision(_sim([5000], [5050], ppg=0.2))
    assert d["headline"] == "NO_TOO_CLOSE"
    assert d["headlineText"] == HEADLINE_TEXT["NO_TOO_CLOSE"] == "NO — TOO CLOSE"
    assert d["missingEvidence"] == []
    assert d["confidence"]["level"] in ("HIGH", "MEDIUM", "LOW")


def test_unpriced_asset_is_not_enough_evidence_never_a_capped_recommendation():
    # TC-A left this open: Analyze gave a capped-confidence call while the meter
    # refused.  Now both refuse.
    d = _decision(_sim([6000, 0], [5000], ppg=1.5))
    assert d["headline"] == "NOT_ENOUGH_EVIDENCE"
    assert {g["code"] for g in d["missingEvidence"]} == {"unpriced_assets"}
    assert d["confidence"]["level"] is None
    assert d["subtext"]


@pytest.mark.parametrize(
    "extra,code",
    [
        ({"unresolvedIn": ["Mystery Man"]}, "off_board_assets"),
        (
            {
                "ownedPickChecks": {
                    "notOwnedBySender": [{"label": "2027 1st", "actualOwnerName": "Joe"}]
                }
            },
            "unheld_assets",
        ),
    ],
)
def test_missing_assets_are_named(extra, code):
    d = _decision(_sim([6000], [5000], ppg=1.5, **extra))
    assert d["headline"] == "NOT_ENOUGH_EVIDENCE"
    assert code in {g["code"] for g in d["missingEvidence"]}


def test_quarantined_and_stale_values_are_not_enough_evidence():
    q = _decision(_sim([6000], [5000], ppg=1.5, assets={"quarantined": True}))
    s = _decision(_sim([6000], [5000], ppg=1.5, assets={"valueFreshness": "low"}))
    assert q["headline"] == s["headline"] == "NOT_ENOUGH_EVIDENCE"
    assert {g["code"] for g in q["missingEvidence"]} == {"quarantined_values"}
    assert {g["code"] for g in s["missingEvidence"]} == {"stale_values"}
    ok = _decision(_sim([6000], [5000], ppg=1.5, assets={"valueFreshness": "medium"}))
    assert ok["headline"] != "NOT_ENOUGH_EVIDENCE"


def test_unknown_pick_ownership_with_picks_in_the_trade():
    sim = _sim([6000], [5000], ppg=1.5, pickOwnership={"state": "unavailable", "reason": "x"})
    sim["receiving"][0]["assetClass"] = "pick"
    d = _decision(sim)
    assert {g["code"] for g in d["missingEvidence"]} == {"pick_ownership_unknown"}


def test_unknown_roster_and_unknown_posture():
    sim = _sim([6000], [5000], ppg=1.5, posture=None)
    sim["rosterUtility"] = {"available": False, "unavailableReason": "roster_capacity_unavailable"}
    d = _decision(sim)
    assert {g["code"] for g in d["missingEvidence"]} == {"roster_unknown", "posture_unknown"}
    # An explicit strategy cures the posture gap (but not the roster one).
    d2 = _decision(sim, team_goal="BALANCED")
    assert {g["code"] for g in d2["missingEvidence"]} == {"roster_unknown"}


def test_unprojected_player_blocks_win_now_but_not_long_term():
    sim = _sim([6000], [5000], ppg=None)
    sim["rosterUtility"] = _utility(1.0, coverage="partial")
    assert _decision(sim)["headline"] == "NOT_ENOUGH_EVIDENCE"  # PUSH -> WIN_NOW
    assert _decision(sim, team_goal="LONG_TERM")["headline"] == "YES"


def test_offseason_roster_is_not_applicable_not_missing():
    sim = _sim([6000], [5000], ppg=None)
    sim["rosterUtility"] = {"available": False, "unavailableReason": "season_unresolved"}
    d = _decision(sim)
    assert d["headline"] == "YES"
    assert d["components"]["rosterBenefit"]["state"] == "not_applicable"
    assert d["confidence"]["axes"]["coverage"] == "MEDIUM"


def test_unpriced_forced_cut_is_not_enough_evidence():
    cap = _capacity(
        state=None, requiresDrops=True, sizeAfter=59, overLimitAfter=1, unpricedForcedDrops=1
    )
    d = _decision(_sim([6000], [5000], ppg=1.5, capacity=cap))
    assert "forced_drop_unpriced" in {g["code"] for g in d["missingEvidence"]}


# ── Owner decision 2: strategy from posture, always shown, overridable ─────


@pytest.mark.parametrize("label,goal", sorted(POSTURE_TO_GOAL.items()))
def test_strategy_follows_posture(label, goal):
    d = _decision(_sim([6000], [5000], ppg=1.5, posture=label))
    assert d["strategy"]["used"] == goal
    assert d["strategy"]["source"] == "posture"
    assert d["posture"]["label"] == label


def test_strategy_mapping_is_the_owner_decision():
    assert POSTURE_TO_GOAL == {
        "PUSH": "WIN_NOW",
        "HOLD": "BALANCED",
        "RETOOL": "BALANCED",
        "REBUILD": "LONG_TERM",
    }


def test_no_evidence_posture_is_balanced_and_says_so():
    sim = _sim([6000], [5000], ppg=1.5)
    sim["competitivePosture"] = _posture("HOLD", evidence="no_evidence")
    d = _decision(sim)
    assert d["strategy"] == {**d["strategy"], "used": "BALANCED", "source": "posture_no_evidence"}


def test_override_is_used_and_echoed_and_invalid_is_reported():
    d = _decision(_sim([6000], [5000], ppg=1.5), team_goal="win now")
    assert d["strategy"]["requested"] == "win now"
    assert d["strategy"]["used"] == "WIN_NOW" and d["strategy"]["source"] == "user"
    bad = _decision(_sim([6000], [5000], ppg=1.5, posture="REBUILD"), team_goal="moon")
    assert bad["strategy"]["requestedValid"] is False
    assert bad["strategy"]["used"] == "LONG_TERM"  # falls back to posture


def test_strategy_decides_only_a_disagreement():
    # Value favours (+1,000 on 6,000: unfair band) but the roster loses 3 ppg.
    sim = _sim([6000], [5000], ppg=-3.0)
    assert _decision(sim, team_goal="LONG_TERM")["headline"] == "YES"
    assert _decision(sim, team_goal="WIN_NOW")["headline"] == "NO"
    d = _decision(sim, team_goal="WIN_NOW")
    assert d["deciding"] == "strategy"
    assert d["confidence"]["axes"]["agreement"] == "LOW"
    # When they agree, the strategy changes nothing.
    agree = _sim([6000], [5000], ppg=3.0)
    assert {
        _decision(agree, team_goal=g)["headline"] for g in ("WIN_NOW", "BALANCED", "LONG_TERM")
    } == {"YES"}


# ── Gates and feasibility ───────────────────────────────────────────────────


def test_no_legal_cleanup_is_no():
    d = _decision(_sim([9000], [3000], ppg=5.0, capacity=_capacity(ladderExhausted=True)))
    assert d["headline"] == "NO"
    assert d["deciding"] == "executionGate"


def test_forced_cut_value_is_charged_once_against_the_package():
    cap = _capacity(
        sizeAfter=59,
        requiresDrops=True,
        overLimitAfter=1,
        forcedDropReleaseCost=900,
        forcedDrops=[{"name": "Bench Guy", "value": 900}],
    )
    plain = _decision(_sim([6000], [5000], ppg=0.0))
    cut = _decision(_sim([6000], [5000], ppg=0.0, capacity=cap))
    assert plain["components"]["objectiveValue"]["netGap"] == 1000
    assert cut["components"]["objectiveValue"]["netGap"] == 100
    assert cut["components"]["objectiveValue"]["forcedReleaseCost"] == 900
    assert plain["headline"] == "YES" and cut["headline"] == "NO_TOO_CLOSE"


# ── Properties ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ppg", [-3.0, 0.0, 3.0])
@pytest.mark.parametrize("goal", ["WIN_NOW", "BALANCED", "LONG_TERM"])
def test_more_incoming_value_never_worsens_the_decision(ppg, goal):
    prev = -1
    for incoming in range(3000, 9001, 250):
        h = _decision(_sim([incoming], [6000], ppg=ppg), team_goal=goal)["headline"]
        assert ORDER[h] >= prev, (incoming, h)
        prev = ORDER[h]


def test_asset_only_is_side_symmetric():
    for a, b in ((7000, 5000), (5000, 7000), (6000, 6050)):
        d1 = _decision(_sim([a], [b], team=False))
        d2 = _decision(_sim([b], [a], team=False))
        flip = {"YES": "NO", "NO": "YES", "NO_TOO_CLOSE": "NO_TOO_CLOSE"}
        assert d2["headline"] == flip[d1["headline"]]
        assert d1["strategy"]["source"] == "asset_only"


def test_team_impact_cannot_influence_the_decision():
    """Owner decision 5: the retired verdict does not come back in any form."""
    sim = _sim([6000], [5000], ppg=1.5)
    base = _decision(copy.deepcopy(sim))
    for impact in (
        {"verdict": "decline", "compositeScore": -99},
        {"verdict": "accept", "compositeScore": 99, "fitScore": 100},
    ):
        assert _decision({**copy.deepcopy(sim), "teamImpact": impact}) == base


def test_the_decision_never_executes_and_carries_its_receipts():
    d = _decision(_sim([6000], [5000], ppg=1.5))
    assert d["recommendationOnly"] is True and d["executes"] is False
    assert d["bands"]["status"] == "PROVISIONAL"
    assert d["confidence"]["isProbability"] is False
    assert isinstance(d["confidence"]["statement"], str) and d["confidence"]["statement"]
    for r in d["reasons"]:
        assert r["text"] and isinstance(r["evidence"], dict)
    assert d["primaryReason"] in d["reasons"]


# ── What would change it / coverage / receipt (TC-C remaining items) ───────


def _flip(d, kind):
    return next((w for w in d["whatWouldChange"] if w["kind"] == kind), None)


def test_price_flip_is_found_by_rerunning_and_actually_flips():
    sim = _sim([5000], [5050], ppg=0.2)  # NO — TOO CLOSE
    d = _decision(sim)
    w = _flip(d, "price")
    assert w and w["flipsTo"] == "YES" and w["evidence"]["side"] == "receive"
    v = w["evidence"]["assetValue"]
    # Re-run the whole analysis with that asset added: it flips; one step less does not.
    bigger = _sim([5000, v], [5050], ppg=0.2)
    smaller = _sim([5000, v - 25], [5050], ppg=0.2)
    assert _decision(bigger)["headline"] == "YES"
    assert _decision(smaller)["headline"] == "NO_TOO_CLOSE"


def test_a_yes_names_what_you_would_have_to_add_to_lose_it():
    d = _decision(_sim([7000], [5000], ppg=1.5))
    w = _flip(d, "price")
    assert d["headline"] == "YES" and w["evidence"]["side"] == "send" and w["flipsTo"] != "YES"


def test_strategy_flip_listed_only_when_it_changes_the_answer():
    d = _decision(_sim([6000], [5000], ppg=-3.0), team_goal="WIN_NOW")
    flips = {
        w["evidence"]["strategy"]: w["flipsTo"]
        for w in d["whatWouldChange"]
        if w["kind"] == "strategy"
    }
    assert flips == {"LONG_TERM": "YES"}
    agree = _decision(_sim([6000], [5000], ppg=3.0))
    assert not [w for w in agree["whatWouldChange"] if w["kind"] == "strategy"]


def test_not_enough_evidence_lists_what_to_resolve():
    d = _decision(_sim([6000, 0], [5000], ppg=1.5))
    assert [w["kind"] for w in d["whatWouldChange"]] == ["evidence"]
    assert d["whatWouldChange"][0]["flipsTo"] is None


def test_coverage_has_all_ten_dimensions_and_never_claims_the_absent():
    d = _decision(_sim([6000], [5000], ppg=1.5))
    cov = {c["dimension"]: c for c in d["coverage"]}
    assert len(d["coverage"]) == 10
    assert cov["asset_value"]["state"] == "evaluated" and cov["asset_value"]["evidence"]
    assert cov["opportunity_cost"]["state"] == "unavailable"
    assert cov["opportunity_cost"]["evidence"] is None
    assert cov["long_term"]["state"] == "partial"
    for c in d["coverage"]:
        if c["state"] in ("unavailable", "not_applicable", "excluded_by_mode"):
            assert c["evidence"] is None
    off = {c["dimension"]: c for c in _decision(_sim([6000], [5000], team=False))["coverage"]}
    assert off["immediate_improvement"]["state"] == "excluded_by_mode"
    assert off["immediate_improvement"]["exclusionReason"] == "asset_only_mode"


def test_only_independent_deciding_dimensions_decide():
    d = _decision(_sim([6000], [5000], ppg=1.5))
    for c in d["coverage"]:
        if c["role"] == "decides":
            assert c["evidenceKind"] == "independent"


def test_receipt_is_reproducible_and_sensitive():
    sim = _sim([6000], [5000], ppg=1.5)
    r1 = analyze_trade(copy.deepcopy(sim), provenance={"boardStamp": "2026-10-17T00:00:00Z"})
    r2 = analyze_trade(copy.deepcopy(sim), provenance={"boardStamp": "2026-10-17T00:00:00Z"})
    rec = r1["decision"]["receipt"]
    assert rec == r2["decision"]["receipt"]
    assert rec["boardStamp"] == "2026-10-17T00:00:00Z"
    assert rec["analyzeConfig"]["materialityPpg"] == 1.0
    assert rec["bands"] == "fairness_bands_v1"
    assert rec["packageModel"]["id"] == "geom_q078_v1"
    other = analyze_trade(_sim([6100], [5000], ppg=1.5))["decision"]["receipt"]
    goal = analyze_trade(copy.deepcopy(sim), team_goal="LONG_TERM")["decision"]["receipt"]
    assert len({rec["requestHash"], other["requestHash"], goal["requestHash"]}) == 3


# ── Owner decision (final, 2026-10-18): RETOOL → BALANCED ───────────────────


@pytest.mark.parametrize(
    "label,goal",
    [("PUSH", "WIN_NOW"), ("RETOOL", "BALANCED"), ("REBUILD", "LONG_TERM"), ("HOLD", "BALANCED")],
)
def test_all_four_classifications_map_and_show_in_decision_and_receipt(label, goal):
    d = _decision(_sim([6000], [5000], ppg=1.5, posture=label))
    st = d["strategy"]
    assert (st["inferredClassification"], st["inferredStrategy"], st["used"]) == (label, goal, goal)
    assert st["reasoning"]
    rec = d["receipt"]["strategy"]
    assert (rec["inferredClassification"], rec["used"], rec["source"]) == (label, goal, "posture")
    assert rec["reasoning"] == st["reasoning"]
    strategy_reason = next(r for r in d["reasons"] if r["component"] == "strategy")
    assert strategy_reason["evidence"]["inferredClassification"] == label


@pytest.mark.parametrize("label", ["PUSH", "RETOOL", "REBUILD", "HOLD"])
@pytest.mark.parametrize("override", ["WIN_NOW", "BALANCED", "LONG_TERM"])
def test_override_works_from_every_classification(label, override):
    d = _decision(_sim([6000], [5000], ppg=1.5, posture=label), team_goal=override)
    assert d["strategy"]["used"] == override and d["strategy"]["source"] == "user"
    assert d["strategy"]["requested"] == override
    assert d["strategy"]["inferredClassification"] == label
    assert d["receipt"]["strategy"]["requested"] == override


def test_retool_is_never_reported_as_rebuilder():
    d = _decision(_sim([6000], [5000], ppg=1.5, posture="RETOOL"))
    # Every user-facing sentence, and every field naming the classification.
    words = [d["strategy"]["reasoning"], d["receipt"]["strategy"]["reasoning"]]
    words += [r["text"] for r in d["reasons"]] + [w["text"] for w in d["whatWouldChange"]]
    assert not any("rebuild" in w.lower() for w in words)
    assert "retool" in d["strategy"]["reasoning"].lower()
    assert d["strategy"]["inferredClassification"] == "RETOOL"
    assert d["receipt"]["strategy"]["inferredClassification"] == "RETOOL"
    assert d["posture"]["label"] == "RETOOL"
    assert d["strategy"]["used"] == "BALANCED"


def test_balanced_does_not_trade_meaningful_current_production_for_value():
    # RETOOL -> BALANCED: a large lineup gain (+4 ppg) for a modest value loss
    # (-400 on ~8,400, slight band) is a YES; LONG_TERM would say NO.
    sim = _sim([8000], [8400], ppg=4.0, posture="RETOOL")
    d = _decision(sim)
    assert d["strategy"]["used"] == "BALANCED"
    assert d["components"]["objectiveValue"]["magnitude"] == "modest"
    assert d["headline"] == "YES"
    assert _decision(sim, team_goal="LONG_TERM")["headline"] == "NO"
    # ...and symmetric: a large value gain for a modest lineup loss is a YES too.
    sym = _sim([9000], [7000], ppg=-1.5, posture="RETOOL")
    assert _decision(sym)["headline"] == "YES"
