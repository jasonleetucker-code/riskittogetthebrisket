"""rank-space-hampel-v1 (preregistered challenger; default OFF)."""

from __future__ import annotations

import math

import pytest

from src.api import data_contract as dc
from src.api import feature_flags
from src.canonical import player_valuation as pv

OFF = (pv.HILL_PERCENTILE_C, pv.HILL_PERCENTILE_S)


@pytest.mark.parametrize("p", [0.001, 0.01, 0.05, 0.2, 0.5, 0.9])
def test_inverse_is_exact(p):
    v = 9999.0 / (1.0 + (p / OFF[0]) ** OFF[1])
    assert math.isclose(dc._hill_inverse(v, *OFF), p, rel_tol=1e-9)


def test_inverse_edges():
    assert dc._hill_inverse(9999.0, *OFF) == 0.0
    assert dc._hill_inverse(0.0, *OFF) == math.inf


def test_guards_match_the_incumbent():
    three = [("a", 5000.0), ("b", 5100.0), ("c", 9000.0)]
    assert dc._hampel_filter_rank_space(three, curve=OFF) == (three, [])  # n < 4
    same = [(k, 4000.0) for k in "abcd"]
    assert dc._hampel_filter_rank_space(same, curve=OFF)[1] == []  # perfect agreement


def test_never_collapses_a_row_to_one_survivor():
    pairs = [("a", 9000.0), ("b", 1000.0), ("c", 1100.0), ("d", 1050.0)]
    kept, dropped = dc._hampel_filter_rank_space(pairs, curve=OFF)
    assert len(kept) >= 2


def test_floor_protects_what_the_incumbent_floor_protects_mid_board():
    """Mid-board, a disagreement inside the incumbent's 1,000-point floor is
    not an outlier in rank space either (the floor is carried, not tuned)."""
    pairs = [("a", 3000.0), ("b", 3050.0), ("c", 3020.0), ("d", 3010.0), ("e", 3400.0)]
    assert dc._hampel_filter_per_player(pairs)[1] == []
    assert dc._hampel_filter_rank_space(pairs, curve=OFF)[1] == []


def test_flag_ships_off_and_is_declared():
    assert feature_flags._DEFAULTS["rank_space_hampel_challenger"] is False
