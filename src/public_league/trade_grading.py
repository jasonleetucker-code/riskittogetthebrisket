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
It has no imports outside the standard library.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


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


# ── KTC value adjustment (port of the JS port of KTC's site.min.js) ──────
#
# ``frontend/lib/trade-logic.js`` carries a verbatim port of
# keeptradecut.com's ``processV`` / ``reverseAdjust`` / ``adjustPackage``.
# This is that port again, in Python, because the public grade has to be
# computed server-side and the VA is part of the canonical formula — a
# stud-for-pile trade is not fairly described by its linear sums alone.
#
# The constants and branch structure are lifted from the JS one-for-one;
# see ``frontend/lib/trade-logic.js`` for the annotated mapping back to
# KTC's single-letter identifiers.  Divergence between the two is a bug,
# and the shared parity fixture is what catches it.

# KTC's MAXPLAYERVAL — board-wide ceiling used as the asymptotic
# reference in reverseAdjust's "all-equal" fallback branch.
_KTC_MAX_PLAYER_VAL = 10000
# KTC's t = playersArray[0].value + 80 — top-of-board reference.
_KTC_T_REFERENCE = 10041
# KTC's tcFilters.variance — the 5% equality threshold.
_KTC_VARIANCE_PCT = 5


def _js_round(x: float) -> int:
    """JavaScript ``Math.round`` — half rounds toward +Infinity.

    Python's builtin ``round`` is round-half-to-even, so ``round(0.5)``
    is 0 where JS gives 1.  The VA algorithm rounds twice (once inside
    ``_ktc_check_equality``, once on the final displayed value), and a
    half-value landing on a band edge is exactly the kind of one-off
    divergence the parity fixture exists to prevent.
    """
    return math.floor(x + 0.5)


def _ktc_process_v(value: float, max_in_trade: float, t: float, nerf_index: int) -> float:
    """KTC's per-player raw adjustment (``processV``)."""
    if not (value > 0) or not (max_in_trade > 0) or not (t > 0):
        return 0.0
    s = (0.05 * pow(value / t, 1.3) + 0.05 * pow(value / (1.05 * max_in_trade), 6) + 0.1) * value
    if nerf_index > 0:
        s *= max(0.6, 1 - 0.15 * nerf_index)
    if s < 0:
        s /= 4
    return s


def _ktc_reverse_adjust(raw_diff: float, max_in_trade: float, t: float, nerf_count: int) -> int:
    """KTC's ``reverseAdjust`` — solve for the value whose raw adj is ``raw_diff``.

    Two-phase iterative search (not bisection): a 10-step coarse pass
    with step 0.75x the current relative error, then — if convergence is
    still worse than 5% — a 10-step refinement with step 0.25x.

    ``guess`` is KTC's ``l`` (spelled out because ruff's E741 rejects a
    bare ``l``); every other single letter keeps KTC's own name.
    """
    if not (raw_diff > 0) or not (max_in_trade > 0):
        return 0
    seed = _ktc_process_v(max_in_trade, max_in_trade, t, -1)
    n = max_in_trade
    if seed < raw_diff:
        n = max((raw_diff / seed) * max_in_trade * 0.8, max_in_trade)
    guess = n / 2
    d = 1.0
    u = 0
    best_err = 1.0
    best_guess = -1.0
    while d > 0.025 and u <= 10:
        i = _ktc_process_v(guess, n, t, nerf_count)
        d = min(1.0, abs(i - raw_diff) / raw_diff)
        if d > 0.025:
            o = guess
            p = d * guess * 0.75
            guess += p if i <= raw_diff else -p
            if d < best_err:
                best_err = d
                best_guess = o
                if best_guess > max_in_trade:
                    n = best_guess
        elif d < best_err:
            best_err = d
            best_guess = guess
            if best_guess > max_in_trade:
                n = best_guess
        if u == 10 and d > 0.05:
            f = 0
            guess = max(1.0, best_guess)
            while d > 0.025 and f <= 10:
                i2 = _ktc_process_v(guess, n, t, nerf_count)
                d = min(1.0, abs(i2 - raw_diff) / raw_diff)
                if d > 0.025:
                    o = guess
                    p = d * guess * 0.25
                    guess += p if i2 <= raw_diff else -p
                    if d < best_err:
                        best_err = d
                        best_guess = o
                        if best_guess > max_in_trade:
                            n = best_guess
                elif d < best_err:
                    best_err = d
                    best_guess = guess
                    if best_guess > max_in_trade:
                        n = best_guess
                f += 1
            guess = best_guess
        u += 1
    return _js_round(guess)


def _ktc_check_equality(a: float, b: float, variance_pct: float) -> bool:
    """KTC's ``checkEquality`` — true iff |a-b|/(a+b)*100 rounds to <= variance."""
    total = max(0.0, a) + max(0.0, b)
    if total <= 0:
        return True
    pct = min(100.0, (abs(a - b) / total) * 100.0)
    return (_js_round(10 * pct) / 10) <= variance_pct


def _ktc_build_side_adj(
    values: list[float], max_in_trade: float, t: float
) -> tuple[list[dict[str, Any]], float]:
    """Per-piece adjustments with KTC's progressive-nerf rule.

    Pieces below ``0.5 * max_in_trade`` are "small"; the FIRST small
    piece is unnerfed (nerfIndex 0 → multiplier 1.0), each subsequent
    one steps down 0.85 / 0.70 / 0.60-floor.
    """
    half = 0.5 * max_in_trade
    nerf_index = -1
    raw_adj_sum = 0.0
    items: list[dict[str, Any]] = []
    for v in values:
        if v < half:
            nerf_index += 1
        adj = _ktc_process_v(v, max_in_trade, t, nerf_index)
        raw_adj_sum += adj
        items.append({"value": v, "adj": adj, "nerfIndex": nerf_index})
    # Stable descending sort, matching the JS comparator: Python's
    # ``reverse=True`` keeps the original order among equal keys.
    items.sort(key=lambda it: it["adj"], reverse=True)
    return items, raw_adj_sum


def ktc_adjust_package(team1_vals: Iterable[float], team2_vals: Iterable[float]) -> dict[str, Any]:
    """KTC's ``adjustPackage``.  Returns ``{value, side, displayed}``.

    ``side`` is 1 when team1 receives the value adjustment, 2 when
    team2 does, and 0 when KTC would suppress the badge entirely.
    """
    t_one = sorted((float(v) for v in team1_vals if _finite(v) and float(v) > 0), reverse=True)
    t_two = sorted((float(v) for v in team2_vals if _finite(v) and float(v) > 0), reverse=True)
    if not t_one or not t_two:
        return {"value": 0, "side": 0, "displayed": False}

    variance = _KTC_VARIANCE_PCT
    t = _KTC_T_REFERENCE

    team1_total = sum(t_one)
    team2_total = sum(t_two)
    r = max(t_one[0], t_two[0])
    o = _ktc_process_v(0.5 * r, r, t, -1)
    s, e = _ktc_build_side_adj(t_one, r, t)
    n, a = _ktc_build_side_adj(t_two, r, t)
    h = e / team1_total
    y = a / team2_total
    v = math.floor(abs(e - a))
    k = _ktc_check_equality(team1_total, team2_total, variance)
    b = _ktc_check_equality(e, a, variance)

    # ``T`` — extra nerf count handed to reverseAdjust: nerfIndex+1 of
    # the FIRST item on the larger-rawAdj side whose adj falls below the
    # raw_adj diff.
    big_t = 0
    if v < o:
        for it in n if e > a else s:
            if it["adj"] < v:
                big_t = it["nerfIndex"] + 1
                break

    side = 0
    value = 0.0
    w = True

    if k and b:
        # BRANCH 1: totals AND raw_adjs both within variance.
        if e > a:
            side = 1
            adj = _ktc_reverse_adjust(v, r, t, big_t)
            gap = team2_total + adj - team1_total
            if gap > 0:
                value = gap
            else:
                w = False
                side = 2
                value = -gap
        elif a > e:
            side = 2
            adj = _ktc_reverse_adjust(v, r, t, big_t)
            gap = team1_total + adj - team2_total
            if gap > 0:
                value = gap
            else:
                w = False
                side = 1
                value = -gap
    elif h > y:
        # BRANCH 2: side1 has higher raw_adj intensity.
        side = 1
        if e > a:
            adj = _ktc_reverse_adjust(v, r, t, big_t)
            gap = team2_total + adj - team1_total
            if gap > 0:
                value = gap
            else:
                w = False
                side = 2
                value = abs(gap)
        else:
            # h > y but e <= a — KTC's "intensity flip" branch.
            big_v = -1
            if team1_total < team2_total:
                big_v = 1
            elif team2_total < team1_total:
                big_v = 2
            m = _ktc_reverse_adjust(abs(e - a), max(t_one + t_two), 10099, big_t)
            if m > 0 and big_v > 0:
                side = big_v
                if big_v == 2:
                    rr = m - (team1_total - team2_total)
                    if rr > 0:
                        value = rr
                    else:
                        w = False
                        value = rr
                else:
                    rr = m - (team2_total - team1_total)
                    if rr > 0:
                        if rr > _KTC_MAX_PLAYER_VAL:
                            w = False
                            value = 0.0
                            side = 1
                        else:
                            side = 2
                            value = rr
                    else:
                        w = True
                        value = -rr
            else:
                w = False
    else:
        # BRANCH 3: side2 has higher raw_adj intensity (mirror of 2).
        side = 2
        if a > e:
            adj = _ktc_reverse_adjust(v, r, t, big_t)
            gap = team1_total + adj - team2_total
            if gap > 0:
                value = gap
            else:
                w = False
                side = 1
                value = abs(gap)
        else:
            big_v = -1
            if team1_total < team2_total:
                big_v = 1
            elif team2_total < team1_total:
                big_v = 2
            m = _ktc_reverse_adjust(abs(e - a), max(t_one + t_two), 10099, big_t)
            if m > 0 and big_v > 0:
                side = big_v
                if big_v == 1:
                    rr = m - (team2_total - team1_total)
                    if rr > 0:
                        value = rr
                    else:
                        w = False
                        value = rr
                else:
                    rr = m - (team1_total - team2_total)
                    if rr > 0:
                        if rr > _KTC_MAX_PLAYER_VAL:
                            w = False
                            value = 0.0
                            side = 1
                        else:
                            side = 1
                            value = rr
                    else:
                        w = True
                        value = -rr
            else:
                w = False

    # KTC's display gates: sign check, a 3.3%-of-combined-volume floor
    # ("Fair Trade" zone), and an unconditional 1v1 suppression.
    displayed = False
    if value != 0:
        if w:
            displayed = True
        if abs(value / (team1_total + team2_total)) < 0.033:
            displayed = False
    if len(t_one) == 1 and len(t_two) == 1:
        displayed = False
    if not displayed:
        return {"value": 0, "side": 0, "displayed": False}
    return {"value": _js_round(value), "side": side, "displayed": True}


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

    This function is deliberately NOT where "unpriced" is decided.  It
    normalises a list of numbers; whether a dropped entry was worthless
    or unknown is information the caller holds and passes separately —
    see :func:`grade_trade_sides`.  Answering that question here is
    what produced W19-F003: an asset the board could not price was
    dropped and became indistinguishable from one that was never in
    the trade.
    """
    out: list[float] = []
    for value in raw or []:
        if not _finite(value):
            continue
        num = float(value)
        if num > 0:
            out.append(num)
    return out


# ── Abstention ───────────────────────────────────────────────────────
#
# The band table above answers "how lopsided was this trade".  It can
# only answer that over a set of assets that were all priced.  When one
# was not, there is no honest bucket: the missing asset can be a 2025
# first, and 224 of 1,708 slots on the live public feed are exactly
# that.  So the letter is withheld rather than computed over a subset
# and presented as if it covered the whole trade (W19-F003).
#
# Shaped like a grade block so every consumer that renders
# ``{grade, color, label}`` keeps working without a branch — but with a
# dash where the letter goes, which no band can produce.
UNGRADED: dict[str, str] = {
    "grade": "—",
    "color": "var(--subtext)",
    "label": "Not graded — unpriced assets",
}


def ungraded_badge(unpriced: int) -> dict[str, str]:
    """:data:`UNGRADED` with the count spelled out in the label."""
    if unpriced <= 0:
        return dict(UNGRADED)
    noun = "asset" if unpriced == 1 else "assets"
    return {
        **UNGRADED,
        "label": f"Not graded — {unpriced} unpriced {noun}",
    }


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
    sides: Iterable[tuple[Any, ...]],
) -> list[dict[str, Any]]:
    """Grade every side of one trade from ``(got_values, gave_values)`` pairs.

    Each side is graded on its OWN net rather than against the other
    sides' received totals — which is what makes 3+ team trades come out
    right, since the sent and received pools do not pair up there.  For a
    two-team trade the two are algebraically identical (A.got == B.gave).

    A side may be supplied as a THIRD element: the number of that
    side's assets the valuation could not price.  When any side reports
    one, EVERY side's letter is withheld (:data:`UNGRADED`) — not just
    the side holding the unpriced asset.  A two-team trade is one
    equation: if A received a pick nothing could price, B gave that
    same pick, so B's net is wrong by exactly the same unknown amount.
    Grading B while abstaining on A would publish a verdict on half of
    a trade nobody could evaluate (W19-F003).

    Every result carries ``unpricedAssetCount`` (that side's own) and
    ``tradeUnpricedAssetCount`` (the whole trade's), so the omission is
    on the payload whether or not a surface renders the badge.  Omitting
    the third element preserves the previous behavior exactly, which is
    what the shared parity fixture exercises.
    """
    parsed: list[tuple[list[float], list[float], int]] = []
    for side in sides:
        raw_got, raw_gave, *rest = side
        unpriced = int(rest[0]) if rest and rest[0] else 0
        parsed.append(
            (sanitize_side_values(raw_got), sanitize_side_values(raw_gave), max(0, unpriced))
        )

    trade_unpriced = sum(u for _got, _gave, u in parsed)
    out: list[dict[str, Any]] = []
    for got_values, gave_values, unpriced in parsed:
        result = grade_trade_side(
            got_values, gave_values, trade_va_net(got_values, gave_values)
        )
        result["unpricedAssetCount"] = unpriced
        result["tradeUnpricedAssetCount"] = trade_unpriced
        if trade_unpriced:
            result["grade"] = ungraded_badge(trade_unpriced)
        out.append(result)
    return out
