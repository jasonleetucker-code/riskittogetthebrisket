"""Canonical dynasty Team Strength over the meaningful top of a roster.

This is intentionally different from ``src.ros.team_strength`` and from the
weekly-starter fit model in ``src.trade.team_impact``:

* ROS strength answers how strong the optimal/best-ball lineup projects now.
* trade team impact answers how a move fits the league's actual starter shape.
* THIS module answers the product's canonical dynasty Team Strength question:
  how much league-adjusted dynasty value is concentrated in the meaningful
  upper portion of the roster.

The fixed portfolio limits are product semantics, not league starter counts:
QB 3, RB 3, WR 5, TE 3, DL 5, LB 5, DB 5.  Recomputing the Top-N groups before
and after a transaction naturally implements replacement cascades: if WR3 is
sent, the old WR6 can be promoted into the Top-5; if a received WR becomes WR7,
he retains full asset value but contributes zero *immediate* Team Strength.

Pure computation. No I/O, no network, no clock, and critically no mutation of
canonical player value. Missing values are reported and excluded; they are
never silently coerced to observed zero.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

TOP_N_LIMITS: dict[str, int] = {
    "QB": 3,
    "RB": 3,
    "WR": 5,
    "TE": 3,
    "DL": 5,
    "LB": 5,
    "DB": 5,
}

_BASE_POSITIONS = frozenset(TOP_N_LIMITS)


def _position(asset: Mapping[str, Any]) -> str:
    """Return the canonical base position carried by resolved roster assets."""
    raw = asset.get("basePos") or asset.get("position") or asset.get("pos") or ""
    pos = str(raw).strip().upper()
    # Some callers collapse defensive positions to IDP in ``pos`` but carry the
    # real slot in ``basePos``.  A bare IDP token is deliberately not guessed.
    return pos if pos in _BASE_POSITIONS else ""


def _value(asset: Mapping[str, Any]) -> float | None:
    """Observed dynasty value, preserving missing-vs-zero semantics."""
    raw = asset.get("value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _asset_key(asset: Mapping[str, Any]) -> str:
    """Stable-enough identity for before/after movement reporting.

    Resolved trade assets do not yet guarantee one canonical id field across
    every producer. Prefer stable ids when present and only then fall back to a
    normalized display name. This keeps the comparison ready for the canonical
    identity migration without breaking today's contract.
    """
    for field in ("canonicalPlayerId", "playerId", "sleeperId", "assetId", "id"):
        raw = asset.get(field)
        if raw is not None and str(raw).strip():
            return f"id:{str(raw).strip()}"
    name = str(asset.get("name") or asset.get("canonicalName") or "").strip().casefold()
    return f"name:{name}"


def _member(asset: Mapping[str, Any], *, roster_rank: int) -> dict[str, Any]:
    value = _value(asset)
    assert value is not None  # only called for priced assets
    return {
        "key": _asset_key(asset),
        "name": asset.get("name") or asset.get("canonicalName"),
        "position": _position(asset),
        "value": int(value) if value.is_integer() else round(value, 3),
        "overallRank": asset.get("rank"),
        "rosterPositionRank": roster_rank,
    }


def build_team_strength(assets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build the canonical Top-N Team Strength snapshot for one roster.

    Draft picks and non-player assets never occupy a Team Strength slot. Assets
    at recognized positions with missing values are retained in diagnostic
    coverage instead of being counted as zero.
    """
    priced_by_pos: dict[str, list[Mapping[str, Any]]] = {p: [] for p in TOP_N_LIMITS}
    missing_by_pos: dict[str, list[dict[str, Any]]] = {p: [] for p in TOP_N_LIMITS}

    for asset in assets:
        if str(asset.get("assetClass") or "player").strip().lower() == "pick":
            continue
        pos = _position(asset)
        if not pos:
            continue
        value = _value(asset)
        if value is None:
            missing_by_pos[pos].append(
                {
                    "key": _asset_key(asset),
                    "name": asset.get("name") or asset.get("canonicalName"),
                    "position": pos,
                    "reason": "missing_value",
                }
            )
            continue
        priced_by_pos[pos].append(asset)

    positions: dict[str, dict[str, Any]] = {}
    total_value = 0.0
    all_missing: list[dict[str, Any]] = []

    for pos, limit in TOP_N_LIMITS.items():
        ordered = sorted(
            priced_by_pos[pos],
            key=lambda a: (
                -float(_value(a) or 0.0),
                int(a.get("rank")) if isinstance(a.get("rank"), int) else 10**9,
                str(a.get("name") or a.get("canonicalName") or "").casefold(),
            ),
        )
        ranked = [_member(asset, roster_rank=i) for i, asset in enumerate(ordered, start=1)]
        core = ranked[:limit]
        depth = ranked[limit:]
        pos_value = sum(float(member["value"]) for member in core)
        total_value += pos_value
        missing = missing_by_pos[pos]
        all_missing.extend(missing)
        positions[pos] = {
            "limit": limit,
            "eligibleCount": len(ranked),
            "coreCount": len(core),
            "coreValue": int(pos_value) if pos_value.is_integer() else round(pos_value, 3),
            "core": core,
            # Depth is useful for replacement-cascade explainability and rosters
            # are small enough that retaining it here is not a payload problem.
            "depth": depth,
            "missingValueCount": len(missing),
            "missingValueAssets": missing,
        }

    return {
        "methodology": "dynasty_top_n_v1",
        "limits": dict(TOP_N_LIMITS),
        "totalValue": int(total_value) if total_value.is_integer() else round(total_value, 3),
        "positions": positions,
        "missingValueCount": len(all_missing),
        "missingValueAssets": all_missing,
        "semantics": {
            "totalValue": "sum of league-adjusted dynasty value inside canonical Top-N position groups",
            "missingValue": "excluded and reported; never coerced to observed zero",
            "draftPicks": "retain asset value elsewhere but contribute zero current Team Strength",
        },
    }


def _pct_change(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return round(100.0 * (after - before) / before, 2)


def compare_team_strength(
    before_assets: Sequence[Mapping[str, Any]],
    after_assets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare Top-N strength before/after and explain the roster cascade."""
    before = build_team_strength(before_assets)
    after = build_team_strength(after_assets)

    before_all = {_asset_key(a): a for a in before_assets if _position(a)}
    after_all = {_asset_key(a): a for a in after_assets if _position(a)}

    positional_delta: dict[str, dict[str, Any]] = {}
    entered: list[dict[str, Any]] = []
    exited: list[dict[str, Any]] = []

    for pos in TOP_N_LIMITS:
        b = before["positions"][pos]
        a = after["positions"][pos]
        b_value = float(b["coreValue"])
        a_value = float(a["coreValue"])
        b_core = {member["key"]: member for member in b["core"]}
        a_core = {member["key"]: member for member in a["core"]}

        position_entered: list[dict[str, Any]] = []
        for key in a_core.keys() - b_core.keys():
            member = dict(a_core[key])
            member["movement"] = "received_into_core" if key not in before_all else "promoted_from_depth"
            position_entered.append(member)
            entered.append(member)

        position_exited: list[dict[str, Any]] = []
        for key in b_core.keys() - a_core.keys():
            member = dict(b_core[key])
            member["movement"] = "sent_from_core" if key not in after_all else "bumped_to_depth"
            position_exited.append(member)
            exited.append(member)

        delta = a_value - b_value
        positional_delta[pos] = {
            "beforeValue": int(b_value) if b_value.is_integer() else round(b_value, 3),
            "afterValue": int(a_value) if a_value.is_integer() else round(a_value, 3),
            "delta": int(delta) if delta.is_integer() else round(delta, 3),
            "percentChange": _pct_change(b_value, a_value),
            "enteredCore": sorted(position_entered, key=lambda m: int(m["rosterPositionRank"])),
            "exitedCore": sorted(position_exited, key=lambda m: int(m["rosterPositionRank"])),
        }

    before_total = float(before["totalValue"])
    after_total = float(after["totalValue"])
    total_delta = after_total - before_total

    return {
        "methodology": "dynasty_top_n_v1",
        "before": before,
        "after": after,
        "delta": {
            "totalValue": int(total_delta) if total_delta.is_integer() else round(total_delta, 3),
            "percentChange": _pct_change(before_total, after_total),
            "byPosition": positional_delta,
        },
        "enteredCore": entered,
        "exitedCore": exited,
        "semantics": {
            "assetValueVsStrength": "asset value is unchanged; this reports marginal impact on the canonical Top-N roster core",
            "replacementCascade": "core groups are rebuilt after the transaction, so depth promotions and bumps are explicit",
        },
    }
