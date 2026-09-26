"""Game Day team switcher — any roster's perspective, never another league's.

Owner directive 2026-09-25 (#1335): Game Day must switch between every team
in the SELECTED league and show the intelligence from that team's side.

The backend already owns the answer: one league-week render holds every
roster's side (`render_league`), and `compose_team_payload` selects one of
them plus its scheduled opponent.  So switching perspective is a selection,
never a second simulation.  What is pinned here:

1. **Perspective reverses, not relabels** — served from the SAME collector
   generation, the opponent's payload carries the opponent's own numbers
   (win chances swap, the margin negates), read from the committed fixtures
   that `test_game_day_ui_fixtures.py` pins byte-equal to the endpoint.
2. **`leagueTeams` is the rendered league and nothing else** — every roster
   exactly once, from the render the payload was composed from.
3. **League isolation** — an owner who holds no roster in THIS render is a
   `TeamNotInLeague` refusal carrying THIS league's rosters; it never
   resolves against another league's render, even one that holds them.
4. **The shared render is never mutated** — it may be a cached generation
   every viewer is served from.
"""

from __future__ import annotations

import copy
import json
from unittest import mock

import pytest

from src.api import matchup_intel
from tests.game_day import ui_payloads


def _fixture(name: str) -> dict:
    return json.loads(ui_payloads.fixture_path(name).read_text(encoding="utf-8"))


# ── 1. Perspective, from real served payloads ───────────────────────────


def test_the_opponent_perspective_is_the_opponents_own_answer():
    mine = _fixture("halftime")
    theirs = _fixture("halftime-opponent")
    # One league, one week, one generation: the switch recomputed nothing.
    for key in ("leagueKey", "season", "week", "mode"):
        assert mine[key] == theirs[key]
    assert mine["freshness"]["generationId"] == theirs["freshness"]["generationId"]
    # The sides swap...
    assert theirs["team"]["ownerId"] == mine["opponent"]["ownerId"]
    assert theirs["opponent"]["ownerId"] == mine["team"]["ownerId"]
    assert theirs["team"]["rosterId"] == str(ui_payloads.OPPONENT_ROSTER)
    # ...and so do the numbers: reversed, not relabelled.
    m, t = mine["team"]["outcome"], theirs["team"]["outcome"]
    assert t["winMatchupPct"] == mine["opponent"]["outcome"]["winMatchupPct"]
    assert theirs["opponent"]["outcome"]["winMatchupPct"] == m["winMatchupPct"]
    assert t["winMatchupPct"] != m["winMatchupPct"]
    assert t["expectedMarginVsOpponent"] == pytest.approx(-m["expectedMarginVsOpponent"])
    assert t["expectedFinalBestBall"] == mine["opponent"]["outcome"]["expectedFinalBestBall"]
    # The slate is ordered from the selected side: its own players first.
    sides = [p["side"] for g in theirs["nflSlate"]["games"] for p in g["players"]]
    team_ids = {
        p["playerId"]
        for g in theirs["nflSlate"]["games"]
        for p in g["players"]
        if p["side"] == "team"
    }
    mine_opp_ids = {
        p["playerId"]
        for g in mine["nflSlate"]["games"]
        for p in g["players"]
        if p["side"] == "opponent"
    }
    assert "team" in sides
    assert team_ids == mine_opp_ids


def test_every_served_payload_lists_the_whole_league_once():
    for name in ui_payloads.SCENARIOS:
        payload = _fixture(name)
        teams = payload["leagueTeams"]
        roster_ids = [t["rosterId"] for t in teams]
        assert len(roster_ids) == len(set(roster_ids)) == 12, name
        owners = {t["ownerId"] for t in teams}
        # The selected team and its opponent are both in the list.
        assert payload["team"]["ownerId"] in owners, name
        if payload.get("opponent"):
            assert payload["opponent"]["ownerId"] in owners, name
        for t in teams:
            assert set(t) == {"ownerId", "rosterId", "teamName", "displayName"}, name


# ── 2-4. Composition over a synthetic render ────────────────────────────


def _render(league_key: str, owners: dict[str, str | None], opponents: dict[str, str]):
    """A minimal league render: roster id -> owner id, plus the schedule."""
    sides = {
        rid: {
            "ownerId": oid,
            "rosterId": rid,
            "teamName": f"{league_key} team {rid}",
            "displayName": f"mgr {rid}",
            "outcome": {"winMatchupPct": float(rid)},
        }
        for rid, oid in owners.items()
    }
    return {
        "shared": {"leagueKey": league_key, "season": 2026, "week": 3, "mode": "live"},
        "lineage": {},
        "notes": [],
        "sides": sides,
        "opponents": opponents,
        "ownerToRoster": {oid: rid for rid, oid in owners.items() if oid},
        "slate": {"base": {"games": []}, "entries": {}},
    }


@pytest.fixture(autouse=True)
def _no_archive_io():
    with mock.patch.object(
        matchup_intel, "_archive_evidence", return_value={"state": "not_captured"}
    ):
        yield


MAIN = _render(
    "dynasty_main",
    {"1": "own-a", "2": "own-b", "3": "own-c", "4": None},
    {"1": "2", "2": "1", "3": "4", "4": "3"},
)
NEW = _render("dynasty_new", {"1": "own-x", "2": "own-y"}, {"1": "2", "2": "1"})


@pytest.mark.parametrize("owner,roster,opponent", [("own-a", "1", "2"), ("own-b", "2", "1")])
def test_any_roster_resolves_with_its_own_opponent(owner, roster, opponent):
    p = matchup_intel.compose_team_payload(MAIN, owner_id=owner)
    assert p["leagueKey"] == "dynasty_main"
    assert p["team"]["rosterId"] == roster
    assert p["team"]["ownerId"] == owner
    assert p["opponent"]["rosterId"] == opponent
    assert p["team"]["outcome"]["winMatchupPct"] == float(roster)


def test_a_team_facing_an_unmanaged_roster_still_resolves():
    p = matchup_intel.compose_team_payload(MAIN, owner_id="own-c")
    assert p["opponent"]["rosterId"] == "4"
    assert p["opponent"]["ownerId"] is None


def test_league_teams_is_this_render_only_and_stable():
    teams = matchup_intel.compose_team_payload(MAIN, owner_id="own-a")["leagueTeams"]
    assert [t["rosterId"] for t in teams] == ["1", "2", "3", "4"]
    assert all(t["teamName"].startswith("dynasty_main") for t in teams)
    # An unmanaged roster is listed (it IS in the league) but not addressable.
    assert teams[3]["ownerId"] is None


def test_an_owner_from_another_league_is_refused_with_this_leagues_teams():
    # own-x holds a roster in dynasty_new — that must not make it resolvable
    # against dynasty_main, and the refusal offers only dynasty_main's teams.
    with pytest.raises(matchup_intel.TeamNotInLeague) as exc:
        matchup_intel.compose_team_payload(MAIN, owner_id="own-x")
    teams = exc.value.league_teams
    assert {t["rosterId"] for t in teams} == {"1", "2", "3", "4"}
    assert all(t["teamName"].startswith("dynasty_main") for t in teams)
    assert "own-x" not in {t["ownerId"] for t in teams}
    # ...while the league that does hold it answers for its own league.
    assert matchup_intel.compose_team_payload(NEW, owner_id="own-x")["leagueKey"] == "dynasty_new"


@pytest.mark.parametrize("owner", ["own-zzz", "", "None", "4"])
def test_an_unknown_or_rosterless_owner_is_refused(owner):
    with pytest.raises(matchup_intel.TeamNotInLeague):
        matchup_intel.compose_team_payload(MAIN, owner_id=owner)


def test_switching_never_mutates_the_shared_render():
    render = copy.deepcopy(MAIN)
    before = copy.deepcopy(render)
    for owner in ("own-a", "own-b", "own-c"):
        payload = matchup_intel.compose_team_payload(render, owner_id=owner)
        payload["team"]["mutated"] = True
        payload["leagueTeams"].append({"rosterId": "99"})
    assert render == before
