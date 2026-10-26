#!/usr/bin/env python3
"""Whole-dollar step evidence over the 250 seeded synthetic dynasty_main classes.

Read-only.  For every class whose largest-remainder rounding (Step A) breaks a
constraint, prints the violations, the picks the constrained minimum-deviation
step (Step B) changed with their dollar deltas, and the total / max deviation
from the reference curve; then an aggregate.  The seeds and class generator
are the test suite's (``tests/draft_valuation/test_curve_properties.py``).

Usage: ``python scripts/draft_valuation_whole_dollar_report.py``.  Exit 0.
"""

from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.draft.rookie_auction.curve import compute_curve  # noqa: E402
from tests.draft_valuation.test_curve_properties import SEEDS, _case  # noqa: E402


def main() -> int:
    methods: dict[str, int] = {}
    refused = []
    devs, maxes, sizes = [], [], []
    for seed in SEEDS:
        res = compute_curve(*_case(seed))
        w = res.whole_dollars
        if w is None:
            refused.append((seed, res.whole_dollars_refusal))
            continue
        methods[w.method] = methods.get(w.method, 0) + 1
        if w.method == "largest_remainder":
            continue
        labels = [r.label for r in res.rows]
        step_a_dev = sum(
            (abs(Fraction(a) - Fraction(u, 2)) for a, u in zip(w.step_a_dollars, res.units)),
            Fraction(0),
        )
        viol = ", ".join(
            f"{v.split('@')[0]}@{labels[int(v.split('@')[1])]}" if "@" in v else v
            for v in w.step_a_violations
        )
        reps = " ".join(f"{labels[i]}{d:+d}" for i, d in w.repairs)
        print(
            f"seed {seed}: Step A violations [{viol}]; repairs {len(w.repairs)} picks, "
            f"net {sum(d for _, d in w.repairs):+d}: {reps}; total deviation "
            f"{w.total_deviation} (Step A {step_a_dev}); max deviation {w.max_deviation}"
        )
        devs.append(w.total_deviation)
        maxes.append(w.max_deviation)
        sizes.append(len(w.repairs))
    print(f"\nmethods: {methods}; refused: {refused or 'none'}")
    if devs:
        print(
            f"recovered {len(devs)}: total deviation min {min(devs)} mean "
            f"{float(sum(devs) / len(devs)):.2f} max {max(devs)}; max per-pick deviation "
            f"{max(maxes)}; repaired picks per class {min(sizes)}-{max(sizes)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
