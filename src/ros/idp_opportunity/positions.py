"""Family (Sleeper DL / LB / DB) and true-position sub-group (CB / S / LB / EDGE / DT).

The sub-group is an evidence label, never imputed: anything the rules below cannot
place is ``UNKNOWN`` and is excluded from sub-group metrics (counted).
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["FAMILIES", "SUBGROUPS", "UNKNOWN", "challenger_family", "family_of", "subgroup_of"]

FAMILIES = ("DL", "LB", "DB")
SUBGROUPS = ("CB", "S", "LB", "EDGE", "DT")
UNKNOWN = "UNKNOWN"

_PFF = {"ED": "EDGE", "DI": "DT", "LB": "LB", "CB": "CB", "S": "S"}
_NFLVERSE = {
    "DE": "EDGE",
    "EDGE": "EDGE",
    "DT": "DT",
    "NT": "DT",
    "CB": "CB",
    "S": "S",
    "SS": "S",
    "FS": "S",
    "SAF": "S",
    "ILB": "LB",
    "MLB": "LB",
    "LB": "LB",
}

#: Which preregistered challenger family a sub-group belongs to.
_CHALLENGER = {"CB": "CB", "LB": "LB_S", "S": "LB_S", "EDGE": "EDGE_DT", "DT": "EDGE_DT"}


def family_of(sleeper_position: str | None, fantasy_positions: Iterable[str] | None) -> str | None:
    """Sleeper family, or ``None`` for a non-IDP player."""
    pos = (sleeper_position or "").upper()
    if pos in FAMILIES:
        return pos
    fps = [str(p).upper() for p in (fantasy_positions or [])]
    for fam in FAMILIES:
        if fam in fps:
            return fam
    return None


def subgroup_of(family: str, pff_position: str | None, *positions: str | None) -> str:
    """PFF position first, then each further position label in the caller's order
    (nflverse ``position``, nflverse roster ``depth_chart_position``, Sleeper
    ``position``); the first that maps wins.  Nothing maps → ``UNKNOWN``."""
    pff = (pff_position or "").upper()
    if pff in _PFF:
        return _PFF[pff]
    for raw in positions:
        pos = (raw or "").upper()
        if pos == "OLB":
            return "EDGE" if family == "DL" else "LB"
        if pos in _NFLVERSE:
            return _NFLVERSE[pos]
    return UNKNOWN


def challenger_family(subgroup: str) -> str | None:
    return _CHALLENGER.get(subgroup)
