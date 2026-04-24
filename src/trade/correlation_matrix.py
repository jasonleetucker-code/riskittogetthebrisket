"""Upgrade-item #7: correlation matrix builder for the Monte Carlo
trade simulator.

The v1 Monte Carlo (``src.trade.monte_carlo``) uses uniform
``same_team_rho`` + ``same_pos_group_rho`` scalars.  That's a
conservative floor — fine for shipping, but it under-captures
reality: backup-starter pairs on the same team are more
correlated than randomly-paired players, and WR+TE stacks
correlate with their QB.

This module builds a player-by-player correlation matrix that
the Monte Carlo sampler can consume as an alternative to the
two-scalar model.  The matrix is Cholesky-decomposed and used
to produce correlated draws from standard normals.

Structure
---------
For a set of N players the matrix is NxN with diagonal 1.0.
Off-diagonal entries fill from a rule ladder:

    1.00 identity
    0.55 same team, same position (RB1/RB2 handcuffs)
    0.35 same team + "stack" positions (QB+WR, QB+TE)
    0.25 same team, other positions
    0.15 same position group, different team (all QBs move
         together somewhat on schedule-induced injuries etc.)
    0.00 otherwise

All rules subject to the same ceiling ``max_rho`` (default 0.85)
so the matrix stays positive-definite.

Positive-definiteness
---------------------
A block-correlation matrix with uniform off-diagonals can fail
PD when the off-diagonal exceeds 1/(N-1).  We enforce that by
shrinking rho via ``_shrink_to_pd`` until Cholesky succeeds.
Pure-Python Cholesky — slow for N>100, but trades sizes are
tiny (rarely >10 per side).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Stack rules — (pos_a, pos_b) → higher rho than "same team other pos".
_STACK_PAIRS = frozenset({
    ("QB", "WR"), ("WR", "QB"),
    ("QB", "TE"), ("TE", "QB"),
    # RB handcuff.
    ("RB", "RB"),
})

_SAME_TEAM_SAME_POS_RHO = 0.55
_SAME_TEAM_STACK_RHO = 0.35
_SAME_TEAM_OTHER_RHO = 0.25
_SAME_POS_DIFF_TEAM_RHO = 0.15


@dataclass(frozen=True)
class _PlayerAxis:
    team: str
    position: str
    position_group: str  # "offense" | "idp" | "pick"


def build_matrix(
    axes: list[_PlayerAxis],
    *,
    max_rho: float = 0.85,
) -> list[list[float]]:
    """Return an NxN correlation matrix from the per-player axes.

    Symmetric; diagonal=1.  Off-diagonal from the rule ladder.
    """
    n = len(axes)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        mat[i][i] = 1.0
    for i in range(n):
        for j in range(i + 1, n):
            rho = _pairwise_rho(axes[i], axes[j], max_rho=max_rho)
            mat[i][j] = rho
            mat[j][i] = rho
    return mat


def _pairwise_rho(
    a: _PlayerAxis, b: _PlayerAxis, *, max_rho: float,
) -> float:
    same_team = bool(a.team and a.team == b.team)
    same_pos = bool(a.position and a.position == b.position)
    same_group = bool(a.position_group and a.position_group == b.position_group)

    if same_team and same_pos:
        return min(max_rho, _SAME_TEAM_SAME_POS_RHO)
    if same_team and (a.position, b.position) in _STACK_PAIRS:
        return min(max_rho, _SAME_TEAM_STACK_RHO)
    if same_team:
        return min(max_rho, _SAME_TEAM_OTHER_RHO)
    if same_group:
        return min(max_rho, _SAME_POS_DIFF_TEAM_RHO)
    return 0.0


def cholesky(matrix: list[list[float]]) -> list[list[float]] | None:
    """Return lower-triangular Cholesky factor L such that LL^T = matrix.

    Returns None if matrix is not positive-definite (caller can
    shrink and retry).
    """
    n = len(matrix)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                diag = matrix[i][i] - s
                if diag <= 0:
                    return None
                L[i][j] = math.sqrt(diag)
            else:
                if L[j][j] == 0:
                    return None
                L[i][j] = (matrix[i][j] - s) / L[j][j]
    return L


def shrink_to_pd(
    matrix: list[list[float]],
    *,
    max_iterations: int = 8,
    shrink_factor: float = 0.90,
) -> list[list[float]]:
    """Repeatedly multiply off-diagonals by ``shrink_factor`` until
    Cholesky succeeds.  After ``max_iterations`` if still not PD,
    falls back to identity (no correlation)."""
    current = [row[:] for row in matrix]
    for _ in range(max_iterations):
        if cholesky(current) is not None:
            return current
        # Shrink off-diagonals.
        for i in range(len(current)):
            for j in range(len(current)):
                if i != j:
                    current[i][j] *= shrink_factor
    # Last resort — identity.
    n = len(current)
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def build_axes_from_trade_players(players) -> list[_PlayerAxis]:
    """Convert ``TradePlayer`` dataclass instances into per-player axes."""
    axes = []
    for p in players:
        axes.append(_PlayerAxis(
            team=getattr(p, "team", "") or "",
            position=getattr(p, "position", "") or "",
            position_group=getattr(p, "position_group", "") or "offense",
        ))
    return axes
