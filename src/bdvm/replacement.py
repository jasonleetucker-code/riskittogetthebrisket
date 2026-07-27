"""Dynamic, flex-aware replacement levels (BDVM module 3).

Replacement level does ALL the positional-scarcity work in BDVM — no
Superflex/TEP/EDGE multipliers exist anywhere in the model.  Format
sensitivity flows from exact scoring, lineup slots, flex eligibility,
league size, and waiver depth (master prompt §3.6).

    R_g = FPG at rank [league-wide flex-allocated startable slots at g
                        + waiver buffer]

VORP (this waiver-buffered baseline) is primary; VOLS (worst starter)
is retained as a diagnostic only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.bdvm.league_config import BdvmLeagueConfig
from src.bdvm.pool import PoolFn


@dataclass(frozen=True)
class GroupReplacement:
    group: str
    startable_slots: int  # league-wide, after flex allocation
    replacement_rank: int  # startable + waiver buffer
    replacement_fpg: float  # VORP baseline (primary)
    worst_starter_fpg: float  # VOLS (diagnostic)
    pool_exhausted: bool  # replacement rank fell off the measured pool


class ReplacementEngine:
    """Greedy flex allocation over per-group rank→FPG pools.

    Each flex slot is assigned to whichever eligible group offers the
    best next-available player; the pools are monotone decreasing so a
    single pass converges.  Deterministic tie-break: group name.
    """

    def __init__(self, cfg: BdvmLeagueConfig, pools: Mapping[str, PoolFn]):
        self.cfg = cfg
        self.pools = dict(pools)
        self.groups: dict[str, GroupReplacement] = {}
        self._solve()

    def _solve(self) -> None:
        cfg = self.cfg
        counts: dict[str, int] = {g: cfg.teams * int(n) for g, n in cfg.starters.items()}
        for _slot_name, (n_per_team, eligible) in cfg.flex.items():
            for _ in range(int(n_per_team) * cfg.teams):
                best_g: str | None = None
                best_v = float("-inf")
                for g in sorted(eligible):
                    pool = self.pools.get(g)
                    if pool is None:
                        continue
                    v = pool(counts.get(g, 0) + 1)
                    if v > best_v:
                        best_g, best_v = g, v
                if best_g is not None:
                    counts[best_g] = counts.get(best_g, 0) + 1

        for g, startable in counts.items():
            buf = int(round(cfg.teams * cfg.buffer_for(g)))
            repl_rank = startable + buf
            pool = self.pools.get(g)
            if pool is None:
                self.groups[g] = GroupReplacement(g, startable, repl_rank, 0.0, 0.0, True)
                continue
            exhausted = bool(getattr(pool, "exhausted_at", lambda r: False)(repl_rank))
            self.groups[g] = GroupReplacement(
                group=g,
                startable_slots=startable,
                replacement_rank=repl_rank,
                replacement_fpg=float(pool(repl_rank)),
                worst_starter_fpg=float(pool(startable)) if startable > 0 else 0.0,
                pool_exhausted=exhausted,
            )

    # ------------------------------------------------------------------
    def R(self, group: str) -> float:
        gr = self.groups.get(group)
        return gr.replacement_fpg if gr else 0.0

    def startable(self, group: str) -> int:
        gr = self.groups.get(group)
        return gr.startable_slots if gr else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            g: {
                "startableSlots": gr.startable_slots,
                "replacementRank": gr.replacement_rank,
                "replacementFpg": round(gr.replacement_fpg, 3),
                "worstStarterFpg": round(gr.worst_starter_fpg, 3),
                "method": "dynamic_vorp",
                "poolExhausted": gr.pool_exhausted,
            }
            for g, gr in sorted(self.groups.items())
        }
