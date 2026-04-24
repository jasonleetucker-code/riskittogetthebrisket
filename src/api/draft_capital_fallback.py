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
    contract: dict[str, Any], season: int, round_num: int, slot: int,
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


def build_sleeper_derived(
    sleeper_league_id: str,
    contract: dict[str, Any],
    *,
    current_season: int,
    num_teams: int = 12,
    draft_rounds: int = 4,
) -> dict[str, Any]:
    """Fetch owner / pick data from Sleeper and produce a draft-
    capital board.  Returns the same shape as the workbook path so
    the frontend's ``DraftCapitalSection`` can render it verbatim.

    ``contract`` is the in-memory canonical contract (for pick values).
    """
    rosters = _fetch_json(
        f"https://api.sleeper.app/v1/league/{sleeper_league_id}/rosters"
    )
    users = _fetch_json(
        f"https://api.sleeper.app/v1/league/{sleeper_league_id}/users"
    )
    traded = _fetch_json(
        f"https://api.sleeper.app/v1/league/{sleeper_league_id}/traded_picks"
    ) or []

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
        for u in users if isinstance(u, dict)
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
                picks.append(SleeperDerivedPick(
                    pick=f"{round_n}.{slot:02d}",
                    round=round_n,
                    slot=slot,
                    current_owner=roster_name_by_id.get(current_rid, f"Team {current_rid}"),
                    original_owner=roster_name_by_id.get(original_rid, f"Team {original_rid}"),
                    is_traded=is_traded,
                    raw_value=value,
                    dollar_value=0,  # filled after normalization
                ))

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
        "totalBudget": _TARGET_TOTAL_BUDGET,
        "source": "sleeper_derived",
        "viewLabel": "Sleeper-derived, flat per-round valuation",
        "teamTotals": [
            {"team": t, "auctionDollars": d}
            for t, d in sorted(team_totals.items(), key=lambda kv: -kv[1])
        ],
        "picks": [
            {
                "pick": p.pick, "round": p.round, "slot": p.slot,
                "currentOwner": p.current_owner,
                "originalOwner": p.original_owner,
                "isTraded": p.is_traded,
                "isExpansion": False,
                "adjustedDollarValue": p.dollar_value,
                "dollarValue": p.dollar_value,
            }
            for p in picks
        ],
    }


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
