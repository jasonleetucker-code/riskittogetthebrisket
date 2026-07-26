"""LI-8 — best-ball roster simulation and trade deltas.

The load-bearing property is MONOTONICITY: removing a player from a
best-ball roster can never raise its expected score, because the slot
goes to whoever spiked and fewer options is weakly worse.  An earlier
revision violated it (+2.55 for dropping a player) because a single
shared RNG stream desynchronised when the roster changed size.
"""

from __future__ import annotations

import random

import pytest

from src.league_intel.sim import (
    SIM_MODEL_VERSION,
    simulate_roster,
    simulate_trade_delta,
)

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "LB", "DL"]


def player(pid, pos, value, fp=()):
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": value,
        "fantasyPositions": list(fp),
    }


def roster(n_extra=6):
    base = [
        player("qb1", "QB", 55),
        player("qb2", "QB", 40),
        player("rb1", "RB", 50),
        player("rb2", "RB", 42),
        player("rb3", "RB", 30),
        player("wr1", "WR", 48),
        player("wr2", "WR", 44),
        player("wr3", "WR", 33),
        player("te1", "TE", 35),
        player("lb1", "LB", 28),
        player("dl1", "DL", 26),
    ]
    base += [player(f"depth{i}", "WR", 20 - i) for i in range(n_extra)]
    return base


class TestSimulateRoster:
    def test_produces_a_distribution(self):
        d = simulate_roster(roster(), SLOTS, weeks=80, seed=1)
        assert d.is_available is True
        assert d.mean > 0
        assert d.sd > 0
        assert d.p10 < d.mean < d.p90

    def test_deterministic_for_a_given_seed(self):
        a = simulate_roster(roster(), SLOTS, weeks=60, seed=5)
        b = simulate_roster(roster(), SLOTS, weeks=60, seed=5)
        assert a.mean == b.mean and a.sd == b.sd

    def test_different_seeds_differ(self):
        a = simulate_roster(roster(), SLOTS, weeks=60, seed=1)
        b = simulate_roster(roster(), SLOTS, weeks=60, seed=2)
        assert a.mean != b.mean

    def test_roster_order_does_not_matter(self):
        r = roster()
        shuffled = list(r)
        random.Random(11).shuffle(shuffled)
        a = simulate_roster(r, SLOTS, weeks=60, seed=4)
        b = simulate_roster(shuffled, SLOTS, weeks=60, seed=4)
        assert a.mean == pytest.approx(b.mean)

    def test_too_small_a_roster_is_unavailable_not_fabricated(self):
        d = simulate_roster([player("a", "QB", 50)], SLOTS, weeks=50)
        assert d.is_available is False
        assert d.mean is None
        assert "too little to simulate" in d.unavailable_reason

    def test_unpriced_players_counted_but_not_drawn(self):
        r = roster() + [player("ghost", "WR", 0)]
        d = simulate_roster(r, SLOTS, weeks=50, seed=1)
        assert d.total_players == len(r)
        assert d.priced_players == len(r) - 1

    def test_hybrids_keep_their_eligibility(self):
        """A DL/LB hybrid must be startable at LB, so a roster with one
        outscores an otherwise identical roster without the LB slot
        filled."""
        without = [p for p in roster() if p["playerId"] != "lb1"]
        with_hybrid = without + [player("hy", "DL", 28, fp=("DL", "LB"))]
        a = simulate_roster(without, SLOTS, weeks=80, seed=2)
        b = simulate_roster(with_hybrid, SLOTS, weeks=80, seed=2)
        assert b.mean > a.mean


class TestMonotonicity:
    """Removing an option can never raise a best-ball score."""

    @pytest.mark.parametrize("drop", [1, 2, 5])
    def test_dropping_players_never_increases_the_mean(self, drop):
        r = sorted(roster(), key=lambda p: -p["rosValue"])
        d = simulate_trade_delta(r, r[:-drop], SLOTS, weeks=100, seed=3)
        assert d.mean_delta <= 1e-9

    def test_dropping_the_best_player_hurts(self):
        r = sorted(roster(), key=lambda p: -p["rosValue"])
        d = simulate_trade_delta(r, r[1:], SLOTS, weeks=100, seed=3)
        assert d.mean_delta < 0

    def test_adding_a_strong_player_helps(self):
        r = roster()
        d = simulate_trade_delta(r, r + [player("star", "WR", 60)], SLOTS, weeks=100, seed=3)
        assert d.mean_delta > 0


class TestPairedSeeding:
    """The before/after comparison must isolate the roster change."""

    def test_identical_rosters_give_exactly_zero(self):
        r = roster()
        d = simulate_trade_delta(r, list(r), SLOTS, weeks=80, seed=6)
        assert d.mean_delta == 0.0
        assert d.sd_delta == 0.0

    def test_reordering_gives_exactly_zero(self):
        """The bug this guards: a shared RNG stream made the delta
        depend on roster ORDER and SIZE, not just contents."""
        r = roster()
        shuffled = list(r)
        random.Random(13).shuffle(shuffled)
        d = simulate_trade_delta(r, shuffled, SLOTS, weeks=80, seed=6)
        assert d.mean_delta == 0.0

    def test_swapping_equal_players_is_near_zero(self):
        r = roster()
        swapped = [p for p in r if p["playerId"] != "wr3"] + [player("wr3b", "WR", 33)]
        d = simulate_trade_delta(r, swapped, SLOTS, weeks=200, seed=6)
        assert abs(d.mean_delta) < 2.0


class TestUnavailableIsNotZero:
    def test_unsimulatable_roster_returns_none_not_zero(self):
        r = roster()
        d = simulate_trade_delta(r, [player("a", "QB", 50)], SLOTS, weeks=50)
        assert d.is_available is False
        assert d.mean_delta is None  # NOT 0.0
        assert d.unavailable_reason
        assert d.confidence == 0.0

    def test_available_delta_carries_confidence_and_assumptions(self):
        r = roster()
        d = simulate_trade_delta(r, r[1:], SLOTS, weeks=60, seed=1)
        assert d.is_available is True
        assert 0 < d.confidence <= 1
        assert any("approximation" in a for a in d.assumptions)
        assert any("paired seeds" in a for a in d.assumptions)

    def test_serializes_with_model_version(self):
        r = roster()
        d = simulate_trade_delta(r, r[1:], SLOTS, weeks=50, seed=1).to_dict()
        assert d["modelVersion"] == SIM_MODEL_VERSION
        assert "meanDelta" in d and "sdDelta" in d
        assert d["before"]["isAvailable"] is True


class TestVariesAcrossRealRosters:
    """A metric that does not vary across the 12 real teams is not a
    metric."""

    @staticmethod
    def _pool():
        import json
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "tests"
            / "league_intel"
            / "fixtures"
            / "league_pool.json"
        )
        if not path.exists():
            pytest.skip("league pool fixture not present")
        return json.loads(path.read_text())

    def test_mean_and_sd_vary_across_teams(self):
        import statistics

        pool = self._pool()
        slots = (
            ["QB"]
            + ["RB"] * 2
            + ["WR"] * 3
            + ["TE"] * 2
            + ["FLEX"] * 2
            + ["SUPER_FLEX"]
            + ["K"]
            + ["DL"] * 3
            + ["LB"] * 3
            + ["DB"] * 3
        )
        means, sds = [], []
        for team in pool:
            d = simulate_roster(team["players"], slots, weeks=40, seed=7)
            assert d.is_available
            means.append(d.mean)
            sds.append(d.sd)
        assert len(means) == 12
        assert statistics.pstdev(means) > 10  # real spread, not a constant
        assert statistics.pstdev(sds) > 0.5
