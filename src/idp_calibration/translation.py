"""Cross-league relativity multiplier math (schema v2).

Converts per-season bucket centers into per-bucket multipliers that
express **how my league values this IDP bucket relative to a test
league, anchored to each league's own offense baseline**.

Per-bucket formula::

    my_norm[i]   = center_vor_mine[i]  / offense_anchor_mine
    test_norm[i] = center_vor_test[i]  / offense_anchor_test
    final[i]     = my_norm[i] / test_norm[i]     # the applied multiplier

Where ``offense_anchor_*`` is the mean VOR of the top-24 RB+WR under
each league's scoring (see ``vor.compute_offense_anchor_vor``).

Fields on the emitted :class:`BucketMultipliers` record:

* ``intrinsic`` — ``my_norm[i]``. How much VOR my-league scoring
  produces for this bucket expressed as a multiple of one average top-24
  flex starter's VOR. Display-only in the final-mode production path.
* ``market`` — ``test_norm[i]``. Same measure for the test league.
* ``final`` — ``intrinsic / market``. The **relativity ratio** applied
  as a multiplier to market-derived ``rankDerivedValue`` in the live
  pipeline. 1.0 = identical weighting; > 1.0 lifts the bucket; < 1.0
  cuts it.

Multi-year weighting folds per-season buckets (and per-season offense
anchors) into a single table by applying recency weights and skipping
missing seasons.
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

# Schema version tag written into the emitted multipliers/anchors
# artifact. ``production.py`` refuses to apply anything older than
# :data:`CALIBRATION_SCHEMA_VERSION` because the v1 ``final`` field
# encoded a different quantity (top-bucket-normalised VOR decay) and
# would be misinterpreted as a relativity ratio.
CALIBRATION_SCHEMA_VERSION: int = 2

# Cross-league relativity bounds. The engineering floor/ceiling here
# bounds the ``final`` multiplier only — the display-side ``intrinsic``
# and ``market`` fields are emitted without a ceiling because they're
# in offense-anchor units and the reader does not apply them as
# multipliers when the active mode is ``blended``/``final``.
RELATIVITY_MIN: float = 0.25
RELATIVITY_MAX: float = 4.0

# Guard against pathological zero/near-zero offense anchors. A
# missing-data anchor collapses the ratio to garbage; we fall back to
# an identity multiplier (``1.0``) whenever either side can't produce
# a real number.
_OFFENSE_ANCHOR_EPSILON: float = 1.0  # VOR points; anything below this is noise


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


def _clamp_relativity(value: float) -> float:
    """Clamp a relativity ratio into ``[RELATIVITY_MIN, RELATIVITY_MAX]``.

    Unlike the old :func:`_clamp_series`, we do not force the output to
    sit below 1.0 — a relativity > 1.0 is the signal that "my league
    values this bucket more than the test league." The floor keeps a
    pathological near-zero test anchor from producing an absurd
    deflation; the ceiling keeps a pathological near-zero my-league
    anchor from producing an absurd inflation. Identity passes through
    unchanged.
    """
    if not isinstance(value, (int, float)):
        return 1.0
    v = float(value)
    if v != v:  # NaN
        return 1.0
    return max(RELATIVITY_MIN, min(RELATIVITY_MAX, v))


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
    offense_anchor_mine: float = 0.0,
    offense_anchor_test: float = 0.0,
    multiplier_floor: float = 0.05,  # kept for signature compat; no longer used
) -> PositionMultipliers:
    """Combine per-season bucket tables into cross-league relativity multipliers.

    For each bucket the function computes::

        my_norm   = weighted_center_vor_mine / offense_anchor_mine
        test_norm = weighted_center_vor_test / offense_anchor_test
        final     = my_norm / test_norm          (clamped to [0.25, 4.0])

    ``offense_anchor_mine`` / ``offense_anchor_test`` are the mean VOR
    of the top-24 RB+WR under each league's scoring (see
    :func:`src.idp_calibration.vor.compute_offense_anchor_vor`),
    weighted-aggregated across seasons upstream. They put ``intrinsic``
    and ``market`` into a common "offense flex starter" unit so the
    ratio represents genuine cross-league relativity rather than raw
    VOR point counts (which would just reflect scoring intensity).

    Fallback semantics:

    * Either anchor missing / ≤ ``_OFFENSE_ANCHOR_EPSILON`` → every
      bucket emits the identity multiplier (1.0) with raw VOR still
      exposed on ``intrinsic`` / ``market`` for audit.
    * A single bucket with ``center_vor_mine`` ≤ 0 or
      ``center_vor_test`` ≤ 0 → emit identity (1.0) for that bucket's
      ``final`` — we don't have a meaningful ratio when either side is
      at/below replacement.

    ``multiplier_floor`` is accepted for call-site compat but no longer
    used; the relativity floor/ceiling are set by
    :data:`RELATIVITY_MIN` / :data:`RELATIVITY_MAX`.
    """
    del multiplier_floor  # schema v1 vestige; relativity has its own bounds
    year_weights = year_weights or DEFAULT_YEAR_WEIGHTS
    blend = blend or DEFAULT_BLEND  # kept for API compat; unused in v2 math
    del blend
    labels = _bucket_labels(per_season)

    anchors_ok = (
        offense_anchor_mine > _OFFENSE_ANCHOR_EPSILON
        and offense_anchor_test > _OFFENSE_ANCHOR_EPSILON
    )

    buckets: list[BucketMultipliers] = []
    for label in labels:
        mine_centers = _collect_year_centers(per_season, label, "center_vor_mine")
        test_centers = _collect_year_centers(per_season, label, "center_vor_test")
        mine_val, _ = _weighted_center(mine_centers, year_weights)
        test_val, _ = _weighted_center(test_centers, year_weights)
        total_count = 0
        for season_buckets in per_season.values():
            for b in season_buckets:
                if b.label == label:
                    total_count += int(b.count)
                    break

        if anchors_ok:
            my_norm = mine_val / offense_anchor_mine
            test_norm = test_val / offense_anchor_test
        else:
            my_norm = 0.0
            test_norm = 0.0

        # Relativity ratio — the applied multiplier.
        if anchors_ok and mine_val > 0 and test_val > 0:
            final = _clamp_relativity(my_norm / test_norm)
        else:
            # No meaningful ratio: identity passthrough so the live
            # pipeline leaves the market-derived value alone rather
            # than guessing.
            final = 1.0

        buckets.append(
            BucketMultipliers(
                label=label,
                intrinsic=my_norm,
                market=test_norm,
                final=final,
                count=total_count,
            )
        )

    return PositionMultipliers(position="", buckets=buckets)


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
    offense_anchor_mine: float = 0.0,
    offense_anchor_test: float = 0.0,
    multiplier_floor: float = 0.05,
) -> dict[str, PositionMultipliers]:
    """Produce per-bucket relativity multiplier tables for DL/LB/DB.

    ``offense_anchor_mine`` / ``offense_anchor_test`` are the aggregate
    (year-weighted) top-24 RB+WR mean VOR on each side; they are
    threaded into :func:`compute_position_multipliers` so every bucket
    is normalised into the same offense-anchored unit before the ratio.
    Missing anchors collapse every bucket to identity (see that helper's
    docstring).
    """
    out: dict[str, PositionMultipliers] = {}
    for position, per_season in per_season_per_position.items():
        result = compute_position_multipliers(
            per_season,
            year_weights=year_weights,
            blend=blend,
            offense_anchor_mine=offense_anchor_mine,
            offense_anchor_test=offense_anchor_test,
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
