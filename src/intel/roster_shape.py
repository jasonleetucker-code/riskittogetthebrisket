"""Lightweight positional surplus/deficit per team, for lead scoring.

``src/roster_intel/`` produces a far richer roster analysis, but it
needs the full gameplan orchestration.  Insider Trading only needs the
one thing ``partner.RosterSignal`` actually reads — RELATIVE positional
surplus and deficit — so this derives that directly from the contract's
team rosters and the league's starter requirements.

The units deliberately do not matter: ``_need_alignment`` and this
module's consumers use only the relative magnitudes within a roster, so
"starter-quality bodies above/below requirement" is a valid scale
without pretending to be a value.

DEGRADES, NEVER FAILS.  A missing contract, missing positions or missing
starter settings all yield an empty signal, which makes the partner term
abstain rather than making the whole lead list disappear.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from src.roster_intel.partner import RosterSignal
from src.ros.lineup import resolve_starter_slots, slot_demand

log = logging.getLogger(__name__)


def _starter_requirements(roster_settings: Mapping[str, Any] | None) -> dict[str, float]:
    """Effective starters per real position, flex spread evenly.

    Reads the canonical :func:`slot_demand` contract's ``even_split``
    (C2-U1) instead of the local ``_FLEX_ELIGIBLE`` table this module
    used to keep — one of four independent re-derivations of the same
    rule.  The approximation is fine HERE and only here for the reason
    the module docstring already gives: consumers use the relative
    magnitudes within a roster, never the absolute number.
    """
    settings = dict(roster_settings or {})
    slots, _source = resolve_starter_slots(roster_settings=settings)
    return dict(slot_demand(slots).even_split)


def team_signals(
    teams: list[dict[str, Any]] | None,
    position_by_player: Mapping[str, str] | None,
    roster_settings: Mapping[str, Any] | None,
    *,
    value_by_player: Mapping[str, float] | None = None,
    starter_value_floor: float = 0.0,
) -> dict[str, RosterSignal]:
    """``{ownerId: RosterSignal}`` from the contract's sleeper teams.

    A player counts toward a position only if their value clears
    ``starter_value_floor`` — roster clog is not depth, and counting it
    would make every deep bench look like a surplus.
    """
    out: dict[str, RosterSignal] = {}
    if not teams or not position_by_player:
        return out
    req = _starter_requirements(roster_settings)
    if not req:
        return out

    for team in teams:
        if not isinstance(team, dict):
            continue
        owner = str(team.get("ownerId") or "").strip()
        if not owner:
            continue
        counts: dict[str, float] = {}
        for pid in team.get("playerIds") or team.get("players") or []:
            pos = str(position_by_player.get(str(pid)) or "").upper()
            if not pos:
                continue
            if value_by_player is not None and starter_value_floor > 0:
                if float(value_by_player.get(str(pid)) or 0.0) < starter_value_floor:
                    continue
            counts[pos] = counts.get(pos, 0.0) + 1.0

        surplus: dict[str, float] = {}
        deficit: dict[str, float] = {}
        for pos, needed in req.items():
            have = counts.get(pos, 0.0)
            gap = have - needed
            if gap > 0:
                surplus[pos] = gap
            elif gap < 0:
                deficit[pos] = -gap
        out[owner] = RosterSignal(owner_id=owner, surplus=surplus, deficit=deficit)
    return out


def owner_of_player(teams: list[dict[str, Any]] | None, player_id: str) -> str | None:
    """Which manager currently rosters this player in THIS league."""
    for team in teams or []:
        if not isinstance(team, dict):
            continue
        ids = {str(p) for p in (team.get("playerIds") or team.get("players") or [])}
        if str(player_id) in ids:
            owner = str(team.get("ownerId") or "").strip()
            return owner or None
    return None


def matchable_values(
    teams: list[dict[str, Any]] | None,
    value_by_player: Mapping[str, float] | None,
) -> dict[str, list[float]]:
    """``{ownerId: [asset values]}`` — what each manager could pay with."""
    out: dict[str, list[float]] = {}
    if not teams or not value_by_player:
        return out
    for team in teams:
        if not isinstance(team, dict):
            continue
        owner = str(team.get("ownerId") or "").strip()
        if not owner:
            continue
        vals = []
        for pid in team.get("playerIds") or team.get("players") or []:
            v = value_by_player.get(str(pid))
            if v:
                vals.append(float(v))
        out[owner] = vals
    return out
