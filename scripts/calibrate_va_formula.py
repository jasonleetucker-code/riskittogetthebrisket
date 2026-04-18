#!/usr/bin/env python3
"""Re-fit the KTC-style Value Adjustment formula against a broader set
of observed KTC data points.

The 2-team VA formula in ``frontend/lib/trade-logic.js`` was originally
fit to 3 data points — all 1-vs-2 trades (single stud vs a 2-piece
bundle).  Three new 1-vs-3 data points exposed that the original fit
under-predicts consolidation premium when the multi-side has a
second high-value asset.  This script joint-fits SLOPE, INT, CAP, and
DECAY against all 6 observed points and reports error distributions
for a few candidate parameter sets.

The formula being fit:

    gapRatio  = (top_small - top_large) / top_small
    scarcity  = clamp(SLOPE * gapRatio - INT, 0, CAP)
    extras    = large.sort_desc()[small.count:]
    VA        = sum(extras[i] * scarcity * DECAY^i for i in range(len(extras)))

Run: ``python3 scripts/calibrate_va_formula.py``
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass


@dataclass(frozen=True)
class DataPoint:
    label: str
    single: float
    multi: tuple[float, ...]
    ktc_va: float

    @property
    def top_large(self) -> float:
        return max(self.multi)

    @property
    def gap_ratio(self) -> float:
        return (self.single - self.top_large) / self.single

    @property
    def extras(self) -> list[float]:
        # Sort desc, drop one to align with the single-side count.
        return sorted(self.multi, reverse=True)[1:]


# All 6 observed KTC Value Adjustment points.
# A-C: original 1-vs-2 points that fit the current formula within 3%.
# D-F: new 1-vs-3 points that expose the structural miss.
DATA: list[DataPoint] = [
    DataPoint("A", 9999, (7846, 5717), 3712),
    DataPoint("B", 7846, (5717, 4829), 3034),
    DataPoint("C", 7846, (6949, 5717), 1166),
    DataPoint("D", 4342, (2667, 2324, 1172), 1820),
    DataPoint("E", 7798, (4519, 4208, 2906), 3834),
    DataPoint("F", 9999, (7471, 4862, 2215), 4879),
]


def predict(pt: DataPoint, slope: float, intercept: float, cap: float, decay: float) -> float:
    raw = slope * pt.gap_ratio - intercept
    scarcity = max(0.0, min(cap, raw))
    total = 0.0
    for i, extra in enumerate(pt.extras):
        total += extra * scarcity * (decay ** i)
    return total


def errors(slope: float, intercept: float, cap: float, decay: float) -> list[tuple[str, float, float, float]]:
    """Return per-point (label, predicted, target, pct_error)."""
    rows = []
    for pt in DATA:
        pred = predict(pt, slope, intercept, cap, decay)
        err = (pred - pt.ktc_va) / pt.ktc_va
        rows.append((pt.label, pred, pt.ktc_va, err))
    return rows


def objective(
    slope: float, intercept: float, cap: float, decay: float,
    metric: str = "mean_abs_pct",
    max_pct_weight: float = 1.0,
) -> float:
    """Scalar loss over the 6 points.

    ``mean_abs_pct``   — mean of |pct_error| — easy to read, can hide a single large miss.
    ``rms_pct``        — root mean square pct error — penalizes outliers more.
    ``max_pct``        — worst-case pct error — minimizes the largest miss.
    ``blend``          — mean_abs + max_pct_weight * max_abs — tunable mix.
    """
    errs = [abs(row[3]) for row in errors(slope, intercept, cap, decay)]
    if metric == "mean_abs_pct":
        return sum(errs) / len(errs)
    if metric == "rms_pct":
        return (sum(e * e for e in errs) / len(errs)) ** 0.5
    if metric == "max_pct":
        return max(errs)
    if metric == "blend":
        return sum(errs) / len(errs) + max_pct_weight * max(errs)
    raise ValueError(f"unknown metric {metric!r}")


def grid_search(
    slope_range: tuple[float, float, int],
    int_range: tuple[float, float, int],
    cap_range: tuple[float, float, int],
    decay_range: tuple[float, float, int],
    metric: str = "rms_pct",
) -> dict:
    """Brute-force grid search; returns the best parameter set by ``metric``."""
    def _linspace(lo, hi, n):
        if n == 1:
            return [lo]
        step = (hi - lo) / (n - 1)
        return [lo + step * i for i in range(n)]

    slopes = _linspace(*slope_range)
    ints = _linspace(*int_range)
    caps = _linspace(*cap_range)
    decays = _linspace(*decay_range)

    best = None
    for slope, intercept, cap, decay in itertools.product(slopes, ints, caps, decays):
        loss = objective(slope, intercept, cap, decay, metric=metric)
        if best is None or loss < best["loss"]:
            best = {
                "loss": loss,
                "slope": slope,
                "intercept": intercept,
                "cap": cap,
                "decay": decay,
            }
    return best


def report(slope: float, intercept: float, cap: float, decay: float, title: str) -> None:
    print(f"\n=== {title} ===")
    print(f"  SLOPE={slope:.4f}  INT={intercept:.4f}  CAP={cap:.4f}  DECAY={decay:.4f}")
    rows = errors(slope, intercept, cap, decay)
    print(f"  {'case':<4} {'single':>6} {'top_multi':>9} {'gap':>7} "
          f"{'pred':>6} {'ktc':>5} {'err%':>7}")
    for (label, pred, ktc, err), pt in zip(rows, DATA):
        print(f"  {label:<4} {pt.single:>6.0f} {pt.top_large:>9.0f} "
              f"{pt.gap_ratio:>7.3f} {pred:>6.0f} {ktc:>5.0f} {err*100:>+6.2f}%")
    abs_errs = [abs(r[3]) for r in rows]
    print(f"  mean |err| = {sum(abs_errs)/len(abs_errs)*100:.2f}%,  "
          f"max |err| = {max(abs_errs)*100:.2f}%,  "
          f"rms |err| = {((sum(e*e for e in abs_errs)/len(abs_errs))**0.5)*100:.2f}%")


def main() -> None:
    # Baseline: current production values.
    report(4.27, 0.288, 0.64, 0.70, "CURRENT (production)")

    # Coarse grid pass to locate the basin of attraction.
    print("\nRunning coarse grid search ...")
    coarse = grid_search(
        slope_range=(3.0, 6.0, 16),    # steps of 0.2
        int_range=(0.1, 0.5, 9),        # steps of 0.05
        cap_range=(0.5, 0.9, 9),        # steps of 0.05
        decay_range=(0.5, 0.95, 10),    # steps of 0.05
        metric="rms_pct",
    )
    report(coarse["slope"], coarse["intercept"], coarse["cap"], coarse["decay"],
           "COARSE GRID BEST (rms_pct)")

    # Fine local refinement around the coarse winner.
    print("\nRunning fine grid refinement ...")
    fine = grid_search(
        slope_range=(coarse["slope"] - 0.25, coarse["slope"] + 0.25, 11),
        int_range=(max(0.0, coarse["intercept"] - 0.1), coarse["intercept"] + 0.1, 11),
        cap_range=(max(0.3, coarse["cap"] - 0.1), min(1.0, coarse["cap"] + 0.1), 11),
        decay_range=(max(0.3, coarse["decay"] - 0.08), min(1.0, coarse["decay"] + 0.08), 11),
        metric="rms_pct",
    )
    report(fine["slope"], fine["intercept"], fine["cap"], fine["decay"],
           "FINE GRID BEST (rms_pct)")

    # Also try minimizing the MAX error (minimax fit) — safer for
    # worst-case production behavior than minimizing the mean.
    print("\nRunning fine grid refinement (minimax) ...")
    mm = grid_search(
        slope_range=(coarse["slope"] - 0.25, coarse["slope"] + 0.25, 11),
        int_range=(max(0.0, coarse["intercept"] - 0.1), coarse["intercept"] + 0.1, 11),
        cap_range=(max(0.3, coarse["cap"] - 0.1), min(1.0, coarse["cap"] + 0.1), 11),
        decay_range=(max(0.3, coarse["decay"] - 0.08), min(1.0, coarse["decay"] + 0.08), 11),
        metric="max_pct",
    )
    report(mm["slope"], mm["intercept"], mm["cap"], mm["decay"],
           "FINE GRID BEST (minimax)")


if __name__ == "__main__":
    main()
