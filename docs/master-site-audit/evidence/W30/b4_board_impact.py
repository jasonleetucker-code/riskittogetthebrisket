#!/usr/bin/env python3
"""B4 §4 steps 5-6 — full board impact, and the B3 corridor interaction.

Builds the board TWICE from the identical pinned input — once with the
tail saturating at rank 500 (pre-B4 production) and once at
:data:`src.canonical.tail_policy.TAIL_SATURATION_RANK` — and diffs them.

Covers, in order:

* values changed, and the rank-movement distribution
* membership at the served cutoff
* composition at top 50 / 100 / 200 / 400
* positional effects
* largest movers
* pick movement
* **upward movement despite lower raw contributions** — B1.2 saw this and
  it must be explained rather than dismissed
* the B3 corridor interaction: clamps before/after, bucket distribution,
  anchor source, direction

Nothing here changes production; the policy is swapped by patching the
declared constant for the duration of one build.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent

POSITION_BUCKETS = (
    ("QB", {"QB"}),
    ("RB", {"RB"}),
    ("WR", {"WR"}),
    ("TE", {"TE"}),
    ("DL/EDGE", {"DL", "EDGE", "DE", "DT"}),
    ("LB", {"LB"}),
    ("DB", {"DB", "CB", "S"}),
)


def bucket_for(position: str, asset_class: str) -> str:
    if asset_class == "pick":
        return "picks"
    pos = (position or "").upper()
    for name, members in POSITION_BUCKETS:
        if pos in members:
            return name
    return "other"


def board_at(saturation_rank: int) -> list[dict]:
    """Build the pinned board with the tail saturating at ``saturation_rank``."""
    from src.api.data_contract import build_api_data_contract
    from src.canonical import tail_policy

    raw = json.loads((ROOT / "exports/latest/dynasty_data_2026-08-11.json").read_bytes())
    prev = tail_policy.TAIL_SATURATION_RANK
    tail_policy.TAIL_SATURATION_RANK = int(saturation_rank)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            contract = build_api_data_contract(raw)
        return contract.get("playersArray") or []
    finally:
        tail_policy.TAIL_SATURATION_RANK = prev


def _index(rows: list[dict]) -> dict[str, dict]:
    return {str(r.get("displayName")): r for r in rows}


def _saturated_names(rows: list[dict], n: int = 500) -> set[str]:
    """Rows carrying at least one rank-Hill observation past ``n``."""
    out = set()
    for r in rows:
        for meta in (r.get("sourceRankMeta") or {}).values():
            if not isinstance(meta, dict):
                continue
            if meta.get("valueContributionPath") != "rank_hill":
                continue
            eff = meta.get("effectiveRank")
            if isinstance(eff, int) and eff > n:
                out.add(str(r.get("displayName")))
                break
    return out


def report() -> None:
    from src.canonical.tail_policy import TAIL_SATURATION_RANK

    print(f"== building the pinned board twice: tail at 500 (pre-B4) vs {TAIL_SATURATION_RANK} ==")
    before = board_at(500)
    after = board_at(TAIL_SATURATION_RANK)
    b_idx, a_idx = _index(before), _index(after)
    names = sorted(set(b_idx) & set(a_idx))
    print(f"  rows: before={len(before)} after={len(after)} common={len(names)}")

    touched = _saturated_names(before)
    print(f"  rows carrying a saturated rank-Hill observation: {len(touched)}")

    # ── values changed ──
    changed, deltas = [], {}
    for nm in names:
        vb, va = b_idx[nm].get("rankDerivedValue"), a_idx[nm].get("rankDerivedValue")
        if vb is None or va is None:
            continue
        if vb != va:
            changed.append(nm)
            deltas[nm] = va - vb
    print(f"\n== values changed: {len(changed)} of {len(names)} rows ==")
    untouched_moved = [nm for nm in changed if nm not in touched]
    print(f"  of which OUTSIDE the saturated population: {len(untouched_moved)}")
    if untouched_moved:
        print("  (a value moving on a row with no saturated observation is a SECOND-ORDER")
        print("   effect — blend/corridor coupling, not the tail policy acting directly)")

    # ── rank movement ──
    moves = {}
    for nm in names:
        rb, ra = b_idx[nm].get("canonicalConsensusRank"), a_idx[nm].get("canonicalConsensusRank")
        if isinstance(rb, int) and isinstance(ra, int):
            moves[nm] = ra - rb
    if moves:
        vals = sorted(moves.values())
        print(f"\n== rank movement over {len(moves)} rows ranked in BOTH builds ==")
        print(f"  moved at all : {sum(1 for v in vals if v)}")
        print(
            f"  min/p10/med/p90/max : {vals[0]} / {vals[len(vals) // 10]} / "
            f"{vals[len(vals) // 2]} / {vals[9 * len(vals) // 10]} / {vals[-1]}"
        )

    # ── membership at the served cutoff ──
    rb_set = {nm for nm in names if b_idx[nm].get("canonicalConsensusRank")}
    ra_set = {nm for nm in names if a_idx[nm].get("canonicalConsensusRank")}
    print("\n== membership at the served cutoff ==")
    print(f"  served before={len(rb_set)}  after={len(ra_set)}")
    print(f"  promoted into the board: {sorted(ra_set - rb_set)}")
    print(f"  dropped off the board  : {sorted(rb_set - ra_set)}")

    # ── composition at the top ──
    def top_n(idx: dict, n: int) -> list[str]:
        ranked = [
            (r["canonicalConsensusRank"], nm)
            for nm, r in idx.items()
            if isinstance(r.get("canonicalConsensusRank"), int)
        ]
        return [nm for _, nm in sorted(ranked)[:n]]

    print("\n== composition at the top ==")
    for n in (50, 100, 200, 400):
        tb, ta = set(top_n(b_idx, n)), set(top_n(a_idx, n))
        print(f"  top {n:<4} identical={tb == ta}  entered={len(ta - tb)}  left={len(tb - ta)}")

    # ── positional effects ──
    print("\n== positional effect (rows whose value moved) ==")
    pop: Counter = Counter()
    hit: Counter = Counter()
    for nm in names:
        b = bucket_for(str(b_idx[nm].get("position") or ""), str(b_idx[nm].get("assetClass") or ""))
        pop[b] += 1
        if nm in deltas:
            hit[b] += 1
    for b, _ in list(POSITION_BUCKETS) + [("picks", set()), ("other", set())]:
        if pop.get(b):
            print(
                f"  {b:<9} {hit.get(b, 0):>4} of {pop[b]:>4}  ({100.0 * hit.get(b, 0) / pop[b]:>5.1f}%)"
            )

    # ── largest movers ──
    print("\n== largest value movers ==")
    for nm in sorted(deltas, key=lambda k: -abs(deltas[k]))[:12]:
        rb = b_idx[nm].get("canonicalConsensusRank")
        ra = a_idx[nm].get("canonicalConsensusRank")
        print(
            f"  {nm:<26}{b_idx[nm].get('position') or '':<5}"
            f"{b_idx[nm].get('rankDerivedValue'):>6} -> {a_idx[nm].get('rankDerivedValue'):>6}"
            f"  ({deltas[nm]:+5})   rank {rb} -> {ra}"
        )

    # ── picks ──
    pick_moved = [nm for nm in deltas if str(b_idx[nm].get("assetClass")) == "pick"]
    print(f"\n== pick movement: {len(pick_moved)} pick rows changed value ==")
    for nm in sorted(pick_moved, key=lambda k: -abs(deltas[k]))[:8]:
        print(
            f"  {nm:<26}{b_idx[nm].get('rankDerivedValue'):>6} -> "
            f"{a_idx[nm].get('rankDerivedValue'):>6}  ({deltas[nm]:+5})"
        )

    # ── upward movement despite lower raw contributions ──
    #
    # B1.2 saw this and it must be EXPLAINED. Every saturated observation
    # can only fall (the tail resolves lower than the clamped value), so a
    # row whose value ROSE did not rise because its own evidence rose.
    print("\n== rows that ROSE despite every changed contribution falling ==")
    anomalies = []
    for nm in changed:
        if deltas[nm] <= 0:
            continue
        bm = b_idx[nm].get("sourceRankMeta") or {}
        am = a_idx[nm].get("sourceRankMeta") or {}
        raw_up = False
        raw_down = False
        for k, m in am.items():
            if not isinstance(m, dict) or not isinstance(bm.get(k), dict):
                continue
            cb, ca = bm[k].get("valueContribution"), m.get("valueContribution")
            if isinstance(cb, int) and isinstance(ca, int):
                if ca > cb:
                    raw_up = True
                if ca < cb:
                    raw_down = True
        if not raw_up:
            anomalies.append((nm, deltas[nm], raw_down))
    print(f"  {len(anomalies)} row(s)")
    for nm, d, raw_down in anomalies[:10]:
        clamp_b = (b_idx[nm].get("marketCorridorClamp") or {}).get("applied")
        clamp_a = (a_idx[nm].get("marketCorridorClamp") or {}).get("applied")
        print(
            f"  {nm:<26}{d:+6}  someContributionFell={raw_down}  "
            f"corridorClamp {clamp_b} -> {clamp_a}"
        )

    # ── the B3 corridor interaction ──
    def clamps(idx: dict) -> dict[str, dict]:
        return {
            nm: r["marketCorridorClamp"]
            for nm, r in idx.items()
            if isinstance(r.get("marketCorridorClamp"), dict)
            and r["marketCorridorClamp"].get("applied")
        }

    cb, ca = clamps(b_idx), clamps(a_idx)
    print("\n== B3 market-corridor interaction (measured, B3 NOT reopened) ==")
    print(f"  clamps applied: before={len(cb)}  after={len(ca)}")
    print(f"  newly clamped : {len(set(ca) - set(cb))}")
    print(f"  no longer     : {len(set(cb) - set(ca))}")
    for label, coll in (("before", cb), ("after", ca)):
        print(
            f"  {label:<7} buckets={dict(Counter(c.get('confidenceBucket') for c in coll.values()))}"
            f"  direction={dict(Counter(c.get('direction') for c in coll.values()))}"
            f"  anchors={dict(Counter(c.get('marketSource') for c in coll.values()))}"
        )
    bands_b = sorted(c.get("bandPct") or 0 for c in cb.values())
    bands_a = sorted(c.get("bandPct") or 0 for c in ca.values())
    for label, bands in (("before", bands_b), ("after", bands_a)):
        if bands:
            print(
                f"  {label:<7} bandPct min/med/max = {bands[0]:.4f} / "
                f"{bands[len(bands) // 2]:.4f} / {bands[-1]:.4f}"
            )
    newly = sorted(set(ca) - set(cb))
    if newly:
        print("  newly-clamped rows:")
        for nm in newly[:12]:
            c = ca[nm]
            print(
                f"    {nm:<26}{c.get('direction'):<6}band={c.get('bandPct')}"
                f"  anchor={c.get('marketSource')}  sources={a_idx[nm].get('sourceCount')}"
                f"  rank={a_idx[nm].get('canonicalConsensusRank')}"
            )

    payload = {
        "saturationRankAfter": TAIL_SATURATION_RANK,
        "rowsCompared": len(names),
        "rowsWithSaturatedObservation": len(touched),
        "valuesChanged": len(changed),
        "valuesChangedOutsideSaturatedPopulation": len(untouched_moved),
        "servedBefore": len(rb_set),
        "servedAfter": len(ra_set),
        "promoted": sorted(ra_set - rb_set),
        "dropped": sorted(rb_set - ra_set),
        "roseWithNoContributionRising": [
            {"name": nm, "delta": d, "someContributionFell": rd} for nm, d, rd in anomalies
        ],
        "corridor": {
            "appliedBefore": len(cb),
            "appliedAfter": len(ca),
            "newlyClamped": sorted(set(ca) - set(cb)),
            "noLongerClamped": sorted(set(cb) - set(ca)),
            "bucketsBefore": dict(Counter(c.get("confidenceBucket") for c in cb.values())),
            "bucketsAfter": dict(Counter(c.get("confidenceBucket") for c in ca.values())),
            "directionBefore": dict(Counter(c.get("direction") for c in cb.values())),
            "directionAfter": dict(Counter(c.get("direction") for c in ca.values())),
            "anchorsBefore": dict(Counter(c.get("marketSource") for c in cb.values())),
            "anchorsAfter": dict(Counter(c.get("marketSource") for c in ca.values())),
        },
        "largestMovers": [
            {
                "name": nm,
                "position": b_idx[nm].get("position"),
                "before": b_idx[nm].get("rankDerivedValue"),
                "after": a_idx[nm].get("rankDerivedValue"),
                "delta": deltas[nm],
            }
            for nm in sorted(deltas, key=lambda k: -abs(deltas[k]))[:25]
        ],
    }
    (OUT / "b4_board_impact.json").write_text(json.dumps(payload, indent=1, default=str))
    print(f"\nwrote {OUT / 'b4_board_impact.json'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.report:
        report()
        return 0
    ap.error("pass --report")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
