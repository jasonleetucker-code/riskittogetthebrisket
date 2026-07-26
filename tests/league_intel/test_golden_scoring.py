"""LI-2 — golden validation: exact scorer vs Sleeper-awarded scores.

Fixtures are frozen real player-weeks from the 2025 season of this
league (previous_league_id 1180092661344120832, status: complete),
captured 2026-07-26 from:

* ``GET /v1/stats/nfl/regular/2025/{week}``          — raw stat lines
* ``GET /v1/league/{prev}/matchups/{week}``          — host-awarded
  ``players_points`` / ``starters_points`` / ``points``
* ``GET /v1/league/{prev}``                          — the 2025 scoring
  settings (rates differ from 2026; the key vocabulary is identical,
  so these fixtures pin the scoring MECHANICS at the host's own
  numbers)

The 2026 season had no scored weeks at capture time (offseason), so
2025 is the only host-awarded ground truth available.  Full
methodology + verdicts: docs/league-intelligence/SCORING_VALIDATION.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_intel.scorer import score_stat_line

FIXTURES = Path(__file__).parent / "fixtures"
TOL = 0.011  # host displays 2-decimal scores; see SCORING_VALIDATION.md


@pytest.fixture(scope="module")
def scoring_2025():
    return json.loads((FIXTURES / "scoring_settings_2025.json").read_text())


def _player_cases():
    cases = json.loads((FIXTURES / "golden_player_weeks.json").read_text())
    return [pytest.param(c, id=f"{c['archetype'].replace(' ', '-')}-{c['name']}") for c in cases]


@pytest.mark.parametrize("case", _player_cases())
def test_golden_player_week_matches_host_awarded_points(case, scoring_2025):
    bd = score_stat_line(case["statLine"], scoring_2025)
    assert bd.total_points == pytest.approx(case["expectedPoints"], abs=TOL), (
        f"{case['name']} ({case['archetype']}) week {case['week']}: "
        f"scored {bd.total_points:.3f}, host awarded {case['expectedPoints']}"
    )


def test_archetype_coverage_matches_spec():
    """The golden set must keep covering the spec's representative
    archetypes — shrinking it silently would weaken the validation."""
    cases = json.loads((FIXTURES / "golden_player_weeks.json").read_text())
    archetypes = {c["archetype"] for c in cases}
    required = {
        "pocket QB",
        "rushing QB",
        "sack-prone QB",
        "pick-six QB",
        "pass-catching RB",
        "possession WR",
        "deep-threat WR",
        "receiving TE",
        "kicker",
        "tackle LB",
        "edge rusher",
        "interior DL",
        "box safety",
        "ballhawk corner",
    }
    assert required <= archetypes
    positions = {c["position"] for c in cases}
    assert {"QB", "RB", "WR", "TE", "K", "LB", "DE", "DT", "DB"} <= positions


def test_pick_six_fixture_confirms_stacking(scoring_2025):
    """The frozen pick-six week must actually carry both keys and
    reconcile only when BOTH pass_int and pass_int_td are charged."""
    cases = json.loads((FIXTURES / "golden_player_weeks.json").read_text())
    case = next(c for c in cases if c["archetype"] == "pick-six QB")
    line = case["statLine"]
    assert line["pass_int"] >= 1 and line["pass_int_td"] >= 1
    with_both = score_stat_line(line, scoring_2025).total_points
    without_td_key = score_stat_line(
        {k: v for k, v in line.items() if k != "pass_int_td"}, scoring_2025
    ).total_points
    assert with_both == pytest.approx(case["expectedPoints"], abs=TOL)
    assert without_td_key != pytest.approx(case["expectedPoints"], abs=TOL)


@pytest.mark.parametrize("idx", [0, 1])
def test_golden_team_week_total(idx, scoring_2025):
    """Full-team validation: score every starter's raw stat line and
    sum → must equal the host's matchup ``points`` (best-ball optimal
    lineup as awarded by Sleeper)."""
    teams = json.loads((FIXTURES / "golden_team_weeks.json").read_text())
    team = teams[idx]
    computed = 0.0
    for pid in team["starters"]:
        line = team["statLines"].get(pid)
        if line is None:
            continue  # empty starter slot (host awards 0)
        computed += score_stat_line(line, scoring_2025).total_points
    # Sum of per-player 0.01-rounded scores: tolerance scales with
    # starter count.
    assert computed == pytest.approx(team["expectedTeamPoints"], abs=0.006 * len(team["starters"]))
    # Host self-consistency: starters_points sums to points exactly.
    assert sum(team["startersPoints"]) == pytest.approx(team["expectedTeamPoints"], abs=0.01)
