"""Best-projected-lineup optimizer for ROS team-strength.

Given a roster + per-player ROS values + the league's roster_settings,
return the highest-scoring eligible lineup plus a residual "depth"
score for the bench — best-ball-aware.

PR 1 uses a deterministic-mean approximation:

    starting_lineup_score = Σ ros_value over best eligible lineup
    bb_depth_score        = Σ ros_value over the next ``DEPTH_BENCH_LIMIT``
                            players, decayed by position (best-ball
                            spike-week premium for WR/RB/TE).

PR 3 will replace this with Monte Carlo sims that draw weekly scores
from each player's distribution and pick the optimal lineup per draw.
For PR 1 the deterministic approximation is good enough to power the
new /league section and gives us a stable target to validate against.

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
    """Roster entry for the optimizer.  Immutable so the order doesn't matter."""

    player_id: str
    canonical_name: str
    position: str
    ros_value: float
    confidence: float = 1.0
    injured: bool = False
    bye: bool = False


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


def _value_with_health_penalty(player: RosterPlayer) -> float:
    """Discount ros_value when the player is injured / on bye."""
    base = max(0.0, float(player.ros_value or 0.0))
    if player.injured:
        base *= 0.4
    elif player.bye:
        base *= 0.0
    return base


def optimize_lineup(
    roster: Iterable[RosterPlayer],
    *,
    starter_slots: Iterable[str],
) -> LineupSolution:
    """Greedy best-projected lineup over the configured starter slots.

    Greedy approach: walk slots in restrictiveness order (specific
    positions before flex / super-flex), pick the highest-value eligible
    unused player.  Optimal under the deterministic-mean assumption
    because per-slot decisions are independent given fixed values.

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

    starting_total = 0.0
    starting_rows: list[dict[str, Any]] = []
    unfilled: list[str] = []

    for slot in slot_order:
        pick: RosterPlayer | None = None
        for player in pool:
            if player.player_id in used:
                continue
            if not _eligible_for_slot(slot, player.position):
                continue
            pick = player
            break
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
        depth_factor = decay_per_player ** seen
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
    healthy_starters = sum(
        1 for r in starting_rows if not r.get("flagged")
    )
    health_score = (
        healthy_starters / len(starting_rows) * 100 if starting_rows else 0.0
    )

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
