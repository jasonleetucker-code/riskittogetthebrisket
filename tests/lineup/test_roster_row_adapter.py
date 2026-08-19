"""ONE roster-row → RosterPlayer adapter.

Two byte-identical copies existed, and the second one's docstring said
it "mirrors" the first "deliberately: the two modules must agree on how
a roster row becomes an optimizer input, or their numbers stop being
comparable". Agreement maintained by hand is what ONE CONCEPT, ONE
CANONICAL OWNER exists to replace.
"""

from __future__ import annotations

import ast
import inspect

from src.league_intel import replacement as replacement_mod
from src.roster_intel import marginal as marginal_mod
from src.ros.lineup import roster_player_from_row, roster_players_from_rows

_ROW = {
    "playerId": "p1",
    "canonicalName": "Player One",
    "position": "rb",
    "rosValue": 500.0,
    "confidence": 0.8,
    "injured": True,
    "fantasyPositions": ["rb", "wr"],
}


def test_both_historical_copies_now_delegate():
    """Structural, not behavioural: a future edit that re-inlines either
    copy reintroduces the drift this consolidation removed."""
    for fn in (replacement_mod._to_roster_players, marginal_mod.to_roster_players):
        tree = ast.parse(inspect.getsource(fn).lstrip())
        calls = {
            n.func.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "roster_players_from_rows" in calls, fn.__qualname__
        # And it constructs no RosterPlayer of its own.
        assert "RosterPlayer" not in calls, fn.__qualname__


def test_no_adapter_coerces_a_missing_number_to_zero():
    """`float(row.get("rosValue") or 0.0)` is the exact coercion C2-U1
    retired from the lineup owner. It must not survive in an adapter,
    where it would hand the solver a real, assignable, worthless player
    instead of an unpriced one.

    Matched STRUCTURALLY on the `ros_value=` argument — any
    `<expr> or <numeric 0>` reaching it — rather than on literal text.
    Scoped to that one field on purpose: `confidence or 0.0` in the same
    call is a different statement (no confidence IS no confidence, and
    it is not the solver's objective), so a blanket rule would fail on
    correct code. A text match is defeated by renaming the loop
    variable, which is exactly what a re-inline would do; this was
    measured, not assumed (a mutant using `p.get` instead of `row.get`
    slipped past the string form).

    Scoped to the three adapter functions rather than to whole files:
    `measure_endogenous_starters` carries the same expression over rows
    the solver ALREADY seated, where a missing value is unreachable
    (`lineup.py` writes `rosValue` for every assigned player), so
    flagging it would be a false positive.

    Docstrings are stripped first, because `roster_player_from_row`
    QUOTES the retired expression to explain why it is gone — a guard
    that reads its own explanation as a regression is the mistake that
    made two earlier guards in this repo decorative (#909).
    """
    for fn in (
        replacement_mod._to_roster_players,
        marginal_mod.to_roster_players,
        roster_player_from_row,
    ):
        tree = ast.parse(inspect.getsource(fn).lstrip())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(
                node
            ):
                node.body = node.body[1:]
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or node.arg != "ros_value":
                continue
            for inner in ast.walk(node.value):
                if not isinstance(inner, ast.BoolOp) or not isinstance(inner.op, ast.Or):
                    continue
                assert not any(
                    isinstance(v, ast.Constant)
                    and isinstance(v.value, (int, float))
                    and not isinstance(v.value, bool)
                    and v.value == 0
                    for v in inner.values[1:]
                ), f"{fn.__qualname__} coerces a missing ros_value to zero"


def test_the_three_copies_agree_because_there_is_one():
    a = replacement_mod._to_roster_players([_ROW])
    b = marginal_mod.to_roster_players([_ROW])
    c = roster_players_from_rows([_ROW])
    assert a == b == c


def test_a_missing_value_is_unknown_not_zero():
    player = roster_player_from_row({"playerId": "ghost", "position": "WR"})
    assert player.ros_value is None


def test_an_explicit_zero_is_a_real_value():
    """0.0 means "assignable and contributes nothing"; None means "we
    have no read". Conflating them is what the retired coercion did."""
    player = roster_player_from_row({"playerId": "p", "position": "WR", "rosValue": 0})
    assert player.ros_value == 0.0


def test_row_fields_map_across_faithfully():
    p = roster_player_from_row(_ROW)
    assert p.player_id == "p1"
    assert p.canonical_name == "Player One"
    assert p.position == "RB"
    assert p.ros_value == 500.0
    assert p.confidence == 0.8
    assert p.injured is True
    assert p.bye is False
    # Hybrid eligibility survives: dropping it silently benches hybrid
    # IDPs (LI-3 / ADR-007).
    assert p.fantasy_positions == ("RB", "WR")


def test_player_id_falls_back_to_the_canonical_name():
    """Some roster sources are name-keyed. An empty id would collide
    every such player onto one entry, and the solver's duplicate guard
    would then seat only the first."""
    p = roster_player_from_row({"canonicalName": "Only Name", "position": "TE"})
    assert p.player_id == "Only Name"
