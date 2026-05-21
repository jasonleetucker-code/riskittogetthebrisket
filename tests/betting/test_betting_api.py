"""API-level tests for the Betting endpoints (FastAPI TestClient).

Verifies auth gating, settings round-trip, guardrail rejection, and the
clean "not configured" path when no Kalshi credentials are present.
These run without any Kalshi/Odds credentials.
"""

from __future__ import annotations

import uuid

import pytest

from starlette.testclient import TestClient

import server


@pytest.fixture()
def client():
    return TestClient(server.app)


@pytest.fixture()
def authed():
    """A TestClient with an injected in-memory session cookie."""
    sid = uuid.uuid4().hex
    server.auth_sessions[sid] = {"username": f"tester_{sid[:8]}"}
    c = TestClient(server.app)
    c.cookies.set(server.JASON_AUTH_COOKIE_NAME, sid)
    yield c
    server.auth_sessions.pop(sid, None)


def test_endpoints_require_auth(client):
    gets = [
        "/api/betting/recommendations",
        "/api/betting/bets",
        "/api/betting/settings",
        "/api/betting/rooting",
    ]
    for path in gets:
        assert client.get(path).status_code == 401, f"{path} should require auth"
    assert client.post("/api/betting/bets", json={}).status_code == 401
    assert client.post("/api/betting/kill", json={}).status_code == 401


def test_settings_roundtrip(authed):
    resp = authed.get("/api/betting/settings")
    assert resp.status_code == 200
    settings = resp.json()["settings"]
    assert settings["unit_usd"] > 0
    assert settings["env"] in ("demo", "prod")

    resp = authed.put(
        "/api/betting/settings",
        json={"unit_usd": 8, "per_bet_max_usd": 30, "daily_cap_usd": 60},
    )
    assert resp.status_code == 200
    saved = resp.json()["settings"]
    assert saved["unit_usd"] == 8
    assert saved["per_bet_max_usd"] == 30


def test_recommendations_empty_without_snapshot(authed):
    resp = authed.get("/api/betting/recommendations")
    assert resp.status_code == 200
    body = resp.json()
    assert "recommendations" in body
    assert isinstance(body["recommendations"], list)


def test_post_bet_guardrail_rejects_oversized(authed):
    # Default per-bet max is 25; a $999 stake → way over.
    resp = authed.post(
        "/api/betting/bets",
        json={"targetPrice": 50, "stakeUsd": 999, "sideTeam": "New York Knicks"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "exceeds_per_bet_max"


def test_post_bet_invalid_price(authed):
    resp = authed.post("/api/betting/bets", json={"targetPrice": 150, "stakeUsd": 5})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_target_price"


def test_post_bet_zero_stake_rejected(authed):
    resp = authed.post("/api/betting/bets", json={"targetPrice": 50, "stakeUsd": 0})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_stake"


def test_post_bet_not_configured_without_credentials(authed):
    # Valid, within-guardrail bet — but no Kalshi creds → clean 503.
    resp = authed.post(
        "/api/betting/bets",
        json={"targetPrice": 50, "stakeUsd": 5, "ticker": "KXNBAGAME-TEST"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"] == "betting_not_configured"


def test_kill_and_rooting_empty(authed):
    resp = authed.post("/api/betting/kill", json={})
    assert resp.status_code == 200
    assert resp.json()["canceled"] == 0

    resp = authed.get("/api/betting/rooting")
    assert resp.status_code == 200
    assert resp.json()["rooting"] == []
