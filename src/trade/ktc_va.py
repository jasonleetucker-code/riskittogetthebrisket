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

ONE OWNER — of the PRIVATE-side API.  This module is the sole Python owner
of KTC VA's dataclass-shaped interface consumed by ``src/trade`` and its
callers.  ``src/trade/market_value_adjustment.py`` is a compatibility
re-export of this file and computes nothing of its own.

The underlying arithmetic (``processV`` / ``reverseAdjust`` / ``adjustPackage``)
now lives one layer down, in ``src/valuation_math/ktc_va_core.py`` — a
stdlib-only module with no dependency on anything private, so that the public
``/league`` grading path (``src/public_league/trade_grading.py``, which is
structurally forbidden from importing ``src.trade`` at all — see that
module's docstring and ``tests/public_league/test_public_contract.py::
ImportSurfaceTests``) can share the SAME algorithm instead of maintaining its
own copy.  This module's job is the private-side dataclass wrapper
(:class:`KtcVAResult`) and the historical public names below; it computes
nothing the core does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.valuation_math.ktc_va_core import (
    KTC_MAX_PLAYER_VAL,
    KTC_T_REFERENCE,
    KTC_VARIANCE_PCT,
)
from src.valuation_math.ktc_va_core import adjust_package_raw as _adjust_package_raw
from src.valuation_math.ktc_va_core import js_round as _js_round  # noqa: F401 — kept for test/legacy import compat
from src.valuation_math.ktc_va_core import process_v as ktc_process_v
from src.valuation_math.ktc_va_core import reverse_adjust as ktc_reverse_adjust

__all__ = [
    "KTC_MAX_PLAYER_VAL",
    "KTC_MAX_PLAYER_VALUE",
    "KTC_T_REFERENCE",
    "KTC_TOP_REFERENCE",
    "KTC_VARIANCE_PCT",
    "KTC_VARIANCE_PERCENT",
    "KtcVAResult",
    "PackageAdjustment",
    "adjusted_pair_totals",
    "ktc_adjust_package",
    "ktc_process_v",
    "ktc_reverse_adjust",
]

# Aliases kept for the callers that grew up against the (now retired)
# second port in ``market_value_adjustment``.
KTC_MAX_PLAYER_VALUE = KTC_MAX_PLAYER_VAL
KTC_TOP_REFERENCE = KTC_T_REFERENCE
KTC_VARIANCE_PERCENT = KTC_VARIANCE_PCT


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

    The branch structure lives in :func:`src.valuation_math.ktc_va_core.
    adjust_package_raw`; this wrapper only maps its plain-tuple return onto
    this module's historical dataclass shape.
    """
    value, side, displayed = _adjust_package_raw(
        team1_vals, team2_vals, variance_pct=variance_pct, t=t
    )
    if not displayed:
        return KtcVAResult.empty()
    return KtcVAResult(value=value, side=side, displayed=True)


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
