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

_BASE_POSITIONS = frozenset(
    {
        "QB",
        "RB",
        "WR",
        "TE",
        "DL",
        "DT",
        "DE",
        "EDGE",
        "NT",
        "LB",
        "ILB",
        "OLB",
        "MLB",
        "DB",
        "CB",
        "S",
        "FS",
        "SS",
    }
)


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
            }
            if self.bid_aggressive is not None
            else None,
        }


def _compute_faab_bid(
    candidate_value: float,
    *,
    league_budget: int = 100,
    top_value_in_pool: float | None = None,
    anchors: Any = None,
    league: Any = None,
) -> tuple[int, int, int]:
    """Return (aggressive, reasonable, lowball) FAAB bids.

    Thin back-compat shim over ``src.trade.faab_engine``.  The formula
    this used to hold — ``0.05 + 0.25 x (value / best value on the
    wire)`` of the budget — had no absolute value scale at all: the
    top player on the wire always scored ``share == 1.0`` and so always
    priced at 30% / 21% / 10% of the budget whether he graded 9999 or
    900.  On the real 2026-08-04 board that made a deep-league TE3
    (value 1908) a $21-of-$100 claim, and it made a BARREN wire bid
    MORE because a weaker field lowered the denominator.

    Values now come from the engine's objective ceiling, which is
    pinned to league-format anchors instead of to whoever happens to
    be available.  ``top_value_in_pool`` is accepted and ignored; it
    is retained only so existing callers keep working.
    """
    if candidate_value <= 0 or league_budget <= 0:
        return (0, 0, 0)

    from src.trade import faab_engine as _engine  # noqa: PLC0415 — avoid import cycle

    league_ctx = league or _engine.LeagueContext(original_budget=int(league_budget))
    if anchors is None:
        # No board context: fall back to the configured format priors
        # rather than inventing a pool-relative scale.
        cfg = _engine.FaabConfig()
        anchors = _engine.Anchors(
            v_allin=cfg.num("anchors", "fallbackAllinValue", 2400),
            v_repl=cfg.num("anchors", "fallbackReplacementValue", 1400),
            band=max(
                1.0,
                cfg.num("anchors", "fallbackAllinValue", 2400)
                - cfg.num("anchors", "fallbackReplacementValue", 1400),
            ),
            starter_slots=int(league_ctx.team_count) * int(league_ctx.starters_per_team),
            source="fallback",
        )

    displayed, _raw = _engine.objective_ceiling(float(candidate_value), anchors)
    budget = max(1, int(league_budget))
    aggressive = int(round(displayed * budget))
    reasonable = int(round(aggressive * 0.70))
    lowball = int(round(aggressive * 0.35))
    return (aggressive, reasonable, lowball)


def _normalize_name(name: str) -> str:
    """Loose trim+lowercase roster-ownership key.

    Family 3 in the ``src/utils/name_clean`` key registry.  Byte-equal
    counterparts, each keying an unrelated domain and therefore
    deliberately NOT hoisted into one shared helper:

      * ``frontend/lib/waiver-logic.js::normalizeName`` — the client
        waiver pool.  This is a real parity pair: the owned/my-roster
        Sets on both sides must key the same way.
      * ``src/api/source_history.py::_norm_name_key`` — rolling
        snapshot log keys (also splits ``"Name::assetClass"``).
      * ``server.py`` FAAB endpoint local ``_norm`` — resolving
        add/drop rows out of ``playersArray``.

    Do NOT swap this for ``name_clean.normalize_player_name``.  The
    strict key strips generational suffixes, so ``"Marvin Harrison
    Jr."`` (Sleeper) would newly collide with ``"Marvin Harrison"``
    (contract) and any future ``"Kenneth Walker"`` would collapse into
    ``"Kenneth Walker III"`` — silently changing which players are
    filtered out of the waiver add pool.
    """
    return str(name or "").strip().lower()


def find_waiver_targets(
    contract: dict[str, Any],
    sleeper_teams: list[dict[str, Any]] | None,
    *,
    min_value: int = MIN_WAIVER_VALUE,
    per_position_limit: int = DEFAULT_PER_POSITION_LIMIT,
    include_kicker_def: bool = False,
    user_faab_remaining: int | None = None,
    league_budget: int | None = None,
    team_count: int | None = None,
    starters_per_team: int | None = None,
) -> dict[str, Any]:
    """Return waiver-wire suggestions grouped by position.

    ``league_budget`` is the league's ORIGINAL full-season FAAB
    allowance and sets the scale every bid is expressed against.
    ``user_faab_remaining`` is the selected team's current balance and
    acts only as a CAP.  They are different quantities and must not be
    passed interchangeably.
    """
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

        # Two-source minimum.  A player backed by a single ranking
        # source has no corroboration — these produced the "weird"
        # waiver suggestions whose value rested on one list.  Never
        # surface them as a pickup regardless of position.  ``sourceCount``
        # is the matched-source count stamped by the canonical pipeline.
        try:
            source_count = int(row.get("sourceCount") or 0)
        except (TypeError, ValueError):
            source_count = 0
        if source_count < 2:
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

    # The bid scale is the league's ORIGINAL budget, never the user's
    # remaining balance.  Passing ``user_faab_remaining`` as
    # ``league_budget`` (which this did until the FAAB engine landed)
    # made a player's "objective" worth shrink purely because the
    # manager had already spent — the same player was worth $21 in
    # week 1 and $4 in week 10 with no change in the player.  The
    # remaining balance is a CAP applied afterwards, not the scale.
    from src.trade import faab_engine as _engine  # noqa: PLC0415

    budget = int(league_budget or 0)
    if budget <= 0:
        budget = _engine.FaabConfig().num("leagueRules", "defaultBudget", 100)
        budget = int(budget)

    league_ctx = _engine.LeagueContext(
        original_budget=budget,
        team_count=int(team_count or 12),
        starters_per_team=int(starters_per_team or 20),
    )
    board_values = [
        row.get("rankDerivedValue")
        for row in arr
        if isinstance(row, dict)
        and isinstance(row.get("rankDerivedValue"), (int, float))
        and str(row.get("position") or "").upper()
        not in set(_engine.FaabConfig().get("anchors", "excludedPositions", []) or [])
    ]
    available_values = [c.consensus_value for cs in candidates_by_position.values() for c in cs]
    anchors = _engine.resolve_anchors(
        board_values,
        league_ctx,
        available_values=available_values or None,
    )

    cap = user_faab_remaining if user_faab_remaining is not None else budget
    cap = max(0, int(cap))

    for cs in candidates_by_position.values():
        for c in cs:
            agg, reas, low = _compute_faab_bid(
                c.consensus_value,
                league_budget=budget,
                anchors=anchors,
                league=league_ctx,
            )
            # A recommendation must never exceed what the team has.
            c.bid_aggressive = min(agg, cap)
            c.bid_reasonable = min(reas, cap)
            c.bid_lowball = min(low, cap)

    out_by_position: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for pos, candidates in candidates_by_position.items():
        candidates.sort(key=lambda c: -c.consensus_value)
        capped = candidates[:per_position_limit]
        out_by_position[pos] = [c.to_dict() for c in capped]
        total += len(capped)

    family_map = {
        "DL": "DL",
        "DT": "DL",
        "DE": "DL",
        "EDGE": "DL",
        "NT": "DL",
        "LB": "LB",
        "ILB": "LB",
        "OLB": "LB",
        "MLB": "LB",
        "DB": "DB",
        "CB": "DB",
        "S": "DB",
        "FS": "DB",
        "SS": "DB",
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

        candidates.append(
            (
                float(consensus),
                {
                    "name": name,
                    "position": str(row.get("position") or "").upper(),
                    "consensusValue": int(round(float(consensus))),
                    "adjustedValue": int(round(float(consensus))),  # alias
                    "rank": rank if isinstance(rank, int) else None,
                    "rationale": " · ".join(rationale_parts),
                },
            )
        )

    candidates.sort(key=lambda x: x[0])
    return [c[1] for c in candidates[:limit]]
