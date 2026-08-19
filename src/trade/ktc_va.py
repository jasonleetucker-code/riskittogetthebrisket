"""KTC's Value Adjustment algorithm — Python port.

Verbatim translation of the JS port in ``frontend/lib/trade-logic.js``
(``ktcProcessV`` / ``ktcReverseAdjust`` / ``ktcAdjustPackage``), which
itself is a verbatim port of KTC's client-side algorithm in
``keeptradecut.com/js/site.min.js``.

This module exists so backend Python code (Angle Finder, trade
suggestions, retro-grading) can compute the same VA the frontend
displays.  Without it, ``/api/angle/find`` and ``/api/angle/packages``
would grade trades with the legacy V2 formula while the trade page
shows KTC's actual VA — same trade, two different numbers.

Parity with the JS port is verified by
``tests/trade/test_ktc_va_python_port.py``, which runs the 139-trade
fixture (``scripts/ktc_va_observations.json``) through both the
Python and JS implementations and asserts agreement to ±1.

──────────────────────────────────────────────────────────────────────
Raw canonical value vs contextual Value Adjustment
──────────────────────────────────────────────────────────────────────
Two quantities, deliberately distinct, and conflating them is defect
#800:

* **raw canonical value** — ``rankDerivedValue``, the one number the
  board publishes for an asset.  VA never mutates it.  A player is
  worth the same whatever package he is in.
* **adjusted side total** — ``raw + VA``, the comparison quantity for
  ONE specific pairing of packages.  It is a property of the trade,
  not of any asset in it, and it is what every fairness verdict,
  meter and gap in this repo is measured on.

The consequence that matters: **VA is a function of BOTH sides'
complete value arrays**, so adding a piece of raw value ``V`` to a side
does NOT move the adjusted gap by ``V``.  Adding a piece re-runs
:func:`ktc_adjust_package` from scratch — the piece count changes, the
progressive-nerf ladder shifts, the recipient side can flip, and the
1-v-1 / 3.3% display gates snap on or off.  Anything that wants to
close a gap must therefore **simulate the post-add adjusted gap**, not
subtract a raw value from it.  See
``suggestions._find_balancers`` and
``frontend/lib/trade-logic.js::findBalancers``.

ONE OWNER.  This module is the only Python implementation of KTC's VA.
``src/trade/market_value_adjustment.py`` is a compatibility re-export of
this file and computes nothing of its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

# Constants lifted from KTC's site.min.js (see frontend/lib/trade-logic.js).
KTC_MAX_PLAYER_VAL = 10000
KTC_T_REFERENCE = 10041
KTC_VARIANCE_PCT = 5

# Aliases kept for the callers that grew up against the (now retired)
# second port in ``market_value_adjustment``.
KTC_MAX_PLAYER_VALUE = KTC_MAX_PLAYER_VAL
KTC_TOP_REFERENCE = KTC_T_REFERENCE
KTC_VARIANCE_PERCENT = KTC_VARIANCE_PCT


def _js_round(value: float) -> int:
    """JavaScript ``Math.round``: half rounds UP, never to even.

    Python's built-in ``round`` is banker's rounding, which disagrees
    with the JS original on exact halves.  Measured over 30,000 random
    packages the two rounding rules produced different published VAs on
    **60** of them (always by 1 point).  The frontend is the reference
    implementation KTC's numbers are matched against, so half-up is the
    correct rule and this helper is used everywhere a value crosses out
    of the algorithm.
    """

    return math.floor(value + 0.5)


@dataclass(frozen=True)
class KtcVAResult:
    """Result of a KTC adjustPackage computation.

    Mirrors the JS shape ``{value, side, displayed}``.  ``side`` is
    KTC's 1-indexed team identifier (1 = team1, 2 = team2, 0 = no VA).
    """

    value: int = 0
    side: int = 0
    displayed: bool = False

    @classmethod
    def empty(cls) -> "KtcVAResult":
        return cls(value=0, side=0, displayed=False)


#: Compatibility alias.  ``market_value_adjustment`` named the same
#: concept ``PackageAdjustment``; it is the SAME class, so results from
#: either import path compare equal.
PackageAdjustment = KtcVAResult


def ktc_process_v(value: float, max_in_trade: float, t: float, nerf_index: int) -> float:
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


def ktc_reverse_adjust(raw_diff: float, max_in_trade: float, t: float, nerf_count: int) -> int:
    """KTC's iterative virtual-player solver (site.min.js::reverseAdjust)."""
    if raw_diff <= 0 or max_in_trade <= 0:
        return 0
    seed = ktc_process_v(max_in_trade, max_in_trade, t, -1)
    n = max_in_trade
    if seed < raw_diff:
        n = max((raw_diff / seed) * max_in_trade * 0.8, max_in_trade)
    l = n / 2
    d = 1.0
    u = 0
    best_err = 1.0
    best_l = -1.0
    while d > 0.025 and u <= 10:
        i = ktc_process_v(l, n, t, nerf_count)
        d = min(1.0, abs(i - raw_diff) / raw_diff)
        if d > 0.025:
            o = l
            p = d * l * 0.75
            l = l + p if i <= raw_diff else l - p
            if d < best_err:
                best_err = d
                best_l = o
                if best_l > max_in_trade:
                    n = best_l
        elif d < best_err:
            best_err = d
            best_l = l
            if best_l > max_in_trade:
                n = best_l
        if u == 10 and d > 0.05:
            f = 0
            l = max(1.0, best_l)
            while d > 0.025 and f <= 10:
                i2 = ktc_process_v(l, n, t, nerf_count)
                d = min(1.0, abs(i2 - raw_diff) / raw_diff)
                if d > 0.025:
                    o = l
                    p = d * l * 0.25
                    l = l + p if i2 <= raw_diff else l - p
                    if d < best_err:
                        best_err = d
                        best_l = o
                        if best_l > max_in_trade:
                            n = best_l
                elif d < best_err:
                    best_err = d
                    best_l = l
                    if best_l > max_in_trade:
                        n = best_l
                f += 1
            l = best_l
        u += 1
    return _js_round(l)


def _ktc_check_equality(a: float, b: float, variance_pct: float) -> bool:
    """KTC's checkEquality — true iff |a-b|/(a+b)*100 ≤ variancePct."""
    s = max(0.0, a) + max(0.0, b)
    if s <= 0:
        return True
    pct = min(100.0, abs(a - b) / s * 100)
    return _js_round(10 * pct) / 10 <= variance_pct


def _build_side_adj(values: Sequence[float], max_in_trade: float, t: float):
    """Build per-piece adjustments with KTC's progressive-nerf rule."""
    half = 0.5 * max_in_trade
    nerf_index = -1
    raw_adj_sum = 0.0
    items = []
    for v in values:
        nerfed = False
        if v < half:
            nerf_index += 1
            nerfed = True
        adj = ktc_process_v(v, max_in_trade, t, nerf_index)
        raw_adj_sum += adj
        items.append({"value": v, "adj": adj, "nerfed": nerfed, "nerfIndex": nerf_index})
    items.sort(key=lambda it: -it["adj"])
    return items, raw_adj_sum


def ktc_adjust_package(
    team1_vals: Iterable[float],
    team2_vals: Iterable[float],
    *,
    variance_pct: float = KTC_VARIANCE_PCT,
    t: float = KTC_T_REFERENCE,
) -> KtcVAResult:
    """KTC's adjustPackage, ported from site.min.js.

    Takes two iterables of raw KTC values and returns a
    :class:`KtcVAResult`.  ``side`` is 1 if team1 receives the VA, 2
    if team2 receives it, 0 (with ``displayed=False``) when KTC would
    suppress the VA badge entirely.
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
        return KtcVAResult.empty()

    team1_total = sum(t_one)
    team2_total = sum(t_two)
    r = max(t_one[0], t_two[0])
    o = ktc_process_v(0.5 * r, r, t, -1)
    s_items, e = _build_side_adj(t_one, r, t)
    n_items, a = _build_side_adj(t_two, r, t)
    h = e / team1_total
    y = a / team2_total
    v = math.floor(abs(e - a))
    k = _ktc_check_equality(team1_total, team2_total, variance_pct)
    b = _ktc_check_equality(e, a, variance_pct)

    # Compute T (extra nerf count for reverseAdjust).  Walks the
    # larger-rawAdj side and records the first item whose adj falls
    # below v.
    T = 0
    if v < o:
        items = n_items if e > a else s_items
        for it in items:
            if it["adj"] < v:
                T = it["nerfIndex"] + 1
                break

    side = 0
    value = 0.0
    w = True

    if k and b:
        # BRANCH 1: trade is fair on both totals AND raw_adj
        if e > a:
            side = 1
            S = ktc_reverse_adjust(v, r, t, T)
            A = team2_total + S - team1_total
            if A > 0:
                value = A
            else:
                w = False
                side = 2
                value = -A
        elif a > e:
            side = 2
            S = ktc_reverse_adjust(v, r, t, T)
            A = team1_total + S - team2_total
            if A > 0:
                value = A
            else:
                w = False
                side = 1
                value = -A
    elif h > y:
        # BRANCH 2: side1 has higher raw_adj intensity
        side = 1
        if e > a:
            S = ktc_reverse_adjust(v, r, t, T)
            A = team2_total + S - team1_total
            if A > 0:
                value = A
            else:
                w = False
                side = 2
                value = abs(A)
        else:
            # h > y but e <= a — "intensity flip" special branch
            V = -1
            if team1_total < team2_total:
                V = 1
            elif team2_total < team1_total:
                V = 2
            M = ktc_reverse_adjust(abs(e - a), max(*t_one, *t_two), 10099, T)
            if M > 0 and V > 0:
                side = V
                if V == 2:
                    R = M - (team1_total - team2_total)
                    if R > 0:
                        value = R
                    else:
                        w = False
                        value = R
                else:
                    R = M - (team2_total - team1_total)
                    if R > 0:
                        if R > KTC_MAX_PLAYER_VAL:
                            w = False
                            value = 0
                            side = 1
                        else:
                            side = 2
                            value = R
                    else:
                        w = True
                        value = -R
            else:
                w = False
    else:
        # BRANCH 3: side2 has higher raw_adj intensity (mirror of branch 2)
        side = 2
        if a > e:
            S = ktc_reverse_adjust(v, r, t, T)
            A = team1_total + S - team2_total
            if A > 0:
                value = A
            else:
                w = False
                side = 1
                value = abs(A)
        else:
            V = -1
            if team1_total < team2_total:
                V = 1
            elif team2_total < team1_total:
                V = 2
            M = ktc_reverse_adjust(abs(e - a), max(*t_one, *t_two), 10099, T)
            if M > 0 and V > 0:
                side = V
                if V == 1:
                    R = M - (team2_total - team1_total)
                    if R > 0:
                        value = R
                    else:
                        w = False
                        value = R
                else:
                    R = M - (team1_total - team2_total)
                    if R > 0:
                        if R > KTC_MAX_PLAYER_VAL:
                            w = False
                            value = 0
                            side = 1
                        else:
                            side = 1
                            value = R
                    else:
                        w = True
                        value = -R
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
        return KtcVAResult.empty()
    return KtcVAResult(value=_js_round(value), side=side, displayed=True)


def adjusted_pair_totals(
    small_values: Iterable[float],
    large_values: Iterable[float],
) -> tuple[float, float, float, float]:
    """Apply KTC's VA to a pair of value lists.

    Drop-in replacement for the legacy ``angle._adjusted_pair_totals``
    that uses KTC's actual algorithm via :func:`ktc_adjust_package`.

    Returns ``(small_adjusted, large_adjusted, small_va, large_va)``.
    Sign convention: each side's adjusted total is its raw sum plus
    its VA (≥ 0).  When KTC suppresses the VA badge (1v1, < 3.3%,
    "Fair Trade"), both VAs are zero and adjusted totals equal raw.
    """
    small_list = [float(v) for v in small_values if v is not None and float(v) > 0]
    large_list = [float(v) for v in large_values if v is not None and float(v) > 0]
    small_sum = sum(small_list)
    large_sum = sum(large_list)
    if not small_list or not large_list:
        return small_sum, large_sum, 0.0, 0.0
    # Pass small=team1, large=team2 to ktc_adjust_package; map result.side
    # back to whichever input list it refers to.
    result = ktc_adjust_package(small_list, large_list)
    if not result.displayed or result.value <= 0:
        return small_sum, large_sum, 0.0, 0.0
    if result.side == 1:
        return small_sum + result.value, large_sum, float(result.value), 0.0
    return small_sum, large_sum + result.value, 0.0, float(result.value)
