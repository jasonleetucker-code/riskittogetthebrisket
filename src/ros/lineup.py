"""Best-projected-lineup optimizer for ROS team-strength.

Given a roster + per-player ROS values + the league's roster_settings,
return the highest-scoring eligible lineup plus a residual "depth"
score for the bench — best-ball-aware.

    starting_lineup_score = Σ ros_value over the OPTIMAL eligible lineup
    bb_depth_score        = Σ ros_value over the next ``DEPTH_BENCH_LIMIT``
                            players, decayed by position (best-ball
                            spike-week premium for WR/RB/TE).

Exactness (LI-3, ADR-004)
─────────────────────────
The lineup fill is an **exact** maximum-weight assignment, not a
heuristic.  It was previously a slot-ordered greedy ("walk slots
most-restrictive-first, take the best eligible unused player"), which
is optimal only while the slot eligibility sets form a *laminar*
family (each pair nested or disjoint).  That happens to hold for this
league's slots today (QB ⊂ SUPER_FLEX; RB/WR/TE ⊂ FLEX ⊂ SUPER_FLEX;
DL/LB/DB ⊂ IDP_FLEX; K disjoint) — so the old code produced correct
answers by an unstated precondition nobody was enforcing.  A single
non-laminar slot (a WR/TE-only flex beside the RB/WR/TE FLEX, a
QB/RB-only slot, a two-family IDP flex) breaks it *silently*: no
error, just a quietly suboptimal lineup.

``optimize_lineup`` now solves the assignment exactly via weight-
descending matroid greedy with augmenting paths (Kuhn's algorithm on
the bipartite player↔slot graph).  Because slot eligibility defines a
transversal matroid and each player's weight is slot-independent,
processing players in descending weight and augmenting when possible
yields a provably maximum-weight assignment for ANY eligibility
structure — laminar or not.  Cost is O(P·S·E), trivial at roster
scale (≤60 players × ≤25 slots), and it is dependency-free.
``tests/league_intel/test_lineup_exactness.py`` pins equivalence with
brute force and includes the non-laminar case the old greedy failed.

Slot eligibility map mirrors Sleeper's roster_positions naming:

    QB, RB, WR, TE, FLEX (RB/WR/TE), SUPER_FLEX (QB/RB/WR/TE),
    DL, LB, DB, IDP_FLEX (DL/LB/DB), DEF (team defense, ignored), K, BN

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# Per-position eligibility for flex slots.  Order encodes priority when
# the optimizer has a choice (more-restricted slot fills first).
_FLEX_ELIGIBLE = {"RB", "WR", "TE"}
_SUPER_FLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}
_IDP_FLEX_ELIGIBLE = {"DL", "DE", "DT", "EDGE", "LB", "DB", "S", "CB"}
_IDP_FAMILIES = {
    "DL": {"DL", "DE", "DT", "EDGE"},
    "LB": {"LB"},
    "DB": {"DB", "S", "CB"},
}

# Best-ball depth: how many bench rows to count.  Beyond this, a
# player's spike-week contribution is too marginal to credit at the
# team level.
DEPTH_BENCH_LIMIT = 8

# Position decay for depth contribution — first bench WR/RB/TE counts
# fully, second counts 70%, third counts 49%, etc.  QBs and IDP get a
# slightly steeper decay because their backup-week spikes are rarer.
_DEPTH_DECAY = {
    "QB": 0.55,
    "RB": 0.65,
    "WR": 0.65,
    "TE": 0.55,
    "DL": 0.55,
    "LB": 0.55,
    "DB": 0.55,
}
_DEFAULT_DECAY = 0.50


@dataclass(frozen=True)
class RosterPlayer:
    """Roster entry for the optimizer.  Immutable so the order doesn't matter.

    ``fantasy_positions`` mirrors Sleeper's per-player
    ``fantasy_positions`` list — the field the host itself uses for
    slot eligibility.  It is frequently WIDER than ``position``: a
    pass-rushing linebacker ships as ``position="DL"`` with
    ``fantasy_positions=["DL", "LB"]`` and is legal in either slot.
    Empty (the default) means "fall back to ``position``", so existing
    callers keep working unchanged.
    """

    player_id: str
    canonical_name: str
    position: str
    ros_value: float
    confidence: float = 1.0
    injured: bool = False
    bye: bool = False
    fantasy_positions: tuple[str, ...] = ()

    def eligible_positions(self) -> tuple[str, ...]:
        """Every position this player may be slotted at."""
        if self.fantasy_positions:
            merged = {p.strip().upper() for p in self.fantasy_positions if p and p.strip()}
            if self.position:
                merged.add(self.position.strip().upper())
            return tuple(sorted(merged))
        return (self.position.strip().upper(),) if self.position else ()


@dataclass
class LineupSolution:
    """Structured optimizer output for serialization + UI."""

    starting_lineup_score: float
    starting_lineup: list[dict[str, Any]]
    bench_depth_score: float
    bench_depth: list[dict[str, Any]]
    positional_coverage_score: float
    health_availability_score: float
    unfilled_slots: list[str]


def _normalize_slot_name(slot: str) -> str:
    s = (slot or "").strip().upper()
    if s in {"SUPER_FLEX", "SUPERFLEX", "OP"}:
        return "SUPER_FLEX"
    if s in {"WRRB_FLEX", "WR_RB_FLEX", "FLEX_WRRB"}:
        return "FLEX"
    if s in {"IDP_FL", "IDP_FLEX", "IDPFLX"}:
        return "IDP_FLEX"
    return s


def _eligible_for_slot(slot: str, position: str) -> bool:
    pos = (position or "").upper()
    norm = _normalize_slot_name(slot)
    if norm == "SUPER_FLEX":
        return pos in _SUPER_FLEX_ELIGIBLE
    if norm == "FLEX":
        return pos in _FLEX_ELIGIBLE
    if norm == "IDP_FLEX":
        return pos in _IDP_FLEX_ELIGIBLE
    if norm in _IDP_FAMILIES:
        return pos in _IDP_FAMILIES[norm]
    return pos == norm


def _player_eligible_for_slot(slot: str, player: RosterPlayer) -> bool:
    """Slot eligibility over ALL of a player's fantasy positions.

    Sleeper evaluates eligibility against ``fantasy_positions``, so a
    DL/LB hybrid legally fills either an LB or a DL slot.  Checking
    only ``position`` (as this module used to) silently benches the
    better lineup — confirmed against real Sleeper best-ball weeks in
    ``tests/league_intel/test_lineup_exactness.py``.
    """
    return any(_eligible_for_slot(slot, pos) for pos in player.eligible_positions())


def _value_with_health_penalty(player: RosterPlayer) -> float:
    """Discount ros_value when the player is injured / on bye."""
    base = max(0.0, float(player.ros_value or 0.0))
    if player.injured:
        base *= 0.4
    elif player.bye:
        base *= 0.0
    return base


def solve_optimal_assignment(
    pool: list[RosterPlayer],
    slots: list[str],
) -> dict[int, RosterPlayer]:
    """Exact maximum-weight player→slot assignment.

    Returns ``{slot_index: player}`` maximizing Σ adjusted value over
    assigned players, subject to each player filling at most one slot
    and each slot holding at most one eligible player.

    Algorithm: matroid greedy with augmenting paths.  Slot eligibility
    defines a transversal matroid and each player's weight is the same
    whichever slot they fill, so processing players in descending
    weight and admitting a player whenever an augmenting path to a
    free slot exists is provably optimal — for any eligibility
    structure, laminar or not.  (Admitting a player may reshuffle
    already-assigned players between slots; it never evicts one,
    which is exactly why the exchange argument holds.)

    Deterministic: players are ordered by ``(-value, player_id)`` and
    augmenting paths explore slots in index order, so equal-value ties
    resolve the same way on every run.
    """
    ordered = sorted(pool, key=lambda p: (-_value_with_health_penalty(p), p.player_id))
    eligible_slots: list[list[int]] = [
        [i for i, slot in enumerate(slots) if _player_eligible_for_slot(slot, p)] for p in ordered
    ]
    # slot index -> index into `ordered`
    slot_owner: dict[int, int] = {}

    def _augment(player_idx: int, seen: set[int]) -> bool:
        for slot_idx in eligible_slots[player_idx]:
            if slot_idx in seen:
                continue
            seen.add(slot_idx)
            owner = slot_owner.get(slot_idx)
            if owner is None or _augment(owner, seen):
                slot_owner[slot_idx] = player_idx
                return True
        return False

    seen_ids: set[str] = set()
    for idx, player in enumerate(ordered):
        # Guard against a roster carrying the same player twice — the
        # matching would otherwise happily start them in two slots.
        if player.player_id in seen_ids:
            continue
        seen_ids.add(player.player_id)
        _augment(idx, set())

    assignment = {slot_idx: ordered[p_idx] for slot_idx, p_idx in slot_owner.items()}
    return _canonicalize_slots(assignment, slots)


def _canonicalize_slots(
    assignment: dict[int, RosterPlayer],
    slots: list[str],
) -> dict[int, RosterPlayer]:
    """Pick a canonical representative among equally-optimal lineups.

    A maximum-weight assignment is rarely unique: a WR worth the same
    in the WR slot and the FLEX slot can sit in either without changing
    the score.  Which one the matching happens to return is an artifact
    of augmenting-path order, and it leaks into the UI ("why is my WR1
    listed as my FLEX?").

    Callers expect the intuitive labelling: higher-value players in the
    more restrictive slots, which is the order ``slots`` is already
    sorted in.  This pass repeatedly (a) slides a player into an
    earlier empty slot they are eligible for, and (b) swaps two
    assigned players when the earlier slot holds the lower value and
    both are cross-eligible.  Both moves keep the multiset of started
    players — and therefore the total — identical, so optimality is
    preserved by construction.
    """
    changed = True
    while changed:
        changed = False
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                here, there = assignment.get(i), assignment.get(j)
                if there is None:
                    continue
                if here is None:
                    if _player_eligible_for_slot(slots[i], there):
                        assignment[i] = there
                        del assignment[j]
                        changed = True
                    continue
                if _value_with_health_penalty(here) >= _value_with_health_penalty(there):
                    continue
                if _player_eligible_for_slot(slots[i], there) and _player_eligible_for_slot(
                    slots[j], here
                ):
                    assignment[i], assignment[j] = there, here
                    changed = True
    return assignment


def optimize_lineup(
    roster: Iterable[RosterPlayer],
    *,
    starter_slots: Iterable[str],
) -> LineupSolution:
    """Exact best-projected lineup over the configured starter slots.

    The starting lineup is a true maximum-weight assignment (see
    ``solve_optimal_assignment`` and the module docstring); slots are
    reported in restrictiveness order for stable output.

    Returns:
        LineupSolution with starting_lineup_score = Σ best lineup, plus
        the bench_depth contribution + positional_coverage +
        health_availability sub-scores ready to feed
        ``team_ros_strength``'s composite formula.
    """
    pool = sorted(
        list(roster),
        key=lambda p: -_value_with_health_penalty(p),
    )
    used: set[str] = set()
    slot_order = sorted(
        [_normalize_slot_name(s) for s in starter_slots],
        key=_slot_priority,
    )

    assignment = solve_optimal_assignment(pool, slot_order)

    starting_total = 0.0
    starting_rows: list[dict[str, Any]] = []
    unfilled: list[str] = []

    for slot_idx, slot in enumerate(slot_order):
        pick = assignment.get(slot_idx)
        if pick is None:
            unfilled.append(slot)
            continue
        used.add(pick.player_id)
        adj_value = _value_with_health_penalty(pick)
        starting_total += adj_value
        starting_rows.append(
            {
                "slot": slot,
                "playerId": pick.player_id,
                "canonicalName": pick.canonical_name,
                "position": pick.position,
                "rosValue": round(float(pick.ros_value), 2),
                "adjustedValue": round(adj_value, 2),
                "confidence": round(float(pick.confidence), 3),
                "flagged": "injured" if pick.injured else ("bye" if pick.bye else None),
            }
        )

    # Bench contribution — best-ball spike-week credit.
    bench: list[RosterPlayer] = [p for p in pool if p.player_id not in used]
    bench_total = 0.0
    bench_rows: list[dict[str, Any]] = []
    by_pos_seen: dict[str, int] = {}
    for player in bench:
        if len(bench_rows) >= DEPTH_BENCH_LIMIT:
            break
        decay_per_player = _DEPTH_DECAY.get(player.position.upper(), _DEFAULT_DECAY)
        seen = by_pos_seen.get(player.position.upper(), 0)
        # First bench player at a position counts fully; second decays
        # by `decay_per_player`; third by decay^2; etc.
        depth_factor = decay_per_player**seen
        adj_value = _value_with_health_penalty(player) * depth_factor
        bench_total += adj_value
        bench_rows.append(
            {
                "playerId": player.player_id,
                "canonicalName": player.canonical_name,
                "position": player.position,
                "rosValue": round(float(player.ros_value), 2),
                "depthFactor": round(depth_factor, 3),
                "depthContribution": round(adj_value, 2),
            }
        )
        by_pos_seen[player.position.upper()] = seen + 1

    # Positional coverage — penalize teams missing depth at scarce
    # positions (QB in superflex, TE).  PR1 uses a simple presence
    # check; PR2 will weight by replacement-level scarcity.
    coverage_score = _positional_coverage(roster)

    # Health availability — share of starters not flagged injured/bye.
    healthy_starters = sum(1 for r in starting_rows if not r.get("flagged"))
    health_score = healthy_starters / len(starting_rows) * 100 if starting_rows else 0.0

    return LineupSolution(
        starting_lineup_score=round(starting_total, 2),
        starting_lineup=starting_rows,
        bench_depth_score=round(bench_total, 2),
        bench_depth=bench_rows,
        positional_coverage_score=round(coverage_score, 2),
        health_availability_score=round(health_score, 2),
        unfilled_slots=unfilled,
    )


# Restrictive slots fill before flexible ones so we don't burn a SF
# pick on a WR who could've slotted FLEX.
def _slot_priority(slot: str) -> tuple[int, str]:
    if slot == "SUPER_FLEX":
        return (3, slot)
    if slot in {"FLEX", "IDP_FLEX"}:
        return (2, slot)
    return (0, slot)


def _positional_coverage(roster: Iterable[RosterPlayer]) -> float:
    """0-100 score for "does the roster have depth at scarce positions"."""
    counts: dict[str, int] = {}
    for p in roster:
        counts[p.position.upper()] = counts.get(p.position.upper(), 0) + 1
    targets = {"QB": 2, "RB": 4, "WR": 5, "TE": 2}
    pts = 0.0
    for pos, target in targets.items():
        have = counts.get(pos, 0)
        pts += min(1.0, have / target) * (100.0 / len(targets))
    return pts
