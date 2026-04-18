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


@dataclass
class FamilyScale:
    """Scalar that scales IDP values relative to offense.

    * ``intrinsic`` — what my-league scoring + my-league lineup imply.
    * ``market`` — same recipe under test-league scoring + lineup.
    * ``final`` — blended via the same intrinsic/market weights used
      for per-bucket multipliers.
    * ``sample_size`` — number of above-replacement players across both
      families used to compute the numbers, for transparency.

    The scale is applied multiplicatively on top of per-bucket
    multipliers in production:

        final_value = rankDerivedValue × family_scale × bucket_multiplier

    A value > 1.0 means my league values IDP as a class more than the
    test/market baseline does; < 1.0 means less.
    """

    intrinsic: float = 1.0
    market: float = 1.0
    final: float = 1.0
    intrinsic_my_ratio: float = 0.0
    intrinsic_test_ratio: float = 0.0
    sample_size: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.sample_size is None:
            self.sample_size = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "intrinsic": round(self.intrinsic, 4),
            "market": round(self.market, 4),
            "final": round(self.final, 4),
            "intrinsic_my_ratio": round(self.intrinsic_my_ratio, 4),
            "intrinsic_test_ratio": round(self.intrinsic_test_ratio, 4),
            "sample_size": dict(self.sample_size),
        }


def _sum_above_replacement(vor_values: list[float]) -> float:
    """Sum the positive portion of a VOR list — i.e. the total starter
    value produced by that cohort. Sub-replacement contributions are
    dropped so a bench of below-average players doesn't inflate the
    "class value" measure.
    """
    return sum(max(0.0, float(v)) for v in vor_values)


def compute_family_scale(
    *,
    idp_vor_my: list[float],
    idp_vor_test: list[float],
    offense_vor_my: list[float],
    offense_vor_test: list[float],
    blend: dict[str, float] | None = None,
    scale_min: float = 0.25,
    scale_max: float = 4.0,
) -> FamilyScale:
    """Compute the IDP-family scaling factor for one time period.

    Ratios:

        my_ratio   = sum(IDP VOR, my) / sum(offense VOR, my)
        test_ratio = sum(IDP VOR, test) / sum(offense VOR, test)

        family_scale_intrinsic = my_ratio / test_ratio

    Intuition: if my league's IDP starters produce 30% more
    fantasy-point VOR per unit of offense VOR than the test league's,
    then "IDP as a class" is worth 30% more in my league's economy
    and every IDP trade value should lift by roughly the same factor.

    The market channel is symmetric with my / test swapped — what would
    today's test-league scoring produce if applied to an IDP-heavy
    roster? (In practice it's always 1.0 by this definition, since
    it's computing test_ratio / test_ratio; we emit it for
    completeness and future use in a different blending scheme.)

    ``scale_min`` / ``scale_max`` cap the output so pathological
    replacement-level mismatches can't produce absurd scales.
    """
    blend = blend or DEFAULT_BLEND
    idp_my = _sum_above_replacement(idp_vor_my)
    idp_test = _sum_above_replacement(idp_vor_test)
    off_my = _sum_above_replacement(offense_vor_my)
    off_test = _sum_above_replacement(offense_vor_test)

    # Guard against division-by-zero — either side having zero
    # above-replacement VOR means we can't compute a meaningful ratio.
    if off_my <= 0 or off_test <= 0 or idp_test <= 0:
        return FamilyScale(
            intrinsic=1.0,
            market=1.0,
            final=1.0,
            intrinsic_my_ratio=0.0,
            intrinsic_test_ratio=0.0,
            sample_size={
                "idp_my": sum(1 for v in idp_vor_my if v > 0),
                "idp_test": sum(1 for v in idp_vor_test if v > 0),
                "offense_my": sum(1 for v in offense_vor_my if v > 0),
                "offense_test": sum(1 for v in offense_vor_test if v > 0),
            },
        )

    my_ratio = idp_my / off_my
    test_ratio = idp_test / off_test
    raw_intrinsic = my_ratio / test_ratio
    intrinsic = max(scale_min, min(scale_max, raw_intrinsic))
    # Market channel: by construction this comparison is test-vs-test,
    # which yields 1.0. We keep the field so the UI has the same
    # three-channel shape as per-bucket multipliers, and so a future
    # blending scheme can plug a different definition in.
    market = 1.0
    alpha = float(blend.get("intrinsic", 0.75))
    beta = 1.0 - alpha
    final = alpha * intrinsic + beta * market

    return FamilyScale(
        intrinsic=intrinsic,
        market=market,
        final=final,
        intrinsic_my_ratio=my_ratio,
        intrinsic_test_ratio=test_ratio,
        sample_size={
            "idp_my": sum(1 for v in idp_vor_my if v > 0),
            "idp_test": sum(1 for v in idp_vor_test if v > 0),
            "offense_my": sum(1 for v in offense_vor_my if v > 0),
            "offense_test": sum(1 for v in offense_vor_test if v > 0),
        },
    )


def combine_family_scales(
    per_season: dict[int, FamilyScale],
    year_weights: dict[int, float],
) -> FamilyScale:
    """Weighted multi-year aggregation of single-season family scales.

    Each channel (intrinsic / market / final) is a weighted mean
    across resolved seasons using the renormalised year weights.
    Seasons with zero weight or a no-op (1.0/1.0/1.0) scale are
    dropped from the mean so a bad season doesn't flatten the signal.
    """
    if not per_season:
        return FamilyScale()
    total_weight = 0.0
    weighted = {"intrinsic": 0.0, "market": 0.0, "final": 0.0}
    combined_sample: dict[str, int] = {}
    for year, scale in per_season.items():
        w = float(year_weights.get(int(year), 0.0))
        if w <= 0:
            continue
        total_weight += w
        weighted["intrinsic"] += w * scale.intrinsic
        weighted["market"] += w * scale.market
        weighted["final"] += w * scale.final
        for k, v in (scale.sample_size or {}).items():
            combined_sample[k] = combined_sample.get(k, 0) + int(v)
    if total_weight <= 0:
        return FamilyScale()
    return FamilyScale(
        intrinsic=weighted["intrinsic"] / total_weight,
        market=weighted["market"] / total_weight,
        final=weighted["final"] / total_weight,
        sample_size=combined_sample,
    )


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
