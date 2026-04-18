#!/usr/bin/env python3
"""Calibrate the KTC-style Value Adjustment formula against all observed
KTC data points.

13 data points across 4 topologies (1-vs-2, 1-vs-3, 2-vs-3, 3-vs-5)
collected from the KTC trade calculator (Superflex, TEP=1).  The
original 3-point calibration from PR #82 fit a simple
top-gap-scarcity + exponential-decay formula; adding 10 more points
revealed the formula structurally under-predicts whenever (a) the
"extra" piece is a low-value throw-in or (b) many nearly-equal
pieces are being consolidated (3-vs-5 case).

This script:
    * Declares every data point as (small, large, observed_va).
    * Defines several candidate formula families.
    * Runs a brute-force grid search over the free parameters of each.
    * Reports per-case errors + aggregate statistics (mean, max, RMS).

Run: ``python3 scripts/calibrate_va_formula.py``

The frontend keeps its formula in ``frontend/lib/trade-logic.js``.  When
a winning candidate is found, port its predict() body over there and
update the pinned regression tests in
``frontend/__tests__/trade-logic.test.js``.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DataPoint:
    """Observed KTC Value Adjustment.

    ``small`` is the side with fewer pieces — the side that receives
    the VA.  ``large`` has more pieces.  Both are raw value lists in
    KTC's 1-9999 display scale.
    """
    label: str
    small: tuple[float, ...]
    large: tuple[float, ...]
    ktc_va: float
    topology: str = ""

    def sorted_small(self) -> list[float]:
        return sorted(self.small, reverse=True)

    def sorted_large(self) -> list[float]:
        return sorted(self.large, reverse=True)

    def top_gap(self) -> float:
        s = self.sorted_small()
        L = self.sorted_large()
        if not s or not L:
            return 0.0
        return max(0.0, (s[0] - L[0]) / s[0])

    def extras(self) -> list[float]:
        """Multi-side pieces beyond what the small side can pair with."""
        return self.sorted_large()[len(self.small):]

    def small_top(self) -> float:
        return self.sorted_small()[0] if self.small else 0.0


DATA: list[DataPoint] = [
    DataPoint("A", (9999,), (7846, 5717), 3712, "1v2"),
    DataPoint("B", (7846,), (5717, 4829), 3034, "1v2"),
    DataPoint("C", (7846,), (6949, 5717), 1166, "1v2"),
    DataPoint("D", (4342,), (2667, 2324, 1172), 1820, "1v3"),
    DataPoint("E", (7798,), (4519, 4208, 2906), 3834, "1v3"),
    DataPoint("F", (9999,), (7471, 4862, 2215), 4879, "1v3"),
    DataPoint("G", (7795,), (6883, 2950), 2077, "1v2"),
    DataPoint("H", (7795,), (5086, 4021, 2950), 3587, "1v3"),
    DataPoint("I", (9999,), (7813, 5086), 4103, "1v2"),
    DataPoint("J", (9999,), (7813, 3811, 2756), 4848, "1v3"),
    DataPoint("K", (7509,), (6737, 2179), 1887, "1v2"),
    DataPoint("L", (9999, 9983, 5086), (9603, 7687, 7298, 4206, 2670), 4586, "3v5"),
    DataPoint("M", (7795, 1914), (5086, 4021, 3943), 3371, "2v3"),
]


# ── Formula candidates ──────────────────────────────────────────────────
#
# Each predict function returns the predicted VA for one DataPoint
# given a params dict.  Signatures must match so the grid-search loop
# can iterate uniformly.

def predict_v1_current(pt: DataPoint, p: dict) -> float:
    """V1 (current production): top-gap scarcity * exponential-decay extras."""
    top_gap = pt.top_gap()
    raw = p["slope"] * top_gap - p["intercept"]
    scarcity = max(0.0, min(p["cap"], raw))
    total = 0.0
    for i, extra in enumerate(pt.extras()):
        total += extra * scarcity * (p["decay"] ** i)
    return total


def predict_v2_per_extra(pt: DataPoint, p: dict) -> float:
    """V2: per-extra scarcity based on each extra's own gap ratio.

    Each extra gets a scarcity from ``(single - extra) / single`` — a
    bigger gap means more consolidation premium on that piece.  No
    decay; each piece's contribution is fully independent.
    """
    small_top = pt.small_top()
    total = 0.0
    for extra in pt.extras():
        gap = max(0.0, (small_top - extra) / small_top) if small_top else 0.0
        scarcity = max(0.0, min(p["cap"], p["slope"] * gap - p["intercept"]))
        total += extra * scarcity
    return total


def predict_v3_hybrid(pt: DataPoint, p: dict) -> float:
    """V3: top-gap scarcity modulated per-extra by extras-ratio.

    Idea: the top-gap scarcity sets a ceiling, but each extra's
    effective weight scales up (toward 1.0) as the extra becomes more
    "filler" (smaller relative to the single).

        effective_i = top_scarcity + boost * max(0, extra_gap_i - top_gap)

    where ``extra_gap_i = (small_top - extra_i) / small_top``.  This
    reduces to V1 when all extras are near the top-large value.
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    top_scarcity = max(0.0, min(p["cap"], p["slope"] * top_gap - p["intercept"]))
    total = 0.0
    for i, extra in enumerate(pt.extras()):
        if small_top > 0:
            extra_gap = max(0.0, (small_top - extra) / small_top)
        else:
            extra_gap = 0.0
        effective = top_scarcity + p["boost"] * max(0.0, extra_gap - top_gap)
        effective = max(0.0, min(p["effective_cap"], effective))
        total += extra * effective * (p["decay"] ** i)
    return total


def predict_v4_additive(pt: DataPoint, p: dict) -> float:
    """V4: additive model — base floor + top_gap term + (1 - extras_ratio) term.

    For each extra, effective weight is::

        w_i = floor + alpha * top_gap + beta * (1 - extra_i / small_top)

    Clamped to [0, cap].  Captures the insight that smaller extras
    carry a HIGHER consolidation premium (lower extras_ratio → higher
    w_i from the beta term), while still responding to top-gap for
    overall magnitude.
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    total = 0.0
    for i, extra in enumerate(pt.extras()):
        ratio = (extra / small_top) if small_top else 1.0
        w = p["floor"] + p["alpha"] * top_gap + p["beta"] * max(0.0, 1 - ratio)
        w = max(0.0, min(p["cap"], w))
        total += extra * w * (p["decay"] ** i)
    return total


def predict_v5_additive_with_roster(pt: DataPoint, p: dict) -> float:
    """V5: V4 + a roster-slot baseline that doesn't vanish at top_gap=0.

    Same as V4 but the floor is a flat addition that survives even
    when top_gap and extras_ratio both push the weight down.  Designed
    to salvage case L (3v5 with near-equal tops, all pieces bulky).
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    total = 0.0
    for i, extra in enumerate(pt.extras()):
        ratio = (extra / small_top) if small_top else 1.0
        # Additive terms.
        w = p["floor"] + p["alpha"] * top_gap + p["beta"] * max(0.0, 1 - ratio)
        w = max(p["min_weight"], min(p["cap"], w))
        total += extra * w * (p["decay"] ** i)
    return total


# ── Scoring + grid search ───────────────────────────────────────────────

def errors(predict_fn, params: dict) -> list[tuple[str, float, float, float, str]]:
    rows = []
    for pt in DATA:
        pred = predict_fn(pt, params)
        err = (pred - pt.ktc_va) / pt.ktc_va
        rows.append((pt.label, pred, pt.ktc_va, err, pt.topology))
    return rows


def objective(predict_fn, params: dict, metric: str = "rms") -> float:
    errs = [abs(r[3]) for r in errors(predict_fn, params)]
    if metric == "mean":
        return sum(errs) / len(errs)
    if metric == "rms":
        return (sum(e * e for e in errs) / len(errs)) ** 0.5
    if metric == "max":
        return max(errs)
    if metric == "blend":  # mean + worst/4
        return sum(errs) / len(errs) + max(errs) / 4
    raise ValueError(metric)


def report(predict_fn, params: dict, title: str) -> None:
    print(f"\n=== {title} ===")
    print(f"  params: {params}")
    rows = errors(predict_fn, params)
    print(f"  {'case':<4} {'topo':>5} {'pred':>6} {'ktc':>6} {'err%':>8}")
    for label, pred, ktc, err, topo in rows:
        print(f"  {label:<4} {topo:>5} {pred:>6.0f} {ktc:>6.0f} {err*100:>+7.2f}%")
    abs_errs = [abs(r[3]) for r in rows]
    mean = sum(abs_errs) / len(abs_errs) * 100
    mx = max(abs_errs) * 100
    rms = ((sum(e * e for e in abs_errs) / len(abs_errs)) ** 0.5) * 100
    over_10 = sum(1 for e in abs_errs if e > 0.10)
    over_20 = sum(1 for e in abs_errs if e > 0.20)
    print(f"  mean |err|={mean:5.2f}%  max={mx:5.2f}%  rms={rms:5.2f}%  "
          f"(>10%: {over_10}, >20%: {over_20})")


def grid_search(predict_fn, param_grid: dict[str, list], metric: str = "rms") -> dict:
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    best = None
    count = 0
    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        loss = objective(predict_fn, params, metric=metric)
        count += 1
        if best is None or loss < best["loss"]:
            best = {"loss": loss, "params": params}
    return best


def _linspace(lo, hi, n):
    if n == 1:
        return [lo]
    return [lo + (hi - lo) / (n - 1) * i for i in range(n)]


# ── Main ────────────────────────────────────────────────────────────────
def main() -> None:
    # V1 — CURRENT PRODUCTION FORMULA.
    v1_prod = {"slope": 4.27, "intercept": 0.288, "cap": 0.64, "decay": 0.70}
    report(predict_v1_current, v1_prod, "V1 (current production)")

    # V1 best refit — establish baseline for what the current formula
    # family can achieve against all 13 points.
    print("\n--- V1 grid refit ---")
    v1_best = grid_search(
        predict_v1_current,
        {
            "slope": _linspace(3.0, 6.0, 16),
            "intercept": _linspace(0.10, 0.50, 9),
            "cap": _linspace(0.45, 0.85, 9),
            "decay": _linspace(0.40, 0.95, 12),
        },
        metric="rms",
    )
    report(predict_v1_current, v1_best["params"], "V1 best refit (RMS)")

    # V2 — per-extra scarcity.
    print("\n--- V2 grid refit ---")
    v2_best = grid_search(
        predict_v2_per_extra,
        {
            "slope": _linspace(0.3, 1.6, 14),
            "intercept": _linspace(-0.3, 0.3, 13),
            "cap": _linspace(0.30, 0.90, 13),
        },
        metric="rms",
    )
    report(predict_v2_per_extra, v2_best["params"], "V2 per-extra scarcity (RMS)")

    # V3 — hybrid with boost on sub-top extras.
    print("\n--- V3 grid refit ---")
    v3_best = grid_search(
        predict_v3_hybrid,
        {
            "slope": _linspace(3.0, 6.0, 7),
            "intercept": _linspace(0.10, 0.45, 8),
            "cap": _linspace(0.45, 0.80, 8),
            "decay": _linspace(0.45, 0.95, 6),
            "boost": _linspace(0.0, 2.0, 11),
            "effective_cap": _linspace(0.50, 1.20, 8),
        },
        metric="rms",
    )
    report(predict_v3_hybrid, v3_best["params"], "V3 hybrid (RMS)")

    # V4 — additive model (floor + alpha*top_gap + beta*(1-ratio)).
    print("\n--- V4 grid refit ---")
    v4_best = grid_search(
        predict_v4_additive,
        {
            "floor": _linspace(-0.3, 0.4, 15),
            "alpha": _linspace(-0.5, 2.0, 11),
            "beta": _linspace(0.0, 2.0, 11),
            "cap": _linspace(0.50, 1.20, 8),
            "decay": _linspace(0.5, 1.0, 6),
        },
        metric="rms",
    )
    report(predict_v4_additive, v4_best["params"], "V4 additive (RMS)")

    # V5 — V4 with flat minimum weight (to rescue case L).
    print("\n--- V5 grid refit ---")
    v5_best = grid_search(
        predict_v5_additive_with_roster,
        {
            "floor": _linspace(-0.3, 0.4, 8),
            "alpha": _linspace(-0.5, 2.0, 6),
            "beta": _linspace(0.0, 2.0, 6),
            "cap": _linspace(0.6, 1.1, 6),
            "decay": _linspace(0.5, 1.0, 6),
            "min_weight": _linspace(0.0, 0.3, 7),
        },
        metric="rms",
    )
    report(predict_v5_additive_with_roster, v5_best["params"], "V5 additive + roster floor (RMS)")

    # Summary ranking.
    print("\n=== CANDIDATE RANKING (by RMS) ===")
    candidates = [
        ("V1 prod", predict_v1_current, v1_prod),
        ("V1 refit", predict_v1_current, v1_best["params"]),
        ("V2", predict_v2_per_extra, v2_best["params"]),
        ("V3", predict_v3_hybrid, v3_best["params"]),
        ("V4", predict_v4_additive, v4_best["params"]),
        ("V5", predict_v5_additive_with_roster, v5_best["params"]),
    ]
    for name, fn, params in candidates:
        errs = [abs(r[3]) for r in errors(fn, params)]
        mean = sum(errs) / len(errs) * 100
        mx = max(errs) * 100
        rms = ((sum(e * e for e in errs) / len(errs)) ** 0.5) * 100
        over_10 = sum(1 for e in errs if e > 0.10)
        over_20 = sum(1 for e in errs if e > 0.20)
        print(f"  {name:<10}  rms={rms:5.2f}%  mean={mean:5.2f}%  max={mx:5.2f}%  "
              f">10%: {over_10}/13  >20%: {over_20}/13")


if __name__ == "__main__":
    main()
