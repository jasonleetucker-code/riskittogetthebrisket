"""The canonical-labelling pass reads precomputed eligibility — exactly.

``solve_optimal_assignment(..., precomputed_eligibility=...)`` used the
precomputed map for the matching but re-derived eligibility per slot pair in
``_canonicalize_slots``, which dominated every Monte-Carlo caller's solve
(Trade War Room speed, owner directive 2026-10-19).  It now reads the same
precomputed answer.  Pinned here: with and without the precomputed map the
solver returns the identical assignment — same slots, same players, same dict
ORDER (callers iterate ``.values()``) — over randomized pools with hybrids,
IDP families, custom flex rules, ties and negative realized points.
"""

from __future__ import annotations

import random

import pytest

from src.ros import lineup
from src.ros.lineup import (
    OBJECTIVE_ADJUSTED,
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    precompute_slot_eligibility,
    solve_optimal_assignment,
)

SLOT_SETS = [
    ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"],
    ["QB", "RB", "WR", "TE", "DL", "LB", "DB", "IDP_FLEX", "IDP_FLEX"],
    ["SUPER_FLEX", "FLEX", "WR", "DL_LB", "DB_LB"],
]
RULES = [None, {"FLEX": ["RB", "WR"], "IDP_FLEX": ["LB", "DB"]}, {"SUPER_FLEX": ["QB", "TE"]}]


def _pool(rng: random.Random, n: int) -> list[RosterPlayer]:
    positions = ["QB", "RB", "WR", "TE", "DL", "LB", "DB", "OLB", "SS", "K"]
    out = []
    for i in range(n):
        pos = rng.choice(positions)
        fantasy = tuple(rng.sample(["DL", "LB", "DB", "RB", "WR"], rng.randint(0, 2)))
        value = rng.choice([None, 0.0, -1.5, 3.0, 3.0, 7.25]) if rng.random() < 0.3 else None
        if value is None and rng.random() < 0.9:
            value = round(rng.uniform(-2.0, 25.0), 1)
        out.append(
            RosterPlayer(
                player_id=f"p{i:02d}",
                canonical_name=f"P{i}",
                position=pos,
                ros_value=value,
                fantasy_positions=fantasy,
                injured=rng.random() < 0.1,
                bye=rng.random() < 0.05,
            )
        )
    return out


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("objective", [OBJECTIVE_REALIZED_POINTS, OBJECTIVE_ADJUSTED])
def test_precomputed_and_derived_eligibility_give_the_identical_assignment(seed, objective):
    rng = random.Random(seed)
    slots = SLOT_SETS[seed % len(SLOT_SETS)]
    rule = RULES[(seed // 3) % len(RULES)]
    template = _pool(rng, rng.randint(4, 30))
    elig = precompute_slot_eligibility(template, slots, slot_eligibility=rule)
    # Solve the full pool and a random subset of it (the absence / weekly
    # pools are subsets of the template the map was derived from).
    for pool in (template, rng.sample(template, max(1, len(template) // 2))):
        derived = solve_optimal_assignment(pool, slots, slot_eligibility=rule, objective=objective)
        reused = solve_optimal_assignment(
            pool,
            slots,
            slot_eligibility=rule,
            precomputed_eligibility=elig,
            objective=objective,
        )
        assert [(i, p.player_id) for i, p in derived.items()] == [
            (i, p.player_id) for i, p in reused.items()
        ]


@pytest.mark.parametrize("seed", range(60))
def test_a_map_derived_under_another_rule_never_changes_the_labelling(seed):
    """``best_ball_utility._run`` derives its map WITH the league rule and calls
    the solver WITHOUT it.  The labelling pass must then answer with the
    call's own predicate, exactly as before; re-reading the map there
    relabelled ~10% of randomized custom-rule lineups (independent review of
    #1828).

    Reference-free property: the labelling pass loops to a fixed point of the
    predicate it uses, so the solver's output must be unchanged by running
    that pass again with the CALL's predicate."""
    rng = random.Random(1000 + seed)
    slots = SLOT_SETS[seed % len(SLOT_SETS)]
    rule = RULES[1 + seed % 2]  # a real league rule, never None
    pool = _pool(rng, rng.randint(4, 30))
    tagged = precompute_slot_eligibility(pool, slots, slot_eligibility=rule)
    for call_rule in (None, RULES[1 + (seed + 1) % 2], rule):
        got = solve_optimal_assignment(
            pool,
            slots,
            slot_eligibility=call_rule,
            precomputed_eligibility=tagged,
            objective=OBJECTIVE_REALIZED_POINTS,
        )
        again = lineup._canonicalize_slots(
            dict(got),
            list(slots),
            lineup._eligibility_predicate(call_rule),
            value=lineup._value_fn(OBJECTIVE_REALIZED_POINTS),
        )
        assert [(i, p.player_id) for i, p in got.items()] == [
            (i, p.player_id) for i, p in again.items()
        ]
