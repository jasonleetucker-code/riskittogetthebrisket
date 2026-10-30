"""Roster Construction V1 on a REAL league shape: dynasty_main 2025, weeks 1-17.

``tests/league_intel/fixtures/matchups_2025`` holds every roster's ``players``
and ``players_points`` for ten real teams (no host ``starters`` / ``points``
and no league object).  The 2026 registry starters are supplied as a labelled
assumption, so this pins invariants and cost, not host parity.  Host parity is
covered by the synthetic fixtures (``test_construction.py``), whose host lineups
are solver-awarded.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.api import roster_construction_api as api
from src.roster_intel import construction as rc
from tests.roster_intel.rc_support import DYNASTY_MAIN_SLOTS

FIX = Path(__file__).resolve().parents[1] / "league_intel" / "fixtures" / "matchups_2025"


@pytest.fixture(scope="module")
def season():
    meta = json.loads((FIX / "players_meta.json").read_text(encoding="utf-8"))
    weeks = {
        w: [
            rc.TeamWeekIn(
                roster_id=e["roster_id"], roster=tuple(e["players"]), points=e["players_points"]
            )
            for e in json.loads((FIX / f"w{w}.json").read_text(encoding="utf-8"))
        ]
        for w in range(1, 18)
    }
    players = {
        p: rc.PlayerMeta(
            position=m.get("position") or "",
            fantasy_positions=tuple(m.get("fantasy_positions") or ()),
        )
        for p, m in meta.items()
    }
    si = rc.SeasonInput(
        season="2025",
        slots=tuple(DYNASTY_MAIN_SLOTS),
        slot_source="assumption:2026_registry_starters",
        lineup_mode=rc.LINEUP_BEST_BALL,
        weeks=weeks,
        players=players,
        marginal_unavailable_reason="fixture_has_no_host_lineups",
    )
    t0 = time.perf_counter()
    ls = rc.compute_league_season(si, api.load_priors())
    return ls, time.perf_counter() - t0


def test_real_shape_every_team_week_solves_and_groups_add_up(season):
    ls, _ = season
    assert ls.team_ids == list(range(1, 11))
    for wk in ls.included_weeks:
        for rid, sol in ls.solutions[wk].items():
            assert sol.valid and sol.parity == rc.PARITY_UNVERIFIED
            ids = [pid for _i, _s, pid, _p in sol.assigned]
            assert len(ids) == len(set(ids))
            assert set(ids) <= set(sol.roster)
    for rid in ls.team_ids:
        total = sum(ls.production[rid][g]["points"] for g in ls.groups)
        lineups = sum(ls.solutions[wk][rid].score for wk in ls.included_weeks)
        assert total == pytest.approx(lineups, abs=0.1)


def test_real_shape_idp_slots_are_filled_by_family_or_hybrid(season):
    ls, _ = season
    for wk in ls.included_weeks:
        for sol in ls.solutions[wk].values():
            for _i, slot, pid, _p in sol.assigned:
                if slot in ("DL", "LB", "DB"):
                    meta = ls.si.players[pid]
                    fams = {rc.group_of(rc.PlayerMeta(position=p)) for p in meta.fantasy_positions}
                    fams.add(rc.group_of(meta))
                    assert slot in fams


def test_real_shape_team_view_is_complete_and_honest(season):
    ls, _ = season
    t0 = time.perf_counter()
    view = rc.build_team_view(ls, 1, rc.ValueInput(available=False, reason="fixture"))
    elapsed = time.perf_counter() - t0
    assert {p["position"] for p in view["positions"]} == set(ls.groups)
    for pos in view["positions"]:
        assert pos["production"]["of"] == 10
        assert pos["value"] == {"available": False, "reason": "fixture"}
    rows = view["players"]
    assert rows and all(r["starts"]["value"] <= r["starts"]["of"] for r in rows)
    h = [r["hypotheticalStarts"] for r in rows]
    assert sum(x["of"] for x in h) > 0
    assert all(r["marginalPoints"]["value"] is None for r in rows)
    # Measured cost on the real 10-team, 17-week shape (see the PR record).
    assert elapsed < 10


def test_real_shape_compute_cost(season):
    _ls, elapsed = season
    assert elapsed < 30  # measured ~1.7 s on the dev box; generous for CI
