"""Owner correction 2026-09-29: an award record requirement is ".500 OR BETTER".

For any award that actually has a record eligibility requirement, a franchise
qualifies on record when its official regular-season winning percentage is
>= .500 (exactly .500 counts; below does not). Today that is League MVP only;
its separate playoff-field requirement is unchanged. Manager of the Year has
NO record gate and must not gain one. Missing or zero-game records never
qualify from a fabricated .500.
"""

from __future__ import annotations

import pytest

from src.public_league import awards
from tests.public_league.test_league_mvp_team_success_gate import OWNERS, build, pids, race

# Everyone in the field (playoff_teams=6) so only the RECORD half decides.
BASE = {1: (1, 3), 2: (2, 2), 3: (4, 0), 4: (3, 1), 5: (3, 1), 6: (0, 4)}


def _gate(records, *, ties=None, playoff_teams=6):
    """Run the real gate over a season whose roster records are given."""
    from tests.public_league import test_league_mvp_team_success_gate as fx

    captured = {}
    real = awards._league_mvp_gate

    def spy(snapshot, season):
        for roster in season.rosters:
            rid = roster["roster_id"]
            if ties and rid in ties:
                roster["settings"]["ties"] = ties[rid]
        out = real(snapshot, season)
        captured["gate"] = out
        return out

    awards._league_mvp_gate = spy
    try:
        full = dict(BASE)
        full.update(records)
        fx.build(records=full, playoff_teams=playoff_teams)
    finally:
        awards._league_mvp_gate = real
    return captured["gate"]


@pytest.mark.parametrize(
    ("wins", "losses", "eligible"),
    [
        (6, 6, True),  # exactly .500 counts
        (7, 7, True),
        (8, 8, True),
        (14, 14, True),  # median-game league: host counts both games per week
        (8, 6, True),  # above .500
        (6, 7, False),  # below .500
        (7, 8, False),
        (0, 1, False),
    ],
)
def test_the_record_criterion_is_500_inclusive(wins, losses, eligible):
    gate = _gate({2: (wins, losses)})
    team = gate["teams"]["owner-B"]
    assert team["eligible"] is eligible
    if eligible:
        assert team["reason"] is None
    else:
        assert team["reason"] == awards.MVP_RECORD_BELOW_500 == "team_record_below_500"


@pytest.mark.parametrize(
    ("record", "ties", "eligible"),
    [
        ((6, 6), 1, True),  # 6-6-1: (6 + 0.5) / 13 = .500 exactly
        ((6, 7), 1, False),  # 6-7-1: .464
        ((5, 5), 2, True),  # 5-5-2: .500
    ],
)
def test_ties_follow_the_canonical_standings_half_win(record, ties, eligible):
    gate = _gate({2: record}, ties={2: ties})
    assert gate["teams"]["owner-B"]["eligible"] is eligible


def test_zero_games_never_qualifies_from_a_fabricated_500():
    # No decided games: not eligible, and NOT called "below .500" either --
    # the record is unavailable, which is a different, truthful reason.
    gate = _gate({2: (0, 0)})
    team = gate["teams"]["owner-B"]
    assert team["eligible"] is False
    assert team["reason"] == awards.MVP_RECORD_UNAVAILABLE == "team_record_unavailable"
    assert team["reason"] != awards.MVP_RECORD_BELOW_500


def test_a_500_team_outside_the_playoff_field_is_still_ineligible():
    # Field = top 3 = C, D, E; B is exactly .500 and 4th.
    gate = _gate({}, playoff_teams=3)
    team = gate["teams"]["owner-B"]
    assert team["eligible"] is False
    assert team["reason"] == awards.MVP_OUTSIDE_PLAYOFF_FIELD


def test_a_500_team_inside_the_playoff_field_is_eligible_and_its_star_races():
    sec = build(playoff_teams=4)  # field = C, D, E, B — B is exactly .500
    r = race(sec, "league_mvp")
    assert "rb2" in pids(r["standings"])
    outside = {o["playerId"] for o in r["eligibility"]["outsideTheRace"]}
    assert "rb2" not in outside


def test_unknown_standings_stay_unverified_never_500():
    sec = build(playoff_teams=None)
    r = race(sec, "league_mvp")
    assert r["awaitingReason"] == awards.LEAGUE_MVP_ELIGIBILITY_UNVERIFIED


def test_manager_of_the_year_has_no_record_gate():
    # The .500 correction must not create a record gate where none exists:
    # below-.500 managers (A 1-3, F 0-4) stay in the Manager of the Year race.
    sec = build()
    moty = race(sec, "manager_of_the_year")
    owners = {s["ownerId"] for s in moty["standings"]}
    assert {"owner-A", "owner-F"} <= owners
    assert owners == set(OWNERS)
