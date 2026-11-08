"""CW-50 — the waiver routes against the owner's example, at the HTTP boundary.

*"A waiver recommendation must respect the actual eligible players, available
FAAB, roster capacity, dynasty protection rules, and NO TRANSACTION
alternative"* (owner directive 2026-11-07).  Route-level half of
``tests/trade/test_cw50_waiver_workflow.py``.

Every expected value is written by hand from the four-player league below; no
production function computes an expectation.  All external inputs are stubbed
(no Sleeper, no snapshot, no intel).

Record: ``docs/engineering/CW50_WAIVER_WORKFLOW_VERIFICATION_2026-11-07.md``.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from src.trade import faab_contention


def _row(name, pos, value, pid):
    return {
        "canonicalName": name,
        "displayName": name,
        "position": pos,
        "rankDerivedValue": value,
        "playerId": pid,
        "sourceCount": 3,
        "rookie": False,
    }


def _registry(tmp_path, *, roster_size=None):
    settings = {"teamCount": 3, "starters": {"QB": 1, "WR": 1}}
    if roster_size is not None:
        settings["rosterSize"] = roster_size
    leagues = [
        {
            "key": "main",
            "displayName": "Main",
            "sleeperLeagueId": "L-MAIN",
            "active": True,
            "rosterSettings": settings,
        },
        {
            "key": "other",
            "displayName": "Other",
            "sleeperLeagueId": "L-OTHER",
            "active": True,
            "rosterSettings": {"teamCount": 3},
        },
    ]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"defaultLeagueKey": "main", "leagues": leagues}), encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    def configure(roster_size=None):
        monkeypatch.setenv(
            "LEAGUE_REGISTRY_PATH", str(_registry(tmp_path, roster_size=roster_size))
        )
        league_registry.reload_registry()

    configure()
    from src.api import user_kv

    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(
        server._sleeper_overlay, "fetch_sleeper_teams_overlay", lambda **kwargs: None
    )
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", lambda **kwargs: None)
    monkeypatch.setattr(server.public_snapshot_store, "load_snapshot", lambda: None)
    monkeypatch.setattr(
        faab_contention, "load_intel_snapshot", lambda path=None, league_key=None: None
    )
    from src.adapters import sleeper_trending

    monkeypatch.setattr(sleeper_trending, "get_trending_adds", lambda **kwargs: None)
    yield configure
    league_registry.reload_registry()


def _contract():
    """Me: a QB and a WR.  Rival holds a WR.  Wire: one WR, one unpriced WR."""
    return {
        "meta": {"leagueKey": "main"},
        "players": {"stub": {"name": "Stub"}},
        "playersArray": [
            _row("Hot Pickup", "WR", 4000, "p-hot"),
            _row("Unpriced Guy", "WR", None, "p-unp"),
            _row("Backup Wr", "WR", 1000, "p-bwr"),
            _row("Rostered Qb", "QB", 6000, "p-rqb"),
            _row("Rival Wr", "WR", 5000, "p-rwr"),
            _row("Unpriced Mine", "WR", None, "p-um"),
        ],
        "sleeper": {
            "leagueId": "L-MAIN",
            "teams": [
                {
                    "ownerId": "me",
                    "name": "My Team",
                    "players": ["Rostered Qb", "Backup Wr"],
                    "playerIds": ["p-rqb", "p-bwr"],
                    "faabRemaining": 80,
                },
                {
                    "ownerId": "o1",
                    "name": "Rival One",
                    "players": ["Rival Wr"],
                    "playerIds": ["p-rwr"],
                    "faabRemaining": 60,
                },
                {
                    "ownerId": "o2",
                    "name": "Rival Two",
                    "players": [],
                    "playerIds": [],
                    "faabRemaining": 40,
                },
            ],
        },
    }


def _desk(monkeypatch, body, contract=None):
    monkeypatch.setattr(server, "latest_contract_data", contract or _contract())
    return TestClient(server.app).post("/api/waiver/faab-recommend", json=body)


# ── eligible players ─────────────────────────────────────────────────


def test_an_unpriced_add_gets_no_figure_never_a_zero(env, monkeypatch):
    res = _desk(monkeypatch, {"addPlayerName": "Unpriced Guy", "teamOwnerId": "me"})
    assert res.status_code == 422
    assert res.json()["error"] == "add_player_unpriced"


@pytest.mark.parametrize(
    ("add", "owner", "rostered_by", "own"),
    [
        ("Rival Wr", "me", "Rival One", False),
        ("Backup Wr", "me", "My Team", True),
    ],
)
def test_a_rostered_player_is_not_a_claim(env, monkeypatch, add, owner, rostered_by, own):
    res = _desk(monkeypatch, {"addPlayerName": add, "teamOwnerId": owner})
    assert res.status_code == 409
    body = res.json()
    assert body["error"] == "add_player_not_available"
    assert body["rosteredBy"] == rostered_by
    assert body["onYourRoster"] is own
    assert body["matchedBy"] == "playerId"


def test_a_free_agent_is_still_priced(env, monkeypatch):
    res = _desk(monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"})
    assert res.status_code == 200
    assert res.json()["resolvedAddValue"] == 4000


# ── the drop side: unknown is unknown, never free ────────────────────


@pytest.mark.parametrize(
    ("drop", "state"),
    [("Nobody Here", "not_on_board"), ("Unpriced Mine", "unpriced")],
)
def test_an_unknown_drop_is_never_treated_as_free(env, monkeypatch, drop, state):
    """ODR-SR-UNPRICED: an unpriced asset in drop logic is never a free drop.

    The desk used to charge it 0 and say "replacement level — free"."""
    res = _desk(
        monkeypatch,
        {"addPlayerName": "Hot Pickup", "dropPlayerName": drop, "teamOwnerId": "me"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["error"] == "drop_player_unpriced"
    assert body["dropValueState"] == state


def test_a_priced_drop_is_charged_and_stated(env, monkeypatch):
    res = _desk(
        monkeypatch,
        {"addPlayerName": "Hot Pickup", "dropPlayerName": "Backup Wr", "teamOwnerId": "me"},
    )
    body = res.json()
    assert body["resolvedDropValue"] == 1000
    assert body["dropValueState"] == "priced"


def test_no_drop_is_none_not_a_zero_value_drop(env, monkeypatch):
    body = _desk(monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"}).json()
    assert body["resolvedDropValue"] is None
    assert body["dropValueState"] == "none"


# ── roster capacity: a full roster names the release it forces ──────


def test_full_roster_claim_names_the_forced_release(env, monkeypatch):
    env(roster_size=2)  # me holds exactly 2
    body = _desk(monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"}).json()
    cap = body["rosterCapacity"]
    assert cap["application"] == "reported_not_applied"
    assert cap["rosterLimit"] == 2
    assert cap["requiresDrops"] is True
    # QB and WR must both stay filled.  Hot Pickup (4000) takes the WR slot,
    # so the cheapest legal release is Backup Wr (1000) — never Rostered Qb.
    assert [d["name"] for d in cap["forcedDrops"]] == ["Backup Wr"]
    assert cap["forcedDrops"][0]["value"] == 1000
    assert any("Backup Wr" in w and "roster is full" in w for w in body["warnings"])


def test_open_spot_claim_forces_nothing(env, monkeypatch):
    env(roster_size=3)
    body = _desk(monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"}).json()
    assert body["rosterCapacity"]["requiresDrops"] is False
    assert body["rosterCapacity"]["forcedDrops"] == []
    assert not any("roster is full" in w for w in body["warnings"])


def test_unknown_cap_is_unknown_never_unlimited(env, monkeypatch):
    env(roster_size=None)
    body = _desk(monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"}).json()
    assert body["rosterCapacity"]["rosterLimit"] is None
    assert body["rosterCapacity"]["requiresDrops"] is None
    assert any("capacity is unknown" in w for w in body["warnings"])


def test_capacity_report_moves_no_figure(env, monkeypatch):
    """Reported, not applied: the same claim prices identically at any cap."""
    env(roster_size=2)
    full = _desk(monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"}).json()
    env(roster_size=5)
    room = _desk(monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"}).json()
    for key in ("conservative", "standard", "aggressive", "max"):
        assert full[key] == room[key]


def test_the_capacity_report_never_builds_the_league_bundle(env, monkeypatch):
    """Warm-only: the desk reads the last built bundle and never pays the solve."""
    from src.api import gameplan

    def _tripwire(*args, **kwargs):
        raise AssertionError("the bid desk must not build the league bundle")

    monkeypatch.setattr(gameplan, "get_league_bundle", _tripwire)
    monkeypatch.setattr(gameplan, "last_built_league_bundle", lambda key: None)
    env(roster_size=2)
    body = _desk(monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"}).json()
    cap = body["rosterCapacity"]
    assert cap["requiresDrops"] is True
    assert any("scarcity inert" in n for n in cap["notes"])


def test_no_team_named_reports_capacity_unavailable(env, monkeypatch):
    body = _desk(monkeypatch, {"addPlayerName": "Hot Pickup"}).json()
    assert body["rosterCapacity"]["state"] == "unavailable"
    assert body["rosterCapacity"]["reason"] == "team_not_identified"


# ── available FAAB at the route ─────────────────────────────────────


def test_suggestions_route_stamps_the_balance_it_capped_at(env, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    res = TestClient(server.app).post(
        "/api/waiver/suggestions", json={"teamOwnerId": "me", "minValue": 0}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["faabBudget"]["state"] == "known"
    assert body["faabBudget"]["balance"] == 80
    assert body["faabBudget"]["source"] == "roster"
    for items in body["by_position"].values():
        for c in items:
            assert c["bid"]["aggressive"] <= 80


# ── league scoping ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/waiver/suggestions", {}),
        ("/api/waiver/perfect", {"teamOwnerId": "me"}),
        ("/api/waiver/faab-recommend", {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"}),
    ],
)
def test_another_leagues_rosters_never_answer(env, monkeypatch, path, body):
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    client = TestClient(server.app)
    res = client.post(path, json={**body, "leagueKey": "other"})
    assert res.status_code == 503
    assert res.json()["error"] == "data_not_ready"
    res = client.post(path, json={**body, "leagueKey": "nope"})
    assert res.status_code == 400
    assert res.json()["error"] == "unknown_league"
