"""Points above replacement on the converted scale (shadow, reported only).

Replacement comes from the canonical owner,
``src.league_intel.replacement.compute_replacement_levels`` — the exact
lineup solver's endogenous allocation over the league's real rosters.  This
module only substitutes the converted value for ``rosValue`` in COPIES of the
roster rows; it keeps no slot table, re-derives no flex split and applies no
scarcity multiplier (a replacement-based measure already prices scarcity, so a
multiplier on top would count it twice).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from src.league_intel.replacement import compute_replacement_levels, normalize_base_position

#: The replacement tier PAR is measured against (preregistration §3).
PAR_TIER = "starter"


def substitute_values(
    teams: Sequence[Mapping[str, Any]],
    value_of: Callable[[Mapping[str, Any]], float | None],
) -> list[dict[str, Any]]:
    """Copies of ``teams`` whose players carry ``value_of(player)`` as ``rosValue``.

    A player ``value_of`` cannot price keeps ``rosValue: 0.0`` in the copy —
    the canonical owner's own convention for "no ROS read" (excluded from its
    level pools) — and is reported by the caller as unpriced, never as a 0-point
    player.
    """
    out: list[dict[str, Any]] = []
    for team in teams:
        players = []
        for p in team.get("players") or []:
            v = value_of(p)
            players.append({**dict(p), "rosValue": float(v) if v is not None and v > 0 else 0.0})
        out.append({**dict(team), "players": players})
    return out


def replacement_points(
    teams: Sequence[Mapping[str, Any]],
    starter_slots: Sequence[str],
) -> dict[str, float | None]:
    """``{base position: starter-tier replacement value}`` on whatever scale
    the rows' ``rosValue`` carries (here: converted points)."""
    levels = compute_replacement_levels(teams, starter_slots)
    return {pos: rep.value(PAR_TIER) for pos, rep in levels.items()}


def par_for(
    position: str | None, value: float | None, replacement: Mapping[str, float | None]
) -> float | None:
    """``value − R(position)``; ``None`` when either side is unknown."""
    if value is None:
        return None
    base = normalize_base_position(str(position or ""))
    r = replacement.get(base)
    if r is None:
        return None
    return float(value) - float(r)


__all__ = ["PAR_TIER", "par_for", "replacement_points", "substitute_values"]
