from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from src.data_models import CanonicalAssetValue, RawAssetRecord

CANONICAL_SCALE = 9999
KNOWN_UNIVERSES = {"offense_vet", "offense_rookie", "idp_vet", "idp_rookie", "picks"}
TRANSFORM_VERSION = "0.3.0"

# Sources with fewer records than this get their blend weight discounted
# proportionally.  Prevents partial scrapes from inflating player values.
MIN_EXPECTED_SOURCE_COVERAGE = 300


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

        # For rank-based sources, use the max rank value as the effective
        # depth (not just the record count).  A partial scrape may have
        # 169 records with ranks spanning 10–499; the depth should reflect
        # the full ranking universe so percentiles stay accurate.
        record_count = len(ranked)
        max_rank_value = max(
            (float(r.rank_raw) for r in ranked if r.rank_raw is not None),
            default=0.0,
        )
        depth = max(record_count, int(max_rank_value))

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
    asset_metadata: dict[str, dict] | None = None,
    expected_source_coverage: int = MIN_EXPECTED_SOURCE_COVERAGE,
) -> list[CanonicalAssetValue]:
    weighted: dict[str, float] = defaultdict(float)
    total_w: dict[str, float] = defaultdict(float)
    by_source_for_asset: dict[str, dict[str, int]] = defaultdict(dict)
    names = asset_names or {}
    meta_lookup = asset_metadata or {}

    for source_id, asset_scores in per_source_asset_scores.items():
        w = float(source_weights.get(source_id, 1.0))
        if w <= 0:
            continue

        # Coverage-based weight discount: if a source covers far fewer
        # players than expected, reduce its effective weight proportionally.
        # This prevents partial scrapes (e.g. 169 of 500 players) from
        # having outsized influence on the blend.  Only applies when the
        # expected coverage threshold is set and the source is meaningfully
        # below it (at least 50 records to avoid penalizing tiny test inputs).
        coverage = len(asset_scores)
        if expected_source_coverage > 0 and coverage >= 50 and coverage < expected_source_coverage:
            coverage_ratio = coverage / expected_source_coverage
            w *= coverage_ratio

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
                metadata=dict(meta_lookup.get(asset_key, {})),
            )
        )
    out.sort(key=lambda x: x.blended_value, reverse=True)
    return out


def _collect_asset_metadata(records: list[RawAssetRecord]) -> dict[str, dict]:
    """Collect position, team, and scoring-context metadata from raw records.

    When multiple sources provide position data for the same asset,
    prefer the first non-empty value found.

    Also tracks per-source TEP/SF inclusion flags so downstream code
    knows which adjustments are already baked into the blended value.
    """
    meta: dict[str, dict] = {}
    for rec in records:
        key = rec.asset_key
        if key not in meta:
            meta[key] = {"sources_with_tep": [], "sources_without_tep": [],
                         "sources_with_sf": [], "sources_without_sf": []}
        entry = meta[key]
        if not entry.get("position") and rec.position_normalized_guess:
            entry["position"] = rec.position_normalized_guess
        if not entry.get("team") and rec.team_normalized_guess:
            entry["team"] = rec.team_normalized_guess
        # Track TEP/SF per source for this asset
        rec_meta = rec.metadata_json or {}
        if rec_meta.get("includes_tep"):
            entry["sources_with_tep"].append(rec.source)
        else:
            entry["sources_without_tep"].append(rec.source)
        if rec_meta.get("includes_sf"):
            entry["sources_with_sf"].append(rec.source)
        else:
            entry["sources_without_sf"].append(rec.source)
    # Compute summary flags
    for entry in meta.values():
        has_tep = entry["sources_with_tep"]
        no_tep = entry["sources_without_tep"]
        entry["tep_status"] = (
            "all_included" if has_tep and not no_tep else
            "none_included" if no_tep and not has_tep else
            "mixed" if has_tep and no_tep else
            "unknown"
        )
        has_sf = entry["sources_with_sf"]
        no_sf = entry["sources_without_sf"]
        entry["sf_status"] = (
            "all_included" if has_sf and not no_sf else
            "none_included" if no_sf and not has_sf else
            "mixed" if has_sf and no_sf else
            "unknown"
        )
    return meta


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
        asset_meta = _collect_asset_metadata(rows)
        out[universe] = blend_source_values(
            per_source, source_weights=source_weights, universe=universe,
            asset_names=names, asset_metadata=asset_meta,
        )
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

