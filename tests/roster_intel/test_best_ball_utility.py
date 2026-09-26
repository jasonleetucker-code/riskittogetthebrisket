"""#1173 roster-conditional best-ball utility — discriminating cases.

Each case is built so that naive value arithmetic (sum the projections in,
subtract the projections out) gives the WRONG answer, and only a per-scenario
global lineup solve gives the right one.  Synthetic rosters; means in points.
"""

from __future__ import annotations

import pytest

from src.roster_intel.best_ball_utility import UtilityPlayer, evaluate_trade_utility

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
SF_SLOTS = ["QB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]
IDP_SLOTS = ["QB", "RB", "WR", "TE", "DL", "LB", "IDP_FLEX"]
DRAWS = 300


def P(pid, pos, ppg, *fantasy):
    return UtilityPlayer(pid, pid, pos, ppg, tuple(fantasy))


BASE = [
    P("qb1", "QB", 21.0),
    P("rb1", "RB", 16.0),
    P("rb2", "RB", 13.0),
    P("te1", "TE", 10.0),
]


def swap(roster, out_ids, incoming):
    return [p for p in roster if p.player_id not in out_ids] + list(incoming)


def evaluate(before, after, slots=SLOTS, **kw):
    ids_before = {p.player_id for p in before}
    ids_after = {p.player_id for p in after}
    roles = {pid: "outgoing" for pid in ids_before - ids_after}
    roles.update({pid: "incoming" for pid in ids_after - ids_before})
    return evaluate_trade_utility(
        before=before, after=after, slots=slots, roles=roles, draws=DRAWS, **kw
    )


def row(result, pid):
    return next(r for r in result["players"] if r["playerId"] == pid)


def test_star_consolidation_beats_raw_arithmetic():
    wrs = [P("wr1", "WR", 18.0), P("wr2", "WR", 16.0), P("wr3", "WR", 12.0), P("wr4", "WR", 11.0)]
    before = BASE + wrs
    after = swap(before, {"wr3", "wr4"}, [P("star", "WR", 20.0)])
    r = evaluate(before, after)
    # Naive: 20 in vs 12 + 11 out = -3 ppg.  The legal lineup disagrees.
    assert r["impact"]["ppg"] > 2 * r["impact"]["standardError"]
    assert row(r, "star")["lineupEntryPctAfter"] > 90
    # The two outgoing WRs were real but part-time best-ball contributors:
    # usable production well under their raw projections.
    assert row(r, "wr4")["usablePpgBefore"] < 11.0
    assert row(r, "wr4")["lineupEntryPctBefore"] < 75
    assert r["shape"]["label"] == "consolidation"
    assert r["after"]["redundantPpg"] < r["before"]["redundantPpg"]


def test_redundant_depth_is_not_usable_value():
    wrs = [P("wr1", "WR", 20.0), P("wr2", "WR", 18.0), P("wr3", "WR", 17.0)]
    before = BASE + wrs
    after = before + [P("depth", "WR", 10.0)]
    r = evaluate(before, after)
    # Naive: +10 ppg.  In best ball a bench WR scores only in the weeks he
    # outscores a starter, so most of his projection is redundant here.
    raw_added = 10.0
    assert r["impact"]["ppg"] < 0.6 * raw_added
    assert row(r, "depth")["lineupEntryPctAfter"] < 70
    assert r["after"]["redundantPpg"] > r["before"]["redundantPpg"] + 3


def test_flex_interaction_is_solved_globally():
    wrs = [P("wr1", "WR", 18.0), P("wr2", "WR", 16.0), P("wr3", "WR", 12.0)]
    before = BASE + wrs
    after = before + [P("rb3", "RB", 17.0)]
    r = evaluate(before, after)
    # Before, the third WR held the FLEX every week.  The new RB competes for
    # it through the shared FLEX, so a WR loses lineup share to an RB — which
    # per-position depth arithmetic (RBs vs RBs, WRs vs WRs) cannot see.
    displaced = row(r, "wr3")
    assert displaced["role"] == "displaced"
    assert displaced["lineupEntryPctBefore"] == 100.0
    assert displaced["lineupEntryPctAfter"] < 90.0
    per_position_view = 0.0  # "no RB slot is empty, so no RB is added" view
    assert r["impact"]["ppg"] > per_position_view + 2.0


def test_superflex_qb_depth_flows_through_the_sf_slot():
    roster = [
        P("qb1", "QB", 22.0),
        P("qb2", "QB", 16.0),
        P("rb1", "RB", 14.0),
        P("wr1", "WR", 15.0),
        P("wr2", "WR", 13.0),
        P("wr3", "WR", 8.0),
        P("te1", "TE", 9.0),
    ]
    after = swap(roster, {"qb2"}, [P("wr4", "WR", 11.0)])
    sf = evaluate(roster, after, slots=SF_SLOTS)
    one_qb = evaluate(roster, after, slots=[s for s in SF_SLOTS if s != "SUPER_FLEX"])
    # QB2 is a starter only because SUPER_FLEX exists: trading him for a
    # better-projected-than-bench WR hurts in SF and helps without it.
    assert sf["impact"]["ppg"] < -2.0
    assert row(sf, "qb2")["lineupEntryPctBefore"] > 90
    assert one_qb["impact"]["ppg"] > sf["impact"]["ppg"] + 2.0


def test_idp_flex_eligibility_is_solved_globally():
    roster = [
        P("qb1", "QB", 20.0),
        P("rb1", "RB", 14.0),
        P("wr1", "WR", 14.0),
        P("te1", "TE", 8.0),
        P("dl1", "DL", 9.0),
        P("lb1", "LB", 11.0),
    ]
    # An edge rusher Sleeper lists as DL/LB: he can fill LB or IDP_FLEX.
    after = roster + [P("edge", "DL", 12.0, "DL", "LB")]
    r = evaluate(roster, after, slots=IDP_SLOTS)
    assert row(r, "edge")["lineupEntryPctAfter"] > 80
    # Before: IDP_FLEX empty (no third IDP) — after, it is filled.
    assert r["impact"]["ppg"] > 8.0


def test_literal_zero_is_real_and_missing_is_partial():
    wrs = [P("wr1", "WR", 15.0)]
    before = BASE + wrs  # one WR slot and the FLEX are empty
    zero = evaluate(before, before + [P("zero", "WR", 0.0)])
    zrow = row(zero, "zero")
    assert zrow["projectedPpg"] == 0.0
    assert zero["coverage"]["state"] == "full"
    assert zero["impact"]["ppg"] == pytest.approx(0.0, abs=1e-9)

    missing = evaluate(before, before + [P("ghost", "WR", None)])
    mrow = row(missing, "ghost")
    assert mrow["projectedPpg"] is None
    assert mrow["lineupEntryPctAfter"] is None  # never seated, never 0%
    assert missing["coverage"]["state"] == "partial"
    assert missing["coverage"]["tradedUnprojectedPlayerIds"] == ["ghost"]
    assert "ghost" in missing["after"]["unprojectedPlayerIds"]


def test_identical_rosters_pair_exactly():
    roster = BASE + [P("wr1", "WR", 15.0), P("wr2", "WR", 12.0)]
    r = evaluate_trade_utility(before=roster, after=list(roster), slots=SLOTS, roles={}, draws=50)
    assert r["impact"]["ppg"] == 0.0
    assert r["impact"]["standardError"] == 0.0


def test_deterministic_across_calls():
    before = BASE + [P("wr1", "WR", 15.0), P("wr2", "WR", 12.0)]
    after = swap(before, {"wr2"}, [P("wr9", "WR", 13.0)])
    a = evaluate(before, after)
    b = evaluate(before, after)
    assert a["impact"] == b["impact"]


def test_cleanup_is_reported_separately_from_the_raw_landing():
    before = BASE + [P("wr1", "WR", 15.0), P("wr2", "WR", 12.0), P("wr3", "WR", 9.0)]
    landed = before + [P("wr9", "WR", 14.0)]
    legal = [p for p in landed if p.player_id != "rb2"]  # cleanup cut an RB starter
    r = evaluate_trade_utility(
        before=before,
        after=legal,
        after_before_cleanup=landed,
        slots=SLOTS,
        roles={"wr9": "incoming", "rb2": "forcedDrop"},
        draws=DRAWS,
    )
    assert r["impact"]["ppgBeforeCleanup"] > r["impact"]["ppg"]
    assert row(r, "rb2")["role"] == "forcedDrop"


def test_depth_measure_sees_lost_insurance():
    before = BASE + [
        P("wr1", "WR", 16.0),
        P("wr2", "WR", 15.0),
        P("wr3", "WR", 12.0),
        P("rb3", "RB", 11.0),
    ]
    # Trade the bench RB for a slightly better WR: little healthy-lineup
    # change, but an RB absence now falls further.
    after = swap(before, {"rb3"}, [P("wr9", "WR", 12.5)])
    r = evaluate(before, after)
    assert r["depth"]["meanLossDeltaPpg"] > 0
    assert r["depth"]["method"] == "single_starter_absence"


def test_no_slots_is_unavailable_not_zero():
    r = evaluate_trade_utility(before=BASE, after=BASE, slots=[], roles={})
    assert r["available"] is False
    assert r["unavailableReason"] == "starter_slots_unresolved"
