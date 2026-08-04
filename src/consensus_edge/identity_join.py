"""One join from nflverse ids to board keys, shared by both consumers.

Two Consensus Edge features were dark for the *same* reason, and it was
not a modelling problem:

* ``league_intel.reception_fit`` returns per-player scoring multipliers
  keyed by **GSIS id**
* ``nfl_data.opportunity_stats`` returns targets / carries / red-zone
  work keyed by ``receiver_player_id`` / ``rusher_player_id``, also GSIS

and the board is keyed by **display name**. No join, no components.

The join already exists in pieces and this module only assembles them:
Sleeper's player directory carries ``gsis_id`` alongside ``player_id``,
``src/identity/unified_mapper.py`` already indexes it by both, and
contract rows already carry ``_sleeperId``. So the chain is
``gsis → sleeper → row``, entirely through existing data.

**Why this is its own module.** Both consumers need the identical map. A
second, subtly different join is how a repo ends up with two answers to
"which player is this", and the failure is silent — rows simply stop
matching. One implementation, one set of rules.

**It refuses rather than guessing.** No player directory, or a directory
without GSIS ids (the checked-in stub is exactly that), yields an empty
map and the dependent components report themselves absent. A partial or
fuzzy-matched join would be worse than none: it would apply one player's
usage to another and look entirely normal doing it.
"""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


def load_player_directory() -> dict[str, dict[str, Any]] | None:
    """Sleeper's ``/v1/players/nfl`` dump, from the cache the app keeps.

    Read-only and never fetched here: this runs on a request path, and a
    network call behind a board build is how a page becomes unreliable.
    Production refreshes it through ``src/public_league/snapshot_store``.
    """
    try:
        from src.public_league import snapshot_store  # noqa: PLC0415

        path = snapshot_store.NFL_PLAYERS_PATH
        if not path.exists():
            return None
        import json  # noqa: PLC0415

        directory = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — absence is a state, not a crash
        _LOGGER.debug("player directory unavailable: %s", exc)
        return None
    return directory if isinstance(directory, dict) else None


def sleeper_to_gsis(directory: dict[str, dict[str, Any]] | None) -> dict[str, str]:
    """``{sleeper_id: gsis_id}`` for every entry that carries both."""
    out: dict[str, str] = {}
    for sleeper_id, entry in (directory or {}).items():
        if not isinstance(entry, dict):
            continue
        gsis = str(entry.get("gsis_id") or "").strip()
        if gsis:
            out[str(sleeper_id)] = gsis
    return out


def build_gsis_to_player_key(
    contract: dict[str, Any] | None,
    directory: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str]:
    """``{gsis_id: playerKey}`` for the rows on this board.

    ``playerKey`` is the display name, matching what
    ``fair_value._row_key`` produces, so callers can index straight into
    a board without a second convention.

    Joins on Sleeper id ONLY. Name matching is deliberately not attempted
    as a fallback: a wrong usage or scoring multiplier attached to the
    wrong player is indistinguishable from a right one downstream, and
    the whole point of these components is that a number means what it
    says.

    Returns ``{}`` when the directory is missing or carries no GSIS ids —
    which is the checked-in stub's case, and correctly leaves the
    dependent components dark rather than half-joined.
    """
    if not contract:
        return {}
    directory = directory if directory is not None else load_player_directory()
    by_sleeper = sleeper_to_gsis(directory)
    if not by_sleeper:
        return {}

    out: dict[str, str] = {}
    # The legacy ``players`` dict is where ``_sleeperId`` lives; the
    # contract preserves it verbatim from the raw payload.
    players = contract.get("players")
    if isinstance(players, dict):
        for name, row in players.items():
            sleeper_id = row_sleeper_id(row)
            if not sleeper_id:
                continue
            gsis = by_sleeper.get(sleeper_id)
            if gsis:
                out[gsis] = str(name)

    # playersArray carries the display name the board actually keys on;
    # prefer it where both exist so the join lands on the same string
    # ``fair_value._row_key`` produces.
    for row in contract.get("playersArray") or []:
        sleeper_id = row_sleeper_id(row)
        if not sleeper_id:
            continue
        gsis = by_sleeper.get(sleeper_id)
        key = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        if gsis and key:
            out[gsis] = key

    return out


def row_sleeper_id(row: Any) -> str:
    """The Sleeper id on a contract row, whichever spelling it carries.

    ``playersArray`` rows call it ``playerId``; the legacy ``players``
    dict calls it ``_sleeperId``. Both are the same Sleeper id and both
    are live — the runtime view strips ``playersArray``, so a consumer
    that only knew one spelling would join fine in tests and match zero
    rows in production. One function, both spellings, one place to fix
    if a third appears.
    """
    if not isinstance(row, dict):
        return ""
    for field in ("playerId", "_sleeperId", "sleeperId"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def player_context_index(
    contract: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """``{playerKey: playerctx record}`` for the rows on this board.

    ``data/playerctx/snapshot.json`` is keyed by GSIS id (or a
    ``sleeper:<id>`` fallback for players nflverse has no GSIS id for)
    and ships its own ``sleeperIndex`` mapping Sleeper id → that key, so
    the join is a single lookup per row and needs no name matching at
    all.

    Note this does NOT go through the Sleeper player directory: the
    snapshot's index is built from the same directory at refresh time,
    so consulting it again would only add a way for the two to disagree.
    Absent snapshot → ``{}`` → the opportunity component reports itself
    absent, which is the correct state outside production where
    ``data/`` is gitignored.
    """
    if not contract or not isinstance(snapshot, dict):
        return {}
    players = snapshot.get("players")
    index = snapshot.get("sleeperIndex")
    if not isinstance(players, dict) or not isinstance(index, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for row in contract.get("playersArray") or []:
        sleeper_id = row_sleeper_id(row)
        if not sleeper_id:
            continue
        key = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        if not key:
            continue
        record = players.get(index.get(sleeper_id) or "")
        if isinstance(record, dict):
            out[key] = record
    return out


def coverage(contract: dict[str, Any] | None, join: dict[str, str]) -> dict[str, Any]:
    """How much of the board the join actually reaches.

    Reported so a thin join is visible as a thin join. A component that
    silently matched 12 of 900 players would otherwise look like a
    component that found little to say.
    """
    rows = [r for r in (contract or {}).get("playersArray") or [] if isinstance(r, dict)]
    return {
        "boardRows": len(rows),
        "joinedPlayers": len(join),
        "joinCoverage": (len(join) / len(rows)) if rows else 0.0,
    }
