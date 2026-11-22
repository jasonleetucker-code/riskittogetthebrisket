"""DYN10 waiver correctness — B1 (protections) and B3 (roster freshness).

B1.  /waivers builds "Best Add/Drop Moves" and "Best Unique Upgrade Set"
from the team's canonical cut ladder (``GET /api/roster/intelligence
?droppability=1`` → ``team_droppability`` → ``build_cut_ladder``).  That
ladder ignored the user's persistent trade protections, so the greedy lists
could propose dropping a player the Perfect Waivers panel on the SAME page
listed as "Protected, never proposed as drops".

The repair is a protection-aware ladder: protected players are never cut
candidates, and the ladder is REBUILT over the rest through the owner's own
``candidate_ids`` seam — not a client-side skip of the protected rung, which
would miss a player the unconstrained ladder blocked only because a
protected one had been released first.  Protections are private: they apply
only to the requesting user's OWN team and never reach a payload served to
anyone else.

B3.  The waiver payloads said ``rosterSource: "contract"`` with no
staleness flag, so a roster block restored from a last-good snapshot could
list a free agent claimed since.  ``rosterFreshness`` now carries the one
roster-freshness reader's verdict (``current`` / ``stale`` / ``unknown``).
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry, user_kv
from src.api import roster_intelligence as ri
from src.api.roster_freshness import served_roster_freshness
from src.roster_intel.droppability import league_droppability, team_droppability
from src.trade.constraints import UNRESOLVED, resolve_constraints

URL = "/api/roster/intelligence"


def _row(pid, name, pos, value, team="XX"):
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": pos,
        "team": team,
        "rankDerivedValue": value,
        "sourceCount": 3,
        "assetClass": "offense",
    }


def _contract(league_key="main"):
    """A league starting QB + WR + WR.  ``me`` rosters three WRs, so the
    unconstrained ladder releases the cheapest WR and then has to KEEP the
    other two — Bench WR is blocked only because Deep WR went first."""
    return {
        "meta": {"leagueKey": league_key},
        "playersArray": [
            _row("qb1", "Star QB", "QB", 8000, "BUF"),
            _row("wr1", "Star WR", "WR", 7000, "MIN"),
            _row("wr2", "Bench WR", "WR", 3000, "CIN"),
            _row("wr3", "Deep WR", "WR", 400, "CIN"),
            _row("fa1", "Free WR", "WR", 2600, "DAL"),
            _row("o1", "Other QB", "QB", 7000, "KC"),
            _row("o2", "Other WR", "WR", 5000, "KC"),
            _row("o3", "Other WR2", "WR", 4000, "KC"),
        ],
        "sleeper": {
            "rosterPositions": ["QB", "WR", "WR", "BN", "BN"],
            "teams": [
                {
                    "ownerId": "me",
                    "name": "Mine",
                    "roster_id": 1,
                    "players": ["Star QB", "Star WR", "Bench WR", "Deep WR"],
                    "playerIds": ["qb1", "wr1", "wr2", "wr3"],
                    "faabBudget": 100,
                    "faabRemaining": 60,
                },
                {
                    "ownerId": "them",
                    "name": "Theirs",
                    "roster_id": 2,
                    "players": ["Other QB", "Other WR", "Other WR2"],
                    "playerIds": ["o1", "o2", "o3"],
                    "faabBudget": 100,
                    "faabRemaining": 100,
                },
            ],
        },
    }


def _rung_names(drop_payload):
    return [r["name"] for r in drop_payload["cutLadder"]["rungs"]]


# ══ The ladder, at the adapter ═════════════════════════════════════


def test_unconstrained_baseline_proposes_the_cheapest_wr_and_keeps_star_wr():
    """The fixture's premise, pinned so the tests below mean something."""
    drops = team_droppability(_contract(), owner_id="me")
    assert _rung_names(drops) == ["Deep WR"]
    assert {"Bench WR", "Star WR"} <= {u["name"] for u in drops["cutLadder"]["undroppable"]}
    assert "protections" not in drops


def test_a_protected_player_is_never_a_cut_rung_and_the_ladder_is_rebuilt():
    """Deep WR is protected.  He must not be a rung — and because he is now
    KEPT, the lineup no longer needs Bench WR: he becomes a legal release.
    Skipping the protected rung of the unconstrained ladder (``["Deep WR"]``)
    would leave NO drop at all and Bench WR wrongly blocked."""
    constraints = resolve_constraints(
        contract=_contract(), persistent={"untouchables": ["Deep WR"], "nflTeams": []}
    )
    drops = team_droppability(_contract(), owner_id="me", constraints=constraints)
    names = _rung_names(drops)
    assert "Deep WR" not in names
    assert names == ["Bench WR"]
    assert drops["protections"]["state"] == "applied"
    assert [p["name"] for p in drops["protections"]["protectedOnRoster"]] == ["Deep WR"]
    assert drops["protections"]["protectedOnRoster"][0]["reason"] == "protected_individual"
    # A protected player is not mislabelled as lineup-required either.
    assert "Deep WR" not in {u["name"] for u in drops["cutLadder"]["undroppable"]}


def test_an_nfl_team_rule_protects_through_the_same_owner():
    constraints = resolve_constraints(
        contract=_contract(), persistent={"untouchables": [], "nflTeams": ["CIN"]}
    )
    drops = team_droppability(_contract(), owner_id="me", constraints=constraints)
    assert not {"Bench WR", "Deep WR"} & set(_rung_names(drops))
    assert {p["name"] for p in drops["protections"]["protectedOnRoster"]} == {
        "Bench WR",
        "Deep WR",
    }


def test_unreadable_protections_propose_no_cut_at_all():
    drops = team_droppability(_contract(), owner_id="me", constraints=UNRESOLVED)
    assert drops["cutLadder"]["rungs"] == []
    assert drops["protections"]["state"] == "unresolved"
    assert any("could not be read" in n for n in drops["notes"])


def test_no_constraints_leave_the_payload_byte_identical():
    """Every existing caller (Perfect Waivers, the waiver advisor, drop
    assessment, the league loop) passes none and must see no change."""
    contract = _contract()
    assert json.dumps(team_droppability(contract, owner_id="me"), sort_keys=True) == json.dumps(
        team_droppability(contract, owner_id="me", constraints=None), sort_keys=True
    )


def test_no_league_wide_builder_can_carry_a_users_protections():
    """Protections reach ONE team's ladder per request.  The league-wide
    builders feed cached / shared consumers, so they take no constraints."""
    assert "constraints" not in inspect.signature(league_droppability).parameters
    assert "constraints" not in inspect.signature(ri.build_league_roster_intelligence).parameters


# ══ The route: own team only, never leaked ═════════════════════════


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "111",
                        "active": True,
                        "rosterSettings": {"teamCount": 2, "rosterSize": 5},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry))
    league_registry.reload_registry()
    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    sleeper_ids = {"alice": "me", "bob": "them", "carol": None}

    def _session(request):
        user = (getattr(request, "headers", None) or {}).get("x-test-user")
        if not user:
            return None
        session = {"username": user, "auth_method": "password"}
        if sleeper_ids.get(user):
            session["sleeper_user_id"] = sleeper_ids[user]
        return session

    monkeypatch.setattr(server, "_get_auth_session", _session)
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_teams_overlay", lambda **_kw: None)
    contract = _contract()
    monkeypatch.setattr(server, "latest_contract_data", contract)
    server._PERFECT_WAIVERS_CACHE.clear()
    client = TestClient(server.app, raise_server_exceptions=True)
    yield SimpleNamespace(client=client, contract=contract)
    league_registry.reload_registry()


def _as(user):
    return {"x-test-user": user}


def _drops(env, user, team):
    res = env.client.get(f"{URL}?team={team}&droppability=1", headers=_as(user))
    assert res.status_code == 200, res.text
    assert res.headers.get("cache-control") == "no-store"
    return res.json()["team"]["droppability"]


def _protect(env, user, untouchables=(), nfl_teams=()):
    res = env.client.put(
        "/api/user/trade-protections",
        json={"leagueKey": "main", "untouchables": list(untouchables), "nflTeams": list(nfl_teams)},
        headers=_as(user),
    )
    assert res.status_code == 200, res.text


def test_the_owner_never_sees_a_protected_player_as_a_cut(env):
    before = _drops(env, "alice", "me")
    assert "Deep WR" in _rung_names(before)
    assert before["protections"] == {
        "state": "applied",
        "protectedOnRoster": [],
        "source": "src/trade/constraints.py",
    }
    _protect(env, "alice", untouchables=["Deep WR"])
    after = _drops(env, "alice", "me")
    assert "Deep WR" not in _rung_names(after)
    assert _rung_names(after) == ["Bench WR"]
    assert [p["name"] for p in after["protections"]["protectedOnRoster"]] == ["Deep WR"]


def test_the_ladder_agrees_with_perfect_waivers_on_who_is_protected(env):
    _protect(env, "alice", untouchables=["Deep WR"], nfl_teams=["MIN"])
    drops = _drops(env, "alice", "me")
    plan = env.client.post(
        "/api/waiver/perfect", json={"leagueKey": "main", "teamOwnerId": "me"}, headers=_as("alice")
    )
    assert plan.status_code == 200, plan.text
    from_plan = {r["name"] for r in plan.json()["constraints"]["protectedOnRoster"]}
    from_ladder = {r["name"] for r in drops["protections"]["protectedOnRoster"]}
    assert from_plan == from_ladder == {"Deep WR", "Star WR"}


def test_another_user_gets_the_unchanged_ladder_and_no_trace_of_the_protection(env):
    unconstrained = team_droppability(env.contract, owner_id="me")
    _protect(env, "alice", untouchables=["Deep WR"])
    for viewer, reason in (("bob", "not_requesters_team"), ("carol", "requester_team_unknown")):
        res = env.client.get(f"{URL}?team=me&droppability=1", headers=_as(viewer))
        assert res.status_code == 200, res.text
        drops = res.json()["team"]["droppability"]
        assert drops["protections"] == {"state": "not_applied", "reason": reason}
        served = {k: v for k, v in drops.items() if k != "protections"}
        assert served == json.loads(json.dumps(unconstrained))
        assert "protected_individual" not in res.text
        assert "protectedOnRoster" not in res.text


def test_a_users_protections_never_bind_another_teams_ladder(env):
    """alice protects every KC player — all of bob's roster.  Viewing bob's
    team she gets bob's real ladder: her rule binds her own roster only."""
    _protect(env, "alice", nfl_teams=["KC"])
    drops = _drops(env, "alice", "them")
    assert drops["protections"] == {"state": "not_applied", "reason": "not_requesters_team"}
    assert drops["cutLadder"] == json.loads(
        json.dumps(team_droppability(env.contract, owner_id="them")["cutLadder"])
    )


def test_the_shared_contract_is_not_mutated_by_a_protected_request(env):
    snapshot = json.dumps(env.contract, sort_keys=True)
    _protect(env, "alice", untouchables=["Deep WR"])
    _drops(env, "alice", "me")
    assert json.dumps(server.latest_contract_data, sort_keys=True) == snapshot


def test_unreadable_protections_fail_closed_on_the_owners_ladder(env, monkeypatch):
    def boom(_username):
        raise RuntimeError("kv store down")

    monkeypatch.setattr(server._user_kv, "get_user_state", boom)
    drops = _drops(env, "alice", "me")
    assert drops["cutLadder"]["rungs"] == []
    assert drops["protections"]["state"] == "unresolved"


# ══ B3 — roster freshness on the waiver payloads ═══════════════════

_NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def _stamped(source, hours_ago):
    fetched = (_NOW - timedelta(hours=hours_ago)).isoformat()
    return {"sleeper": {"rosterSource": source, "rosterFetchedAt": fetched}}


@pytest.mark.parametrize(
    ("contract", "from_overlay", "overlay_at", "state", "delivery"),
    [
        (_stamped("live", 1), False, None, "current", "contract"),
        (_stamped("last_good", 1), False, None, "stale", "contract"),
        (_stamped("live", 30), False, None, "stale", "contract"),
        ({"sleeper": {}}, False, None, "unknown", "contract"),
        # The overlay is judged by ITS fetch time, never by the baked block's
        # stamps it was spliced beside.
        (
            _stamped("last_good", 90),
            True,
            (_NOW - timedelta(minutes=5)).isoformat(),
            "current",
            "live_overlay",
        ),
        (
            _stamped("live", 1),
            True,
            (_NOW - timedelta(hours=9)).isoformat(),
            "stale",
            "live_overlay",
        ),
        (_stamped("live", 1), True, None, "unknown", "live_overlay"),
    ],
)
def test_served_roster_freshness(contract, from_overlay, overlay_at, state, delivery):
    out = served_roster_freshness(
        contract, from_overlay=from_overlay, overlay_fetched_at=overlay_at, now=_NOW
    )
    assert out["state"] == state
    assert out["delivery"] == delivery
    if state == "unknown":
        assert out["ageHours"] is None


def test_waiver_payloads_say_when_their_rosters_are_a_restored_snapshot(env):
    restored = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    env.contract["sleeper"]["rosterSource"] = "last_good"
    env.contract["sleeper"]["rosterFetchedAt"] = restored
    body = {"leagueKey": "main", "teamOwnerId": "me"}
    for path in ("/api/waiver/suggestions", "/api/waiver/perfect"):
        res = env.client.post(path, json=body, headers=_as("alice"))
        assert res.status_code == 200, (path, res.text)
        payload = res.json()
        assert payload["rosterSource"] == "contract"
        assert payload["rosterFreshness"]["state"] == "stale", path
        assert payload["rosterFreshness"]["source"] == "last_good"
    # A Perfect Waivers cache hit re-states freshness rather than replaying it.
    env.contract["sleeper"]["rosterSource"] = "live"
    hit = env.client.post("/api/waiver/perfect", json=body, headers=_as("alice")).json()
    assert hit["rosterFreshness"]["state"] == "current"
    ladder = env.client.get(f"{URL}?team=me&droppability=1", headers=_as("alice")).json()
    assert ladder["rosterFreshness"]["state"] == "current"


def test_live_rosters_are_current(env, monkeypatch):
    fetched = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    monkeypatch.setattr(
        server._sleeper_overlay,
        "fetch_sleeper_teams_overlay",
        lambda **_kw: {
            "teams": list(env.contract["sleeper"]["teams"]),
            "overlayFetchedAt": fetched,
        },
    )
    res = env.client.post(
        "/api/waiver/suggestions",
        json={"leagueKey": "main", "teamOwnerId": "me"},
        headers=_as("alice"),
    )
    assert res.status_code == 200, res.text
    fresh = res.json()["rosterFreshness"]
    assert fresh["state"] == "current" and fresh["delivery"] == "live_overlay"
