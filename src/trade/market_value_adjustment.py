"""Compatibility re-export of the canonical KTC Value Adjustment.

**This module computes nothing.**  ``src/trade/ktc_va.py`` is the one
Python owner of KTC's package Value Adjustment; this file exists only so
the arbitrage-finder adapter and its tests keep their historical import
path and spelling.

Why it was collapsed
────────────────────
Until 2026-08-18 this file held a SECOND line-for-line port of the same
JS algorithm, and the two ports **disagreed**.  Measured: 0 differences
across the 139-observation KTC fixture
(``scripts/ktc_va_observations.json``), but **60 differences across
30,000 random packages** — always by exactly 1 value point, e.g.
``[6370, 3327, 4606]`` vs ``[270, 9700]`` returning 5,545 here and 5,546
there.

The cause was rounding.  This port used ``floor(x + 0.5)`` (JavaScript
``Math.round``, half-up); ``ktc_va`` used Python's ``round``, which is
banker's rounding and disagrees on exact halves.  The frontend is the
reference implementation, so half-up was the correct rule and it was the
copy THREE engines used (suggestions, angle, monte_carlo) that was
wrong.  ``ktc_va._js_round`` now carries the correct rule for everyone,
and the fixture gained the half-integer cases it never had.

Names differ from the owner's for historical reasons and are mapped
here rather than in the owner:

===============================  =========================
this module                      ``src.trade.ktc_va``
===============================  =========================
``PackageAdjustment``            ``KtcVAResult`` (same class)
``ktc_process_value``            ``ktc_process_v``
``KTC_MAX_PLAYER_VALUE``         ``KTC_MAX_PLAYER_VAL``
``KTC_TOP_REFERENCE``            ``KTC_T_REFERENCE``
``KTC_VARIANCE_PERCENT``         ``KTC_VARIANCE_PCT``
``top_reference=`` / ``variance_percent=``  ``t=`` / ``variance_pct=``
===============================  =========================

Rule for new code: import from ``src.trade.ktc_va``.
"""

from __future__ import annotations

from typing import Iterable

from src.trade.ktc_va import (
    KTC_MAX_PLAYER_VALUE,
    KTC_TOP_REFERENCE,
    KTC_VARIANCE_PERCENT,
    KtcVAResult,
    PackageAdjustment,
    ktc_process_v,
)
from src.trade.ktc_va import ktc_adjust_package as _ktc_adjust_package
from src.trade.ktc_va import ktc_reverse_adjust as _ktc_reverse_adjust

__all__ = [
    "KTC_MAX_PLAYER_VALUE",
    "KTC_TOP_REFERENCE",
    "KTC_VARIANCE_PERCENT",
    "KtcVAResult",
    "PackageAdjustment",
    "ktc_adjust_package",
    "ktc_process_value",
    "ktc_reverse_adjust",
]


def ktc_process_value(
    value: float,
    max_in_trade: float,
    top_reference: float = KTC_TOP_REFERENCE,
    nerf_index: int = -1,
) -> float:
    """Legacy spelling of :func:`src.trade.ktc_va.ktc_process_v`."""

    return ktc_process_v(value, max_in_trade, top_reference, nerf_index)


def ktc_reverse_adjust(
    raw_difference: float,
    max_in_trade: float,
    top_reference: float = KTC_TOP_REFERENCE,
    nerf_count: int = 0,
) -> int:
    """Legacy spelling of :func:`src.trade.ktc_va.ktc_reverse_adjust`."""

    return _ktc_reverse_adjust(raw_difference, max_in_trade, top_reference, nerf_count)


def ktc_adjust_package(
    first_values: Iterable[int | float],
    second_values: Iterable[int | float],
    *,
    variance_percent: float = KTC_VARIANCE_PERCENT,
    top_reference: float = KTC_TOP_REFERENCE,
) -> PackageAdjustment:
    """Legacy spelling of :func:`src.trade.ktc_va.ktc_adjust_package`."""

    return _ktc_adjust_package(
        first_values,
        second_values,
        variance_pct=variance_percent,
        t=top_reference,
    )
