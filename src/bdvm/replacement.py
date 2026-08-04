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


class ReplacementUnavailableError(RuntimeError):
    """Raised when a group's replacement level is not measurable.

    R is the ORIGIN of the value scale: everything downstream prices
    surplus over it.  A fabricated R = 0 therefore turns every player's
    surplus into his entire per-game production and produces a payload
    indistinguishable from a real one, so the three ways the data can
    fail to answer — group never entered the lineup solve, group has no
    projected pool, replacement rank past the end of the pool — raise
    here instead.  Callers follow the §6.3 missing-data policy and
    report those players as ``unpriced`` with a reason.
    """


@dataclass(frozen=True)
class GroupReplacement:
    group: str
    startable_slots: int  # league-wide, after flex allocation
    replacement_rank: int  # startable + waiver buffer
    replacement_fpg: float | None  # VORP baseline (primary); None = not measurable
    worst_starter_fpg: float | None  # VOLS (diagnostic)
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
            repl_fpg = _measured(pool, repl_rank)
            self.groups[g] = GroupReplacement(
                group=g,
                startable_slots=startable,
                replacement_rank=repl_rank,
                replacement_fpg=repl_fpg,
                worst_starter_fpg=_measured(pool, startable),
                pool_exhausted=repl_fpg is None,
            )

    # ------------------------------------------------------------------
    def R(self, group: str) -> float:
        """Replacement FPG for ``group``, or raise if it is not measurable.

        Deliberately NOT a 0.0 fallback — see ``ReplacementUnavailableError``.
        Guard with ``has_replacement`` when the caller can degrade.
        """
        gr = self.groups.get(group)
        if gr is None:
            raise ReplacementUnavailableError(
                f"no replacement level for lineup group {group!r}: it has no "
                "starter or flex slots in this league"
            )
        if gr.replacement_fpg is None:
            raise ReplacementUnavailableError(
                f"replacement level for {group!r} is not measurable: rank "
                f"{gr.replacement_rank} falls outside the projected pool"
            )
        return gr.replacement_fpg

    def has_replacement(self, group: str) -> bool:
        gr = self.groups.get(group)
        return gr is not None and gr.replacement_fpg is not None

    def startable(self, group: str) -> int:
        """Startable slots — a genuine 0 for a group the league never starts."""
        gr = self.groups.get(group)
        return gr.startable_slots if gr else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            g: {
                "startableSlots": gr.startable_slots,
                "replacementRank": gr.replacement_rank,
                # None (not 0.0) when the pool cannot answer the rank —
                # the payload must not read as a measured zero.
                "replacementFpg": (
                    None if gr.replacement_fpg is None else round(gr.replacement_fpg, 3)
                ),
                "worstStarterFpg": (
                    None if gr.worst_starter_fpg is None else round(gr.worst_starter_fpg, 3)
                ),
                "method": "dynamic_vorp",
                "poolExhausted": gr.pool_exhausted,
            }
            for g, gr in sorted(self.groups.items())
        }


def _measured(pool: PoolFn | None, rank: int) -> float | None:
    """FPG at ``rank``, or None when the pool cannot answer that rank.

    ``PoolCurve`` returns 0.0 past its end ("nothing left on the waiver
    wire"), which is the right answer for the greedy flex allocation —
    it is comparing next-available players — but the WRONG answer for a
    replacement level, where a rank the pool never measured is missing
    data, not a 0.0-FPG player.
    """
    if pool is None or rank <= 0:
        return None
    if bool(getattr(pool, "exhausted_at", lambda _r: False)(rank)):
        return None
    return float(pool(rank))
