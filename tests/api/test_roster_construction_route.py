"""GET /api/roster-construction — flag, auth, league routing and payload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api import feature_flags, league_registry, user_kv
from tests.roster_intel.rc_support import build_snapshot, league_of, make_contract, positions_of

URL = "/api/roster-construction"
AS = {"x-test-user": "alice"}


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
                        "sleeperLeagueId": "RCMAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 4, "rosterSize": 58},
                    },
                    {
                        "key": "side",
                        "displayName": "Side",
                        "sleeperLeagueId": "RCSIDE",
                        "active": True,
                        "rosterSettings": {"teamCount": 4, "rosterSize": 27},
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
    teams = league_of(4)
    main = build_snapshot(teams, league_id="RCMAIN")
    side = build_snapshot(teams, best_ball=0, league_id="RCSIDE")
    built: list[str] = []

    def _build(league_id, *a, **k):
        built.append(league_id)
        return side

    monkeypatch.setattr(server, "_get_public_snapshot", lambda *a, **k: main)
    monkeypatch.setattr(server, "build_public_snapshot", _build)
    pos = positions_of(teams)
    contract = make_contract(
        "main", {rid: list(t) for rid, t in teams.items()}, {p: 1000.0 for p in pos}, pos
    )
    monkeypatch.setattr(server, "latest_contract_data", contract)
    for cache in (
        server._roster_construction_cache,
        server._rc_league_cache,
        server._rc_snapshot_cache,
        server._player_impact_cache,
        server._rc_season_status_cache,
        server._rc_nfl_state_cache,
    ):
        cache.clear()
    # Host week-finality reads Sleeper /state/nfl; never the network in tests.
    nfl = {"state": {"season": "2025", "season_type": "regular", "display_week": 99}}
    monkeypatch.setattr(server, "_rc_nfl_state", lambda: nfl["state"])
    real = feature_flags.is_enabled
    state = {"on": True}
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda name, *a, **k: state["on"] if name == "roster_construction" else real(name, *a, **k),
    )
    client = TestClient(server.app, raise_server_exceptions=True)
    yield type(
        "E",
        (),
        {"client": client, "state": state, "contract": contract, "built": built, "nfl": nfl},
    )
    league_registry.reload_registry()


def test_flag_off_is_503_before_anything(env):
    env.state["on"] = False
    res = env.client.get(URL, headers=AS)
    assert res.status_code == 503
    assert res.json() == {"error": "feature_disabled", "flag": "roster_construction"}


def test_requires_a_session(env):
    res = env.client.get(URL)
    assert res.status_code == 401


def test_not_a_public_api_path():
    assert not server._is_public_api_path(URL)


def test_league_overview_without_team(env):
    res = env.client.get(URL, params={"leagueKey": "main"}, headers=AS)
    assert res.status_code == 200
    body = res.json()
    assert body["schemaVersion"] == "roster_construction.v1"
    assert body["leagueKey"] == "main"
    assert "team" not in body and len(body["teams"]) == 4
    assert res.headers["cache-control"] == "private, no-store"


def test_selected_team_payload_and_value_is_read_only(env):
    before = json.dumps(env.contract, sort_keys=True)
    res = env.client.get(URL, params={"leagueKey": "main", "rosterId": "2"}, headers=AS)
    assert res.status_code == 200
    body = res.json()
    assert body["team"]["rosterId"] == 2
    assert body["lineupBasis"] == "host_best_ball_optimal"
    assert body["valueBlock"]["available"] is True
    assert body["rules"]["rosterLimit"] == 58
    assert json.dumps(env.contract, sort_keys=True) == before


def test_managed_league_is_served_labelled_not_refused(env):
    res = env.client.get(URL, params={"leagueKey": "side", "rosterId": "1"}, headers=AS)
    assert res.status_code == 200
    body = res.json()
    assert env.built == ["RCSIDE"]
    assert body["lineupBasis"] == "hypothetical_optimal"
    assert body["valueBlock"] == {
        "available": False,
        "reason": "contract_league_mismatch",
        "asOf": None,
    }
    row = body["players"][0]
    assert row["marginalPoints"]["value"] is None
    assert row["marginalPoints"]["unavailableWeeks"]


def test_errors_are_named(env):
    assert env.client.get(URL, params={"leagueKey": "nope"}, headers=AS).status_code == 400
    r = env.client.get(URL, params={"leagueKey": "main", "season": "1999"}, headers=AS)
    assert r.status_code == 404 and r.json()["error"] == "unknown_season"
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "77"}, headers=AS)
    assert r.status_code == 404 and r.json()["error"] == "unknown_team"
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "x"}, headers=AS)
    assert r.status_code == 400 and r.json()["error"] == "invalid_roster_id"


def test_include_playoffs_parameter(env):
    r = env.client.get(URL, params={"leagueKey": "main", "includePlayoffs": "1"}, headers=AS)
    assert r.status_code == 200 and r.json()["rules"]["includePlayoffs"] is True


def test_error_responses_are_not_cacheable(env):
    cases = [
        ({}, AS),  # flag off below
        ({"leagueKey": "nope"}, AS),
        ({"leagueKey": "main", "rosterId": "x"}, AS),
        ({"leagueKey": "main", "season": "1999"}, AS),
        ({"leagueKey": "main"}, {}),
    ]
    for params, headers in cases:
        r = env.client.get(URL, params=params, headers=headers)
        assert "no-store" in (r.headers.get("cache-control") or ""), (params, r.status_code)
    env.state["on"] = False
    r = env.client.get(URL, headers=AS)
    assert r.status_code == 503 and r.headers["cache-control"] == "private, no-store"


def test_posture_failure_is_a_stable_code(env, monkeypatch):
    from src.api import gameplan

    def boom(*a, **k):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(gameplan, "league_competitive_postures", boom)
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "1"}, headers=AS)
    assert r.status_code == 200
    assert r.json()["team"]["posture"] == {"label": None, "reason": "posture_lookup_failed"}
    assert "RuntimeError" not in r.text and "secret detail" not in r.text


def test_posture_unavailable_carries_the_owner_reason_code(env, monkeypatch):
    from src.api import gameplan

    def unavailable(*a, **k):
        raise gameplan.GameplanUnavailable("bundle_not_built", "long prose")

    monkeypatch.setattr(gameplan, "league_competitive_postures", unavailable)
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "1"}, headers=AS)
    assert r.json()["team"]["posture"]["reason"] == "posture_unavailable:bundle_not_built"
    assert "GameplanUnavailable" not in r.text


def test_posture_owner_import_failure_degrades_instead_of_503(env, monkeypatch):
    # Validator note 2 (#2028): a failing import of the posture owner must
    # degrade to a named unavailable, not break the whole page.
    import sys

    import src.api

    # ``from src.api import gameplan`` reads the package attribute first.
    monkeypatch.delattr(src.api, "gameplan", raising=False)
    monkeypatch.setitem(sys.modules, "src.api.gameplan", None)
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "1"}, headers=AS)
    assert r.status_code == 200
    assert r.json()["team"]["posture"] == {"label": None, "reason": "posture_lookup_failed"}


# ── D2 (owner decision 2026-11-01): unverified historical lineup rules ──────
def _two_season_snapshot():
    """2026 verified; 2025's league object lists 17 starters while every
    matchup seats 21 (the real dynasty_main 2025 shape)."""
    from tests.roster_intel.rc_support import DYNASTY_MAIN_SLOTS

    teams = league_of(4)
    cur = build_snapshot(teams, league_id="RCMAIN", season="2026")
    old = build_snapshot(teams, league_id="RCMAIN25", season="2025")
    old.seasons[0].league["roster_positions"] = DYNASTY_MAIN_SLOTS[:17] + ["BN"] * 10
    cur.seasons = cur.seasons + old.seasons
    return cur


def test_contradicted_historical_season_is_an_explicit_unavailable_state(env, monkeypatch):
    snap = _two_season_snapshot()
    monkeypatch.setattr(server, "_get_public_snapshot", lambda *a, **k: snap)
    r = env.client.get(URL, params={"leagueKey": "main"}, headers=AS)
    body = r.json()
    assert r.status_code == 200 and body["season"] == "2026" and body["available"] is True
    assert body["availableSeasons"] == ["2026", "2025"]
    assert body["seasonAvailability"] == [
        {"season": "2026", "available": True, "reason": None},
        {"season": "2025", "available": False, "reason": "historical_lineup_config_unverified"},
    ]
    for params in ({"season": "2025"}, {"season": "2025", "rosterId": "1"}):
        r = env.client.get(URL, params={"leagueKey": "main", **params}, headers=AS)
        body = r.json()
        assert r.status_code == 200, params
        assert body["available"] is False
        assert body["unavailableReason"] == "historical_lineup_config_unverified"
        assert body["lineupConfig"]["contradictions"] == [
            "starter_count_differs_from_configured_slots"
        ]
        assert body["lineupConfig"]["recordedStarterSlotCount"] == 17
        # Nothing lineup-derived is served: no teams, no team view, no ranks.
        assert body["teams"] == [] and "team" not in body and "players" not in body
        assert "coverage" not in body and "rules" not in body
        assert r.headers["cache-control"] == "private, no-store"


def test_ops_health_reports_a_withheld_current_season(env, monkeypatch):
    from tests.roster_intel.rc_support import DYNASTY_MAIN_SLOTS

    # Fine: the default (current) season is verified.
    assert server._roster_construction_health() == []
    # The CURRENT season's league object now contradicts its matchups.
    snap = _two_season_snapshot()
    snap.seasons[0].league["roster_positions"] = DYNASTY_MAIN_SLOTS[:17] + ["BN"] * 10
    monkeypatch.setattr(server, "_get_public_snapshot", lambda *a, **k: snap)
    server._rc_season_status_cache.clear()
    (row,) = server._roster_construction_health()
    assert row["leagueKey"] == "main" and row["season"] == "2026"
    assert row["reason"] == "lineup_config_unverified"
    assert row["contradictions"] == ["starter_count_differs_from_configured_slots"]
    # Flag off: nothing served, nothing withheld.
    env.state["on"] = False
    assert server._roster_construction_health() == []


def test_ops_health_is_unknown_when_it_cannot_check(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(server, "_roster_construction_season_statuses", boom)
    assert server._roster_construction_health() is None


def test_post_refresh_warm_prebuilds_the_default_view_only_when_on(env):
    env.state["on"] = False
    server._warm_roster_construction_after_refresh()
    assert not server._rc_league_cache and not server._rc_season_status_cache
    env.state["on"] = True
    server._warm_roster_construction_after_refresh()
    assert len(server._rc_league_cache) == 1 and len(server._rc_season_status_cache) == 1
    # The route then answers from the warmed league-season.
    (key,) = server._rc_league_cache
    warmed = server._rc_league_cache[key]
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "1"}, headers=AS)
    assert r.status_code == 200 and server._rc_league_cache[key] is warmed


def test_post_refresh_warm_never_raises(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(server, "_roster_construction_season_statuses", boom)
    server._warm_roster_construction_after_refresh()  # logged, not raised


def test_unknown_team_never_answers_with_another_teams_data(env):
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "77"}, headers=AS)
    assert r.status_code == 404
    assert r.json() == {"error": "unknown_team", "rosterId": 77, "season": "2025"}


# ── production defect 2026-11-03: an unfinalized host week ───────────────
def _in_season_with_provisional_week_8():
    """In-season 2026, weeks 1-8 scored by the host clock, week 8's host
    lineups provisional (each team's FIRST 21 players, not the optimum)."""
    teams = league_of(4)
    snap = build_snapshot(
        teams, weeks=list(range(1, 9)), league_id="RCMAIN", season="2026", status="in_season"
    )
    s = snap.seasons[0]
    s.league["settings"]["last_scored_leg"] = 8
    for e in s.matchups_by_week[8]:
        e["starters"] = list(e["players"][:21])
        e["points"] = round(sum(e["players_points"].get(p, 0.0) for p in e["starters"]), 2)
    return snap


def test_an_unfinalized_host_week_no_longer_withholds_the_season(env, monkeypatch):
    snap = _in_season_with_provisional_week_8()
    monkeypatch.setattr(server, "_get_public_snapshot", lambda *a, **k: snap)
    env.nfl["state"] = {"season": "2026", "season_type": "regular", "week": 9, "display_week": 8}
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "1"}, headers=AS)
    body = r.json()
    assert r.status_code == 200 and body["available"] is True and body["season"] == "2026"
    assert body["coverage"]["weeksIncluded"] == list(range(1, 8))
    assert {"week": 8, "reason": "host_week_not_final"} in body["coverage"]["weeksExcluded"]
    assert body["coverage"]["contradictedWeeks"] == []
    assert server._roster_construction_health() == []  # no ops alert


def test_nfl_state_is_fetched_once_per_expiry_and_failure_is_unknown(monkeypatch):
    from src.public_league import sleeper_client

    calls = []

    def fetch():
        calls.append(1)
        return None if len(calls) == 1 else {"season": "2026", "display_week": 8}

    monkeypatch.setattr(sleeper_client, "fetch_nfl_state", fetch)
    server._rc_nfl_state_cache.clear()
    assert server._rc_nfl_state() is None  # failure -> unknown, cached briefly
    assert server._rc_nfl_state() is None and len(calls) == 1
    server._rc_nfl_state_cache["state"] = (0.0, None)  # failure TTL expired
    assert server._rc_nfl_state() == {"season": "2026", "display_week": 8}
    assert server._rc_nfl_state() == {"season": "2026", "display_week": 8} and len(calls) == 2
    server._rc_nfl_state_cache.clear()


def test_once_the_host_finalizes_the_week_its_contradiction_is_real(env, monkeypatch):
    # Same data, but the host has moved on (display_week 9): week 8 is final
    # and its awarded lineups are not the optimum -- a real contradiction of
    # the best-ball flag, so the strict rule withholds the season.
    snap = _in_season_with_provisional_week_8()
    monkeypatch.setattr(server, "_get_public_snapshot", lambda *a, **k: snap)
    env.nfl["state"] = {"season": "2026", "season_type": "regular", "week": 9, "display_week": 9}
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "1"}, headers=AS)
    body = r.json()
    assert r.status_code == 200 and body["available"] is False
    assert body["unavailableReason"] == "lineup_config_unverified"
    assert body["lineupConfig"]["contradictedWeeks"] == [8]
    assert "team" not in body
    (row,) = server._roster_construction_health()  # the ops alert would fire
    assert row["contradictedWeeks"] == [8]
