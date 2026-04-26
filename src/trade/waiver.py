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
        }


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
