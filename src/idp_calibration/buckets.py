"""Per-position rank-bucket aggregation.

Given :class:`~src.idp_calibration.vor.VorRow` data, bucket the
players into rank ranges (by ``rank_mine``), and compute the per
bucket ``(mean + median) / 2`` blended center under both scoring
systems.

If a bucket has fewer than ``min_bucket_size`` members it is merged
into the neighbouring (lower-rank) bucket and the merge is recorded
in the output so the UI can flag it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean, median
from typing import Any, Iterable

from .vor import VorRow

DEFAULT_BUCKETS: tuple[tuple[int, int], ...] = (
    (1, 6),
    (7, 12),
    (13, 24),
    (25, 36),
    (37, 60),
    (61, 100),
)


@dataclass
class BucketResult:
    label: str  # "1-6"
    lo: int
    hi: int
    count: int
    mean_vor_test: float
    median_vor_test: float
    center_vor_test: float
    mean_vor_mine: float
    median_vor_mine: float
    center_vor_mine: float
    ratio_mine_over_test: float | None
    merged_from: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "lo": self.lo,
            "hi": self.hi,
            "count": self.count,
            "mean_vor_test": self.mean_vor_test,
            "median_vor_test": self.median_vor_test,
            "center_vor_test": self.center_vor_test,
            "mean_vor_mine": self.mean_vor_mine,
            "median_vor_mine": self.median_vor_mine,
            "center_vor_mine": self.center_vor_mine,
            "ratio_mine_over_test": self.ratio_mine_over_test,
            "merged_from": list(self.merged_from),
        }


def _aggregate(values_test: list[float], values_mine: list[float]) -> tuple[float, float, float, float, float, float]:
    if not values_test or not values_mine:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mean_t = float(fmean(values_test))
    med_t = float(median(values_test))
    center_t = (mean_t + med_t) / 2.0
    mean_m = float(fmean(values_mine))
    med_m = float(median(values_mine))
    center_m = (mean_m + med_m) / 2.0
    return (mean_t, med_t, center_t, mean_m, med_m, center_m)


def bucketize(
    rows: Iterable[VorRow],
    position: str,
    *,
    buckets: Iterable[tuple[int, int]] = DEFAULT_BUCKETS,
    min_bucket_size: int = 3,
) -> list[BucketResult]:
    """Bucket rows by their *my-league* rank and compute centers.

    The ranking used for bucketing is ``rank_mine`` because the
    buckets represent "my-league DL1-DL6", "my-league DL7-DL12" etc.
    The centers aggregate VOR from both scoring systems so the caller
    can compute market vs intrinsic multipliers downstream.
    """
    position = position.upper()
    by_bucket: list[dict[str, Any]] = [
        {"label": f"{lo}-{hi}", "lo": lo, "hi": hi, "rows": [], "merged": []}
        for lo, hi in buckets
    ]
    for row in rows:
        if row.position.upper() != position:
            continue
        rank = int(row.rank_mine)
        for bucket in by_bucket:
            if bucket["lo"] <= rank <= bucket["hi"]:
                bucket["rows"].append(row)
                break

    # Merge small buckets into the nearest lower-rank neighbour. We
    # walk high->low so merges propagate from the tail upward.
    for idx in range(len(by_bucket) - 1, 0, -1):
        bucket = by_bucket[idx]
        if len(bucket["rows"]) < min_bucket_size:
            prev = by_bucket[idx - 1]
            prev["rows"].extend(bucket["rows"])
            prev["merged"].append(bucket["label"])
            bucket["rows"] = []
            bucket["merged_into_next"] = True

    results: list[BucketResult] = []
    for bucket in by_bucket:
        if not bucket["rows"] and not bucket.get("merged_into_next"):
            # Empty bucket that wasn't merged into a prior one — keep
            # it as a zero-count placeholder so the UI shows the gap.
            results.append(
                BucketResult(
                    label=bucket["label"],
                    lo=bucket["lo"],
                    hi=bucket["hi"],
                    count=0,
                    mean_vor_test=0.0,
                    median_vor_test=0.0,
                    center_vor_test=0.0,
                    mean_vor_mine=0.0,
                    median_vor_mine=0.0,
                    center_vor_mine=0.0,
                    ratio_mine_over_test=None,
                    merged_from=[],
                )
            )
            continue
        if bucket.get("merged_into_next"):
            continue
        vs_t = [r.vor_test for r in bucket["rows"]]
        vs_m = [r.vor_mine for r in bucket["rows"]]
        mean_t, med_t, center_t, mean_m, med_m, center_m = _aggregate(vs_t, vs_m)
        ratio = None
        if abs(center_t) > 1e-6:
            ratio = center_m / center_t
        results.append(
            BucketResult(
                label=bucket["label"],
                lo=bucket["lo"],
                hi=bucket["hi"],
                count=len(bucket["rows"]),
                mean_vor_test=round(mean_t, 4),
                median_vor_test=round(med_t, 4),
                center_vor_test=round(center_t, 4),
                mean_vor_mine=round(mean_m, 4),
                median_vor_mine=round(med_m, 4),
                center_vor_mine=round(center_m, 4),
                ratio_mine_over_test=round(ratio, 4) if ratio is not None else None,
                merged_from=list(bucket.get("merged") or []),
            )
        )
    return results


def buckets_to_dict(results: list[BucketResult]) -> list[dict[str, Any]]:
    return [r.to_dict() for r in results]
