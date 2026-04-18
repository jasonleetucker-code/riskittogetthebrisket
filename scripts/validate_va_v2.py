#!/usr/bin/env python3
"""Sanity-check the V2 Value Adjustment formula against real league trades.

Pipeline:
    1. Load the exported dynasty player values + pick anchors from
       ``exports/latest/dynasty_data_*.json`` (same source the
       frontend /trade calculator reads from).
    2. Load the public-league activity feed from
       ``data/public_league/contract.json`` — every trade the public
       /league page surfaces, with ``receivedAssets`` per side.
    3. For each historical trade, resolve every asset to its current
       KTC value (players by display name, picks by canonical label),
       then run both V1 (legacy) and V2 (live) VA formulas.
    4. Emit a side-by-side report flagging:
         * Cases where V2's VA differs from V1 by > 1000 raw points or
           > 50 % of V1.
         * Cases where V2 awards a VA exceeding the single side's top
           asset (suspicious magnitude).
         * Cases where the recipient side flips between V1 and V2
           (shouldn't happen — both formulas give VA to the smaller
           side, but worth asserting).
         * Distribution histogram of V2 / raw-total ratios.

This script is a one-shot sanity check, NOT a perfect production
regression — it uses current asset values rather than trade-time
values, so its numbers differ from what the trade calculator
showed at the moment each historical trade happened.  Still useful
for catching anything where V2 produces structurally weird output.

Run: ``python3 scripts/validate_va_v2.py``
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

# ── V1 (legacy) and V2 (live production) formula ports ─────────────────
# Mirror ``frontend/lib/trade-logic.js::computeValueAdjustment`` so the
# numbers here match what the live UI produces.

V1_SLOPE = 4.27
V1_INTERCEPT = 0.288
V1_CAP = 0.64
V1_DECAY = 0.70

V2_SLOPE = 3.75
V2_INTERCEPT = 0.45
V2_CAP = 0.55
V2_BOOST = 1.4
V2_EFFECTIVE_CAP = 1.0
V2_DECAY = 0.35


def compute_va_v1(small: list[float], large: list[float]) -> float:
    if len(small) == 0 or small[0] <= 0:
        return 0.0
    if len(small) >= len(large):
        return 0.0
    small = sorted(small, reverse=True)
    large = sorted(large, reverse=True)
    top_gap = max(0.0, (small[0] - large[0]) / small[0])
    raw = V1_SLOPE * top_gap - V1_INTERCEPT
    scarcity = max(0.0, min(V1_CAP, raw))
    if scarcity == 0:
        return 0.0
    total = 0.0
    for i, extra in enumerate(large[len(small):]):
        total += extra * scarcity * (V1_DECAY ** i)
    return total


def compute_va_v2(small: list[float], large: list[float]) -> float:
    if len(small) == 0 or small[0] <= 0:
        return 0.0
    if len(small) >= len(large):
        return 0.0
    small = sorted(small, reverse=True)
    large = sorted(large, reverse=True)
    top_small = small[0]
    top_large = large[0]
    top_gap = max(0.0, (top_small - top_large) / top_small)
    if top_gap == 0:
        return 0.0
    raw = V2_SLOPE * top_gap - V2_INTERCEPT
    top_scarcity = max(0.0, min(V2_CAP, raw))
    total = 0.0
    for i, extra in enumerate(large[len(small):]):
        extra_gap = max(0.0, (top_small - extra) / top_small)
        boost = V2_BOOST * max(0.0, extra_gap - top_gap)
        effective = max(0.0, min(V2_EFFECTIVE_CAP, top_scarcity + boost))
        total += extra * effective * (V2_DECAY ** i)
    return total


# ── Asset resolution ────────────────────────────────────────────────────
def build_resolvers() -> tuple[dict[str, float], dict[str, float]]:
    """Return (player_by_name, pick_by_label) value maps from export."""
    # Latest export.
    export_files = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))
    if not export_files:
        raise SystemExit("No dynasty_data_*.json under exports/latest/")
    with open(export_files[-1]) as f:
        data = json.load(f)
    # Players are keyed by display name.  Use `ktc` field (1-9999 scale)
    # as the value source — same thing the UI's "Our Value" maps from.
    player_by_name = {}
    for name, raw in (data.get("players") or {}).items():
        if not isinstance(raw, dict):
            continue
        val = raw.get("ktc")
        if not isinstance(val, (int, float)) or val <= 0:
            continue
        player_by_name[name.lower()] = float(val)

    # Pick anchors: labels like "2026 Early 1st" or "2026 1.07".
    anchors = (data.get("pickAnchors") or {}).get("ktc") or {}
    pick_by_label = {
        key.lower(): float(val)
        for key, val in anchors.items()
        if isinstance(val, (int, float)) and val > 0
    }
    return player_by_name, pick_by_label


def resolve_asset(asset: dict[str, Any],
                  players: dict[str, float],
                  picks: dict[str, float]) -> tuple[float, bool]:
    """Return (value, resolved).  ``resolved`` is False when we can't
    find a value for the asset (retired/dropped player, missing pick).
    We skip unresolved assets from VA math but still count them for
    reporting."""
    kind = str(asset.get("kind") or "").lower()
    if kind == "player":
        name = str(asset.get("playerName") or "").strip().lower()
        if name in players:
            return players[name], True
        return 0.0, False
    if kind == "pick":
        label = str(asset.get("label") or "").strip().lower()
        if label in picks:
            return picks[label], True
        # Fallback: build synthetic label from season + round.
        season = asset.get("season")
        rnd = asset.get("round")
        if season and rnd:
            synth = f"{season} {_round_label(rnd)}".lower()
            if synth in picks:
                return picks[synth], True
            synth2 = f"{season} mid {_round_label(rnd)}".lower()
            if synth2 in picks:
                return picks[synth2], True
        return 0.0, False
    # Unknown kind.
    return 0.0, False


_ROUND_SUFFIX = {1: "1st", 2: "2nd", 3: "3rd"}


def _round_label(rnd) -> str:
    try:
        rnd = int(rnd)
    except (TypeError, ValueError):
        return str(rnd)
    return _ROUND_SUFFIX.get(rnd, f"{rnd}th")


# ── Trade iteration + report ───────────────────────────────────────────
def iter_trades():
    path = REPO / "data" / "public_league" / "contract.json"
    if not path.exists():
        raise SystemExit(f"Missing {path}")
    with open(path) as f:
        contract = json.load(f)
    feed = (contract.get("sections") or {}).get("activity", {}).get("feed") or []
    for trade in feed:
        yield trade


def analyze_trade(trade: dict[str, Any],
                  players: dict[str, float],
                  picks: dict[str, float]) -> dict[str, Any]:
    sides = trade.get("sides") or []
    if len(sides) != 2:
        return {"skipped": "multi_side"}

    side_values = []
    unresolved = 0
    for side in sides:
        values = []
        for asset in side.get("receivedAssets") or []:
            v, resolved = resolve_asset(asset, players, picks)
            if resolved:
                values.append(v)
            else:
                unresolved += 1
        side_values.append(values)

    a, b = side_values
    if not a or not b:
        return {"skipped": "empty_side"}

    # Determine small vs large by piece count (matches live formula).
    if len(a) == len(b):
        va_v1 = 0.0
        va_v2 = 0.0
        recipient = None
    else:
        if len(a) < len(b):
            small, large = a, b
            recipient = 0
        else:
            small, large = b, a
            recipient = 1
        va_v1 = compute_va_v1(small, large)
        va_v2 = compute_va_v2(small, large)

    # Raw totals for each side.
    raw_a = sum(a)
    raw_b = sum(b)

    return {
        "transactionId": trade.get("transactionId"),
        "season": trade.get("season"),
        "week": trade.get("week"),
        "aCount": len(a),
        "bCount": len(b),
        "recipient": recipient,
        "rawA": raw_a,
        "rawB": raw_b,
        "smallTop": max(small) if recipient is not None else 0,
        "va_v1": va_v1,
        "va_v2": va_v2,
        "delta": va_v2 - va_v1,
        "unresolved": unresolved,
    }


def _hist(values: list[float], bins: int = 10) -> list[tuple[float, float, int]]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [(lo, hi, len(values))]
    step = (hi - lo) / bins
    out = []
    for i in range(bins):
        a = lo + i * step
        b = lo + (i + 1) * step if i < bins - 1 else hi + 1e-9
        count = sum(1 for v in values if a <= v < b)
        out.append((a, b, count))
    return out


def main() -> None:
    players, picks = build_resolvers()
    print(f"Resolvers: {len(players)} players, {len(picks)} pick labels.")

    trades = list(iter_trades())
    print(f"Trades in feed: {len(trades)}")

    analyzed = []
    skipped = Counter()
    for t in trades:
        r = analyze_trade(t, players, picks)
        if "skipped" in r:
            skipped[r["skipped"]] += 1
            continue
        analyzed.append(r)

    print(f"Analyzed: {len(analyzed)}   Skipped: {dict(skipped)}")
    uneven = [r for r in analyzed if r["recipient"] is not None]
    even = [r for r in analyzed if r["recipient"] is None]
    print(f"  uneven-piece trades (VA applies): {len(uneven)}")
    print(f"  even-piece trades (no VA):        {len(even)}")

    if not uneven:
        return

    # Distribution of V2 VAs as fraction of raw-small-side total.
    v2_vas = [r["va_v2"] for r in uneven]
    v1_vas = [r["va_v1"] for r in uneven]
    deltas = [r["delta"] for r in uneven]

    print("\n=== V1 vs V2 VA summary ===")
    print(f"  V1 mean: {sum(v1_vas)/len(v1_vas):7.1f}   min: {min(v1_vas):6.1f}   max: {max(v1_vas):6.1f}")
    print(f"  V2 mean: {sum(v2_vas)/len(v2_vas):7.1f}   min: {min(v2_vas):6.1f}   max: {max(v2_vas):6.1f}")
    print(f"  Δ mean:  {sum(deltas)/len(deltas):7.1f}   min: {min(deltas):6.1f}   max: {max(deltas):6.1f}")

    print("\n=== Δ distribution (V2 − V1) ===")
    for lo, hi, cnt in _hist(deltas, bins=10):
        bar = "#" * cnt
        print(f"  [{lo:7.1f} → {hi:7.1f}]  {cnt:3}  {bar}")

    print("\n=== Top 10 biggest V2-vs-V1 increases ===")
    top_up = sorted(uneven, key=lambda r: -r["delta"])[:10]
    for r in top_up:
        print(
            f"  {r['season']}-wk{r['week']:>2}  {r['aCount']}v{r['bCount']}  "
            f"V1={r['va_v1']:6.0f} → V2={r['va_v2']:6.0f}  (Δ +{r['delta']:6.0f})  "
            f"rawA={r['rawA']:5.0f} rawB={r['rawB']:5.0f}  unresolved={r['unresolved']}"
        )

    print("\n=== Top 10 biggest V2-vs-V1 decreases ===")
    top_down = sorted(uneven, key=lambda r: r["delta"])[:10]
    for r in top_down:
        print(
            f"  {r['season']}-wk{r['week']:>2}  {r['aCount']}v{r['bCount']}  "
            f"V1={r['va_v1']:6.0f} → V2={r['va_v2']:6.0f}  (Δ {r['delta']:6.0f})  "
            f"rawA={r['rawA']:5.0f} rawB={r['rawB']:5.0f}  unresolved={r['unresolved']}"
        )

    # Structural sanity checks.
    print("\n=== Structural sanity checks ===")
    va_over_top = [r for r in uneven if r["va_v2"] > r["smallTop"]]
    print(f"  V2 VA exceeds small-side top asset: {len(va_over_top)}/{len(uneven)}")
    if va_over_top:
        for r in va_over_top[:5]:
            print(
                f"    {r['season']}-wk{r['week']}  V2={r['va_v2']:.0f}  smallTop={r['smallTop']:.0f}"
            )

    negative_va = [r for r in uneven if r["va_v2"] < 0]
    print(f"  V2 VA negative: {len(negative_va)}/{len(uneven)}")

    newly_nonzero = [r for r in uneven if r["va_v1"] == 0 and r["va_v2"] > 0]
    print(f"  V2 turned on VA where V1 was 0: {len(newly_nonzero)}/{len(uneven)}")
    if newly_nonzero:
        median_new = sorted(r["va_v2"] for r in newly_nonzero)[len(newly_nonzero) // 2]
        max_new = max(r["va_v2"] for r in newly_nonzero)
        print(f"    new VA median: {median_new:.0f}, max: {max_new:.0f}")

    # V2/V1 ratio for cases where both produced VA > 0.
    both_nonzero = [r for r in uneven if r["va_v1"] > 100 and r["va_v2"] > 100]
    if both_nonzero:
        ratios = [r["va_v2"] / r["va_v1"] for r in both_nonzero]
        print(f"  V2/V1 ratio (both >100): mean {sum(ratios)/len(ratios):.2f}x  "
              f"median {sorted(ratios)[len(ratios)//2]:.2f}x  "
              f"min {min(ratios):.2f}x  max {max(ratios):.2f}x")

    print("\nDone.")


if __name__ == "__main__":
    main()
