"""Team-aware trade impact analyzer.

Produces a roster-shape-aware verdict on a proposed trade — the dynasty
manager's actual question: *does this trade FIT my roster*, not just
*is the equity fair*.

Pure functions; no I/O.  Inputs are the same resolved-asset dicts that
``src/api/trade_simulator.py`` already builds, plus the league's
``rosterSettings`` (from ``src.api.league_registry``).

CRITICAL ARCHITECTURAL RULE — see ``src/league/README.md``:

    Player VALUES are global per scoring profile.
    Team FIT is per-league.

This module produces a *fit score alongside* a player's value.  It
NEVER mutates ``row.value`` per team.  The retired LAM module proved
that path is wrong — do not re-introduce it here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.ros.lineup import RosterPlayer, assign_lineup, resolve_starter_slots, slot_demand

_BASE_POSITIONS = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")


def _load_default_weights() -> dict[str, Any]:
    """Read config/trade/team_impact.json once.  Falls back to safe
    defaults if the file is missing — same shape as the JSON.
    """
    try:
        path = Path(__file__).resolve().parents[2] / "config" / "trade" / "team_impact.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "weights": {
                "fillStarter": 1.0,
                "depth": 0.25,
                "overflow": 0.6,
                "fitNormalization": 4000,
                "equityNormalization": 2500,
                "compositeFitWeight": 0.55,
                "compositeEquityWeight": 0.45,
            },
            "verdictThresholds": {
                "accept": 20,
                "leanAccept": 8,
                "leanDecline": -8,
                "decline": -20,
            },
            "windowFit": {
                "contendIndexThreshold": 0.15,
                "youngStarterMaxAge": 23,
                "primeStarterMinAge": 24,
                "primeStarterMaxAge": 29,
            },
        }


def _starter_slots(roster_settings: dict[str, Any]) -> dict[str, int]:
    """Extract the per-slot starter counts dict (e.g. {"QB":1,"RB":2,...}).
    Returns ``{}`` if absent — caller treats that as "no fit analysis
    possible".
    """
    s = roster_settings.get("starters") if isinstance(roster_settings, dict) else None
    if not isinstance(s, dict):
        return {}
    return {str(k).upper(): int(v) for k, v in s.items() if isinstance(v, (int, float))}


def project_starters(
    assets: list[dict[str, Any]],
    roster_settings: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Starting lineup from a list of resolved assets.

    Returns ``{base_pos: [asset, ...]}`` — the starters at each base
    position (RB starters from FLEX go into the RB bucket).  Picks are
    ignored (they don't start).

    **Consumes the canonical assignment owner** (C2-U1).  It used to
    keep its own slot-ordered greedy plus its own
    ``_DEFAULT_*_ELIGIBLE`` tables, and measured against Sleeper's own
    awarded lineups over 10 real 2025 team-weeks that engine reproduced
    the host on **0 of 10** — 238.92 points of which was eligibility
    blindness (it read ``basePos`` only, so a DL/LB hybrid was locked
    out of half its legal slots) and 2.76 points the greedy itself lost
    (its ``_FILL_ORDER`` filled ``SFLEX`` before ``FLEX``, i.e.
    least-restrictive first).  It also named no ``K`` slot, though that
    never reached this function's own output.

    The eligibility half only becomes real once callers supply
    ``fantasyPositions``; assets that carry none fall back to
    ``basePos``, which is exactly the old behaviour.  Nothing is
    fabricated to fill the gap.
    """
    slots, _source = resolve_starter_slots(roster_settings=roster_settings)
    if not slots:
        return {p: [] for p in _BASE_POSITIONS}

    pool: list[RosterPlayer] = []
    by_id: dict[str, dict[str, Any]] = {}
    for idx, asset in enumerate(assets):
        base = (asset.get("basePos") or asset.get("pos") or "").upper()
        if base not in _BASE_POSITIONS:
            continue
        # Index-keyed: these dicts have no stable identifier, and two
        # roster picks can legitimately share a display name.
        key = f"{idx}"
        by_id[key] = asset
        value = asset.get("value")
        pool.append(
            RosterPlayer(
                player_id=key,
                canonical_name=str(asset.get("name") or key),
                position=base,
                # ``None`` stays ``None``: an asset the board declined to
                # price is UNPRICED, not worth zero, and must not win a
                # starting slot ahead of one we can price.
                ros_value=None if value is None else float(value),
                fantasy_positions=tuple(
                    str(fp).upper() for fp in (asset.get("fantasyPositions") or ()) if fp
                ),
            )
        )

    starters: dict[str, list[dict[str, Any]]] = {p: [] for p in _BASE_POSITIONS}
    assignment = assign_lineup(pool, slots)
    # Slot order, so the buckets read the way the league's lineup card
    # does rather than in augmenting-path order.
    for slot_idx in sorted(assignment.assignments):
        player = assignment.assignments[slot_idx]
        asset = by_id.get(player.player_id)
        if asset is None:
            continue
        base = (asset.get("basePos") or asset.get("pos") or "").upper()
        if base in starters:
            starters[base].append(asset)
    return starters


def _aggregate_state(
    assets: list[dict[str, Any]],
    roster_settings: dict[str, Any],
) -> dict[str, Any]:
    """Project starters + compute totalCount/starterCount/depthCount/
    starterValue per base position.
    """
    starters = project_starters(assets, roster_settings)
    starter_count = {p: len(starters[p]) for p in _BASE_POSITIONS}
    starter_value = {p: sum(int(a.get("value") or 0) for a in starters[p]) for p in _BASE_POSITIONS}
    total_count: dict[str, int] = {p: 0 for p in _BASE_POSITIONS}
    for a in assets:
        pos = (a.get("basePos") or a.get("pos") or "").upper()
        if pos in total_count:
            total_count[pos] += 1
    depth_count = {p: max(0, total_count[p] - starter_count[p]) for p in _BASE_POSITIONS}
    return {
        "starters": starters,
        "starterCount": starter_count,
        "starterValue": starter_value,
        "totalCount": total_count,
        "depthCount": depth_count,
    }


def _needed_at(pos: str, roster_settings: dict[str, Any]) -> float:
    """Starter demand at ``pos``, for overflow detection.

    Reads the canonical :func:`slot_demand` contract's ``even_split``
    field — a DECLARED approximation, not truth (see
    ``src/ros/lineup.py::SlotDemand``: LI-5 measured the even split ~40%
    wrong at QB).  It is the right rung here because overflow only asks
    "is this roster carrying more bodies than the lineup can absorb",
    which a coarse sizing constant answers.

    Retired the local ``_flex_share`` — one of four independent
    re-derivations of the same even-split rule in the tree.
    """
    return slot_demand(resolve_starter_slots(roster_settings=roster_settings)[0]).even_split.get(
        pos.upper(), 0.0
    )


def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _league_active_positions(roster_settings: dict[str, Any]) -> list[str]:
    """Positions the league actually starts.  ``dynasty_new`` returns
    only QB/RB/WR/TE; ``dynasty_main`` adds DL/LB/DB.  This is the
    guard that prevents IDP redundancy false-positives in non-IDP
    leagues.
    """
    return [p for p in _BASE_POSITIONS if _needed_at(p, roster_settings) > 0]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _classify_window(
    before_assets: list[dict[str, Any]],
    config: dict[str, Any],
) -> str:
    """Posture from current roster: contender / balanced / rebuilder.

    Heuristic:
      contendIndex = top10 WIN-NOW value share
                   - (rookie pick share + young (<24) player share)

    "Win-now" means an asset that is neither a rookie pick nor a young
    player — i.e. the ones that score points for you THIS season.  The
    top-10 slice used to be taken over every asset, which counted the
    future twice with opposite signs: a rebuilder whose ten most
    valuable assets ARE first-round picks scored a near-1.0
    ``top10_share`` and a near-1.0 ``pick_share``, the two cancelled,
    and the engine called them "balanced".  Excluding picks and kids
    from the positive term makes every dollar feed at most one side of
    the subtraction, so a pick-stuffed roster reads as the rebuilder it
    is.

    Picks are also excluded from ``young_value`` — a pick row that
    carries an ``age`` (defensive; they normally don't) would otherwise
    be charged to the negative term twice.
    """
    threshold = float(config.get("windowFit", {}).get("contendIndexThreshold", 0.15))
    young_max = int(config.get("windowFit", {}).get("youngStarterMaxAge", 23))

    def _is_pick(asset: dict[str, Any]) -> bool:
        return (asset.get("assetClass") or "").lower() == "pick"

    def _is_young(asset: dict[str, Any]) -> bool:
        return isinstance(asset.get("age"), int) and asset["age"] <= young_max

    total_value = sum(int(a.get("value") or 0) for a in before_assets) or 1

    win_now = [a for a in before_assets if not _is_pick(a) and not _is_young(a)]
    by_value = sorted(win_now, key=lambda a: int(a.get("value") or 0), reverse=True)
    top10_value = sum(int(a.get("value") or 0) for a in by_value[:10])
    top10_share = top10_value / total_value

    pick_value = sum(int(a.get("value") or 0) for a in before_assets if _is_pick(a))
    pick_share = pick_value / total_value

    young_value = sum(
        int(a.get("value") or 0) for a in before_assets if not _is_pick(a) and _is_young(a)
    )
    young_share = young_value / total_value

    contend_index = top10_share - (pick_share + young_share)
    if contend_index > threshold:
        return "contender"
    if contend_index < -threshold:
        return "rebuilder"
    return "balanced"


def _window_fit_for_asset(
    asset: dict[str, Any],
    posture: str,
    config: dict[str, Any],
    *,
    sign: int,
) -> float:
    """Score one moving asset against the team's posture.

    ``sign=+1`` for receiving, ``sign=-1`` for sending.  Returns a
    float in roughly [-1, +1] before averaging.
    """
    wf = config.get("windowFit", {})
    prime_min = int(wf.get("primeStarterMinAge", 24))
    prime_max = int(wf.get("primeStarterMaxAge", 29))
    young_max = int(wf.get("youngStarterMaxAge", 23))

    is_pick = (asset.get("assetClass") or "").lower() == "pick"
    age = asset.get("age") if isinstance(asset.get("age"), int) else None
    is_young = age is not None and age <= young_max
    is_prime = age is not None and prime_min <= age <= prime_max

    if posture == "contender":
        if is_prime:
            return 1.0 * sign
        if is_pick or is_young:
            return -1.0 * sign
        return 0.0
    if posture == "rebuilder":
        if is_pick or is_young:
            return 1.0 * sign
        if is_prime:
            return -0.5 * sign
        return 0.0
    return 0.0


def _redundancy(
    receiving: list[dict[str, Any]],
    after_starters: dict[str, list[dict[str, Any]]],
    before_state: dict[str, Any],
    roster_settings: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flag acquired assets that don't crack the starting lineup at a
    position the team was already saturated in.  Skipped for positions
    the league doesn't start (no false-positives in non-IDP leagues).
    """
    starter_names = {
        str(a.get("name") or "").lower() for assets in after_starters.values() for a in assets
    }
    active = set(_league_active_positions(roster_settings))
    out: list[dict[str, Any]] = []
    for asset in receiving:
        pos = (asset.get("basePos") or asset.get("pos") or "").upper()
        if pos not in active:
            continue
        name_key = str(asset.get("name") or "").lower()
        if name_key in starter_names:
            continue
        before_count = before_state["totalCount"].get(pos, 0)
        needed = _needed_at(pos, roster_settings)
        if before_count >= int(needed) + 1:
            out.append(
                {
                    "name": asset.get("name"),
                    "pos": pos,
                    "reason": "duplicate at saturated position",
                }
            )
    return out


def _verdict(composite: float, thresholds: dict[str, Any]) -> str:
    if composite >= float(thresholds.get("accept", 20)):
        return "accept"
    if composite >= float(thresholds.get("leanAccept", 8)):
        return "lean accept"
    if composite > float(thresholds.get("leanDecline", -8)):
        return "neutral"
    if composite > float(thresholds.get("decline", -20)):
        return "lean decline"
    return "decline"


def _rationale(
    *,
    starter_value_delta: dict[str, int],
    starter_delta: dict[str, int],
    overflow_delta: dict[str, int],
    redundancy: list[dict[str, Any]],
    window_fit: float,
    posture: str,
    equity: int,
    fit_score: float,
) -> list[str]:
    """Top 5 bullets ranked by absolute contribution to verdict."""
    bullets: list[tuple[float, str]] = []
    for pos, dv in starter_value_delta.items():
        if dv == 0:
            continue
        sign = "+" if dv > 0 else ""
        if dv > 0 and starter_delta.get(pos, 0) > 0:
            bullets.append((abs(dv), f"Adds a starting {pos} ({sign}{dv} starter value)"))
        elif dv < 0 and starter_delta.get(pos, 0) < 0:
            bullets.append((abs(dv), f"Loses a starting {pos} ({sign}{dv} starter value)"))
        else:
            bullets.append((abs(dv) * 0.6, f"Shifts {pos} starter quality ({sign}{dv})"))
    for pos, od in overflow_delta.items():
        if od >= 1:
            bullets.append((400 * od, f"Adds bench depth at saturated {pos} (-overflow)"))
    for r in redundancy:
        bullets.append((300, f"Acquired {r['name']} ({r['pos']}) doesn't start — duplicate"))
    if abs(window_fit) >= 0.4:
        word = "aligns with" if window_fit > 0 else "fights"
        bullets.append(
            (abs(window_fit) * 1000, f"Trade {word} a {posture} window ({window_fit:+.1f})")
        )
    if abs(equity) >= 500:
        bullets.append((abs(equity) * 0.3, f"Net KTC equity {equity:+d}"))
    if abs(fit_score) >= 5:
        bullets.append((abs(fit_score) * 5, f"Roster-shape fit score {fit_score:+.0f}"))
    bullets.sort(key=lambda b: b[0], reverse=True)
    return [b[1] for b in bullets[:5]]


def compute(
    *,
    before_assets: list[dict[str, Any]],
    after_assets: list[dict[str, Any]],
    receiving: list[dict[str, Any]],
    sending: list[dict[str, Any]],
    equity: int,
    roster_settings: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build the ``teamImpact`` payload.  Returns ``None`` when
    ``roster_settings`` lacks starter slots (no fit analysis possible).
    """
    cfg = config or _load_default_weights()
    weights = cfg.get("weights", {})
    thresholds = cfg.get("verdictThresholds", {})

    if not _starter_slots(roster_settings):
        return None

    before = _aggregate_state(before_assets, roster_settings)
    after = _aggregate_state(after_assets, roster_settings)
    active = _league_active_positions(roster_settings)

    starter_delta = {
        p: after["starterCount"][p] - before["starterCount"][p] for p in _BASE_POSITIONS
    }
    starter_value_delta = {
        p: after["starterValue"][p] - before["starterValue"][p] for p in _BASE_POSITIONS
    }
    depth_delta = {p: after["depthCount"][p] - before["depthCount"][p] for p in _BASE_POSITIONS}

    # Overflow detection — anything above (needed + 1) is bench bloat.
    overflow_delta: dict[str, int] = {}
    for p in _BASE_POSITIONS:
        cap = int(_needed_at(p, roster_settings)) + 1
        before_over = max(0, before["totalCount"][p] - cap)
        after_over = max(0, after["totalCount"][p] - cap)
        overflow_delta[p] = after_over - before_over

    # Average starter value per pos, for normalization.
    avg_starter_val: dict[str, float] = {}
    for p in _BASE_POSITIONS:
        combined = [int(a.get("value") or 0) for a in before["starters"][p]] + [
            int(a.get("value") or 0) for a in after["starters"][p]
        ]
        avg_starter_val[p] = _avg(combined) or 1500.0

    w_fill = float(weights.get("fillStarter", 1.0))
    w_depth = float(weights.get("depth", 0.25))
    w_overflow = float(weights.get("overflow", 0.6))
    fit_norm = float(weights.get("fitNormalization", 4000)) or 4000.0

    fit_raw = 0.0
    for p in active:
        fit_raw += w_fill * starter_value_delta[p]
        # Diminishing depth: only the first depth piece earns a bonus.
        before_first_depth = 1 if before["depthCount"][p] >= 1 else 0
        after_first_depth = 1 if after["depthCount"][p] >= 1 else 0
        fit_raw += w_depth * (after_first_depth - before_first_depth) * avg_starter_val[p]
        fit_raw -= w_overflow * max(0, overflow_delta[p]) * avg_starter_val[p]

    fit_score = _clamp(100.0 * fit_raw / fit_norm, -100.0, 100.0)
    equity_norm = float(weights.get("equityNormalization", 2500)) or 2500.0
    equity_score = _clamp(100.0 * float(equity) / equity_norm, -100.0, 100.0)

    cw_fit = float(weights.get("compositeFitWeight", 0.55))
    cw_eq = float(weights.get("compositeEquityWeight", 0.45))
    composite = cw_fit * fit_score + cw_eq * equity_score

    posture = _classify_window(before_assets, cfg)
    window_score = 0.0
    moving = []
    for a in receiving:
        moving.append(_window_fit_for_asset(a, posture, cfg, sign=+1))
    for a in sending:
        moving.append(_window_fit_for_asset(a, posture, cfg, sign=-1))
    if moving:
        window_score = sum(moving) / len(moving)

    def _avg_age(assets: list[dict[str, Any]]) -> float | None:
        ages = [a["age"] for a in assets if isinstance(a.get("age"), int)]
        return sum(ages) / len(ages) if ages else None

    in_age = _avg_age(receiving)
    out_age = _avg_age(sending)
    age_delta = (in_age - out_age) if (in_age is not None and out_age is not None) else 0.0

    # Scarcity delta — reports the per-position starter-vs-replacement
    # shift for the user.  This is reporting only, never re-prices.
    scarcity_delta: dict[str, float] = {}
    for p in active:
        before_avg = (
            (before["starterValue"][p] / before["starterCount"][p])
            if before["starterCount"][p]
            else 0
        )
        after_avg = (
            (after["starterValue"][p] / after["starterCount"][p]) if after["starterCount"][p] else 0
        )
        scarcity_delta[p] = round(after_avg - before_avg, 1)

    redundancy = _redundancy(receiving, after["starters"], before, roster_settings)
    rationale = _rationale(
        starter_value_delta={p: starter_value_delta[p] for p in active},
        starter_delta={p: starter_delta[p] for p in active},
        overflow_delta={p: overflow_delta[p] for p in active},
        redundancy=redundancy,
        window_fit=window_score,
        posture=posture,
        equity=equity,
        fit_score=fit_score,
    )

    return {
        "fitScore": round(fit_score, 1),
        "equityScore": round(equity_score, 1),
        "compositeScore": round(composite, 1),
        "verdict": _verdict(composite, thresholds),
        "posture": posture,
        "starterDelta": {p: starter_delta[p] for p in active},
        "starterValueDelta": {p: starter_value_delta[p] for p in active},
        "depthDelta": {p: depth_delta[p] for p in active},
        "windowFit": round(window_score, 2),
        "ageDelta": round(age_delta, 1),
        "scarcityDelta": scarcity_delta,
        "redundancy": redundancy,
        "rationale": rationale,
    }
