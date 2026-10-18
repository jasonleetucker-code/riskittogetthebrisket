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
        "RETOOL": "LONG_TERM",
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
