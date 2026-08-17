"""BDVM roster analysis + double-positive trade scan (prompt §10–11 slice).

Consumes a completed BDVM valuation payload plus the contract's Sleeper
teams block and produces, per roster: strategy capitals (the three
currencies + risk-neutral), now/future ratio, quick starter FPG,
positional surplus vs. replacement, value-weighted age, pick capital,
and a contend/retool/rebuild direction.

The trade scan searches 1-for-1 / 2-for-1 / 1-for-2 packages that are
**double-positive**: each side gains under ITS OWN strategy currency
(CES-packaged, roster-spot aware), gated by external market fairness.
Market fairness is only computed on a single market's prices (KTC for
offense+picks, IDPTC for IDP); a side that mixes markets is gated on
BDVM trade-clearing values instead and labeled so — raw KTC and IDPTC
numbers are never summed together (§3.12).

Scope note: ``starterFpg`` here is BDVM's own currency (projected fantasy
points per game), but the LINEUP behind it is no longer BDVM's own —
since C2-U1 it is solved by the canonical owner ``src/ros/lineup.py``,
exactly like every other lineup in the tree.  What stays BDVM-side is
the objective, not the assignment.  The personalized layer (leave-out
marginals) remains ``src/roster_intel`` per ADR-004.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Mapping

from src.bdvm.params import ParamSet
from src.bdvm.trade_math import package_value
from src.ros.lineup import RosterPlayer, assign_lineup

_IDP_GROUPS = frozenset({"DL", "LB", "DB"})

# Scan pruning knobs (documented judgment calls, kept module-level so a
# future parameter-set migration is one move away).
TOP_ASSETS_PER_SIDE = 12
MIN_ASSET_VALUE = 400.0
MIN_GAIN_EACH_SIDE = 150.0
MARKET_FAIRNESS_TOLERANCE_PCT = 12.0
MAX_RESULTS = 40

_CONTEND_RATIO = 1.15
_REBUILD_RATIO = 1.0 / 1.15


def rosters_from_contract(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize the contract's sleeper.teams block."""
    teams = (contract.get("sleeper") or {}).get("teams") or []
    out = []
    for t in teams:
        out.append(
            {
                "name": t.get("name") or t.get("sleeperTeamName") or f"roster_{t.get('roster_id')}",
                "ownerId": str(t.get("ownerId") or ""),
                "rosterId": t.get("roster_id"),
                "playerIds": [str(x) for x in (t.get("playerIds") or [])],
                "playerNames": list(t.get("players") or []),
                "picks": list(t.get("pickDetails") or t.get("picks") or []),
            }
        )
    return out


def _directions_relative(ratios: list[float]) -> list[str]:
    """League-relative contend/retool/rebuild classification.

    The absolute reference rule (ratio vs 1.15) saturates whenever the
    projection pool structurally favors one horizon — with a proxy
    baseline and no priced rookies, EVERY roster's contender capital
    exceeds its rebuilder capital and all twelve rosters would read
    "contend", which is useless.  Strategy inside a league is relative:
    a roster is contending when its now/future ratio is materially above
    the league median (documented judgment call; the absolute ratio is
    still exposed per roster).
    """
    if not ratios:
        return []
    ordered = sorted(ratios)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 == 1 else (ordered[mid - 1] + ordered[mid]) / 2.0
    median = max(1e-9, median)
    out = []
    for ratio in ratios:
        rel = ratio / median
        if rel > _CONTEND_RATIO:
            out.append("contend")
        elif rel < _REBUILD_RATIO:
            out.append("rebuild")
        else:
            out.append("retool")
    return out


def strategy_for_direction(direction: str) -> str:
    return {"contend": "contender", "rebuild": "rebuilder"}.get(direction, "balanced")


def _starter_fpg(
    assets: list[Mapping[str, Any]], starters: Mapping[str, int], flex: Mapping[str, Any]
) -> float:
    """Projected FPG of this roster's best legal lineup.

    Routes through the canonical assignment owner
    (``src/ros/lineup.py``) — C2-U1.  It was ``_quick_starter_fpg``, a
    per-group greedy that filled dedicated slots first and then took the
    best next-available at each flex, and which said so itself
    ("heuristic display number only").  Two things made that wrong
    rather than merely approximate: it could not express a player legal
    at more than one group, and its flex pass is the least-restrictive-
    first order that a greedy is not optimal under.

    The league's OWN flex eligibility is passed through
    ``slot_eligibility``, because ``bdvm/league_config`` reads it from
    the registry (``flexEligible`` / ``sflexEligible`` /
    ``idpFlexEligible``) and it is league config, not a constant.
    """
    slots: list[str] = []
    eligibility: dict[str, tuple[str, ...]] = {}
    for group, need in starters.items():
        slots.extend([str(group).upper()] * max(0, int(need)))
    for slot, spec in (flex or {}).items():
        count, eligible = (
            spec if isinstance(spec, tuple) else (spec.get("count", 0), spec.get("eligible", []))
        )
        slot_u = str(slot).upper()
        slots.extend([slot_u] * max(0, int(count)))
        eligibility[slot_u] = tuple(str(g).upper() for g in eligible)

    pool = [
        RosterPlayer(
            player_id=str(a.get("playerId") or a.get("name") or i),
            canonical_name=str(a.get("name") or ""),
            position=str(a["group"]).upper(),
            # BDVM never emits a priced asset without an fpg, but the
            # distinction is preserved rather than coerced: an absent
            # projection is UNKNOWN, not zero points.
            ros_value=None if a.get("fpg") is None else float(a["fpg"]),
        )
        for i, a in enumerate(assets)
    ]
    return assign_lineup(pool, slots, slot_eligibility=eligibility or None).score


def analyze_rosters(
    valuation_payload: Mapping[str, Any],
    contract: Mapping[str, Any],
    params: ParamSet,
    *,
    league_cfg_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-roster BDVM aggregates.  Returns {rosters: [...], meta: {...}}."""
    players = valuation_payload.get("players") or []
    by_pid = {str(p.get("playerId")): p for p in players}
    replacement = valuation_payload.get("replacement") or {}
    meta_cfg = league_cfg_meta or {}
    starters = {k: int(v) for k, v in (meta_cfg.get("starters") or {}).items()}
    flex = meta_cfg.get("flex") or {}
    strategies = params.strategy_names()

    rosters_out = []
    ratios: list[float] = []
    for roster in rosters_from_contract(contract):
        assets = []
        for pid in roster["playerIds"]:
            p = by_pid.get(pid)
            if p is None:
                continue
            assets.append(
                {
                    "playerId": pid,
                    "name": p["name"],
                    "position": p["position"],
                    "group": p["group"],
                    "fpg": p["projection"]["fpg"],
                    "age": p["raw"]["age"],
                    "tradeValue": p["tradeValue"],
                    "marketValue": (p.get("market") or {}).get("marketValue"),
                    "tradeClearing": (p.get("market") or {}).get("tradeClearing"),
                }
            )
        capitals = {s: sum(a["tradeValue"].get(s, 0.0) for a in assets) for s in strategies}
        now = capitals.get("contender", 0.0)
        future = capitals.get("rebuilder", 0.0)
        total_bal = sum(a["tradeValue"].get("balanced", 0.0) for a in assets)
        weighted_age = (
            sum(a["age"] * a["tradeValue"].get("balanced", 0.0) for a in assets) / total_bal
            if total_bal > 0
            else 0.0
        )
        surplus = {}
        for group, need in starters.items():
            repl_fpg = float((replacement.get(group) or {}).get("replacementFpg") or 0.0)
            have = sum(1 for a in assets if a["group"] == group and a["fpg"] > repl_fpg)
            surplus[group] = have - int(need)
        ratios.append(now / max(1.0, future))
        rosters_out.append(
            {
                "name": roster["name"],
                "ownerId": roster["ownerId"],
                "rosterId": roster["rosterId"],
                "assetCount": len(assets),
                "unmatchedPlayerIds": len(roster["playerIds"]) - len(assets),
                "capitals": {k: round(v, 1) for k, v in capitals.items()},
                "nowFutureRatio": round(now / max(1.0, future), 3),
                "valueWeightedAge": round(weighted_age, 2),
                "starterFpg": round(_starter_fpg(assets, starters, flex), 1),
                "positionalSurplus": surplus,
                "pickCount": len(roster["picks"]),
                "assets": sorted(assets, key=lambda a: -a["tradeValue"].get("balanced", 0.0)),
            }
        )
    for roster_entry, direction in zip(rosters_out, _directions_relative(ratios)):
        roster_entry["direction"] = direction
        roster_entry["strategy"] = strategy_for_direction(direction)
    return {
        "rosters": rosters_out,
        "meta": {
            "starterFpgMethod": "greedy_by_group (authoritative lineup = src/ros/lineup.py)",
            "directionMethod": "now/future ratio relative to league median",
            "directionThresholds": {"contend": _CONTEND_RATIO, "rebuild": round(_REBUILD_RATIO, 3)},
        },
    }


# ---------------------------------------------------------------------------
# Double-positive trade scan
# ---------------------------------------------------------------------------


def _market_side(assets: list[Mapping[str, Any]]) -> tuple[float | None, str]:
    """(market total, basis).  Single-market only; else model clearing.

    Never sums raw KTC and raw IDPTC for one side — a mixed side falls
    back to BDVM tradeClearing values with an explicit basis label.
    """
    groups = {("idp" if a["group"] in _IDP_GROUPS else "off") for a in assets}
    if len(groups) == 1 and all(a.get("marketValue") is not None for a in assets):
        return sum(float(a["marketValue"]) for a in assets), "single_market"
    if all(a.get("tradeClearing") is not None for a in assets):
        return sum(float(a["tradeClearing"]) for a in assets), "model_clearing"
    return None, "unpriced"


def _side_gain(
    gets: list[Mapping[str, Any]],
    gives: list[Mapping[str, Any]],
    strategy: str,
    params: ParamSet,
) -> float:
    get_vals = [a["tradeValue"].get(strategy, 0.0) for a in gets]
    give_vals = [a["tradeValue"].get(strategy, 0.0) for a in gives]
    return package_value(get_vals, params) - package_value(give_vals, params)


def scan_double_positive_trades(
    roster_analysis: Mapping[str, Any],
    params: ParamSet,
    *,
    team: str | None = None,
    max_results: int = MAX_RESULTS,
) -> dict[str, Any]:
    """Find trades that are positive for BOTH sides in their own currency.

    ``team`` filters side A by owner id or roster name (case-insensitive);
    None scans every ordered pair.
    """
    rosters = roster_analysis.get("rosters") or []
    if team is not None:
        team_l = team.lower()
        side_a_rosters = [
            r for r in rosters if r["ownerId"].lower() == team_l or str(r["name"]).lower() == team_l
        ]
        if not side_a_rosters:
            return {"error": "unknown_team", "team": team, "trades": []}
    else:
        side_a_rosters = rosters

    results: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for ra in side_a_rosters:
        a_assets = [
            a for a in ra["assets"] if a["tradeValue"].get("balanced", 0.0) >= MIN_ASSET_VALUE
        ]
        a_assets = a_assets[:TOP_ASSETS_PER_SIDE]
        for rb in rosters:
            if rb is ra or rb["ownerId"] == ra["ownerId"]:
                continue
            b_assets = [
                a for a in rb["assets"] if a["tradeValue"].get("balanced", 0.0) >= MIN_ASSET_VALUE
            ]
            b_assets = b_assets[:TOP_ASSETS_PER_SIDE]
            shapes: list[tuple[list, list]] = []
            shapes += [([x], [y]) for x in a_assets for y in b_assets]
            shapes += [(list(pair), [y]) for pair in combinations(a_assets, 2) for y in b_assets]
            shapes += [([x], list(pair)) for x in a_assets for pair in combinations(b_assets, 2)]
            for gives_a, gets_a in shapes:
                # direction-independent key: A giving X for B's Y is the
                # same trade as B giving Y for A's X
                key = tuple(
                    sorted(
                        (
                            (ra["ownerId"], tuple(sorted(x["playerId"] for x in gives_a))),
                            (rb["ownerId"], tuple(sorted(x["playerId"] for x in gets_a))),
                        )
                    )
                )
                if key in seen:
                    continue
                seen.add(key)
                gain_a = _side_gain(gets_a, gives_a, ra["strategy"], params)
                if gain_a < MIN_GAIN_EACH_SIDE:
                    continue
                gain_b = _side_gain(gives_a, gets_a, rb["strategy"], params)
                if gain_b < MIN_GAIN_EACH_SIDE:
                    continue
                mkt_a, basis_a = _market_side(gives_a)
                mkt_b, basis_b = _market_side(gets_a)
                if mkt_a is None or mkt_b is None:
                    continue
                total = max(1.0, mkt_a + mkt_b)
                fairness_pct = 100.0 * abs(mkt_a - mkt_b) / total
                if fairness_pct > MARKET_FAIRNESS_TOLERANCE_PCT:
                    continue
                results.append(
                    {
                        "from": {
                            "ownerId": ra["ownerId"],
                            "name": ra["name"],
                            "strategy": ra["strategy"],
                            "gives": [x["name"] for x in gives_a],
                            "gain": round(gain_a, 1),
                        },
                        "to": {
                            "ownerId": rb["ownerId"],
                            "name": rb["name"],
                            "strategy": rb["strategy"],
                            "gives": [x["name"] for x in gets_a],
                            "gain": round(gain_b, 1),
                        },
                        "marketFairnessPct": round(fairness_pct, 1),
                        "fairnessBasis": basis_a if basis_a == basis_b else "model_clearing",
                        "doublePositive": True,
                        "minGain": round(min(gain_a, gain_b), 1),
                    }
                )
    results.sort(key=lambda r: -r["minGain"])
    return {
        "trades": results[:max_results],
        "scanned": len(seen),
        "pruning": {
            "topAssetsPerSide": TOP_ASSETS_PER_SIDE,
            "minAssetValue": MIN_ASSET_VALUE,
            "minGainEachSide": MIN_GAIN_EACH_SIDE,
            "marketFairnessTolerancePct": MARKET_FAIRNESS_TOLERANCE_PCT,
        },
    }
