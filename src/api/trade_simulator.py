"""Trade simulator — what-if delta for a proposed trade.

Given the signed-in user's team and a proposed swap
(``playersIn[]`` / ``playersOut[]`` / ``picksIn[]`` / ``picksOut[]``),
return the delta on the usual terminal aggregates:

* ``totalValue`` before / after / delta
* ``tiers`` (elite / high / mid / depth counts) before / after
* ``byPosition`` (per-position value share) before / after
* Per-asset resolution so the caller can render "you gave X value,
  received Y value" breakdowns in the UI

Design: pure function over the live contract — no side effects, no
persistence.  Anyone can simulate anything, the live ``/api/data``
contract doesn't change.

Uses the same helpers as ``terminal.py`` (``_row_value``,
``_tier_bucket``, ``_normalize_pos``) so the simulator's numbers
exactly match what the terminal panel shows — a user can't end up
staring at a $13 delta in the header and a $147 delta in the
simulator for the same swap.
"""
from __future__ import annotations

from typing import Any

from src.api.terminal import (
    _build_row_index,
    _normalize_pos,
    _players_array,
    _row_rank,
    _row_value,
    _tier_bucket,
    POS_GROUPS,
)


def _resolve_asset(
    name: str,
    *,
    row_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve a single display name to a summary dict for the
    simulator output.  Matches ``terminal.py``'s rowValue semantics.
    """
    if not name:
        return None
    key = str(name).strip().lower()
    row = row_index.get(key)
    if not row:
        return None
    value = int(_row_value(row))
    pos = _normalize_pos(row.get("pos") or row.get("position"))
    return {
        "name": row.get("displayName") or row.get("canonicalName") or name,
        "pos": pos,
        "value": value,
        "rank": _row_rank(row),
        "tier": _tier_bucket(value),
    }


def _aggregate(assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute totalValue / tiers / byPosition for a roster list of
    resolved asset dicts.  Matches the shape ``_compute_portfolio_insights``
    emits so the simulator UI can reuse the same renderers.
    """
    total = 0
    tiers = {"elite": 0, "high": 0, "mid": 0, "depth": 0}
    by_position: dict[str, dict[str, int]] = {
        g: {"count": 0, "value": 0} for g in POS_GROUPS
    }
    for a in assets:
        v = int(a.get("value") or 0)
        total += v
        tiers[_tier_bucket(v)] += 1
        bucket = a.get("pos") if a.get("pos") in POS_GROUPS else None
        if bucket:
            by_position[bucket]["count"] += 1
            by_position[bucket]["value"] += v
    return {
        "totalValue": total,
        "tiers": tiers,
        "byPosition": by_position,
    }


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Pretty-print the aggregate delta for the UI."""
    delta = {
        "totalValue": int(after["totalValue"]) - int(before["totalValue"]),
        "tiers": {
            k: int(after["tiers"].get(k, 0)) - int(before["tiers"].get(k, 0))
            for k in ("elite", "high", "mid", "depth")
        },
        "byPosition": {
            g: {
                "count": int(after["byPosition"][g]["count"]) - int(before["byPosition"][g]["count"]),
                "value": int(after["byPosition"][g]["value"]) - int(before["byPosition"][g]["value"]),
            }
            for g in POS_GROUPS
        },
    }
    return delta


def simulate_trade(
    contract: dict[str, Any],
    *,
    resolved_team: dict[str, Any] | None,
    players_in: list[str] | None = None,
    players_out: list[str] | None = None,
    picks_in: list[str] | None = None,
    picks_out: list[str] | None = None,
) -> dict[str, Any]:
    """Build the simulator payload for a single hypothetical trade.

    Returns::

        {
          "team":          {ownerId, name, rosterId},
          "before":        {totalValue, tiers, byPosition},
          "after":         {totalValue, tiers, byPosition},
          "delta":         {totalValue, tiers, byPosition},
          "receiving":     [{name, pos, value, rank, tier}],  # resolved
          "sending":       [{name, pos, value, rank, tier}],
          "unresolvedIn":  [str, ...],   # names we couldn't match
          "unresolvedOut": [str, ...],
          "equity":        int,          # net value to team (positive = good)
        }

    Never mutates the contract or persists.  Pure function over the
    passed inputs; call repeatedly for different what-ifs.

    ``picks_in`` / ``picks_out`` are treated identically to players —
    the contract's ``players`` dict carries pick rows by their
    canonical display name ("2026 early 1st", etc.) and they resolve
    the same way through ``row_index``.
    """
    players_in = [p for p in (players_in or []) if p]
    players_out = [p for p in (players_out or []) if p]
    picks_in = [p for p in (picks_in or []) if p]
    picks_out = [p for p in (picks_out or []) if p]

    rows = _players_array(contract)
    row_index = _build_row_index(rows)

    team_block = None
    current_players: list[str] = []
    if resolved_team and isinstance(resolved_team, dict):
        team_block = {
            "ownerId": str(resolved_team.get("ownerId") or ""),
            "name": str(resolved_team.get("name") or ""),
            "rosterId": resolved_team.get("roster_id"),
        }
        current_players = [str(p) for p in (resolved_team.get("players") or [])]

    def _resolve_many(names: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        resolved: list[dict[str, Any]] = []
        missing: list[str] = []
        for n in names:
            hit = _resolve_asset(n, row_index=row_index)
            if hit is None:
                missing.append(n)
            else:
                resolved.append(hit)
        return resolved, missing

    # BEFORE state: the team's current roster + picks, resolved.
    before_assets: list[dict[str, Any]] = []
    for name in current_players:
        hit = _resolve_asset(name, row_index=row_index)
        if hit is not None:
            before_assets.append(hit)
    current_picks = (
        [str(p) for p in (resolved_team.get("picks") or [])]
        if resolved_team and isinstance(resolved_team, dict)
        else []
    )
    for pick in current_picks:
        hit = _resolve_asset(pick, row_index=row_index)
        if hit is not None:
            before_assets.append(hit)

    # Receiving / sending sides of the trade.
    receiving, unresolved_in = _resolve_many([*players_in, *picks_in])
    sending, unresolved_out = _resolve_many([*players_out, *picks_out])

    # AFTER state: drop the sent, add the received.  Uses a Set of
    # lowercased names to de-dup in case the same player appears on
    # both the current roster and in the sending list (user error
    # protection).
    sent_keys = {str(a["name"]).strip().lower() for a in sending}
    after_assets: list[dict[str, Any]] = [
        a for a in before_assets if str(a["name"]).strip().lower() not in sent_keys
    ]
    after_assets.extend(receiving)

    before = _aggregate(before_assets)
    after = _aggregate(after_assets)
    delta = _diff(before, after)

    equity = sum(a["value"] for a in receiving) - sum(a["value"] for a in sending)

    return {
        "team": team_block,
        "before": before,
        "after": after,
        "delta": delta,
        "receiving": receiving,
        "sending": sending,
        "unresolvedIn": unresolved_in,
        "unresolvedOut": unresolved_out,
        "equity": int(equity),
    }
