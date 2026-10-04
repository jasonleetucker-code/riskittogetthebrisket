"""Market side of an owned league pick, for GENERATED-TRADE comparability only.

C7-PICKGEN-01 (owner decision 2026-10-03).  The finder's market gate needs a
retail market value for every asset a generated package sends.  An owned pick
whose draft slot is unknown resolves, canonically, to the GENERIC grade
(``"2027 Round 1"``, ``identity.picks.market_resolution`` → ``unknown_slot``),
and the retail market (KTC) publishes no generic grade — only its own
Early / Mid / Late tier values.  This module is the ONE answer to "what is that
pick worth on the market side of a generated trade", and nothing else:

* it never sets or replaces the canonical standalone pick value (that is
  ``src/api/pick_value_resolution.py``'s, and the finder's model value still
  reads it);
* it never presents a derived number as KTC's native price for the pick;
* it never hard-switches an uncertain pick to one tier.

The formula (owner, verbatim in intent)::

    P_used(tier) = c x P_forecast(tier) + (1 - c) x 1/3
    V_market     = sum over Early/Mid/Late of P_used(tier) x KTC_tier_value

With no forecast (``c = 0``) that is exactly the plain average of KTC's three
native tier values for that exact year and round — the only path live today.
A forecast plugs into the same formula once owned-pick forecasting exists
(C1-U7) AND the league's real rookie-draft-order rule is settled (reverse
standings is NOT established versus Max PF / points); its confidence must be
empirically calibrated and is provisional until then.  Every input travels in
the provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "PICK_MARKET_METHOD_VERSION",
    "TIERS",
    "PickMarketEstimate",
    "TierForecast",
    "unknown_slot_market_value",
]

PICK_MARKET_METHOD_VERSION = "pick_market_v1_tier_average"
TIERS = ("early", "mid", "late")


@dataclass(frozen=True)
class TierForecast:
    """A forecast of where an owned pick lands, with calibrated confidence.

    ``probabilities`` over Early / Mid / Late must sum to 1; ``confidence`` in
    [0, 1] is how much of it to trust (0 = ignore it entirely).
    """

    probabilities: Mapping[str, float]
    confidence: float
    source: str
    calibrated: bool = False

    def validated(self) -> "TierForecast":
        probs = {t: float(self.probabilities.get(t, 0.0)) for t in TIERS}
        if any(p < 0 for p in probs.values()) or abs(sum(probs.values()) - 1.0) > 1e-6:
            raise ValueError("forecast tier probabilities must be non-negative and sum to 1")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("forecast confidence must be within [0, 1]")
        return self


@dataclass(frozen=True)
class PickMarketEstimate:
    """The derived market-side value, or ``value=None`` with a reason."""

    value: int | None
    year: int
    round_num: int
    reason: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "year": self.year,
            "round": self.round_num,
            "reason": self.reason,
            "methodVersion": PICK_MARKET_METHOD_VERSION,
            "classification": "PRIOR",
            "isNativeMarketPrice": False,
            "scope": "generated_trade_comparability_only",
            **self.provenance,
        }


def unknown_slot_market_value(
    year: int,
    round_num: int,
    ktc_tier_values: Mapping[str, float | None],
    *,
    forecast: TierForecast | None = None,
) -> PickMarketEstimate:
    """Derived market value for an owned pick of unknown slot.

    ``ktc_tier_values`` are KTC's NATIVE ``{"early", "mid", "late"}`` values
    for exactly this year and round.  All three are required: averaging a
    subset would bias the answer toward whichever tiers happened to be
    published, so a missing tier makes the pick UNPRICED (``None``), never a
    partial average and never zero.
    """
    native = {t: ktc_tier_values.get(t) for t in TIERS}
    missing = [
        t
        for t, v in native.items()
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0
    ]
    if missing:
        return PickMarketEstimate(
            value=None,
            year=int(year),
            round_num=int(round_num),
            reason="ktc_tier_values_missing:" + ",".join(missing),
            provenance={"ktcTierValues": dict(native)},
        )
    generic_average = sum(float(native[t]) for t in TIERS) / len(TIERS)
    confidence = 0.0
    used = {t: 1.0 / 3.0 for t in TIERS}
    forecast_value: float | None = None
    if forecast is not None:
        f = forecast.validated()
        confidence = float(f.confidence)
        forecast_value = sum(float(f.probabilities[t]) * float(native[t]) for t in TIERS)
        used = {t: confidence * float(f.probabilities[t]) + (1.0 - confidence) / 3.0 for t in TIERS}
    value = sum(used[t] * float(native[t]) for t in TIERS)
    return PickMarketEstimate(
        value=int(round(value)),
        year=int(year),
        round_num=int(round_num),
        provenance={
            "ktcTierValues": {t: float(native[t]) for t in TIERS},
            "genericAverage": round(generic_average, 1),
            "forecastProbabilities": (
                None if forecast is None else {t: forecast.probabilities.get(t) for t in TIERS}
            ),
            "forecastConfidence": None if forecast is None else confidence,
            "forecastSource": None if forecast is None else forecast.source,
            "forecastCalibrated": None if forecast is None else forecast.calibrated,
            "forecastWeightedValue": None if forecast_value is None else round(forecast_value, 1),
            "tierWeightsUsed": {t: round(used[t], 6) for t in TIERS},
            "basis": "plain_ktc_tier_average" if forecast is None else "forecast_shrunk_to_thirds",
        },
    )
