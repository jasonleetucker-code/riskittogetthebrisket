"""Golden team-plan payloads for the home "This week" panel (DYN10 item #5).

The JSON files under ``frontend/__tests__/fixtures/team-plan/`` are produced by
the REAL composer (``src/api/team_plan.py::compose_team_plan``) from the same
owner-shaped inputs ``tests/api/test_team_plan.py`` builds.  The frontend panel
renders them; this test fails when the composer's output drifts from them, so
the panel is never tested against a hand-invented contract.

Regenerate after an intended contract change::

    TEAM_PLAN_REGEN_FIXTURES=1 python -m pytest tests/api/test_team_plan_frontend_fixtures.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.api.team_plan import OwnerRead
from tests.api.test_team_plan import (
    _compose,
    _gameplan,
    _perfect,
    _room,
    _roster_intel,
    _suggestions,
    _target,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "frontend" / "__tests__" / "fixtures" / "team-plan"
)

_STALE = {
    "state": "stale",
    "source": "last_good",
    "fetchedAt": "2026-11-20T18:00:00+00:00",
    "ageHours": 30.5,
    "maxAgeHours": 6.0,
}


def _actions_plan() -> dict:
    """Every owner answered: buy targets, a sell-high, waiver moves, an aging room."""
    intel = _roster_intel([_room("QB", True)])
    # The weakness owner's real block also publishes ``urgentPositions``
    # (``TeamWeakness.to_dict``); the panel reads that list, never a level cut.
    intel["team"]["weakness"]["urgentPositions"] = ["TE"]
    return _compose(roster_intelligence=OwnerRead(payload=intel))


def _incomplete_stale_plan() -> dict:
    """Cold caches, stale rosters, an unmeasured age room and no actions."""
    unmeasured = {**_room("DB", False), "valueWeightedAge": None, "ageVsLeagueMedian": None}
    intel = _roster_intel([_room("QB", False), unmeasured])
    intel["team"]["strength"] = {"total": 30000.0, "leagueRank": None}
    intel["team"]["agePortfolio"]["valueWeightedCoreAge"] = None
    return _compose(
        roster_freshness=_STALE,
        posture=OwnerRead(reason="league_bundle_not_warm"),
        roster_intelligence=OwnerRead(payload=intel),
        buy_targets=OwnerRead(reason="gameplan_targets_not_warm"),
        sell_high=OwnerRead(payload=_suggestions([], reason="no_need_positions")),
        waivers=OwnerRead(reason="perfect_waivers_not_warm"),
        draft_capital=OwnerRead(reason="draft_capital_not_warm"),
    )


def _do_nothing_plan() -> dict:
    """Every owner-backed kind assessed and empty."""
    return _compose(
        buy_targets=OwnerRead(payload=_gameplan([_target("x", recommended=False)])),
        sell_high=OwnerRead(payload=_suggestions([], reason="no_need_positions")),
        waivers=OwnerRead(payload=_perfect([])),
        roster_intelligence=OwnerRead(payload=_roster_intel([_room("QB", False)])),
    )


CASES = {
    "plan-actions.json": _actions_plan,
    "plan-incomplete-stale.json": _incomplete_stale_plan,
    "plan-do-nothing.json": _do_nothing_plan,
}


def _render(payload: dict) -> str:
    # Key order is the composer's own (the wire order FastAPI serves), not sorted.
    return json.dumps(payload, indent=2) + "\n"


@pytest.mark.parametrize("name", sorted(CASES))
def test_frontend_fixture_matches_the_composer(name):
    expected = _render(CASES[name]())
    path = FIXTURE_DIR / name
    if os.environ.get("TEAM_PLAN_REGEN_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")
    assert path.exists(), f"missing {path}; regenerate with TEAM_PLAN_REGEN_FIXTURES=1"
    assert path.read_text(encoding="utf-8") == expected, (
        f"{name} drifted from compose_team_plan; regenerate with TEAM_PLAN_REGEN_FIXTURES=1 "
        "and re-check the panel's frontend tests"
    )


def test_fixtures_cover_each_plan_state():
    states = {name: CASES[name]()["planState"] for name in CASES}
    assert states == {
        "plan-actions.json": "actions",
        "plan-incomplete-stale.json": "incomplete",
        "plan-do-nothing.json": "do_nothing",
    }
