"""Seeded date-block bootstrap.

Origins on adjacent days share most of their target window, so cells are not
independent; resampling individual days would understate uncertainty and let one
hot interval look like many independent confirmations.  Origins are grouped into
consecutive calendar blocks of ``block_days`` and BLOCKS are resampled with
replacement.  Statistics are passed as per-date additive sufficient statistics,
so a replicate is a weighted sum -- exact and fast.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np


def block_ids(dates: Sequence[date], block_days: int) -> np.ndarray:
    """Block index per origin date: ``(date - first) // block_days``."""
    if block_days < 1:
        raise ValueError("block_days must be >= 1")
    if not dates:
        return np.zeros(0, dtype=np.int64)
    first = min(dates)
    return np.array([(d - first).days // block_days for d in dates], dtype=np.int64)


def replicate_weights(blocks: np.ndarray, n_boot: int, seed: int) -> np.ndarray:
    """(n_boot, n_dates) multiplicities: each replicate draws len(unique blocks)
    blocks with replacement; a date's weight is how often its block was drawn."""
    uniq, inv = np.unique(blocks, return_inverse=True)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    counts = np.zeros((n_boot, len(uniq)))
    for b in range(n_boot):
        counts[b] = np.bincount(draws[b], minlength=len(uniq))
    return counts[:, inv]


@dataclass(frozen=True)
class Estimate:
    point: float | None
    se: float | None
    lo: float | None  # 5th percentile
    hi: float | None  # 95th percentile
    n_blocks: int
    n_boot: int

    def as_dict(self, nd: int = 4) -> dict:
        def r(x):
            return None if x is None else round(float(x), nd)

        return {
            "point": r(self.point),
            "se": r(self.se),
            "ci90": [r(self.lo), r(self.hi)],
            "blocks": self.n_blocks,
            "boot": self.n_boot,
        }


def bootstrap(
    per_date: np.ndarray,
    stat: Callable[[np.ndarray], float | None],
    blocks: np.ndarray,
    *,
    n_boot: int,
    seed: int,
) -> Estimate:
    """``per_date`` is (n_dates, ...) additive statistics; ``stat(summed)`` maps the
    (weighted) sum over dates to the estimate.  Replicates that are undefined are
    dropped and counted; nothing is coerced to zero."""
    n_blocks = int(len(np.unique(blocks))) if len(blocks) else 0
    if n_blocks == 0:
        return Estimate(None, None, None, None, 0, 0)
    point = stat(per_date.sum(axis=0))
    w = replicate_weights(blocks, n_boot, seed)
    reps = []
    for b in range(n_boot):
        v = stat(np.tensordot(w[b], per_date, axes=(0, 0)))
        if v is not None and np.isfinite(v):
            reps.append(v)
    if point is None or len(reps) < max(10, n_boot // 2):
        return Estimate(point, None, None, None, n_blocks, len(reps))
    arr = np.array(reps)
    return Estimate(
        float(point),
        float(arr.std(ddof=1)),
        float(np.percentile(arr, 5)),
        float(np.percentile(arr, 95)),
        n_blocks,
        len(reps),
    )
