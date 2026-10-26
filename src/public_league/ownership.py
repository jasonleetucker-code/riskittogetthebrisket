"""Mid-season roster hand-offs — the one owner of "who held this roster in week N".

Sleeper keeps a roster's ``roster_id`` when the roster changes hands, and
``/league/{id}/rosters`` reports only the CURRENT ``owner_id``.  Every
consumer that maps ``(league_id, roster_id)`` to an owner therefore
attributes the whole season to whoever holds the roster at fetch time: a
manager who left mid-season loses their history and their successor
inherits it.

``config/leagues/roster_ownership_changes.json`` records each hand-off by
Sleeper user id (never by name — two managers can share a first name) with
the first week the new owner is responsible for.  :func:`owner_at` answers
the attribution question:

* ``week`` given and before the hand-off → the outgoing owner;
* ``week`` given and on/after it, or ``week`` unknown → the current owner.

Unknown week deliberately means "current owner": a caller that cannot say
which week an event belongs to keeps today's behaviour rather than
guessing history.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.utils.config_loader import load_json, repo_root

_CONFIG = ("config", "leagues", "roster_ownership_changes.json")


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _changes() -> dict[tuple[str, int], tuple[dict[str, Any], ...]]:
    data = load_json(repo_root().joinpath(*_CONFIG), default={}) or {}
    out: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in data.get("changes") or []:
        if not isinstance(row, dict):
            continue
        league_id = str(row.get("leagueId") or "").strip()
        roster_id = _as_int(row.get("rosterId"))
        week = _as_int(row.get("effectiveWeek"))
        from_owner = str(row.get("fromOwnerId") or "").strip()
        to_owner = str(row.get("toOwnerId") or "").strip()
        if not (league_id and roster_id is not None and week and from_owner and to_owner):
            continue
        out.setdefault((league_id, roster_id), []).append(
            {
                "leagueId": league_id,
                "rosterId": roster_id,
                "season": str(row.get("season") or ""),
                "effectiveWeek": week,
                "fromOwnerId": from_owner,
                "fromUsername": str(row.get("fromUsername") or ""),
                "toOwnerId": to_owner,
                "toUsername": str(row.get("toUsername") or ""),
            }
        )
    return {k: tuple(sorted(v, key=lambda c: c["effectiveWeek"])) for k, v in out.items()}


def changes_for(league_id: Any, roster_id: Any) -> tuple[dict[str, Any], ...]:
    rid = _as_int(roster_id)
    if rid is None:
        return ()
    return _changes().get((str(league_id or ""), rid), ())


def all_changes() -> list[dict[str, Any]]:
    return [c for group in _changes().values() for c in group]


def owner_at(league_id: Any, roster_id: Any, current_owner: str, week: Any = None) -> str:
    """The owner responsible for ``roster_id`` in ``week``.

    ``current_owner`` is what Sleeper reports today.  With no recorded
    hand-off, or no week, it is the answer.
    """
    wk = _as_int(week)
    if wk is None:
        return current_owner
    for change in changes_for(league_id, roster_id):
        if wk < change["effectiveWeek"]:
            return change["fromOwnerId"]
    return current_owner


def handed_off_roster(league_id: Any, owner_id: Any) -> int | None:
    """The roster ``owner_id`` handed off mid-season in ``league_id``, or ``None``.

    The outgoing owner of a recorded hand-off is no longer the roster's
    current owner, so a reverse lookup over Sleeper's current ``owner_id``s
    cannot find the roster they held for their own weeks.
    """
    lid = str(league_id or "")
    oid = str(owner_id or "")
    if not (lid and oid):
        return None
    for change in all_changes():
        if change["leagueId"] == lid and change["fromOwnerId"] == oid:
            return change["rosterId"]
    return None
