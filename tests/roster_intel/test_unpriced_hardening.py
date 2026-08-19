"""Unpriced players must not crash — and must not become zero (F7).

Integration's finding 3.  ``roster_player_from_row`` widened
``ros_value`` to ``float | None`` (that is the missing-is-never-zero
repair) without hardening the ~10 downstream sites that do
``p.ros_value > 0`` / ``max(0.0, …)`` / ``sum(…)``.  Measured: a row
omitting ``rosValue`` makes ``position_marginals`` and
``analyze_roster`` raise ``TypeError`` on this branch where ``main``
returned a number.

Not reachable today — both production callers are fed ``fullRoster``
rows that always carry a numeric ``rosValue`` — so the semantics are
right and the guards are missing.  There are two wrong ways to add
them, and this file pins against both:

* **crash** — a roster containing one unpriceable player takes down
  every metric for the whole team;
* **``or 0.0``** — the coercion C2-U1 retired, which would make an
  unknown player a real, assignable, worthless one and quietly drag
  every aggregate down.

The right answer is the one the lineup solver already uses: exclude him
from the arithmetic and REPORT him.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from src.ros.lineup import RosterPlayer

REPO = pathlib.Path(__file__).resolve().parents[2]

_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]


def P(pid, pos, val):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=val)


def _pool(with_unpriced: bool):
    pool = [
        P("QB1", "QB", 90.0),
        P("RB1", "RB", 80.0),
        P("RB2", "RB", 70.0),
        P("WR1", "WR", 85.0),
        P("WR2", "WR", 75.0),
        P("TE1", "TE", 60.0),
        P("RB3", "RB", 40.0),
    ]
    if with_unpriced:
        pool.append(P("MYSTERY", "WR", None))
    return pool


# ══ It must not crash ══════════════════════════════════════════════


def test_position_marginals_survives_an_unpriced_player():
    from src.roster_intel.marginal import position_marginals

    clean = position_marginals(_pool(False), _SLOTS)
    withunp = position_marginals(_pool(True), _SLOTS)
    assert withunp.lineup_score == clean.lineup_score


def test_analyze_roster_survives_an_unpriced_player():
    from src.roster_intel.engine import analyze_roster

    out = analyze_roster("owner-1", _pool(True), _SLOTS)
    assert out is not None


@pytest.mark.parametrize("fn_name", ["position_marginals", "absence_impacts"])
def test_marginal_entry_points_survive_an_all_unpriced_roster(fn_name):
    """The degenerate case: nothing is priced. It must answer, not raise
    — and it must not answer as though every player were worth zero."""
    import src.roster_intel.marginal as m

    pool = [P("A", "QB", None), P("B", "RB", None)]
    getattr(m, fn_name)(pool, _SLOTS)


# ══ …and it must not silently value them at zero ═══════════════════


def test_an_unpriced_player_changes_no_value_aggregate():
    """THE property. Adding a player the board cannot price must not move
    a single number — not down (coerced to 0), not up. He is excluded
    from the arithmetic, exactly as the solver excludes him from slots."""
    from src.roster_intel.marginal import position_marginals

    clean = position_marginals(_pool(False), _SLOTS)
    withunp = position_marginals(_pool(True), _SLOTS)
    assert withunp.lineup_score == clean.lineup_score
    assert withunp.filled_slots == clean.filled_slots
    clean_by_pos = {
        pos: (m.marginal_points, m.clogger_value, m.priced) for pos, m in clean.by_position.items()
    }
    dirty_by_pos = {
        pos: (m.marginal_points, m.clogger_value, m.priced)
        for pos, m in withunp.by_position.items()
    }
    for pos, values in clean_by_pos.items():
        assert dirty_by_pos.get(pos) == values, pos


def test_a_real_zero_is_still_a_real_value():
    """``0.0`` supplied explicitly is a player who is ASSIGNABLE and
    contributes nothing.  ``None`` is a player who cannot be assigned at
    all.  Excluding the real zero along with the unknown would be the
    same conflation in the other direction, so the crisp test is the
    solver: one gets a slot, the other does not.
    """
    from src.ros.lineup import assign_lineup

    zero = assign_lineup([P("ZERO", "QB", 0.0)], ["QB"])
    assert zero.starter_ids == {"ZERO"}
    assert zero.unpriced_ids == frozenset()

    unknown = assign_lineup([P("MYSTERY", "QB", None)], ["QB"])
    assert unknown.starter_ids == set()
    assert unknown.unpriced_ids == frozenset({"MYSTERY"})
    assert unknown.unfilled_slots == ["QB"]


def test_roster_membership_counts_an_unpriced_player_but_his_value_does_not():
    """Membership is real even when value is not — the same rule
    ``rosteredCount`` follows on the endpoint.  What must not move is
    any VALUE aggregate."""
    from src.roster_intel.marginal import position_marginals

    clean = position_marginals(_pool(False), _SLOTS)
    withunp = position_marginals(_pool(True), _SLOTS)
    wr_clean, wr_unp = clean.by_position["WR"], withunp.by_position["WR"]
    assert wr_unp.rostered == wr_clean.rostered + 1  # he is on the roster
    assert wr_unp.priced == wr_clean.priced  # …and carries no value
    assert wr_unp.marginal_points == wr_clean.marginal_points
    assert wr_unp.clogger_value == wr_clean.clogger_value


# ══ Structural: the retired coercion stays retired ═════════════════


_HARDENED = ("engine.py", "window.py", "profiles.py", "marginal.py")


def test_no_hardened_module_reintroduces_the_or_zero_coercion():
    """``float(p.ros_value or 0.0)`` is the exact expression C2-U1
    retired from the owner. Re-adding it here to dodge the TypeError
    would move the defect rather than fix it.

    Docstrings are stripped first — these modules explain the rule in
    prose, and a guard that trips on its own explanation teaches people
    to stop explaining."""
    for name in _HARDENED:
        tree = ast.parse((REPO / "src/roster_intel" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                ):
                    body[0].value.value = ""
        source = ast.unparse(tree)
        assert "ros_value or 0" not in source, name
        assert "ros_value or 0.0" not in source, name
