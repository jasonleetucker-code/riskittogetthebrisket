"""Roster capacity and the legal post-trade roster (roster half of C3-CAP-01).

The binding spec (``docs/trade/ROSTER_CAPACITY_FORCED_DROP_TRADE_ANALYSIS_ADDENDUM_2026-08-14.md``,
#843) lists eleven validation fixtures.  Nine of them are roster mechanics and
are here, named for the spec's own wording.  Two — Team Context OFF excluding
#843 from the verdict, and generated-trade ranking changing — are trade-lane
behaviour and belong with whoever owns the verdict; this module deliberately
has none.
"""

from __future__ import annotations

import ast
import pathlib

from src.roster_intel.capacity import (
    CLEANUP_AMBIGUITY_TOLERANCE,
    plan_roster_capacity,
)
from src.ros.lineup import RosterPlayer

REPO = pathlib.Path(__file__).resolve().parents[2]

#: 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX.
_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"]
_WAIVERS = {"QB": 100.0, "RB": 100.0, "WR": 100.0, "TE": 100.0}


def P(pid, pos, val):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=val)


def _roster(extra=0):
    """Exactly 10 players — enough to fill all 8 slots with 2 spare."""
    base = [
        P("QB1", "QB", 900),
        P("RB1", "RB", 800),
        P("RB2", "RB", 700),
        P("WR1", "WR", 850),
        P("WR2", "WR", 750),
        P("WR3", "WR", 650),
        P("TE1", "TE", 600),
        P("FLEXER", "RB", 500),
        P("BENCH1", "WR", 300),
        P("BENCH2", "WR", 250),
    ]
    return base + [P(f"X{i}", "WR", 200 - i) for i in range(extra)]


def _plan(**kw):
    kw.setdefault("waiver_values", _WAIVERS)
    return plan_roster_capacity(_roster(kw.pop("extra", 0)), _SLOTS, **kw)


# ══ The spec's own worked fixtures ═════════════════════════════════


def test_fixture_1_full_roster_one_for_one_needs_no_cut():
    out = _plan(active_limit=10, incoming=[P("NEW", "WR", 900)], outgoing_ids=["BENCH2"])
    assert out.capacity.net_player_change == 0
    assert out.capacity.over_limit_after_package == 0
    assert out.capacity.fits_cleanly is True
    assert out.cleanup.releases == ()
    assert out.capacity.final_count == 10


def test_fixture_2_full_roster_one_for_two_needs_one_cleanup_move():
    out = _plan(
        active_limit=10,
        incoming=[P("A", "WR", 900), P("B", "WR", 880)],
        outgoing_ids=["BENCH2"],
    )
    assert out.capacity.post_package_count == 11
    assert out.capacity.cleanup_moves_required == 1
    assert len(out.cleanup.releases) == 1
    assert out.cleanup.feasible is True
    assert out.capacity.final_count == 10


def test_fixture_3_one_open_spot_absorbs_a_quantity_package_cleanly():
    """ "If the team has enough open space to absorb the incoming players,
    state that the trade fits cleanly and impose no forced-drop cost." """
    out = _plan(
        active_limit=11,
        incoming=[P("A", "WR", 900), P("B", "WR", 880)],
        outgoing_ids=["BENCH2"],
    )
    assert out.capacity.open_spots_before == 1
    assert out.capacity.fits_cleanly is True
    assert out.cleanup.releases == ()
    assert out.cleanup.total_effective_cut_cost is None  # no cost, not a zero cost


def test_fixture_4_one_over_then_two_for_one_returns_to_legal():
    out = _plan(
        extra=1, active_limit=10, incoming=[P("A", "WR", 900)], outgoing_ids=["BENCH1", "BENCH2"]
    )
    assert out.capacity.over_limit_before == 1
    assert out.capacity.over_limit_after_package == 0
    assert out.capacity.overage_transition == "resolved"
    assert out.cleanup.releases == ()


def test_fixture_5_three_over_then_two_for_one_improves_the_overage_to_two():
    out = _plan(
        extra=3, active_limit=10, incoming=[P("A", "WR", 900)], outgoing_ids=["BENCH1", "BENCH2"]
    )
    assert out.capacity.over_limit_before == 3
    assert out.capacity.over_limit_after_package == 2
    assert out.capacity.overage_transition == "improved"
    assert out.capacity.cleanup_moves_required == 2
    assert len(out.cleanup.releases) == 2


def test_fixture_6_one_over_then_one_for_two_worsens_the_overage_to_two():
    out = _plan(
        extra=1,
        active_limit=10,
        incoming=[P("A", "WR", 900), P("B", "WR", 880)],
        outgoing_ids=["BENCH2"],
    )
    assert out.capacity.over_limit_before == 1
    assert out.capacity.over_limit_after_package == 2
    assert out.capacity.overage_transition == "worsened"


def test_fixture_7_taxi_relief_is_unavailable_rather_than_assumed_either_way():
    """ "Taxi / IR capacity only where actual league rules and player
    eligibility permit those moves."  Neither can be established here —
    Sleeper's per-player taxi assignment is ingested nowhere — so the honest
    answer is that it is not modelled.  Assuming relief would understate
    required cuts; assuming none would overstate them for a league that has
    it."""
    out = _plan(active_limit=10, taxi_size=4, incoming=[P("A", "WR", 900)])
    assert out.capacity.taxi_size == 4
    assert out.capacity.taxi_relief_modelled is False
    assert "eligibility" in out.capacity.taxi_relief_reason
    # And the cut requirement is computed WITHOUT pretending the taxi absorbed
    # anyone.
    assert out.capacity.cleanup_moves_required == 1


def test_fixture_8_the_forced_cut_is_the_lowest_real_marginal_loss_not_the_lowest_raw_value():
    """THE fixture the spec calls out by name: *"do not model it solely as
    package delta − lowest raw player value"*.

    ``TE1`` is the cheapest rostered player here by a wide margin, but he is
    the only TE and the lineup needs one — so releasing him is illegal and the
    canonical ladder never offers him.  A raw-value sort picks him first."""
    thin = [
        P("QB1", "QB", 900),
        P("RB1", "RB", 800),
        P("RB2", "RB", 700),
        P("WR1", "WR", 850),
        P("WR2", "WR", 750),
        P("WR3", "WR", 650),
        P("TE1", "TE", 120),  # cheapest on the roster, and irreplaceable
        P("FLEXER", "RB", 500),
        P("BENCH1", "WR", 300),
    ]
    cheapest_raw = min(thin, key=lambda p: p.ros_value).player_id
    assert cheapest_raw == "TE1"

    out = plan_roster_capacity(
        thin, _SLOTS, incoming=[P("A", "WR", 900)], active_limit=9, waiver_values=_WAIVERS
    )
    released = {r["playerId"] for r in out.cleanup.releases}
    assert released == {"BENCH1"}
    assert "TE1" not in released


def test_fixture_8b_a_cheaper_player_is_kept_when_his_replacement_is_dearer():
    """The half of fixture 8 that the undroppable-TE case does NOT prove.

    Above, ``TE1`` never reaches the ladder at all, so re-sorting the ladder
    by raw value would still avoid him — a mutation that survived until this
    test existed.  The discrimination the spec actually demands is between two
    players who are BOTH legally droppable, where raw value and real marginal
    loss disagree:

    ================  ==========  ==============  =====
    player            raw value   waiver at pos   ECC
    ================  ==========  ==============  =====
    ``SPARE_WR``      300         100             200
    ``SPARE_TE``      400         500             0
    ================  ==========  ==============  =====

    Raw value says cut ``SPARE_WR`` (300 < 400).  Real marginal loss says cut
    ``SPARE_TE``, because a tight end that good is sitting on the wire and the
    wide receiver is not.  ``SPARE_TE`` is the right answer, and it is the
    dearer player.
    """
    roster = [
        P("QB1", "QB", 900),
        P("RB1", "RB", 800),
        P("RB2", "RB", 700),
        P("WR1", "WR", 850),
        P("WR2", "WR", 750),
        P("WR3", "WR", 650),
        P("TE1", "TE", 600),
        P("FLEXER", "RB", 500),
        P("SPARE_WR", "WR", 300),
        P("SPARE_TE", "TE", 400),
    ]
    waivers = {"QB": 100.0, "RB": 100.0, "WR": 100.0, "TE": 500.0}
    out = plan_roster_capacity(
        roster, _SLOTS, incoming=[P("A", "WR", 900)], active_limit=10, waiver_values=waivers
    )
    released = [r["playerId"] for r in out.cleanup.releases]
    assert released == ["SPARE_TE"]
    # The one it kept is the CHEAPER player — which a raw-value rule cannot do.
    assert min(roster, key=lambda p: p.ros_value).player_id == "SPARE_WR"
    chosen = out.cleanup.releases[0]
    assert chosen["effectiveCutCost"] == 0.0
    assert chosen["baseValue"] == 400.0


def test_fixture_9_picks_do_not_consume_an_active_roster_spot():
    """ "Draft picks normally do not consume an immediate active roster spot
    and must not be counted as current players merely because they are
    included in the trade." """
    with_picks = _plan(
        active_limit=10,
        incoming=[P("A", "WR", 900)],
        outgoing_ids=["BENCH2"],
        incoming_picks=3,
        outgoing_picks=1,
    )
    without = _plan(active_limit=10, incoming=[P("A", "WR", 900)], outgoing_ids=["BENCH2"])
    assert with_picks.capacity.post_package_count == without.capacity.post_package_count
    assert with_picks.capacity.cleanup_moves_required == without.capacity.cleanup_moves_required
    # Counted and reported, so the omission is visible rather than silent.
    assert with_picks.capacity.picks_excluded == 4


# ══ Missing is never zero ══════════════════════════════════════════


def test_an_unknown_roster_limit_degrades_rather_than_assuming_room():
    """ "Missing capacity data must remain degraded/unknown; do not silently
    assume zero open spots, zero overage, no forced drop."  A roster whose
    limit is unknown is not a roster with infinite room."""
    out = _plan(incoming=[P("A", "WR", 900)])
    c = out.capacity
    assert c.available is False
    assert c.unavailable_reason == "active_roster_limit_unknown"
    assert (c.active_limit, c.open_spots_before, c.over_limit_before) == (None, None, None)
    assert (c.cleanup_moves_required, c.final_count, c.fits_cleanly) == (None, None, None)
    assert c.overage_transition == "unknown"
    # …but the counts that ARE knowable without a limit still are.
    assert c.post_package_count == 11
    assert c.net_player_change == 1


def test_a_non_positive_limit_is_unknown_not_a_limit_of_zero():
    for bad in (0, -1, None, "12"):
        out = _plan(active_limit=bad, incoming=[P("A", "WR", 900)])
        assert out.capacity.active_limit is None, bad


def test_cleanup_that_the_lineup_forbids_is_reported_infeasible_not_forced():
    """Every remaining player is required to fill the lineup, so the ladder
    cannot supply the cuts.  Saying so beats cutting a starter to make the
    arithmetic work."""
    minimal = [
        P("QB1", "QB", 900),
        P("RB1", "RB", 800),
        P("RB2", "RB", 700),
        P("WR1", "WR", 850),
        P("WR2", "WR", 750),
        P("WR3", "WR", 650),
        P("TE1", "TE", 600),
        P("FLEXER", "RB", 500),
    ]
    # 8 players fill all 8 slots exactly, so NOBODY is droppable. Adding two
    # and demanding a 7-man roster asks for three cuts the lineup forbids.
    out = plan_roster_capacity(
        minimal,
        _SLOTS,
        incoming=[P("A", "WR", 900), P("B", "WR", 880)],
        active_limit=7,
        waiver_values=_WAIVERS,
    )
    assert out.capacity.cleanup_moves_required == 3
    assert out.cleanup.feasible is False
    assert out.cleanup.shortfall > 0
    assert len(out.cleanup.releases) < 3


# ══ Uncertainty is preserved, not resolved ═════════════════════════


def test_close_cleanup_alternatives_are_reported_rather_than_pretended_certain():
    """ "If multiple cleanup options are close, preserve uncertainty rather
    than pretending one drop is certain." """
    tied = _roster()
    tied[-1] = P("BENCH2", "WR", 300)  # identical to BENCH1
    out = plan_roster_capacity(
        tied, _SLOTS, incoming=[P("A", "WR", 900)], active_limit=10, waiver_values=_WAIVERS
    )
    assert len(out.cleanup.releases) == 1
    assert out.cleanup.ambiguous is True
    assert out.cleanup.close_alternatives
    assert out.cleanup.to_dict()["toleranceStatus"] == "PRIOR"


def test_a_clearly_cheapest_cut_is_not_reported_as_ambiguous():
    out = _plan(active_limit=10, incoming=[P("A", "WR", 900)])
    assert len(out.cleanup.releases) == 1
    assert out.cleanup.ambiguous is False
    assert out.cleanup.close_alternatives == ()


def test_the_tolerance_only_decides_what_is_REPORTED_never_what_is_CUT():
    """A calibration knob that changed the answer would be a calibration knob
    on a canonical decision.  This one is not."""
    import src.roster_intel.capacity as cap

    baseline = _plan(active_limit=10, incoming=[P("A", "WR", 900)])
    original = cap.CLEANUP_AMBIGUITY_TOLERANCE
    try:
        cap.CLEANUP_AMBIGUITY_TOLERANCE = 10.0
        loosened = _plan(active_limit=10, incoming=[P("A", "WR", 900)])
    finally:
        cap.CLEANUP_AMBIGUITY_TOLERANCE = original
    assert [r["playerId"] for r in loosened.cleanup.releases] == [
        r["playerId"] for r in baseline.cleanup.releases
    ]
    assert loosened.cleanup.ambiguous and not baseline.cleanup.ambiguous
    assert CLEANUP_AMBIGUITY_TOLERANCE == original


# ══ The final roster is the LEGAL one ══════════════════════════════


def test_roster_intelligence_runs_on_the_final_legal_roster_not_the_over_limit_one():
    """ "The analyzer must not run season odds on an impossible over-limit
    roster when a required cleanup move materially changes the roster." """
    out = _plan(
        active_limit=10,
        incoming=[P("A", "WR", 900), P("B", "WR", 880)],
        outgoing_ids=["BENCH2"],
    )
    released = {r["playerId"] for r in out.cleanup.releases}
    final_ids = out.simulation.core_after.core_ids
    assert not (released & final_ids)
    assert "BENCH2" not in final_ids
    assert {"A", "B"} <= set(final_ids) | out.simulation.core_after.unpriced_ids


def test_no_verdict_grade_or_score_is_produced():
    """Structural.  Everything left of EVALUATE is roster mechanics; the
    verdict is the trade lane's, and a roster fact that quietly becomes an
    opinion is not auditable."""
    payload = _plan(active_limit=10, incoming=[P("A", "WR", 900)]).to_dict()
    blob = repr(payload).lower()
    for banned in ("verdict", "grade", "recommend", "score", "rating", "winner", "make", "pass"):
        assert banned not in blob, banned


def test_it_never_computes_a_package_delta_minus_lowest_raw_value():
    """The shortcut the spec forbids by name.  Structural, because the honest
    way to not do a thing is to have no code that could."""
    tree = ast.parse((REPO / "src/roster_intel/capacity.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body[0].value.value = ""
    source = ast.unparse(tree)
    # It never touches a player's value at all — not to sort by it, not to
    # take a minimum of it, not to subtract it from a package delta.  The
    # only cost numbers it sees are the ladder's own ``effectiveCutCost``
    # stamps, which are already replacement-adjusted by the canonical owner.
    # (``rankDerivedValue`` is deliberately absent from this list: it appears
    # once, as the ``valueScale`` stamp naming which scale the ladder's costs
    # are in.  Naming a scale is not reading a value.)
    for banned in ("ros_value", "board_value", ".value"):
        assert banned not in source, banned
    # And the cleanup comes off the canonical ladder and nowhere else.
    assert "pool_cut_ladder" in source
    assert source.count("pool_cut_ladder") == 2  # the import and the one call


def test_it_does_not_mutate_the_roster_it_was_given():
    pool = _roster()
    snapshot = [(p.player_id, p.ros_value) for p in pool]
    plan_roster_capacity(
        pool,
        _SLOTS,
        incoming=[P("A", "WR", 900)],
        outgoing_ids=["BENCH1"],
        active_limit=10,
        waiver_values=_WAIVERS,
    )
    assert [(p.player_id, p.ros_value) for p in pool] == snapshot
