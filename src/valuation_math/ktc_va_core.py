"""KTC's Value Adjustment algorithm — the one stdlib-only algorithmic core.

Verbatim translation of KTC's client-side algorithm (``keeptradecut.com/js/site.min.js``
``processV`` / ``reverseAdjust`` / ``adjustPackage``), matching the reference JS port in
``frontend/lib/trade-logic.js``.

Why this module exists, separately from ``src/trade/ktc_va.py``
──────────────────────────────────────────────────────────────
``src/trade/ktc_va.py`` is the canonical PRIVATE-side Python owner of KTC Value
Adjustment, consumed by the trade arbitrage finder, suggestions, angle finder and
Monte Carlo. The public ``/league`` activity timeline also needs the identical
number (``src/public_league/trade_grading.py`` grades a trade's fairness, and a
stud-for-pile trade is not fairly described by linear sums alone) — but
``tests/public_league/test_public_contract.py::ImportSurfaceTests`` hard-forbids
anything under ``src/public_league`` from importing ``src.trade`` (or
``src.canonical``, ``src.pool``, ``src.api.data_contract``) at all, so
``trade_grading.py`` could not simply delegate to ``src.trade.ktc_va``.

Until 2026-08-20 that boundary was satisfied by ``trade_grading.py`` carrying a
second, independently-maintained line-for-line copy of the same algorithm — a
genuine duplicate-owner defect (C3-VA-01), not a deliberate second opinion: the
two copies disagreed on rounding for eleven months before a prior pass fixed
that particular divergence, and nothing structurally prevented the next one.

This module is the fix: the algorithm has **no private business logic in it** —
it is closed-form math over plain numbers, with no dependency on canonical
values, leagues, rosters or identity — so it can live outside every forbidden
import prefix. Both ``src.trade.ktc_va`` and ``src.public_league.trade_grading``
now import THIS module and wrap its plain-tuple return in their own
historically-shaped public API (a frozen dataclass on the private side, a dict
on the public side). Divergence between the two callers is now structurally
impossible rather than merely tested against — there is only one place the
arithmetic can be written.

``tests/valuation_math/test_single_owner.py`` guards against a third copy
reappearing.
"""

from __future__ import annotations

import math
from typing import Iterable, NamedTuple, Sequence

# Constants lifted from KTC's site.min.js (see frontend/lib/trade-logic.js).
KTC_MAX_PLAYER_VAL = 10000
KTC_T_REFERENCE = 10041
KTC_VARIANCE_PCT = 5


def js_round(value: float) -> int:
    """JavaScript ``Math.round``: half rounds UP, never to even.

    Python's built-in ``round`` is banker's rounding, which disagrees with the
    JS original on exact halves. The frontend is the reference implementation
    KTC's numbers are matched against, so half-up is the correct rule.
    """

    return math.floor(value + 0.5)


def process_v(value: float, max_in_trade: float, t: float, nerf_index: int) -> float:
    """KTC's per-player raw adjustment (site.min.js::processV)."""
    if value <= 0 or max_in_trade <= 0 or t <= 0:
        return 0.0
    s = (
        0.05 * math.pow(value / t, 1.3) + 0.05 * math.pow(value / (1.05 * max_in_trade), 6) + 0.1
    ) * value
    if nerf_index > 0:
        s *= max(0.6, 1 - 0.15 * nerf_index)
    if s < 0:
        s /= 4
    return s


def reverse_adjust(raw_diff: float, max_in_trade: float, t: float, nerf_count: int) -> int:
    """KTC's iterative virtual-player solver (site.min.js::reverseAdjust)."""
    if raw_diff <= 0 or max_in_trade <= 0:
        return 0
    seed = process_v(max_in_trade, max_in_trade, t, -1)
    n = max_in_trade
    if seed < raw_diff:
        n = max((raw_diff / seed) * max_in_trade * 0.8, max_in_trade)
    guess = n / 2
    d = 1.0
    u = 0
    best_err = 1.0
    best_guess = -1.0
    while d > 0.025 and u <= 10:
        i = process_v(guess, n, t, nerf_count)
        d = min(1.0, abs(i - raw_diff) / raw_diff)
        if d > 0.025:
            o = guess
            p = d * guess * 0.75
            guess = guess + p if i <= raw_diff else guess - p
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
                i2 = process_v(guess, n, t, nerf_count)
                d = min(1.0, abs(i2 - raw_diff) / raw_diff)
                if d > 0.025:
                    o = guess
                    p = d * guess * 0.25
                    guess = guess + p if i2 <= raw_diff else guess - p
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
    return js_round(guess)


def check_equality(a: float, b: float, variance_pct: float) -> bool:
    """KTC's checkEquality — true iff |a-b|/(a+b)*100 (rounded) <= variancePct."""
    s = max(0.0, a) + max(0.0, b)
    if s <= 0:
        return True
    pct = min(100.0, abs(a - b) / s * 100)
    return js_round(10 * pct) / 10 <= variance_pct


class SideAdjItem(NamedTuple):
    value: float
    adj: float
    nerf_index: int


def build_side_adj(
    values: Sequence[float], max_in_trade: float, t: float
) -> tuple[list[SideAdjItem], float]:
    """Build per-piece adjustments with KTC's progressive-nerf rule.

    Pieces below ``0.5 * max_in_trade`` are "small"; the first small piece is
    unnerfed (nerf index 0 -> multiplier 1.0), each subsequent one steps down
    0.85 / 0.70 / 0.60-floor. Returned list is a STABLE descending sort by
    ``adj`` — Python's ``sort(..., reverse=True)`` preserves original order
    among equal keys, matching KTC's comparator.
    """
    half = 0.5 * max_in_trade
    nerf_index = -1
    raw_adj_sum = 0.0
    items: list[SideAdjItem] = []
    for v in values:
        if v < half:
            nerf_index += 1
        adj = process_v(v, max_in_trade, t, nerf_index)
        raw_adj_sum += adj
        items.append(SideAdjItem(value=v, adj=adj, nerf_index=nerf_index))
    items.sort(key=lambda it: it.adj, reverse=True)
    return items, raw_adj_sum


def adjust_package_raw(
    team1_vals: Iterable[float],
    team2_vals: Iterable[float],
    *,
    variance_pct: float = KTC_VARIANCE_PCT,
    t: float = KTC_T_REFERENCE,
) -> tuple[int, int, bool]:
    """KTC's adjustPackage, ported from site.min.js.

    Takes two iterables of raw KTC values and returns ``(value, side,
    displayed)``. ``side`` is 1 if team1 receives the VA, 2 if team2 does, 0
    (with ``displayed=False``) when KTC would suppress the VA badge entirely.

    This is the ONE place the algorithm's branch structure is written. Callers
    on either side of the public/private import boundary wrap this return in
    their own historically-shaped public API; neither may re-derive it.
    """
    t_one = sorted(
        (float(v) for v in team1_vals if v is not None and float(v) > 0),
        reverse=True,
    )
    t_two = sorted(
        (float(v) for v in team2_vals if v is not None and float(v) > 0),
        reverse=True,
    )
    if not t_one or not t_two:
        return 0, 0, False

    team1_total = sum(t_one)
    team2_total = sum(t_two)
    r = max(t_one[0], t_two[0])
    o = process_v(0.5 * r, r, t, -1)
    s_items, e = build_side_adj(t_one, r, t)
    n_items, a = build_side_adj(t_two, r, t)
    h = e / team1_total
    y = a / team2_total
    v = math.floor(abs(e - a))
    k = check_equality(team1_total, team2_total, variance_pct)
    b = check_equality(e, a, variance_pct)

    # Compute T (extra nerf count for reverse_adjust). Walks the larger-rawAdj
    # side and records the first item whose adj falls below v.
    big_t = 0
    if v < o:
        items = n_items if e > a else s_items
        for it in items:
            if it.adj < v:
                big_t = it.nerf_index + 1
                break

    side = 0
    value = 0.0
    w = True

    if k and b:
        # BRANCH 1: trade is fair on both totals AND raw_adj
        if e > a:
            side = 1
            solved = reverse_adjust(v, r, t, big_t)
            gap = team2_total + solved - team1_total
            if gap > 0:
                value = gap
            else:
                w = False
                side = 2
                value = -gap
        elif a > e:
            side = 2
            solved = reverse_adjust(v, r, t, big_t)
            gap = team1_total + solved - team2_total
            if gap > 0:
                value = gap
            else:
                w = False
                side = 1
                value = -gap
    elif h > y:
        # BRANCH 2: side1 has higher raw_adj intensity
        side = 1
        if e > a:
            solved = reverse_adjust(v, r, t, big_t)
            gap = team2_total + solved - team1_total
            if gap > 0:
                value = gap
            else:
                w = False
                side = 2
                value = abs(gap)
        else:
            # h > y but e <= a — "intensity flip" special branch
            big_v = -1
            if team1_total < team2_total:
                big_v = 1
            elif team2_total < team1_total:
                big_v = 2
            m = reverse_adjust(abs(e - a), max(*t_one, *t_two), 10099, big_t)
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
                        if rr > KTC_MAX_PLAYER_VAL:
                            w = False
                            value = 0
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
        # BRANCH 3: side2 has higher raw_adj intensity (mirror of branch 2)
        side = 2
        if a > e:
            solved = reverse_adjust(v, r, t, big_t)
            gap = team1_total + solved - team2_total
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
            m = reverse_adjust(abs(e - a), max(*t_one, *t_two), 10099, big_t)
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
                        if rr > KTC_MAX_PLAYER_VAL:
                            w = False
                            value = 0
                            side = 1
                        else:
                            side = 1
                            value = rr
                    else:
                        w = True
                        value = -rr
            else:
                w = False

    # Display gates (1v1 + 3.3% suppression + sign check)
    displayed = False
    if value != 0:
        if w:
            displayed = True
        if abs(value / (team1_total + team2_total)) < 0.033:
            displayed = False
    if len(t_one) == 1 and len(t_two) == 1:
        displayed = False
    if not displayed:
        return 0, 0, False
    return js_round(value), side, True
