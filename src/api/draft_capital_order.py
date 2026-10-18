"""Draft slots for a draft-capital class from Sleeper standings (Batch E, owner 2026-10-18).

The one owner of "which team picks where" is
``src/public_league/draft_order.py`` (owner decision 2026-10-04,
``reverse_record_lower_pf`` for ``dynasty_main``).  This module only ADAPTS
Sleeper's league + roster objects into that owner's inputs and states how
far the answer can be trusted; it orders nothing itself.

* **Verified final standings** — the league's regular season is over
  (Sleeper ``status`` is ``post_season`` / ``complete``) and every team has
  played exactly the regular season's games (``playoff_week_start -
  start_week`` weeks, doubled when the league also plays the weekly median
  game).  The order is then the rule's order: ``final_standings``.  A real
  tie on record AND Points For is not decided by the rule, so it is never
  called final — it stays a labelled projection with the tie named.
* **Standings to date** — mid-season, the same rule applied to the current
  record and Points For is a FORECAST of the final order (the draft-order
  owner allows predictive evidence to forecast record and PF; only the rule
  turns them into slots).  Labelled ``projected``.
* Anything else — no recorded rule, a class these standings do not decide, a
  team without a record, no game played yet — answers ``None`` and the caller
  keeps its existing labelled order.  Missing is never zero: a roster without
  a record is not placed as 0-0.

The ``playoff_sim`` slot distribution is NOT used here: it is a season
simulation, not something the draft-capital request already has, and the
board's slot dollars need one order, not a distribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from src.public_league import draft_order as _draft_order

__all__ = [
    "ORDER_FINAL_STANDINGS",
    "ORDER_STANDINGS_TO_DATE",
    "ClassSlotOrder",
    "class_slot_order",
    "regular_season_final",
    "sleeper_standings_rows",
]

ORDER_FINAL_STANDINGS = "final_standings"
ORDER_STANDINGS_TO_DATE = "standings_to_date"
_FINAL_STATUSES = frozenset({"post_season", "complete"})


@dataclass(frozen=True)
class ClassSlotOrder:
    """Slots for one class: ``slot_by_roster`` (1 = first pick)."""

    class_year: int
    basis: str  # ORDER_FINAL_STANDINGS / ORDER_STANDINGS_TO_DATE
    rule: str
    slot_by_roster: Mapping[int, int]
    final: bool
    reason: str
    unresolved_ties: tuple[tuple[int, ...], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classYear": self.class_year,
            "basis": self.basis,
            "rule": self.rule,
            "final": self.final,
            "reason": self.reason,
            "unresolvedTies": [list(t) for t in self.unresolved_ties],
        }


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sleeper_standings_rows(
    rosters: Iterable[Mapping[str, Any]], roster_ids: Iterable[int] | None = None
) -> list[dict[str, Any]] | None:
    """Sleeper rosters → the draft-order owner's standings rows.

    ``ownerId`` is the roster id (as a string — the owner's row key).  Points
    For is ``fpts + fpts_decimal / 100``, the same reading the board's other
    standings code uses.  ``None`` when any requested roster lacks a record
    (its order is unknown, never 0-0).
    """
    wanted = {int(r) for r in roster_ids} if roster_ids is not None else None
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for r in rosters or ():
        if not isinstance(r, Mapping):
            continue
        rid = _int(r.get("roster_id"))
        if rid is None or (wanted is not None and rid not in wanted):
            continue
        s = r.get("settings") if isinstance(r.get("settings"), Mapping) else {}
        wins, losses, ties = _int(s.get("wins")), _int(s.get("losses")), _int(s.get("ties"))
        fpts, fpts_dec = _int(s.get("fpts")), _int(s.get("fpts_decimal") or 0)
        if wins is None or losses is None or ties is None or fpts is None or fpts_dec is None:
            return None
        rows.append(
            {
                "ownerId": str(rid),
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "pointsFor": fpts + fpts_dec / 100,
            }
        )
        seen.add(rid)
    if wanted is not None and seen != wanted:
        return None
    return rows


def regular_season_final(
    league_meta: Mapping[str, Any] | None, rows: list[Mapping[str, Any]]
) -> tuple[bool, str]:
    """``(True, reason)`` only when the regular season is provably over."""
    if not isinstance(league_meta, Mapping):
        return False, "league_meta_unavailable"
    status = league_meta.get("status")
    if status not in _FINAL_STATUSES:
        return False, f"league_status:{status}"
    settings = (
        league_meta.get("settings") if isinstance(league_meta.get("settings"), Mapping) else {}
    )
    playoff_start = _int(settings.get("playoff_week_start"))
    start_week = _int(settings.get("start_week")) or 1
    if playoff_start is None or playoff_start <= start_week:
        return False, "regular_season_length_unknown"
    games_per_week = 2 if _int(settings.get("league_average_match")) == 1 else 1
    expected = (playoff_start - start_week) * games_per_week
    short = [
        r["ownerId"] for r in rows if int(r["wins"]) + int(r["losses"]) + int(r["ties"]) != expected
    ]
    if short:
        return False, f"records_not_final:expected_{expected}_games:{','.join(short)}"
    return True, f"regular_season_complete:{expected}_games"


def class_slot_order(
    *,
    league_key: str | None,
    league_meta: Mapping[str, Any] | None,
    rosters: Iterable[Mapping[str, Any]] | None,
    class_year: int,
    roster_ids: Iterable[int],
) -> ClassSlotOrder | None:
    """Slots for ``class_year`` from these standings, or ``None`` (see module doc)."""
    rule = _draft_order.league_draft_order_rule(league_key)
    if rule != _draft_order.REVERSE_RECORD_LOWER_PF:
        return None
    season = _int((league_meta or {}).get("season")) if isinstance(league_meta, Mapping) else None
    # A season's standings decide the NEXT rookie class only.
    if season is None or int(class_year) != season + 1:
        return None
    ids = sorted({int(r) for r in roster_ids})
    if not ids:
        return None
    rows = sleeper_standings_rows(rosters or (), ids)
    if not rows:
        return None
    if all(int(r["wins"]) + int(r["losses"]) + int(r["ties"]) == 0 for r in rows) and all(
        float(r["pointsFor"]) == 0 for r in rows
    ):
        return None  # no game played: there are no standings to order yet
    try:
        order = _draft_order.draft_order_from_standings(rows)
    except ValueError:
        return None
    final, reason = regular_season_final(league_meta, rows)
    ties = tuple(tuple(int(o) for o in group) for group in order.unresolved_ties)
    if final and ties:
        final, reason = False, "final_standings_tied_on_record_and_points_for"
    return ClassSlotOrder(
        class_year=int(class_year),
        basis=ORDER_FINAL_STANDINGS if final else ORDER_STANDINGS_TO_DATE,
        rule=rule,
        slot_by_roster={int(o): i for i, o in enumerate(order.order, start=1)},
        final=final,
        reason=reason,
        unresolved_ties=ties,
    )
