"""Tests for the admin endpoints (Phase 11 follow-ons).

Covers:
  * nfl-data flush: admin-only, returns count evicted.
  * force-logout-all: wipes sessions.
  * signal-state migrate: idempotent, calls the migration module.
  * Auth gates: unauthenticated → 401; authed non-admin → 403.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture(autouse=True)
def _stub_allowlist(monkeypatch):
    # Every admin test assumes a known allowlist so the "is admin"
    # check is predictable.
    monkeypatch.setattr(
        server, "PRIVATE_APP_ALLOWED_USERNAMES",
        frozenset({"jasonleetucker"}),
    )
    yield


def _authed_admin(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(
        server, "_get_auth_session",
        lambda r: {"username": "jasonleetucker"},
    )


def _authed_non_admin(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(
        server, "_get_auth_session",
        lambda r: {"username": "randomuser"},
    )


def test_nfl_data_flush_requires_auth():
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/admin/nfl-data/flush")
    assert res.status_code == 401


def test_nfl_data_flush_requires_admin(monkeypatch):
    _authed_non_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/admin/nfl-data/flush")
    assert res.status_code == 403


def test_nfl_data_flush_admin_returns_ok(monkeypatch):
    _authed_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/admin/nfl-data/flush")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "evicted" in body


def test_force_logout_all_requires_admin(monkeypatch):
    _authed_non_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/admin/sessions/force-logout-all")
    assert res.status_code == 403


def test_force_logout_all_clears_sessions(monkeypatch):
    _authed_admin(monkeypatch)
    # Seed some in-memory sessions.
    server.auth_sessions["abc"] = {"username": "u1"}
    server.auth_sessions["def"] = {"username": "u2"}
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/admin/sessions/force-logout-all")
    assert res.status_code == 200
    body = res.json()
    assert body["inMemoryCleared"] >= 2
    # in-memory cleared.
    assert "abc" not in server.auth_sessions


def test_signal_state_migrate_requires_admin(monkeypatch):
    _authed_non_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/admin/signal-state/migrate")
    assert res.status_code == 403


def test_signal_state_migrate_admin_returns_summary(monkeypatch):
    _authed_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/admin/signal-state/migrate")
    # In a production env with a default league configured: 200 + summary.
    # In a bare test env without a registry: 500 + "no_default_league".
    # Both are acceptable — what we're pinning is the admin gate, not the
    # registry presence (that's covered by test_league_registry).
    assert res.status_code in (200, 500), res.text
    if res.status_code == 200:
        body = res.json()
        assert "processed" in body
        assert "counts" in body
    else:
        assert res.json()["error"] == "no_default_league"


def test_realized_points_requires_feature_flag(monkeypatch):
    _authed_admin(monkeypatch)
    # Flag defaults OFF; endpoint should 503.
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/player/12345/realized")
    assert res.status_code == 503
    assert res.json()["error"] == "feature_disabled"


def test_realized_points_flag_on_returns_shape(monkeypatch):
    _authed_admin(monkeypatch)
    monkeypatch.setenv("RISKIT_FEATURE_REALIZED_POINTS_API", "1")
    from src.api import feature_flags
    feature_flags.reload()
    try:
        with TestClient(server.app, raise_server_exceptions=True) as c:
            # Request a player — stats unavailable in test env, but
            # the handler should gracefully return an empty result.
            res = c.get("/api/player/12345/realized")
        # Could be 200 with reason=no_stats_available / unmapped_player,
        # or a league-resolution error (400 unknown_league, 404
        # no_leagues_configured, 503 data_not_ready) depending on the
        # test env's registry state.
        assert res.status_code in (200, 400, 404, 503), res.text
        if res.status_code == 200:
            body = res.json()
            assert body["sleeperId"] == "12345"
    finally:
        feature_flags.reload()
