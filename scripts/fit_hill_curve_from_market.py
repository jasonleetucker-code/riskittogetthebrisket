#!/usr/bin/env python3
"""Fit the Hill curve (midpoint, slope) to average market source values.

Loads per-source value CSVs from ``CSVs/site_raw/`` — KTC, IDPTradeCalc,
DynastyNerds (SF TEP), DynastyDaddy (SF) — normalises each source so
its top player = 9999, grid-searches a Hill curve per source, then
reports the simple mean + n-weighted mean of (midpoint, slope).

Use the output to update ``src/canonical/player_valuation.py`` constants
``HILL_MIDPOINT`` / ``HILL_SLOPE`` (offense) or ``IDP_HILL_MIDPOINT`` /
``IDP_HILL_SLOPE`` (IDP) when the community's dropoff shape drifts from
ours.

Usage:
    python3 scripts/fit_hill_curve_from_market.py          # offense (default)
    python3 scripts/fit_hill_curve_from_market.py --universe idp
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

OFFENSE_SOURCES: dict[str, tuple[str, str]] = {
    "KTC":          ("CSVs/site_raw/ktc.csv",                 "value"),
    "IDPTradeCalc": ("CSVs/site_raw/idpTradeCalc.csv",        "value"),
    "DynastyDaddy": ("CSVs/site_raw/dynastyDaddySf.csv",      "value"),
    "DynastyNerds": ("CSVs/site_raw/dynastyNerdsSfTep.csv",   "Value"),
}

# IDP market sources.  FantasyPros IDP exposes a pre-normalized 1-9999
# ``normalizedValue`` column straight from its dynasty IDP expert
# consensus, so the fit works off published IDP pricing directly.
# IDPTradeCalc's raw ``value`` column mixes offense + IDP + picks, but
# the IDP entries always cluster below 7500 on its scale — cap the
# slice at row 200 to approximate "IDP-only" without a position column.
IDP_SOURCES: dict[str, tuple[str, str]] = {
    "FantasyProsIDP": ("CSVs/site_raw/fantasyProsIdp.csv", "normalizedValue"),
}


def _load_values(path: Path, col: str) -> list[float]:
    vs: list[float] = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            raw = r.get(col)
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if v > 0:
                vs.append(v)
    vs.sort(reverse=True)
    return vs


def _hill(rank: float, midpoint: float, slope: float) -> float:
    rank = max(1.0, float(rank))
    return 1.0 + 9998.0 / (1.0 + ((rank - 1.0) / midpoint) ** slope)


def _fit(normed_points: list[tuple[int, float]]) -> tuple[float, float, float]:
    """Grid-search + refine (midpoint, slope) minimising MSE."""
    best: tuple[float, float, float] | None = None
    for m_i in range(20, 201, 1):
        m = float(m_i)
        for s_i in range(40, 251, 2):
            s = s_i / 100.0
            err = sum((v - _hill(r, m, s)) ** 2 for r, v in normed_points)
            if best is None or err < best[0]:
                best = (err, m, s)
    assert best is not None
    # Fine refinement
    err0, m0, s0 = best
    for dm in (-0.5, -0.25, 0.0, 0.25, 0.5):
        for ds in (-0.01, -0.005, 0.0, 0.005, 0.01):
            m = m0 + dm
            s = s0 + ds
            err = sum((v - _hill(r, m, s)) ** 2 for r, v in normed_points)
            if err < best[0]:
                best = (err, m, s)
    return best[1], best[2], best[0] / len(normed_points)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--universe", choices=["offense", "idp"], default="offense",
        help="Which market to fit (default: offense)",
    )
    args = parser.parse_args()

    sources = OFFENSE_SOURCES if args.universe == "offense" else IDP_SOURCES
    print(f"Fitting Hill curve to {len(sources)} {args.universe} market sources …")
    print()
    fits: list[tuple[str, int, float, float, float]] = []
    for label, (rel_path, col) in sources.items():
        values = _load_values(REPO / rel_path, col)
        if not values:
            print(f"  {label}: no values found at {rel_path}")
            continue
        top = values[0]
        normed = [(i + 1, v / top * 9999.0) for i, v in enumerate(values[:300])]
        m, s, mse = _fit(normed)
        fits.append((label, len(values), m, s, mse))
        print(f"  {label:14s}  n={len(values):4d}  midpoint={m:6.2f}  slope={s:5.3f}  mse/pt={mse:.1f}")

    if not fits:
        print("No sources loaded; aborting.")
        return 1

    total = sum(n for _, n, *_ in fits)
    simple_m = sum(m for *_, _m, _s, _ in () or ()) or 0.0
    simple_m = sum(m for _, _, m, _, _ in fits) / len(fits)
    simple_s = sum(s for _, _, _, s, _ in fits) / len(fits)
    weighted_m = sum(n * m for _, n, m, _, _ in fits) / total
    weighted_s = sum(n * s for _, n, _, s, _ in fits) / total

    print()
    print(f"  {'Simple mean':14s}                   midpoint={simple_m:6.2f}  slope={simple_s:5.3f}")
    print(f"  {'n-Weighted':14s}                   midpoint={weighted_m:6.2f}  slope={weighted_s:5.3f}")
    print(f"  {'Current (ours)':14s}                   midpoint=45.00          slope=1.100")

    print()
    print("Value at key ranks (top=9999):")
    ranks = (1, 5, 10, 25, 50, 75, 100, 150, 200, 300)
    header = f"  {'rank':>4}" + "".join(f"{r:>9}" for r in ranks)
    print(header)
    for label, _, m, s, _ in fits:
        row = "".join(f"{int(_hill(r, m, s)):>9}" for r in ranks)
        print(f"  {label[:14]:<14}" + row)
    print(f"  {'SIMPLE_AVG':<14}" + "".join(f"{int(_hill(r, simple_m, simple_s)):>9}" for r in ranks))
    print(f"  {'N_WEIGHTED':<14}" + "".join(f"{int(_hill(r, weighted_m, weighted_s)):>9}" for r in ranks))
    print(f"  {'CURRENT':<14}" + "".join(f"{int(_hill(r, 45, 1.1)):>9}" for r in ranks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
