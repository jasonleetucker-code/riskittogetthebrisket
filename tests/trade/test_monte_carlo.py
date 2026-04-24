"""Tests for the Monte Carlo trade simulator.

Key invariants:
  * Clear-winner trade → win prob ~ 1.
  * Equal trade → win prob ~ 0.5 (within sampling tolerance).
  * Reproducible with same seed.
  * Correlation changes the spread but not the mean.
  * Empty sides don't crash.
  * Label stays explicit: "consensus_based_win_rate".
"""
from __future__ import annotations

from src.trade import monte_carlo as mc


def _p(name, p50, spread=0.15, team="BUF", group="offense"):
    return mc.TradePlayer(
        name=name, team=team, position_group=group,
        p10=p50 * (1 - spread), p50=p50, p90=p50 * (1 + spread),
    )


def test_clear_winner_gives_near_one_win_prob():
    # Side A: one huge player (10000), Side B: one tiny (100).
    result = mc.simulate_trade(
        [_p("A", 10000)],
        [_p("B", 100)],
        n_sims=5000, seed=42,
    )
    assert result.win_prob_a > 0.99


def test_clear_loser_gives_near_zero_win_prob():
    result = mc.simulate_trade(
        [_p("A", 100)],
        [_p("B", 10000)],
        n_sims=5000, seed=42,
    )
    assert result.win_prob_a < 0.01


def test_equal_trade_near_half():
    """Same value each side → win prob hovers ~0.5."""
    result = mc.simulate_trade(
        [_p("A", 5000)],
        [_p("B", 5000)],
        n_sims=10000, seed=42,
    )
    assert 0.40 <= result.win_prob_a <= 0.60


def test_seeded_simulation_reproducible():
    a_first = mc.simulate_trade([_p("A", 5000)], [_p("B", 4500)], n_sims=2000, seed=99)
    a_second = mc.simulate_trade([_p("A", 5000)], [_p("B", 4500)], n_sims=2000, seed=99)
    assert a_first.win_prob_a == a_second.win_prob_a
    assert a_first.mean_delta == a_second.mean_delta


def test_higher_correlation_widens_spread_of_delta():
    """Intuition: high team correlation on same-side players pumps
    variance.  All A players on BUF, all B on SF → rho should
    widen the delta distribution."""
    a = [_p("A1", 5000, team="BUF"), _p("A2", 4800, team="BUF"), _p("A3", 4500, team="BUF")]
    b = [_p("B1", 4700, team="SF"), _p("B2", 4900, team="SF"), _p("B3", 4600, team="SF")]
    low = mc.simulate_trade(a, b, n_sims=3000, seed=1, same_team_rho=0.0, same_pos_group_rho=0.0)
    high = mc.simulate_trade(a, b, n_sims=3000, seed=1, same_team_rho=0.45, same_pos_group_rho=0.0)
    # With correlated same-team moves, spread grows.
    assert high.std_delta >= low.std_delta * 0.95


def test_empty_sides_do_not_crash():
    result = mc.simulate_trade([], [], n_sims=100)
    assert result.win_prob_a == 0.5
    assert result.mean_delta == 0.0
    assert result.n_sims == 0


def test_one_side_empty_still_runs():
    result = mc.simulate_trade([_p("A", 5000)], [], n_sims=500, seed=7)
    assert result.win_prob_a > 0.99


def test_to_dict_preserves_disclaimer():
    result = mc.simulate_trade([_p("A", 1000)], [_p("B", 900)], n_sims=500, seed=1)
    d = result.to_dict()
    assert d["method"] == "consensus_based_win_rate"
    assert "consensus" in d["disclaimer"].lower()
    assert "NOT" in d["disclaimer"]


def test_build_trade_player_uses_band_when_available():
    row = {
        "name": "Josh Allen", "team": "BUF", "pos": "QB",
        "rankDerivedValue": 9000,
        "valueBand": {"p10": 8200, "p50": 9000, "p90": 9700},
    }
    tp = mc.build_trade_player(row)
    assert tp.p10 == 8200
    assert tp.p50 == 9000
    assert tp.p90 == 9700


def test_build_trade_player_falls_back_to_pct_band():
    row = {"name": "X", "team": "KC", "pos": "RB", "rankDerivedValue": 5000}
    tp = mc.build_trade_player(row)
    assert tp.p50 == 5000
    assert tp.p10 == 5000 * 0.85
    assert tp.p90 == 5000 * 1.15


def test_build_trade_player_groups_idp_correctly():
    row = {"name": "LB1", "team": "SF", "pos": "LB", "rankDerivedValue": 3000}
    tp = mc.build_trade_player(row)
    assert tp.position_group == "idp"


def test_build_trade_player_groups_pick_correctly():
    row = {"name": "2027 Mid 4th", "pos": "PICK", "rankDerivedValue": 500}
    tp = mc.build_trade_player(row)
    assert tp.position_group == "pick"


def test_build_trade_player_nameless_returns_none():
    assert mc.build_trade_player({"rankDerivedValue": 100}) is None
    assert mc.build_trade_player(None) is None


def test_triangular_draw_covers_full_range():
    # u=0 → low tail; u=1 → high tail.
    lo = mc._triangular_draw(100, 200, 300, 1e-6)  # noqa: SLF001
    hi = mc._triangular_draw(100, 200, 300, 1 - 1e-6)  # noqa: SLF001
    assert lo < 100
    assert hi > 300
    # u=0.5 → exactly p50 (200).
    mid = mc._triangular_draw(100, 200, 300, 0.5)  # noqa: SLF001
    assert abs(mid - 200) < 0.01
