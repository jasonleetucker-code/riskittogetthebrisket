"""Sleeper-derived draft-capital fallback for leagues without a
pinned Excel workbook (upgrade item #13).

The workbook path (``_fetch_draft_capital`` in server.py) is pinned
to the default league's rookie pool — League B and any future-added
league get ``501 not_configured_for_league`` today.

This module builds a BACKUP view from pure Sleeper + canonical-
contract data:

* Picks: pulled from Sleeper's `/traded_picks` + `/drafts` for the
  target league.
* Pick values: read from the canonical contract's ``playersArray``
  where ``assetClass == "pick"`` and ``rankDerivedValue`` is
  stamped — so the values are already calibrated by the Hill curve.
* Total budget: scaled to match the default league's workbook total
  (1200) so the bar chart reads the same.

UI labels this view as "Sleeper-derived, flat per-round valuation"
so users know it's the backup path, not the richer workbook
numbers.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
import json as _json
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Matches the workbook's total so the bar chart stays comparable.
_TARGET_TOTAL_BUDGET = 1200
_DEFAULT_TIMEOUT = 15.0


@dataclass(frozen=True)
class SleeperDerivedPick:
    pick: str  # "1.01", "2.07", etc.
    season: int  # this path spans two seasons — disambiguates rows
    round: int
    slot: int
    current_owner: str  # display name
    original_owner: str
    is_traded: bool
    raw_value: float  # canonical 0-9999 rankDerivedValue
    dollar_value: int  # normalized to budget


def _fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "riskit-draft-fallback/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp:
            return _json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        _LOGGER.warning("draft_capital_fallback fetch %s failed: %s", url, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("draft_capital_fallback parse %s failed: %s", url, exc)
        return None


def _normalize_pick_name(season: int, round_num: int, slot: int) -> str:
    return f"{season} Pick {round_num}.{slot:02d}"


def _pick_value_from_contract(
    contract: dict[str, Any],
    season: int,
    round_num: int,
    slot: int,
) -> float:
    """Look up the rankDerivedValue for a specific pick in the
    canonical contract.  Falls back to interpolation / 0."""
    if not isinstance(contract, dict):
        return 0.0
    arr = contract.get("playersArray")
    target_name = _normalize_pick_name(season, round_num, slot)
    # Try exact match first.
    if isinstance(arr, list):
        for p in arr:
            if isinstance(p, dict) and p.get("displayName") == target_name:
                v = p.get("rankDerivedValue")
                if isinstance(v, (int, float)):
                    return float(v)
    # Legacy dict shape.
    players = contract.get("players")
    if isinstance(players, dict) and target_name in players:
        row = players[target_name]
        v = row.get("rankDerivedValue") if isinstance(row, dict) else None
        if isinstance(v, (int, float)):
            return float(v)
    # Fallback: flat per-round value.  Round 1 ≈ 7000, Round 2 ≈ 4000,
    # Round 3 ≈ 2000, Round 4 ≈ 1200.  Generous but monotonic.
    flat = {1: 7000.0, 2: 4000.0, 3: 2000.0, 4: 1200.0, 5: 700.0, 6: 300.0}
    return flat.get(round_num, 100.0)


#: Last-resort round count.  Kept because Sleeper can be unreachable, but it is
#: now a fallback rather than the only value the function ever sees — see
#: ``resolve_draft_rounds``.
DEFAULT_DRAFT_ROUNDS = 4

#: Sleeper's own clamp; a league cannot configure a rookie draft outside it.
MIN_DRAFT_ROUNDS = 1
MAX_DRAFT_ROUNDS = 6


def resolve_draft_rounds(
    sleeper_league_id: str,
    declared: Any = None,
) -> tuple[int, str]:
    """``(rounds, source)`` for a league's rookie draft.

    Order: Sleeper's own draft settings, then whatever the registry declares,
    then the fallback constant.  ``source`` is returned so the payload can say
    which one answered instead of presenting a guess as a fact.

    This exists because the round count was a parameter nobody passed.  The
    caller supplied ``num_teams`` and not ``draft_rounds``, so every non-default
    league was built as a 4-round draft — while the default league runs 6.  That
    is not cosmetic: ``_TARGET_TOTAL_BUDGET`` is normalized across whatever
    picks the loop produces, so a wrong round count silently redistributes the
    entire $1200 across every team's ``auctionDollars``.
    """
    drafts = _fetch_json(f"https://api.sleeper.app/v1/league/{sleeper_league_id}/drafts")
    if isinstance(drafts, list):
        for d in drafts:
            if not isinstance(d, dict):
                continue
            rounds = (d.get("settings") or {}).get("rounds")
            try:
                n = int(rounds)
            except (TypeError, ValueError):
                continue
            if MIN_DRAFT_ROUNDS <= n <= MAX_DRAFT_ROUNDS:
                return n, "sleeper"

    try:
        n = int(declared)
        if MIN_DRAFT_ROUNDS <= n <= MAX_DRAFT_ROUNDS:
            return n, "registry"
    except (TypeError, ValueError):
        pass

    return DEFAULT_DRAFT_ROUNDS, "default"


def build_sleeper_derived(
    sleeper_league_id: str,
    contract: dict[str, Any],
    *,
    current_season: int,
    draft_rounds: int | None = None,
    declared_draft_rounds: Any = None,
    rookies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch owner / pick data from Sleeper and produce a draft-
    capital board.  Returns the same shape as the workbook path so
    the frontend's ``DraftCapitalSection`` can render it verbatim.

    ``contract`` is the in-memory canonical contract (for pick values).

    ``draft_rounds`` pins the count explicitly (tests); leaving it ``None``
    resolves it from Sleeper, then from ``declared_draft_rounds``, then from
    ``DEFAULT_DRAFT_ROUNDS``.

    There is deliberately no ``num_teams`` parameter any more.  It was declared,
    never referenced, and shadowed by ``actual_num_teams`` derived from the
    roster feed — so the caller's carefully-computed value did nothing.  That
    asymmetry is what hid the ``draft_rounds`` bug at the call site: team count
    self-corrected from Sleeper, round count did not, and both looked equally
    wired.

    ``rookies`` staples the rookie board onto the current season's slots, the
    same way the workbook path does.  Passing it is legitimate across leagues
    and is not a leak of one league's data into another: rookie values follow
    the **scoring profile**, not the league key (CLAUDE.md, "Rankings vs league
    context"), and the two live leagues share ``superflex_tep15_ppr1``.  The
    caller is responsible for checking that; omit the argument and the board
    renders exactly as before, with no rookie fields at all.
    """
    rounds_source = "explicit"
    if draft_rounds is None:
        draft_rounds, rounds_source = resolve_draft_rounds(
            sleeper_league_id, declared_draft_rounds
        )
    draft_rounds = max(MIN_DRAFT_ROUNDS, min(MAX_DRAFT_ROUNDS, int(draft_rounds)))

    rosters = _fetch_json(f"https://api.sleeper.app/v1/league/{sleeper_league_id}/rosters")
    users = _fetch_json(f"https://api.sleeper.app/v1/league/{sleeper_league_id}/users")
    traded = (
        _fetch_json(f"https://api.sleeper.app/v1/league/{sleeper_league_id}/traded_picks") or []
    )

    if not rosters or not users:
        return {
            "error": "sleeper_unreachable",
            "message": "Could not fetch rosters / users from Sleeper.",
        }
    if not isinstance(rosters, list) or not isinstance(users, list):
        return {
            "error": "sleeper_unreachable",
            "message": "Unexpected Sleeper response shape.",
        }

    # roster_id → owner display name.
    user_map = {
        str(u.get("user_id")): (
            (u.get("metadata") or {}).get("team_name")
            or u.get("display_name")
            or f"Team {u.get('user_id')}"
        )
        for u in users
        if isinstance(u, dict)
    }
    roster_name_by_id: dict[int, str] = {}
    for r in rosters:
        if not isinstance(r, dict):
            continue
        rid = r.get("roster_id")
        if rid is None:
            continue
        owner_id = str(r.get("owner_id") or "")
        roster_name_by_id[int(rid)] = user_map.get(owner_id, f"Team {rid}")

    actual_num_teams = max(len(rosters), 1)

    # Build traded-pick map: (season, round, original_owner_rid) → new_owner_rid
    traded_map: dict[tuple[int, int, int], int] = {}
    if isinstance(traded, list):
        for t in traded:
            if not isinstance(t, dict):
                continue
            try:
                season = int(t.get("season"))
                round_n = int(t.get("round"))
                original_rid = int(t.get("roster_id"))
                new_rid = int(t.get("owner_id"))
            except (TypeError, ValueError):
                continue
            traded_map[(season, round_n, original_rid)] = new_rid

    # Build picks.  Sleeper doesn't expose per-slot ownership for
    # FUTURE drafts (pick order not set), so we assume reverse
    # standings — which for this view is fine (ordering is not the
    # point, value + ownership is).
    picks: list[SleeperDerivedPick] = []
    for season in (current_season, current_season + 1):
        for round_n in range(1, draft_rounds + 1):
            for slot in range(1, actual_num_teams + 1):
                original_rid = slot  # stand-in: slot N = original owner roster N
                current_rid = traded_map.get((season, round_n, original_rid), original_rid)
                is_traded = current_rid != original_rid
                value = _pick_value_from_contract(contract, season, round_n, slot)
                picks.append(
                    SleeperDerivedPick(
                        pick=f"{round_n}.{slot:02d}",
                        season=season,
                        round=round_n,
                        slot=slot,
                        current_owner=roster_name_by_id.get(current_rid, f"Team {current_rid}"),
                        original_owner=roster_name_by_id.get(original_rid, f"Team {original_rid}"),
                        is_traded=is_traded,
                        raw_value=value,
                        dollar_value=0,  # filled after normalization
                    )
                )

    # Normalize to target total.
    total_raw = sum(p.raw_value for p in picks)
    scale = (_TARGET_TOTAL_BUDGET / total_raw) if total_raw > 0 else 0.0
    dollar_values = [p.raw_value * scale for p in picks]
    # Largest-remainder rounding to hit exactly _TARGET_TOTAL_BUDGET.
    rounded = _round_to_budget(dollar_values, _TARGET_TOTAL_BUDGET)
    picks = [
        SleeperDerivedPick(**{**p.__dict__, "dollar_value": int(dv)})
        for p, dv in zip(picks, rounded)
    ]

    team_totals: dict[str, int] = {}
    for p in picks:
        team_totals[p.current_owner] = team_totals.get(p.current_owner, 0) + p.dollar_value
    # Pad missing teams (owners with no picks).
    for name in roster_name_by_id.values():
        team_totals.setdefault(name, 0)

    return {
        "season": current_season,
        "numTeams": actual_num_teams,
        "draftRounds": draft_rounds,
        # Which source answered.  ``"default"`` means neither Sleeper nor the
        # registry knew, and the board is built on an assumption — worth being
        # able to see, since the round count silently rescales every team's
        # auction dollars.
        "draftRoundsSource": rounds_source,
        "totalBudget": _TARGET_TOTAL_BUDGET,
        # This path builds picks for BOTH the current and next season
        # (see the ``for season in (current_season, current_season + 1)``
        # loop above), so both years are already in ``teamTotals``.
        # Consumers must not also add roster picks for these years.
        "coveredPickYears": [int(current_season), int(current_season) + 1],
        "source": "sleeper_derived",
        "viewLabel": "Sleeper-derived, flat per-round valuation",
        "teamTotals": [
            {"team": t, "auctionDollars": d}
            for t, d in sorted(team_totals.items(), key=lambda kv: -kv[1])
        ],
        "rookieSource": "contract" if rookies else "none",
        "picks": [
            _serialize_pick(p, i, current_season, rookies or [])
            for i, p in enumerate(picks)
        ],
    }


def _serialize_pick(
    p: SleeperDerivedPick,
    index: int,
    current_season: int,
    rookies: list[dict[str, Any]],
) -> dict[str, Any]:
    """One pick row, with the rookie board stapled onto current-season slots.

    ``overallPick`` is emitted because the frontend sorts on it before mapping
    rookies onto slots; without it the whole sync path bailed and fell back to
    a hardcoded rookie list.

    Rookie `i` goes to overall slot `i`, matching the workbook path's rule
    (``server._fetch_draft_capital``).  Only the CURRENT season's slots get one
    — next year's class does not exist yet, and inventing names for it is
    exactly the kind of plausible-looking fiction this repo refuses.
    """
    row: dict[str, Any] = {
        "pick": p.pick,
        "season": p.season,
        "round": p.round,
        "slot": p.slot,
        "overallPick": index + 1,
        "currentOwner": p.current_owner,
        "originalOwner": p.original_owner,
        "isTraded": p.is_traded,
        "isExpansion": False,
        "adjustedDollarValue": p.dollar_value,
        "dollarValue": p.dollar_value,
    }
    if p.season != int(current_season):
        return row
    # Current-season slots are numbered from 1 in the same order they were
    # built, so the index IS the overall slot within this season.
    if index >= len(rookies):
        return row
    r = rookies[index]
    row["rookieName"] = r.get("name")
    row["rookiePos"] = r.get("pos")
    row["rookieKtcValue"] = r.get("dollar")
    row["rookieKtcDollar"] = r.get("ktcDollar")
    row["rookieIdpDollar"] = r.get("idpTradeCalcDollar")
    row["rookieBoardValue"] = r.get("boardValue")
    row["rookieDispersionCV"] = r.get("dispersionCV")
    row["rookieSingleSource"] = r.get("singleSource")
    return row


def _round_to_budget(values: list[float], target_total: int) -> list[int]:
    """Largest-remainder rounding to hit exactly ``target_total``.

    Duplicates the behavior of server.py::_round_to_budget for
    the workbook path — same math, same invariant (∑ = target)."""
    if not values:
        return []
    total = sum(values)
    if total <= 0:
        return [0] * len(values)
    # Scale and floor; distribute remainder by largest fractional part.
    scaled = [v * target_total / total for v in values]
    floors = [int(s) for s in scaled]
    remainder = target_total - sum(floors)
    fractionals = sorted(
        range(len(scaled)),
        key=lambda i: -(scaled[i] - floors[i]),
    )
    out = list(floors)
    for i in fractionals[:remainder]:
        out[i] += 1
    return out
