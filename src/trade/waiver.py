"""Waiver-wire suggestions — actionable free-agent pickups.

Distinct from ``src/trade/suggestions.py``, which generates
trade-target ideas between rosters.  Waiver suggestions are players
NOT currently on any roster in the league — directly addable from
free agency.

Algorithm (per call):

1. Build the universe of all rostered players across the league
   from ``sleeper.teams[*].players``.
2. Walk the canonical contract's ``playersArray``, filter to:
   * Active offense / IDP positions (no DSTs, no Ks unless league
     scoring includes K/DEF — but those are typically waiver
     fodder anyway, so we always include them).
   * Players NOT in the rostered set.
   * Players with ``rankDerivedValue >= MIN_WAIVER_VALUE`` (default
     500) — drops the long tail of practice-squad noise.
   * Optionally with the existing pre-draft rookie gate from
     ``suggestions._rookies_eligible_today`` so rookie placeholders
     don't surface during Feb 1 - May 11.
3. Sort by:
   * When ``apply_scoring_fit=True``: ``idpScoringFitAdjustedValue``
     for IDPs, ``rankDerivedValue`` for offense (so the lens
     surfaces league-aware value).
   * Otherwise: pure ``rankDerivedValue``.
4. Group by position so the user sees the best pickup per slot
   ("best LB available, best DL, best WR depth").

Output shape mirrors ``trade.suggestions``: a list of player dicts
with ``rationale`` + ``confidence`` so the frontend can render with
the same components.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.trade.suggestions import _rookies_eligible_today

_LOGGER = logging.getLogger(__name__)


# ── Tuning ─────────────────────────────────────────────────────────
# Drops the long tail of low-value FAs.  500 is the empirical floor
# below which the consensus blend is too noisy to be actionable.
MIN_WAIVER_VALUE = 500

# Cap candidates per position so the response stays readable on
# the frontend.  6 covers the realistic window (you'd never pick
# up the 8th-best LB on the wire).
DEFAULT_PER_POSITION_LIMIT = 6

# Positions that can be picked up.  Excludes "PICK" (you don't
# pick up draft picks on waivers) and excludes "DEF" / "K" by
# default since most leagues stream those.  Pass
# ``include_kicker_def=True`` to enable.
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
    adjusted_value: int  # equals consensus when scoring-fit not applied
    rank: int | None
    tier: str | None
    fit_delta: float | None  # None for offense + IDPs without delta
    fit_confidence: str | None
    fit_synthetic: bool
    is_rookie: bool
    # FAAB bid range (computed from position scarcity + adjusted
    # value share of league budget).  None when budget context
    # missing.  Three thresholds for user discretion.
    bid_aggressive: int | None = None
    bid_reasonable: int | None = None
    bid_lowball: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "consensusValue": self.consensus_value,
            "adjustedValue": self.adjusted_value,
            "rank": self.rank,
            "tier": self.tier,
            "fitDelta": self.fit_delta,
            "fitConfidence": self.fit_confidence,
            "fitSynthetic": self.fit_synthetic,
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
    """Return (aggressive, reasonable, lowball) FAAB bids.

    Heuristic: a player's bid scales with their value relative to
    the top of the FA pool.  The top FA gets 25-40% of remaining
    budget on the aggressive tier, scaling down linearly to ~$1 for
    the lowest-value FAs.  Three thresholds give the user a
    decision range without prescribing one number.

    ``league_budget`` is the user's REMAINING FAAB.  Defaults to
    100 (typical Sleeper league).  The caller is responsible for
    scoping this — a $100 cap with 5 weeks left should hold ~$20
    in reserve for emergencies, so the user might pass a smaller
    effective budget.
    """
    if candidate_value <= 0 or league_budget <= 0:
        return (0, 0, 0)
    top_v = max(candidate_value, top_value_in_pool or 0)
    # Share of pool's top — anchors the aggressive bid.  Top FA =
    # 1.0; an FA at half the top's value = 0.5.
    share = candidate_value / top_v if top_v > 0 else 1.0
    # Aggressive: 30% of budget at top, scaling down to ~5% at the
    # bottom of the pool.  Hits "this is a real piece, win the bid".
    aggressive_pct = 0.05 + 0.25 * share
    # Reasonable: 70% of aggressive — wins ~most contested cases.
    # Lowball: 35% of aggressive — only wins if no one else cared.
    aggressive = max(1, round(league_budget * aggressive_pct))
    reasonable = max(1, round(aggressive * 0.70))
    lowball = max(1, round(aggressive * 0.35))
    return (aggressive, reasonable, lowball)


def _normalize_name(name: str) -> str:
    """Lowercase + strip whitespace for roster-set membership checks."""
    return str(name or "").strip().lower()


def find_waiver_targets(
    contract: dict[str, Any],
    sleeper_teams: list[dict[str, Any]] | None,
    *,
    apply_scoring_fit: bool = False,
    scoring_fit_weight: float = 0.30,
    min_value: int = MIN_WAIVER_VALUE,
    per_position_limit: int = DEFAULT_PER_POSITION_LIMIT,
    include_kicker_def: bool = False,
    user_faab_remaining: int | None = None,
) -> dict[str, Any]:
    """Return waiver-wire suggestions grouped by position.

    Returns:

        {
          "by_position": {
            "QB": [WaiverCandidate.to_dict(), ...],
            "RB": [...],
            ...
          },
          "total": int,
          "rookies_excluded": bool,
        }

    ``rookies_excluded`` reports whether the pre-draft window gate
    fired this call (Feb 1 - May 11) so the frontend can surface a
    note explaining why a rookie hasn't shown up.
    """
    arr = contract.get("playersArray") or []
    if not isinstance(arr, list):
        return {"by_position": {}, "total": 0, "rookies_excluded": False}

    # Build the rostered-set across all teams.  Single pass.
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
    fit_weight = max(0.0, min(1.0, float(scoring_fit_weight)))

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

        # Compute adjusted value when scoring-fit is on AND this is
        # an IDP with a delta.  Mirrors ``trade-logic.js::displayValue``.
        delta = row.get("idpScoringFitDelta")
        adjusted = float(consensus)
        if (apply_scoring_fit
                and isinstance(delta, (int, float))
                and fit_weight > 0):
            adjusted = max(0, min(9999, float(consensus) + float(delta) * fit_weight))

        cand = WaiverCandidate(
            name=name,
            position=pos,
            consensus_value=int(round(float(consensus))),
            adjusted_value=int(round(adjusted)),
            rank=row.get("canonicalConsensusRank") or None,
            tier=row.get("idpScoringFitTier"),
            fit_delta=float(delta) if isinstance(delta, (int, float)) else None,
            fit_confidence=row.get("idpScoringFitConfidence"),
            fit_synthetic=bool(row.get("idpScoringFitSynthetic")),
            is_rookie=is_rookie,
        )
        candidates_by_position.setdefault(pos, []).append(cand)

    # FAAB bid suggestions: scale relative to the TOP-VALUE FA in
    # the pool so the aggressive bid means "win this top piece".
    # Pool-wide top is the same across positions — bid suggestions
    # are absolute, not per-position.
    top_value = max(
        (c.adjusted_value for cs in candidates_by_position.values() for c in cs),
        default=0,
    )
    if user_faab_remaining is None or user_faab_remaining <= 0:
        user_faab_remaining = 100  # default Sleeper FAAB

    for cs in candidates_by_position.values():
        for c in cs:
            agg, reas, low = _compute_faab_bid(
                c.adjusted_value,
                league_budget=user_faab_remaining,
                top_value_in_pool=top_value,
            )
            c.bid_aggressive = agg
            c.bid_reasonable = reas
            c.bid_lowball = low

    # Sort each position bucket by ``adjusted_value`` descending and
    # cap per the limit.  Adjusted == consensus when scoring-fit is
    # off, so this works in both modes.
    out_by_position: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for pos, candidates in candidates_by_position.items():
        candidates.sort(key=lambda c: -c.adjusted_value)
        capped = candidates[:per_position_limit]
        out_by_position[pos] = [c.to_dict() for c in capped]
        total += len(capped)

    # Group abstract IDP families together so the consumer can fold
    # CB/S into "DB", DT/DE/EDGE into "DL", etc.  Done by emitting
    # a parallel "byFamily" view alongside.
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
        by_family[fam] = items[: per_position_limit * 2]  # families show 2x

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
    apply_scoring_fit: bool = False,
    scoring_fit_weight: float = 0.30,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return the lowest-value players on the user's roster, ranked
    bottom-up.  These are the natural drop candidates when adding a
    waiver pickup — best-ball-native: you adjust the 30-man roster
    every week, not the lineup.

    Adjusted value applies the scoring-fit weight when the toggle
    is on, so a fit-NEGATIVE IDP (lens says league overvalues them
    vs market) drops in priority — the lens flags them as
    "trade/drop" candidates first.

    Returns up to ``limit`` entries, sorted by adjusted value
    ascending (lowest first).  Only includes players currently on
    the user's roster.

    Each entry includes a ``rationale`` field explaining why the
    player is in the drop column: low rank, fit-negative, fringe
    tier, etc.  The frontend renders these as muted badges so the
    user can decide which to drop without scrolling deep into
    /rankings.
    """
    arr = contract.get("playersArray") or []
    if not isinstance(arr, list):
        return []

    roster_lower = {_normalize_name(n) for n in (user_team_players or [])}
    if not roster_lower:
        return []

    fit_weight = max(0.0, min(1.0, float(scoring_fit_weight)))
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

        delta = row.get("idpScoringFitDelta")
        adjusted = float(consensus)
        if (apply_scoring_fit
                and isinstance(delta, (int, float))
                and fit_weight > 0):
            adjusted = max(0, min(9999, float(consensus) + float(delta) * fit_weight))

        # Build rationale.
        rationale_parts: list[str] = []
        rank = row.get("canonicalConsensusRank")
        if isinstance(rank, int) and rank > 200:
            rationale_parts.append(f"rank #{rank} on consensus")
        if (apply_scoring_fit
                and isinstance(delta, (int, float))
                and delta <= -1500):
            tier = row.get("idpScoringFitTier")
            tier_label = (tier or "").replace("_", " ")
            rationale_parts.append(
                f"fit-negative {Math_round(delta)} ({tier_label})"
            )
        elif row.get("idpScoringFitTier") in ("fringe", "below_replacement"):
            rationale_parts.append(f"{row.get('idpScoringFitTier').replace('_', ' ')} tier")
        if not rationale_parts:
            rationale_parts.append("low value vs roster average")

        candidates.append((adjusted, {
            "name": name,
            "position": str(row.get("position") or "").upper(),
            "consensusValue": int(round(float(consensus))),
            "adjustedValue": int(round(adjusted)),
            "rank": rank if isinstance(rank, int) else None,
            "fitDelta": float(delta) if isinstance(delta, (int, float)) else None,
            "fitTier": row.get("idpScoringFitTier"),
            "rationale": " · ".join(rationale_parts),
        }))

    candidates.sort(key=lambda x: x[0])  # ascending — lowest first
    return [c[1] for c in candidates[:limit]]


def Math_round(v):
    return int(round(float(v)))
