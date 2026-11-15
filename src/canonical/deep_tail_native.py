"""The native-value ladder of the ``idp-deep-tail-native-v1`` CHALLENGER.

Default OFF (flag ``idp_deep_tail_native_challenger``); evaluation only.
Preregistration (frozen, committed before this module existed):
``docs/valuation/evidence/idp-deep-tail-native-2026-10-18/PREREGISTRATION.md``.

The incumbent prices every rank vote on the Hill master its coordinate pool
routes to, with the B4 tail policy past the 500-rank reference.  The challenger
asks a narrower question about one band: for an IDP row's ``shared_market`` rank
vote at effective rank ``500 < r <= TAIL_SATURATION_RANK``, what value does the
IDP Trade Calculator itself put on the asset at rank ``r``?  This module answers
that from the calculator's own value-direct votes:

* one point per asset: ``(effective rank, raw / site_max x 9999)``;
* points sorted by rank, tied ranks averaged, then made non-increasing by
  pool-adjacent-violators (isotonic regression);
* the value at ``r`` is linear interpolation between the two nearest points;
* outside the covered range there is no answer (``None``), never a zero and
  never an extrapolated guess -- the caller keeps the incumbent value.

It changes no Hill constant, no reference N, no tail saturation rank and no
rank coordinate: it is a different rank-to-value map inside one band, and it is
monotone, so a source's own ordering of the players it ranks is preserved.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable
from dataclasses import dataclass

from src.canonical.player_valuation import PERCENTILE_REFERENCE_N
from src.canonical.tail_policy import TAIL_SATURATION_RANK

CHALLENGER_VERSION = "idp-deep-tail-native-v1"
#: Effective ranks strictly above this are past the Hill fit domain (p > 1 at
#: the fixed 500-rank reference) and are the band the challenger reprices.
DEEP_TAIL_MIN_RANK_EXCLUSIVE: int = int(PERCENTILE_REFERENCE_N)
#: Ranks above the tail saturation rank keep the incumbent's saturated value.
DEEP_TAIL_MAX_RANK_INCLUSIVE: int = int(TAIL_SATURATION_RANK or PERCENTILE_REFERENCE_N)
#: A ladder needs at least this many points deeper than the reference to price
#: anything in the band.
MIN_DEEP_POINTS: int = 2


@dataclass(frozen=True)
class NativeLadder:
    """A non-increasing rank -> value map, defined on ``[ranks[0], ranks[-1]]``."""

    ranks: tuple[float, ...]
    values: tuple[float, ...]

    @property
    def deep_points(self) -> int:
        return sum(1 for r in self.ranks if r > DEEP_TAIL_MIN_RANK_EXCLUSIVE)

    def covers(self, rank: float) -> bool:
        return bool(self.ranks) and self.ranks[0] <= rank <= self.ranks[-1]

    def value_at(self, rank: float) -> float | None:
        """Interpolated native value at ``rank``, or ``None`` outside the ladder."""
        if not self.covers(rank) or len(self.ranks) < 2:
            return None
        i = bisect.bisect_left(self.ranks, rank)
        if i < len(self.ranks) and self.ranks[i] == rank:
            return self.values[i]
        lo, hi = i - 1, i
        r0, r1 = self.ranks[lo], self.ranks[hi]
        v0, v1 = self.values[lo], self.values[hi]
        return v0 + (v1 - v0) * (rank - r0) / (r1 - r0)


def _pava_non_increasing(values: list[float], weights: list[float]) -> list[float]:
    """Weighted isotonic regression, non-increasing (pool adjacent violators)."""
    blocks: list[list[float]] = []  # [mean, weight, count]
    for v, w in zip(values, weights):
        blocks.append([v, w, 1.0])
        while len(blocks) >= 2 and blocks[-2][0] < blocks[-1][0]:
            m2, w2, c2 = blocks.pop()
            m1, w1, c1 = blocks.pop()
            wt = w1 + w2
            blocks.append([(m1 * w1 + m2 * w2) / wt, wt, c1 + c2])
    out: list[float] = []
    for mean, _w, count in blocks:
        out.extend([mean] * int(count))
    return out


def build_native_ladder(points: Iterable[tuple[float, float]]) -> NativeLadder:
    """The challenger's ladder from ``(effective rank, native value)`` points.

    Points with a non-finite or non-positive rank or value are ignored (they are
    not observations).  Tied ranks are averaged into one point of weight equal
    to their count before the isotonic fit.
    """
    by_rank: dict[float, list[float]] = {}
    for rank, value in points:
        try:
            r, v = float(rank), float(value)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(r) and math.isfinite(v)) or r <= 0 or v <= 0:
            continue
        by_rank.setdefault(r, []).append(v)
    ranks = sorted(by_rank)
    means = [sum(by_rank[r]) / len(by_rank[r]) for r in ranks]
    weights = [float(len(by_rank[r])) for r in ranks]
    fitted = _pava_non_increasing(means, weights)
    return NativeLadder(ranks=tuple(ranks), values=tuple(fitted))


def in_deep_band(rank: float) -> bool:
    """True when ``rank`` is in the band the challenger reprices."""
    return DEEP_TAIL_MIN_RANK_EXCLUSIVE < rank <= DEEP_TAIL_MAX_RANK_INCLUSIVE


def native_price(ladder: NativeLadder, rank: float) -> float | None:
    """The challenger's price for a deep-band rank vote, or ``None`` (keep incumbent)."""
    if not in_deep_band(rank) or ladder.deep_points < MIN_DEEP_POINTS:
        return None
    return ladder.value_at(rank)
