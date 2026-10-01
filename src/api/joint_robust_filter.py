"""Joint outlier + sparse-evidence challenger (#1555 Batch 2 Unit C, DISABLED by default).

Owner decision B (2026-10-01): outlier handling and sparse-source confidence form
one pipeline problem. The incumbent has two defects that interact:

* the per-player outlier filter (``data_contract._hampel_filter_per_player``) is
  value-only, so weak evidence can remove strong evidence (three stale
  observations at weight 0.03 remove a fresh one at 1.0); and
* the single-source rule multiplies the estimate by 0.30 whenever at most one
  family survives -- treating thin coverage as low value. A naive weighted
  filter would remove the three weak observations instead, leave one family, and
  hand the fresh 4600 straight to that rule: 1380.

This module is the challenger's robustness step. It is a pure function. The
pipeline uses it only when ``joint_outlier_sparse_challenger`` is on, and when it
is, the 0.30 rule is replaced by an explicit ``limitedEvidence`` state.

Rules, in order:

1. **Weights carry evidence and dependence.** The centre is the weighted median
   and the scale the weighted median absolute deviation, both over the
   observations' effective weights after family capping (callers pass capped
   weights), so correlated family members cannot outvote independent evidence.
   The weighted median is the PIPELINE's own (``data_contract.
   _weighted_median_sorted``: continuous in the weights, monotone in the
   values, the ordinary median under equal weights) -- never a second, step-
   function median (review of #1571: the lower step median snapped Kyle
   Hamilton's centre 2269 -> 3554 on a 0.001 weight change).
2. **The threshold** is the incumbent's: ``max(k · scale, min_threshold)``. Zero
   dispersion falls back to the floor -- unchanged behaviour.
3. **Disagreement never removes the dominant evidence.** An observation that
   ITSELF holds at least ``dominant_share`` of the row's evidence weight is never
   dropped for disagreeing (judged per observation, so a broken member of a
   heavy family is not shielded by its siblings).
4. **The filter never manufactures a singleton.** If the drops would leave one
   family where two or more were present, nothing is dropped and the row keeps
   its disagreement, reported as such.
5. **Order invariance.** Results depend on the multiset of observations, never
   on their order.

``min_n`` keeps the incumbent's guard: fewer than ``min_n`` observations is too
few to call any of them an outlier.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

CHALLENGER_VERSION = "joint-robust-v2"


@dataclass(frozen=True)
class FilterResult:
    kept: tuple[str, ...]
    dropped: tuple[str, ...]
    centre: float | None
    scale: float | None
    threshold: float | None
    reasons: dict = field(default_factory=dict)
    skipped: str | None = None


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float | None:
    """The pipeline's weighted median over positive weights; ``None`` with none.

    Delegates to ``data_contract._weighted_median_sorted`` (one owner).  Sorting
    by ``(value, weight)`` makes the result order-invariant.
    """
    from src.api.data_contract import _weighted_median_sorted  # noqa: PLC0415 — one owner

    pairs = sorted((float(v), float(w)) for v, w in zip(values, weights) if w > 0)
    total = sum(w for _v, w in pairs)
    if total <= 0:
        return None
    return _weighted_median_sorted(pairs, total)


def joint_robust_filter(
    observations: Sequence[tuple[str, float]],
    weights: Mapping[str, float],
    families: Mapping[str, str],
    *,
    k: float,
    min_n: int,
    min_threshold: float,
    dominant_share: float = 0.5,
) -> FilterResult:
    """Which observations survive, given evidence weights and family dependence."""
    keys = sorted(key for key, _value in observations)
    value_of = {key: float(value) for key, value in observations}
    if len(keys) < min_n:
        return FilterResult(tuple(keys), (), None, None, None, {}, "below_min_n")
    w = {key: max(0.0, float(weights.get(key, 0.0))) for key in keys}
    total = sum(w.values())
    if total <= 0:
        return FilterResult(tuple(keys), (), None, None, None, {}, "no_positive_weight")
    centre = weighted_median([value_of[key] for key in keys], [w[key] for key in keys])
    deviations = [abs(value_of[key] - centre) for key in keys]
    scale = weighted_median(deviations, [w[key] for key in keys])
    if scale is None:  # unreachable: total weight > 0 was checked above
        return FilterResult(tuple(keys), (), centre, None, None, {}, "no_positive_weight")
    threshold = max(k * scale, min_threshold)
    reasons: dict[str, str] = {}
    candidates = []
    for key in keys:
        if abs(value_of[key] - centre) <= threshold:
            continue
        if w[key] / total >= dominant_share:
            reasons[key] = "dominant_evidence_kept"
            continue
        candidates.append(key)
    present = {families.get(key, key) for key in keys}
    surviving = {families.get(key, key) for key in keys if key not in candidates}
    if candidates and len(present) >= 2 and len(surviving) < 2:
        for key in candidates:
            reasons[key] = "kept_to_avoid_single_family"
        candidates = []
    for key in candidates:
        reasons[key] = "outlier"
    kept = tuple(key for key in keys if key not in candidates)
    return FilterResult(kept, tuple(candidates), centre, scale, threshold, reasons)


def effective_family_count(family_weights: Mapping[str, float]) -> float | None:
    """Kish effective number of families, ``(Σw)² / Σw²``, over family weights.

    It assumes families are independent of each other (members within a family
    are already collapsed by the caller's capping). That assumption is disclosed
    with every published value; it is not a calibrated sample size.
    """
    values = [w for w in family_weights.values() if w > 0]
    if not values:
        return None
    return sum(values) ** 2 / sum(w * w for w in values)
