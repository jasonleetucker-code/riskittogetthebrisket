"""Waiver-wire suggestions — actionable free-agent pickups.

Finds players currently NOT on any roster in the league, sorted by
``rankDerivedValue`` descending.  Pre-draft window (Feb 1 – May 11)
suppresses rookies via the ``_rookies_eligible_today`` gate from
``src.trade.suggestions``.

Companion ``find_drop_candidates`` returns the lowest-value players
on the user's roster — best-ball-native: when adding a FA, you have
to drop someone, and this surfaces who first.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.trade.suggestions import _rookies_eligible_today

_LOGGER = logging.getLogger(__name__)


MIN_WAIVER_VALUE = 500
DEFAULT_PER_POSITION_LIMIT = 6

_BASE_POSITIONS = frozenset({
    "QB", "RB", "WR", "TE",
    "DL", "DT", "DE", "EDGE", "NT",
    "LB", "ILB", "OLB", "MLB",
    "DB", "CB", "S", "FS", "SS",
})


@dataclass
class WaiverCandidate:
    name: str
    position: str
    consensus_value: int
    rank: int | None
    is_rookie: bool
    bid_aggressive: int | None = None
    bid_reasonable: int | None = None
    bid_lowball: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "consensusValue": self.consensus_value,
            "adjustedValue": self.consensus_value,  # alias for backwards compat
            "rank": self.rank,
            "isRookie": self.is_rookie,
            "bid": {
                "aggressive": self.bid_aggressive,
                "reasonable": self.bid_reasonable,
                "lowball": self.bid_lowball,
            } if self.bid_aggressive is not None else None,
        }


def _compute_faab_bid(
    candidate_value: float,
    *,
    league_budget: int = 100,
    top_value_in_pool: float | None = None,
) -> tuple[int, int, int]:
    """Return (aggressive, reasonable, lowball) FAAB bids."""
    if candidate_value <= 0 or league_budget <= 0:
        return (0, 0, 0)
    top_v = max(candidate_value, top_value_in_pool or 0)
    share = candidate_value / top_v if top_v > 0 else 1.0
    aggressive_pct = 0.05 + 0.25 * share
    aggressive = max(1, round(league_budget * aggressive_pct))
    reasonable = max(1, round(aggressive * 0.70))
    lowball = max(1, round(aggressive * 0.35))
    return (aggressive, reasonable, lowball)


def _normalize_name(name: str) -> str:
    return str(name or "").strip().lower()


def find_waiver_targets(
    contract: dict[str, Any],
    sleeper_teams: list[dict[str, Any]] | None,
    *,
    min_value: int = MIN_WAIVER_VALUE,
    per_position_limit: int = DEFAULT_PER_POSITION_LIMIT,
    include_kicker_def: bool = False,
    user_faab_remaining: int | None = None,
) -> dict[str, Any]:
    """Return waiver-wire suggestions grouped by position."""
    arr = contract.get("playersArray") or []
    if not isinstance(arr, list):
        return {"by_position": {}, "by_family": {}, "total": 0, "rookies_excluded": False}

    rostered: set[str] = set()
    for team in sleeper_teams or []:
        if not isinstance(team, dict):
            continue
        for n in team.get("players") or []:
            rostered.add(_normalize_name(n))

    rookies_eligible = _rookies_eligible_today()
    positions = set(_BASE_POSITIONS)
    if include_kicker_def:
        positions.update({"K", "DEF"})

    candidates_by_position: dict[str, list[WaiverCandidate]] = {}

    for row in arr:
        if not isinstance(row, dict):
            continue
        pos = str(row.get("position") or "").upper()
        if pos not in positions:
            continue

        name = str(row.get("displayName") or row.get("canonicalName") or "")
        if not name or _normalize_name(name) in rostered:
            continue

        consensus = row.get("rankDerivedValue")
        if not isinstance(consensus, (int, float)) or consensus < min_value:
            continue

        is_rookie = bool(row.get("rookie") or row.get("_formatFitRookie"))
        if is_rookie and not rookies_eligible:
            continue

        cand = WaiverCandidate(
            name=name,
            position=pos,
            consensus_value=int(round(float(consensus))),
            rank=row.get("canonicalConsensusRank") or None,
            is_rookie=is_rookie,
        )
        candidates_by_position.setdefault(pos, []).append(cand)

    top_value = max(
        (c.consensus_value for cs in candidates_by_position.values() for c in cs),
        default=0,
    )
    if user_faab_remaining is None or user_faab_remaining <= 0:
        user_faab_remaining = 100

    for cs in candidates_by_position.values():
        for c in cs:
            agg, reas, low = _compute_faab_bid(
                c.consensus_value,
                league_budget=user_faab_remaining,
                top_value_in_pool=top_value,
            )
            c.bid_aggressive = agg
            c.bid_reasonable = reas
            c.bid_lowball = low

    out_by_position: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for pos, candidates in candidates_by_position.items():
        candidates.sort(key=lambda c: -c.consensus_value)
        capped = candidates[:per_position_limit]
        out_by_position[pos] = [c.to_dict() for c in capped]
        total += len(capped)

    family_map = {
        "DL": "DL", "DT": "DL", "DE": "DL", "EDGE": "DL", "NT": "DL",
        "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB",
        "DB": "DB", "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB",
    }
    by_family: dict[str, list[dict[str, Any]]] = {}
    for pos, items in out_by_position.items():
        fam = family_map.get(pos, pos)
        by_family.setdefault(fam, []).extend(items)
    for fam, items in by_family.items():
        items.sort(key=lambda c: -int(c.get("adjustedValue") or 0))
        by_family[fam] = items[: per_position_limit * 2]

    return {
        "by_position": out_by_position,
        "by_family": by_family,
        "total": total,
        "rookies_excluded": not rookies_eligible,
    }


def find_drop_candidates(
    contract: dict[str, Any],
    user_team_players: list[str],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return the lowest-value players on the user's roster, ranked
    bottom-up.  Best-ball companion to ``find_waiver_targets``."""
    arr = contract.get("playersArray") or []
    if not isinstance(arr, list):
        return []

    roster_lower = {_normalize_name(n) for n in (user_team_players or [])}
    if not roster_lower:
        return []

    candidates: list[tuple[float, dict[str, Any]]] = []

    for row in arr:
        if not isinstance(row, dict):
            continue
        name = str(row.get("displayName") or row.get("canonicalName") or "")
        if _normalize_name(name) not in roster_lower:
            continue

        consensus = row.get("rankDerivedValue")
        if not isinstance(consensus, (int, float)) or consensus <= 0:
            continue

        rank = row.get("canonicalConsensusRank")
        rationale_parts: list[str] = []
        if isinstance(rank, int) and rank > 200:
            rationale_parts.append(f"rank #{rank} on consensus")
        if not rationale_parts:
            rationale_parts.append("low value vs roster average")

        candidates.append((float(consensus), {
            "name": name,
            "position": str(row.get("position") or "").upper(),
            "consensusValue": int(round(float(consensus))),
            "adjustedValue": int(round(float(consensus))),  # alias
            "rank": rank if isinstance(rank, int) else None,
            "rationale": " · ".join(rationale_parts),
        }))

    candidates.sort(key=lambda x: x[0])
    return [c[1] for c in candidates[:limit]]
