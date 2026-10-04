"""Rookie-draft ORDER — the one owner of "which team picks where".

Owner decision 2026-10-04, canonical for ``dynasty_main``
(``config/leagues/draft_order_rules.json``)::

    1. Worst final REGULAR-SEASON record receives the earliest pick.
    2. Teams tied on record: LOWER total regular-season Points For picks
       earlier.
    3. Applied recursively through every tied group.

Not Max PF, not all-play record, not Team Strength rank.  Predictive
evidence (Team Strength, projections, schedule, injuries, the season
simulation) may FORECAST a team's final record and Points For; only this
rule turns a final record + Points For into a draft slot.

Two keys applied recursively is exactly a lexicographic order on
``(wins ascending, pointsFor ascending)``: within a record tie the lower
Points For goes first, and a further tie on Points For is the only thing
left.  That last case — identical record AND identical Points For — is not
covered by the owner rule:

* in a SIMULATION (continuous scores) it is a measure-zero event and is
  broken by the caller's ``rng`` so no identifier decides it (the W19-F008
  lesson from ``playoff_odds.standings_from_sim``);
* for REAL standings it is reported as an unresolved tie, never silently
  ordered.

A league with no recorded rule is UNKNOWN: :func:`league_draft_order_rule`
returns ``None`` and consumers publish no draft-slot forecast.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "REVERSE_RECORD_LOWER_PF",
    "DraftOrder",
    "draft_order",
    "draft_order_from_standings",
    "league_draft_order_rule",
]

REVERSE_RECORD_LOWER_PF = "reverse_record_lower_pf"

_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "leagues" / "draft_order_rules.json"


def league_draft_order_rule(league_key: str | None, *, path: Path | None = None) -> str | None:
    """The league's recorded draft-order rule id, or ``None`` when unknown."""
    if not league_key:
        return None
    try:
        data = json.loads((path or _RULES_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = (data.get("rules") or {}).get(str(league_key))
    rule = entry.get("rule") if isinstance(entry, Mapping) else None
    return rule if rule == REVERSE_RECORD_LOWER_PF else None


@dataclass(frozen=True)
class DraftOrder:
    """Owners in pick order (index 0 = slot 1) plus any unresolved ties."""

    order: tuple[str, ...]
    #: Groups of owners identical on BOTH keys whose relative order the rule
    #: does not decide.  Empty in every simulation (the rng decides there).
    unresolved_ties: tuple[tuple[str, ...], ...] = ()

    def slot_of(self, owner: str) -> int | None:
        try:
            return self.order.index(owner) + 1
        except ValueError:
            return None


def draft_order(
    wins: Mapping[str, float],
    points_for: Mapping[str, float],
    owners: Iterable[str],
    *,
    rng: random.Random | None = None,
) -> DraftOrder:
    """Order ``owners`` by the canonical rule (worst record, then lower PF first).

    ``wins`` may carry half-wins (a tied game counts as half, the standings
    convention).  An owner missing from ``wins`` or ``points_for`` is not
    orderable and is refused rather than placed at 0.
    """
    owners = list(owners)
    missing = [o for o in owners if o not in wins or o not in points_for]
    if missing:
        raise ValueError(f"cannot order owners without a final record and PF: {missing}")

    def key(o: str) -> tuple[float, float]:
        return (float(wins[o]), float(points_for[o]))

    if rng is not None:
        draws = {o: rng.random() for o in owners}
        ordered = sorted(owners, key=lambda o: (*key(o), draws[o]))
        return DraftOrder(order=tuple(ordered))

    ordered = sorted(owners, key=lambda o: (*key(o), o))
    groups: dict[tuple[float, float], list[str]] = {}
    for o in ordered:
        groups.setdefault(key(o), []).append(o)
    unresolved = tuple(tuple(g) for g in groups.values() if len(g) > 1)
    return DraftOrder(order=tuple(ordered), unresolved_ties=unresolved)


def draft_order_from_standings(rows: Iterable[Mapping[str, Any]]) -> DraftOrder:
    """Real final standings rows (``ownerId``, ``wins``, ``ties``, ``pointsFor``)."""
    wins: dict[str, float] = {}
    pf: dict[str, float] = {}
    for r in rows:
        oid = str(r.get("ownerId") or "")
        if not oid:
            continue
        points = r.get("pointsFor")
        if not isinstance(points, (int, float)) or isinstance(points, bool):
            raise ValueError(f"owner {oid} has no final Points For — order is unknown, not 0")
        wins[oid] = float(r.get("wins") or 0) + 0.5 * float(r.get("ties") or 0)
        pf[oid] = float(points)
    return draft_order(wins, pf, list(wins))
