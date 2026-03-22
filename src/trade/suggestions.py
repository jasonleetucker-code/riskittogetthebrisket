"""Trade suggestion engine v1.

Given a roster, canonical values, and league context, generates actionable
trade suggestions: sell-high, buy-low, consolidation, positional upgrades.

Design principles:
- Deterministic: same inputs → same outputs
- Roster-aware: understands positional surplus and need
- Value-aware: uses canonical display values for fairness
- League-aware: uses replacement baselines for scarcity
- No opponent data required: works from market values only

The engine does NOT modify any internal canonical values or calibration.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from src.canonical.calibration import to_display_value


# ── Configuration ────────────────────────────────────────────────────

# Starter demand per position in default SF/TEP/IDP (effective starters per team)
DEFAULT_STARTER_NEEDS: dict[str, int] = {
    "QB": 2,   # 1 QB + ~1 SFLEX
    "RB": 3,   # 2 RB + ~1 FLEX
    "WR": 4,   # 3 WR + ~1 FLEX
    "TE": 1,   # 1 TE
    "DL": 3,   # 2 DL + ~1 IDP_FLEX
    "LB": 3,   # 2 LB + ~1 IDP_FLEX
    "DB": 2,   # 2 DB
}

# Minimum display value to consider a player "rosterable" (not a throw-in)
MIN_RELEVANT_VALUE = 500

# Fairness band: how close two trade sides need to be (display scale)
FAIRNESS_TOLERANCE = 769  # ~1 "Lean" verdict worth

# How many suggestions per category
MAX_SUGGESTIONS_PER_TYPE = 8

# Consolidation: the upgrade target must be worth at least this fraction
# of the combined depth pieces
CONSOLIDATION_MIN_UPGRADE_RATIO = 0.70

# Position aliases for normalization
_POS_ALIASES: dict[str, str] = {
    "DE": "DL", "DT": "DL", "EDGE": "DL", "NT": "DL",
    "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB",
    "OLB": "LB", "ILB": "LB",
}


# ── Data structures ─────────────────────────────────────────────────

@dataclass
class PlayerAsset:
    """A player or pick with canonical values."""
    name: str
    position: str
    display_value: int
    calibrated_value: int
    source_count: int = 0
    team: str = ""
    rookie: bool = False
    years_exp: int | None = None
    universe: str = ""
    dispersion_cv: float | None = None


@dataclass
class RosterAnalysis:
    """Positional analysis of a roster."""
    roster_size: int
    by_position: dict[str, list[PlayerAsset]]
    surplus_positions: list[str]
    need_positions: list[str]
    starter_counts: dict[str, int]  # above-replacement count
    depth_counts: dict[str, int]   # below-replacement count


@dataclass
class TradeSuggestion:
    """A single trade suggestion."""
    type: str  # "sell_high", "buy_low", "consolidation", "positional_upgrade"
    give: list[PlayerAsset]
    receive: list[PlayerAsset]
    give_total: int   # display value
    receive_total: int
    gap: int
    fairness: str  # "even", "lean", "stretch"
    rationale: str
    why_this_helps: str
    confidence: str  # "high", "medium", "low"
    strategy: str  # "contender", "rebuilder", "neutral"


# ── Core engine ──────────────────────────────────────────────────────

def _norm_pos(pos: str) -> str:
    p = pos.strip().upper()
    return _POS_ALIASES.get(p, p)


def build_asset_pool(canonical_snapshot: dict[str, Any]) -> list[PlayerAsset]:
    """Convert canonical snapshot assets into PlayerAsset objects."""
    assets = canonical_snapshot.get("assets", [])
    pool: list[PlayerAsset] = []
    for a in assets:
        name = str(a.get("display_name", "")).strip()
        if not name:
            continue
        cv = a.get("calibrated_value")
        dv = a.get("display_value")
        if cv is None:
            continue
        if dv is None:
            dv = to_display_value(cv)
        meta = a.get("metadata", {}) or {}
        pos = _norm_pos(str(meta.get("position", "") or ""))
        pool.append(PlayerAsset(
            name=name,
            position=pos,
            display_value=int(dv),
            calibrated_value=int(cv),
            source_count=len(a.get("source_values", {})),
            team=str(meta.get("team", "") or ""),
            rookie=bool(meta.get("rookie", False)),
            years_exp=meta.get("years_exp"),
            universe=str(a.get("universe", "")),
        ))
    pool.sort(key=lambda x: -x.display_value)
    return pool


def analyze_roster(
    roster_names: list[str],
    asset_pool: list[PlayerAsset],
    starter_needs: dict[str, int] | None = None,
) -> RosterAnalysis:
    """Analyze a roster for positional surplus and need."""
    needs = starter_needs or DEFAULT_STARTER_NEEDS

    # Match roster names to assets
    pool_by_name: dict[str, PlayerAsset] = {}
    for a in asset_pool:
        key = a.name.lower().strip()
        if key not in pool_by_name or a.display_value > pool_by_name[key].display_value:
            pool_by_name[key] = a

    by_position: dict[str, list[PlayerAsset]] = {}
    matched = 0
    for rn in roster_names:
        key = rn.lower().strip()
        a = pool_by_name.get(key)
        if a is None:
            continue
        matched += 1
        by_position.setdefault(a.position, []).append(a)

    # Sort each position by value descending
    for pos in by_position:
        by_position[pos].sort(key=lambda x: -x.display_value)

    # Compute surplus/need
    surplus_positions: list[str] = []
    need_positions: list[str] = []
    starter_counts: dict[str, int] = {}
    depth_counts: dict[str, int] = {}

    for pos, need in needs.items():
        players = by_position.get(pos, [])
        relevant = [p for p in players if p.display_value >= MIN_RELEVANT_VALUE]
        starters = relevant[:need]
        depth = relevant[need:]
        starter_counts[pos] = len(starters)
        depth_counts[pos] = len(depth)
        if len(starters) < need:
            need_positions.append(pos)
        if len(depth) >= 2:
            surplus_positions.append(pos)

    return RosterAnalysis(
        roster_size=matched,
        by_position=by_position,
        surplus_positions=surplus_positions,
        need_positions=need_positions,
        starter_counts=starter_counts,
        depth_counts=depth_counts,
    )


def _fairness_label(gap: int) -> str:
    a = abs(gap)
    if a < 256:
        return "even"
    if a < 769:
        return "lean"
    return "stretch"


def _strategy_for_player(player: PlayerAsset) -> str:
    """Infer whether a player is a contender or rebuilder asset."""
    if player.rookie or (player.years_exp is not None and player.years_exp <= 2):
        return "rebuilder"
    if player.years_exp is not None and player.years_exp >= 8:
        return "contender"
    return "neutral"


def _confidence_from_sources(source_count: int) -> str:
    if source_count >= 6:
        return "high"
    if source_count >= 3:
        return "medium"
    return "low"


# ── Suggestion generators ───────────────────────────────────────────

def _generate_sell_high(
    roster: RosterAnalysis,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
) -> list[TradeSuggestion]:
    """Find sell-high candidates: surplus-position veterans with high value."""
    suggestions: list[TradeSuggestion] = []

    for pos in roster.surplus_positions:
        players = roster.by_position.get(pos, [])
        if len(players) < 2:
            continue
        need = DEFAULT_STARTER_NEEDS.get(pos, 1)
        # Sell candidates: depth pieces (ranked after starters) with decent value
        sell_candidates = [p for p in players[need:] if p.display_value >= MIN_RELEVANT_VALUE]
        if not sell_candidates:
            continue

        for sell in sell_candidates[:3]:
            # Find buy targets at need positions
            for need_pos in roster.need_positions:
                # Find a target near sell value
                targets = [
                    a for a in asset_pool
                    if a.position == need_pos
                    and a.name.lower() not in roster_names_set
                    and a.display_value >= MIN_RELEVANT_VALUE
                    and abs(a.display_value - sell.display_value) < FAIRNESS_TOLERANCE
                ]
                if not targets:
                    continue
                # Best target: closest in value, slight underpay preferred
                targets.sort(key=lambda t: abs(t.display_value - sell.display_value))
                target = targets[0]
                gap = sell.display_value - target.display_value
                suggestions.append(TradeSuggestion(
                    type="sell_high",
                    give=[sell],
                    receive=[target],
                    give_total=sell.display_value,
                    receive_total=target.display_value,
                    gap=gap,
                    fairness=_fairness_label(gap),
                    rationale=f"You have {pos} surplus ({len(players)} rostered, need {need}). "
                              f"Move {sell.name} for a {need_pos} upgrade.",
                    why_this_helps=f"Converts {pos} depth into a {need_pos} you actually need.",
                    confidence=_confidence_from_sources(min(sell.source_count, target.source_count)),
                    strategy=_strategy_for_player(sell),
                ))

    suggestions.sort(key=lambda s: -min(s.give_total, s.receive_total))
    return suggestions[:MAX_SUGGESTIONS_PER_TYPE]


def _generate_buy_low(
    roster: RosterAnalysis,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
) -> list[TradeSuggestion]:
    """Find buy-low targets: need-position players slightly below roster depth value."""
    suggestions: list[TradeSuggestion] = []

    # For each need position, find targets that could be acquired cheaply
    for need_pos in roster.need_positions:
        # What is my current best asset at this position?
        current = roster.by_position.get(need_pos, [])
        # I want targets better than what I have
        current_best = current[0].display_value if current else 0
        target_floor = max(MIN_RELEVANT_VALUE, current_best)

        # Targets: above my current best, available on market
        targets = [
            a for a in asset_pool
            if a.position == need_pos
            and a.name.lower() not in roster_names_set
            and a.display_value > target_floor
        ]
        if not targets:
            continue

        # For each target, find what I could trade from surplus
        for target in targets[:5]:
            for surplus_pos in roster.surplus_positions:
                depth = roster.by_position.get(surplus_pos, [])
                need = DEFAULT_STARTER_NEEDS.get(surplus_pos, 1)
                tradeable = [p for p in depth[need:] if p.display_value >= MIN_RELEVANT_VALUE]
                for sell in tradeable[:2]:
                    gap = sell.display_value - target.display_value
                    if abs(gap) < FAIRNESS_TOLERANCE:
                        suggestions.append(TradeSuggestion(
                            type="buy_low",
                            give=[sell],
                            receive=[target],
                            give_total=sell.display_value,
                            receive_total=target.display_value,
                            gap=gap,
                            fairness=_fairness_label(gap),
                            rationale=f"Target {target.name} ({need_pos}) fills your roster need. "
                                      f"You can afford to trade {sell.name} from {surplus_pos} surplus.",
                            why_this_helps=f"Adds a starter-caliber {need_pos} without weakening "
                                           f"your {surplus_pos} starting lineup.",
                            confidence=_confidence_from_sources(min(sell.source_count, target.source_count)),
                            strategy="neutral",
                        ))

    # Deduplicate by target name, keep best fairness
    seen: dict[str, TradeSuggestion] = {}
    for s in suggestions:
        key = s.receive[0].name
        if key not in seen or abs(s.gap) < abs(seen[key].gap):
            seen[key] = s
    result = sorted(seen.values(), key=lambda s: -s.receive_total)
    return result[:MAX_SUGGESTIONS_PER_TYPE]


def _generate_consolidation(
    roster: RosterAnalysis,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
) -> list[TradeSuggestion]:
    """Find 2-for-1 consolidation trades: combine depth into a difference-maker."""
    suggestions: list[TradeSuggestion] = []

    # Collect all tradeable depth pieces across surplus positions
    tradeable: list[PlayerAsset] = []
    for pos in roster.surplus_positions:
        players = roster.by_position.get(pos, [])
        need = DEFAULT_STARTER_NEEDS.get(pos, 1)
        for p in players[need:]:
            if p.display_value >= MIN_RELEVANT_VALUE:
                tradeable.append(p)

    tradeable.sort(key=lambda x: -x.display_value)
    if len(tradeable) < 2:
        return []

    # Try pairs of depth pieces
    tried: set[str] = set()
    for i in range(min(len(tradeable), 6)):
        for j in range(i + 1, min(len(tradeable), 8)):
            p1, p2 = tradeable[i], tradeable[j]
            combined = p1.display_value + p2.display_value
            pair_key = f"{p1.name}|{p2.name}"
            if pair_key in tried:
                continue
            tried.add(pair_key)

            # Find a single upgrade target worth the package
            min_target = int(combined * CONSOLIDATION_MIN_UPGRADE_RATIO)
            max_target = combined + FAIRNESS_TOLERANCE

            # Prefer need-position targets
            for prefer_need in [True, False]:
                targets = [
                    a for a in asset_pool
                    if a.name.lower() not in roster_names_set
                    and min_target <= a.display_value <= max_target
                    and a.display_value > max(p1.display_value, p2.display_value)
                    and (not prefer_need or a.position in roster.need_positions)
                ]
                if not targets:
                    continue
                targets.sort(key=lambda t: -t.display_value)
                target = targets[0]
                gap = combined - target.display_value
                pos_note = f" at a position of need ({target.position})" if target.position in roster.need_positions else ""
                suggestions.append(TradeSuggestion(
                    type="consolidation",
                    give=[p1, p2],
                    receive=[target],
                    give_total=combined,
                    receive_total=target.display_value,
                    gap=gap,
                    fairness=_fairness_label(gap),
                    rationale=f"Package {p1.name} + {p2.name} into {target.name}{pos_note}. "
                              f"Turns two depth pieces into one difference-maker.",
                    why_this_helps=f"Upgrades roster quality by condensing {p1.position}/{p2.position} "
                                   f"depth into a higher-tier asset.",
                    confidence=_confidence_from_sources(target.source_count),
                    strategy="contender" if target.display_value >= 7000 else "neutral",
                ))
                break  # One target per pair is enough

    suggestions.sort(key=lambda s: -s.receive_total)
    return suggestions[:MAX_SUGGESTIONS_PER_TYPE]


def _generate_positional_upgrades(
    roster: RosterAnalysis,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
) -> list[TradeSuggestion]:
    """Find same-position upgrades: trade a starter + sweetener for a better starter."""
    suggestions: list[TradeSuggestion] = []

    for pos in DEFAULT_STARTER_NEEDS:
        players = roster.by_position.get(pos, [])
        if len(players) < 2:
            continue
        need = DEFAULT_STARTER_NEEDS.get(pos, 1)
        if need < 1:
            continue

        # Current starter range
        starters = players[:need]
        depth = [p for p in players[need:] if p.display_value >= MIN_RELEVANT_VALUE]
        if not starters or not depth:
            continue

        # For the weakest starter, find an upgrade target
        weakest_starter = starters[-1]
        upgrade_floor = weakest_starter.display_value + 500  # meaningful upgrade

        targets = [
            a for a in asset_pool
            if a.position == pos
            and a.name.lower() not in roster_names_set
            and a.display_value >= upgrade_floor
        ]
        if not targets:
            continue

        for target in targets[:3]:
            # Trade weakest starter + a depth piece from any surplus
            gap_needed = target.display_value - weakest_starter.display_value
            # Find a sweetener
            sweeteners = [
                p for p in depth
                if p.name != weakest_starter.name
                and abs(p.display_value - gap_needed) < FAIRNESS_TOLERANCE
            ]
            if not sweeteners:
                # Try any surplus depth piece
                for sp in roster.surplus_positions:
                    sp_depth = roster.by_position.get(sp, [])
                    sp_need = DEFAULT_STARTER_NEEDS.get(sp, 1)
                    for p in sp_depth[sp_need:]:
                        if p.display_value >= MIN_RELEVANT_VALUE and abs(p.display_value - gap_needed) < FAIRNESS_TOLERANCE:
                            sweeteners.append(p)
            if not sweeteners:
                continue

            sweeteners.sort(key=lambda s: abs(s.display_value - gap_needed))
            sweetener = sweeteners[0]
            give_total = weakest_starter.display_value + sweetener.display_value
            gap = give_total - target.display_value

            if abs(gap) > FAIRNESS_TOLERANCE * 1.5:
                continue

            suggestions.append(TradeSuggestion(
                type="positional_upgrade",
                give=[weakest_starter, sweetener],
                receive=[target],
                give_total=give_total,
                receive_total=target.display_value,
                gap=gap,
                fairness=_fairness_label(gap),
                rationale=f"Upgrade {pos} starter: move {weakest_starter.name} + {sweetener.name} "
                          f"for {target.name}.",
                why_this_helps=f"Replaces your {pos}{need} with a higher-caliber {pos} starter.",
                confidence=_confidence_from_sources(target.source_count),
                strategy="contender",
            ))

    suggestions.sort(key=lambda s: -s.receive_total)
    return suggestions[:MAX_SUGGESTIONS_PER_TYPE]


def _find_balancers(
    gap: int,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
    exclude_names: set[str],
) -> list[PlayerAsset]:
    """Find assets that could balance a trade gap."""
    if abs(gap) < 256:
        return []
    target_value = abs(gap)
    candidates = [
        a for a in asset_pool
        if a.name.lower() not in roster_names_set
        and a.name.lower() not in exclude_names
        and a.display_value >= 100
        and abs(a.display_value - target_value) < target_value * 0.4
    ]
    candidates.sort(key=lambda c: abs(c.display_value - target_value))
    return candidates[:3]


# ── Main entry point ─────────────────────────────────────────────────

def generate_suggestions(
    roster_names: list[str],
    canonical_snapshot: dict[str, Any],
    *,
    starter_needs: dict[str, int] | None = None,
    max_per_type: int = MAX_SUGGESTIONS_PER_TYPE,
) -> dict[str, Any]:
    """Generate trade suggestions for a given roster.

    Args:
        roster_names: List of player names on the user's team.
        canonical_snapshot: Full canonical snapshot with assets.
        starter_needs: Override positional starter needs.
        max_per_type: Max suggestions per category.

    Returns:
        Dict with suggestion categories, roster analysis, and metadata.
    """
    pool = build_asset_pool(canonical_snapshot)
    roster = analyze_roster(roster_names, pool, starter_needs)
    roster_set = {n.lower().strip() for n in roster_names}

    sell_high = _generate_sell_high(roster, pool, roster_set)
    buy_low = _generate_buy_low(roster, pool, roster_set)
    consolidation = _generate_consolidation(roster, pool, roster_set)
    upgrades = _generate_positional_upgrades(roster, pool, roster_set)

    # Add balancers to suggestions with non-even fairness
    all_suggestions = sell_high + buy_low + consolidation + upgrades
    for s in all_suggestions:
        if s.fairness != "even":
            exclude = {p.name.lower() for p in s.give + s.receive}
            s_balancers = _find_balancers(s.gap, pool, roster_set, exclude)
            # Store on the suggestion object (we'll serialize later)
            s.__dict__["balancers"] = s_balancers

    return {
        "rosterAnalysis": _serialize_roster(roster),
        "sellHigh": [_serialize_suggestion(s) for s in sell_high],
        "buyLow": [_serialize_suggestion(s) for s in buy_low],
        "consolidation": [_serialize_suggestion(s) for s in consolidation],
        "positionalUpgrades": [_serialize_suggestion(s) for s in upgrades],
        "totalSuggestions": len(all_suggestions),
        "metadata": {
            "assetPoolSize": len(pool),
            "rosterMatched": roster.roster_size,
            "rosterProvided": len(roster_names),
            "starterNeeds": starter_needs or DEFAULT_STARTER_NEEDS,
        },
    }


# ── Serializers ──────────────────────────────────────────────────────

def _serialize_player(p: PlayerAsset) -> dict[str, Any]:
    return {
        "name": p.name,
        "position": p.position,
        "displayValue": p.display_value,
        "team": p.team,
        "rookie": p.rookie,
    }


def _serialize_suggestion(s: TradeSuggestion) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": s.type,
        "give": [_serialize_player(p) for p in s.give],
        "receive": [_serialize_player(p) for p in s.receive],
        "giveTotal": s.give_total,
        "receiveTotal": s.receive_total,
        "gap": s.gap,
        "fairness": s.fairness,
        "rationale": s.rationale,
        "whyThisHelps": s.why_this_helps,
        "confidence": s.confidence,
        "strategy": s.strategy,
    }
    balancers = s.__dict__.get("balancers", [])
    if balancers:
        result["suggestedBalancers"] = [_serialize_player(b) for b in balancers]
    return result


def _serialize_roster(r: RosterAnalysis) -> dict[str, Any]:
    return {
        "rosterSize": r.roster_size,
        "surplusPositions": r.surplus_positions,
        "needPositions": r.need_positions,
        "starterCounts": r.starter_counts,
        "depthCounts": r.depth_counts,
        "byPosition": {
            pos: [_serialize_player(p) for p in players]
            for pos, players in r.by_position.items()
        },
    }
