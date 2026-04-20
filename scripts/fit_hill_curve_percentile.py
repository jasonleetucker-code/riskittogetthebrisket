#!/usr/bin/env python3
"""Fit the Final Framework Hill curve against percentile-transformed input.

Replaces the rank-based fit in ``fit_hill_curve_from_market.py`` with
the framework's step-2→3 formulation:

    p = (r − 1) / (N − 1)
    V(p) = 9999 / (1 + (p / c)^s)

where N is the SOURCE's native pool size.  Each value-based market
source contributes (p, normalized_v) pairs where normalized_v is
scaled so the source's top player = 9999.  We combine all sources'
pairs into one dataset and fit a single global (c, s) via grid search.

This is the right fit methodology for the Final Framework's
percentile-per-native-source approach: each source's top rank always
maps to p=0 → V=9999, and each source's bottom rank maps to p=1 → V
at some low value set by (c, s).

Usage:
    python3 scripts/fit_hill_curve_percentile.py
    python3 scripts/fit_hill_curve_percentile.py --universe idp
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Offense value-based sources. Each entry is (csv_path, value_col).
OFFENSE_SOURCES: dict[str, tuple[str, str]] = {
    "KTC":          ("CSVs/site_raw/ktc.csv",               "value"),
    "IDPTradeCalc": ("CSVs/site_raw/idpTradeCalc.csv",      "value"),
    "DynastyDaddy": ("CSVs/site_raw/dynastyDaddySf.csv",    "value"),
    "DynastyNerds": ("CSVs/site_raw/dynastyNerdsSfTep.csv", "Value"),
}

# IDP value-based sources. IDPTradeCalc is the only IDP backbone with
# a true native value; we fit its IDP slice separately from offense.
IDP_SOURCES: dict[str, tuple[str, str]] = {
    "IDPTradeCalc-IDP": ("CSVs/site_raw/idpTradeCalc.csv", "value"),
}

_IDP_POSITIONS: frozenset[str] = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "ILB", "OLB", "MLB",
     "DB", "CB", "S", "SS", "FS"}
)


def _load_values(path: Path, col: str) -> list[float]:
    vs: list[float] = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            raw = r.get(col)
            try:
                v = float(raw) if raw else 0.0
            except (TypeError, ValueError):
                continue
            if v > 0:
                vs.append(v)
    vs.sort(reverse=True)
    return vs


def _load_idptc_idp_values() -> list[float]:
    """Return IDPTC's IDP-only values, sorted desc, using the latest
    snapshot's sleeper positions map to filter to IDP rows.
    """
    import json

    candidates = sorted(
        (REPO / "data").glob("dynasty_data_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return []
    with candidates[0].open() as f:
        raw = json.load(f)
    positions = (raw.get("sleeper") or {}).get("positions") or {}
    vs: list[float] = []
    for name, p in (raw.get("players") or {}).items():
        pos = str(positions.get(name, "")).strip().upper()
        if pos not in _IDP_POSITIONS:
            continue
        v = (p or {}).get("idpTradeCalc")
        try:
            vf = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            continue
        if vf > 0:
            vs.append(vf)
    vs.sort(reverse=True)
    return vs


def _percentile_pairs(values: list[float]) -> list[tuple[float, float]]:
    """Return [(p, normalized_v)] where p = (i)/(N-1) for i in 0..N-1
    and normalized_v = values[i] / values[0] * 9999.
    """
    if len(values) < 2:
        return []
    top = values[0]
    n = len(values)
    return [
        ((i) / (n - 1), values[i] / top * 9999.0)
        for i in range(n)
    ]


def _hill(p: float, c: float, s: float) -> float:
    p = max(0.0, min(1.0, float(p)))
    if p == 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def _fit(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Grid-search + refine (c, s) minimising MSE on the pairs."""
    best: tuple[float, float, float] | None = None
    # c ∈ (0, 1) — midpoint in percentile space.  0.01..0.5 in 0.005
    # steps covers the plausible range comfortably.
    c_grid = [0.005 + 0.005 * i for i in range(100)]  # 0.005 .. 0.5
    s_grid = [0.4 + 0.02 * i for i in range(106)]     # 0.4  .. 2.5
    for c in c_grid:
        for s in s_grid:
            err = sum((v - _hill(p, c, s)) ** 2 for p, v in pairs)
            if best is None or err < best[0]:
                best = (err, c, s)
    assert best is not None
    err0, c0, s0 = best
    # Fine refinement
    for dc in (-0.002, -0.001, 0.0, 0.001, 0.002):
        for ds in (-0.01, -0.005, 0.0, 0.005, 0.01):
            c = c0 + dc
            s = s0 + ds
            if c <= 0 or s <= 0:
                continue
            err = sum((v - _hill(p, c, s)) ** 2 for p, v in pairs)
            if err < best[0]:
                best = (err, c, s)
    return best[1], best[2], best[0] / len(pairs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--universe", choices=["offense", "idp"], default="offense",
    )
    args = parser.parse_args()

    sources = OFFENSE_SOURCES if args.universe == "offense" else IDP_SOURCES
    print(f"Fitting percentile Hill curve to {len(sources)} "
          f"{args.universe} sources …\n")
    all_pairs: list[tuple[float, float]] = []
    per_source_fits: list[tuple[str, int, float, float, float]] = []

    for label, (rel_path, col) in sources.items():
        if args.universe == "idp" and label == "IDPTradeCalc-IDP":
            values = _load_idptc_idp_values()
        else:
            values = _load_values(REPO / rel_path, col)
        if not values:
            print(f"  {label}: no values found")
            continue
        pairs = _percentile_pairs(values[:400])  # top 400 per source
        c, s, mse = _fit(pairs)
        per_source_fits.append((label, len(pairs), c, s, mse))
        all_pairs.extend(pairs)
        print(f"  {label:18s}  n={len(pairs):4d}  c={c:.4f}  s={s:.3f}  "
              f"rmse={mse ** 0.5:.1f}")

    if not per_source_fits:
        print("No sources loaded; aborting.")
        return 1

    # Combined fit across all source pairs (what we actually adopt).
    print(f"\n  Combined fit across {len(all_pairs)} points:")
    combined_c, combined_s, combined_mse = _fit(all_pairs)
    print(f"  {'COMBINED':18s}              c={combined_c:.4f}  s={combined_s:.3f}  "
          f"rmse={combined_mse ** 0.5:.1f}")

    # Per-source simple-average fit (alt reference).
    simple_c = sum(c for _, _, c, _, _ in per_source_fits) / len(per_source_fits)
    simple_s = sum(s for _, _, _, s, _ in per_source_fits) / len(per_source_fits)
    print(f"  {'SIMPLE_AVG':18s}              c={simple_c:.4f}  s={simple_s:.3f}")

    # Reference values at key percentiles.
    print("\nValue at key percentiles:")
    ps = (0.0, 0.001, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
    print("  " + "".join(f"{p:>9.3f}" for p in ps))
    print("  " + "".join(f"{int(_hill(p, combined_c, combined_s)):>9}" for p in ps))

    # Suggested constant names.
    print()
    if args.universe == "offense":
        print(f"HILL_PERCENTILE_C: float = {combined_c:.4f}")
        print(f"HILL_PERCENTILE_S: float = {combined_s:.3f}")
    else:
        print(f"IDP_HILL_PERCENTILE_C: float = {combined_c:.4f}")
        print(f"IDP_HILL_PERCENTILE_S: float = {combined_s:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
