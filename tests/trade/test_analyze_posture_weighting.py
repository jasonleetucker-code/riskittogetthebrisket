"""#840 / #792 — Competitive Posture WEIGHS, it never votes.

``src.trade.analyze_trade`` lets a team's posture decide which of two
DISAGREEING primary lenses carries the call (PUSH → the current-season roster
lens; RETOOL / REBUILD → the long-horizon market lens; HOLD or LOW confidence
→ neither).  What is pinned:

* posture never moves a verdict when the lenses agree, never creates a
  direction from two neutral lenses, and never lands beyond a LEAN (not a
  veto) — Wave B double-count rules 1 and 3;
* the addendum's decision cases (1, 2, 7, 8, 9, 10) through the real packet;
* ``contextEffect`` names what changed because of team context versus raw
  value, one dimension at a time;
* Asset-Only excludes posture and the other team's capacity entirely;
* the forced-drop value has exactly one carrier (double-count rule 2).
"""

from __future__ import annotations

import itertools

import pytest

from src.trade.analyze_trade import DimensionResult, _recommend, analyze_trade
from tests.trade.test_analyze_trade import _capacity, _sim, _utility


def _posture(label, confidence="HIGH"):
    return {
        "available": True,
        "selected": {"teamName": "Us", "posture": label, "confidence": confidence},
        "counterparty": None,
        "timing": {"phase": "regular_season"},
        "countedAsVote": False,
    }


def _with_posture(sim, label, confidence="HIGH"):
    sim["posture"] = _posture(label, confidence)
    return sim


def _lens(name, direction, magnitude="lean"):
    return DimensionResult(
        name=name, available=True, direction=direction, detail={"magnitude": magnitude}
    )


_OFF = DimensionResult(name="feasibility", available=False, unavailable_reason="x")


def _posture_lens(label, confidence="HIGH"):
    return DimensionResult(
        name="posture",
        available=True,
        votes=False,
        detail={"selected": {"posture": label, "confidence": confidence}},
    )


# ── Invariants ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("label", ["PUSH", "HOLD", "RETOOL", "REBUILD"])
@pytest.mark.parametrize("conf", ["HIGH", "MEDIUM", "LOW"])
def test_posture_only_ever_breaks_a_market_roster_split(label, conf):
    dirs = ["favors", "opposes", "neutral"]
    for m, r in itertools.product(dirs, dirs):
        market, roster = _lens("equity", m), _lens("rosterUtility", r)
        without = _recommend(market, roster, _OFF)
        with_p = _recommend(market, roster, _OFF, _posture_lens(label, conf))
        if {m, r} != {"favors", "opposes"}:
            assert with_p[0] == without[0], (label, conf, m, r)
        else:
            assert with_p[0] in ("TOO_CLOSE", "LEAN_MAKE", "LEAN_PASS")  # never a veto


def test_hold_and_low_confidence_leave_the_split_too_close():
    split = (_lens("equity", "favors"), _lens("rosterUtility", "opposes"), _OFF)
    assert _recommend(*split, _posture_lens("HOLD"))[0] == "TOO_CLOSE"
    assert _recommend(*split, _posture_lens("PUSH", "LOW"))[0] == "TOO_CLOSE"


def test_posture_is_reported_but_never_a_vote():
    a = analyze_trade(_with_posture(_sim([5000], [3000], utility=_utility(2.0)), "PUSH"))
    lens = a["lenses"]["posture"]
    assert lens["available"] is True
    assert lens["votes"] is False
    assert lens["detail"]["countedAsVote"] is False


# ── The addendum's decision cases ───────────────────────────────────────


def test_case1_contender_pays_a_first_for_a_large_lineup_gain():
    """PUSH team: market says it overpays, the legal lineup gains a lot."""
    sim = _with_posture(_sim([3000], [5600], utility=_utility(6.0)), "PUSH")
    a = analyze_trade(sim)
    assert a["lenses"]["market"]["direction"] == "opposes"
    assert a["lenses"]["roster"]["direction"] == "favors"
    assert a["recommendation"] == "LEAN_MAKE"
    assert "posture_weighting:PUSH->rosterUtility" in a["basis"]
    assert a["contextEffect"]["assetOnlyRecommendation"] in ("LEAN_PASS", "PASS")
    assert a["contextEffect"]["changed"] is True


def test_case2_contender_pays_the_same_price_for_a_tiny_gain():
    """The lineup gain sits inside the neutral band: no split for posture to
    break, so the market's objection stands."""
    sim = _with_posture(_sim([3000], [5600], utility=_utility(0.2, se=0.05)), "PUSH")
    a = analyze_trade(sim)
    assert a["lenses"]["roster"]["direction"] == "neutral"
    assert a["recommendation"] in ("LEAN_PASS", "PASS")
    assert "posture_weighting" not in a["basis"]


def test_case7_young_rebuilder_adding_an_older_producer():
    """REBUILD: lineup gain now, long-horizon value lost → the market leads."""
    sim = _with_posture(_sim([3000], [4200], utility=_utility(4.0)), "REBUILD")
    a = analyze_trade(sim)
    assert a["recommendation"] == "LEAN_PASS"
    assert "posture_weighting:REBUILD->equity" in a["basis"]


def test_case8_old_contender_acquiring_younger_value():
    """PUSH: value up, this season's lineup down → the roster lens leads."""
    sim = _with_posture(_sim([4200], [3000], utility=_utility(-4.0)), "PUSH")
    a = analyze_trade(sim)
    assert a["recommendation"] == "LEAN_PASS"
    assert a["contextEffect"]["changedBy"][0]["dimension"] == "rosterUtility"


def test_case9_wins_raw_value_but_opens_a_severe_hole():
    sim = _sim([4200], [3000], utility=_utility(-6.0))
    hold = analyze_trade(_with_posture(dict(sim), "HOLD"))
    assert hold["recommendation"] == "TOO_CLOSE"
    push = analyze_trade(_with_posture(dict(sim), "PUSH"))
    assert push["recommendation"] == "LEAN_PASS"


def test_case10_loses_small_value_but_materially_improves_the_lineup():
    sim = _with_posture(_sim([3000], [3700], utility=_utility(5.0)), "PUSH")
    a = analyze_trade(sim)
    assert a["recommendation"] == "LEAN_MAKE"
    assert any("Team direction PUSH" in r for r in a["reasonsFor"])


def test_title_odds_are_never_claimed():
    """Cases 1/2/10 talk about title odds; the trade counterfactual is not
    wired, so the packet names it unavailable instead of inventing it."""
    a = analyze_trade(_with_posture(_sim([3000], [5600], utility=_utility(6.0)), "PUSH"))
    names = {d["dimension"] for d in a["unavailableDimensions"]}
    assert {"currentSeasonEquity", "ownPickSlotCounterfactual"} <= names


# ── Context effect / Asset-Only ─────────────────────────────────────────


def test_context_effect_names_each_dimension_that_moved_the_verdict():
    sim = _sim(
        [5000],
        [3000],
        utility=_utility(2.0),
        capacity=_capacity(before=58, after=59, drops=["Cut"], release=2500, requires=True),
    )
    a = analyze_trade(sim)
    effect = a["contextEffect"]
    assert effect["assetOnlyRecommendation"] in ("MAKE", "LEAN_MAKE")
    assert [c["dimension"] for c in effect["changedBy"]] == ["feasibility"] or effect["changed"]


def test_asset_only_excludes_posture_and_the_other_teams_capacity():
    sim = _with_posture(_sim([3000], [5600], utility=_utility(6.0), context=False), "PUSH")
    sim["counterparty"] = {"available": True, "rosterCapacity": _capacity(), "team": {}}
    a = analyze_trade(sim)
    assert a["lenses"]["posture"]["unavailableReason"] == "asset_only_mode"
    assert a["lenses"]["counterpartyFeasibility"]["unavailableReason"] == "asset_only_mode"
    assert a["contextEffect"]["changed"] is False
    assert "posture_weighting" not in a["basis"]


# ── Double-count rules ───────────────────────────────────────────────────


def test_rule2_forced_drop_value_has_one_carrier():
    """The market lens prices the PACKAGE only; the released value is the
    feasibility lens's alone; the weekly cost is inside the roster lens."""
    base = _sim([5000], [3000], utility=_utility(2.0))
    cut = _sim(
        [5000],
        [3000],
        utility=_utility(2.0),
        capacity=_capacity(before=58, after=59, drops=["Cut"], release=2500, requires=True),
    )
    a, b = analyze_trade(base), analyze_trade(cut)
    assert a["lenses"]["market"] == b["lenses"]["market"]  # never net of the cut
    assert b["lenses"]["feasibility"]["direction"] == "opposes"


def test_rule1_posture_cannot_reward_consolidation_twice():
    """A 2-for-1 the market already credits (VA premium) and the roster lens
    already credits (lineup gain) is MAKE without posture; posture adds
    nothing on top — there is no split for it to weigh."""
    sim = _sim([6000], [3000, 2500], utility=_utility(4.0))
    plain = analyze_trade(sim)
    pushed = analyze_trade(_with_posture(_sim([6000], [3000, 2500], utility=_utility(4.0)), "PUSH"))
    assert plain["recommendation"] == pushed["recommendation"]
    assert "posture_weighting" not in pushed["basis"]


def test_counterparty_cut_is_context_not_our_cost():
    sim = _sim([5000], [3000], utility=_utility(2.0))
    sim["counterparty"] = {
        "available": True,
        "team": {"name": "Them"},
        "rosterCapacity": _capacity(before=58, after=59, drops=["X"], release=4000, requires=True),
    }
    with_cp = analyze_trade(sim)
    without = analyze_trade(_sim([5000], [3000], utility=_utility(2.0)))
    assert with_cp["recommendation"] == without["recommendation"]
    assert with_cp["lenses"]["counterpartyFeasibility"]["votes"] is False
    assert any("Them would have to cut" in r for r in with_cp["reasonsAgainst"])
