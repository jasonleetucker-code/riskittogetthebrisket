"""NO TRANSACTION as an explicit, evidenced option (MD-112, Part 9A).

``trade_decision.status_quo`` states, by name, the comparison every decision
already makes implicitly: both decision components are measured against doing
nothing (A = the trade's adjusted package gap net of forced releases, B =
lineup points after minus before), so the status quo is the zero of each.

Independent oracle: every expected number below is worked by hand from the
package-model definition (``geom_q078_v1``: ``U = sum q**i * v_i`` over a
package's values sorted high to low, ``q = 0.78``; adjusted gap =
``U(receives) - U(sends)``) and the fairness-band definition
(``config/trade/fairness_bands.json``: a gap is inside the neutral band when
``|gap| < max(250, 3.5% x the larger package utility)``), plus the roster
lens's declared neutral band (``max(1.0 ppg, 2 x standard error)``).  None of
them is read back from the code under test.

Worked cases (Team Context ON unless noted; posture PUSH -> WIN_NOW):

* clearly good   recv 7000 / send 5000, +3.0 ppg (se 0.3)
  net +2000, band half-width max(250, 245) = 250 -> trade clears by 1750;
  ppg band max(1.0, 0.6) = 1.0 -> trade clears by 2.0.  YES -> keep nothing.
* clearly bad    the mirror: declining clears by 1750 / 2.0.  NO -> declining.
* near-zero gap  recv 5000 / send 5050, +0.2 ppg: -50 and +0.2 sit inside
  250 and 1.0.  NO — TOO CLOSE -> declining (a near tie never favours acting).
* insufficient   an unpriced incoming asset: no margin is published, and
  declining is neither preferred nor dispreferred (``preferred is None``).
* forced drop    recv 6000 / send 5000 with a forced 900 release: net +100,
  inside 250 -> declining; the same trade with no cut nets +1000 -> trade.
* consolidation  asset-only, send 2500+2000 / recv 5500:
  U_send = 2500 + 0.78*2000 = 4060, gap +1440, half-width max(250, 192.5)
  = 250 -> trade clears by 1190.
* relative band  asset-only, recv 9000 / send 8700: gap +300, half-width
  max(250, 315) = 315 -> 15 short of clearing: declining.
* hair inside    recv 6000 / send 5000 with a 750.04 forced-release charge:
  net 249.96 against a 250 half-width is INSIDE the band (fair), although the
  clearance rounds to 0.0 at one decimal; ``insideBand`` says so.
* strategy       the War Room ``too-close-strategy`` scenario: the roster gain
  (+1.23 ppg against a 1.0 band) is outside its band, and a LONG_TERM strategy
  does not count a modest roster gain as enough: ``strategy_declines``, never
  ``near_tie``.
"""

from __future__ import annotations

import copy

import pytest

from src.trade import trade_decision
from src.trade.analyze_trade import analyze_trade
from tests.trade.test_trade_decision import _capacity, _sim

Q = 0.78


def U(values):
    """Independent package-utility oracle (geom_q078_v1)."""
    return sum(Q**i * v for i, v in enumerate(sorted(values, reverse=True)))


def half_width(send, recv):
    """Independent fairness neutral-band half-width (fairness_bands_v2)."""
    return max(250.0, 0.035 * max(U(send), U(recv)))


def _sq(sim, **kw):
    out = analyze_trade(sim, **kw)
    return out["decision"], out["statusQuo"]


def _cut_capacity(release):
    return _capacity(
        sizeAfter=59,
        requiresDrops=True,
        overLimitAfter=1,
        forcedDropReleaseCost=release,
        forcedDrops=[{"name": "Bench Guy", "value": release}],
    )


# ── Hand-worked cases ──────────────────────────────────────────────────────


def test_clearly_good_trade_beats_the_status_quo():
    d, sq = _sq(_sim([7000], [5000], ppg=3.0))
    assert d["headline"] == "YES"
    assert sq["state"] == "trade_beats_status_quo"
    assert sq["preferred"] is False and sq["preferredOption"] == "TRADE"
    assert sq["actionSupported"] is True
    assert sq["reason"] == "clears_decision_thresholds"
    m = sq["margin"]["objectiveValue"]
    assert m["value"] == 2000 and m["neutralBandHalfWidth"] == half_width([5000], [7000]) == 250
    assert m["tradeClearance"] == 1750 and m["statusQuoClearance"] == -2250
    r = sq["margin"]["rosterBenefit"]
    assert r["value"] == 3.0 and r["neutralBandHalfWidth"] == 1.0
    assert r["tradeClearance"] == 2.0 and r["statusQuoClearance"] == -4.0
    assert sq["baseline"] == {
        "objectiveValue": 0,
        "rosterBenefitPpg": 0,
        "forcedReleaseCost": 0,
        "definition": sq["baseline"]["definition"],
    }


def test_clearly_bad_trade_prefers_declining():
    d, sq = _sq(_sim([5000], [7000], ppg=-3.0))
    assert d["headline"] == "NO"
    assert sq["preferred"] is True and sq["preferredOption"] == "NO_TRANSACTION"
    assert sq["actionSupported"] is False
    assert sq["reason"] == "decision_rule_prefers_status_quo"
    assert sq["margin"]["objectiveValue"]["statusQuoClearance"] == 1750
    assert sq["margin"]["rosterBenefit"]["statusQuoClearance"] == 2.0


def test_near_zero_gap_prefers_declining_never_acting():
    d, sq = _sq(_sim([5000], [5050], ppg=0.2))
    assert d["headline"] == "NO_TOO_CLOSE"
    assert sq["state"] == "status_quo_preferred" and sq["reason"] == "near_tie"
    assert sq["preferred"] is True and sq["actionSupported"] is False
    m = sq["margin"]["objectiveValue"]
    # -50 against a 250 half-width: 300 short of favouring the trade, 200 short
    # of favouring declining -- inside the band on both sides.
    assert m["value"] == -50 and m["tradeClearance"] == -300 and m["statusQuoClearance"] == -200
    r = sq["margin"]["rosterBenefit"]
    assert r["tradeClearance"] == pytest.approx(-0.8) and r["statusQuoClearance"] == -1.2


def test_insufficient_evidence_states_no_preference_and_no_margin():
    d, sq = _sq(_sim([6000, 0], [5000], ppg=1.5))
    assert d["headline"] == "NOT_ENOUGH_EVIDENCE"
    assert sq["state"] == "insufficient_evidence" and sq["reason"] == "missing_evidence"
    assert sq["preferred"] is None and sq["preferredOption"] is None
    assert sq["actionSupported"] is False
    assert sq["evidence"]["missingEvidence"] == ["unpriced_assets"]
    assert sq["margin"]["objectiveValue"] is None and sq["margin"]["rosterBenefit"] is None
    assert sq["evidence"]["objectiveValue"] == {"evaluated": False, "reason": "evidenceGate"}


def test_forced_drop_heavy_trade_flips_to_declining():
    _, plain = _sq(_sim([6000], [5000], ppg=0.0))
    d, cut = _sq(_sim([6000], [5000], ppg=0.0, capacity=_cut_capacity(900)))
    assert plain["preferred"] is False  # +1000 clears 250 by 750
    assert plain["margin"]["objectiveValue"]["tradeClearance"] == 750
    assert d["headline"] == "NO_TOO_CLOSE" and cut["preferred"] is True
    fr = cut["evidence"]["forcedRelease"]
    assert fr["state"] == "cut_required"
    assert fr["chargedToTrade"] == 900 and fr["chargedToStatusQuo"] == 0
    assert fr["forcedDrops"] == ["Bench Guy"]
    m = cut["margin"]["objectiveValue"]
    assert m["value"] == 1000 - 900 and m["tradeClearance"] == -150


def test_consolidation_uses_the_package_model_gap():
    send, recv = [2500, 2000], [5500]
    d, sq = _sq(_sim(recv, send, team=False))
    gap = U(recv) - U(send)
    assert gap == pytest.approx(1440)
    assert d["headline"] == "YES" and sq["preferred"] is False
    m = sq["margin"]["objectiveValue"]
    assert m["value"] == pytest.approx(gap, abs=0.5)
    assert m["neutralBandHalfWidth"] == half_width(send, recv) == 250
    assert m["tradeClearance"] == pytest.approx(gap - 250, abs=0.5)
    # Asset-only: the roster lens and posture are excluded by mode, not zero.
    assert sq["margin"]["rosterBenefit"] is None
    assert sq["evidence"]["rosterBenefit"]["state"] == "excluded_by_mode"
    assert sq["evidence"]["posture"] == {"state": "excluded_by_mode"}
    assert sq["evidence"]["forcedRelease"]["state"] == "excluded_by_mode"


def test_relative_band_keeps_a_small_gain_on_a_large_package_as_declining():
    send, recv = [8700], [9000]
    d, sq = _sq(_sim(recv, send, team=False))
    assert half_width(send, recv) == pytest.approx(315)
    assert d["headline"] == "NO_TOO_CLOSE" and sq["preferred"] is True
    m = sq["margin"]["objectiveValue"]
    assert m["value"] == 300 and m["neutralBandHalfWidth"] == 315
    assert m["tradeClearance"] == -15


def test_execution_gate_leaves_the_status_quo_as_the_only_option():
    d, sq = _sq(_sim([7000], [5000], ppg=3.0, capacity=_capacity(ladderExhausted=True)))
    assert d["headline"] == "NO" and d["deciding"] == "executionGate"
    assert sq["preferred"] is True and sq["reason"] == "trade_not_executable"
    assert sq["margin"]["objectiveValue"] is None
    assert sq["evidence"]["objectiveValue"] == {"evaluated": False, "reason": "executionGate"}


def test_posture_fit_is_reported_as_context_never_a_vote():
    _, sq = _sq(_sim([7000], [5000], ppg=3.0, posture="REBUILD"))
    p = sq["evidence"]["posture"]
    assert p["state"] == "evaluated" and p["postureLabel"] == "REBUILD"
    assert p["strategyUsed"] == "LONG_TERM" and p["role"] == "selects_strategy_never_votes"


# ── Invariants ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("team", [True, False])
@pytest.mark.parametrize("goal", [None, "WIN_NOW", "BALANCED", "LONG_TERM"])
@pytest.mark.parametrize("ppg", [-4.0, -1.5, 0.0, 1.5, 4.0])
def test_declining_is_preferred_unless_the_headline_is_yes(team, goal, ppg):
    for incoming in range(3000, 9001, 250):
        for release in (None, 600):
            cap = _cut_capacity(release) if (team and release) else None
            d, sq = _sq(
                _sim([incoming], [6000], ppg=ppg, team=team, capacity=cap),
                team_goal=goal,
                counterfactuals=False,  # never changes the decision; keeps the sweep fast
            )
            yes = d["headline"] == "YES"
            assert sq["state"] in trade_decision.STATUS_QUO_STATES
            assert (sq["preferred"] is False) == yes
            assert sq["actionSupported"] is yes
            if not yes:
                assert sq["preferred"] in (True, None)
            if d["headline"] == "NOT_ENOUGH_EVIDENCE":
                assert sq["preferred"] is None
            m = sq["margin"]["objectiveValue"]
            if m is not None:
                # The margin agrees with the component's own classification.
                direction = d["components"]["objectiveValue"]["direction"]
                assert m["insideBand"] is (direction == "neutral")
                assert (m["tradeClearance"] >= 0) == (direction == "favors")
                assert (m["statusQuoClearance"] >= 0) == (direction == "opposes")
            r = sq["margin"]["rosterBenefit"]
            if r is not None:
                assert r["insideBand"] is (r["direction"] == "neutral")
            if sq["reason"] == "near_tie":
                # A near tie means every evaluated component is inside its band.
                assert all(x["insideBand"] for x in (m, r) if x is not None)
            if d["deciding"] == "strategy" and d["headline"] != "YES":
                assert sq["reason"] == "strategy_declines" and sq["preferred"] is True
            assert sq["margin"]["crossComponent"] is None


def test_status_quo_never_changes_the_decision_or_its_coverage():
    sim = _sim([6000], [5000], ppg=1.5)
    out = analyze_trade(copy.deepcopy(sim))
    assert "statusQuo" not in out["decision"]
    cov = {r["dimension"]: r for r in out["decision"]["coverage"]}
    # The coverage record is unchanged: the best ALTERNATIVE is still not wired.
    assert cov["opportunity_cost"]["state"] == "unavailable"
    assert cov["opportunity_cost"]["exclusionReason"] == "not_wired"
    oc = out["statusQuo"]["opportunityCost"]
    assert oc["state"] == "unavailable"
    assert oc["reason"] == trade_decision.OPPORTUNITY_COST_UNAVAILABLE_REASON
    assert oc["coverageExclusionReason"] == "not_wired"
    assert oc["comparedAlternatives"] == ["NO_TRANSACTION"]


class _Lens:
    """An unavailable lens: what ``status_quo`` sees when nothing was measured."""

    available = False
    detail: dict = {}
    unavailable_reason = "not_computed"


def test_status_quo_is_pure_and_does_not_mutate_the_decision():
    decision = analyze_trade(_sim([6000, 0], [5000], ppg=1.5))["decision"]
    before = copy.deepcopy(decision)
    first = trade_decision.status_quo(
        decision, market=_Lens(), feasibility=_Lens(), posture=_Lens(), team_context=True
    )
    second = trade_decision.status_quo(
        decision, market=_Lens(), feasibility=_Lens(), posture=_Lens(), team_context=True
    )
    assert decision == before
    assert first == second


@pytest.mark.parametrize(
    "decision",
    [
        {},
        {"headline": "MAYBE"},
        {"headline": "YES", "deciding": "executionGate"},
        {"headline": "YES", "deciding": "evidenceGate"},
        {"headline": "NOT_ENOUGH_EVIDENCE", "deciding": "objectiveValue"},
        {"headline": "NO"},
        {"headline": "NO", "deciding": "bogus"},
        {"headline": "YES"},
        {"headline": "NO_TOO_CLOSE"},
        {"headline": "NO_TOO_CLOSE", "deciding": "executionGate"},
    ],
)
def test_a_malformed_decision_fails_closed(decision):
    sq = trade_decision.status_quo(
        decision, market=_Lens(), feasibility=_Lens(), posture=_Lens(), team_context=False
    )
    assert sq["state"] == "insufficient_evidence" and sq["reason"] == "decision_unrecognized"
    assert sq["preferred"] is None and sq["actionSupported"] is False
    assert sq["margin"]["objectiveValue"] is None


def test_a_net_a_hair_inside_the_band_is_inside_never_a_signed_zero():
    # Direct: 249.96 against 250 rounds to a clearance of 0.0 (never -0.0) and
    # is reported inside the band by the component's own classification.
    m = trade_decision._clearance(
        249.96,
        250.0,
        unit="canonical value points (adjusted package)",
        direction="neutral",
        digits=1,
    )
    assert m["insideBand"] is True
    assert m["tradeClearance"] == 0.0 and str(m["tradeClearance"]) == "0.0"
    assert m["statusQuoClearance"] == -500.0
    # Through the decision: a 750.04 forced-release charge on a +1000 gap.
    cap = _capacity(
        sizeAfter=59,
        requiresDrops=True,
        overLimitAfter=1,
        forcedDropReleaseCost=750.04,
        forcedDrops=[{"name": "Bench Guy", "value": 750.04}],
        forcedDropCharge=750.04,
        forcedDropChargeBasis={"state": "exact"},
    )
    d, sq = _sq(_sim([6000], [5000], ppg=0.0, capacity=cap))
    assert d["components"]["objectiveValue"]["band"]["level"] == "fair"
    assert d["headline"] == "NO_TOO_CLOSE" and sq["reason"] == "near_tie"
    m = sq["margin"]["objectiveValue"]
    assert m["value"] == 250.0 and m["neutralBandHalfWidth"] == 250.0
    assert m["insideBand"] is True and m["direction"] == "neutral"
    assert str(m["tradeClearance"]) == "0.0"


def test_strategy_decided_too_close_is_strategy_declines_not_a_near_tie():
    from tests.trade import war_room_ui_payloads as wr

    body = wr.build("too-close-strategy")
    d, sq = body["analysis"]["decision"], body["analysis"]["statusQuo"]
    assert d["headline"] == "NO_TOO_CLOSE" and d["deciding"] == "strategy"
    assert d["strategy"]["used"] == "LONG_TERM"
    assert sq["reason"] == "strategy_declines" and sq["preferred"] is True
    assert sq["actionSupported"] is False
    r = sq["margin"]["rosterBenefit"]
    # The roster gain is OUTSIDE its band; the strategy, not a tie, declines it.
    assert r["insideBand"] is False and r["tradeClearance"] > 0
    assert sq["margin"]["objectiveValue"]["insideBand"] is True
    assert "near" not in sq["text"] and "strategy" in sq["text"]


def test_strategy_decided_no_is_strategy_declines():
    # Value up modestly (+400 / 5400 = 7.4%, the slight band), lineup down
    # modestly (-1.5 ppg against a 1.0 band), WIN_NOW: _rule says NO by strategy.
    d, sq = _sq(_sim([5400], [5000], ppg=-1.5), team_goal="WIN_NOW")
    assert d["headline"] == "NO" and d["deciding"] == "strategy"
    assert sq["reason"] == "strategy_declines" and sq["preferred"] is True
    assert sq["margin"]["objectiveValue"]["insideBand"] is False
