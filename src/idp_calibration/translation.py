"""Intrinsic / market / final multiplier math.

Converts per-season bucket centers into per-bucket multipliers:

* **Intrinsic** — "what my-league scoring + my-league lineup economics
  say this bucket is worth". Normalised against the top bucket so
  the top bucket in each position has multiplier 1.0.
* **Market** — same recipe but using the test-league centers. This
  is treated as a prior, not ground truth.
* **Final** — convex blend ``alpha * intrinsic + (1 - alpha) * market``.

Multi-year weighting folds per-season buckets into a single table by
applying recency weights and skipping missing seasons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .buckets import BucketResult

DEFAULT_YEAR_WEIGHTS: dict[int, float] = {
    2025: 0.40,
    2024: 0.30,
    2023: 0.20,
    2022: 0.10,
}

DEFAULT_BLEND: dict[str, float] = {"intrinsic": 0.75, "market": 0.25}


@dataclass
class BucketMultipliers:
    label: str
    intrinsic: float
    market: float
    final: float
    count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "intrinsic": round(self.intrinsic, 4),
            "market": round(self.market, 4),
            "final": round(self.final, 4),
            "count": int(self.count),
        }


@dataclass
class PositionMultipliers:
    position: str
    buckets: list[BucketMultipliers] = field(default_factory=list)

    def by_label(self, kind: str = "final") -> dict[str, float]:
        return {b.label: getattr(b, kind) for b in self.buckets}

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "buckets": [b.to_dict() for b in self.buckets],
        }


def _weighted_center(
    year_to_center: dict[int, float],
    year_weights: dict[int, float],
) -> tuple[float, float]:
    """Return (weighted_value, sum_of_weights_used).

    Only seasons present in ``year_to_center`` contribute weight. If
    all weights are zero the function returns (0.0, 0.0).
    """
    total_val = 0.0
    total_w = 0.0
    for year, center in year_to_center.items():
        w = float(year_weights.get(int(year), 0.0))
        if w <= 0:
            continue
        total_val += float(center) * w
        total_w += w
    if total_w <= 0:
        return 0.0, 0.0
    return total_val / total_w, total_w


def _normalise(values: list[float]) -> list[float]:
    """Normalise so the top (first) bucket equals 1.0.

    If the top bucket is zero we fall back to the max abs value; if
    everything is zero we return 1.0s so downstream code doesn't get
    divide-by-zero.
    """
    if not values:
        return []
    anchor = values[0]
    if abs(anchor) < 1e-9:
        anchor = max((abs(v) for v in values), default=0.0)
    if abs(anchor) < 1e-9:
        return [1.0 for _ in values]
    return [v / anchor for v in values]


def _collect_year_centers(
    per_season: dict[int, list[BucketResult]],
    label: str,
    field_name: str,
) -> dict[int, float]:
    out: dict[int, float] = {}
    for year, buckets in per_season.items():
        for bucket in buckets:
            if bucket.label == label:
                out[int(year)] = float(getattr(bucket, field_name))
                break
    return out


def _bucket_labels(per_season: dict[int, list[BucketResult]]) -> list[str]:
    """Return the union of bucket labels across every season.

    Seasons can disagree on the label set when small buckets merge into
    neighbours in one year but survive in another. Using only the first
    season's labels (the previous behaviour) silently dropped valid
    data. We now collect every label we've seen and sort by the
    numeric low bound so the multiplier tables stay in rank order.
    """
    labels_with_lo: dict[str, int] = {}
    for buckets in per_season.values():
        for b in buckets:
            if b.label in labels_with_lo:
                continue
            try:
                labels_with_lo[b.label] = int(b.label.split("-")[0])
            except (TypeError, ValueError):
                labels_with_lo[b.label] = 10**9
    return sorted(labels_with_lo.keys(), key=lambda lbl: labels_with_lo[lbl])


def compute_position_multipliers(
    per_season: dict[int, list[BucketResult]],
    *,
    year_weights: dict[int, float] | None = None,
    blend: dict[str, float] | None = None,
    multiplier_floor: float = 0.05,
) -> PositionMultipliers:
    """Combine per-season bucket tables into per-bucket multipliers.

    ``multiplier_floor`` (default ``0.05``) clamps every emitted
    multiplier to a positive minimum. Without it, sub-replacement
    buckets produce **negative** multipliers: VOR goes negative for
    players below replacement, normalisation against the positive
    top bucket yields a negative ratio, and the live pipeline would
    multiply ``rankDerivedValue`` by a negative number — flipping a
    player's value sign, which is nonsense (a bench depth player
    still has positive trade value, just a small one). Flooring at
    5% matches the anchor-curve floor so bucket and anchor lookups
    don't disagree.
    """
    year_weights = year_weights or DEFAULT_YEAR_WEIGHTS
    blend = blend or DEFAULT_BLEND
    labels = _bucket_labels(per_season)
    intrinsic_raw: list[float] = []
    market_raw: list[float] = []
    counts: list[int] = []
    for label in labels:
        mine_centers = _collect_year_centers(per_season, label, "center_vor_mine")
        test_centers = _collect_year_centers(per_season, label, "center_vor_test")
        mine_val, _ = _weighted_center(mine_centers, year_weights)
        test_val, _ = _weighted_center(test_centers, year_weights)
        intrinsic_raw.append(mine_val)
        market_raw.append(test_val)
        total_count = 0
        for buckets in per_season.values():
            for b in buckets:
                if b.label == label:
                    total_count += int(b.count)
                    break
        counts.append(total_count)
    intrinsic_norm = _clamp_series(
        _enforce_descending(_normalise(intrinsic_raw)), multiplier_floor
    )
    market_norm = _clamp_series(
        _enforce_descending(_normalise(market_raw)), multiplier_floor
    )
    alpha = float(blend.get("intrinsic", 0.75))
    beta = 1.0 - alpha
    final_norm = _clamp_series(
        _enforce_descending(
            [alpha * i + beta * m for i, m in zip(intrinsic_norm, market_norm)]
        ),
        multiplier_floor,
    )
    buckets = [
        BucketMultipliers(
            label=lbl,
            intrinsic=intrinsic_norm[i],
            market=market_norm[i],
            final=final_norm[i],
            count=counts[i],
        )
        for i, lbl in enumerate(labels)
    ]
    return PositionMultipliers(position="", buckets=buckets)


def _enforce_descending(values: list[float]) -> list[float]:
    """Clamp a list so each element is <= the previous one.

    This prevents calibration noise from producing a bucket that is
    worth *more* than a higher-ranked bucket. We only enforce a soft
    non-increasing pass — equal values are allowed so small genuine
    plateaus (e.g. mid-tier depth) survive.
    """
    out: list[float] = []
    for i, v in enumerate(values):
        if i == 0:
            out.append(v)
            continue
        prev = out[-1]
        out.append(min(v, prev))
    return out


def _clamp_series(values: list[float], floor: float) -> list[float]:
    """Clamp every value into ``[floor, 1.0]`` while preserving non-increasing order.

    Without this, ``_normalise`` divides every VOR center by the top
    bucket's positive value — sub-replacement buckets (negative VOR)
    therefore emit *negative* multipliers. Applied to a positive
    ``rankDerivedValue`` in the live pipeline, a negative multiplier
    would flip the player's value sign. We instead floor at
    ``floor`` (default 5%) so sub-replacement buckets collapse to
    the minimum positive multiplier and cap at 1.0 so calibration
    noise can't inflate a deep bucket past the top bucket.
    """
    floor = max(0.0, float(floor))
    return [max(floor, min(1.0, float(v))) for v in values]


def build_multi_year_multipliers(
    per_season_per_position: dict[str, dict[int, list[BucketResult]]],
    *,
    year_weights: dict[int, float] | None = None,
    blend: dict[str, float] | None = None,
    multiplier_floor: float = 0.05,
) -> dict[str, PositionMultipliers]:
    """Produce intrinsic/market/final multiplier tables for DL/LB/DB.

    ``multiplier_floor`` flows through to
    :func:`compute_position_multipliers` so every emitted multiplier
    sits inside ``[floor, 1.0]``. See the per-position helper's
    docstring for the rationale (sub-replacement VOR would otherwise
    yield negative multipliers).
    """
    out: dict[str, PositionMultipliers] = {}
    for position, per_season in per_season_per_position.items():
        result = compute_position_multipliers(
            per_season,
            year_weights=year_weights,
            blend=blend,
            multiplier_floor=multiplier_floor,
        )
        result.position = position
        out[position] = result
    return out


def multipliers_to_dict(
    multipliers: dict[str, PositionMultipliers],
) -> dict[str, Any]:
    return {pos: pm.to_dict() for pos, pm in multipliers.items()}


def normalise_year_weights(
    weights: dict[int, float] | None,
    *,
    seasons: Iterable[int],
) -> dict[int, float]:
    """Restrict weights to the supplied seasons and renormalise.

    Used by the engine before calling into :func:`compute_position_multipliers`
    so a season that failed to resolve doesn't silently inflate the
    other years.

    If every supplied season has zero/missing weight (e.g. the user
    selected seasons outside the default weight keys like 2021 / 2020),
    fall back to **uniform** weights across the supplied seasons. An
    all-zero return here would collapse every bucket center to zero and
    produce a silent no-op calibration — uniform is the honest choice.
    """
    if not weights:
        weights = DEFAULT_YEAR_WEIGHTS
    filt = {int(s): float(weights.get(int(s), 0.0)) for s in seasons}
    if not filt:
        return {}
    total = sum(v for v in filt.values() if v > 0)
    if total <= 0:
        n = len(filt)
        uniform = 1.0 / n
        return {s: uniform for s in filt}
    return {s: w / total for s, w in filt.items()}
