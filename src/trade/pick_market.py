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
#: season already played (an early-season record says little), and reaches
#: 1.0 only when the regular season is complete — then the final standings
#: are OBSERVED, not forecast.  Replaced by :func:`calibrated_confidence`
#: once enough realized drafts exist.
PROVISIONAL_CONFIDENCE_CAP = 0.5
#: Minimum realized (forecast, slot) outcomes before calibration is trusted:
#: two full 12-team classes.
CALIBRATION_MIN_OUTCOMES = 24


def tier_probabilities_from_slots(
    slot_distribution: list[float], *, league_size: int
) -> dict[str, float] | None:
    """``P(slot = i)`` (index 0 = slot 1) → Early/Mid/Late via ``slot_tier``."""
    from src.identity.picks import slot_tier  # noqa: PLC0415

    total = sum(p for p in slot_distribution if isinstance(p, (int, float)))
    if not slot_distribution or total <= 0:
        return None
    probs = {t: 0.0 for t in TIERS}
    for i, p in enumerate(slot_distribution):
        tier = slot_tier(i + 1, league_size=league_size)
        if tier is None or not isinstance(p, (int, float)):
            continue
        probs[tier] += float(p) / total
    return probs


def provisional_confidence(games_played: int, games_remaining: int) -> tuple[float, str]:
    """``(confidence, basis)`` before calibration exists — labelled provisional."""
    played, remaining = max(0, int(games_played)), max(0, int(games_remaining))
    if played > 0 and remaining == 0:
        return 1.0, "final_standings_observed"
    total = played + remaining
    if total <= 0:
        return 0.0, "no_regular_season_evidence"
    return PROVISIONAL_CONFIDENCE_CAP * played / total, "provisional_season_progress"


def calibrated_confidence(
    history: list[tuple[Mapping[str, float], str]],
) -> float | None:
    """Confidence from realized outcomes, or ``None`` until there are enough.

    ``history`` is ``[(forecast tier probabilities, realized tier), ...]`` where
    the realized tier comes from the league's actual draft order.  The score is
    the forecast's Brier skill against the equal-thirds prior, clamped to
    [0, 1]: a forecast no better than thirds earns no weight.
    """
    if len(history) < CALIBRATION_MIN_OUTCOMES:
        return None
    uniform = {t: 1.0 / 3.0 for t in TIERS}

    def brier(p: Mapping[str, float], actual: str) -> float:
        return sum((float(p.get(t, 0.0)) - (1.0 if t == actual else 0.0)) ** 2 for t in TIERS)

    model = sum(brier(p, a) for p, a in history) / len(history)
    base = sum(brier(uniform, a) for _p, a in history) / len(history)
    if base <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - model / base))


def owned_pick_forecasts(
    sim_payload: Mapping[str, Any] | None,
    contract: Mapping[str, Any] | None,
    *,
    calibration: float | None = None,
) -> dict[int, tuple[int, TierForecast]]:
    """``{originRosterId: (draftYear, TierForecast)}`` for the upcoming class.

    Only the class drafted after the SIMULATED season (``season + 1``) has a
    forecast; later classes have none and stay at the plain average.  A sim
    without ``draftSlotDistribution`` (no recorded draft-order rule) yields
    nothing.  ``calibration`` (from :func:`calibrated_confidence`) replaces the
    provisional confidence when supplied.
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
    if calibration is not None:
        confidence, basis, calibrated = float(calibration), "calibrated_brier_skill", True
    else:
        played = sim_payload.get("regularSeasonGamesPlayed")
        remaining = sim_payload.get("regularSeasonGamesRemaining")
        if isinstance(played, int) and isinstance(remaining, int):
            confidence, basis = provisional_confidence(played, remaining)
        else:
            # Season progress unknown: no evidence to lean on, so the forecast
            # gets no weight and the value stays the plain tier average.
            confidence, basis = 0.0, "season_progress_unknown"
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
                },
            ),
        )
    return out
