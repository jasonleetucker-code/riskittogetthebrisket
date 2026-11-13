"""``match_team`` resolves the /draft workspace's team names (website audit,
2026-11-12).

The draft workspace's teams come from ``/api/draft-capital``, which names them
by their Sleeper TEAM name; the contract's ``sleeper.teams[].name`` is the
manager's display name.  Measured on the dynasty_main board: 11 of 12
draft-capital names answered ``unknown_team`` from
``/api/draft/roster-context``, so Perfect Draft vanished for every team except
the one whose two names coincide.
"""

from __future__ import annotations

from src.draft.context import match_team

TEAMS = [
    {"name": "Jason", "sleeperTeamName": "Medical Murrayjuana", "ownerId": "4684", "roster_id": 1},
    {"name": "Ed", "sleeperTeamName": "ShitbowlChampion ", "ownerId": "7114", "roster_id": 2},
    {"name": "schoeppeya", "sleeperTeamName": "schoeppeya", "ownerId": "1393", "roster_id": 12},
    # A display name that equals ANOTHER team's Sleeper team name.
    {
        "name": "Medical Murrayjuana",
        "sleeperTeamName": "Other Team",
        "ownerId": "9999",
        "roster_id": 13,
    },
]


def _match(name):
    return match_team(TEAMS, owner_id=None, roster_id=None, team_name=name)


def test_a_draft_capital_team_name_resolves_to_its_team():
    assert _match("ShitbowlChampion ")["ownerId"] == "7114"
    # Whitespace / case drift between the feed and the contract is tolerated.
    assert _match("shitbowlchampion")["ownerId"] == "7114"


def test_the_display_name_still_resolves_and_keeps_precedence():
    assert _match("Ed")["ownerId"] == "7114"
    # "Medical Murrayjuana" is one team's display name AND another's Sleeper
    # team name: the display name wins, exactly as before.
    assert _match("Medical Murrayjuana")["ownerId"] == "9999"


def test_owner_id_still_wins_over_any_name():
    t = match_team(TEAMS, owner_id="4684", roster_id=None, team_name="Ed")
    assert t["ownerId"] == "4684"


def test_an_unknown_name_is_still_refused_never_a_fallback():
    assert _match("Not A Team") is None
    assert _match("") is None


def test_teams_without_a_sleeper_team_name_are_unaffected():
    assert match_team(
        [{"name": "Solo", "ownerId": "1"}], owner_id=None, roster_id=None, team_name="Solo"
    )
    assert (
        match_team(
            [{"name": "Solo", "ownerId": "1"}], owner_id=None, roster_id=None, team_name="Other"
        )
        is None
    )


def test_a_sleeper_team_name_two_teams_share_resolves_to_neither():
    # Sleeper allows duplicate team names: the name then identifies no team,
    # and the first match must not be handed back as if it did.
    twins = [
        {"name": "A", "sleeperTeamName": "Same", "ownerId": "1"},
        {"name": "B", "sleeperTeamName": "Same", "ownerId": "2"},
    ]
    assert match_team(twins, owner_id=None, roster_id=None, team_name="Same") is None
    # Each team is still reachable by its own display name.
    assert match_team(twins, owner_id=None, roster_id=None, team_name="B")["ownerId"] == "2"
