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
native tier values for that exact year and round.  For the upcoming class the
forecast comes from the season simulation under the league's canonical
draft-order rule (owner decision 2026-10-04: reverse final regular-season
record, ties to the LOWER total Points For — ``src/public_league/
draft_order.py``), with a PROVISIONAL confidence until it is calibrated against
realized drafts (:func:`calibrated_confidence`).  Later classes have no
forecast and stay at the plain average.  Every input travels in the
provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "PICK_MARKET_METHOD_VERSION",
    "PROVISIONAL_CONFIDENCE_CAP",
    "TIERS",
    "PickMarketEstimate",
    "TierForecast",
    "calibrated_confidence",
    "owned_pick_forecasts",
    "progress_bucket",
    "provisional_confidence",
    "tier_probabilities_from_slots",
    "unknown_slot_market_value",
]

PICK_MARKET_METHOD_VERSION = "pick_market_v2_tier_average_forecast_shrink"
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
    #: Explainability: the record / Points For / slot distributions the
    #: probabilities came from, and how the confidence was set.
    provenance: Mapping[str, Any] = field(default_factory=dict)

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
    forecast_unavailable_reason: str | None = None,
    ktc_tier_sources: Mapping[str, str | None] | None = None,
) -> PickMarketEstimate:
    """Derived market value for an owned pick of unknown slot.

    ``forecast_unavailable_reason`` says why no forecast applies when
    ``forecast`` is ``None`` (no recorded draft-order rule, no simulation, a
    later class, an unmapped franchise); ``ktc_tier_sources`` names which KTC
    key priced each tier, so a mixed average is visible rather than silent.

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
            provenance={
                "ktcTierValues": dict(native),
                "ktcTierSources": None if ktc_tier_sources is None else dict(ktc_tier_sources),
            },
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
            "ktcTierSources": None if ktc_tier_sources is None else dict(ktc_tier_sources),
            "genericAverage": round(generic_average, 1),
            "forecastUnavailableReason": (
                (forecast_unavailable_reason or "no_forecast_supplied")
                if forecast is None
                else None
            ),
            "forecastProbabilities": (
                None if forecast is None else {t: forecast.probabilities.get(t) for t in TIERS}
            ),
            "forecastConfidence": None if forecast is None else confidence,
            "forecastSource": None if forecast is None else forecast.source,
            "forecastCalibrated": None if forecast is None else forecast.calibrated,
            "forecastEvidence": None if forecast is None else dict(forecast.provenance),
            "forecastWeightedValue": None if forecast_value is None else round(forecast_value, 1),
            "tierWeightsUsed": {t: round(used[t], 6) for t in TIERS},
            "basis": "plain_ktc_tier_average" if forecast is None else "forecast_shrunk_to_thirds",
        },
    )


# ── The forecast half (owner decision 2026-10-04) ────────────────────
#
# The upcoming class's slot follows the league's CANONICAL draft-order rule
# (``src/public_league/draft_order.py``: reverse final regular-season record,
# ties to the LOWER total Points For).  The season simulation
# (``src/ros/playoff_sim.py``) draws final records and Points For and applies
# that rule per simulation, publishing ``draftSlotDistribution``.  Here a slot
# distribution becomes Early/Mid/Late probabilities and a confidence, and
# :func:`unknown_slot_market_value` shrinks it toward thirds — so the forecast
# replaces the equal-third prior gradually, by evidence, with no new formula.

#: PRIOR, PROVISIONAL: the most a not-yet-calibrated forecast may move the
#: market side mid-season.  Confidence rises with the share of the regular
#: season already FINISHED, in the league's own weeks (an early-season record
#: says little), and reaches 1.0 only when every regular-season week is final
#: — then the final standings are OBSERVED, not forecast.  Replaced by
#: :func:`calibrated_confidence` once enough realized drafts exist.
PROVISIONAL_CONFIDENCE_CAP = 0.5
#: Minimum realized (forecast, slot) outcomes, PER season-progress bucket,
#: before calibration is trusted: two full 12-team classes.
CALIBRATION_MIN_OUTCOMES = 24
#: Season-progress buckets calibration is fitted within: quarters of the
#: regular season, plus "complete".  A week-2 forecast and a week-13 forecast
#: are different instruments and must not share one weight.
PROGRESS_BUCKETS = 4
#: Grid resolution for fitting the shrinkage weight ``c``.
_CALIBRATION_GRID = 100


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def tier_probabilities_from_slots(
    slot_distribution: list[float], *, league_size: int
) -> dict[str, float] | None:
    """``P(slot = i)`` (index 0 = slot 1) → Early/Mid/Late via ``slot_tier``."""
    from src.identity.picks import slot_tier  # noqa: PLC0415

    total = sum(p for p in slot_distribution if _is_number(p))
    if not slot_distribution or total <= 0:
        return None
    probs = {t: 0.0 for t in TIERS}
    for i, p in enumerate(slot_distribution):
        tier = slot_tier(i + 1, league_size=league_size)
        if tier is None or not _is_number(p):
            continue
        probs[tier] += float(p) / total
    return probs


def progress_bucket(weeks_final: Any, weeks_total: Any) -> int | None:
    """``0 .. PROGRESS_BUCKETS - 1`` by quarter of the season, ``PROGRESS_BUCKETS``
    once complete, ``None`` when progress is unknown."""
    if not (_is_number(weeks_final) and _is_number(weeks_total)) or weeks_total <= 0:
        return None
    frac = max(0.0, float(weeks_final)) / float(weeks_total)
    if frac >= 1.0:
        return PROGRESS_BUCKETS
    return min(PROGRESS_BUCKETS - 1, int(frac * PROGRESS_BUCKETS))


def provisional_confidence(weeks_final: Any, weeks_total: Any) -> tuple[float, str]:
    """``(confidence, basis)`` before calibration exists — labelled provisional.

    Inputs are the league's own regular-season weeks (finished / total), as
    ``playoff_sim`` publishes them in ``regularSeasonProgress``.  Unknown
    progress gives the forecast no weight — it is not read as "early".
    """
    if not (_is_number(weeks_final) and _is_number(weeks_total)) or weeks_total <= 0:
        return 0.0, "season_progress_unknown"
    done, total = max(0.0, float(weeks_final)), float(weeks_total)
    if done >= total:
        return 1.0, "final_standings_observed"
    return PROVISIONAL_CONFIDENCE_CAP * done / total, "provisional_season_progress"


def _brier(p: Mapping[str, float], actual: str) -> float:
    return sum((float(p.get(t, 0.0)) - (1.0 if t == actual else 0.0)) ** 2 for t in TIERS)


def calibrated_confidence(
    history: list[tuple[Mapping[str, float], str, int]],
    bucket: int | None,
) -> float | None:
    """The fitted shrinkage weight ``c`` for this season-progress bucket.

    ``history`` is ``[(forecast tier probabilities, realized tier, bucket),
    ...]`` — each a forecast that was MADE at that point of a past season,
    with the tier the league's actual draft order then gave the pick.  Only
    the same bucket's outcomes are used, and ``c`` is fitted directly: the
    value in [0, 1] minimising the mean Brier score of the SHRUNK forecast
    ``c x P + (1 - c)/3`` that :func:`unknown_slot_market_value` actually
    uses.  ``None`` until the bucket holds ``CALIBRATION_MIN_OUTCOMES``.
    """
    if bucket is None:
        return None
    rows = [(p, a) for p, a, b in history if b == bucket and a in TIERS]
    if len(rows) < CALIBRATION_MIN_OUTCOMES:
        return None

    def loss(c: float) -> float:
        return sum(
            _brier({t: c * float(p.get(t, 0.0)) + (1.0 - c) / 3.0 for t in TIERS}, a)
            for p, a in rows
        ) / len(rows)

    grid = [i / _CALIBRATION_GRID for i in range(_CALIBRATION_GRID + 1)]
    # Ties resolve to the SMALLER weight: equal evidence never buys trust.
    return min(grid, key=lambda c: (loss(c), c))


def owned_pick_forecasts(
    sim_payload: Mapping[str, Any] | None,
    contract: Mapping[str, Any] | None,
    *,
    calibration_history: list[tuple[Mapping[str, float], str, int]] | None = None,
) -> dict[int, tuple[int, TierForecast]]:
    """``{originRosterId: (draftYear, TierForecast)}`` for the upcoming class.

    Only the class drafted after the SIMULATED season (``season + 1``) has a
    forecast; later classes have none and stay at the plain average.  A sim
    without ``draftSlotDistribution`` (no recorded draft-order rule) yields
    nothing.  ``calibration_history`` (see :func:`calibrated_confidence`)
    replaces the provisional confidence once the CURRENT season-progress bucket
    holds enough realized outcomes.
    """
    if not isinstance(sim_payload, Mapping) or not sim_payload.get("draftOrderRule"):
        return {}
    try:
        draft_year = int(sim_payload.get("season")) + 1
    except (TypeError, ValueError):
        return {}
    rows = [r for r in sim_payload.get("playoffOdds") or [] if isinstance(r, Mapping)]
    teams = ((contract or {}).get("sleeper") or {}).get("teams") or []
    rid_by_owner: dict[str, int] = {}
    for t in teams:
        try:
            rid_by_owner[str(t.get("ownerId") or "")] = int(t.get("roster_id"))
        except (TypeError, ValueError):
            continue
    league_size = len(rows)
    progress = sim_payload.get("regularSeasonProgress")
    progress = progress if isinstance(progress, Mapping) else {}
    weeks_final, weeks_total = progress.get("weeksFinal"), progress.get("weeksTotal")
    bucket = progress_bucket(weeks_final, weeks_total)
    fitted = calibrated_confidence(calibration_history or [], bucket)
    if fitted is not None:
        confidence, basis, calibrated = fitted, "calibrated_shrinkage_fit", True
    else:
        # Unknown progress gives no weight: the value stays the plain average.
        confidence, basis = provisional_confidence(weeks_final, weeks_total)
        calibrated = False
    out: dict[int, tuple[int, TierForecast]] = {}
    for r in rows:
        rid = rid_by_owner.get(str(r.get("ownerId") or ""))
        dist = r.get("draftSlotDistribution")
        if rid is None or not isinstance(dist, list):
            continue
        probs = tier_probabilities_from_slots(dist, league_size=league_size)
        if probs is None:
            continue
        out[rid] = (
            draft_year,
            TierForecast(
                probabilities=probs,
                confidence=confidence,
                source="season_simulation",
                calibrated=calibrated,
                provenance={
                    "draftOrderRule": sim_payload.get("draftOrderRule"),
                    "simulatedSeason": sim_payload.get("season"),
                    "simulations": sim_payload.get("n_simulations"),
                    "finalRecordDistribution": r.get("finalWins"),
                    "finalPointsForDistribution": r.get("finalPointsFor"),
                    "slotDistribution": [round(float(p), 4) for p in dist],
                    "confidenceBasis": basis,
                    "seasonProgress": {
                        "weeksFinal": weeks_final,
                        "weeksTotal": weeks_total,
                        "bucket": bucket,
                    },
                },
            ),
        )
    return out
