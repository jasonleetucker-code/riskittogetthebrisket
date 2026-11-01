"""Family (Sleeper DL / LB / DB) and true-position sub-group (CB / S / LB / EDGE / DT).

The sub-group is an evidence label, never imputed: anything the rules below cannot
place is ``UNKNOWN`` and is excluded from sub-group metrics (counted).
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = [
    "CHALLENGER_FAMILIES",
    "CHALLENGER_SUBGROUPS",
    "FAMILIES",
    "SUBGROUPS",
    "UNKNOWN",
    "challenger_family",
    "family_of",
    "subgroup_of",
]

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

#: The preregistered challenger families, in order.
CHALLENGER_FAMILIES = ("CB", "LB_S", "EDGE_DT")

#: ``((challenger family, (sub-groups...)), ...)`` derived from :data:`SUBGROUPS`.
#: This package's own EVALUATION taxonomy (which true-position sub-groups each
#: challenger is scored on).  It is NOT a lineup slot -> eligible-positions map and
#: decides nothing about who may fill a slot; lineup rules live in ``src.ros.lineup``.
CHALLENGER_SUBGROUPS = tuple(
    (fam, tuple(sg for sg in SUBGROUPS if _CHALLENGER[sg] == fam)) for fam in CHALLENGER_FAMILIES
)


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
