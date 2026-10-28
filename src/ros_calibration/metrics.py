"""Evaluation metrics for the ROS scale calibration study (preregistration §4).

Pure functions over plain records.  Bootstraps resample CLUSTERS (players or
team-weeks) with replacement and report a 95% percentile interval; the same
resample is applied to both arms of a paired difference.
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable, Mapping, Sequence

import numpy as np


def mae(pred: Sequence[float], obs: Sequence[float]) -> float | None:
    if not pred:
        return None
    return sum(abs(p - y) for p, y in zip(pred, obs)) / len(pred)


def rmse(pred: Sequence[float], obs: Sequence[float]) -> float | None:
    if not pred:
        return None
    return math.sqrt(sum((p - y) ** 2 for p, y in zip(pred, obs)) / len(pred))


def ratio(obs: Sequence[float], pred: Sequence[float]) -> float | None:
    """``Σ obs / Σ pred``; ``None`` when the denominator is not positive."""
    den = sum(pred)
    if not den > 0:
        return None
    return sum(obs) / den


def calibration_slope(pred: Sequence[float], obs: Sequence[float]) -> float | None:
    """OLS slope of obs on pred (1.0 = calibrated spread)."""
    n = len(pred)
    if n < 2:
        return None
    mp = sum(pred) / n
    mo = sum(obs) / n
    sxx = sum((p - mp) ** 2 for p in pred)
    if sxx <= 0:
        return None
    return sum((p - mp) * (o - mo) for p, o in zip(pred, obs)) / sxx


def _rankdata(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman ρ with average ranks for ties; ``None`` below 3 points or no spread."""
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    rx = _rankdata(xs)
    ry = _rankdata(ys)
    n = len(rx)
    mx = sum(rx) / n
    my = sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def percentile_ci(stats: Sequence[float]) -> list[float | None]:
    vals = sorted(s for s in stats if s is not None and math.isfinite(s))
    if not vals:
        return [None, None]
    return [float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))]


def cluster_bootstrap(
    records: Sequence[Any],
    cluster_of: Callable[[Any], str],
    stat: Callable[[list[Any]], float | None],
    *,
    b: int,
    seed: int,
) -> dict[str, Any]:
    """Point estimate + 95% percentile CI of ``stat`` resampling clusters."""
    point = stat(list(records))
    groups: dict[str, list[Any]] = {}
    for r in records:
        groups.setdefault(cluster_of(r), []).append(r)
    keys = sorted(groups)
    rng = random.Random(seed)
    stats: list[float | None] = []
    for _ in range(b):
        sample: list[Any] = []
        for _j in range(len(keys)):
            sample.extend(groups[keys[rng.randrange(len(keys))]])
        stats.append(stat(sample))
    return {
        "n": len(records),
        "clusters": len(keys),
        "estimate": point,
        "ci95": percentile_ci([s for s in stats if s is not None]),
    }


def cross_group_concordance_matrices(
    off: Sequence[tuple[float, float]],
    idp: Sequence[tuple[float, float]],
) -> tuple[np.ndarray, np.ndarray]:
    """(concordant, valid) indicator matrices for every OFF x IDP pair.

    Each input item is ``(mu, y)``.  A pair is VALID when the realized points
    differ; it is CONCORDANT when the predicted order matches the realized
    order.  A predicted tie on a valid pair counts half.
    """
    mo = np.array([m for m, _ in off], dtype=float)[:, None]
    yo = np.array([y for _, y in off], dtype=float)[:, None]
    mi = np.array([m for m, _ in idp], dtype=float)[None, :]
    yi = np.array([y for _, y in idp], dtype=float)[None, :]
    dy = np.sign(yo - yi)
    dm = np.sign(mo - mi)
    valid = (dy != 0).astype(float)
    conc = np.where(dm == 0, 0.5, (dm == dy).astype(float)) * valid
    return conc, valid


def concordance_from_weeks(
    weeks: Mapping[Any, tuple[np.ndarray, np.ndarray]],
    weights: Mapping[Any, tuple[np.ndarray, np.ndarray]] | None = None,
) -> float | None:
    num = 0.0
    den = 0.0
    for wk, (conc, valid) in weeks.items():
        if weights is None:
            num += float(conc.sum())
            den += float(valid.sum())
        else:
            wo, wi = weights[wk]
            num += float(wo @ conc @ wi)
            den += float(wo @ valid @ wi)
    return num / den if den > 0 else None


def all_play_concordance(pred: Sequence[float], obs: Sequence[float]) -> tuple[float, int]:
    """(concordant share, valid pairs) over every unordered pair of teams."""
    num = 0.0
    den = 0
    n = len(pred)
    for i in range(n):
        for j in range(i + 1, n):
            dy = obs[i] - obs[j]
            if dy == 0:
                continue
            den += 1
            dp = pred[i] - pred[j]
            if dp == 0:
                num += 0.5
            elif (dp > 0) == (dy > 0):
                num += 1.0
    return (num / den if den else float("nan")), den


__all__ = [
    "all_play_concordance",
    "calibration_slope",
    "cluster_bootstrap",
    "concordance_from_weeks",
    "cross_group_concordance_matrices",
    "mae",
    "percentile_ci",
    "ratio",
    "rmse",
    "spearman",
]
