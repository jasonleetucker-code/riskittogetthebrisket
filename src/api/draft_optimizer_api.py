"""Cached adapter between ``server.py`` and the Perfect Draft engine.

Thin by design: the engine (``src/draft/``) stays a pure function of its
inputs, and this layer owns only caching and the payload envelope — the same
split as ``src/api/bdvm_api.py``.

The cache key carries the **team identity**.  That is not an optimization
detail: every number this endpoint returns is specific to one roster, so a key
that omitted the team would serve one manager's cut ladder to another.  It is
the structural guarantee against cross-team leakage, and
``tests/draft/test_roster_context.py`` pins it.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from src.draft.context import build_roster_context, list_draft_teams

__all__ = ["get_draft_teams", "get_roster_context", "reset_cache"]

_lock = threading.Lock()
# One entry per (contract, league, team).  A 12-team league inspected team by
# team through the UI's selector should stay warm, so the cap is comfortably
# above one league's team count rather than a single slot.
_CACHE_MAX = 16
_context_cache: OrderedDict[tuple, dict[str, Any]] = OrderedDict()


def _contract_stamp(contract: Mapping[str, Any] | None) -> tuple:
    """Identity of the contract this payload was built from.

    ``id()`` alone is unsafe — CPython reuses addresses after a refresh frees
    the old contract — so it is paired with the build timestamp, exactly as
    ``bdvm_api`` does.
    """
    if not isinstance(contract, Mapping):
        return (0, None, None)
    return (
        id(contract),
        contract.get("generatedAt"),
        contract.get("scrapeTimestamp"),
    )


def get_draft_teams(contract: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Teams available to the draft optimizer's team selector."""
    return list_draft_teams(contract)


def get_roster_context(
    contract: Mapping[str, Any] | None,
    league_key: str | None,
    *,
    owner_id: str | None = None,
    roster_id: Any = None,
    team_name: str | None = None,
) -> dict[str, Any]:
    """Cached :func:`src.draft.context.build_roster_context`.

    Propagates :class:`ValueError` from the engine (``no_rosters_loaded`` /
    ``unknown_team``) so the route can turn it into a precise error code.
    """
    key = (
        *_contract_stamp(contract),
        str(league_key or ""),
        str(owner_id or ""),
        str(roster_id or ""),
        str(team_name or "").strip().lower(),
    )
    with _lock:
        hit = _context_cache.get(key)
        if hit is not None:
            _context_cache.move_to_end(key)
            return hit

    # Built outside the lock: two concurrent cold requests each build and the
    # second write wins — a wasted build, never a wrong answer, since the build
    # is a pure function of its inputs.  Holding the lock across it would
    # serialise every draft request in the process behind one solve.
    payload = build_roster_context(
        contract,
        league_key,
        owner_id=owner_id,
        roster_id=roster_id,
        team_name=team_name,
    )
    with _lock:
        _context_cache[key] = payload
        _context_cache.move_to_end(key)
        while len(_context_cache) > _CACHE_MAX:
            _context_cache.popitem(last=False)
    return payload


def reset_cache() -> None:
    """Test hook."""
    with _lock:
        _context_cache.clear()
