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
