#!/usr/bin/env python3
"""Sweep calibration exponents to find the best tier/delta tradeoff.

Reads the latest canonical snapshot (with KTC), re-applies calibration
with different exponents, then runs comparison against legacy to measure
tier agreement, avg delta, and top-N overlap.

This does NOT modify any production files — it operates on in-memory copies.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path for shared imports
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._shared import _repo_root, _latest as _latest_file


def recalibrate_assets(assets: list[dict], exponent: float, universe_scales: dict[str, int]) -> list[dict]:
    """Re-apply calibration with a different exponent. Returns a new list."""
    import re
    NON_FANTASY = {"K", "P", "OL"}
    NON_FANTASY_CEIL = 600

    def _is_pick(a):
        n = str(a.get("display_name", "")).lower().strip()
        patterns = [r"^\d{4}\s+(pick|early|mid|late)", r"^(early|mid|late)\s+\d",
                    r"^\d{4}\s+\d+\.\d+", r"pick\s+\d+\.\d+", r"^\d{4}\s+\d+(st|nd|rd|th)$"]
        return any(re.search(p, n) for p in patterns)

    by_universe: dict[str, list[dict]] = {}
    for a in assets:
        u = str(a.get("universe", "unknown"))
        by_universe.setdefault(u, []).append(a)

    for universe, group in by_universe.items():
        scale = universe_scales.get(universe, 8500)
        players = [a for a in group if not _is_pick(a)]
        sort_key = "blended_value"
        players.sort(key=lambda a: -(a.get(sort_key) or 0))
        for rank_idx, asset in enumerate(players):
            depth = len(players)
            if depth == 0:
                break
            rank = rank_idx + 1
            percentile = (depth - (rank - 1)) / depth
            calibrated = int(round(scale * (percentile ** exponent)))
            calibrated = max(0, min(scale, calibrated))
            pos = str(asset.get("metadata", {}).get("position", "")).upper()
            if pos in NON_FANTASY and calibrated > NON_FANTASY_CEIL:
                calibrated = NON_FANTASY_CEIL
            asset["calibrated_value"] = calibrated

    return assets


def run_comparison(canonical_assets: list[dict], legacy: dict[str, dict]) -> dict:
    """Quick comparison returning key metrics."""
    import re

    def _normalize(name):
        n = name.strip()
        for sfx in (" Jr.", " Sr.", " II", " III", " IV", " V"):
            if n.endswith(sfx):
                n = n[:-len(sfx)].strip()
        return n.lower().replace(".", "").replace("'", "").replace("\u2019", "")

    def _is_pick_name(name):
        n = name.lower().strip()
        patterns = [r"^\d{4}\s+(pick|early|mid|late)", r"^(early|mid|late)\s+\d",
                    r"^\d{4}\s+\d+\.\d+", r"pick\s+\d+\.\d+", r"^\d{4}\s+\d+(st|nd|rd|th)$"]
        return any(re.search(p, n) for p in patterns)

    # Build canonical lookup
    can_lookup = {}
    for a in canonical_assets:
        name = str(a.get("display_name", "")).strip()
        val = a.get("calibrated_value") or a.get("blended_value")
        if not name or val is None:
            continue
        existing = can_lookup.get(name)
        if existing is not None and existing["value"] >= int(val):
            continue
        can_lookup[name] = {"value": int(val), "universe": a.get("universe", ""),
                           "source_count": len(a.get("source_values", {}))}

    # Build legacy normalized lookup
    legacy_norm = {}
    for name in legacy:
        legacy_norm[_normalize(name)] = name

    # Match
    matched = []
    for c_name, c_data in can_lookup.items():
        c_norm = _normalize(c_name)
        l_name = legacy_norm.get(c_norm) or (c_name if c_name in legacy else None)
        if l_name is None:
            continue
        l_data = legacy[l_name]
        delta = c_data["value"] - l_data["value"]
        matched.append({
            "name": c_name, "canonical_value": c_data["value"], "legacy_value": l_data["value"],
            "delta": delta, "abs_delta": abs(delta), "universe": c_data["universe"],
            "source_count": c_data["source_count"], "legacy_pos": l_data.get("pos", ""),
        })

    def tier(v):
        if v >= 7000: return "elite"
        if v >= 5000: return "star"
        if v >= 3000: return "starter"
        if v >= 1500: return "bench"
        return "depth"

    # Offense players only
    offense = [m for m in matched if m["universe"] in ("offense_vet", "offense_rookie")
               and not _is_pick_name(m["name"]) and m.get("legacy_pos", "") != "PICK"]
    if len(offense) < 10:
        return {"error": "too few offense players"}

    abs_deltas = [m["abs_delta"] for m in offense]
    n = len(offense)
    tier_agree = sum(1 for m in offense if tier(m["canonical_value"]) == tier(m["legacy_value"]))

    by_c = sorted(offense, key=lambda m: -m["canonical_value"])
    by_l = sorted(offense, key=lambda m: -m["legacy_value"])
    top50 = min(50, n)
    c_top = {m["name"] for m in by_c[:top50]}
    l_top = {m["name"] for m in by_l[:top50]}

    c_top100 = {m["name"] for m in by_c[:100]}
    l_top100 = {m["name"] for m in by_l[:100]}

    # Per-position breakdown
    pos_tier = {}
    for m in offense:
        pos = m.get("legacy_pos", "?")
        if pos not in pos_tier:
            pos_tier[pos] = {"agree": 0, "total": 0, "deltas": []}
        pos_tier[pos]["total"] += 1
        pos_tier[pos]["deltas"].append(m["abs_delta"])
        if tier(m["canonical_value"]) == tier(m["legacy_value"]):
            pos_tier[pos]["agree"] += 1

    # QB 7-15 check
    qbs = [m for m in offense if m.get("legacy_pos") == "QB"]
    qbs_by_legacy = sorted(qbs, key=lambda m: -m["legacy_value"])
    qb7_15 = qbs_by_legacy[6:15] if len(qbs_by_legacy) >= 15 else []
    qb7_15_tier_agree = sum(1 for m in qb7_15 if tier(m["canonical_value"]) == tier(m["legacy_value"]))

    # TE top-15 check
    tes = [m for m in offense if m.get("legacy_pos") == "TE"]
    tes_by_legacy = sorted(tes, key=lambda m: -m["legacy_value"])
    te_top15 = tes_by_legacy[:15] if len(tes_by_legacy) >= 15 else []
    te_top15_tier_agree = sum(1 for m in te_top15 if tier(m["canonical_value"]) == tier(m["legacy_value"]))

    return {
        "offense_count": n,
        "avg_abs_delta": int(round(sum(abs_deltas) / n)),
        "median_abs_delta": sorted(abs_deltas)[n // 2],
        "top50_overlap_pct": round(len(c_top & l_top) / top50 * 100),
        "top100_overlap_pct": round(len(c_top100 & l_top100) / 100 * 100) if n >= 100 else None,
        "tier_agreement_pct": round(tier_agree / n * 100, 1),
        "pos_tier": {p: {"pct": round(d["agree"] / d["total"] * 100, 1),
                         "avg_delta": int(round(sum(d["deltas"]) / d["total"]))}
                     for p, d in sorted(pos_tier.items())},
        "qb7_15_tier_agree": f"{qb7_15_tier_agree}/{len(qb7_15)}",
        "te_top15_tier_agree": f"{te_top15_tier_agree}/{len(te_top15)}",
    }


def main():
    repo = _repo_root()

    # Load latest canonical snapshot
    snap_path = _latest_file(repo / "data" / "canonical", "canonical_snapshot_*.json")
    if not snap_path:
        print("No canonical snapshot found")
        return 1
    snap = json.loads(snap_path.read_text())
    print(f"Snapshot: {snap_path.name} ({snap['source_count']} sources, {snap['asset_count']} assets)")

    # Load legacy data
    legacy_path = _latest_file(repo / "data", "legacy_data_*.json")
    if not legacy_path:
        legacy_path = _latest_file(repo / "data", "dynasty_data_*.json")
    if not legacy_path:
        print("No legacy data found")
        return 1
    legacy_data = json.loads(legacy_path.read_text())
    legacy = {}
    for name, pdata in legacy_data.get("players", {}).items():
        if not isinstance(pdata, dict):
            continue
        val = pdata.get("_finalAdjusted") or pdata.get("_composite")
        if val is None or int(val) <= 0:
            continue
        pos = str(pdata.get("position") or pdata.get("POS") or "").upper()
        legacy[name] = {"value": int(val), "pos": pos}

    universe_scales = {"offense_vet": 8500, "offense_rookie": 8500,
                       "idp_vet": 5000, "idp_rookie": 5000}

    # Sweep exponents
    exponents = [2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5]
    print(f"\n{'Exp':>5} | {'Tier%':>6} | {'AvgΔ':>6} | {'MedΔ':>6} | {'Top50':>5} | {'T100':>5} | {'QB7-15':>7} | {'TE15':>6} | {'QB%':>5} | {'RB%':>5} | {'WR%':>5} | {'TE%':>5}")
    print("-" * 100)

    for exp in exponents:
        assets = copy.deepcopy(snap["assets"])
        recalibrate_assets(assets, exp, universe_scales)
        result = run_comparison(assets, legacy)
        if "error" in result:
            print(f"{exp:>5.2f} | ERROR: {result['error']}")
            continue

        pos = result.get("pos_tier", {})
        qb_pct = pos.get("QB", {}).get("pct", "?")
        rb_pct = pos.get("RB", {}).get("pct", "?")
        wr_pct = pos.get("WR", {}).get("pct", "?")
        te_pct = pos.get("TE", {}).get("pct", "?")

        marker = ""
        if result["tier_agreement_pct"] >= 65 and result["avg_abs_delta"] <= 800:
            marker = " ← PASS"
        elif result["tier_agreement_pct"] >= 65:
            marker = " ← tier PASS"
        elif result["avg_abs_delta"] <= 800:
            marker = " ← delta PASS"

        print(f"{exp:>5.2f} | {result['tier_agreement_pct']:>5.1f}% | {result['avg_abs_delta']:>5d} | {result['median_abs_delta']:>5d} | {result['top50_overlap_pct']:>4d}% | {result['top100_overlap_pct']:>4d}% | {result['qb7_15_tier_agree']:>7s} | {result['te_top15_tier_agree']:>6s} | {qb_pct:>4}% | {rb_pct:>4}% | {wr_pct:>4}% | {te_pct:>4}%{marker}")

    # Also test offense_rookie ceiling reduction
    print("\n--- Rookie ceiling sweep (at best offense_vet exponent) ---")
    best_exp = None
    best_score = 0
    for exp in exponents:
        assets_test = copy.deepcopy(snap["assets"])
        recalibrate_assets(assets_test, exp, universe_scales)
        r = run_comparison(assets_test, legacy)
        if "error" not in r:
            score = r["tier_agreement_pct"] - max(0, r["avg_abs_delta"] - 800) * 0.02
            if score > best_score:
                best_score = score
                best_exp = exp
    if best_exp is None:
        best_exp = 2.5

    print(f"Best vet exponent: {best_exp}")
    for rookie_ceil in [8500, 7500, 7000, 6500]:
        scales = dict(universe_scales)
        scales["offense_rookie"] = rookie_ceil
        assets_test = copy.deepcopy(snap["assets"])
        recalibrate_assets(assets_test, best_exp, scales)
        r = run_comparison(assets_test, legacy)
        if "error" not in r:
            print(f"  rookie_ceil={rookie_ceil}: tier={r['tier_agreement_pct']:.1f}%, delta={r['avg_abs_delta']}, top50={r['top50_overlap_pct']}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
