"""Positional rank→FPG pools built from blended projections.

The replacement engine asks "what does the r-th best player at group g
score per game?".  In production the answer comes from the sorted
consensus projections; tests may use synthetic decay curves (the
reference fixture does).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from src.bdvm.league_config import BdvmLeagueConfig
from src.bdvm.projections import ConsensusProjection

PoolFn = Callable[[int], float]


@dataclass(frozen=True)
class PoolCurve:
    """Rank→FPG accessor over a sorted (descending) FPG list.

    Ranks beyond the observed pool return 0.0 — honestly "nothing left
    on the waiver wire", rather than extrapolating value that does not
    exist.  ``exhausted_at`` lets callers flag replacement ranks that
    fell off the measured pool.
    """

    fpg_sorted: tuple[float, ...]

    def __call__(self, rank: int) -> float:
        if rank <= 0:
            rank = 1
        if rank > len(self.fpg_sorted):
            return 0.0
        return self.fpg_sorted[rank - 1]

    @property
    def size(self) -> int:
        return len(self.fpg_sorted)

    def exhausted_at(self, rank: int) -> bool:
        return rank > len(self.fpg_sorted)


def build_group_pools(
    consensus: Iterable[ConsensusProjection],
    cfg: BdvmLeagueConfig,
) -> dict[str, PoolCurve]:
    """Group blended projections into per-lineup-group FPG curves."""
    by_group: dict[str, list[float]] = {}
    for c in consensus:
        try:
            group = cfg.group(c.position)
        except Exception:
            continue  # positions with no lineup group (e.g. K in K-less leagues)
        by_group.setdefault(group, []).append(c.mu_fpg)
    return {g: PoolCurve(tuple(sorted(vals, reverse=True))) for g, vals in by_group.items()}


def pools_from_callables(pool_map: Mapping[str, PoolFn]) -> Mapping[str, PoolFn]:
    """Pass-through helper so the engine accepts synthetic pools in tests."""
    return dict(pool_map)
