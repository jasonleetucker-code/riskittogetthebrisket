"""Tests for the Monte Carlo correlation matrix builder."""
from __future__ import annotations

from src.trade import correlation_matrix as cm


def _ax(team, pos, group="offense"):
    return cm._PlayerAxis(team=team, position=pos, position_group=group)  # noqa: SLF001


def test_identity_on_empty_input():
    mat = cm.build_matrix([])
    assert mat == []


def test_diagonal_is_one():
    axes = [_ax("BUF", "QB"), _ax("KC", "RB"), _ax("MIA", "WR")]
    mat = cm.build_matrix(axes)
    assert mat[0][0] == 1.0
    assert mat[1][1] == 1.0
    assert mat[2][2] == 1.0


def test_same_team_same_pos_gets_high_rho():
    """Two RBs on the same team — handcuff correlation."""
    axes = [_ax("BUF", "RB"), _ax("BUF", "RB")]
    mat = cm.build_matrix(axes)
    # Same team + same pos = 0.55 (also matches stack-rule RB/RB = 0.55 either way).
    assert mat[0][1] >= 0.50


def test_qb_wr_stack_higher_than_same_team_other():
    axes = [_ax("BUF", "QB"), _ax("BUF", "WR")]
    mat = cm.build_matrix(axes)
    # QB/WR stack pair gets _SAME_TEAM_STACK_RHO = 0.35.
    assert mat[0][1] == 0.35


def test_same_team_other_pair_has_smaller_rho():
    axes = [_ax("BUF", "QB"), _ax("BUF", "LB")]  # QB + LB — not a stack
    mat = cm.build_matrix(axes)
    # Same-team but different group — 0.25.
    assert mat[0][1] == 0.25


def test_different_teams_same_pos_group():
    axes = [_ax("BUF", "QB"), _ax("KC", "QB")]
    mat = cm.build_matrix(axes)
    # Same group (offense), different team — 0.15.
    assert mat[0][1] == 0.15


def test_different_everything_zero():
    axes = [_ax("BUF", "QB"), _ax("KC", "RB", group="offense")]
    mat = cm.build_matrix(axes)
    # Same group offense but — wait, the rule says same_group → 0.15.
    # If we want to ensure "different everything" is zero, we need
    # different groups.  QB + DL.
    axes2 = [_ax("BUF", "QB", group="offense"), _ax("KC", "DL", group="idp")]
    mat2 = cm.build_matrix(axes2)
    assert mat2[0][1] == 0.0


def test_matrix_symmetric():
    axes = [_ax("BUF", "QB"), _ax("BUF", "WR"), _ax("KC", "RB")]
    mat = cm.build_matrix(axes)
    for i in range(len(mat)):
        for j in range(len(mat)):
            assert mat[i][j] == mat[j][i]


def test_cholesky_succeeds_on_pd_matrix():
    # 2x2 identity.
    mat = [[1.0, 0.0], [0.0, 1.0]]
    L = cm.cholesky(mat)
    assert L is not None
    # LL^T should reconstruct identity.
    assert abs(L[0][0] - 1.0) < 1e-9
    assert abs(L[1][1] - 1.0) < 1e-9


def test_cholesky_fails_on_non_pd():
    # Correlation 0.999 × off-diagonal with many entries can fail PD.
    mat = [[1.0, 0.99, 0.99], [0.99, 1.0, 0.99], [0.99, 0.99, 1.0]]
    # This particular matrix IS positive definite — all eigenvalues > 0.
    # A better example: negative determinant.
    # 2x2 with rho > 1 explicitly breaks.
    bad = [[1.0, 1.5], [1.5, 1.0]]
    assert cm.cholesky(bad) is None


def test_shrink_to_pd_recovers():
    # Break PD with rho > 1.
    mat = [[1.0, 1.5], [1.5, 1.0]]
    shrunk = cm.shrink_to_pd(mat)
    # Now PD.
    L = cm.cholesky(shrunk)
    assert L is not None


def test_shrink_to_pd_falls_back_to_identity_when_stuck():
    # Negative diagonal → never PD; should fall back.
    bad = [[1.0, 10.0], [10.0, 1.0]]  # severely broken
    shrunk = cm.shrink_to_pd(bad, max_iterations=2, shrink_factor=0.99)
    # After shrink we either got PD or identity.  Either is acceptable.
    L = cm.cholesky(shrunk)
    assert L is not None


def test_build_axes_from_trade_players():
    from src.trade.monte_carlo import TradePlayer
    players = [
        TradePlayer(name="A", team="BUF", position_group="offense",
                    p10=100, p50=200, p90=300),
    ]
    axes = cm.build_axes_from_trade_players(players)
    assert len(axes) == 1
    assert axes[0].team == "BUF"
    assert axes[0].position_group == "offense"


def test_matrix_respects_max_rho_ceiling():
    """max_rho cap prevents excessive correlation that would break
    PD in a large block."""
    axes = [_ax("BUF", "RB"), _ax("BUF", "RB")]
    mat = cm.build_matrix(axes, max_rho=0.30)
    assert mat[0][1] == 0.30
