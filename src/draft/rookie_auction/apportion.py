"""Whole-dollar apportionment — the final step of the rookie-auction curve.

Owner decision 2026-10-18: the ``dynasty_main`` rookie auction uses WHOLE
DOLLARS ONLY.  The spreadsheet's half-dollar curve (column L) stays the
mathematical reference; turning it into whole dollars is this separately
identified step:

a) floor every exact value to whole dollars;
b) ``residual = total - sum(floors)`` (an exact integer);
c) the ``residual`` largest fractional remainders get +1 — ties go to the
   EARLIER index (the higher draft position);
d) verify: every value an integer, the sum exactly ``total``, non-increasing
   by draft position, and any per-pick ``floors`` / ``caps`` the caller
   supplies;
e) anything violated REFUSES (:class:`ApportionmentRefused`, the conflict
   named).  The total is never changed to make a result fit.

Exact arithmetic only (``Fraction``); floats are refused as inputs rather
than guessed at.  Pure, stdlib-only, no I/O.  The signature is deliberately
small and stable — PR #1785 consumes it for every ``dynasty_main`` class::

    from src.draft.rookie_auction.apportion import apportion_whole_dollars
    result = apportion_whole_dollars(values, 1200)          # -> WholeDollarApportionment
    result.dollars                                           # tuple[int, ...]

Team budgets follow by construction: every pick is an integer, so a
manager's budget is the exact integer sum of the picks they own, and the
twelve budgets total the class pool.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Sequence

__all__ = [
    "ApportionmentRefused",
    "WholeDollarApportionment",
    "apportion_whole_dollars",
]


class ApportionmentRefused(ValueError):
    """The values cannot be apportioned to whole dollars under the constraints."""

    def __init__(self, conflict: str, detail: str = "") -> None:
        super().__init__(f"{conflict}: {detail}" if detail else conflict)
        self.conflict = conflict


@dataclass(frozen=True)
class WholeDollarApportionment:
    dollars: tuple[int, ...]
    floored: tuple[int, ...]
    remainders: tuple[Fraction, ...]
    residual: int
    plus_one_indices: tuple[int, ...]
    total: int

    def receipt(self, labels: Sequence[str] | None = None) -> dict[str, object]:
        def name(i: int) -> object:
            return labels[i] if labels is not None else i

        return {
            "method": "floor_then_largest_remainder_earlier_index_first",
            "total": self.total,
            "flooredSum": sum(self.floored),
            "residual": self.residual,
            "plusOne": [name(i) for i in self.plus_one_indices],
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


def apportion_whole_dollars(
    values: Sequence[object],
    total: int,
    *,
    floors: Sequence[int] | None = None,
    caps: Sequence[int | None] | None = None,
) -> WholeDollarApportionment:
    """Whole-dollar apportionment of ``values`` (in draft order) to ``total``.

    ``values`` must already sum to exactly ``total`` (the class pool is never
    rescaled here).  ``floors`` / ``caps`` are optional per-pick integer
    bounds checked on the result.
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

    base = [math.floor(f) for f in exact]
    remainders = [exact[i] - base[i] for i in range(n)]
    residual = total - sum(base)
    # 0 <= residual < n always holds here (each remainder < 1, sum exact).
    order = sorted(range(n), key=lambda i: (-remainders[i], i))
    plus_one = sorted(i for i in order[:residual] if remainders[i] > 0)
    if len(plus_one) != residual:
        raise ApportionmentRefused("residual_unallocatable", f"residual {residual}")
    dollars = list(base)
    for i in plus_one:
        dollars[i] += 1

    if sum(dollars) != total:
        raise ApportionmentRefused("sum_not_total", f"{sum(dollars)} != {total}")
    for i in range(1, n):
        if dollars[i] > dollars[i - 1]:
            raise ApportionmentRefused(
                "not_non_increasing", f"index {i}: {dollars[i - 1]} -> {dollars[i]}"
            )
    if floors is not None:
        for i, (d, lo) in enumerate(zip(dollars, floors)):
            if lo is not None and d < int(lo):
                raise ApportionmentRefused("below_floor", f"index {i}: {d} < {lo}")
    if caps is not None:
        for i, (d, hi) in enumerate(zip(dollars, caps)):
            if hi is not None and d > int(hi):
                raise ApportionmentRefused("above_cap", f"index {i}: {d} > {hi}")
    return WholeDollarApportionment(
        dollars=tuple(dollars),
        floored=tuple(base),
        remainders=tuple(remainders),
        residual=residual,
        plus_one_indices=tuple(plus_one),
        total=total,
    )
