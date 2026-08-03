"""KTC-native package Value Adjustment for backend trade engines.

This is a line-for-line Python port of the authoritative frontend
implementation in ``frontend/lib/trade-logic.js::ktcAdjustPackage``.
Keep the parity fixtures in ``tests/trade/test_finder_value_adjustment.py``
green whenever either runtime changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Iterable

KTC_MAX_PLAYER_VALUE = 10_000
KTC_TOP_REFERENCE = 10_041
KTC_VARIANCE_PERCENT = 5.0


@dataclass(frozen=True)
class PackageAdjustment:
    """Displayed package adjustment and the side that receives it.

    ``side`` follows KTC's convention: 1 for the first side, 2 for the
    second side, and 0 when no adjustment is displayed.
    """

    value: int = 0
    side: int = 0
    displayed: bool = False


def _js_round(value: float) -> int:
    """Match JavaScript ``Math.round`` rather than Python banker's rounding."""

    return floor(value + 0.5)


def ktc_process_value(
    value: float,
    max_in_trade: float,
    top_reference: float = KTC_TOP_REFERENCE,
    nerf_index: int = -1,
) -> float:
    """Port of KTC ``processV`` from the calculator's canonical JS path."""

    if not (value > 0 and max_in_trade > 0 and top_reference > 0):
        return 0.0
    adjusted = (
        0.05 * (value / top_reference) ** 1.3 + 0.05 * (value / (1.05 * max_in_trade)) ** 6 + 0.1
    ) * value
    if nerf_index > 0:
        adjusted *= max(0.6, 1 - 0.15 * nerf_index)
    if adjusted < 0:
        adjusted /= 4
    return adjusted


def ktc_reverse_adjust(
    raw_difference: float,
    max_in_trade: float,
    top_reference: float = KTC_TOP_REFERENCE,
    nerf_count: int = 0,
) -> int:
    """Port of KTC ``reverseAdjust`` iterative virtual-player solver."""

    if not (raw_difference > 0 and max_in_trade > 0):
        return 0

    seed = ktc_process_value(max_in_trade, max_in_trade, top_reference, -1)
    current_max = max_in_trade
    if seed < raw_difference:
        current_max = max(
            (raw_difference / seed) * max_in_trade * 0.8,
            max_in_trade,
        )

    candidate = current_max / 2
    error = 1.0
    iteration = 0
    best_error = 1.0
    best_candidate = -1.0

    while error > 0.025 and iteration <= 10:
        processed = ktc_process_value(
            candidate,
            current_max,
            top_reference,
            nerf_count,
        )
        error = min(1.0, abs(processed - raw_difference) / raw_difference)
        if error > 0.025:
            previous = candidate
            step = error * candidate * 0.75
            candidate += step if processed <= raw_difference else -step
            if error < best_error:
                best_error = error
                best_candidate = previous
                if best_candidate > max_in_trade:
                    current_max = best_candidate
        elif error < best_error:
            best_error = error
            best_candidate = candidate
            if best_candidate > max_in_trade:
                current_max = best_candidate

        if iteration == 10 and error > 0.05:
            refinement = 0
            candidate = max(1.0, best_candidate)
            while error > 0.025 and refinement <= 10:
                processed = ktc_process_value(
                    candidate,
                    current_max,
                    top_reference,
                    nerf_count,
                )
                error = min(1.0, abs(processed - raw_difference) / raw_difference)
                if error > 0.025:
                    previous = candidate
                    step = error * candidate * 0.25
                    candidate += step if processed <= raw_difference else -step
                    if error < best_error:
                        best_error = error
                        best_candidate = previous
                        if best_candidate > max_in_trade:
                            current_max = best_candidate
                elif error < best_error:
                    best_error = error
                    best_candidate = candidate
                    if best_candidate > max_in_trade:
                        current_max = best_candidate
                refinement += 1
            candidate = best_candidate
        iteration += 1

    return _js_round(candidate)


def _check_equality(a: float, b: float, variance_percent: float) -> bool:
    total = max(0.0, a) + max(0.0, b)
    if total <= 0:
        return True
    percentage = min(100.0, abs(a - b) / total * 100)
    rounded = _js_round(10 * percentage) / 10
    return rounded <= variance_percent


def _build_side_adjustments(
    values: list[float],
    max_in_trade: float,
    top_reference: float,
) -> tuple[list[dict[str, float | int | bool]], float]:
    half_max = 0.5 * max_in_trade
    nerf_index = -1
    raw_sum = 0.0
    items: list[dict[str, float | int | bool]] = []

    for value in values:
        nerfed = False
        if value < half_max:
            nerf_index += 1
            nerfed = True
        adjustment = ktc_process_value(
            value,
            max_in_trade,
            top_reference,
            nerf_index,
        )
        raw_sum += adjustment
        items.append(
            {
                "value": value,
                "adjustment": adjustment,
                "nerfed": nerfed,
                "nerf_index": nerf_index,
            }
        )

    items.sort(key=lambda item: -float(item["adjustment"]))
    return items, raw_sum


def ktc_adjust_package(
    first_values: Iterable[int | float],
    second_values: Iterable[int | float],
    *,
    variance_percent: float = KTC_VARIANCE_PERCENT,
    top_reference: float = KTC_TOP_REFERENCE,
) -> PackageAdjustment:
    """Return KTC's displayed package adjustment for two value arrays."""

    first = sorted(
        (float(value) for value in first_values if float(value) > 0),
        reverse=True,
    )
    second = sorted(
        (float(value) for value in second_values if float(value) > 0),
        reverse=True,
    )
    if not first or not second:
        return PackageAdjustment()

    first_total = sum(first)
    second_total = sum(second)
    max_in_trade = max(first[0], second[0])
    half_max_reference = ktc_process_value(
        0.5 * max_in_trade,
        max_in_trade,
        top_reference,
        -1,
    )
    first_items, first_raw = _build_side_adjustments(
        first,
        max_in_trade,
        top_reference,
    )
    second_items, second_raw = _build_side_adjustments(
        second,
        max_in_trade,
        top_reference,
    )
    first_intensity = first_raw / first_total
    second_intensity = second_raw / second_total
    raw_difference = floor(abs(first_raw - second_raw))
    totals_equal = _check_equality(first_total, second_total, variance_percent)
    raws_equal = _check_equality(first_raw, second_raw, variance_percent)

    extra_nerf_count = 0
    if raw_difference < half_max_reference:
        items = second_items if first_raw > second_raw else first_items
        for item in items:
            if float(item["adjustment"]) < raw_difference:
                extra_nerf_count = int(item["nerf_index"]) + 1
                break

    side = 0
    value = 0.0
    sign_gate = True

    if totals_equal and raws_equal:
        if first_raw > second_raw:
            side = 1
            virtual = ktc_reverse_adjust(
                raw_difference,
                max_in_trade,
                top_reference,
                extra_nerf_count,
            )
            difference = second_total + virtual - first_total
            if difference > 0:
                value = difference
            else:
                sign_gate = False
                side = 2
                value = -difference
        elif second_raw > first_raw:
            side = 2
            virtual = ktc_reverse_adjust(
                raw_difference,
                max_in_trade,
                top_reference,
                extra_nerf_count,
            )
            difference = first_total + virtual - second_total
            if difference > 0:
                value = difference
            else:
                sign_gate = False
                side = 1
                value = -difference
    elif first_intensity > second_intensity:
        side = 1
        if first_raw > second_raw:
            virtual = ktc_reverse_adjust(
                raw_difference,
                max_in_trade,
                top_reference,
                extra_nerf_count,
            )
            difference = second_total + virtual - first_total
            if difference > 0:
                value = difference
            else:
                sign_gate = False
                side = 2
                value = abs(difference)
        else:
            total_side = -1
            if first_total < second_total:
                total_side = 1
            elif second_total < first_total:
                total_side = 2
            virtual = ktc_reverse_adjust(
                abs(first_raw - second_raw),
                max(first + second),
                10_099,
                extra_nerf_count,
            )
            if virtual > 0 and total_side > 0:
                side = total_side
                if total_side == 2:
                    remainder = virtual - (first_total - second_total)
                    if remainder > 0:
                        value = remainder
                    else:
                        sign_gate = False
                        value = remainder
                else:
                    remainder = virtual - (second_total - first_total)
                    if remainder > 0:
                        if remainder > KTC_MAX_PLAYER_VALUE:
                            sign_gate = False
                            value = 0
                            side = 1
                        else:
                            side = 2
                            value = remainder
                    else:
                        sign_gate = True
                        value = -remainder
            else:
                sign_gate = False
    else:
        side = 2
        if second_raw > first_raw:
            virtual = ktc_reverse_adjust(
                raw_difference,
                max_in_trade,
                top_reference,
                extra_nerf_count,
            )
            difference = first_total + virtual - second_total
            if difference > 0:
                value = difference
            else:
                sign_gate = False
                side = 1
                value = abs(difference)
        else:
            total_side = -1
            if first_total < second_total:
                total_side = 1
            elif second_total < first_total:
                total_side = 2
            virtual = ktc_reverse_adjust(
                abs(first_raw - second_raw),
                max(first + second),
                10_099,
                extra_nerf_count,
            )
            if virtual > 0 and total_side > 0:
                side = total_side
                if total_side == 1:
                    remainder = virtual - (second_total - first_total)
                    if remainder > 0:
                        value = remainder
                    else:
                        sign_gate = False
                        value = remainder
                else:
                    remainder = virtual - (first_total - second_total)
                    if remainder > 0:
                        if remainder > KTC_MAX_PLAYER_VALUE:
                            sign_gate = False
                            value = 0
                            side = 1
                        else:
                            side = 1
                            value = remainder
                    else:
                        sign_gate = True
                        value = -remainder
            else:
                sign_gate = False

    displayed = False
    if value != 0:
        if sign_gate:
            displayed = True
        if abs(value / (first_total + second_total)) < 0.033:
            displayed = False
    if len(first) == 1 and len(second) == 1:
        displayed = False
    if not displayed:
        return PackageAdjustment()
    return PackageAdjustment(value=_js_round(value), side=side, displayed=True)
