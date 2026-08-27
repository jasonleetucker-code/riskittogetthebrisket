from fastapi.testclient import TestClient

import server
from src.sharp import service


def test_sharp_routes_registered_as_self_authed_not_bypassed(monkeypatch):
    # /api/sharp/cohort and /api/sharp/market are registered in
    # _SELF_AUTHED_API_EXACT (same pattern as /api/signal-alerts/run): the
    # cookie-only middleware lets the request through, but each handler
    # still requires a session OR the SHARP_SMOKE_TOKEN bearer used by the
    # production-smoke workflow — proven by the dedicated tests below.
    # /api/sharp/market/audit is untouched and stays fully middleware-gated.
    assert server._is_public_api_path("/api/sharp/cohort")
    assert server._is_public_api_path("/api/sharp/market")
    assert not server._is_public_api_path("/api/sharp/market/audit")


def test_sharp_market_request_injection_works_with_a_session(monkeypatch):
    monkeypatch.setattr(server, "_get_auth_session", lambda _request: {"user": "test"})
    monkeypatch.setattr(
        service.sharp_market,
        "market_payload",
        lambda **_kwargs: {"status": "ok", "assets": []},
    )

    with TestClient(server.app, raise_server_exceptions=True) as client:
        market = client.get(
            "/api/sharp/market",
            params={
                "window": "30d",
                "platform": "all",
                "qualification": "all",
                "sort": "strength",
                "limit": "25",
            },
        )

    assert market.status_code == 200
    assert market.json() == {"status": "ok", "assets": []}
    assert "private" in (market.headers.get("Cache-Control") or "")


def test_sharp_market_requires_session_or_bearer(monkeypatch):
    monkeypatch.setattr(service, "SHARP_SMOKE_TOKEN", "correct-horse-battery-staple")
    monkeypatch.setattr(
        service.sharp_market,
        "market_payload",
        lambda **_kwargs: {"status": "ok", "assets": []},
    )

    with TestClient(server.app, raise_server_exceptions=True) as client:
        anonymous = client.get("/api/sharp/market")
        wrong_bearer = client.get(
            "/api/sharp/market", headers={"Authorization": "Bearer nope"}
        )
        right_bearer = client.get(
            "/api/sharp/market",
            headers={"Authorization": "Bearer correct-horse-battery-staple"},
        )

    assert anonymous.status_code == 401
    assert wrong_bearer.status_code == 401
    assert right_bearer.status_code == 200


def test_sharp_cohort_requires_session_or_bearer(monkeypatch):
    monkeypatch.setattr(service, "SHARP_SMOKE_TOKEN", "correct-horse-battery-staple")
    monkeypatch.setattr(service, "cohort_status", lambda: {"status": "ok"})

    with TestClient(server.app, raise_server_exceptions=True) as client:
        anonymous = client.get("/api/sharp/cohort")
        wrong_bearer = client.get(
            "/api/sharp/cohort", headers={"Authorization": "Bearer nope"}
        )
        right_bearer = client.get(
            "/api/sharp/cohort",
            headers={"Authorization": "Bearer correct-horse-battery-staple"},
        )

    assert anonymous.status_code == 401
    assert wrong_bearer.status_code == 401
    assert right_bearer.status_code == 200
    assert right_bearer.json() == {"status": "ok"}


def test_sharp_cohort_and_market_bearer_disabled_when_token_unset(monkeypatch):
    monkeypatch.setattr(service, "SHARP_SMOKE_TOKEN", "")

    with TestClient(server.app, raise_server_exceptions=True) as client:
        cohort = client.get(
            "/api/sharp/cohort", headers={"Authorization": "Bearer anything"}
        )
        market = client.get(
            "/api/sharp/market", headers={"Authorization": "Bearer anything"}
        )

    assert cohort.status_code == 401
    assert market.status_code == 401
