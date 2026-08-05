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

Deliberate scope note: the quick starter fill here is a BDVM-side
heuristic view.  The AUTHORITATIVE personalized layer (exact legal
lineup solve, leave-out marginals) remains ``src/roster_intel`` /
``src/ros/lineup.py`` per ADR-004; feeding BDVM currencies into that
machinery is the UI-facing follow-up.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Mapping

from src.bdvm.params import ParamSet
from src.bdvm.trade_math import package_value

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


def _pick_index(valuation_payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Board pick name -> the valuation payload's priced pick entry."""
    out: dict[str, Mapping[str, Any]] = {}
    for entry in valuation_payload.get("picks") or []:
        name = str(entry.get("name") or "").strip()
        if name:
            out[name] = entry
    return out


def _pick_assets(
    roster_picks: list[Any],
    pick_index: Mapping[str, Mapping[str, Any]],
    pick_aliases: Any,
    strategies: list[str],
) -> tuple[list[dict[str, Any]], int]:
    """Roster pick labels -> priced BDVM assets, plus the unpriced count.

    Sleeper spells a pick "2026 1.04 (own)" or "2027 1st"; the board
    names it "2026 Pick 1.04" or "2027 Mid 1st".  The join goes through
    the shared ``src/utils/pick_labels`` resolver — the Python port of
    the frontend's ``resolvePickRow`` — so this surface joins picks the
    same way every other one does.

    A pick the fundamental board could not price (``distribution:
    None``) is COUNTED and skipped, never valued at zero: a zero inside
    a capital reads as "worth nothing" rather than "not priced".
    """
    from src.utils.pick_labels import resolve_pick_name  # noqa: PLC0415

    assets: list[dict[str, Any]] = []
    unpriced = 0
    for raw in roster_picks or []:
        label = raw.get("label") if isinstance(raw, Mapping) else raw
        name = resolve_pick_name(label, pick_index.keys(), pick_aliases)
        entry = pick_index.get(name) if name else None
        distribution = (entry or {}).get("distribution")
        if not isinstance(distribution, Mapping):
            unpriced += 1
            continue
        trade_value = {}
        for strategy in strategies:
            leg = distribution.get(strategy)
            if isinstance(leg, Mapping) and leg.get("ev") is not None:
                trade_value[strategy] = float(leg["ev"])
        if not trade_value:
            unpriced += 1
            continue
        assets.append(
            {
                # Picks have no Sleeper id.  The board can only tell
                # tiers apart, so the board row name IS the pick's
                # identity here — enough for the scan's dedup key, and
                # honest about what is and is not distinguishable.
                "playerId": f"pick::{name}",
                "name": name,
                "position": "PICK",
                "group": "PICK",
                "fpg": None,
                "age": None,
                "isPick": True,
                "tradeValue": trade_value,
                "marketValue": (entry.get("market") or {}).get("marketValue"),
                "tradeClearing": (entry.get("market") or {}).get("tradeClearing"),
            }
        )
    return assets, unpriced


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


def _quick_starter_fpg(
    assets: list[Mapping[str, Any]], starters: Mapping[str, int], flex: Mapping[str, Any]
) -> float:
    """Greedy starter fill by group on projected FPG.

    Heuristic display number only — the exact solver in src/ros/lineup.py
    is the authoritative lineup path (ADR-004/007).
    """
    by_group: dict[str, list[float]] = {}
    for a in assets:
        by_group.setdefault(a["group"], []).append(float(a["fpg"]))
    for vals in by_group.values():
        vals.sort(reverse=True)
    used: dict[str, int] = {g: 0 for g in by_group}
    total = 0.0
    for group, need in starters.items():
        vals = by_group.get(group, [])
        take = min(int(need), len(vals))
        total += sum(vals[:take])
        used[group] = take
    for _slot, spec in (flex or {}).items():
        count, eligible = (
            spec if isinstance(spec, tuple) else (spec.get("count", 0), spec.get("eligible", []))
        )
        for _ in range(int(count)):
            best_g, best_v = None, 0.0
            for g in eligible:
                vals = by_group.get(g, [])
                idx = used.get(g, 0)
                if idx < len(vals) and vals[idx] > best_v:
                    best_g, best_v = g, vals[idx]
            if best_g is not None:
                total += best_v
                used[best_g] = used.get(best_g, 0) + 1
    return total


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

    pick_index = _pick_index(valuation_payload)
    pick_aliases = contract.get("pickAliases")

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
        # Draft picks are roster capital.  ``roster["picks"]`` used to be
        # consumed by ``len()`` alone, so every capital, the now/future
        # ratio and every asset the trade scan could propose were
        # player-only: a rebuilder holding 62 picks reported 59,693 of
        # rebuilder capital against 114,477 with picks included — 47.9%
        # omitted — and two of twelve direction labels flipped.  Audit
        # finding W13-F002.
        pick_assets, picks_unpriced = _pick_assets(
            roster["picks"], pick_index, pick_aliases, strategies
        )
        # Everything that is a CAPITAL sums both asset classes.  The
        # lineup-shaped aggregates below (starter FPG, positional
        # surplus) stay player-only because a pick fills no lineup slot.
        capital_assets = assets + pick_assets

        capitals = {
            s: sum(a["tradeValue"].get(s, 0.0) for a in capital_assets) for s in strategies
        }
        pick_capital = {s: sum(a["tradeValue"].get(s, 0.0) for a in pick_assets) for s in strategies}
        now = capitals.get("contender", 0.0)
        future = capitals.get("rebuilder", 0.0)
        # Value-weighted age stays PLAYER-only on purpose.  A pick has
        # no age, and weighting it in at zero would drag every roster's
        # mean toward a number nothing measured — the exact substitution
        # of a confident value for a missing one this codebase keeps
        # having to undo.
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
                "assetCount": len(capital_assets),
                "playerAssetCount": len(assets),
                "unmatchedPlayerIds": len(roster["playerIds"]) - len(assets),
                "capitals": {k: round(v, 1) for k, v in capitals.items()},
                "pickCapital": {k: round(v, 1) for k, v in pick_capital.items()},
                "nowFutureRatio": round(now / max(1.0, future), 3),
                # Player-only, and named so — see the note above.
                "valueWeightedAge": round(weighted_age, 2),
                "valueWeightedAgeScope": "players",
                "starterFpg": round(_quick_starter_fpg(assets, starters, flex), 1),
                "positionalSurplus": surplus,
                "pickCount": len(roster["picks"]),
                "pickCountPriced": len(pick_assets),
                # Picks the fundamental board declines to price are
                # reported, never valued at zero inside a capital.
                "pickCountUnpriced": picks_unpriced,
                "assets": sorted(
                    capital_assets, key=lambda a: -a["tradeValue"].get("balanced", 0.0)
                ),
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
