"""Spearman rank-correlation between source ranks and realized
end-of-season fantasy points.

Why Spearman (rank-rank) and not Pearson (value-value)?
-------------------------------------------------------
Our sources publish RANKS, not scaled values.  Pearson between a
rank and a points total would be dominated by the 400-rank-to-
1000-points scale mismatch.  Spearman just cares about order,
which is exactly what we want: "does source X's ordering match
who actually scored the most?"

Pure-Python, no SciPy.  O(n log n) from the sort.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceAccuracy:
    source: str
    n_players: int
    spearman_rho: float  # Spearman rank correlation
    top_50_hit_rate: float  # fraction of source's top-50 who ended up top-50 realized


def _rankdata(values: list[float]) -> list[float]:
    """Return ranks with ties averaged (standard 'fractional' rank)."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # 1-based average
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    """Return Spearman's rho in [-1, 1].  Returns 0 for degenerate
    inputs (empty / all-same)."""
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    ra = _rankdata(a)
    rb = _rankdata(b)
    n = len(ra)
    mean_a = sum(ra) / n
    mean_b = sum(rb) / n
    cov = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(n)) / n
    var_a = sum((x - mean_a) ** 2 for x in ra) / n
    var_b = sum((x - mean_b) ** 2 for x in rb) / n
    if var_a <= 0 or var_b <= 0:
        return 0.0
    return cov / math.sqrt(var_a * var_b)


def score_source(
    source: str,
    source_ranks: dict[str, int],  # player_id → rank
    realized_points: dict[str, float],  # player_id → total realized points
    *,
    top_k: int = 50,
) -> SourceAccuracy:
    """Compute Spearman + top-K hit rate for one source."""
    # Intersect players we have both for.
    common = set(source_ranks.keys()) & set(realized_points.keys())
    if len(common) < 2:
        return SourceAccuracy(
            source=source, n_players=len(common),
            spearman_rho=0.0, top_50_hit_rate=0.0,
        )
    # Spearman: lower rank = better.  Negate rank so higher-number
    # means better (aligning with points direction).
    ranks = [-float(source_ranks[p]) for p in common]
    points = [float(realized_points[p]) for p in common]
    rho = spearman(ranks, points)

    # Top-K hit rate: of the source's top-K, how many were also in
    # the realized top-K?
    source_topk = set(sorted(common, key=lambda p: source_ranks[p])[:top_k])
    realized_topk = set(sorted(common, key=lambda p: -realized_points[p])[:top_k])
    hit_rate = len(source_topk & realized_topk) / max(1, min(top_k, len(common)))
    return SourceAccuracy(
        source=source,
        n_players=len(common),
        spearman_rho=round(rho, 4),
        top_50_hit_rate=round(hit_rate, 4),
    )


def score_all_sources(
    source_ranks_by_source: dict[str, dict[str, int]],
    realized_points: dict[str, float],
) -> list[SourceAccuracy]:
    """Score every source in the input dict and return sorted by
    descending Spearman."""
    results = [
        score_source(src, ranks, realized_points)
        for src, ranks in source_ranks_by_source.items()
    ]
    results.sort(key=lambda a: -a.spearman_rho)
    return results
