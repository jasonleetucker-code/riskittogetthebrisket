"""Exact before/after roster simulation (C2-SIM-01).

The manifest's acceptance is a **displacement test**, and the reason is
the point of the module: roster effects are set-dependent, so the player
a transaction displaces is frequently not the player it involved. Most
of this file is that claim, approached from several directions.
"""

from __future__ import annotations

from src.roster_intel.simulation import simulate_roster_change
from src.roster_intel.weakness import build_position_ranks
from src.ros.lineup import RosterPlayer


def P(pid, pos, val, **kw):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=val, **kw)


#: 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX — small enough to reason about by hand.
_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"]


def _roster():
    return [
        P("QB1", "QB", 900),
        P("RB1", "RB", 800),
        P("RB2", "RB", 700),
        P("RB3", "RB", 400),
        P("RB4", "RB", 150),
        P("WR1", "WR", 850),
        P("WR2", "WR", 750),
        P("WR3", "WR", 650),
        P("WR4", "WR", 300),
        P("WR5", "WR", 120),
        P("TE1", "TE", 600),
        P("TE2", "TE", 100),
    ]


def _sim(**kw):
    return simulate_roster_change(_roster(), _SLOTS, **kw)


def _by_id(sim):
    return {m.player_id: m for m in sim.movements}


# ══ The displacement cascade ═══════════════════════════════════════


def test_the_displaced_player_is_not_the_one_traded():
    """THE acceptance test. RB3 (400) holds FLEX before. Acquiring a
    600-value RB takes that FLEX seat, so RB3 is displaced out of the
    starting lineup — by a transaction that never mentioned him.

    A value delta reports +600 and cannot say whose seat moved.
    """
    before = _sim()
    assert before.movements == ()  # no-op baseline

    sim = _sim(incoming=[P("NEW_RB", "RB", 600)])
    moved = _by_id(sim)

    assert moved["NEW_RB"].kind == "promoted"
    assert moved["NEW_RB"].slot_after == "FLEX"
    # RB3 lost the FLEX seat. He is still in the core as depth.
    assert moved["RB3"].slot_before == "FLEX"
    assert moved["RB3"].role_before == "starter"
    assert moved["RB3"].role_after == "reserve"
    assert moved["RB3"].kind == "moved"


def test_a_starter_falling_out_of_the_core_is_displaced_not_merely_moved():
    """Losing a slot and ceasing to matter are different facts, and
    collapsing them hides which one happened."""
    sim = _sim(incoming=[P(f"NEW{i}", "WR", 900 - i) for i in range(4)])
    moved = _by_id(sim)
    displaced = {m.player_id for m in sim.displacements}
    # The weakest WRs fall out of the core entirely.
    assert "WR5" in displaced
    assert moved["WR5"].role_before is not None
    assert moved["WR5"].role_after is None


def test_an_outgoing_starter_shows_as_displaced():
    sim = _sim(outgoing_ids=["QB1"])
    moved = _by_id(sim)
    assert moved["QB1"].kind == "displaced"
    assert moved["QB1"].slot_before == "QB"
    assert moved["QB1"].slot_after is None
    # And the QB slot is now unfillable, which the core reports.
    assert "QB" in sim.core_after.unfilled_starter_slots


def test_unchanged_players_are_not_reported():
    """Movement is the signal. Emitting every unchanged player would
    bury the three rows that matter under thirty that do not."""
    sim = _sim(incoming=[P("NEW_RB", "RB", 600)])
    assert all(m.kind != "unchanged" for m in sim.movements)
    assert "QB1" not in _by_id(sim)


def test_a_no_op_transaction_moves_nothing():
    sim = _sim()
    assert sim.movements == ()
    assert sim.strength_delta == 0.0
    assert sim.promotions == () and sim.displacements == ()


# ══ It is not a value subtraction ══════════════════════════════════


def test_a_player_who_does_not_make_the_core_moves_nothing():
    """The delta is `after − before` over independently solved cores, so
    an acquisition that does not reach the meaningful core contributes
    nothing — while a naive package sum would report +50.

    The roster must be DEEP enough for that to be true. `_roster()` has
    12 players against a core ceiling of 14 (8 slots + 6 reserve demand),
    so on the base fixture a scrub genuinely does make the core and
    genuinely is worth +50. That is correct behaviour, and asserting
    otherwise was a fixture error, not a code one — so this test
    saturates the core first.
    """
    deep = _roster() + [P(f"DEPTH{i}", "RB", 200 + i) for i in range(6)]
    saturated = simulate_roster_change(deep, _SLOTS)
    # Only the rooms SCRUB could enter need to be full. The QB reserve
    # slot stays unfilled because the roster carries one QB, and that is
    # correct — asserting on ALL unfilled slots would fail on a fact
    # unrelated to what this test is about.
    assert "RB" not in saturated.core_before.unfilled_reserve_slots
    assert "FLEX" not in saturated.core_before.unfilled_reserve_slots

    sim = simulate_roster_change(deep, _SLOTS, incoming=[P("SCRUB", "RB", 50)])
    assert sim.strength_delta == 0.0
    assert sim.movements == ()


def test_a_negative_delta_can_still_close_a_need():
    """The case that makes 'never a value subtraction' concrete: give up
    a valuable WR for a cheaper TE when TE is the unfilled slot."""
    thin = [p for p in _roster() if not p.player_id.startswith("TE")]
    ranks = build_position_ranks(
        [(p.player_id, p.position, p.ros_value) for p in thin]
        + [("CHEAP_TE", "TE", 200)]
        + [(f"f{i}", pos, 999 - i) for pos in ("QB", "RB", "WR", "TE") for i in range(30)],
        population="test",
    )
    sim = simulate_roster_change(
        thin,
        _SLOTS,
        incoming=[P("CHEAP_TE", "TE", 200)],
        outgoing_ids=["WR1"],
        ranks=ranks,
        team_count=12,
    )
    # Value went down…
    assert sim.strength_delta < 0
    # …and the unfilled TE slot is now filled.
    assert "TE" in sim.core_before.unfilled_starter_slots
    assert "TE" not in sim.core_after.unfilled_starter_slots


def test_no_verdict_or_grade_is_produced():
    """Structural: this module reports movement. Whether the movement is
    good is a trade-lane judgement, and a roster fact that quietly
    becomes an opinion is not auditable."""
    payload = _sim(incoming=[P("NEW_RB", "RB", 600)]).to_dict()
    for banned in ("verdict", "grade", "recommendation", "score", "rating", "winner"):
        assert not any(banned in k.lower() for k in payload), banned


# ══ Needs, both directions ═════════════════════════════════════════


def _ranks(extra=()):
    rows = [(p.player_id, p.position, p.ros_value) for p in _roster()] + list(extra)
    rows += [
        (f"filler_{pos}{i}", pos, 999 - i * 30)
        for pos in ("QB", "RB", "WR", "TE")
        for i in range(30)
    ]
    return build_position_ranks(rows, population="test")


def test_needs_created_is_reported_with_equal_weight_to_needs_fixed():
    """A simulation that only showed improvements would be an advocacy
    tool. Trading the only QB away must surface QB as a created need."""
    sim = simulate_roster_change(
        _roster(), _SLOTS, outgoing_ids=["QB1"], ranks=_ranks(), team_count=12
    )
    assert "QB" in sim.needs_created
    assert "QB" not in sim.needs_fixed


def test_need_deltas_are_empty_when_weakness_was_not_measured():
    """An unmeasured need is not 'no need'. Without ranks AND a team
    count the weakness half is None and the deltas stay empty rather
    than reporting a confident zero."""
    sim = _sim(outgoing_ids=["QB1"])
    assert sim.weakness_before is None and sim.weakness_after is None
    assert sim.needs_fixed == () and sim.needs_created == ()
    sim2 = simulate_roster_change(_roster(), _SLOTS, ranks=_ranks(), team_count=0)
    assert sim2.needs_fixed == () and sim2.needs_created == ()


# ══ Missing is never zero ══════════════════════════════════════════


def test_an_unpriced_incoming_player_is_reported_and_never_seated():
    sim = _sim(incoming=[P("MYSTERY", "RB", None)])
    assert sim.unpriced_incoming == frozenset({"MYSTERY"})
    assert "MYSTERY" not in {m.player_id for m in sim.movements}
    assert "MYSTERY" not in sim.core_after.core_ids
    # He displaced nobody: an unknown must not beat a known.
    assert sim.strength_delta == 0.0


def test_an_outgoing_id_not_on_the_roster_is_surfaced_not_ignored():
    """ "I removed a player you do not have" is a caller bug, and
    swallowing it makes the simulation quietly answer a different
    question than the one asked."""
    sim = _sim(outgoing_ids=["GHOST", "QB1"])
    assert sim.outgoing_not_found == frozenset({"GHOST"})
    assert "QB1" not in sim.core_after.core_ids


def test_a_refusal_propagates_from_the_core_owner():
    sim = simulate_roster_change(_roster(), [], incoming=[P("X", "RB", 500)])
    assert sim.available is False
    assert sim.unavailable_reason == "no_starter_slots"


# ══ Determinism ════════════════════════════════════════════════════


def test_the_simulation_is_deterministic_and_order_independent():
    import random

    base = _sim(incoming=[P("NEW_RB", "RB", 600)])
    expected = sorted((m.player_id, m.kind, m.slot_after) for m in base.movements)
    rng = random.Random(20260818)
    for _ in range(15):
        shuffled = _roster()
        rng.shuffle(shuffled)
        sim = simulate_roster_change(shuffled, _SLOTS, incoming=[P("NEW_RB", "RB", 600)])
        assert sorted((m.player_id, m.kind, m.slot_after) for m in sim.movements) == expected


def test_it_does_not_mutate_the_roster_it_was_given():
    pool = _roster()
    snapshot = [(p.player_id, p.ros_value) for p in pool]
    simulate_roster_change(pool, _SLOTS, incoming=[P("N", "RB", 600)], outgoing_ids=["RB1"])
    assert [(p.player_id, p.ros_value) for p in pool] == snapshot
