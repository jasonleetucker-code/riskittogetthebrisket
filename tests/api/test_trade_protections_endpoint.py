"""C3-CON-02 — the WRITER for persistent personal trade protections.

``server._constraints_for_request`` has read ``user_kv.tradeConstraintsByLeague``
since C3-CON-01, but nothing wrote it, so every user resolved to "no
protections configured".  These pin the storage endpoint and — the point of the
row — that what it stores is then honoured by the generated-trade consumer.

Spec: ``docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md`` §2,
§7 acceptance 8-11 and 13 (the "Jason + league MIN" minimal test).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry, user_kv

URL = "/api/user/trade-protections"


def _row(name, team, position="WR", value=5000):
    return {
        "displayName": name,
        "canonicalName": name,
        "team": team,
        "position": position,
        "assetClass": "pick" if position == "PICK" else "player",
        "rankDerivedValue": value,
    }


BOARD_ROWS = [
    _row("Justin Jefferson", "MIN"),
    _row("Jordan Addison", "MIN"),
    _row("Ja'Marr Chase", "CIN"),
    _row("Josh Allen", "BUF", "QB"),
    _row("Free Agent Guy", "FA", "RB"),
    _row("Teamless Guy", None, "RB"),
    _row("2027 Early 1st", None, "PICK"),
]


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
                        "aliases": ["primary"],
                        "displayName": "Main",
                        "sleeperLeagueId": "111",
                        "active": True,
                        "rosterSettings": {},
                    },
                    {
                        "key": "backup",
                        "displayName": "Backup",
                        "sleeperLeagueId": "222",
                        "active": True,
                        "rosterSettings": {},
                    },
                    {
                        "key": "retired",
                        "displayName": "Retired",
                        "sleeperLeagueId": "333",
                        "active": False,
                        "rosterSettings": {},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry))
    league_registry.reload_registry()
    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    def _session(request):
        user = (getattr(request, "headers", None) or {}).get("x-test-user")
        return {"username": user, "auth_method": "password"} if user else None

    monkeypatch.setattr(server, "_get_auth_session", _session)
    contract = {"playersArray": [dict(r) for r in BOARD_ROWS]}
    monkeypatch.setattr(server, "latest_contract_data", contract)
    # No ``with``: the lifespan would load the real board over our fixture.
    client = TestClient(server.app, raise_server_exceptions=True)
    yield SimpleNamespace(client=client, contract=contract)
    league_registry.reload_registry()


def _as(user):
    return {"x-test-user": user}


def _ok(res):
    assert res.status_code == 200, res.text
    return res


def _put(env, user, body):
    return env.client.put(URL, json=body, headers=_as(user))


# ── auth + league resolution ─────────────────────────────────────────


def test_anonymous_is_401_on_both_verbs(env):
    assert env.client.get(URL, params={"leagueKey": "main"}).status_code == 401
    res = env.client.put(URL, json={"leagueKey": "main", "untouchables": [], "nflTeams": []})
    assert res.status_code == 401
    assert res.json()["error"] == "auth_required"


def test_league_must_be_named_never_defaulted(env):
    """No silent home-league fallback for a personal rule."""
    res = env.client.get(URL, headers=_as("alice"))
    assert res.status_code == 400
    assert res.json()["error"] == "league_key_required"
    res = _put(env, "alice", {"untouchables": [], "nflTeams": ["MIN"]})
    assert res.status_code == 400
    assert res.json()["error"] == "league_key_required"


@pytest.mark.parametrize(
    ("league", "code"),
    [("nope", "unknown_league"), ("111", "unknown_league"), ("retired", "inactive_league")],
)
def test_unknown_inactive_and_raw_sleeper_ids_are_400(env, league, code):
    res = env.client.get(URL, params={"leagueKey": league}, headers=_as("alice"))
    assert res.status_code == 400
    assert res.json()["error"] == code
    res = _put(env, "alice", {"leagueKey": league, "untouchables": [], "nflTeams": ["MIN"]})
    assert res.status_code == 400
    assert res.json()["error"] == code


def test_aliases_canonicalise_to_the_registry_key(env):
    res = _put(env, "alice", {"leagueKey": "primary", "untouchables": [], "nflTeams": ["MIN"]})
    assert res.status_code == 200, res.text
    assert res.json()["leagueKey"] == "main"
    stored = user_kv.get_user_state("alice")["tradeConstraintsByLeague"]
    assert set(stored) == {"main"}


# ── round trip, idempotency, isolation ───────────────────────────────


def test_unconfigured_is_a_legitimate_empty_answer(env):
    res = env.client.get(URL, params={"leagueKey": "main"}, headers=_as("alice"))
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False
    assert body["untouchables"] == [] and body["nflTeams"] == []
    assert body["nflTeamOptions"] == ["BUF", "CIN", "MIN"]  # FA is not a team


def test_round_trip_is_canonical_and_idempotent(env):
    body = {
        "leagueKey": "main",
        "untouchables": ["ja'marr chase", "  JOSH ALLEN ", "Ja'Marr Chase"],
        "nflTeams": ["min", "MIN"],
    }
    first = _put(env, "alice", body)
    assert first.status_code == 200, first.text
    raw_after_first = user_kv.get_user_state("alice")["tradeConstraintsByLeague"]
    second = _put(env, "alice", body)
    assert second.status_code == 200
    assert user_kv.get_user_state("alice")["tradeConstraintsByLeague"] == raw_after_first
    assert raw_after_first == {
        "main": {"untouchables": ["Ja'Marr Chase", "Josh Allen"], "nflTeams": ["MIN"]}
    }
    got = env.client.get(URL, params={"leagueKey": "main"}, headers=_as("alice")).json()
    assert got["configured"] is True
    assert got["untouchables"] == ["Ja'Marr Chase", "Josh Allen"]
    assert got["nflTeams"] == ["MIN"]
    assert got["unresolvedUntouchables"] == []


def test_other_leagues_and_unrelated_state_are_preserved(env):
    user_kv.merge_user_state("alice", {"watchlist": ["Josh Allen"]})
    _ok(_put(env, "alice", {"leagueKey": "backup", "untouchables": [], "nflTeams": ["BUF"]}))
    _ok(_put(env, "alice", {"leagueKey": "main", "untouchables": [], "nflTeams": ["MIN"]}))
    state = user_kv.get_user_state("alice")
    assert state["tradeConstraintsByLeague"] == {
        "backup": {"untouchables": [], "nflTeams": ["BUF"]},
        "main": {"untouchables": [], "nflTeams": ["MIN"]},
    }
    assert state["watchlist"] == ["Josh Allen"]

    # Clearing one league removes only that league's entry.
    res = _put(env, "alice", {"leagueKey": "main", "untouchables": [], "nflTeams": []})
    assert res.status_code == 200 and res.json()["configured"] is False
    assert user_kv.get_user_state("alice")["tradeConstraintsByLeague"] == {
        "backup": {"untouchables": [], "nflTeams": ["BUF"]}
    }


def test_one_users_write_never_reaches_another_user(env):
    _ok(_put(env, "alice", {"leagueKey": "main", "untouchables": [], "nflTeams": ["MIN"]}))
    got = env.client.get(URL, params={"leagueKey": "main"}, headers=_as("bob")).json()
    assert got["configured"] is False


# ── strict validation through the constraint owner ───────────────────


@pytest.mark.parametrize("code", ["JAC", "XXX", "FA", "Vikings"])
def test_an_nfl_team_the_board_does_not_carry_is_rejected(env, code):
    """'JAC' would store, look configured, and protect nobody (board says JAX)."""
    res = _put(env, "alice", {"leagueKey": "main", "untouchables": [], "nflTeams": [code]})
    assert res.status_code == 400
    body = res.json()
    assert body["error"] == "invalid_protection"
    assert body["errors"] == [{"field": "nflTeams", "value": code, "reason": "unknown_nfl_team"}]
    assert "tradeConstraintsByLeague" not in user_kv.get_user_state("alice")


@pytest.mark.parametrize(
    ("value", "reason"),
    [("Justin Jeffersen", "unknown_player"), ("2027 Early 1st", "not_a_player")],
)
def test_an_asset_that_is_not_a_board_player_is_rejected(env, value, reason):
    res = _put(
        env,
        "alice",
        {"leagueKey": "main", "untouchables": ["Josh Allen", value], "nflTeams": ["MIN"]},
    )
    assert res.status_code == 400
    assert res.json()["errors"] == [{"field": "untouchables", "value": value, "reason": reason}]
    # All-or-nothing: the valid half was NOT stored either.
    assert "tradeConstraintsByLeague" not in user_kv.get_user_state("alice")


@pytest.mark.parametrize(
    "body",
    [
        {"leagueKey": "main", "nflTeams": ["MIN"]},
        {"leagueKey": "main", "untouchables": "Josh Allen", "nflTeams": []},
        {"leagueKey": "main", "untouchables": [7], "nflTeams": []},
        {"leagueKey": "main", "untouchables": [], "nflTeams": [], "scoringProfile": "x"},
    ],
)
def test_malformed_bodies_are_400(env, body):
    res = _put(env, "alice", body)
    assert res.status_code == 400
    assert res.json()["error"] in {"invalid_protection", "invalid_body"}


def test_too_many_players_is_400(env):
    names = ["Josh Allen"] * 101
    res = _put(env, "alice", {"leagueKey": "main", "untouchables": names, "nflTeams": []})
    assert res.status_code == 400
    assert res.json()["errors"][0]["reason"] == "too_many"


def test_no_board_means_no_write_but_clearing_still_works(env, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", None)
    res = _put(env, "alice", {"leagueKey": "main", "untouchables": [], "nflTeams": ["MIN"]})
    assert res.status_code == 503
    assert res.json()["error"] == "data_not_ready"
    res = _put(env, "alice", {"leagueKey": "main", "untouchables": [], "nflTeams": []})
    assert res.status_code == 200
    got = env.client.get(URL, params={"leagueKey": "main"}, headers=_as("alice")).json()
    assert got["nflTeamOptions"] is None and got["unresolvedUntouchables"] is None


def test_a_player_who_left_the_board_is_reported_not_dropped(env):
    _ok(_put(env, "alice", {"leagueKey": "main", "untouchables": ["Josh Allen"], "nflTeams": []}))
    env.contract["playersArray"] = [
        r for r in env.contract["playersArray"] if r["displayName"] != "Josh Allen"
    ]
    got = env.client.get(URL, params={"leagueKey": "main"}, headers=_as("alice")).json()
    assert got["untouchables"] == ["Josh Allen"]
    assert got["unresolvedUntouchables"] == ["Josh Allen"]


# ── end to end: the consumer honours what the writer stored ──────────


def _finder_inputs():
    """A two-team finder fixture whose outgoing pool is exactly P0 + P1."""
    players = {
        f"P{i}": {
            "_finalAdjusted": 6000 - i * 100,
            "position": "RB",
            "_sites": 6,
            "_canonicalSiteValues": {"ktcSfTep": 5000 - i * 100, "idpTradeCalc": 5000 - i * 100},
        }
        for i in range(8)
    }
    teams = [
        {"name": "Us", "ownerId": "1", "roster_id": 1, "players": ["P0", "P1"], "picks": []},
        {"name": "Them", "ownerId": "2", "roster_id": 2, "players": ["P2", "P3"], "picks": []},
    ]
    board = {
        "playersArray": [_row("P0", "MIN", "RB"), _row("P1", "CIN", "RB")]
        + [_row(f"P{i}", "BUF", "RB") for i in range(2, 8)]
    }
    return players, teams, board


def _consumer_run(user, league_key, board, players, teams):
    """The exact path every generated-trade route takes: resolve, then generate."""
    from src.trade import finder

    request = SimpleNamespace(headers=_as(user))
    cfg = league_registry.get_league_by_key(league_key)
    constraints = server._constraints_for_request(request, board, cfg, surface="test")
    return constraints, finder.find_trades(players, "Us", ["Them"], teams, constraints=constraints)


def test_a_saved_protection_is_honoured_by_generated_trades(env, monkeypatch):
    """Jason + league MIN minimal test, end to end through the writer.

    Fail-on-old: before C3-CON-02 nothing could store this block, so the same
    consumer call resolved to no protections and blocked nothing — exactly the
    ``before`` assertion below.
    """
    players, teams, board = _finder_inputs()
    monkeypatch.setattr(server, "latest_contract_data", board)

    before, before_result = _consumer_run("jason", "main", board, players, teams)
    assert before.active is False
    assert before_result["metadata"]["constraintsBlockedOutgoing"] == 0

    res = _put(env, "jason", {"leagueKey": "main", "untouchables": ["p1"], "nflTeams": ["MIN"]})
    assert res.status_code == 200, res.text

    after, result = _consumer_run("jason", "main", board, players, teams)
    assert after.block_reason({"name": "P0"}) == "protected_nfl_team"  # team from the board
    assert after.block_reason({"name": "P1"}) == "protected_individual"
    assert after.may_send({"name": "P2"}) is True  # incoming targets untouched
    assert result["trades"] == []
    assert result["metadata"]["constraintsBlockedOutgoing"] == 2
    assert result["metadata"]["noResultReason"] == "all_outgoing_assets_constrained"

    # Same user, other league: unaffected.  Other user, same league: unaffected.
    other_league, _ = _consumer_run("jason", "backup", board, players, teams)
    other_user, other_result = _consumer_run("bob", "main", board, players, teams)
    assert other_league.active is False
    assert other_user.active is False
    assert other_result["metadata"]["constraintsBlockedOutgoing"] == 0

    # Canonical values are unchanged by preference state (§7 acceptance 13).
    assert [r["rankDerivedValue"] for r in board["playersArray"]] == [5000] * 8
