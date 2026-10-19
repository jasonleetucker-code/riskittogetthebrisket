"""The realistic replacement pool: free agents a team could actually claim.

Answers one question for the marginal-utility lane: when a player leaves a
roster, which players could take the vacated spot for free?  Directive §7:
"Do not assume an empty roster spot is always the correct alternative."

Who is in the pool — every rule CONSUMED from its existing owner, none
re-derived here:

* **rostered anywhere** — :func:`src.draft.context.league_rostered_keys` (the
  one definition of "who is rostered", league-wide, ids and names), unioned
  with the caller's ``rostered_ids``.  A player on a rival roster is exactly as
  unavailable as one on yours.
* **in the live rookie auction** — :func:`src.draft.rookie_pool.auction_rookie_keys`.
  A player you have to bid for is not the free alternative to bidding.
* **picks** — never a waiver replacement (same rule as
  ``src.draft.displacement._available_players``).
* **unavailable** — when the caller supplies per-player availability from
  :mod:`src.ros.availability` together with the remaining ``weeks``, a free
  agent the availability owner calls ``unavailable`` in EVERY remaining week is
  excluded.  Partially available players stay in, carrying their per-week map
  so the lineup solve removes them in the weeks they cannot play.

How a candidate is priced: per-game points under the league's EXACT scoring via
:func:`src.roster_intel.best_ball_utility.league_scored_ppg_by_id` (the trade
path's projection basis).  A free agent with no projection is listed in
``unpriced_ids`` — **never a candidate at 0.0**.  Matching uses ``playerId`` and
the three name fields, case-insensitively, mirroring
``board_values_from_contract``.

Known limit, stated in ``basis``: the universe is the contract's
``playersArray``.  A player Sleeper lists but no board row carries is not
offered.  That can only make the pool thinner (the marginal larger), and the
basis names the source so the direction is visible.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

from src.bestball.contracts import WaiverPool
from src.draft.context import league_rostered_keys
from src.draft.rookie_pool import auction_rookie_keys
from src.roster_intel.best_ball_utility import UtilityPlayer, league_scored_ppg_by_id

__all__ = ["waiver_candidates"]

_KEY_FIELDS = ("playerId", "legacyRef", "canonicalName", "displayName")
_UNAVAILABLE = "unavailable"

PpgLookup = Callable[..., tuple[Mapping[str, float], Mapping[str, Any]]]


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _row_keys(row: Mapping[str, Any]) -> set[str]:
    keys = {_norm(row.get(f)) for f in _KEY_FIELDS}
    keys.discard("")
    return keys


def _fantasy_positions(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw = row.get("fantasyPositions")
    if isinstance(raw, (list, tuple)):
        return tuple(str(x) for x in raw if str(x or "").strip())
    return ()


def _unavailable_every_week(states: Mapping[int, str] | None, weeks: Sequence[int]) -> bool:
    if states is None or not weeks:
        return False
    return all(states.get(w) == _UNAVAILABLE for w in weeks)


def waiver_candidates(
    contract: Mapping[str, Any],
    rostered_ids: Collection[str],
    *,
    season: int,
    scoring_settings: Mapping[str, float],
    excluded_ids: Collection[str] = (),
    params: Mapping[str, Any],
    weeks: Sequence[int] | None = None,
    availability_by_id: Mapping[str, Mapping[int, str]] | None = None,
    ppg_lookup: PpgLookup | None = None,
) -> WaiverPool:
    """Priced free agents for one league, best first.

    ``ppg_lookup`` defaults to ``league_scored_ppg_by_id``; tests and the offline
    report inject a fixture lookup with the same signature
    ``(player_ids, *, season, scoring_settings) -> (ppg_by_id, basis)``.
    """
    lookup: PpgLookup = ppg_lookup or league_scored_ppg_by_id
    rule = (
        "playersArray rows on no roster in the league (src.draft.context."
        "league_rostered_keys + caller rostered_ids), minus the live rookie "
        "auction lots (src.draft.rookie_pool), minus picks, minus caller "
        "exclusions, minus players unavailable in every remaining week"
    )
    base_basis: dict[str, Any] = {
        "rule": rule,
        "universe": "contract.playersArray",
        "season": int(season),
        "paramSetId": params.get("paramSetId"),
    }
    rows = contract.get("playersArray") if isinstance(contract, Mapping) else None
    if not isinstance(rows, list):
        return WaiverPool(
            candidates=(),
            unpriced_ids=(),
            excluded_auction_lot_ids=(),
            basis=base_basis,
            state="unavailable",
            reason="contract_players_missing",
        )

    taken = {_norm(x) for x in rostered_ids if _norm(x)} | league_rostered_keys(contract)
    auction_keys = auction_rookie_keys(contract)
    excluded = {_norm(x) for x in excluded_ids if _norm(x)}
    week_list = list(weeks or ())

    free_agents: dict[str, Mapping[str, Any]] = {}
    auction_lots: list[str] = []
    counts = {"rostered": 0, "picks": 0, "noPlayerId": 0, "callerExcluded": 0}
    unavailable_ids: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pos = str(row.get("position") or "").strip().upper()
        if _norm(row.get("assetClass")) == "pick" or not pos or pos == "PICK":
            counts["picks"] += 1
            continue
        keys = _row_keys(row)
        if keys & taken:
            counts["rostered"] += 1
            continue
        pid = str(row.get("playerId") or "").strip()
        if keys & auction_keys:
            if pid:
                auction_lots.append(pid)
            continue
        if keys & excluded:
            counts["callerExcluded"] += 1
            continue
        if not pid:
            # Nothing to price or roster without a Sleeper id.
            counts["noPlayerId"] += 1
            continue
        if availability_by_id is not None and _unavailable_every_week(
            availability_by_id.get(pid), week_list
        ):
            unavailable_ids.append(pid)
            continue
        free_agents.setdefault(pid, row)

    basis = {
        **base_basis,
        "freeAgentRows": len(free_agents),
        "excluded": {
            **counts,
            "auctionLots": len(set(auction_lots)),
            "unavailableEveryWeek": len(unavailable_ids),
        },
        "unavailableEveryWeekIds": sorted(set(unavailable_ids)),
        "availabilityModelled": availability_by_id is not None and bool(week_list),
    }
    lots = tuple(sorted(set(auction_lots)))
    if not free_agents:
        # An observed empty pool: replacement is truthfully none_available.
        return WaiverPool(
            candidates=(),
            unpriced_ids=(),
            excluded_auction_lot_ids=lots,
            basis={**basis, "pricing": None},
            state="available",
            reason="no_free_agents",
        )

    ids = sorted(free_agents)
    ppg_by_id, pricing = lookup(ids, season=int(season), scoring_settings=scoring_settings)
    pricing = dict(pricing or {})
    priced: list[UtilityPlayer] = []
    unpriced: list[str] = []
    for pid in ids:
        ppg = ppg_by_id.get(pid)
        if not isinstance(ppg, (int, float)):
            unpriced.append(pid)
            continue
        row = free_agents[pid]
        name = str(row.get("canonicalName") or row.get("displayName") or pid)
        priced.append(
            UtilityPlayer(
                player_id=pid,
                name=name,
                position=str(row.get("position") or "").strip().upper(),
                ppg=float(ppg),
                fantasy_positions=_fantasy_positions(row),
                availability=None if availability_by_id is None else availability_by_id.get(pid),
            )
        )
    priced.sort(key=lambda p: (-float(p.ppg), p.player_id))  # ppg is set above
    basis = {**basis, "pricing": pricing, "priced": len(priced), "unpriced": len(unpriced)}

    if pricing.get("state") == "unavailable":
        state, reason = "unavailable", f"pricing_unavailable:{pricing.get('reason')}"
    elif not priced:
        # Free agents exist but none is projected: the best replacement is
        # UNKNOWN, which must not read as "none available".
        state, reason = "unavailable", "no_free_agent_projected"
    else:
        state, reason = "available", None
    return WaiverPool(
        candidates=tuple(priced) if state == "available" else (),
        unpriced_ids=tuple(unpriced) if state == "available" else tuple(ids),
        excluded_auction_lot_ids=lots,
        basis=basis,
        state=state,
        reason=reason,
    )
