"""Independent verifier for a whole-dollar allocation (runtime, production side).

``apportion.apportion_whole_dollars`` produces the published dollars with a
largest-remainder pass and, when that breaks a constraint, a BACKWARD
windowed dynamic programme.  This module checks a finished allocation with a
DIFFERENT exact method and shares no code with it:

* invariants — integers, exact total, non-increasing, per-pick floors / caps,
  reference sums to the total;
* optimality and tie-break — a FORWARD dynamic programme over
  (last value, running sum) minimising one scalarised big-integer objective
  ``deviation * M - sum_i d_i * (T + 1) ** (n - 1 - i)`` with
  ``M > (T + 1) ** n``, whose unique minimiser is the minimum-deviation
  allocation that is lexicographically largest.  States are pruned to
  deviation-so-far <= the allocation's own deviation, which keeps every
  allocation that could beat or tie it, so the check is exact.

Pure, stdlib-only.  The test suite's ``reference_workbook_formulas`` holds a
third, separately written copy of the same checks (plus brute force).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Sequence

__all__ = ["VERIFIER_NAME", "VerificationResult", "verify_whole_dollar_allocation"]

VERIFIER_NAME = "forward_scalarised_dp_v1"


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    failures: tuple[str, ...] = ()
    deviation: Fraction | None = None
    optimum: Fraction | None = None
    checks: tuple[str, ...] = field(default_factory=tuple)

    def receipt(self) -> dict[str, object]:
        return {
            "verifier": VERIFIER_NAME,
            "result": "pass" if self.ok else "fail",
            "failures": list(self.failures),
            "deviation": None if self.deviation is None else str(self.deviation),
            "optimum": None if self.optimum is None else str(self.optimum),
            "checks": list(self.checks),
        }


def _bounds(n, total, floors, caps):
    lo, run = [0] * n, 0
    for i in range(n - 1, -1, -1):
        run = max(run, int(floors[i]) if floors is not None and floors[i] is not None else 0)
        lo[i] = run
    hi, run = [total] * n, total
    for i in range(n):
        run = min(run, int(caps[i]) if caps is not None and caps[i] is not None else total)
        hi[i] = run
    return lo, hi


def verify_whole_dollar_allocation(
    reference: Sequence[Fraction],
    dollars: Sequence[int],
    total: int,
    *,
    floors: Sequence[int | None] | None = None,
    caps: Sequence[int | None] | None = None,
) -> VerificationResult:
    """Check ``dollars`` against ``reference`` and the constraints."""
    failures: list[str] = []
    checks = ["integers", "total", "non_increasing", "floors", "caps", "optimal_lexmax"]
    n = len(reference)
    if len(dollars) != n:
        return VerificationResult(False, (f"length {len(dollars)} != {n}",), checks=tuple(checks))
    ref = [Fraction(r) for r in reference]
    if sum(ref, Fraction(0)) != total:
        failures.append("reference_sum_not_total")
    if any(isinstance(d, bool) or not isinstance(d, int) for d in dollars):
        return VerificationResult(False, ("non_integer",), checks=tuple(checks))
    if sum(dollars) != total:
        failures.append("sum_not_total")
    for i in range(1, n):
        if dollars[i] > dollars[i - 1]:
            failures.append(f"rises@{i}")
    for i, d in enumerate(dollars):
        if d < 0:
            failures.append(f"negative@{i}")
        if floors is not None and floors[i] is not None and d < int(floors[i]):
            failures.append(f"below_floor@{i}")
        if caps is not None and caps[i] is not None and d > int(caps[i]):
            failures.append(f"above_cap@{i}")
    deviation = sum((abs(Fraction(d) - r) for d, r in zip(dollars, ref)), Fraction(0))
    if failures:
        return VerificationResult(False, tuple(failures), deviation, None, tuple(checks))

    den = math.lcm(*(r.denominator for r in ref))
    rs = [int(r * den) for r in ref]
    limit = int(deviation * den)
    lo, hi = _bounds(n, total, floors, caps)
    base = total + 1
    big = base**n + 1
    weight = [base ** (n - 1 - i) for i in range(n)]
    layers: list[dict] = [{(None, 0): (0, 0, None, None)}]
    for i in range(n):
        nxt: dict = {}
        for (last, run), (scal, dev, _p, _d) in layers[-1].items():
            top = min(hi[i], total - run) if last is None else min(hi[i], last, total - run)
            for d in range(lo[i], top + 1):
                step = abs(d * den - rs[i])
                ndev = dev + step
                if ndev > limit:
                    continue
                key = (d, run + d)
                s = scal + step * big - d * weight[i]
                cur = nxt.get(key)
                if cur is None or s < cur[0]:
                    nxt[key] = (s, ndev, (last, run), d)
        layers.append(nxt)
    finals = [(v[0], k) for k, v in layers[-1].items() if k[1] == total]
    if not finals:  # the allocation itself is in the window, so this cannot happen
        return VerificationResult(False, ("no_feasible_state",), deviation, None, tuple(checks))
    _, key = min(finals)
    best: list[int] = []
    opt_dev = layers[n][key][1]
    for i in range(n, 0, -1):
        _s, _dev, parent, d = layers[i][key]
        best.append(d)
        key = parent
    best.reverse()
    optimum = Fraction(opt_dev, den)
    if optimum != deviation:
        failures.append(f"not_minimum_deviation:{deviation}>{optimum}")
    elif best != list(dollars):
        failures.append("not_lexicographic_tie_break")
    return VerificationResult(not failures, tuple(failures), deviation, optimum, tuple(checks))
