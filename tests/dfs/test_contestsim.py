"""Contest Monte Carlo: exact where the answer is known, calibrated where it is statistical."""

from __future__ import annotations

import pytest

from src.dfs import contestsim
from src.dfs.contests import Contest, PayoutBand
from src.dfs.distributions import PlayerDistribution
from src.dfs.rules import get_ruleset

MMA = get_ruleset("draftkings.mma.classic")  # six F slots: a simple, symmetric roster


def _contest(field, ladder, tie_rule="split_positions", fee=1000):
    return Contest(
        name="Toy",
        platform="draftkings",
        sport="mma",
        format="classic",
        entry_fee_cents=fee,
        capacity=field,
        tie_rule=tie_rule,
        ladder=ladder,
    )


def _dist(pid, mean, sd):
    return PlayerDistribution(pid, pid, mean, "normal", sd=sd, basis="test")


def _setup(dists, field, contest, n_field, sims=400, seed=3):
    return contestsim.SimSetup(MMA, contest, n_field, dists, {}, field, sims, seed)


def test_a_lineup_that_always_wins_collects_exactly_first_prize():
    stars = [_dist(f"s{i}", 100.0, 1e-6) for i in range(6)]
    scrubs = [_dist(f"x{i}", 10.0, 1e-6) for i in range(6)]
    field = [tuple(d.player_id for d in scrubs)] * 5
    c = _contest(10, [PayoutBand(1, 1, 50_000), PayoutBand(2, 3, 5_000)])
    out = contestsim.simulate(
        _setup(stars + scrubs, field, c, 10), [tuple(d.player_id for d in stars)], [0.0]
    )
    one = out["perLineup"][0]
    assert one["expectedPayoutCents"] == 50_000 and one["pWin"] == 1.0 and one["pCash"]["p"] == 1.0
    assert one["expectedProfitCents"] == 49_000 and out["assumptions"] == []


def test_a_guaranteed_tie_splits_the_tied_places_exactly():
    # Our lineup and three field-sample copies score the same: 4 entries share places 1-4.
    team = [_dist(f"t{i}", 100.0, 1e-9) for i in range(6)]
    low = [_dist(f"l{i}", 1.0, 1e-9) for i in range(6)]
    ours = tuple(d.player_id for d in team)
    field = [ours, ours, ours] + [tuple(d.player_id for d in low)] * 7  # sample == field (scale 1)
    c = _contest(11, [PayoutBand(1, 1, 40_000), PayoutBand(2, 2, 20_000), PayoutBand(3, 4, 10_000)])
    one = contestsim.simulate(_setup(team + low, field, c, 11), [ours], [0.0])["perLineup"][0]
    assert one["expectedPayoutCents"] == pytest.approx((40_000 + 20_000 + 10_000 + 10_000) / 4)


def test_our_entries_compete_with_each_other_in_the_portfolio():
    stars = [_dist(f"s{i}", 100.0, 1e-6) for i in range(12)]
    scrubs = [_dist(f"x{i}", 10.0, 1e-6) for i in range(6)]
    a, b = tuple(f"s{i}" for i in range(6)), tuple(f"s{i}" for i in range(6, 12))
    field = [tuple(d.player_id for d in scrubs)] * 8
    c = _contest(10, [PayoutBand(1, 1, 50_000), PayoutBand(2, 2, 10_000)])
    out = contestsim.simulate(_setup(stars + scrubs, field, c, 10), [a, b], [0.0, 0.0])
    assert out["portfolio"]["expectedPayoutCents"] == pytest.approx(
        60_000
    )  # 1st + 2nd, never 1st twice


def test_symmetric_contest_gives_each_entry_a_fair_share():
    """All players iid, every lineup disjoint: P(win) ≈ 1/N and EV ≈ pool/N (within MC error)."""
    n = 8
    players = [_dist(f"p{i}", 50.0, 10.0) for i in range(6 * n)]
    lineups = [tuple(f"p{6 * k + j}" for j in range(6)) for k in range(n)]
    c = _contest(n, [PayoutBand(1, 1, 8_000)])
    out = contestsim.simulate(
        _setup(players, lineups[1:], c, n, sims=4000, seed=9), [lineups[0]], [0.0]
    )
    one = out["perLineup"][0]
    assert one["pWin"] == pytest.approx(1 / n, abs=0.02)
    assert one["expectedPayoutCents"] == pytest.approx(
        8_000 / n, abs=3 * one["expectedPayoutSe"] + 1
    )


def test_unknown_tie_rule_is_assumed_and_disclosed_and_inputs_are_bounded():
    stars = [_dist(f"s{i}", 100.0, 1.0) for i in range(6)]
    field = [tuple(d.player_id for d in stars)]
    c = _contest(5, [PayoutBand(1, 1, 1_000)], tie_rule="unknown")
    out = contestsim.simulate(_setup(stars, field, c, 5, sims=50), [field[0]], [0.0])
    assert any("assumedTieRule" in a for a in out["assumptions"])
    with pytest.raises(ValueError):
        contestsim.simulate(
            _setup(stars, field, c, 5, sims=contestsim.MAX_SIMS + 1), [field[0]], [0.0]
        )
    with pytest.raises(KeyError):
        contestsim.simulate(_setup(stars, field, c, 5, sims=10), [("nope",) * 6], [0.0])
