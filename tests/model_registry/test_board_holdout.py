"""The harness that decides whether the league-adjusted board ships.

This is a decision procedure, so the tests that matter most are the ones
proving it CAN return each answer.  A comparison that structurally
cannot say "MARKET WINS" is not evidence for the adjusted board — it is
a guard that cannot fire (ORCHESTRATION.md §6.15), and it would hand a
green light to whatever it was pointed at.

So each verdict gets a constructed population that should produce it,
built by moving the adjusted arm toward or away from the target rather
than by asserting on the real data the runner will feed it.
"""

from __future__ import annotations

import random

import pytest

from src.model_registry.board_holdout import (
    compare_boards,
    paired_bootstrap,
    spearman,
)


def _rows(market, adjusted, actual, positions=None):
    return [
        {
            "market": m,
            "adjusted": a,
            "actual": y,
            "position": (positions[i] if positions else "WR"),
        }
        for i, (m, a, y) in enumerate(zip(market, adjusted, actual))
    ]


# ── spearman ────────────────────────────────────────────────────────────


def test_perfect_agreement_and_perfect_inversion():
    xs = list(range(20))
    assert spearman(xs, xs) == pytest.approx(1.0)
    assert spearman(xs, list(reversed(xs))) == pytest.approx(-1.0)


def test_it_is_invariant_to_monotone_rescaling():
    """The whole reason for a RANK correlation.

    Board values sit on a Hill curve, so a 4% value move means a
    different rank move at the top of the board than at the bottom.
    Scoring on raw values would let that nonlinearity masquerade as
    accuracy.
    """
    xs = list(range(3, 40))
    curved = [x**3 + 17 for x in xs]
    assert spearman(xs, curved) == pytest.approx(1.0)


def test_ties_are_averaged_not_broken_arbitrarily():
    """The board rounds to integers and deep players share values.

    Breaking ties by input order would manufacture ordering information
    that is not in the data — and would make the score depend on how the
    rows happened to be sorted upstream.
    """
    a = [1, 1, 1, 2, 2, 3, 3, 3, 3]
    forward = spearman(a, list(range(len(a))))
    shuffled_pairs = list(zip(a, range(len(a))))
    rng = random.Random(3)
    rng.shuffle(shuffled_pairs)
    reordered = spearman([p[0] for p in shuffled_pairs], [p[1] for p in shuffled_pairs])
    assert forward == pytest.approx(reordered)


def test_degenerate_input_returns_zero_rather_than_raising():
    """A diagnostic must not be the thing that fails."""
    assert spearman([], []) == 0.0
    assert spearman([1, 2], [1, 2]) == 0.0
    assert spearman([5] * 10, list(range(10))) == 0.0
    assert spearman([1, 2, 3], [1, 2]) == 0.0


# ── paired bootstrap ────────────────────────────────────────────────────


def test_the_bootstrap_is_deterministic():
    """A verdict that changes between runs is not a verdict."""
    rng = random.Random(1)
    actual = [rng.random() for _ in range(80)]
    market = [y + rng.gauss(0, 0.4) for y in actual]
    adjusted = [y + rng.gauss(0, 0.2) for y in actual]
    first = paired_bootstrap(market, adjusted, actual, iterations=400)
    second = paired_bootstrap(market, adjusted, actual, iterations=400)
    assert first == second


def test_identical_arms_cannot_produce_a_winner():
    """THE GUARD against the harness inventing a difference.

    If both boards are the same board, every resample must score them
    identically, so the interval is exactly zero-width at zero.  Any
    nonzero spread here would mean the two arms are being resampled
    independently and the comparison is unpaired.
    """
    rng = random.Random(7)
    actual = [rng.random() for _ in range(120)]
    board = [y + rng.gauss(0, 0.3) for y in actual]
    win_rate, lo, hi = paired_bootstrap(board, list(board), actual, iterations=500)
    assert win_rate == 0.0
    assert lo == 0.0 and hi == 0.0


def test_too_small_a_sample_declines_to_answer():
    assert paired_bootstrap([1, 2, 3], [3, 2, 1], [1, 2, 3]) == (0.5, 0.0, 0.0)


# ── verdicts: each one must be reachable ────────────────────────────────


def _noisy_population(seed, market_noise, adjusted_noise, n=200):
    rng = random.Random(seed)
    actual = [rng.random() * 100 for _ in range(n)]
    market = [y + rng.gauss(0, market_noise) for y in actual]
    adjusted = [y + rng.gauss(0, adjusted_noise) for y in actual]
    return market, adjusted, actual


def test_a_genuinely_better_adjusted_board_is_detected():
    market, adjusted, actual = _noisy_population(11, market_noise=30.0, adjusted_noise=8.0)
    res = compare_boards(_rows(market, adjusted, actual), iterations=600)
    assert res.verdict.startswith("ADJUSTED WINS"), res.verdict
    assert res.delta > 0
    assert res.ci_low > 0
    assert res.win_rate > 0.9


def test_a_genuinely_worse_adjusted_board_is_detected():
    """The verdict that makes this harness worth running.

    Without this the whole thing could be a rubber stamp.
    """
    market, adjusted, actual = _noisy_population(12, market_noise=8.0, adjusted_noise=30.0)
    res = compare_boards(_rows(market, adjusted, actual), iterations=600)
    assert res.verdict.startswith("MARKET WINS"), res.verdict
    assert res.delta < 0
    assert res.ci_high < 0


def test_a_wash_is_reported_as_a_wash():
    market, adjusted, actual = _noisy_population(13, market_noise=20.0, adjusted_noise=20.0)
    res = compare_boards(_rows(market, adjusted, actual), iterations=600)
    assert res.verdict.startswith("NO DIFFERENCE DETECTED"), res.verdict
    assert res.ci_low < 0 < res.ci_high


def test_an_adjustment_that_barely_applies_is_inconclusive_not_null():
    """A null result on a population the adjustment never touched says
    nothing about the adjustment — and reporting it as "no difference"
    would let a broken join look like an honest negative.
    """
    rng = random.Random(5)
    actual = [rng.random() * 100 for _ in range(200)]
    market = [y + rng.gauss(0, 20) for y in actual]
    adjusted = list(market)
    for i in range(4):  # four movers out of 200
        adjusted[i] = market[i] * 1.2
    res = compare_boards(_rows(market, adjusted, actual), iterations=300)
    assert res.verdict.startswith("INCONCLUSIVE"), res.verdict
    assert res.movers == 4


def test_movers_counts_only_players_the_adjustment_actually_moved():
    market = [float(i) for i in range(100)]
    adjusted = [v * (1.1 if i % 2 == 0 else 1.0) for i, v in enumerate(market)]
    res = compare_boards(_rows(market, adjusted, market), iterations=100)
    # rank 0 scaled by 1.1 is still 0, so it does not move.
    assert res.movers == 49


# ── joining and shape ───────────────────────────────────────────────────


def test_rows_missing_any_arm_are_dropped_not_defaulted():
    """A player with no realized points must leave the population, not
    enter it as a zero — that would score every unplayed player as the
    worst player in football and reward whichever board ranked him
    lowest."""
    rows = _rows(*_noisy_population(21, 10.0, 10.0, n=60))
    rows.append({"market": 100.0, "adjusted": 110.0, "actual": None, "position": "WR"})
    rows.append({"market": None, "adjusted": 110.0, "actual": 5.0, "position": "WR"})
    rows.append({"market": 100.0, "adjusted": None, "actual": 5.0, "position": "WR"})
    res = compare_boards(rows, iterations=100)
    assert res.n == 60


def test_too_few_joined_players_refuses_to_decide():
    rows = _rows(*_noisy_population(22, 10.0, 10.0, n=12))
    res = compare_boards(rows, iterations=100)
    assert "too few joined players" in res.verdict
    assert res.n == 12


def test_per_position_breakdown_skips_thin_positions():
    """A 3-player position correlation is noise wearing a number."""
    market, adjusted, actual = _noisy_population(23, 15.0, 10.0, n=60)
    positions = ["WR"] * 45 + ["TE"] * 12 + ["QB"] * 3
    res = compare_boards(_rows(market, adjusted, actual, positions), iterations=100)
    assert set(res.by_position) == {"WR", "TE"}
    assert res.by_position["WR"]["n"] == 45


def test_the_payload_round_trips_to_json_shaped_output():
    market, adjusted, actual = _noisy_population(24, 15.0, 10.0, n=60)
    out = compare_boards(_rows(market, adjusted, actual), iterations=100).to_dict()
    assert set(out) >= {
        "n",
        "marketRho",
        "adjustedRho",
        "delta",
        "winRate",
        "ci95",
        "movers",
        "byPosition",
        "verdict",
    }
    assert out["ci95"][0] <= out["ci95"][1]
