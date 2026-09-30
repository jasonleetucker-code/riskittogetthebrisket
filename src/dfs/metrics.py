"""Forecast-evaluation metrics shared by every DFS scorecard.

One owner for "how wrong was this forecast": ownership, projections, field and
contest models all score through here, so two scorecards can never disagree
about what MAE means.  Everything reports its sample size; a small sample is
flagged rather than dressed up (``SMALL_SAMPLE`` below), and uncertainty comes
from a deterministic seeded bootstrap so a rerun reproduces it exactly.
"""

from __future__ import annotations

import math
import random
from typing import Any

SMALL_SAMPLE = 30  # below this, metrics are shown with an explicit small-sample flag


def _ranks(xs: list[float]) -> list[float]:
    """Average ranks (ties share the mean rank)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        mean_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = mean_rank
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    """Rank correlation; None when undefined (fewer than 3 pairs or no variation)."""
    if len(a) != len(b) or len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return round(cov / math.sqrt(va * vb), 4)


def bootstrap_ci(
    errors: list[float],
    stat=lambda e: sum(abs(x) for x in e) / len(e),
    *,
    n: int = 1000,
    seed: int = 7,
) -> tuple[float, float] | None:
    """95% percentile bootstrap interval of ``stat`` over the error sample (seeded)."""
    if len(errors) < 5:
        return None
    rnd = random.Random(seed)
    vals = sorted(stat([errors[rnd.randrange(len(errors))] for _ in errors]) for _ in range(n))
    return round(vals[int(0.025 * n)], 4), round(vals[int(0.975 * n) - 1], 4)


def point_forecast(pairs: list[tuple[float, float]]) -> dict[str, Any] | None:
    """(forecast, actual) pairs → MAE / RMSE / bias (+ = too high) / rank correlation / CI."""
    if not pairs:
        return None
    errs = [f - a for f, a in pairs]
    n = len(errs)
    return {
        "n": n,
        "smallSample": n < SMALL_SAMPLE,
        "mae": round(sum(abs(e) for e in errs) / n, 4),
        "rmse": round(math.sqrt(sum(e * e for e in errs) / n), 4),
        "bias": round(sum(errs) / n, 4),
        "spearman": spearman([f for f, _ in pairs], [a for _, a in pairs]),
        "maeCi95": bootstrap_ci(errs),
    }


def calibration_buckets(
    pairs: list[tuple[float, float]], edges: tuple[float, ...] = (0, 5, 10, 20, 30, 50, 101)
) -> list[dict[str, Any]]:
    """Mean forecast vs mean actual per forecast bucket — each bucket with its own n."""
    out = []
    for lo, hi in zip(edges, edges[1:]):
        inside = [(f, a) for f, a in pairs if lo <= f < hi]
        if inside:
            out.append(
                {
                    "bucket": f"{lo}–{min(hi, 100)}",
                    "n": len(inside),
                    "meanForecast": round(sum(f for f, _ in inside) / len(inside), 3),
                    "meanActual": round(sum(a for _, a in inside) / len(inside), 3),
                }
            )
    return out


def top_k_overlap(
    forecast: dict[str, float], actual: dict[str, float], k: int = 10
) -> dict[str, Any] | None:
    """Share of the actual top-k that the forecast also put in its top-k (common keys only)."""
    keys = forecast.keys() & actual.keys()
    if len(keys) < k:
        return None
    top_f = set(sorted(keys, key=lambda x: -forecast[x])[:k])
    top_a = set(sorted(keys, key=lambda x: -actual[x])[:k])
    return {"k": k, "overlap": len(top_f & top_a), "share": round(len(top_f & top_a) / k, 4)}


def ownership_scorecard(
    forecast: dict[str, float], actual: dict[str, float]
) -> dict[str, Any] | None:
    """Everything the ownership scorecard shows, over players present in BOTH (missing is not 0)."""
    keys = sorted(forecast.keys() & actual.keys())
    if not keys:
        return None
    pairs = [(forecast[k], actual[k]) for k in keys]
    return {
        **(point_forecast(pairs) or {}),
        "buckets": calibration_buckets(pairs),
        "top10": top_k_overlap(forecast, actual, 10),
        "forecastOnly": len(forecast.keys() - actual.keys()),
        "actualOnly": len(actual.keys() - forecast.keys()),
    }
