"""Trade simulator — what-if delta for a proposed trade.

Given the signed-in user's team and a proposed swap
(``playersIn[]`` / ``playersOut[]`` / ``picksIn[]`` / ``picksOut[]``),
return the delta on the usual terminal aggregates:

* ``totalValue`` before / after / delta
* ``tiers`` (elite / high / mid / depth counts) before / after
* ``byPosition`` (per-position value share) before / after
* Per-asset resolution so the caller can render "you gave X value,
  received Y value" breakdowns in the UI
* ``teamStrengthImpact`` — canonical dynasty Top-N roster-core impact,
  deliberately separate from full asset value and weekly starter fit

Design: pure function over the live contract — no side effects, no
persistence. Anyone can simulate anything, the live ``/api/data``
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


_IDP_BASE_POSITIONS = frozenset({"DL", "LB", "DB"})


def _resolve_asset(
    name: str,
    *,
    row_index: dict[str, dict[str, Any]],
    offense_only: bool = False,
) -> dict[str, Any] | None:
    """Resolve a single display name to a summary dict for simulator output.

    Matches ``terminal.py``'s rowValue semantics. When ``offense_only`` is
    True and the row carries a pre-computed ``offenseOnlyRankDerivedValue``
    (set by the IDP-disabled pipeline pre-pass), that value is used instead of
    the full-source ``rankDerivedValue``. This ensures trades involving only
    offense players and picks aren't influenced by IDP source calibration.
    """
    if not name:
        return None
    key = str(name).strip().lower()
    row = row_index.get(key)
    if not row:
        return None
    if offense_only:
        oo = row.get("offenseOnlyRankDerivedValue")
        value = int(oo) if isinstance(oo, (int, float)) and oo > 0 else int(_row_value(row))
    else:
        value = int(_row_value(row))
    pos = _normalize_pos(row.get("pos") or row.get("position"))
    age = row.get("age")
    # ``pos`` collapses DL/LB/DB to "IDP" for terminal aggregation;
    # ``basePos`` preserves the distinction so roster intelligence can apply
    # the product's separate DL/LB/DB Team Strength groups.
    from src.utils.name_clean import normalize_position

    base_pos = normalize_position(row.get("pos") or row.get("position"))
    stable_id = (
        row.get("canonicalPlayerId")
        or row.get("playerId")
        or row.get("sleeperId")
        or row.get("assetId")
        or row.get("id")
    )
    return {
        "canonicalPlayerId": str(stable_id) if stable_id is not None else None,
        "name": row.get("displayName") or row.get("canonicalName") or name,
        "pos": pos,
        "basePos": base_pos or pos,
        "value": value,
        "rank": _row_rank(row),
        "tier": _tier_bucket(value),
        "age": int(age) if isinstance(age, (int, float)) and age else None,
        "assetClass": row.get("assetClass") or ("pick" if pos == "PICK" else "player"),
    }


def _aggregate(assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute totalValue / tiers / byPosition for resolved roster assets."""
    total = 0
    tiers = {"elite": 0, "high": 0, "mid": 0, "depth": 0}
    by_position: dict[str, dict[str, int]] = {g: {"count": 0, "value": 0} for g in POS_GROUPS}
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
                "count": int(after["byPosition"][g]["count"])
                - int(before["byPosition"][g]["count"]),
                "value": int(after["byPosition"][g]["value"])
                - int(before["byPosition"][g]["value"]),
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
    roster_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the simulator payload for a single hypothetical trade.

    ``picks_in`` / ``picks_out`` are treated identically to players for
    portfolio equity, but never occupy a current Team Strength slot. The
    canonical Team Strength comparison is rebuilt from the complete before and
    after roster so replacement cascades are measured rather than subtracting
    the outgoing player's full dynasty value.
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

    # Determine whether any asset in the trade is an IDP player. When the
    # entire trade is offense + picks, use offense-only values that exclude IDP
    # source calibration from the blend. Empty/unresolvable requests retain the
    # full-board baseline for terminal parity.
    all_trade_names = [*players_in, *players_out, *picks_in, *picks_out]
    trade_has_resolved = any(
        row_index.get(n.strip().lower()) is not None for n in all_trade_names if n.strip()
    )
    trade_has_idp = trade_has_resolved and any(
        _normalize_pos(
            (row_index.get(n.strip().lower()) or {}).get("pos")
            or (row_index.get(n.strip().lower()) or {}).get("position")
            or ""
        )
        == "IDP"
        for n in all_trade_names
        if n.strip()
    )
    offense_only = trade_has_resolved and not trade_has_idp

    def _resolve_many(names: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        resolved: list[dict[str, Any]] = []
        missing: list[str] = []
        for n in names:
            hit = _resolve_asset(n, row_index=row_index, offense_only=offense_only)
            if hit is None:
                missing.append(n)
            else:
                resolved.append(hit)
        return resolved, missing

    # BEFORE state: the team's complete current roster + picks, resolved using
    # the exact same canonical row-value semantics as the trade sides.
    before_assets: list[dict[str, Any]] = []
    for name in current_players:
        hit = _resolve_asset(name, row_index=row_index, offense_only=offense_only)
        if hit is not None:
            before_assets.append(hit)
    current_picks = (
        [str(p) for p in (resolved_team.get("picks") or [])]
        if resolved_team and isinstance(resolved_team, dict)
        else []
    )
    for pick in current_picks:
        hit = _resolve_asset(pick, row_index=row_index, offense_only=offense_only)
        if hit is not None:
            before_assets.append(hit)

    receiving, unresolved_in = _resolve_many([*players_in, *picks_in])
    sending, unresolved_out = _resolve_many([*players_out, *picks_out])

    # AFTER state: remove sent assets and add received assets. Keep this
    # simulation deterministic and side-effect free.
    sent_keys = {str(a["name"]).strip().lower() for a in sending}
    after_assets: list[dict[str, Any]] = [
        a for a in before_assets if str(a["name"]).strip().lower() not in sent_keys
    ]
    after_assets.extend(receiving)

    before = _aggregate(before_assets)
    after = _aggregate(after_assets)
    delta = _diff(before, after)

    equity = sum(a["value"] for a in receiving) - sum(a["value"] for a in sending)

    response: dict[str, Any] = {
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

    if resolved_team:
        # Canonical dynasty Top-N roster-core impact. This is intentionally
        # separate from ``teamImpact`` below, which models actual weekly starter
        # shape / competitive-window fit. Keeping both prevents a useful depth
        # asset from being called worthless while still answering whether the
        # transaction changes the meaningful top of THIS roster right now.
        from src.roster_intel.team_strength import compare_team_strength

        response["teamStrengthImpact"] = compare_team_strength(before_assets, after_assets)

    # Existing roster-shape-aware weekly/start-lineup fit verdict. Preserve it
    # as a separate dimension rather than silently changing its semantics.
    if resolved_team and roster_settings:
        from src.trade import team_impact

        impact = team_impact.compute(
            before_assets=before_assets,
            after_assets=after_assets,
            receiving=receiving,
            sending=sending,
            equity=int(equity),
            roster_settings=roster_settings,
        )
        if impact is not None:
            response["teamImpact"] = impact

    return response
