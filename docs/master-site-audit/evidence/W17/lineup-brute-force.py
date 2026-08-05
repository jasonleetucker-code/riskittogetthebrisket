"""Brute-force verification of src.ros.lineup.solve_optimal_assignment."""

import random
import sys
import json

sys.path.insert(0, "/home/user/riskittogetthebrisket")
from src.ros.lineup import (
    RosterPlayer,
    solve_optimal_assignment,
    _player_eligible_for_slot,
    _value_with_health_penalty,
    _normalize_slot_name,
    _slot_priority,
)


def brute(pool, slots):
    """Exhaustive max-weight assignment via DFS over slots."""
    n = len(slots)
    best = [0.0, None]
    idx = list(range(len(pool)))

    def rec(si, used, total, assign):
        if si == n:
            if total > best[0] + 1e-12:
                best[0] = total
                best[1] = dict(assign)
            return
        # leave slot empty
        rec(si + 1, used, total, assign)
        for pi in idx:
            if pi in used:
                continue
            if not _player_eligible_for_slot(slots[si], pool[pi]):
                continue
            assign[si] = pi
            rec(si + 1, used | {pi}, total + _value_with_health_penalty(pool[pi]), assign)
            del assign[si]

    rec(0, frozenset(), 0.0, {})
    return best[0]


POSSETS = [
    ("QB", ()),
    ("RB", ()),
    ("WR", ()),
    ("TE", ()),
    ("K", ()),
    ("DL", ("DL", "LB")),
    ("LB", ()),
    ("DB", ("DB", "LB")),
    ("LB", ("LB", "DB")),
    ("DL", ()),
]
SLOTSETS = [
    # live league (laminar)
    ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "DL", "LB", "DB"],
    # NON-LAMINAR: WRTE-ish flex alongside FLEX -- emulate via TE + FLEX + SUPER_FLEX + WR
    ["WR", "TE", "FLEX", "SUPER_FLEX", "QB", "RB"],
    # IDP two-family: IDP_FLEX beside dedicated DL/LB/DB (hybrids make it non-laminar)
    ["DL", "LB", "DB", "IDP_FLEX", "IDP_FLEX"],
]

random.seed(1234)
fails = []
trials = 0
for slots in SLOTSETS:
    slot_order = sorted([_normalize_slot_name(s) for s in slots], key=_slot_priority)
    for t in range(120):
        npl = random.randint(3, 9)
        pool = []
        for i in range(npl):
            pos, fps = random.choice(POSSETS)
            pool.append(
                RosterPlayer(
                    player_id=f"p{i}",
                    canonical_name=f"p{i}",
                    position=pos,
                    ros_value=round(random.uniform(0, 100), 2),
                    injured=random.random() < 0.15,
                    bye=random.random() < 0.08,
                    fantasy_positions=fps,
                )
            )
        got = solve_optimal_assignment(pool, slot_order)
        got_total = sum(_value_with_health_penalty(p) for p in got.values())
        exp = brute(pool, slot_order)
        trials += 1
        # legality checks
        ids = [p.player_id for p in got.values()]
        legal = len(ids) == len(set(ids)) and all(
            _player_eligible_for_slot(slot_order[si], p) for si, p in got.items()
        )
        if abs(got_total - exp) > 1e-9 or not legal:
            fails.append(
                {
                    "slots": slot_order,
                    "legal": legal,
                    "got": got_total,
                    "brute": exp,
                    "pool": [
                        (
                            p.player_id,
                            p.position,
                            p.fantasy_positions,
                            p.ros_value,
                            p.injured,
                            p.bye,
                        )
                        for p in pool
                    ],
                }
            )
print(
    json.dumps(
        {"trials": trials, "failures": len(fails), "examples": fails[:3]}, indent=2, default=str
    )
)
