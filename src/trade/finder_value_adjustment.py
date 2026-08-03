"""Install KTC package Value Adjustment into the trade arbitrage finder.

The finder historically summed market values linearly while the trade
calculator used KTC's package adjustment. This adapter makes the finder
score the same adjusted totals without mutating the individual assets that
are returned to the API/UI.
"""

from __future__ import annotations

from dataclasses import replace
from functools import wraps
from types import ModuleType
from typing import Any

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


def install(finder: ModuleType) -> None:
    """Patch one loaded ``src.trade.finder`` module exactly once."""

    if getattr(finder, "_MARKET_VALUE_ADJUSTMENT_INSTALLED", False):
        return

    original_score = finder._score_trade
    original_to_dict = finder.TradeCandidate.to_dict

    @wraps(original_score)
    def score_with_value_adjustment(give: list[Any], receive: list[Any]):
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

        candidate = original_score(scoring_give, scoring_receive)
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
            label = (
                "your give side"
                if adjustment_side == "give"
                else "your receive side"
            )
            candidate.summary += (
                f" Market package adjustment: +{adjustment.value:,} to {label}."
            )
        else:
            candidate.ranking_factors.setdefault("marketValueAdjustment", 0)

        return candidate

    @wraps(original_to_dict)
    def to_dict_with_value_adjustment(candidate: Any) -> dict[str, Any]:
        payload = original_to_dict(candidate)
        raw_give = getattr(candidate, "raw_give_ktc_total", candidate.give_ktc_total)
        raw_receive = getattr(
            candidate,
            "raw_receive_ktc_total",
            candidate.receive_ktc_total,
        )
        adjusted_give = getattr(
            candidate,
            "adjusted_give_ktc_total",
            candidate.give_ktc_total,
        )
        adjusted_receive = getattr(
            candidate,
            "adjusted_receive_ktc_total",
            candidate.receive_ktc_total,
        )
        adjustment_value = getattr(candidate, "market_value_adjustment", 0)
        adjustment_side = getattr(candidate, "market_value_adjustment_side", None)
        payload.update(
            {
                "rawGiveKtcTotal": raw_give,
                "rawReceiveKtcTotal": raw_receive,
                "adjustedGiveKtcTotal": adjusted_give,
                "adjustedReceiveKtcTotal": adjusted_receive,
                "marketValueAdjustment": adjustment_value,
                "marketValueAdjustmentSide": adjustment_side,
                "marketValueAdjustmentApplied": bool(
                    adjustment_value > 0 and adjustment_side
                ),
            }
        )
        return payload

    finder._score_trade = score_with_value_adjustment
    finder.TradeCandidate.to_dict = to_dict_with_value_adjustment
    finder._MARKET_VALUE_ADJUSTMENT_INSTALLED = True
