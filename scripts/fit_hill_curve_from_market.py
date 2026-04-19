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

# IDP market sources.  IDPTradeCalc is the retail IDP authority and
# the blend backbone — we want the IDP Hill curve to reproduce its
# per-rank values directly, so our Hill(rank) output matches IDPTC
# BEFORE any per-position IDP calibration multiplier is applied.
# IDPTC's CSV is ``name,value`` for a combined offense+IDP+picks pool
# with no position column, so the ``--universe idp`` path loads a
# snapshot (``dynasty_data_*.json``) to filter to IDP-only rows and
# reads their IDPTC combined-pool ranks directly.  See
# ``_load_idptc_idp_pairs`` below.
IDP_SOURCES: dict[str, tuple[str, str]] = {
    "IDPTradeCalc-IDP": ("CSVs/site_raw/idpTradeCalc.csv", "value"),
}

# IDP positions recognised by the snapshot filter.  Mirrors
# ``src.utils.name_clean`` — kept local to the script to avoid a
# package import at fit time.
_IDP_POSITIONS: frozenset[str] = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "ILB", "OLB", "MLB", "DB", "CB", "S", "SS", "FS"}
)


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


def _load_idptc_idp_pairs() -> list[tuple[int, float]]:
    """Return (idptc_combined_pool_rank, idptc_value) for IDP players.

    IDPTC's CSV has no position column, so we load the most recent
    ``dynasty_data_*.json`` snapshot to borrow its sleeper positions
    map.  Ranks are IDPTC's actual combined-pool positions (not
    IDP-only ordinals) because that's what the blend feeds into the
    Hill curve at runtime.
    """
    import json

    snapshot_candidates = sorted(
        REPO.glob("dynasty_data_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not snapshot_candidates:
        return []
    with snapshot_candidates[0].open() as f:
        raw = json.load(f)
    positions = (raw.get("sleeper") or {}).get("positions") or {}

    all_rows: list[tuple[str, float]] = []
    for name, p in (raw.get("players") or {}).items():
        idptc_val = ((p or {}).get("_canonicalSiteValues") or {}).get("idpTradeCalc")
        try:
            v = float(idptc_val)
        except (TypeError, ValueError):
            continue
        if v > 0:
            all_rows.append((name, v))
    all_rows.sort(key=lambda t: -t[1])

    pairs: list[tuple[int, float]] = []
    for rank, (name, v) in enumerate(all_rows, start=1):
        pos = str(positions.get(name, "")).strip().upper()
        if pos in _IDP_POSITIONS:
            pairs.append((rank, v))
    return pairs


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
        # IDP universe: fit against IDPTC's IDP slice using combined-
        # pool ranks from the latest snapshot (no CSV-only position
        # column).  Hill output then mirrors IDPTC's raw values at
        # the same ranks the blend actually feeds in.
        if args.universe == "idp" and label == "IDPTradeCalc-IDP":
            pairs = _load_idptc_idp_pairs()
            if not pairs:
                print(f"  {label}: no snapshot found at dynasty_data_*.json")
                continue
            # Use raw IDPTC values (not normalised to 9999) — the top
            # IDP in IDPTC is nowhere near 9999 by design, and the
            # blend's Hill output should reproduce that shape.
            normed = list(pairs)
            m, s, mse = _fit(normed)
            fits.append((label, len(pairs), m, s, mse))
            print(
                f"  {label:18s}  n={len(pairs):4d}  midpoint={m:6.2f}  "
                f"slope={s:5.3f}  rmse={mse ** 0.5:.1f}"
            )
            continue
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
