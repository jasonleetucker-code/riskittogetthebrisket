"""Whole-dollar apportionment — the final step of the rookie-auction curve.

Owner decisions 2026-10-18: the ``dynasty_main`` rookie auction uses WHOLE
DOLLARS ONLY.  The spreadsheet curve at its original precision is the
reference (``referenceDollars``); the published, spendable values
(``finalWholeDollars``) come from this separately identified step.

**Step A — largest remainder** (used unchanged whenever it satisfies every
constraint, so existing outputs never move):

a) floor every exact value to whole dollars;
b) ``residual = total - sum(floors)`` (an exact integer);
c) the ``residual`` largest fractional remainders get +1 — ties go to the
   EARLIER index (the higher draft position).

**Step B — constrained minimum deviation** (only when Step A breaks a
constraint).  Solves exactly::

    minimise   sum_i |d_i - r_i|          (total absolute deviation from the
                                           reference r)
    subject to d_i integer,  sum_i d_i = total,
               floor_i <= d_i <= cap_i,  d_i >= d_{i+1}

and among equally optimal allocations takes the lexicographically LARGEST
``d`` (more dollars at earlier draft positions).  Method: an exact backward
dynamic programme over (position, value, remaining budget), restricted to a
window of half-width ``D`` dollars around the reference.  The window is
lossless whenever the optimum is ``<= D`` — an allocation with total
deviation ``<= D`` has every per-pick deviation and every prefix-sum
deviation ``<= D`` — so ``D`` is doubled until the programme's optimum is
``<= D``; that optimum is then the global optimum, and the tie-break is global
too, because every equally optimal allocation lies inside the window.  The
reconstruction walks forward taking the largest value that keeps the optimal
cost.

**Refusal** happens only for bad data (missing / non-finite / float /
negative values, a reference that does not sum to ``total``) or a genuinely
INFEASIBLE constraint system.  Feasibility is decided exactly before Step B:
with ``lo_i = max(floor_j, j >= i)`` and ``hi_i = min(cap_j, j <= i)`` (the
bounds non-increasing order implies), a feasible allocation exists iff
``lo_i <= hi_i`` for every ``i`` and ``sum(lo) <= total <= sum(hi)`` — the
sums of non-increasing integer vectors inside those bounds form a contiguous
range.  The refusal names the binding constraint.  The total is never
changed.  There is no last-known-good store here: a refusal propagates, and
the consumer (PR #1785) refuses the board with ``draft_dollars_refused``.

Exact arithmetic only (``Fraction`` / integers).  Pure, stdlib-only, no I/O.
Stable entry point for PR #1785::

    from src.draft.rookie_auction.apportion import apportion_whole_dollars
    result = apportion_whole_dollars(values, 1200, floors=..., caps=...)
    result.dollars                     # tuple[int, ...] — finalWholeDollars
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Sequence

__all__ = [
    "METHOD_CONSTRAINED",
    "METHOD_LARGEST_REMAINDER",
    "OBJECTIVE",
    "ApportionmentRefused",
    "WholeDollarApportionment",
    "apportion_whole_dollars",
]

METHOD_LARGEST_REMAINDER = "largest_remainder"
METHOD_CONSTRAINED = "constrained_min_deviation"
OBJECTIVE = (
    "minimise sum_i |d_i - r_i| subject to integer d, sum d = total, floor_i <= d_i <= cap_i, "
    "d_i >= d_(i+1); ties: lexicographically largest d (earlier picks first)"
)


class ApportionmentRefused(ValueError):
    """The values cannot be apportioned to whole dollars under the constraints."""

    def __init__(self, conflict: str, detail: str = "") -> None:
        super().__init__(f"{conflict}: {detail}" if detail else conflict)
        self.conflict = conflict


@dataclass(frozen=True)
class WholeDollarApportionment:
    dollars: tuple[int, ...]  # the published finalWholeDollars
    floored: tuple[int, ...]  # Step A: floors
    remainders: tuple[Fraction, ...]  # Step A: fractional remainders
    residual: int  # Step A: total - sum(floors)
    plus_one_indices: tuple[int, ...]  # Step A: who got +1
    total: int
    method: str = METHOD_LARGEST_REMAINDER
    step_a_dollars: tuple[int, ...] = ()
    step_a_violations: tuple[str, ...] = ()
    #: (index, final - step A) for every pick Step B changed.
    repairs: tuple[tuple[int, int], ...] = ()
    total_deviation: Fraction = Fraction(0)
    max_deviation: Fraction = Fraction(0)
    #: Constraints holding with equality at a repaired pick.
    binding_constraints: tuple[str, ...] = ()

    def receipt(self, labels: Sequence[str] | None = None) -> dict[str, object]:
        def name(i: int) -> object:
            return labels[i] if labels is not None else i

        return {
            "method": self.method,
            "objective": OBJECTIVE,
            "objectiveValue": str(self.total_deviation),
            "maxDeviation": str(self.max_deviation),
            "total": self.total,
            "flooredSum": sum(self.floored),
            "residual": self.residual,
            "plusOne": [name(i) for i in self.plus_one_indices],
            "stepAViolations": list(self.step_a_violations),
            "repairs": [{"pick": name(i), "delta": d} for i, d in self.repairs],
            "bindingConstraints": list(self.binding_constraints),
            "finalWholeDollars": list(self.dollars),
        }


def _exact(value: object, index: int) -> Fraction:
    if value is None:
        raise ApportionmentRefused("missing_value", f"index {index} (missing is never zero)")
    if isinstance(value, bool):
        raise ApportionmentRefused("not_a_number", f"index {index}: {value!r}")
    if isinstance(value, float):
        raise ApportionmentRefused("float_input", f"index {index}: pass Decimal/Fraction/int/str")
    try:
        if isinstance(value, Fraction):
            f = value
        elif isinstance(value, int):
            f = Fraction(value)
        elif isinstance(value, Decimal):
            if not value.is_finite():
                raise ApportionmentRefused("non_finite", f"index {index}: {value!r}")
            f = Fraction(value)
        elif isinstance(value, str):
            d = Decimal(value.strip())
            if not d.is_finite():
                raise ApportionmentRefused("non_finite", f"index {index}: {value!r}")
            f = Fraction(d)
        else:
            raise ApportionmentRefused("not_a_number", f"index {index}: {type(value).__name__}")
    except (ArithmeticError, ValueError) as exc:
        if isinstance(exc, ApportionmentRefused):
            raise
        raise ApportionmentRefused("not_a_number", f"index {index}: {value!r}") from exc
    if f < 0:
        raise ApportionmentRefused("negative_value", f"index {index}: {f}")
    return f


def _violations(dollars, total, floors, caps) -> list[str]:
    out: list[str] = []
    if sum(dollars) != total:
        out.append(f"sum_not_total:{sum(dollars)}")
    for i in range(1, len(dollars)):
        if dollars[i] > dollars[i - 1]:
            out.append(f"not_non_increasing@{i}")
    for i, d in enumerate(dollars):
        if floors is not None and floors[i] is not None and d < int(floors[i]):
            out.append(f"below_floor@{i}")
        if caps is not None and caps[i] is not None and d > int(caps[i]):
            out.append(f"above_cap@{i}")
    return out


def _monotone_bounds(n: int, total: int, floors, caps) -> tuple[list[int], list[int]]:
    lo = [0] * n
    run = 0
    for i in range(n - 1, -1, -1):
        f = int(floors[i]) if floors is not None and floors[i] is not None else 0
        run = max(run, f)
        lo[i] = run
    hi = [total] * n
    run = total
    for i in range(n):
        c = int(caps[i]) if caps is not None and caps[i] is not None else total
        run = min(run, c)
        hi[i] = run
    return lo, hi


def _check_feasible(total: int, lo: list[int], hi: list[int]) -> None:
    for i in range(len(lo)):
        if lo[i] > hi[i]:
            raise ApportionmentRefused(
                "infeasible",
                f"index {i}: a floor at or after it ({lo[i]}) exceeds a cap at or "
                f"before it ({hi[i]}) under non-increasing order",
            )
    if sum(lo) > total:
        raise ApportionmentRefused("infeasible", f"monotone floors need {sum(lo)} > total {total}")
    if sum(hi) < total:
        raise ApportionmentRefused("infeasible", f"monotone caps allow {sum(hi)} < total {total}")


def _ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


def _solve_window(r_scaled, scale, total, lo, hi, D):
    """Exact optimum over allocations with per-pick and prefix deviation <= D.

    Costs are integers in units of ``1/scale`` dollars.  Returns
    ``(cost, dollars)`` or ``None`` when the window holds no feasible
    allocation.
    """
    n = len(r_scaled)
    ds = D * scale
    vals: list[list[int]] = []
    for i in range(n):
        a = max(lo[i], _ceil_div(r_scaled[i] - ds, scale))
        b = min(hi[i], (r_scaled[i] + ds) // scale)
        vals.append(list(range(a, b + 1)) if a <= b else [])
    suffix = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + r_scaled[i]
    rwin = [
        (max(0, _ceil_div(suffix[i] - ds, scale)), min(total, (suffix[i] + ds) // scale))
        for i in range(n + 1)
    ]

    tables: list[dict[int, list[int | None]]] = [{} for _ in range(n)]
    next_prefix: dict[int, list[int | None]] = {}
    for i in range(n - 1, -1, -1):
        table: dict[int, list[int | None]] = {}
        nxt_vals = vals[i + 1] if i + 1 < n else []
        for R in range(rwin[i][0], rwin[i][1] + 1):
            row: list[int | None] = []
            for d in vals[i]:
                rest = R - d
                if i == n - 1:
                    tail = 0 if rest == 0 else None
                else:
                    pm = next_prefix.get(rest)
                    k = bisect_right(nxt_vals, d) - 1
                    tail = pm[k] if pm is not None and k >= 0 else None
                row.append(None if tail is None else tail + abs(d * scale - r_scaled[i]))
            table[R] = row
        tables[i] = table
        prefix: dict[int, list[int | None]] = {}
        for R, row in table.items():
            pm_row: list[int | None] = []
            best: int | None = None
            for c in row:
                if c is not None and (best is None or c < best):
                    best = c
                pm_row.append(best)
            prefix[R] = pm_row
        next_prefix = prefix

    row0 = tables[0].get(total)
    if not row0:
        return None
    finite = [c for c in row0 if c is not None]
    if not finite:
        return None
    best = min(finite)
    dollars: list[int] = []
    R, cap, remaining = total, None, best
    for i in range(n):
        row = tables[i][R]
        chosen = None
        for k in range(len(vals[i]) - 1, -1, -1):
            d = vals[i][k]
            if cap is not None and d > cap:
                continue
            if row[k] is not None and row[k] == remaining:
                chosen = d
                break
        if chosen is None:  # pragma: no cover - would be a programme defect
            raise ApportionmentRefused("verification_failed", f"reconstruction at index {i}")
        dollars.append(chosen)
        remaining -= abs(chosen * scale - r_scaled[i])
        R -= chosen
        cap = chosen
    return best, dollars


def apportion_whole_dollars(
    values: Sequence[object],
    total: int,
    *,
    floors: Sequence[int] | None = None,
    caps: Sequence[int | None] | None = None,
) -> WholeDollarApportionment:
    """Whole-dollar apportionment of ``values`` (in draft order) to ``total``.

    ``values`` must already sum to exactly ``total`` (the class pool is never
    rescaled).  ``floors`` / ``caps`` are optional per-pick integer bounds.
    See the module docstring for Step A / Step B and the refusal rule.
    """
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ApportionmentRefused("invalid_total", repr(total))
    n = len(values)
    if n == 0:
        raise ApportionmentRefused("no_values")
    exact = [_exact(v, i) for i, v in enumerate(values)]
    if sum(exact, Fraction(0)) != total:
        raise ApportionmentRefused(
            "sum_not_total", f"values sum to {sum(exact, Fraction(0))}, not {total}"
        )
    if floors is not None and len(floors) != n:
        raise ApportionmentRefused("floors_length", f"{len(floors)} != {n}")
    if caps is not None and len(caps) != n:
        raise ApportionmentRefused("caps_length", f"{len(caps)} != {n}")

    # Step A — largest remainder.
    base = [math.floor(f) for f in exact]
    remainders = [exact[i] - base[i] for i in range(n)]
    residual = total - sum(base)
    order = sorted(range(n), key=lambda i: (-remainders[i], i))
    plus_one = sorted(i for i in order[:residual] if remainders[i] > 0)
    if len(plus_one) != residual:  # pragma: no cover - impossible for an exact sum
        raise ApportionmentRefused("residual_unallocatable", f"residual {residual}")
    step_a = list(base)
    for i in plus_one:
        step_a[i] += 1

    def deviation(ds: Sequence[int]) -> tuple[Fraction, Fraction]:
        devs = [abs(Fraction(d) - exact[i]) for i, d in enumerate(ds)]
        return sum(devs, Fraction(0)), max(devs)

    common = dict(
        floored=tuple(base),
        remainders=tuple(remainders),
        residual=residual,
        plus_one_indices=tuple(plus_one),
        total=total,
        step_a_dollars=tuple(step_a),
    )
    violations = _violations(step_a, total, floors, caps)
    if not violations:
        tot, mx = deviation(step_a)
        return WholeDollarApportionment(
            dollars=tuple(step_a),
            method=METHOD_LARGEST_REMAINDER,
            total_deviation=tot,
            max_deviation=mx,
            **common,
        )

    # Step B — exact constrained minimum deviation.
    lo, hi = _monotone_bounds(n, total, floors, caps)
    _check_feasible(total, lo, hi)
    scale = math.lcm(*(f.denominator for f in exact))
    r_scaled = [f.numerator * (scale // f.denominator) for f in exact]
    window = 4
    while True:
        solved = _solve_window(r_scaled, scale, total, lo, hi, window)
        if solved is not None and Fraction(solved[0], scale) <= window:
            break
        if window >= 2 * total:  # pragma: no cover - feasibility was proven above
            raise ApportionmentRefused("infeasible", "no allocation satisfies the constraints")
        window *= 2
    cost, dollars = solved
    remaining = _violations(dollars, total, floors, caps)
    if remaining:  # pragma: no cover - would be a programme defect
        raise ApportionmentRefused("verification_failed", ", ".join(remaining))
    tot, mx = deviation(dollars)
    if tot != Fraction(cost, scale):  # pragma: no cover - would be a programme defect
        raise ApportionmentRefused("verification_failed", "objective mismatch")
    repairs = tuple((i, dollars[i] - step_a[i]) for i in range(n) if dollars[i] != step_a[i])
    binding: list[str] = []
    for i, _ in repairs:
        if floors is not None and floors[i] is not None and dollars[i] == int(floors[i]):
            binding.append(f"floor@{i}={dollars[i]}")
        if caps is not None and caps[i] is not None and dollars[i] == int(caps[i]):
            binding.append(f"cap@{i}={dollars[i]}")
        if i > 0 and dollars[i] == dollars[i - 1]:
            binding.append(f"non_increasing@{i - 1},{i}")
        if i + 1 < n and dollars[i] == dollars[i + 1]:
            binding.append(f"non_increasing@{i},{i + 1}")
    return WholeDollarApportionment(
        dollars=tuple(dollars),
        method=METHOD_CONSTRAINED,
        step_a_violations=tuple(violations),
        repairs=repairs,
        total_deviation=tot,
        max_deviation=mx,
        binding_constraints=tuple(dict.fromkeys(binding)),
        **common,
    )
