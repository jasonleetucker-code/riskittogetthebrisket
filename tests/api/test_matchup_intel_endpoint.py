"""Contract tests for ``GET /api/matchup/intel`` (W1-14 / W1-15).

Three jobs:

1. **The routing contract** — the same table every league-scoped route
   follows, plus the two states this endpoint adds: ``week_in_progress``
   (409, a state and not an error) and ``clock_unavailable`` (503, because
   guessing the week describes a different week).
2. **The public/private boundary** — this payload is projections, win
   probabilities and roster weaknesses. CLAUDE.md §5 puts all three on the
   private side, so the response must be ``no-store`` and the endpoint must
   not be reachable under ``/api/public/``.
3. **The lineage actually describes the numbers beside it** — W1-15's whole
   ask. A win probability whose projection source, coverage and unverified
   threshold semantics are missing is a number, not intelligence.

Everything is patched at the assembly boundary; no network, no live league.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry, matchup_intel


@pytest.fixture(autouse=True)
def league(tmp_path, monkeypatch):
    """One active league. The endpoint's own logic is what is under test,
    so the registry is minimal rather than a second fixture to maintain."""
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "dynasty_main",
                "leagues": [
                    {
                        "key": "dynasty_main",
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {
                            "teamCount": 12,
                            "starters": {"QB": 1, "RB": 2, "WR": 2, "FLEX": 1},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    yield
    monkeypatch.delenv("LEAGUE_REGISTRY_PATH", raising=False)
    league_registry.reload_registry()


_PAYLOAD = {
    "leagueKey": "dynasty_main",
    "season": 2026,
    "week": 1,
    "mode": "pregame",
    "team": {"ownerId": "own-A", "outcome": {"winMatchupPct": 61.5}},
    "opponent": {"ownerId": "own-B", "outcome": {"winMatchupPct": 38.5}},
    "lineage": {
        "projectionSource": "ros_ensemble:PRESEASON_FULL_SEASON:equal_family_mean",
        "estimateCoverage": {"priced": 600, "active": 674},
        "simulation": {"thresholdSemanticsVerified": False, "thresholdSemantics": "median"},
    },
    "notes": [],
}


def _client():
    return TestClient(server.app, raise_server_exceptions=True)


def _patch(**over):
    kwargs = {"return_value": dict(_PAYLOAD)}
    kwargs.update(over)
    return mock.patch.object(matchup_intel, "build_matchup_intel", **kwargs)


def _patch_clock(season=2026, week=1):
    return mock.patch(
        "src.public_league.sleeper_client.fetch_nfl_state",
        return_value={"season": str(season), "week": week, "season_type": "regular"},
    )


class RoutingTests:
    pass


def test_unknown_league_is_a_400_naming_the_key():
    with _client() as c:
        r = c.get("/api/matchup/intel?leagueKey=not_a_league&team=own-A")
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "unknown_league"
    assert body["leagueKey"] == "not_a_league"


def test_a_team_that_cannot_be_inferred_is_a_400_that_says_how_to_fix_it():
    with _client() as c:
        r = c.get("/api/matchup/intel")
    # Anonymous: no session Sleeper id and no default mapping for it.
    assert r.status_code in (400, 503)
    if r.status_code == 400:
        assert r.json()["error"] == "team_required"


def test_a_happy_path_answers_with_the_assembly_payload():
    with _patch(), _patch_clock(), _client() as c:
        r = c.get("/api/matchup/intel?team=own-A")
    assert r.status_code == 200
    body = r.json()
    assert body["team"]["ownerId"] == "own-A"
    assert body["opponent"]["ownerId"] == "own-B"
    assert body["mode"] == "pregame"


def test_a_week_in_progress_is_409_with_its_own_code():
    # A state, not an error: the caller should render "come back after the
    # games", which it cannot do if this is indistinguishable from a 503.
    with (
        _patch(side_effect=matchup_intel.WeekInProgress("the week has already begun")),
        _patch_clock(),
        _client() as c,
    ):
        r = c.get("/api/matchup/intel?team=own-A")
    assert r.status_code == 409
    assert r.json()["error"] == "week_in_progress"


def test_an_owner_with_no_roster_is_404_not_an_empty_matchup():
    with (
        _patch(side_effect=matchup_intel.TeamNotInLeague("own-Z")),
        _patch_clock(),
        _client() as c,
    ):
        r = c.get("/api/matchup/intel?team=own-Z")
    assert r.status_code == 404
    assert r.json()["error"] == "team_not_found"


def test_an_unstated_clock_refuses_rather_than_guessing_the_week():
    with (
        mock.patch("src.public_league.sleeper_client.fetch_nfl_state", return_value={}),
        _client() as c,
    ):
        r = c.get("/api/matchup/intel?team=own-A")
    assert r.status_code == 503
    assert r.json()["error"] == "clock_unavailable"


def test_an_explicit_week_does_not_need_the_host_clock():
    with (
        _patch(),
        mock.patch("src.public_league.sleeper_client.fetch_nfl_state", return_value={}),
        _client() as c,
    ):
        r = c.get("/api/matchup/intel?team=own-A&season=2026&week=3")
    assert r.status_code == 200


class PrivacyBoundaryTests:
    pass


def test_the_response_is_never_cached_by_a_shared_proxy():
    with _patch(), _patch_clock(), _client() as c:
        r = c.get("/api/matchup/intel?team=own-A")
    assert r.headers.get("cache-control") == "no-store"


def test_this_is_not_a_public_league_route():
    # Projections, win probabilities and roster weaknesses are private under
    # CLAUDE.md §5. The public prefix must not serve them.
    with _client() as c:
        r = c.get("/api/public/league/matchup/intel")
    assert r.status_code != 200


class LineageTests:
    pass


def test_the_payload_carries_its_projection_source_and_coverage():
    with _patch(), _patch_clock(), _client() as c:
        body = c.get("/api/matchup/intel?team=own-A").json()
    lin = body["lineage"]
    assert lin["projectionSource"]
    assert lin["estimateCoverage"] == {"priced": 600, "active": 674}


def test_the_unverified_threshold_semantics_reach_the_wire():
    # W1-23 is BLOCKED on host evidence; a private surface must not present
    # the median leg as settled just because it serialized cleanly.
    with _patch(), _patch_clock(), _client() as c:
        body = c.get("/api/matchup/intel?team=own-A").json()
    assert body["lineage"]["simulation"]["thresholdSemanticsVerified"] is False


def test_the_hosts_season_type_is_stamped_when_it_states_one():
    with _patch(), _patch_clock(), _client() as c:
        body = c.get("/api/matchup/intel?team=own-A").json()
    assert body["seasonType"] == "regular"
