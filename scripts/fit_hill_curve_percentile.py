#!/usr/bin/env python3
"""Fit scope-level master Hill curves per the updated Final Framework.

Framework update (2026-04-20): value-based sources are the training
set for the rank-to-value conversion system.  Methodology:

  Step 1: For each value-based source j, fit its own implied
          rank-to-value curve f_j(p) where p = (r - 1) / (N_j - 1).
  Step 2: For each scope (global, offense, IDP), combine the per-
          source fits into a master curve V*_scope(p) by trimmed
          mean-median across the percentile grid.
  Step 3: Emit the master (c*, s*) for each scope.

Scope assignments (in the current registry):

  - GLOBAL:   IDPTradeCalc (combined offense + IDP pool)
  - OFFENSE:  KTC, DynastyDaddy, DynastyNerds (offense-only pools)
  - IDP:      IDPTradeCalc's IDP slice (the only value-based IDP source)

Replaces the previous "pooled fit" which weighted sources by their
data-point count.  Per-source-then-combine gives each source equal
voice, matching the framework's intent.

Usage:
    python3 scripts/fit_hill_curve_percentile.py
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Value-based sources grouped by scope.  Each entry: (csv_path,
# value_col, label).  The IDP scope is handled specially via
# _load_idptc_idp_values().
GLOBAL_SOURCES: dict[str, tuple[str, str]] = {
    "IDPTradeCalc": ("CSVs/site_raw/idpTradeCalc.csv", "value"),
}
OFFENSE_SOURCES: dict[str, tuple[str, str]] = {
    "KTC":          ("CSVs/site_raw/ktc.csv",               "value"),
    "DynastyDaddy": ("CSVs/site_raw/dynastyDaddySf.csv",    "value"),
    "DynastyNerds": ("CSVs/site_raw/dynastyNerdsSfTep.csv", "Value"),
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
    """IDPTC's IDP-slice values in descending order."""
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
    """Return [(p, normalized_v)] where normalized_v has top = 9999."""
    if len(values) < 2:
        return []
    top = values[0]
    n = len(values)
    return [((i) / (n - 1), values[i] / top * 9999.0) for i in range(n)]


def _hill(p: float, c: float, s: float) -> float:
    p = max(0.0, min(1.0, float(p)))
    if p == 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def _fit(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Grid-search + refine (c, s) against the pairs."""
    best: tuple[float, float, float] | None = None
    c_grid = [0.005 + 0.005 * i for i in range(100)]  # 0.005..0.5
    s_grid = [0.4 + 0.02 * i for i in range(106)]     # 0.4..2.5
    for c in c_grid:
        for s in s_grid:
            err = sum((v - _hill(p, c, s)) ** 2 for p, v in pairs)
            if best is None or err < best[0]:
                best = (err, c, s)
    assert best is not None
    err0, c0, s0 = best
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


def _trimmed_mean_median(values: list[float]) -> float:
    """Framework's step 9 blend: drop max+min, mean of (trimmed_mean,
    trimmed_median).  For n=2 returns mean; for n=1 returns passthrough.
    """
    if not values:
        return 0.0
    vs = sorted(values)
    n = len(vs)
    if n >= 3:
        t = vs[1:-1]
        t_mean = sum(t) / len(t)
        m = len(t)
        t_median = (
            float(t[m // 2])
            if m % 2 == 1
            else (t[m // 2 - 1] + t[m // 2]) / 2.0
        )
        return (t_mean + t_median) / 2.0
    if n == 2:
        return (vs[0] + vs[1]) / 2.0
    return vs[0]


def _fit_scope_master(
    scope_label: str,
    per_source_fits: list[tuple[str, float, float]],  # (label, c, s)
) -> tuple[float, float, float] | None:
    """Build a scope master curve from per-source fits.

    Framework step 5 combines per-source fitted curves into a
    "weighted market target" — the framework does not prescribe a
    specific aggregation rule for this step (the trimmed mean-median
    is for step 9, the subgroup combining).  We use the unweighted
    mean of per-source V_j(p) values at each percentile p.

    The mean (rather than trimmed mean-median) is the right rule
    here because:
      - With n=3 sources, trimmed mean-median degenerates to the
        middle source — it's not a blend, it's a single-source pick.
      - The mean treats every source equally, matching the framework's
        "weighted market target" intent.
      - Outlier curves can't skew the master very far because the
        Hill family is constrained.

    Rule:
      1. Generate a fine percentile grid.
      2. For each percentile, compute V_j(p) for every source in scope.
      3. V*(p) = mean(V_j(p)).
      4. Fit a single Hill against the (p, V*(p)) curve.
      5. Emit master (c*, s*).
    """
    if not per_source_fits:
        return None
    grid: list[float] = []
    for i in range(1, 50):
        grid.append(i / 2000.0)  # fine top-of-curve sampling
    for i in range(1, 200):
        grid.append(i / 200.0)   # linear mid-to-tail sampling
    grid = sorted(set(round(p, 6) for p in grid))

    master_pairs: list[tuple[float, float]] = []
    for p in grid:
        vals = [_hill(p, c, s) for _, c, s in per_source_fits]
        master_pairs.append((p, sum(vals) / len(vals)))

    c, s, mse = _fit(master_pairs)
    return c, s, mse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-old-style",
        action="store_true",
        help="Also print the legacy pooled fit for comparison",
    )
    args = parser.parse_args()

    def _fit_sources(
        sources: dict[str, tuple[str, str]],
        label_prefix: str = "",
    ) -> list[tuple[str, float, float]]:
        out: list[tuple[str, float, float]] = []
        for label, (rel_path, col) in sources.items():
            values = _load_values(REPO / rel_path, col)
            if not values:
                print(f"  {label_prefix}{label}: no values found")
                continue
            pairs = _percentile_pairs(values[:400])
            c, s, mse = _fit(pairs)
            out.append((label, c, s))
            print(
                f"  {label_prefix}{label:18s}  n={len(pairs):4d}  "
                f"c={c:.4f}  s={s:.3f}  rmse={mse ** 0.5:.1f}"
            )
        return out

    print("Per-source Hill fits:\n")
    print("OFFENSE scope (offense-only value sources):")
    offense_fits = _fit_sources(OFFENSE_SOURCES, "")

    print("\nGLOBAL scope (combined offense + IDP value sources):")
    global_fits = _fit_sources(GLOBAL_SOURCES, "")

    print("\nIDP scope (IDP value sources):")
    idp_values = _load_idptc_idp_values()
    idp_fits: list[tuple[str, float, float]] = []
    if idp_values:
        pairs = _percentile_pairs(idp_values)
        c, s, mse = _fit(pairs)
        idp_fits.append(("IDPTradeCalc-IDP", c, s))
        print(
            f"  IDPTradeCalc-IDP    n={len(pairs):4d}  c={c:.4f}  "
            f"s={s:.3f}  rmse={mse ** 0.5:.1f}"
        )
    else:
        print("  (no IDP value source data)")

    print("\nScope-level master curves (trimmed mean-median across per-source fits):")
    for scope_label, fits in (
        ("GLOBAL", global_fits),
        ("OFFENSE", offense_fits),
        ("IDP", idp_fits),
    ):
        result = _fit_scope_master(scope_label, fits)
        if result is None:
            print(f"  {scope_label:8s}  (no per-source fits)")
            continue
        c, s, mse = result
        print(
            f"  {scope_label:8s}  c*={c:.4f}  s*={s:.3f}  "
            f"master-fit rmse={mse ** 0.5:.1f}"
        )

    print()
    print("Value at key percentiles for each scope master:")
    ps = (0.0, 0.001, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
    print("  " + "scope".ljust(8) + "".join(f"{p:>9.3f}" for p in ps))
    for scope_label, fits in (
        ("GLOBAL", global_fits),
        ("OFFENSE", offense_fits),
        ("IDP", idp_fits),
    ):
        result = _fit_scope_master(scope_label, fits)
        if result is None:
            continue
        c, s, _ = result
        row = "".join(f"{int(_hill(p, c, s)):>9}" for p in ps)
        print(f"  {scope_label:<8}" + row)

    print()
    print("Suggested constants (src/canonical/player_valuation.py):")
    for scope_label, fits in (
        ("GLOBAL", global_fits),
        ("OFFENSE", offense_fits),
        ("IDP", idp_fits),
    ):
        result = _fit_scope_master(scope_label, fits)
        if result is None:
            continue
        c, s, _ = result
        prefix = "HILL_" + (scope_label + "_" if scope_label != "OFFENSE" else "")
        # Emit names that match the existing convention:
        # OFFENSE → HILL_PERCENTILE_C/S (already lives here)
        # IDP → IDP_HILL_PERCENTILE_C/S
        # GLOBAL → HILL_GLOBAL_PERCENTILE_C/S (new)
        if scope_label == "OFFENSE":
            print(f"HILL_PERCENTILE_C: float = {c:.4f}")
            print(f"HILL_PERCENTILE_S: float = {s:.3f}")
        elif scope_label == "IDP":
            print(f"IDP_HILL_PERCENTILE_C: float = {c:.4f}")
            print(f"IDP_HILL_PERCENTILE_S: float = {s:.3f}")
        else:
            print(f"HILL_GLOBAL_PERCENTILE_C: float = {c:.4f}")
            print(f"HILL_GLOBAL_PERCENTILE_S: float = {s:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
