"""Sport-aware athlete identity (DFS-§9-03): keys carry sport, a directory answers only
for its own sport, team codes are per sport, unresolved stays unresolved."""

from __future__ import annotations

import pytest

from src.identity.athletes import (
    REASON_NO_DIRECTORY_FOR_SPORT,
    REASON_SPORT_MISMATCH,
    REASON_UNKNOWN_SPORT,
    AthleteIdentityError,
    athlete_key,
    canonical_team,
    parse_athlete_key,
    resolve_athlete,
    sport_scoped_token,
)
from src.identity.resolution import build_sleeper_index, resolve_canonical_v2

# An NFL directory that happens to contain a name an NBA player also carries.
NFL_DIRECTORY = {
    "9001": {
        "full_name": "Jaylen Williams",
        "first_name": "Jaylen",
        "last_name": "Williams",
        "position": "WR",
        "team": "NYJ",
        "active": True,
    },
}


def test_an_nba_name_never_resolves_against_the_nfl_directory():
    index = build_sleeper_index(NFL_DIRECTORY)
    assert index.sport == "nfl"
    # The bare NFL ladder would happily answer — that is the hazard.
    assert resolve_canonical_v2(index, name="Jaylen Williams").sleeper_id == "9001"
    nba = resolve_athlete("nba", index, name="Jaylen Williams", position="PF", team="OKC")
    assert not nba.resolved and nba.sleeper_id is None
    assert nba.reason == REASON_SPORT_MISMATCH
    nhl = resolve_athlete("nhl", None, name="Jaylen Williams")
    assert not nhl.resolved and nhl.reason == REASON_NO_DIRECTORY_FOR_SPORT
    assert resolve_athlete("cricket", index, name="x").reason == REASON_UNKNOWN_SPORT


def test_nfl_resolution_is_exactly_the_canonical_ladder():
    index = build_sleeper_index(NFL_DIRECTORY)
    via_sport = resolve_athlete("nfl", index, name="Jaylen Williams", position="WR", team="NYJ")
    direct = resolve_canonical_v2(index, name="Jaylen Williams", position="WR", team="NYJ")
    assert via_sport == direct and via_sport.resolved


def test_identity_keys_carry_the_sport_and_never_collide_across_sports():
    nba = athlete_key("nba", "dailyfantasyfuel", "CAE5C")
    nfl = athlete_key("nfl", "dailyfantasyfuel", "CAE5C")
    assert nba != nfl
    assert parse_athlete_key(nba) == ("nba", "dailyfantasyfuel", "CAE5C")
    assert parse_athlete_key("athlete:xfl:a:b") is None
    assert sport_scoped_token("nhl", "D65D0") == "nhl-D65D0"
    with pytest.raises(AthleteIdentityError):
        athlete_key("nba", "dailyfantasyfuel", "bad id with spaces")
    with pytest.raises(AthleteIdentityError):
        athlete_key("curling", "x", "1")


def test_team_codes_are_per_sport_and_unknown_is_none():
    # WSH is the Wizards in the NBA (canonical WAS) and the Capitals in the NHL.
    assert canonical_team("nba", "WSH") == "WAS"
    assert canonical_team("nhl", "WSH") == "WSH"
    assert canonical_team("nhl", "WAS") == "WSH"
    # Provider spellings (ESPN / platform / DFF) land on one code per sport.
    assert {canonical_team("nba", c) for c in ("GS", "GSW")} == {"GSW"}
    assert {canonical_team("nba", c) for c in ("UTAH", "UTA")} == {"UTA"}
    assert {canonical_team("nba", c) for c in ("PHO", "PHX")} == {"PHX"}
    assert {canonical_team("nhl", c) for c in ("LA", "LAK")} == {"LAK"}
    assert {canonical_team("nhl", c) for c in ("TB", "TBL")} == {"TBL"}
    assert {canonical_team("nhl", c) for c in ("UTAH", "UTA")} == {"UTA"}
    # LV is a hockey team in the NHL table and unknown to the NBA table.
    assert canonical_team("nhl", "LV") == "VGK"
    assert canonical_team("nba", "LV") is None
    assert canonical_team("nba", "XYZ") is None and canonical_team("nhl", "") is None
    # NFL delegates to the NFL owner.
    assert canonical_team("nfl", "kc") == "KC"
