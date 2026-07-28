"""Project a player's reception-band shape forward, for scoring rules
that pay by catch distance.

The problem
───────────
This league bands receptions by yards gained — 0.25/catch at 0-4 yards
rising to 2.00 at 40+. Historical scoring can read the exact bands from
play-by-play (:mod:`src.nfl_data.reception_depth`). **Projections
cannot**: no projection source publishes banded receptions, and it is
unlikely any ever will.

What makes it tractable is that the two halves separate cleanly:

    projected banded points
        = projected receptions          (any ordinary projection source)
        x expected points per catch     (this module)

and the second factor is a **player trait**, not a forecast of events.

Measured stability, per-catch value ratio year over year::

    2023 -> 2024   n=123   r=0.767   beats league-mean by 52.6% of SSE
    2024 -> 2025   n=128   r=0.718   beats league-mean by 44.3% of SSE

r around 0.72-0.77 is high for a year-over-year fantasy metric — most
sit between 0.3 and 0.5. Carrying a player's own shape forward is
substantially better than assuming he catches like the average player at
his position, which is what a flat rate implicitly assumes.

Why shrinkage, and why toward POSITION
───────────────────────────────────────
r=0.72 is high, not 1.0. A player with 22 catches has a shape estimated
from 22 draws across six bands — several will be empty by chance. Taking
that shape at face value would hand the largest adjustments to the
players whose shapes are least known, which is the failure mode the IDP
per-player attempt was refused for (see
:mod:`src.league_intel.scoring_fit`).

So the estimate is shrunk toward the player's POSITION mean, weighted by
sample size::

    w = n / (n + K)
    shape = w * player_shape + (1 - w) * position_shape

Position rather than league-wide because the position means genuinely
differ — an RB's catch distribution is not a noisy draw from the WR
distribution, it is a different distribution, and shrinking toward the
league would drag every back toward a shape no back has.

:data:`SHRINK_K` is fitted, not chosen: see
:func:`fit_shrinkage_constant`, which picks the K minimising next-season
squared error on held-out seasons.

What this module does NOT do
────────────────────────────
It does not project receptions. That is volume, it depends on offence,
role, health and coaching, and it is what ordinary projection sources
already publish. Combining the two is the caller's job.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from src.nfl_data.reception_depth import BAND_KEYS, summarise_histogram

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "SHRINK_K",
    "MIN_RECEPTIONS_FOR_SHAPE",
    "RECENCY_HALF_LIFE_SEASONS",
    "blend_seasons",
    "expected_points_per_catch",
    "fit_shrinkage_constant",
    "position_shapes",
    "project_band_shape",
]

#: How fast older seasons lose weight. At a half-life of 1.0 the prior
#: season counts half as much as the current one, the season before that
#: a quarter, and so on.
#:
#: Chosen rather than fitted, and the distinction is deliberate:
#: :data:`SHRINK_K` is fitted because there is a clean held-out target
#: for it (next season's per-catch value). Recency weighting has no such
#: target without a longer history than the three seasons on disk, and
#: fitting it on two transitions would be reading noise. 1.0 is the
#: conventional default; it is a prior, not a measurement, and is
#: labelled as one.
RECENCY_HALF_LIFE_SEASONS: float = 1.0


def blend_seasons(
    bands_by_season: Mapping[int, Mapping[str, float]],
    *,
    half_life: float = RECENCY_HALF_LIFE_SEASONS,
) -> dict[str, float]:
    """Combine several seasons of raw band counts into one weighted count.

    **This is what makes an in-season shape usable.** In week 4 a player
    has maybe 15 catches — far too few to trust on their own, and
    :func:`project_band_shape` would rightly shrink almost all of it
    away toward his position. But his last two seasons are still
    informative about how he catches, and a receiver whose role has
    genuinely changed will pull his blended shape as the current season
    accumulates.

    Counts are weighted, not shapes, so sample size carries through: a
    3-catch current season contributes 3 weighted catches, not an equal
    vote with a 90-catch prior. The result feeds
    :func:`project_band_shape` exactly as a single season would, so
    shrinkage still applies on top.
    """
    if not bands_by_season:
        return {b: 0.0 for b in BAND_KEYS}
    newest = max(int(s) for s in bands_by_season)
    out = {b: 0.0 for b in BAND_KEYS}
    for season, bands in bands_by_season.items():
        age = newest - int(season)
        weight = 0.5 ** (age / float(half_life)) if half_life > 0 else (1.0 if age == 0 else 0.0)
        for b in BAND_KEYS:
            out[b] += weight * max(0.0, float((bands or {}).get(b, 0) or 0))
    return out


#: Below this the player's own shape is ignored entirely and the
#: position shape is used unchanged. A handful of catches carries no
#: shape information worth the risk of pretending otherwise.
MIN_RECEPTIONS_FOR_SHAPE: int = 8

#: Shrinkage half-weight: at n == SHRINK_K the estimate is half the
#: player's own shape and half his position's.
#:
#: FITTED, not chosen. :func:`fit_shrinkage_constant` scored candidate
#: values on held-out next-season per-catch value (MSE, lower better)::
#:
#:     K            2023->2024   2024->2025   sum
#:     0   own       0.005413     0.005977    0.011390
#:     20            0.004144     0.004305    0.008449
#:     40            0.004010     0.004087    0.008097   <- joint best
#:     60            0.004024     0.004077    0.008101
#:     inf position  0.004905     0.004927    0.009832
#:
#: Shrinkage beats BOTH endpoints on both pairs — 26% better than
#: trusting the player's own shape, 18% better than ignoring him for the
#: position mean. That is the result that justifies the method: if it
#: had beaten neither, the shrinkage would be doing no work.
#:
#: The optimum is flat between roughly 30 and 60, so the exact value is
#: not load-bearing; anything in that range performs within 1% of best.
SHRINK_K: float = 40.0


def _normalise(counts: Mapping[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(counts.get(b, 0) or 0)) for b in BAND_KEYS)
    if total <= 0:
        return {b: 0.0 for b in BAND_KEYS}
    return {b: max(0.0, float(counts.get(b, 0) or 0)) / total for b in BAND_KEYS}


def position_shapes(
    depth_payload: Mapping[str, Any],
    positions: Mapping[str, str],
    *,
    min_receptions: int = MIN_RECEPTIONS_FOR_SHAPE,
) -> dict[str, dict[str, float]]:
    """Catch-weighted mean band shape per position.

    Weighted by catches rather than by player: a position's shape should
    describe how balls are actually caught at that position, and a
    player-weighted mean would let a 9-catch specialist count as much as
    a 100-catch workhorse.
    """
    acc: dict[str, dict[str, float]] = {}
    for gsis, rec in (depth_payload.get("players") or {}).items():
        if not isinstance(rec, dict):
            continue
        pos = str(positions.get(gsis) or "").upper()
        if not pos:
            continue
        bands = rec.get("bands") or {}
        if sum(int(bands.get(b, 0) or 0) for b in BAND_KEYS) < min_receptions:
            continue
        into = acc.setdefault(pos, {b: 0.0 for b in BAND_KEYS})
        for b in BAND_KEYS:
            into[b] += float(bands.get(b, 0) or 0)
    return {pos: _normalise(counts) for pos, counts in acc.items()}


def project_band_shape(
    player_bands: Mapping[str, float] | None,
    position_shape: Mapping[str, float] | None,
    *,
    shrink_k: float = SHRINK_K,
    min_receptions: int = MIN_RECEPTIONS_FOR_SHAPE,
) -> dict[str, float] | None:
    """Shrink a player's observed band shape toward his position's.

    Returns None when neither a usable player shape nor a position shape
    is available — an explicit "unknown", never a fabricated uniform
    distribution, which would silently price the player as league
    average while looking like a measurement.
    """
    pos_shape = _normalise(position_shape or {}) if position_shape else None
    if pos_shape is not None and sum(pos_shape.values()) <= 0:
        pos_shape = None

    n = sum(max(0.0, float((player_bands or {}).get(b, 0) or 0)) for b in BAND_KEYS)
    if n < min_receptions:
        return dict(pos_shape) if pos_shape else None
    own = _normalise(player_bands or {})
    if pos_shape is None:
        return own

    w = n / (n + float(shrink_k))
    return {b: w * own[b] + (1.0 - w) * pos_shape[b] for b in BAND_KEYS}


def expected_points_per_catch(
    shape: Mapping[str, float] | None,
    scoring: Mapping[str, Any],
) -> float | None:
    """Points a single reception is worth to a player with this shape.

    ``None`` shape returns ``None`` rather than a flat rate: a caller
    that cannot tell "unknown" from "league average" will quietly price
    every unknown player as average.
    """
    if not shape:
        return None
    flat = float(scoring.get("rec") or 0.0)
    return sum(float(shape.get(b, 0.0)) * (flat + float(scoring.get(b) or 0.0)) for b in BAND_KEYS)


def fit_shrinkage_constant(
    prior_payload: Mapping[str, Any],
    later_payload: Mapping[str, Any],
    positions: Mapping[str, str],
    scoring: Mapping[str, Any],
    *,
    candidates: tuple[float, ...] = (0.0, 5.0, 10.0, 20.0, 30.0, 34.0, 40.0, 60.0, 100.0, 1e9),
    min_receptions: int = 20,
) -> dict[str, Any]:
    """Pick the K that best predicts NEXT season's per-catch value.

    The honest test for a shrinkage constant: shrink the prior season's
    shape by each candidate K, price it under ``scoring``, and score it
    against what the player's per-catch value actually turned out to be.

    The two endpoints are the baseline models this must beat — K=0 is
    "trust the player's own shape completely", K=infinity is "use the
    position mean and ignore the player". A fitted K that beat neither
    would mean the shrinkage is doing nothing.
    """
    pos_shapes = position_shapes(prior_payload, positions)
    prior_players = prior_payload.get("players") or {}
    later_players = later_payload.get("players") or {}

    pairs: list[tuple[Mapping[str, float], str, float]] = []
    for gsis, later in later_players.items():
        prior = prior_players.get(gsis)
        if not isinstance(prior, dict) or not isinstance(later, dict):
            continue
        later_summary = summarise_histogram(later.get("bands") or {})
        if later_summary["receptions"] < min_receptions:
            continue
        actual = expected_points_per_catch(later_summary["shares"], scoring)
        if actual is None:
            continue
        pos = str(positions.get(gsis) or "").upper()
        pairs.append((prior.get("bands") or {}, pos, actual))

    results: dict[float, float] = {}
    for k in candidates:
        sse = 0.0
        used = 0
        for bands, pos, actual in pairs:
            shape = project_band_shape(bands, pos_shapes.get(pos), shrink_k=k)
            pred = expected_points_per_catch(shape, scoring)
            if pred is None:
                continue
            sse += (pred - actual) ** 2
            used += 1
        if used:
            results[k] = sse / used

    if not results:
        return {"fitted": None, "reason": "no player had both seasons", "n": 0}
    best = min(results, key=lambda k: results[k])
    return {
        "fitted": best,
        "n": len(pairs),
        "mseByK": {str(k): round(v, 8) for k, v in sorted(results.items())},
        "mseAtBest": round(results[best], 8),
        "mseTrustPlayer": round(results.get(0.0, float("nan")), 8),
        "mseIgnorePlayer": round(results.get(max(candidates), float("nan")), 8),
    }
