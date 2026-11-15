"""C6-MGR-02 Batch A — ``GET /api/manager-intel/profile`` route behaviour.

Router-level tests run on a bare FastAPI app with injected providers (the
portfolio builder is stubbed); one test goes through ``server.app`` to pin
the private gate and the nav capability.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import feature_flags
from src.api import rate_limit
from src.intel import manager_intel_api as api
from src.intel import manager_portfolio as mp

SESSION = {"username": "owner", "auth_method": "password"}


@pytest.fixture
def client(monkeypatch):
    rate_limit.reset_for_tests()
    feature_flags.reload()
    calls: list[dict[str, Any]] = []
    answer: dict[str, Any] = {"status": "ok", "players": [], "leagues": []}

    def fake_profile(username, **kwargs):
        calls.append({"username": username, **kwargs})
        return dict(answer)

    monkeypatch.setattr(mp, "cached_manager_profile", fake_profile)
    session = {"value": SESSION}
    api.configure(
        session_provider=lambda request: session["value"],
        contract_provider=lambda: {"playersArray": [{"playerId": "1"}]},
    )
    app = FastAPI()
    app.include_router(api.router)
    yield TestClient(app), calls, answer, session
    api.configure(session_provider=None, contract_provider=None)
    rate_limit.reset_for_tests()
    feature_flags.reload()


def _get(c, **params):
    return c.get("/api/manager-intel/profile", params=params)


def test_ok_profile_is_no_store_and_reports_the_board(client):
    c, calls, _answer, _session = client
    r = _get(c, username="DynastyFan", scope="keeper", season="2025")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.json()["hasBoard"] is True
    assert calls == [
        {
            "username": "DynastyFan",
            "contract": {"playersArray": [{"playerId": "1"}]},
            "scope": "keeper",
            "season": "2025",
        }
    ]


def test_partial_is_200(client):
    c, _calls, answer, _session = client
    answer["status"] = "partial"
    assert _get(c, username="x").status_code == 200


@pytest.mark.parametrize(
    ("status", "code", "error"),
    [
        ("not_found", 404, "not_found"),
        ("rate_limited", 429, "upstream_rate_limited"),
        ("upstream_unavailable", 503, "upstream_unavailable"),
    ],
)
def test_upstream_states_map_to_status_codes(client, status, code, error):
    c, _calls, answer, _session = client
    answer.clear()
    answer["status"] = status
    r = _get(c, username="ghost")
    assert r.status_code == code and r.json()["error"] == error


@pytest.mark.parametrize(
    "params",
    [
        {"username": ""},
        {"username": "bad name"},
        {"username": "x" * 41},
        {"username": "../etc"},
        {"username": "ok", "scope": "bestball"},
        {"username": "ok", "season": "26"},
    ],
)
def test_bad_input_is_400_and_never_reaches_sleeper(client, params):
    c, calls, _answer, _session = client
    assert _get(c, **params).status_code == 400
    assert calls == []


def test_anonymous_is_401_and_guest_pass_is_403(client):
    c, calls, _answer, session = client
    session["value"] = None
    assert _get(c, username="x").status_code == 401
    session["value"] = {"username": "guest", "auth_method": "guest_pass"}
    assert _get(c, username="x").status_code == 403
    assert calls == []


def test_unwired_deployment_is_401(client):
    c, _calls, _answer, _session = client
    api.configure(session_provider=None, contract_provider=None)
    assert _get(c, username="x").status_code == 401


def test_flag_off_is_503(client, monkeypatch):
    c, calls, _answer, _session = client
    monkeypatch.setenv("RISKIT_FEATURE_MANAGER_INTELLIGENCE", "0")
    feature_flags.reload()
    r = _get(c, username="x")
    assert r.status_code == 503 and r.json()["error"] == "feature_disabled"
    assert calls == []


def test_per_user_rate_limit(client):
    c, calls, _answer, _session = client
    for _ in range(api.RATE_CAPACITY):
        assert _get(c, username="x").status_code == 200
    r = _get(c, username="x")
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    assert len(calls) == api.RATE_CAPACITY


def test_builder_exception_is_503_not_500(client, monkeypatch):
    c, _calls, _answer, _session = client

    def boom(*a, **k):
        raise RuntimeError("sleeper exploded")

    monkeypatch.setattr(mp, "cached_manager_profile", boom)
    r = _get(c, username="x")
    assert r.status_code == 503 and r.json()["error"] == "upstream_unavailable"


def test_flag_is_live_and_default_on():
    assert feature_flags._DEFAULTS["manager_intelligence"] is True
    assert feature_flags.gate_status("manager_intelligence") == "LIVE"


def test_server_gates_the_route_and_publishes_the_nav_capability(monkeypatch):
    import server

    with TestClient(server.app) as c:
        r = c.get("/api/manager-intel/profile", params={"username": "x"})
        assert r.status_code == 401
    assert "managerIntelligence" in server._NAV_GATED_CAPABILITIES
    assert server._NAV_GATED_CAPABILITIES["managerIntelligence"]() is True
    monkeypatch.setenv("RISKIT_FEATURE_MANAGER_INTELLIGENCE", "0")
    feature_flags.reload()
    try:
        assert server._NAV_GATED_CAPABILITIES["managerIntelligence"]() is False
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_MANAGER_INTELLIGENCE")
        feature_flags.reload()


# ── GET /api/manager-intel/activity (Batches B1 + B2 + feed) ────────────


@pytest.fixture
def activity_client(monkeypatch):
    from src.intel import manager_activity as ma

    rate_limit.reset_for_tests()
    feature_flags.reload()
    calls: list[dict[str, Any]] = []
    answer: dict[str, Any] = {"status": "ok", "trades": [], "acquisitions": [], "feed": []}

    def fake_activity(username, **kwargs):
        calls.append({"username": username, **kwargs})
        return dict(answer)

    monkeypatch.setattr(ma, "cached_manager_activity", fake_activity)
    session = {"value": SESSION}
    factory = object()
    api.configure(
        session_provider=lambda request: session["value"],
        contract_provider=lambda: {"playersArray": [{"playerId": "1"}]},
        asof_resolver_provider=lambda: factory,
    )
    app = FastAPI()
    app.include_router(api.router)
    yield TestClient(app), calls, answer, session, factory
    api.configure(session_provider=None, contract_provider=None)
    rate_limit.reset_for_tests()
    feature_flags.reload()


def _act(c, **params):
    return c.get("/api/manager-intel/activity", params=params)


def test_activity_ok_passes_params_and_the_asof_factory(activity_client):
    c, calls, _answer, _session, factory = activity_client
    r = _act(c, username="DynastyFan", window="90d", season="2025", league="123", scope="keeper")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert calls == [
        {
            "username": "DynastyFan",
            "contract": {"playersArray": [{"playerId": "1"}]},
            "window": "90d",
            "season": "2025",
            "league_id": "123",
            "scope": "keeper",
            "asof_factory": factory,
        }
    ]


def test_activity_defaults(activity_client):
    c, calls, _answer, _session, _factory = activity_client
    assert _act(c, username="x").status_code == 200
    assert calls[0]["window"] == "30d" and calls[0]["season"] is None
    assert calls[0]["league_id"] is None and calls[0]["scope"] == "dynasty"


@pytest.mark.parametrize(
    "params",
    [
        {"username": ""},
        {"username": "bad name"},
        {"username": "ok", "window": "14d"},
        {"username": "ok", "season": "26"},
        {"username": "ok", "league": "abc"},
        {"username": "ok", "scope": "bestball"},
    ],
)
def test_activity_bad_input_is_400(activity_client, params):
    c, calls, _answer, _session, _factory = activity_client
    assert _act(c, **params).status_code == 400
    assert calls == []


def test_activity_anonymous_401_guest_403_flag_off_503(activity_client, monkeypatch):
    c, calls, _answer, session, _factory = activity_client
    session["value"] = None
    assert _act(c, username="x").status_code == 401
    session["value"] = {"username": "guest", "auth_method": "guest_pass"}
    assert _act(c, username="x").status_code == 403
    session["value"] = SESSION
    monkeypatch.setenv("RISKIT_FEATURE_MANAGER_INTELLIGENCE", "0")
    feature_flags.reload()
    r = _act(c, username="x")
    assert r.status_code == 503 and r.json()["error"] == "feature_disabled"
    assert calls == []


@pytest.mark.parametrize(
    ("status", "code", "error"),
    [
        ("not_found", 404, "not_found"),
        ("rate_limited", 429, "upstream_rate_limited"),
        ("upstream_unavailable", 503, "upstream_unavailable"),
    ],
)
def test_activity_upstream_states(activity_client, status, code, error):
    c, _calls, answer, _session, _factory = activity_client
    answer.clear()
    answer["status"] = status
    r = _act(c, username="ghost")
    assert r.status_code == code and r.json()["error"] == error


def test_activity_partial_is_200(activity_client):
    c, _calls, answer, _session, _factory = activity_client
    answer["status"] = "partial"
    assert _act(c, username="x").status_code == 200


def test_activity_has_its_own_tighter_rate_limit_bucket(activity_client):
    c, calls, _answer, _session, _factory = activity_client
    assert api.ACTIVITY_RATE_CAPACITY < api.RATE_CAPACITY
    for _ in range(api.ACTIVITY_RATE_CAPACITY):
        assert _act(c, username="x").status_code == 200
    r = _act(c, username="x")
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    assert len(calls) == api.ACTIVITY_RATE_CAPACITY


def test_activity_builder_exception_and_broken_ledger_provider(activity_client, monkeypatch):
    from src.intel import manager_activity as ma

    c, calls, _answer, _session, _factory = activity_client

    def broken_provider():
        raise RuntimeError("ledger exploded")

    api.configure(
        session_provider=lambda request: SESSION,
        contract_provider=lambda: None,
        asof_resolver_provider=broken_provider,
    )
    assert _act(c, username="x").status_code == 200
    assert calls[-1]["asof_factory"] is None

    def boom(*a, **k):
        raise RuntimeError("sleeper exploded")

    monkeypatch.setattr(ma, "cached_manager_activity", boom)
    r = _act(c, username="x")
    assert r.status_code == 503 and r.json()["error"] == "upstream_unavailable"


def test_server_gates_the_activity_route_and_wires_the_ledger():
    import server

    with TestClient(server.app) as c:
        r = c.get("/api/manager-intel/activity", params={"username": "x"})
        assert r.status_code == 401
    # Router fixtures above reset the module-level wiring, so pin the server's
    # configure call itself: it hands over the asof-grades resolver factory.
    import inspect

    source = inspect.getsource(server)
    assert "asof_resolver_provider=lambda: _build_public_activity_valuation()" in source


# ── GET /api/manager-intel/league (Batch C) ─────────────────────────────


@pytest.fixture
def league_client(monkeypatch):
    from src.intel import manager_league as ml

    rate_limit.reset_for_tests()
    feature_flags.reload()
    calls: list[dict[str, Any]] = []
    answer: dict[str, Any] = {"status": "ok", "managers": []}

    def fake_league(league_id, **kwargs):
        calls.append({"leagueId": league_id, **kwargs})
        return dict(answer)

    monkeypatch.setattr(ml, "cached_league_scouting", fake_league)
    session = {"value": SESSION}
    api.configure(
        session_provider=lambda request: session["value"],
        contract_provider=lambda: {"playersArray": [{"playerId": "1"}]},
    )
    app = FastAPI()
    app.include_router(api.router)
    yield TestClient(app), calls, answer, session
    api.configure(session_provider=None, contract_provider=None)
    rate_limit.reset_for_tests()
    feature_flags.reload()


def _lg(c, **params):
    return c.get("/api/manager-intel/league", params=params)


def test_league_ok_passes_params_and_is_no_store(league_client):
    c, calls, _answer, _session = league_client
    r = _lg(c, leagueId="1312006700437352448", window="90d")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert calls == [
        {
            "leagueId": "1312006700437352448",
            "contract": {"playersArray": [{"playerId": "1"}]},
            "window": "90d",
        }
    ]
    assert _lg(c, leagueId="1").status_code == 200
    assert calls[-1]["window"] == "30d"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"leagueId": ""},
        {"leagueId": "abc"},
        {"leagueId": "1" * 25},
        {"leagueId": "../etc"},
        {"leagueId": "123", "window": "14d"},
    ],
)
def test_league_bad_input_is_400_and_never_reaches_sleeper(league_client, params):
    c, calls, _answer, _session = league_client
    assert _lg(c, **params).status_code == 400
    assert calls == []


def test_league_anonymous_401_guest_403_flag_off_503_unwired_401(league_client, monkeypatch):
    c, calls, _answer, session = league_client
    session["value"] = None
    assert _lg(c, leagueId="1").status_code == 401
    session["value"] = {"username": "guest", "auth_method": "guest_pass"}
    assert _lg(c, leagueId="1").status_code == 403
    session["value"] = SESSION
    monkeypatch.setenv("RISKIT_FEATURE_MANAGER_INTELLIGENCE", "0")
    feature_flags.reload()
    r = _lg(c, leagueId="1")
    assert r.status_code == 503 and r.json()["error"] == "feature_disabled"
    monkeypatch.delenv("RISKIT_FEATURE_MANAGER_INTELLIGENCE")
    feature_flags.reload()
    api.configure(session_provider=None, contract_provider=None)
    assert _lg(c, leagueId="1").status_code == 401
    assert calls == []


@pytest.mark.parametrize(
    ("status", "code", "error"),
    [
        ("not_found", 404, "not_found"),
        ("rate_limited", 429, "upstream_rate_limited"),
        ("upstream_unavailable", 503, "upstream_unavailable"),
    ],
)
def test_league_upstream_states(league_client, status, code, error):
    c, _calls, answer, _session = league_client
    answer.clear()
    answer["status"] = status
    r = _lg(c, leagueId="1")
    assert r.status_code == code and r.json()["error"] == error


def test_league_partial_is_200(league_client):
    c, _calls, answer, _session = league_client
    answer["status"] = "partial"
    assert _lg(c, leagueId="1").status_code == 200


def test_league_has_its_own_rate_limit_bucket(league_client, monkeypatch):
    from src.intel import manager_activity as ma

    c, calls, _answer, _session = league_client
    assert api.LEAGUE_RATE_CAPACITY == 6
    for _ in range(api.LEAGUE_RATE_CAPACITY):
        assert _lg(c, leagueId="1").status_code == 200
    r = _lg(c, leagueId="1")
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    assert len(calls) == api.LEAGUE_RATE_CAPACITY
    # A separate bucket: the activity lookup is still open for this user.
    monkeypatch.setattr(ma, "cached_manager_activity", lambda *a, **k: {"status": "ok"})
    assert _act(c, username="x").status_code == 200


def test_league_builder_exception_is_503_not_500(league_client, monkeypatch):
    from src.intel import manager_league as ml

    c, _calls, _answer, _session = league_client

    def boom(*a, **k):
        raise RuntimeError("sleeper exploded")

    monkeypatch.setattr(ml, "cached_league_scouting", boom)
    r = _lg(c, leagueId="1")
    assert r.status_code == 503 and r.json()["error"] == "upstream_unavailable"


def test_server_gates_the_league_route_and_it_is_never_public():
    import server

    with TestClient(server.app) as c:
        r = c.get("/api/manager-intel/league", params={"leagueId": "1312006700437352448"})
        assert r.status_code == 401
        # Not under /api/public in any form.
        assert c.get("/api/public/manager-intel/league").status_code in (401, 404)


# ── Batch E: career + compare ───────────────────────────────────────────


@pytest.fixture
def e_client(monkeypatch):
    from src.intel import manager_career as mc
    from src.intel import manager_compare as mcmp

    rate_limit.reset_for_tests()
    feature_flags.reload()
    calls: list[tuple[str, Any, dict[str, Any]]] = []
    answers: dict[str, dict[str, Any]] = {
        "career": {"status": "ok", "seasons": []},
        "managers": {"status": "ok", "a": {}, "b": {}},
        "league": {"status": "ok", "metrics": []},
    }

    def fake_career(username, **kwargs):
        calls.append(("career", username, kwargs))
        return dict(answers["career"])

    def fake_compare(a, b, **kwargs):
        calls.append(("managers", (a, b), kwargs))
        return dict(answers["managers"])

    def fake_pct(a, league_id, **kwargs):
        calls.append(("league", (a, league_id), kwargs))
        return dict(answers["league"])

    monkeypatch.setattr(mc, "cached_manager_career", fake_career)
    monkeypatch.setattr(mcmp, "build_manager_comparison", fake_compare)
    monkeypatch.setattr(mcmp, "build_league_percentile", fake_pct)
    session = {"value": SESSION}
    api.configure(
        session_provider=lambda request: session["value"],
        contract_provider=lambda: {"playersArray": [{"playerId": "1"}]},
    )
    app = FastAPI()
    app.include_router(api.router)
    yield TestClient(app), calls, answers, session
    api.configure(session_provider=None, contract_provider=None)
    rate_limit.reset_for_tests()
    feature_flags.reload()


def test_career_ok_is_no_store_and_passes_params(e_client):
    c, calls, _answers, _session = e_client
    r = c.get("/api/manager-intel/career", params={"username": "Fan_1", "scope": "keeper"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert calls == [
        (
            "career",
            "Fan_1",
            {"contract": {"playersArray": [{"playerId": "1"}]}, "scope": "keeper"},
        )
    ]


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/manager-intel/career", {"username": "bad name"}),
        ("/api/manager-intel/career", {"username": "ok", "scope": "bestball"}),
        ("/api/manager-intel/compare", {"a": "ok"}),
        ("/api/manager-intel/compare", {"a": "ok", "b": "../x"}),
        ("/api/manager-intel/compare", {"a": "", "b": "ok"}),
        ("/api/manager-intel/compare", {"a": "ok", "leagueId": "abc"}),
        ("/api/manager-intel/compare", {"a": "ok", "b": "y", "window": "1y"}),
    ],
)
def test_e_bad_input_is_400_and_never_reaches_sleeper(e_client, path, params):
    c, calls, _answers, _session = e_client
    assert c.get(path, params=params).status_code == 400
    assert calls == []


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/manager-intel/career", {"username": "x"}),
        ("/api/manager-intel/compare", {"a": "x", "b": "y"}),
    ],
)
def test_e_gates(e_client, monkeypatch, path, params):
    c, calls, _answers, session = e_client
    session["value"] = None
    assert c.get(path, params=params).status_code == 401
    session["value"] = {"username": "guest", "auth_method": "guest_pass"}
    assert c.get(path, params=params).status_code == 403
    session["value"] = SESSION
    monkeypatch.setenv("RISKIT_FEATURE_MANAGER_INTELLIGENCE", "0")
    feature_flags.reload()
    assert c.get(path, params=params).status_code == 503
    monkeypatch.delenv("RISKIT_FEATURE_MANAGER_INTELLIGENCE")
    feature_flags.reload()
    api.configure(session_provider=None, contract_provider=None)
    assert c.get(path, params=params).status_code == 401
    assert calls == []


@pytest.mark.parametrize(
    ("status", "code", "error"),
    [
        ("not_found", 404, "not_found"),
        ("rate_limited", 429, "upstream_rate_limited"),
        ("upstream_unavailable", 503, "upstream_unavailable"),
    ],
)
def test_career_upstream_states(e_client, status, code, error):
    c, _calls, answers, _session = e_client
    answers["career"] = {"status": status}
    r = c.get("/api/manager-intel/career", params={"username": "x"})
    assert r.status_code == code and r.json()["error"] == error


def test_compare_managers_and_league_together(e_client):
    c, calls, _answers, _session = e_client
    r = c.get("/api/manager-intel/compare", params={"a": "x", "b": "y", "leagueId": "12"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["status"] == "ok" and "managers" in body and "league" in body
    assert [k for k, *_ in calls] == ["managers", "league"]
    assert calls[1][2]["window"] == "30d"


def test_compare_partial_side_is_200_partial(e_client):
    c, _calls, answers, _session = e_client
    answers["managers"] = {"status": "partial"}
    r = c.get("/api/manager-intel/compare", params={"a": "x", "b": "y"})
    assert r.status_code == 200 and r.json()["status"] == "partial"


def test_compare_missing_side_is_404_naming_it(e_client):
    c, _calls, answers, _session = e_client
    answers["managers"] = {"status": "not_found", "failedSide": "b"}
    r = c.get("/api/manager-intel/compare", params={"a": "x", "b": "nobody"})
    assert r.status_code == 404
    assert r.json()["side"] == "b" and "nobody" in r.json()["message"]
    answers["managers"] = {"status": "ok"}
    answers["league"] = {"status": "not_found", "failedSide": "league"}
    r = c.get("/api/manager-intel/compare", params={"a": "x", "leagueId": "5"})
    assert r.status_code == 404 and r.json()["side"] == "league"


def test_career_and_compare_have_their_own_buckets(e_client, monkeypatch):
    c, calls, _answers, _session = e_client
    for _ in range(api.CAREER_RATE_CAPACITY):
        assert c.get("/api/manager-intel/career", params={"username": "x"}).status_code == 200
    assert c.get("/api/manager-intel/career", params={"username": "x"}).status_code == 429
    for _ in range(api.COMPARE_RATE_CAPACITY):
        assert c.get("/api/manager-intel/compare", params={"a": "x", "b": "y"}).status_code == 200
    r = c.get("/api/manager-intel/compare", params={"a": "x", "b": "y"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert api.COMPARE_RATE_CAPACITY < api.CAREER_RATE_CAPACITY < api.ACTIVITY_RATE_CAPACITY
    # The profile bucket is untouched.
    monkeypatch.setattr(mp, "cached_manager_profile", lambda *a, **k: {"status": "ok"})
    assert _get(c, username="x").status_code == 200


def test_e_builder_exception_is_503_not_500(e_client, monkeypatch):
    from src.intel import manager_career as mc

    c, _calls, _answers, _session = e_client

    def boom(*a, **k):
        raise RuntimeError("sleeper exploded")

    monkeypatch.setattr(mc, "cached_manager_career", boom)
    r = c.get("/api/manager-intel/career", params={"username": "x"})
    assert r.status_code == 503 and r.json()["error"] == "upstream_unavailable"


def test_server_gates_the_career_and_compare_routes_and_they_are_never_public():
    import server

    with TestClient(server.app) as c:
        assert c.get("/api/manager-intel/career", params={"username": "x"}).status_code == 401
        r = c.get("/api/manager-intel/compare", params={"a": "x", "b": "y"})
        assert r.status_code == 401
        assert c.get("/api/public/manager-intel/career").status_code in (401, 404)
        assert c.get("/api/public/manager-intel/compare").status_code in (401, 404)


# ── Batch F: saved managers, refresh, leaderboards ──────────────────────


@pytest.fixture
def f_client(monkeypatch, tmp_path):
    from src.api import user_kv
    from src.intel import manager_alerts as mal
    from src.intel import manager_league as ml
    from src.intel import manager_saved as ms
    from src.public_league import sleeper_client as sc

    rate_limit.reset_for_tests()
    feature_flags.reload()
    ms.reset_name_memo()
    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "kv.sqlite")
    users = {
        "111": {"user_id": "111", "username": "alpha", "display_name": "Alpha"},
        "alpha": {"user_id": "111", "username": "alpha", "display_name": "Alpha"},
    }
    sleeper = {"calls": [], "kind": None}

    def fake_fetch(handle):
        sleeper["calls"].append(handle)
        if sleeper["kind"]:
            return sleeper["kind"], None
        user = users.get(str(handle).lower())
        return (sc.FETCH_OK, user) if user else (sc.FETCH_NOT_FOUND, None)

    monkeypatch.setattr(sc, "fetch_user_classified", fake_fetch)
    # list_saved binds its fetcher default at def time: route it through the fake.
    real_list = ms.list_saved
    monkeypatch.setattr(
        ms, "list_saved", lambda kv_user, **kw: real_list(kv_user, fetch_user=fake_fetch, **kw)
    )
    refreshes: list[str] = []

    def fake_refresh(kv_user, **kw):
        refreshes.append(kv_user)
        return {"checked": [], "remaining": 0}

    monkeypatch.setattr(mal, "refresh_for_user", fake_refresh)
    leagues: list[tuple[str, str]] = []
    league_answer = {
        "status": "ok",
        "league": {"leagueId": "42", "name": "Alleys"},
        "managers": [],
        "coverage": {"transactions": "complete", "drafts": "complete"},
    }

    def fake_league(league_id, **kw):
        leagues.append((league_id, kw.get("window")))
        return dict(league_answer)

    monkeypatch.setattr(ml, "cached_league_scouting", fake_league)
    session = {"value": SESSION}
    api.configure(
        session_provider=lambda request: session["value"],
        contract_provider=lambda: {"playersArray": []},
    )
    app = FastAPI()
    app.include_router(api.router)
    yield (
        TestClient(app),
        {
            "sleeper": sleeper,
            "session": session,
            "refreshes": refreshes,
            "leagues": leagues,
            "league_answer": league_answer,
            "users": users,
        },
    )
    api.configure(session_provider=None, contract_provider=None)
    rate_limit.reset_for_tests()
    feature_flags.reload()
    ms.reset_name_memo()


def test_saved_round_trip_is_keyed_by_user_id_and_no_store(f_client):
    c, ctx = f_client
    r = c.post("/api/manager-intel/saved", json={"username": "Alpha"})
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["created"] is True and body["saved"]["userId"] == "111"
    assert [m["userId"] for m in body["managers"]] == ["111"] and body["limit"] == 50
    again = c.post("/api/manager-intel/saved", json={"userId": "111"})
    assert again.status_code == 200 and again.json()["created"] is False
    listed = c.get("/api/manager-intel/saved")
    assert listed.status_code == 200 and listed.headers["cache-control"] == "no-store"
    assert listed.json()["managers"][0]["username"] == "alpha"
    gone = c.delete("/api/manager-intel/saved", params={"userId": "111"})
    assert gone.status_code == 200 and gone.json()["removed"] is True
    assert c.get("/api/manager-intel/saved").json()["managers"] == []


def test_saved_list_follows_a_rename(f_client):
    from src.intel import manager_saved as ms

    c, ctx = f_client
    c.post("/api/manager-intel/saved", json={"userId": "111"})
    ms.reset_name_memo()
    ctx["users"]["111"] = {"user_id": "111", "username": "alpha2", "display_name": "Alpha Two"}
    (m,) = c.get("/api/manager-intel/saved").json()["managers"]
    assert (m["userId"], m["username"], m["previousUsernames"]) == ("111", "alpha2", ["alpha"])


@pytest.mark.parametrize(
    ("body", "code", "error"),
    [
        ({}, 400, "invalid_username"),
        ({"username": "bad name"}, 400, "invalid_username"),
        ({"userId": "12ab"}, 400, "invalid_user_id"),
        ({"userId": "111", "alerts": "yes"}, 400, "invalid_body"),
        ({"userId": "111", "displayName": "spoof"}, 400, "invalid_body"),
        ({"username": "ghost"}, 404, "not_found"),
    ],
)
def test_saved_post_validation(f_client, body, code, error):
    c, _ctx = f_client
    r = c.post("/api/manager-intel/saved", json=body)
    assert r.status_code == code and r.json()["error"] == error


def test_saved_post_upstream_states(f_client):
    c, ctx = f_client
    ctx["sleeper"]["kind"] = "rate_limited"
    assert c.post("/api/manager-intel/saved", json={"userId": "111"}).status_code == 429
    from src.intel import manager_saved as ms

    ms.reset_name_memo()
    ctx["sleeper"]["kind"] = "error"
    assert c.post("/api/manager-intel/saved", json={"userId": "111"}).status_code == 503


def test_saved_cap_is_409(f_client, monkeypatch):
    from src.intel import manager_saved as ms

    c, ctx = f_client
    monkeypatch.setattr(ms, "MAX_SAVED", 1)
    ctx["users"]["222"] = {"user_id": "222", "username": "beta"}
    assert c.post("/api/manager-intel/saved", json={"userId": "111"}).status_code == 201
    r = c.post("/api/manager-intel/saved", json={"userId": "222"})
    assert r.status_code == 409 and r.json()["error"] == "saved_limit_reached"


def test_saved_delete_validates(f_client):
    c, _ctx = f_client
    assert c.delete("/api/manager-intel/saved", params={"userId": "x"}).status_code == 400
    r = c.delete("/api/manager-intel/saved", params={"userId": "999"})
    assert r.status_code == 200 and r.json()["removed"] is False


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/manager-intel/saved", {}),
        ("post", "/api/manager-intel/saved", {"json": {"userId": "111"}}),
        ("delete", "/api/manager-intel/saved", {"params": {"userId": "111"}}),
        ("post", "/api/manager-intel/saved/refresh", {}),
        ("get", "/api/manager-intel/leaderboard", {"params": {"population": "saved"}}),
    ],
)
def test_f_gates(f_client, monkeypatch, method, path, kwargs):
    c, ctx = f_client
    ctx["session"]["value"] = None
    assert getattr(c, method)(path, **kwargs).status_code == 401
    ctx["session"]["value"] = {"username": "guest", "auth_method": "guest_pass"}
    r = getattr(c, method)(path, **kwargs)
    assert r.status_code == 403 and r.headers["cache-control"] == "no-store"
    ctx["session"]["value"] = SESSION
    monkeypatch.setenv("RISKIT_FEATURE_MANAGER_INTELLIGENCE", "0")
    feature_flags.reload()
    assert getattr(c, method)(path, **kwargs).status_code == 503
    assert ctx["sleeper"]["calls"] == [] and ctx["refreshes"] == []


def test_saved_lists_are_per_user(f_client):
    c, ctx = f_client
    c.post("/api/manager-intel/saved", json={"userId": "111"})
    ctx["session"]["value"] = {"username": "someone_else", "auth_method": "password"}
    assert c.get("/api/manager-intel/saved").json()["managers"] == []


def test_refresh_runs_for_the_signed_in_user_with_its_own_bucket(f_client):
    c, ctx = f_client
    for _ in range(api.SAVED_REFRESH_RATE_CAPACITY):
        assert c.post("/api/manager-intel/saved/refresh").status_code == 200
    assert ctx["refreshes"] == ["owner"] * api.SAVED_REFRESH_RATE_CAPACITY
    assert c.post("/api/manager-intel/saved/refresh").status_code == 429
    # The saved list itself is a different bucket.
    assert c.get("/api/manager-intel/saved").status_code == 200


def test_leaderboard_populations(f_client):
    c, ctx = f_client
    r = c.get("/api/manager-intel/leaderboard", params={"population": "saved"})
    assert r.status_code == 200 and r.json()["population"]["kind"] == "saved"
    assert ctx["leagues"] == []  # the saved board spends no league read
    r = c.get(
        "/api/manager-intel/leaderboard",
        params={"population": "league", "leagueId": "42", "window": "season"},
    )
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["population"]["label"] == "Current teams in Alleys"
    assert ctx["leagues"] == [("42", "season")]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"population": "all"},
        {"population": "sleeper"},
        {"population": "league"},
        {"population": "league", "leagueId": "abc"},
        {"population": "league", "leagueId": "42", "window": "1y"},
    ],
)
def test_leaderboard_refuses_unnamed_populations(f_client, params):
    c, ctx = f_client
    assert c.get("/api/manager-intel/leaderboard", params=params).status_code == 400
    assert ctx["leagues"] == []


def test_leaderboard_league_upstream_states(f_client):
    c, ctx = f_client
    ctx["league_answer"]["status"] = "not_found"
    r = c.get("/api/manager-intel/leaderboard", params={"population": "league", "leagueId": "1"})
    assert r.status_code == 404


def test_server_gates_the_batch_f_routes_and_they_are_never_public():
    import server

    with TestClient(server.app) as c:
        assert c.get("/api/manager-intel/saved").status_code == 401
        assert c.post("/api/manager-intel/saved", json={"userId": "1"}).status_code == 401
        assert c.delete("/api/manager-intel/saved", params={"userId": "1"}).status_code == 401
        assert c.post("/api/manager-intel/saved/refresh").status_code == 401
        r = c.get("/api/manager-intel/leaderboard", params={"population": "saved"})
        assert r.status_code == 401
        assert c.get("/api/public/manager-intel/saved").status_code in (401, 404)
