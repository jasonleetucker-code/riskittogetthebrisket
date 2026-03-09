from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from src.data_models import CanonicalAssetValue, RawAssetRecord

CANONICAL_SCALE = 9999


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def percentile_from_rank(rank: float, depth: int) -> float:
    """
    Convert rank (1=best) to percentile in [0,1].
    Uses depth-aware denominator so different source depths remain comparable.
    """
    if depth <= 1:
        return 1.0
    r = clamp(rank, 1.0, float(depth))
    return (float(depth) - (r - 1.0)) / float(depth)


def percentile_to_canonical(percentile: float, exponent: float = 0.65) -> int:
    """
    Canonical curve:
      score = 9999 * percentile^exponent
    Lower exponent (<1) keeps top-tier separation while tapering lower tiers.
    """
    p = clamp(percentile, 0.0, 1.0)
    score = int(round(CANONICAL_SCALE * (p**exponent)))
    return int(clamp(score, 0, CANONICAL_SCALE))


def rank_to_canonical(rank: float, depth: int, exponent: float = 0.65) -> int:
    return percentile_to_canonical(percentile_from_rank(rank, depth), exponent=exponent)


def canonicalize_rank_records(
    records: list[RawAssetRecord],
    source_bucket: str,
    exponent: float = 0.65,
) -> dict[str, int]:
    ranked = [r for r in records if r.source_bucket == source_bucket and r.rank is not None]
    if not ranked:
        return {}
    depth = len(ranked)
    out: dict[str, int] = {}
    for r in ranked:
        out[r.asset_key] = rank_to_canonical(float(r.rank), depth=depth, exponent=exponent)
    return out


def blend_source_values(
    per_source_asset_scores: dict[str, dict[str, int]],
    source_weights: dict[str, float],
) -> list[CanonicalAssetValue]:
    """
    Blend canonical source values into one canonical value per asset.
    """
    weighted: dict[str, float] = defaultdict(float)
    total_w: dict[str, float] = defaultdict(float)
    display_names: dict[str, str] = {}
    by_source_for_asset: dict[str, dict[str, int]] = defaultdict(dict)

    for source_id, asset_scores in per_source_asset_scores.items():
        w = float(source_weights.get(source_id, 1.0))
        if w <= 0:
            continue
        for asset_key, score in asset_scores.items():
            weighted[asset_key] += float(score) * w
            total_w[asset_key] += w
            by_source_for_asset[asset_key][source_id] = int(score)

    out: list[CanonicalAssetValue] = []
    for asset_key in weighted.keys():
        denom = total_w.get(asset_key, 0.0)
        if denom <= 0:
            continue
        blended = int(round(weighted[asset_key] / denom))
        out.append(
            CanonicalAssetValue(
                asset_key=asset_key,
                display_name=display_names.get(asset_key, asset_key),
                source_values=by_source_for_asset.get(asset_key, {}),
                blended_value=int(clamp(blended, 0, CANONICAL_SCALE)),
                source_weights_used={k: float(source_weights.get(k, 1.0)) for k in by_source_for_asset.get(asset_key, {})},
                metadata={},
            )
        )
    out.sort(key=lambda x: x.blended_value, reverse=True)
    return out


def bucket_and_canonicalize(records: Iterable[RawAssetRecord]) -> dict[str, dict[str, int]]:
    """
    Convenience function used by scripts:
    - groups by source_id
    - computes canonical values from rank depth within that source
    """
    grouped: dict[str, list[RawAssetRecord]] = defaultdict(list)
    for rec in records:
        grouped[rec.source_id].append(rec)

    out: dict[str, dict[str, int]] = {}
    for source_id, recs in grouped.items():
        ranked = [r for r in recs if r.rank is not None]
        if not ranked:
            continue
        depth = len(ranked)
        source_scores: dict[str, int] = {}
        for r in ranked:
            source_scores[r.asset_key] = rank_to_canonical(float(r.rank), depth=depth)
        out[source_id] = source_scores
    return out

