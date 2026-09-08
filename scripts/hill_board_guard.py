#!/usr/bin/env python3
"""Fail closed if an otherwise-ready Hill promotion has destructive board impact."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any


def _q(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    idx = min(len(xs) - 1, max(0, math.ceil(p * len(xs)) - 1))
    return float(xs[idx])


def _top(rows: dict[str, dict[str, Any]], n: int) -> set[str]:
    ranked = [
        (str(k), float(v["canonicalConsensusRank"]))
        for k, v in rows.items()
        if isinstance(v.get("canonicalConsensusRank"), (int, float))
    ]
    ranked.sort(key=lambda x: x[1])
    return {k for k, _ in ranked[:n]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    before = json.loads(args.before.read_text())
    after = json.loads(args.after.read_text())
    policy = json.loads(args.policy.read_text())["boardImpact"]

    for key in ("inputSha256", "sourceCsvSha256", "freshnessSha256"):
        if before.get(key) != after.get(key):
            raise SystemExit(f"ERROR: board captures differ on {key}; impact is not attributable")

    rb = before.get("rows") or {}
    ra = after.get("rows") or {}
    common = sorted(set(rb) & set(ra))
    value_pct: list[float] = []
    rank_shift: list[float] = []
    newly_unpriced = 0
    before_priced = 0

    for key in common:
        old_v = rb[key].get("rankDerivedValue")
        new_v = ra[key].get("rankDerivedValue")
        if isinstance(old_v, (int, float)):
            before_priced += 1
            if not isinstance(new_v, (int, float)):
                newly_unpriced += 1
            elif old_v:
                value_pct.append(abs(float(new_v) - float(old_v)) / abs(float(old_v)))
        old_r = rb[key].get("canonicalConsensusRank")
        new_r = ra[key].get("canonicalConsensusRank")
        if isinstance(old_r, (int, float)) and isinstance(new_r, (int, float)):
            rank_shift.append(abs(float(new_r) - float(old_r)))

    unpriced_fraction = newly_unpriced / max(1, before_priced)
    median_value = float(median(value_pct)) if value_pct else 0.0
    p90_value = _q(value_pct, 0.90)
    max_value = max(value_pct, default=0.0)
    median_rank = float(median(rank_shift)) if rank_shift else 0.0
    p90_rank = _q(rank_shift, 0.90)
    top25_overlap = len(_top(rb, 25) & _top(ra, 25))
    top100_overlap = len(_top(rb, 100) & _top(ra, 100))

    gates = {
        "same_row_set": set(rb) == set(ra),
        "unpriced": unpriced_fraction <= float(policy["maxUnpricedFraction"]),
        "median_value_change": median_value <= float(policy["maxMedianAbsPctValueChange"]),
        "p90_value_change": p90_value <= float(policy["maxP90AbsPctValueChange"]),
        "max_value_change": max_value <= float(policy["maxSingleAbsPctValueChange"]),
        "top25_overlap": top25_overlap >= int(policy["minTop25Overlap"]),
        "top100_overlap": top100_overlap >= int(policy["minTop100Overlap"]),
        "median_rank_shift": median_rank <= float(policy["maxMedianAbsRankShift"]),
        "p90_rank_shift": p90_rank <= float(policy["maxP90AbsRankShift"]),
    }
    report = {
        "pass": all(gates.values()),
        "gates": gates,
        "metrics": {
            "rows": len(common),
            "beforePriced": before_priced,
            "newlyUnpriced": newly_unpriced,
            "unpricedFraction": unpriced_fraction,
            "medianAbsPctValueChange": median_value,
            "p90AbsPctValueChange": p90_value,
            "maxAbsPctValueChange": max_value,
            "medianAbsRankShift": median_rank,
            "p90AbsRankShift": p90_rank,
            "top25Overlap": top25_overlap,
            "top100Overlap": top100_overlap,
        },
    }
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["metrics"], sort_keys=True))
    if report["pass"]:
        print("Hill board-impact gate: PASS")
        return 0
    failed = [k for k, ok in gates.items() if not ok]
    print("Hill board-impact gate: BLOCK — " + ", ".join(failed))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
