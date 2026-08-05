"""The roster gate must accept every position the scraper can normalize.

``fetch_sleeper_rosters`` appends a rostered player's Sleeper id to
``team_player_ids`` and THEN checks his position against
``VALID_POSITIONS``.  A token that fails the check leaves an owned asset
on a roster with no entry in ``player_id_map``, ``id_to_player`` or
``position_map`` — an id nothing can resolve to a name, a position, or a
board row.

The set was missing SS, FS, OLB, ILB, MLB, NT and EDGE, all of which
Sleeper publishes and all of which ``_POS_FAMILY_MAP`` three hundred
lines above already knows how to collapse into a family.  Live cost was
one player of 666 rostered assets — Jaylinn Hawkins (7058, SS/BAL) —
and ``src/api/sleeper_overlay.py``'s Sleeper-dump name fallback exists
because of that one id (audit W06-F011).

``Dynasty Scraper.py`` cannot be imported here — it has a top-level
Playwright import that CI does not install — so this reads the real
file's constants with ``ast``, the same way
``tests/api/test_source_floor_invariant.py`` reads its floors.  Parsing
the shipped source is what makes this a test of production rather than
of a copy.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SCRAPER = Path(__file__).resolve().parents[2] / "Dynasty Scraper.py"


def _literal_assignment(name: str):
    """The literal value assigned to ``name`` anywhere in the module."""
    tree = ast.parse(_SCRAPER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                try:
                    return ast.literal_eval(node.value)
                except ValueError:
                    return None
    return None


@pytest.fixture(scope="module")
def family_map():
    value = _literal_assignment("_POS_FAMILY_MAP")
    assert isinstance(value, dict), "_POS_FAMILY_MAP is no longer a dict literal"
    return value


@pytest.fixture(scope="module")
def valid_positions():
    value = _literal_assignment("VALID_POSITIONS")
    assert isinstance(value, set), "VALID_POSITIONS is no longer a set literal"
    return value


def test_every_normalizable_position_is_accepted(family_map, valid_positions):
    missing = sorted(set(family_map) - valid_positions)
    assert missing == [], (
        "the roster gate drops position tokens the scraper can normalize: "
        f"{missing} — every rostered player carrying one is invisible to "
        "player_id_map / id_to_player / position_map"
    )


def test_the_gate_still_admits_team_defenses(valid_positions):
    """``DEF`` is not in the family map and must survive the sync."""
    assert "DEF" in valid_positions


def test_the_gate_does_not_admit_offensive_line(valid_positions):
    """The control.  Widening the gate must not turn into accepting
    everything — OL rows are quarantined downstream as
    ``unsupported_position`` and should never enter the maps."""
    assert not ({"OT", "OG", "C", "G", "T"} & valid_positions)
