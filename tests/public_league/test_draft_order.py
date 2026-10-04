"""The canonical rookie-draft ORDER rule (owner decision 2026-10-04).

Reverse final regular-season record; teams tied on record ordered by LOWER
total Points For; applied recursively.  Not Max PF, all-play or Team Strength.
"""

from __future__ import annotations

import json
import random

import pytest

from src.public_league.draft_order import (
    REVERSE_RECORD_LOWER_PF,
    draft_order,
    draft_order_from_standings,
    league_draft_order_rule,
)


def test_worst_record_picks_first():
    wins = {"a": 10, "b": 3, "c": 7}
    pf = {"a": 1500, "b": 1400, "c": 1450}
    assert draft_order(wins, pf, wins).order == ("b", "c", "a")


def test_record_tie_goes_to_the_LOWER_points_for():
    wins = {"a": 6, "b": 6}
    pf = {"a": 1300.5, "b": 1450.0}
    assert draft_order(wins, pf, wins).order == ("a", "b")


def test_points_for_never_outranks_record():
    # b scored far fewer points but won more games: record decides first.
    wins = {"a": 4, "b": 5}
    pf = {"a": 1600, "b": 1000}
    assert draft_order(wins, pf, wins).order == ("a", "b")


def test_three_way_record_tie_is_ordered_recursively_by_lower_pf():
    wins = {"x": 5, "y": 5, "z": 5, "w": 2, "v": 9}
    pf = {"x": 1400, "y": 1200, "z": 1300, "w": 1500, "v": 1100}
    assert draft_order(wins, pf, wins).order == ("w", "y", "z", "x", "v")


def test_a_tied_game_counts_half_a_win():
    rows = [
        {"ownerId": "a", "wins": 6, "ties": 1, "pointsFor": 1200},  # 6.5
        {"ownerId": "b", "wins": 6, "ties": 0, "pointsFor": 1500},  # 6.0
    ]
    assert draft_order_from_standings(rows).order == ("b", "a")


def test_identical_record_and_pf_is_reported_never_silently_ordered():
    out = draft_order({"a": 5, "b": 5}, {"a": 1300, "b": 1300}, ["a", "b"])
    assert out.unresolved_ties == (("a", "b"),)


def test_in_a_simulation_only_the_rng_breaks_an_exact_double_tie():
    wins, pf = {"a": 5, "b": 5}, {"a": 1300, "b": 1300}
    firsts = {draft_order(wins, pf, ["a", "b"], rng=random.Random(i)).order[0] for i in range(40)}
    assert firsts == {"a", "b"}  # not decided by the identifier


def test_missing_points_for_is_unknown_not_zero():
    with pytest.raises(ValueError):
        draft_order({"a": 5}, {}, ["a"])
    with pytest.raises(ValueError):
        draft_order_from_standings([{"ownerId": "a", "wins": 5, "ties": 0, "pointsFor": None}])
    with pytest.raises(ValueError):
        draft_order_from_standings([{"ownerId": "a", "pointsFor": 1200}])


def test_the_rule_is_recorded_for_dynasty_main_and_unknown_elsewhere(tmp_path):
    assert league_draft_order_rule("dynasty_main") == REVERSE_RECORD_LOWER_PF
    assert league_draft_order_rule("some_other_league") is None
    assert league_draft_order_rule(None) is None
    bad = tmp_path / "rules.json"
    bad.write_text(json.dumps({"rules": {"x": {"rule": "max_pf"}}}), encoding="utf-8")
    assert league_draft_order_rule("x", path=bad) is None  # an unknown rule id is not adopted


def test_a_standings_row_without_an_owner_refuses_the_order():
    # Dropping it would shift every later slot by one.
    rows = [
        {"ownerId": "a", "wins": 3, "ties": 0, "pointsFor": 900.0},
        {"wins": 5, "ties": 0, "pointsFor": 950.0},
    ]
    with pytest.raises(ValueError, match="ownerId"):
        draft_order_from_standings(rows)
    dup = [rows[0], dict(rows[0])]
    with pytest.raises(ValueError, match="twice"):
        draft_order_from_standings(dup)
