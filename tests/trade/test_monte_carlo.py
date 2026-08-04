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
        name=name,
        team=team,
        position_group=group,
        p10=p50 * (1 - spread),
        p50=p50,
        p90=p50 * (1 + spread),
    )


def test_clear_winner_gives_near_one_win_prob():
    # Side A: one huge player (10000), Side B: one tiny (100).
    result = mc.simulate_trade(
        [_p("A", 10000)],
        [_p("B", 100)],
        n_sims=5000,
        seed=42,
    )
    assert result.win_prob_a > 0.99


def test_clear_loser_gives_near_zero_win_prob():
    result = mc.simulate_trade(
        [_p("A", 100)],
        [_p("B", 10000)],
        n_sims=5000,
        seed=42,
    )
    assert result.win_prob_a < 0.01


def test_equal_trade_near_half():
    """Same value each side → win prob hovers ~0.5."""
    result = mc.simulate_trade(
        [_p("A", 5000)],
        [_p("B", 5000)],
        n_sims=10000,
        seed=42,
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


def test_exact_ties_are_split_evenly_not_credited_to_b():
    """``winProbA`` counted ``d > 0`` while ``winProbB`` was reported as
    ``1 − winProbA``, so every exact tie was handed to side B in full.

    A degenerate band (p10 = p50 = p90) makes ``_triangular_draw``
    return the same number for every uniform draw, so both sides total
    exactly 1000 in all 500 sims and the delta is 0.0 every time.  The
    old code returned winProbA 0.0 / winProbB 1.0 — a clean sweep for B
    on a trade that is dead even by construction.
    """
    flat_a = mc.TradePlayer(
        name="A", team="BUF", position_group="offense", p10=1000.0, p50=1000.0, p90=1000.0
    )
    flat_b = mc.TradePlayer(
        name="B", team="BUF", position_group="offense", p10=1000.0, p50=1000.0, p90=1000.0
    )
    result = mc.simulate_trade([flat_a], [flat_b], n_sims=500, seed=3)
    assert result.mean_delta == 0.0
    assert result.win_prob_a == 0.5
    d = result.to_dict()
    assert d["winProbA"] == 0.5
    assert d["winProbB"] == 0.5


def test_module_does_not_claim_a_numpy_fast_path():
    """The docstring advertised "NumPy acceleration ... for the hot
    loop"; the module has never imported numpy.  Pinned so the claim
    can't drift back in ahead of the implementation."""
    doc = (mc.__doc__ or "").lower()
    assert "numpy acceleration" not in doc
    assert not hasattr(mc, "np")
    assert not hasattr(mc, "numpy")


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
        "name": "Josh Allen",
        "team": "BUF",
        "pos": "QB",
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


# --- Consolidation adjustment tests ---


def test_consolidation_adjustment_stud_beats_fillers():
    """1 stud vs 4 equal-valued fillers: raw totals favor fillers, VA flips it."""
    stud = [_p("Elite", 3500)]
    fillers = [_p(f"F{i}", 1000) for i in range(4)]  # raw total 4000 > 3500

    no_adj = mc.simulate_trade(stud, fillers, n_sims=10000, seed=42)
    assert no_adj.win_prob_a < 0.5, "fillers should lead on raw totals"

    with_adj = mc.simulate_trade(
        stud,
        fillers,
        n_sims=10000,
        seed=42,
        apply_consolidation_adjustment=True,
    )
    assert with_adj.win_prob_a > no_adj.win_prob_a, "VA must shift odds toward stud"
    assert with_adj.va_adjustment is not None
    assert with_adj.va_adjustment["applied"] is True
    assert with_adj.va_adjustment["side"] == 1  # stud is side_a
    assert with_adj.va_adjustment["value"] > 0


def test_consolidation_adjustment_symmetric_regardless_of_side():
    """VA value is the same magnitude whichever side the stud is placed on."""
    stud = [_p("Elite", 3500)]
    fillers = [_p(f"F{i}", 1000) for i in range(4)]

    ab = mc.simulate_trade(stud, fillers, n_sims=10000, seed=1, apply_consolidation_adjustment=True)
    ba = mc.simulate_trade(fillers, stud, n_sims=10000, seed=1, apply_consolidation_adjustment=True)

    assert ab.va_adjustment["value"] == ba.va_adjustment["value"]
    assert ab.va_adjustment["side"] == 1  # stud received bonus as side_a
    assert ba.va_adjustment["side"] == 2  # stud received bonus as side_b
    assert ab.win_prob_a > 0.5  # stud wins when it's side A
    assert ba.win_prob_a < 0.5  # stud wins when it's side B


def test_consolidation_no_adjustment_on_1v1():
    """KTC suppresses VA for 1v1 trades — no shift applied."""
    result = mc.simulate_trade(
        [_p("Star", 5000)],
        [_p("Good", 4500)],
        n_sims=5000,
        seed=42,
        apply_consolidation_adjustment=True,
    )
    assert result.va_adjustment["applied"] is False
    assert result.va_adjustment["side"] == 0
    assert result.va_adjustment["value"] == 0


def test_consolidation_no_adjustment_equal_packages():
    """Identical value on each side → VA within 5% variance → suppressed."""
    a = [_p("A1", 3000), _p("A2", 2000)]
    b = [_p("B1", 3000), _p("B2", 2000)]
    result = mc.simulate_trade(a, b, n_sims=5000, seed=42, apply_consolidation_adjustment=True)
    assert result.va_adjustment["applied"] is False


def test_consolidation_default_off_preserves_existing_behavior():
    """Default flag=False must produce identical results to explicit False."""
    stud = [_p("Elite", 3500)]
    fillers = [_p(f"F{i}", 1000) for i in range(4)]
    default_result = mc.simulate_trade(stud, fillers, n_sims=5000, seed=99)
    explicit_off = mc.simulate_trade(
        stud, fillers, n_sims=5000, seed=99, apply_consolidation_adjustment=False
    )
    assert default_result.win_prob_a == explicit_off.win_prob_a
    assert default_result.va_adjustment["applied"] is False
