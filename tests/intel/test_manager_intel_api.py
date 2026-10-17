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
