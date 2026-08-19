"""KTC package Value Adjustment for the trade arbitrage finder.

The finder historically summed market values linearly while the trade
calculator used KTC's package adjustment. These helpers make the finder score
the same adjusted totals without mutating the individual assets that are
returned to the API/UI.

RETIRED 2026-08-18: ``install(finder)``
───────────────────────────────────────
Until now this module MONKEYPATCHED the finder — ``src/trade/__init__.py``
rebound ``finder._score_trade`` and ``finder.TradeCandidate.to_dict`` at
package-import time. It worked, and Python's import machinery made it
impossible to bypass (importing a submodule imports its package first), but
three things were wrong with it:

* **The behaviour was invisible from the code that had it.** Reading
  ``finder.py`` told you the finder scored linearly. It did not, and nothing
  in that file said so.
* **"Impossible today because of how imports work"** is a guarantee that a
  refactor nobody thought was risky can remove, and its removal is silent —
  the finder would go on returning trades, scored on a different basis.
* **Double-installing wrapped the wrapper**, adjusting the adjustment. The
  idempotence flag was load-bearing and nothing said why.

``finder.py`` now calls :func:`score_with_value_adjustment` and
:func:`value_adjustment_payload` directly, so the VA is part of the scorer
rather than something done to it afterwards. The guarantee is structural
instead of circumstantial, and ``tests/trade/test_finder_va_is_not_bypassable.py``
pins it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from .market_value_adjustment import PackageAdjustment, ktc_adjust_package


def _market_values(assets: list[Any]) -> list[int]:
    return [int(asset.market_value) for asset in assets if asset.has_market]


def _apply_side_adjustment(assets: list[Any], adjustment: int) -> list[Any]:
    """Clone one asset so the legacy scorer sees the adjusted side total.

    Value Adjustment is side-level math. The existing scorer accepts only
    per-asset values, so the premium is attached temporarily to the largest
    market-valued piece. The returned candidate is restored to the original
    assets before serialization, preventing the synthetic premium from being
    displayed as an individual player's market value.
    """

    if adjustment <= 0 or not assets:
        return list(assets)
    eligible = [
        (index, int(asset.market_value or 0))
        for index, asset in enumerate(assets)
        if asset.has_market
    ]
    if not eligible:
        return list(assets)
    index, value = max(eligible, key=lambda item: item[1])
    adjusted = list(assets)
    adjusted[index] = replace(adjusted[index], market_value=value + adjustment)
    return adjusted


def _adjustment_for(give: list[Any], receive: list[Any]) -> PackageAdjustment:
    all_assets = [*give, *receive]
    if not all_assets or not all(asset.has_market for asset in all_assets):
        return PackageAdjustment()
    return ktc_adjust_package(_market_values(give), _market_values(receive))


def score_with_value_adjustment(
    give: list[Any],
    receive: list[Any],
    score: Callable[[list[Any], list[Any]], Any],
) -> Any:
    """Score a package on KTC-adjusted side totals.

    ``score`` is the underlying value-only scorer.  The premium is attached to
    the largest market-valued piece for the duration of that call and then
    REMOVED, so a synthetic per-asset value can never reach the response.
    """

    raw_give_total = sum(_market_values(give))
    raw_receive_total = sum(_market_values(receive))
    adjustment = _adjustment_for(give, receive)

    scoring_give = list(give)
    scoring_receive = list(receive)
    adjustment_side: str | None = None
    if adjustment.displayed and adjustment.value > 0:
        if adjustment.side == 1:
            scoring_give = _apply_side_adjustment(give, adjustment.value)
            adjustment_side = "give"
        elif adjustment.side == 2:
            scoring_receive = _apply_side_adjustment(receive, adjustment.value)
            adjustment_side = "receive"

    candidate = score(scoring_give, scoring_receive)
    if candidate is None:
        return None

    # Never leak the synthetic per-asset value into the response.
    candidate.give = list(give)
    candidate.receive = list(receive)
    candidate.raw_give_ktc_total = raw_give_total
    candidate.raw_receive_ktc_total = raw_receive_total
    candidate.market_value_adjustment = adjustment.value if adjustment_side else 0
    candidate.market_value_adjustment_side = adjustment_side
    candidate.adjusted_give_ktc_total = candidate.give_ktc_total
    candidate.adjusted_receive_ktc_total = candidate.receive_ktc_total

    if adjustment_side:
        flag = f"market_value_adjustment_{adjustment_side}"
        if flag not in candidate.flags:
            candidate.flags.append(flag)
        candidate.ranking_factors["marketValueAdjustment"] = adjustment.value
        label = "your give side" if adjustment_side == "give" else "your receive side"
        candidate.summary += f" Market package adjustment: +{adjustment.value:,} to {label}."
    else:
        candidate.ranking_factors.setdefault("marketValueAdjustment", 0)

    return candidate


def value_adjustment_payload(candidate: Any) -> dict[str, Any]:
    """The VA fields a scored candidate publishes."""

    raw_give = getattr(candidate, "raw_give_ktc_total", candidate.give_ktc_total)
    raw_receive = getattr(candidate, "raw_receive_ktc_total", candidate.receive_ktc_total)
    adjusted_give = getattr(candidate, "adjusted_give_ktc_total", candidate.give_ktc_total)
    adjusted_receive = getattr(candidate, "adjusted_receive_ktc_total", candidate.receive_ktc_total)
    adjustment_value = getattr(candidate, "market_value_adjustment", 0)
    adjustment_side = getattr(candidate, "market_value_adjustment_side", None)
    return {
        "rawGiveKtcTotal": raw_give,
        "rawReceiveKtcTotal": raw_receive,
        "adjustedGiveKtcTotal": adjusted_give,
        "adjustedReceiveKtcTotal": adjusted_receive,
        "marketValueAdjustment": adjustment_value,
        "marketValueAdjustmentSide": adjustment_side,
        "marketValueAdjustmentApplied": bool(adjustment_value > 0 and adjustment_side),
    }
