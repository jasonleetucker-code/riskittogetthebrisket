"""Canonical trade-grading math — the Python half of a two-language pair.

There are exactly TWO places a dynasty trade gets a letter grade:

* ``frontend/lib/league-analysis.js::gradeTradeSides`` — the private
  ``/trades`` page.
* this module — the public ``/league`` activity timeline, which is
  server-rendered (``src/public_league/activity.py``) and therefore
  cannot import the JS.

Until the 2026-08-04 math audit (finding C3) the two used DIFFERENT
formulas against the SAME 3/8/15/25/40 band table.  The public side
summed ``max(value, 1) ** 1.65`` per received asset and compared side
totals; the private side took a plain linear net plus the KTC value
adjustment.  A power of 1.65 inflates a gap: a 10% linear edge is a
~16% alpha edge, so one trade rendered "Good win (A-)" on ``/trades``
and "Clear win (B+)" on ``/league`` — with a comment in ``activity.py``
asserting they landed in the same bucket.

The linear-ratio-with-VA form below is the canonical one, for the
reason the frontend already documented: the alpha-powered sums dominate
by an order of magnitude, which crushes every percentage toward the
extremes of the band table instead of spreading trades across it.

Because the two implementations live in different languages they are
pinned by a SHARED FIXTURE, ``tests/fixtures/trade_grade_parity_cases.json``,
asserted by ``tests/public_league/test_trade_grade_parity.py`` and
``frontend/__tests__/trade-grade-parity.test.js``.  Neither test may
hardcode an expectation of its own — if the two implementations drift,
exactly one suite goes red against a shared statement of intent.

This module lives under ``src/public_league`` (rather than somewhere
more central) because the public activity feed is its only Python
caller, and the package is forbidden from importing private internals
(``tests/public_league/test_public_contract.py::ImportSurfaceTests``).
Its only non-stdlib import is ``src.valuation_math.ktc_va_core`` — a
dependency-free algorithmic module that lives outside every forbidden
import prefix precisely so this file does not have to re-derive KTC's
Value Adjustment on its own (see the section below).
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from src.valuation_math.ktc_va_core import KTC_VARIANCE_PCT as _KTC_VARIANCE_PCT
from src.valuation_math.ktc_va_core import adjust_package_raw as _adjust_package_raw

# ── Band table ───────────────────────────────────────────────────────────
# Mirrors ``gradeTradeHistorySide`` in ``frontend/lib/league-analysis.js``
# exactly — same cut points, same letters, same labels, same colors.
_GRADE_PCT_FAIR = 3.0
_GRADE_PCT_SLIGHT = 8.0
_GRADE_PCT_GOOD = 15.0
_GRADE_PCT_CLEAR = 25.0
_GRADE_PCT_ROBBERY = 40.0


def grade_from_pct(pct: float, is_winner: bool) -> dict[str, str]:
    """Bucket a MAGNITUDE percentage into the shared band table.

    ``pct`` is ``abs(pctGap)``; ``is_winner`` is ``pctGap > 0``.
    """
    if pct < _GRADE_PCT_FAIR:
        return {"grade": "A", "color": "var(--green)", "label": "Fair trade"}
    if is_winner:
        if pct < _GRADE_PCT_SLIGHT:
            return {"grade": "A", "color": "var(--green)", "label": "Slight win"}
        if pct < _GRADE_PCT_GOOD:
            return {"grade": "A-", "color": "var(--green)", "label": "Good win"}
        if pct < _GRADE_PCT_CLEAR:
            return {"grade": "B+", "color": "#2ecc71", "label": "Clear win"}
        return {"grade": "A+", "color": "#00ff88", "label": "Big win"}
    if pct < _GRADE_PCT_SLIGHT:
        return {"grade": "B+", "color": "#2ecc71", "label": "Slight overpay"}
    if pct < _GRADE_PCT_GOOD:
        return {"grade": "B", "color": "var(--amber)", "label": "Overpay"}
    if pct < _GRADE_PCT_CLEAR:
        return {"grade": "C", "color": "#e67e22", "label": "Bad deal"}
    if pct < _GRADE_PCT_ROBBERY:
        return {"grade": "D", "color": "var(--red)", "label": "Robbery"}
    return {"grade": "F", "color": "#ff4444", "label": "Fleeced"}


# ── KTC value adjustment ──────────────────────────────────────────────
#
# The public grade has to be computed server-side and the VA is part of
# the canonical formula — a stud-for-pile trade is not fairly described
# by its linear sums alone.
#
# Until 2026-08-20 this module carried its OWN full copy of
# ``processV``/``reverseAdjust``/``adjustPackage`` — a genuine duplicate
# of ``src/trade/ktc_va.py`` (which itself duplicates the JS port in
# ``frontend/lib/trade-logic.js``), because this package is structurally
# forbidden from importing ``src.trade`` at all
# (``tests/public_league/test_public_contract.py::ImportSurfaceTests``).
# Two independently-maintained copies of the same algorithm disagreed on
# rounding for eleven months before that was caught.
#
# The algorithm now lives in ONE stdlib-only place,
# ``src/valuation_math/ktc_va_core.py`` — outside every forbidden import
# prefix because it has no private business logic in it, only closed-form
# math over plain numbers.  This module wraps its plain-tuple return in
# the dict shape this file's own callers already expect.
# ``tests/valuation_math/test_single_owner.py`` guards against a third
# copy reappearing here or in ``src/trade``.


def ktc_adjust_package(team1_vals: Iterable[float], team2_vals: Iterable[float]) -> dict[str, Any]:
    """KTC's ``adjustPackage``.  Returns ``{value, side, displayed}``.

    ``side`` is 1 when team1 receives the value adjustment, 2 when
    team2 does, and 0 when KTC would suppress the badge entirely.
    Thin dict-shaped wrapper over the shared algorithmic core — see the
    module docstring above.
    """
    t_one = [float(v) for v in team1_vals if _finite(v) and float(v) > 0]
    t_two = [float(v) for v in team2_vals if _finite(v) and float(v) > 0]
    value, side, displayed = _adjust_package_raw(t_one, t_two, variance_pct=_KTC_VARIANCE_PCT)
    return {"value": value, "side": side, "displayed": displayed}


def trade_va_net(got_values: list[float], gave_values: list[float]) -> float:
    """Signed KTC value adjustment for ONE team's got-vs-gave equation.

    Positive means this team RECEIVED the stud premium; negative means
    they gave the studs away.  Mirrors ``computeTradeVANet`` in
    ``frontend/lib/league-analysis.js``: got is KTC's team1, gave is
    team2, so ``side === 1`` is a bonus and ``side === 2`` a penalty.
    """
    if not got_values or not gave_values:
        return 0.0
    result = ktc_adjust_package(got_values, gave_values)
    if not result["displayed"] or result["value"] <= 0:
        return 0.0
    return float(result["value"]) if result["side"] == 1 else -float(result["value"])


# ── The canonical grade ──────────────────────────────────────────────────


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def sanitize_side_values(raw: Iterable[Any] | None) -> list[float]:
    """Clamp a side's asset values the way the frontend resolver does.

    ``resolveTradeSideList`` maps every asset through
    ``Number.isFinite(v) ? Math.max(0, v) : 0`` and only pushes strictly
    positive values into the array the VA sees, so a NaN or a negative
    contributes nothing to either the linear sum or the VA.  Both halves
    must agree on that or the grades diverge on unpriced assets.
    """
    out: list[float] = []
    for value in raw or []:
        if not _finite(value):
            continue
        num = float(value)
        if num > 0:
            out.append(num)
    return out


def grade_trade_side(
    got_values: list[float], gave_values: list[float], va_net: float
) -> dict[str, Any]:
    """Grade ONE side from its OWN net, with the VA supplied by the caller.

    Split out from :func:`grade_trade_sides` so the shared parity fixture
    can pin the ratio-and-band arithmetic against hand-computed numbers
    for an arbitrary ``va_net``, independent of the KTC engine above.

    The denominator is the larger EFFECTIVE side total (linear + the VA
    on whichever side earned it).  It deliberately does NOT use the
    alpha-weighted sums: those dominate by an order of magnitude and
    would crush every pct toward the extremes of the band table.
    """
    got_linear = sum(got_values)
    gave_linear = sum(gave_values)
    net_linear = got_linear - gave_linear
    net_adjusted = net_linear + va_net
    got_effective = got_linear + max(0.0, va_net)
    gave_effective = gave_linear + max(0.0, -va_net)
    scale = max(got_effective, gave_effective, 1.0)
    pct_gap = (net_adjusted / scale) * 100.0
    return {
        "gotValue": got_linear,
        "gaveValue": gave_linear,
        "netValue": net_linear,
        "vaNet": va_net,
        "netAdjusted": net_adjusted,
        "pctGap": pct_gap,
        "grade": grade_from_pct(abs(pct_gap), pct_gap > 0),
    }


def grade_trade_sides(
    sides: Iterable[tuple[Iterable[Any] | None, Iterable[Any] | None]],
) -> list[dict[str, Any]]:
    """Grade every side of one trade from ``(got_values, gave_values)`` pairs.

    Each side is graded on its OWN net rather than against the other
    sides' received totals — which is what makes 3+ team trades come out
    right, since the sent and received pools do not pair up there.  For a
    two-team trade the two are algebraically identical (A.got == B.gave).
    """
    out: list[dict[str, Any]] = []
    for raw_got, raw_gave in sides:
        got_values = sanitize_side_values(raw_got)
        gave_values = sanitize_side_values(raw_gave)
        out.append(grade_trade_side(got_values, gave_values, trade_va_net(got_values, gave_values)))
    return out
