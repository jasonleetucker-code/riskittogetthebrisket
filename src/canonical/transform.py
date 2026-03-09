from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from src.data_models import CanonicalAssetValue, RawAssetRecord

CANONICAL_SCALE = 9999
KNOWN_UNIVERSES = {"offense_vet", "offense_rookie", "idp_vet", "idp_rookie", "picks"}
TRANSFORM_VERSION = "0.2.0"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def percentile_from_rank(rank: float, depth: int) -> float:
    if depth <= 1:
        return 1.0
    r = clamp(rank, 1.0, float(depth))
    return (float(depth) - (r - 1.0)) / float(depth)


def percentile_to_canonical(percentile: float, exponent: float = 0.65) -> int:
    p = clamp(percentile, 0.0, 1.0)
    score = int(round(CANONICAL_SCALE * (p**exponent)))
    return int(clamp(score, 0, CANONICAL_SCALE))


def rank_to_canonical(rank: float, depth: int, exponent: float = 0.65) -> int:
    return percentile_to_canonical(percentile_from_rank(rank, depth), exponent=exponent)


def split_by_universe(records: Iterable[RawAssetRecord]) -> dict[str, list[RawAssetRecord]]:
    grouped: dict[str, list[RawAssetRecord]] = defaultdict(list)
    for rec in records:
        universe = (rec.universe or "").strip().lower()
        if not universe:
            universe = "unknown"
        grouped[universe].append(rec)
    return grouped


def _rank_records(records: list[RawAssetRecord]) -> list[RawAssetRecord]:
    """
    Deterministic ranking for source->universe set:
    1) rank_raw ascending when available
    2) value_raw descending fallback
    3) stable by name
    """
    with_rank = [r for r in records if r.rank_raw is not None]
    if with_rank:
        return sorted(
            with_rank,
            key=lambda r: (float(r.rank_raw or 10**9), (r.display_name or "").lower()),
        )

    with_value = [r for r in records if r.value_raw is not None]
    if with_value:
        return sorted(
            with_value,
            key=lambda r: (-float(r.value_raw or 0.0), (r.display_name or "").lower()),
        )
    return sorted(records, key=lambda r: (r.display_name or "").lower())


def per_source_scores_for_universe(records: list[RawAssetRecord], exponent: float = 0.65) -> dict[str, dict[str, int]]:
    by_source: dict[str, list[RawAssetRecord]] = defaultdict(list)
    for rec in records:
        by_source[rec.source].append(rec)

    out: dict[str, dict[str, int]] = {}
    for source, source_records in by_source.items():
        ranked = _rank_records(source_records)
        if not ranked:
            continue
        depth = len(ranked)
        scores: dict[str, int] = {}
        for idx, rec in enumerate(ranked, start=1):
            rank = float(rec.rank_raw) if rec.rank_raw is not None else float(idx)
            scores[rec.asset_key] = rank_to_canonical(rank=rank, depth=depth, exponent=exponent)
        out[source] = scores
    return out


def blend_source_values(
    per_source_asset_scores: dict[str, dict[str, int]],
    source_weights: dict[str, float],
    universe: str,
    asset_names: dict[str, str] | None = None,
) -> list[CanonicalAssetValue]:
    weighted: dict[str, float] = defaultdict(float)
    total_w: dict[str, float] = defaultdict(float)
    by_source_for_asset: dict[str, dict[str, int]] = defaultdict(dict)
    names = asset_names or {}

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
                display_name=names.get(asset_key, asset_key),
                universe=universe,
                source_values=by_source_for_asset.get(asset_key, {}),
                blended_value=int(clamp(blended, 0, CANONICAL_SCALE)),
                source_weights_used={
                    k: float(source_weights.get(k, 1.0))
                    for k in by_source_for_asset.get(asset_key, {})
                },
                metadata={},
            )
        )
    out.sort(key=lambda x: x.blended_value, reverse=True)
    return out


def build_canonical_by_universe(
    records: list[RawAssetRecord],
    source_weights: dict[str, float],
    exponent: float = 0.65,
) -> dict[str, list[CanonicalAssetValue]]:
    grouped = split_by_universe(records)
    out: dict[str, list[CanonicalAssetValue]] = {}
    for universe, rows in grouped.items():
        per_source = per_source_scores_for_universe(rows, exponent=exponent)
        names = {r.asset_key: r.display_name for r in rows}
        out[universe] = blend_source_values(per_source, source_weights=source_weights, universe=universe, asset_names=names)
    return out


def flatten_canonical(canonical_by_universe: dict[str, list[CanonicalAssetValue]]) -> list[CanonicalAssetValue]:
    all_assets: list[CanonicalAssetValue] = []
    for rows in canonical_by_universe.values():
        all_assets.extend(rows)
    all_assets.sort(key=lambda x: x.blended_value, reverse=True)
    return all_assets


def detect_suspicious_value_jumps(
    current_assets: list[CanonicalAssetValue],
    previous_assets: list[CanonicalAssetValue],
    jump_threshold: int = 1800,
) -> list[dict]:
    prev_map = {a.asset_key: a.blended_value for a in previous_assets}
    warnings: list[dict] = []
    for asset in current_assets:
        if asset.asset_key not in prev_map:
            continue
        prev = int(prev_map[asset.asset_key])
        cur = int(asset.blended_value)
        delta = cur - prev
        if abs(delta) >= jump_threshold:
            warnings.append(
                {
                    "asset_key": asset.asset_key,
                    "display_name": asset.display_name,
                    "universe": asset.universe,
                    "previous_value": prev,
                    "current_value": cur,
                    "delta": delta,
                }
            )
    return warnings


def rookie_universe_warnings(records: list[RawAssetRecord]) -> list[dict]:
    """
    Heuristic warnings for rookie/full-pool misclassification.
    """
    by_source_universe: dict[tuple[str, str], list[RawAssetRecord]] = defaultdict(list)
    for rec in records:
        by_source_universe[(rec.source, rec.universe)].append(rec)

    warnings: list[dict] = []
    for (source, universe), rows in by_source_universe.items():
        count = len(rows)
        u = universe.lower()
        if "rookie" in u and count > 250:
            warnings.append(
                {
                    "source": source,
                    "universe": universe,
                    "warning": "rookie_universe_count_unusually_large",
                    "record_count": count,
                }
            )
        if "rookie" not in u and count < 60:
            warnings.append(
                {
                    "source": source,
                    "universe": universe,
                    "warning": "non_rookie_universe_count_unusually_small",
                    "record_count": count,
                }
            )
    return warnings

