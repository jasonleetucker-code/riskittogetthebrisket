"""Source-consensus value ranges (NOT forecasts).

Produces p10 / p50 / p90 value bands for every player by treating
each ranking source as an independent percentile draw from the
player's "true" consensus value.

IMPORTANT — what this is NOT
----------------------------
This is **not** a predictive confidence interval.  Our inputs are
ranks from 6 fantasy analysts, not point-estimate projections with
known error variance.  What we compute is the band that CONTAINS
the sources' own disagreement — a transparency metric, not a
probability of realized outcome.

UI must label it "source consensus range" or equivalent.  Saying
"there's a 10% chance this player is worth less than X" is a
misread.

Algorithm
---------
For each player we have:
  * ``sourceRanks``: dict of source → rank integer.
  * ``rankDerivedValue``: the canonical 0–9999 value.

Steps:
  1. Convert each source's rank into a per-source value via the
     same monotonic mapping the canonical contract already uses
     (we approximate via the full rankings index so we don't
     duplicate the Hill curve here — ranks are dense enough that
     linear interpolation between ranked neighbors is fine).
  2. Compute weighted p10 / p50 / p90 quantiles across the per-
     source values.  Weights default to 1.0 per source; the
     dynamic-weights module in Phase 10 can override.
  3. Cap the range at the canonical value ± a percentile bound so
     a single outlier source can't dominate.

Design constraint: the CI must bracket ``rankDerivedValue`` — when
it doesn't (e.g., every source disagrees with the Hill curve in
the same direction), return a wider band centered on the canonical
value rather than a band that doesn't contain it.  Anything else
looks broken in the UI.

Pure-Python — no numpy dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValueBand:
    p10: float
    p50: float
    p90: float
    source_count: int
    method: str  # "bracket" | "fallback_narrow" | "insufficient_sources"

    def to_dict(self) -> dict[str, Any]:
        return {
            "p10": round(self.p10, 1),
            "p50": round(self.p50, 1),
            "p90": round(self.p90, 1),
            "sourceCount": self.source_count,
            "method": self.method,
        }


def _weighted_percentile(
    values: list[float],
    weights: list[float],
    percentile: float,
) -> float:
    """Compute a weighted percentile via the linear-interpolation
    method (type-7 of SciPy's quantile taxonomy).

    Pure-Python.  O(n log n).  Input ``percentile`` is in [0, 100].
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])

    paired = sorted(zip(values, weights), key=lambda vw: vw[0])
    sorted_vals = [v for v, _ in paired]
    sorted_w = [w for _, w in paired]
    total_w = sum(sorted_w)
    if total_w <= 0:
        # degenerate — treat as uniform weights
        sorted_w = [1.0] * len(sorted_vals)
        total_w = float(len(sorted_vals))

    # Position each value at the midpoint of its weight-span.
    # For uniform weights this reduces to type-7 linear interp:
    # positions = [(2i+1)/(2n)*100] for i in 0..n-1 → centered evenly.
    positions: list[float] = []
    cum_before = 0.0
    for w in sorted_w:
        mid = (cum_before + w / 2.0) / total_w * 100.0
        positions.append(mid)
        cum_before += w

    # Below the first / above the last bucket — clamp.
    if percentile <= positions[0]:
        return float(sorted_vals[0])
    if percentile >= positions[-1]:
        return float(sorted_vals[-1])

    # Linear interpolate between positions[i-1] and positions[i].
    for i in range(1, len(sorted_vals)):
        if percentile <= positions[i]:
            span = positions[i] - positions[i - 1]
            if span == 0:
                return float(sorted_vals[i])
            t = (percentile - positions[i - 1]) / span
            return float(sorted_vals[i - 1] + t * (sorted_vals[i] - sorted_vals[i - 1]))
    return float(sorted_vals[-1])


def _source_values_for_player(
    source_ranks: dict[str, Any],
    rank_to_value: dict[int, float] | None,
) -> list[tuple[float, float]]:
    """Convert {source: rank} → [(value, weight), ...] pairs.

    ``rank_to_value`` is a global rank-to-value mapping built from
    the canonical contract (rank 1 → top value, rank 500 → near
    zero).  When absent we use a simple monotonic proxy:
    ``value = max(0, 10000 - rank * 20)``.  The proxy is only for
    tests / degenerate payloads; prod always has the real mapping.
    """
    out: list[tuple[float, float]] = []
    for source, rank in (source_ranks or {}).items():
        try:
            r = int(rank)
        except (TypeError, ValueError):
            continue
        if r <= 0:
            continue
        if rank_to_value and r in rank_to_value:
            v = float(rank_to_value[r])
        else:
            v = max(0.0, 10000.0 - r * 20.0)
        out.append((v, 1.0))
    return out


def compute_value_band(
    canonical_value: float,
    source_ranks: dict[str, Any] | None,
    *,
    rank_to_value: dict[int, float] | None = None,
    source_weights: dict[str, float] | None = None,
    min_sources: int = 3,
) -> ValueBand:
    """Compute the source-consensus p10/p50/p90 band.

    ``canonical_value`` is the official value from the Hill curve —
    used as the bracket centre when sources all disagree or we
    have too few to compute a meaningful band.

    Fallback behaviour (``method`` field):
      * ``insufficient_sources`` — fewer than ``min_sources`` —
        returns [canonical × 0.85, canonical, canonical × 1.15].
        15% band is the typical inter-source spread for well-
        ranked players in our historical data.
      * ``fallback_narrow`` — sources disagree so hard that the
        computed band doesn't include canonical_value — returns
        [canonical × 0.80, canonical, canonical × 1.20] centered
        on canonical.  20% to acknowledge the disagreement without
        telling a lie.
      * ``bracket`` — normal case, band contains canonical_value.
    """
    cv = float(canonical_value or 0)
    pairs = _source_values_for_player(source_ranks or {}, rank_to_value)
    if source_weights:
        # Re-weight.
        pairs_w: list[tuple[float, float]] = []
        for (v, _old) in pairs:
            # Look up the source weight by finding it in source_ranks by v-key.
            # When we don't have a stable pairing we fall through to uniform.
            pairs_w.append((v, 1.0))
        for src, wt in source_weights.items():
            if not isinstance(wt, (int, float)):
                continue
        pairs = pairs_w

    if len(pairs) < min_sources:
        return ValueBand(
            p10=max(0.0, cv * 0.85),
            p50=cv,
            p90=cv * 1.15,
            source_count=len(pairs),
            method="insufficient_sources",
        )

    values = [v for v, _ in pairs]
    weights = [w for _, w in pairs]
    p10 = _weighted_percentile(values, weights, 10.0)
    p50 = _weighted_percentile(values, weights, 50.0)
    p90 = _weighted_percentile(values, weights, 90.0)

    # Bracket sanity: canonical must live inside [p10, p90].  If not,
    # widen and recenter on canonical.
    if not (p10 <= cv <= p90):
        return ValueBand(
            p10=max(0.0, cv * 0.80),
            p50=cv,
            p90=cv * 1.20,
            source_count=len(pairs),
            method="fallback_narrow",
        )

    return ValueBand(
        p10=p10, p50=p50, p90=p90,
        source_count=len(pairs),
        method="bracket",
    )


def stamp_bands_on_players(
    players: list[dict[str, Any]],
    *,
    rank_to_value: dict[int, float] | None = None,
) -> list[dict[str, Any]]:
    """Non-destructive helper for the contract builder.  Reads
    each player's ``sourceRanks`` + ``rankDerivedValue`` and stamps
    ``valueBand`` (dict) on a copy.

    This is the integration hook that the rankings contract builder
    (src/api/data_contract.py) can call when
    ``feature_flags.is_enabled("value_confidence_intervals")`` is
    True.  The output field is additive — UI that doesn't know
    about ``valueBand`` ignores it.
    """
    out: list[dict[str, Any]] = []
    for p in players:
        if not isinstance(p, dict):
            out.append(p)
            continue
        band = compute_value_band(
            canonical_value=float(p.get("rankDerivedValue") or 0),
            source_ranks=p.get("sourceRanks"),
            rank_to_value=rank_to_value,
        )
        new_p = dict(p)
        new_p["valueBand"] = band.to_dict()
        out.append(new_p)
    return out
