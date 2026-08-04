#!/usr/bin/env python3
"""Measure the BDVM dispersion-slot scale mismatch and its signal impact.

WHAT THIS MEASURES
==================
``src/bdvm/market.py::_dispersion_for_row`` feeds one number into
``liquidity = clip(base + coeff x dispersion)``, and that liquidity both
scales ``alpha = gap x liquidity`` and gates
``strong_buy_min_liquidity``.  Until 2026-08-04 three different things
could land in that slot:

1. ``marketDispersionCV``            — a coefficient of variation
2. ``sourceRankPercentileSpread``    — a percentile spread (different statistic)
3. a hardcoded ``0.20``              — when neither was present

This script quantifies (a) how far apart 1 and 2 actually are on rows
that carry both, (b) where the hardcoded default sits on the real CV
distribution, and (c) how each branch lands against the STRONG_BUY
liquidity gate.

It reads the raw scraper payload and builds the contract, so it needs no
running server and no BDVM projection snapshot — the defect is in how
contract fields are consumed, which is fully observable without the
fundamental engine.

USAGE
=====
    python3 scripts/measure_bdvm_dispersion_scale.py exports/latest/dynasty_data_YYYY-MM-DD.json
    python3 scripts/measure_bdvm_dispersion_scale.py <payload> --json docs/measurements/out.json

Pin the payload explicitly; the exports filename rolls daily and a prod
refresh landing mid-session will silently change the numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("ALLOW_DEFAULT_LOGIN_DEV", "1")
os.environ.pop("SLEEPER_LEAGUE_ID", None)
os.environ.setdefault("LEAGUE_REGISTRY_PATH", "/nonexistent/path/for/measurement.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Positions BDVM prices as players.  Picks take the distribution-EV path
# and kickers are never priced, so including them would overstate the
# affected population — the honest denominator is this set.
_PLAYABLE = {"QB", "RB", "WR", "TE", "DL", "LB", "DB"}


def _liquidity(dispersion: float, cfg: dict[str, Any]) -> float:
    raw = float(cfg["base"]) + float(cfg["dispersion_coeff"]) * dispersion
    return min(float(cfg["clip_hi"]), max(float(cfg["clip_lo"]), raw))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("payload", help="raw scraper payload JSON (pin it; do not glob)")
    ap.add_argument("--json", help="write the measurement JSON here")
    args = ap.parse_args()

    from src.api import data_contract as dc
    from src.bdvm.params import load_param_set

    # The build persists a rank snapshot; neutralise it so running this
    # measurement never perturbs a later before/after comparison.
    dc._stamp_rank_changes = lambda *a, **k: None  # noqa: ARG005

    payload_path = Path(args.payload)
    contract = dc.build_api_data_contract(json.loads(payload_path.read_text()))
    rows = contract["playersArray"]

    params = load_param_set("params_v1")
    liq_cfg = params["market"]["liquidity"]
    gate = float(params["market"]["signal_thresholds"]["strong_buy_min_liquidity"])

    def num(row: dict[str, Any], key: str) -> float | None:
        v = row.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    both = [
        (num(r, "marketDispersionCV"), num(r, "sourceRankPercentileSpread"))
        for r in rows
        if num(r, "marketDispersionCV") is not None
        and num(r, "sourceRankPercentileSpread") is not None
    ]
    ratios = sorted(s / c for c, s in both if c and c > 0.001)

    cvs = [v for v in (num(r, "marketDispersionCV") for r in rows) if v is not None]

    branches: dict[str, dict[str, Any]] = {}
    for label in ("A_measured_cv", "B_percentile_spread_fallback", "C_hardcoded_0.20"):
        branches[label] = {"rows": 0, "eligible": 0}

    for r in rows:
        if r.get("position") not in _PLAYABLE:
            continue
        cv = num(r, "marketDispersionCV")
        sp = num(r, "sourceRankPercentileSpread")
        if cv is not None:
            label, d = "A_measured_cv", cv
        elif sp is not None:
            label, d = "B_percentile_spread_fallback", sp
        else:
            label, d = "C_hardcoded_0.20", 0.20
        branches[label]["rows"] += 1
        if _liquidity(min(1.0, max(0.0, d)), liq_cfg) > gate:
            branches[label]["eligible"] += 1

    out = {
        "payload": str(payload_path),
        "rowsTotal": len(rows),
        "scaleMismatch": {
            "rowsCarryingBoth": len(both),
            "spreadOverCvRatio": {
                "median": round(st.median(ratios), 4) if ratios else None,
                "p10": round(ratios[len(ratios) // 10], 4) if ratios else None,
                "p90": round(ratios[len(ratios) * 9 // 10], 4) if ratios else None,
            },
        },
        "cvDistribution": {
            "n": len(cvs),
            "min": round(min(cvs), 6) if cvs else None,
            "median": round(st.median(cvs), 6) if cvs else None,
            "max": round(max(cvs), 6) if cvs else None,
            "hardcodedDefaultPercentileRank": (
                round(sum(1 for v in cvs if v < 0.20) / len(cvs), 4) if cvs else None
            ),
        },
        "strongBuyGate": {"threshold": gate, "byBranch": branches},
    }

    print(f"payload {payload_path}  rows {len(rows)}")
    print()
    print("SCALE MISMATCH (rows carrying BOTH fields)")
    print(f"  n = {len(both)}")
    if ratios:
        print(
            f"  sourceRankPercentileSpread / marketDispersionCV: "
            f"median {st.median(ratios):.2f}x  p10 {ratios[len(ratios)//10]:.2f}x  "
            f"p90 {ratios[len(ratios)*9//10]:.2f}x"
        )
    print()
    print("REAL CV DISTRIBUTION")
    if cvs:
        print(
            f"  n {len(cvs)}  min {min(cvs):.4f}  median {st.median(cvs):.4f}  max {max(cvs):.4f}"
        )
        pct = sum(1 for v in cvs if v < 0.20) / len(cvs)
        print(f"  the hardcoded 0.20 default sits at the {pct:.1%} percentile of measured CVs")
    print()
    print(f"STRONG_BUY LIQUIDITY GATE (> {gate}), BDVM-priceable positions only")
    print(f"  {'branch':<32}{'rows':>6}{'eligible':>10}")
    for label, d in branches.items():
        pct = (100.0 * d["eligible"] / d["rows"]) if d["rows"] else 0.0
        print(f"  {label:<32}{d['rows']:>6}{d['eligible']:>7} ({pct:5.1f}%)")

    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
