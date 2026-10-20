"""``GET /api/roster/intelligence`` measures the rosters the site serves.

Every page lists a league's teams from ``/api/data``, which splices the live
Sleeper teams overlay (≤ 15 min old) over the baked contract (≤ 2 h old, or
indefinitely old when a scrape fails).  The Team Strength ladder used to read
the BAKED block only, so after any membership change the /rosters page showed
two different team lists on one screen.

Measured 2026-10-20: dynasty_main roster 12 lost its owner on Sleeper between
the 23:58 UTC scrape and the next.  ``/api/data`` listed "Team 12"; the ladder
still ranked the departed manager "Blaine" and had no "Team 12" row
(E2E run 39348160535).  These tests pin that the ladder reads the same teams
overlay the rest of the site serves, and falls back to the baked block —
saying so — when the overlay is unavailable.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from tests.api.test_roster_intelligence import _contract


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "test_league",
                "leagues": [
                    {
                        "key": "test_league",
                        "displayName": "Test",
                        "sleeperLeagueId": "L-TEST",
                        "active": True,
                        "rosterSettings": {"teamCount": 4},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)

    baked = _contract(n_teams=4)
    monkeypatch.setattr(server, "latest_contract_data", baked)
    yield baked
    league_registry.reload_registry()


def _live_teams_with_orphan(baked):
    """The baked teams, except the last manager left: Sleeper's
    ``owner_id: null`` → ``ownerId: ""`` named ``Team <roster_id>``."""
    teams = [dict(t) for t in baked["sleeper"]["teams"]]
    teams[-1] = {**teams[-1], "ownerId": "", "name": "Team 4"}
    return teams


def _ladder(client, owner="o0"):
    res = client.get(f"/api/roster/intelligence?team={owner}")
    assert res.status_code == 200, res.text
    body = res.json()
    return body, [row["teamName"] for row in body["leagueContext"]]


def test_the_ladder_ranks_the_live_rosters_the_site_lists(env, monkeypatch):
    live = _live_teams_with_orphan(env)
    calls = []

    def fake_teams_overlay(**kw):
        calls.append(kw.get("sleeper_league_id"))
        return {"teams": live, "overlayFetchedAt": "2026-10-20T00:33:52+00:00"}

    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_teams_overlay", fake_teams_overlay)
    body, ladder = _ladder(TestClient(server.app))

    assert calls == ["L-TEST"]
    assert sorted(ladder) == sorted(t["name"] for t in live)
    assert "Team 4" in ladder
    assert "Team o3" not in ladder  # the departed manager is not still ranked
    assert body["rosterMembership"] == {
        "source": "live_overlay",
        "asOf": "2026-10-20T00:33:52+00:00",
    }
    # The baked global is never mutated by the splice.
    assert [t["name"] for t in server.latest_contract_data["sleeper"]["teams"]][-1] == "Team o3"


def test_no_overlay_falls_back_to_the_baked_rosters_and_says_so(env, monkeypatch):
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_teams_overlay", lambda **kw: None)
    body, ladder = _ladder(TestClient(server.app))
    assert sorted(ladder) == sorted(t["name"] for t in env["sleeper"]["teams"])
    assert body["rosterMembership"] == {"source": "contract", "asOf": None}


def test_an_overlay_failure_degrades_rather_than_failing_the_request(env, monkeypatch):
    def boom(**kw):
        raise RuntimeError("sleeper down")

    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_teams_overlay", boom)
    body, ladder = _ladder(TestClient(server.app))
    assert len(ladder) == 4
    assert body["rosterMembership"]["source"] == "contract"


def test_a_departed_owner_is_no_longer_a_team_in_the_league(env, monkeypatch):
    live = _live_teams_with_orphan(env)
    monkeypatch.setattr(
        server._sleeper_overlay,
        "fetch_sleeper_teams_overlay",
        lambda **kw: {"teams": live, "overlayFetchedAt": "2026-10-20T00:33:52+00:00"},
    )
    res = TestClient(server.app).get("/api/roster/intelligence?team=o3")
    assert res.status_code == 404
    assert res.json()["error"] == "team_not_found"
