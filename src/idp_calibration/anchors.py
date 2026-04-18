"""Anchor curves and monotonic smoothing.

Given per-bucket multipliers we produce three curves per position —
intrinsic, market, final — sampled at the default anchor ranks
``[1, 3, 6, 12, 24, 36, 48, 72, 100]``.

The smoothing pass is an in-place pool-adjacent-violators (PAV) style
sweep that enforces non-increasing anchors along with a floor so we
never emit negative or zero-crossing values. No sklearn dep —
implemented with plain lists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .translation import BucketMultipliers, PositionMultipliers

DEFAULT_ANCHOR_RANKS: tuple[int, ...] = (1, 3, 6, 12, 24, 36, 48, 72, 100)
CURVE_KINDS: tuple[str, ...] = ("intrinsic", "market", "final")


@dataclass
class AnchorPoint:
    rank: int
    value: float

    def to_dict(self) -> dict[str, Any]:
        return {"rank": int(self.rank), "value": round(float(self.value), 4)}


def _bucket_value_at_rank(buckets: list[BucketMultipliers], rank: int, kind: str) -> float:
    """Look up the multiplier for ``rank`` in a bucket list.

    Buckets are labelled ``"lo-hi"``. If ``rank`` falls inside one we
    return its multiplier. If ``rank`` is past the last bucket we
    return the last bucket's value. Missing/empty bucket lists return
    ``0.0``.
    """
    if not buckets:
        return 0.0
    for b in buckets:
        lo, _, hi = b.label.partition("-")
        try:
            lo_i = int(lo)
            hi_i = int(hi)
        except ValueError:
            continue
        if lo_i <= rank <= hi_i:
            return float(getattr(b, kind))
    # Fallback: past the last labelled bucket
    return float(getattr(buckets[-1], kind))


def _monotone_non_increasing(values: list[float], floor: float = 0.0) -> list[float]:
    if not values:
        return []
    out = [max(float(values[0]), floor)]
    for v in values[1:]:
        out.append(max(min(float(v), out[-1]), floor))
    return out


def build_anchor_curve(
    multipliers: PositionMultipliers,
    *,
    anchor_ranks: Iterable[int] = DEFAULT_ANCHOR_RANKS,
    floor: float = 0.05,
) -> dict[str, list[AnchorPoint]]:
    """Return {kind: [AnchorPoint...]} for one position."""
    out: dict[str, list[AnchorPoint]] = {}
    for kind in CURVE_KINDS:
        raw = [
            _bucket_value_at_rank(multipliers.buckets, r, kind)
            for r in anchor_ranks
        ]
        smoothed = _monotone_non_increasing(raw, floor=floor)
        out[kind] = [AnchorPoint(rank=r, value=v) for r, v in zip(anchor_ranks, smoothed)]
    return out


def build_all_anchors(
    multipliers_by_position: dict[str, PositionMultipliers],
    *,
    anchor_ranks: Iterable[int] = DEFAULT_ANCHOR_RANKS,
    floor: float = 0.05,
) -> dict[str, dict[str, list[AnchorPoint]]]:
    return {
        pos: build_anchor_curve(pm, anchor_ranks=anchor_ranks, floor=floor)
        for pos, pm in multipliers_by_position.items()
    }


def anchors_to_dict(
    anchors: dict[str, dict[str, list[AnchorPoint]]],
) -> dict[str, Any]:
    """Flatten for JSON: {kind: {position: [{rank, value}, ...]}}."""
    flat: dict[str, dict[str, list[dict[str, Any]]]] = {k: {} for k in CURVE_KINDS}
    for position, by_kind in anchors.items():
        for kind, points in by_kind.items():
            flat.setdefault(kind, {})[position] = [p.to_dict() for p in points]
    return flat
