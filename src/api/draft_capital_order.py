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
  team without a complete record, no game played yet — answers
  ``unavailable`` with the reason named, and the caller keeps its existing
  labelled (``projected``) order.  Missing is never zero: a roster without a
  record is not placed as 0-0, and an unknown regular-season length is never
  defaulted, so "final" is simply not claimed.

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
    "ORDER_UNAVAILABLE",
    "ClassSlotOrder",
    "class_slot_order",
    "regular_season_final",
    "sleeper_standings_rows",
]

ORDER_FINAL_STANDINGS = "final_standings"
ORDER_STANDINGS_TO_DATE = "standings_to_date"
#: No order could be derived from these standings; ``reason`` names why and
#: the caller keeps its existing (projected) order.
ORDER_UNAVAILABLE = "unavailable"
_FINAL_STATUSES = frozenset({"post_season", "complete"})
#: Every field a standings row needs.  A missing one makes the order UNKNOWN —
#: never 0 wins, never 0 Points For.
_RECORD_FIELDS = ("wins", "losses", "ties", "fpts", "fpts_decimal")


@dataclass(frozen=True)
class ClassSlotOrder:
    """Slots for one class: ``slot_by_roster`` (1 = first pick), or ``None``
    with ``basis == "unavailable"`` and the reason named."""

    class_year: int
    basis: str  # ORDER_FINAL_STANDINGS / ORDER_STANDINGS_TO_DATE / ORDER_UNAVAILABLE
    rule: str | None
    slot_by_roster: Mapping[int, int] | None
    final: bool
    reason: str
    unresolved_ties: tuple[tuple[int, ...], ...] = field(default_factory=tuple)

    @property
    def ordered(self) -> bool:
        return self.slot_by_roster is not None

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
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Sleeper rosters → ``(the draft-order owner's standings rows, None)``,
    or ``(None, reason)``.

    ``ownerId`` is the roster id (as a string — the owner's row key).  Points
    For is ``fpts + fpts_decimal / 100``, the same reading the board's other
    standings code uses.  A requested roster that is absent, or lacks ANY of
    ``wins`` / ``losses`` / ``ties`` / ``fpts`` / ``fpts_decimal``, makes the
    standings unverifiable: the reason names the roster and the fields, and no
    value is ever taken as 0.
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
        values = {k: _int(s.get(k)) for k in _RECORD_FIELDS}
        missing = [k for k, v in values.items() if v is None]
        if missing:
            return None, f"standings_record_missing:roster_{rid}:{','.join(missing)}"
        rows.append(
            {
                "ownerId": str(rid),
                "wins": values["wins"],
                "losses": values["losses"],
                "ties": values["ties"],
                "pointsFor": values["fpts"] + values["fpts_decimal"] / 100,
            }
        )
        seen.add(rid)
    if wanted is not None and seen != wanted:
        absent = ",".join(str(x) for x in sorted(wanted - seen))
        return None, f"standings_roster_missing:{absent}"
    if not rows:
        return None, "standings_no_rosters"
    return rows, None


def regular_season_final(
    league_meta: Mapping[str, Any] | None, rows: list[Mapping[str, Any]]
) -> tuple[bool, str]:
    """``(True, reason)`` only when the regular season is provably over.

    The regular-season game count comes from ``playoff_week_start``,
    ``start_week`` and ``league_average_match`` (a weekly median game doubles
    it).  Any of them missing means the count is unknown, so "final" cannot be
    verified — never a default week or a default single game.
    """
    if not isinstance(league_meta, Mapping):
        return False, "league_meta_unavailable"
    status = league_meta.get("status")
    if status not in _FINAL_STATUSES:
        return False, f"league_status:{status}"
    settings = (
        league_meta.get("settings") if isinstance(league_meta.get("settings"), Mapping) else {}
    )
    playoff_start = _int(settings.get("playoff_week_start"))
    start_week = _int(settings.get("start_week"))
    median_game = _int(settings.get("league_average_match"))
    missing = [
        k
        for k, v in (
            ("playoff_week_start", playoff_start),
            ("start_week", start_week),
            ("league_average_match", median_game),
        )
        if v is None
    ]
    if missing:
        return False, f"regular_season_length_unknown:{','.join(missing)}"
    if playoff_start <= start_week or median_game not in (0, 1):
        return False, "regular_season_length_unknown:inconsistent_settings"
    expected = (playoff_start - start_week) * (2 if median_game == 1 else 1)
    short = [
        r["ownerId"] for r in rows if int(r["wins"]) + int(r["losses"]) + int(r["ties"]) != expected
    ]
    if short:
        return False, f"records_not_final:expected_{expected}_games:{','.join(short)}"
    return True, f"regular_season_complete:{expected}_games"


def _unavailable(class_year: int, rule: str | None, reason: str) -> ClassSlotOrder:
    return ClassSlotOrder(
        class_year=int(class_year),
        basis=ORDER_UNAVAILABLE,
        rule=rule,
        slot_by_roster=None,
        final=False,
        reason=reason,
    )


def class_slot_order(
    *,
    league_key: str | None,
    league_meta: Mapping[str, Any] | None,
    rosters: Iterable[Mapping[str, Any]] | None,
    class_year: int,
    roster_ids: Iterable[int],
) -> ClassSlotOrder:
    """Slots for ``class_year`` from these standings — or ``unavailable`` with
    the reason (see module doc).  Never ``None``: "why there is no order" is
    part of the answer."""
    rule = _draft_order.league_draft_order_rule(league_key)
    if rule != _draft_order.REVERSE_RECORD_LOWER_PF:
        return _unavailable(class_year, rule, f"no_recorded_draft_order_rule:{league_key}")
    season = _int((league_meta or {}).get("season")) if isinstance(league_meta, Mapping) else None
    if season is None:
        return _unavailable(class_year, rule, "league_season_unknown")
    # A season's standings decide the NEXT rookie class only.
    if int(class_year) != season + 1:
        return _unavailable(
            class_year, rule, f"standings_of_{season}_do_not_decide_class_{int(class_year)}"
        )
    ids = sorted({int(r) for r in roster_ids})
    if not ids:
        return _unavailable(class_year, rule, "no_rosters_to_order")
    rows, missing_reason = sleeper_standings_rows(rosters or (), ids)
    if rows is None:
        return _unavailable(class_year, rule, str(missing_reason))
    if all(int(r["wins"]) + int(r["losses"]) + int(r["ties"]) == 0 for r in rows) and all(
        float(r["pointsFor"]) == 0 for r in rows
    ):
        return _unavailable(class_year, rule, "no_games_played")
    try:
        order = _draft_order.draft_order_from_standings(rows)
    except ValueError as exc:
        return _unavailable(class_year, rule, f"standings_invalid:{exc}")
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
