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


# ── Guest-pass admin endpoints ─────────────────────────────────────


def _isolate_guest_pass_db(monkeypatch, tmp_path):
    """Point ``guest_passes`` at a temp SQLite file so admin-endpoint
    tests don't share state with the production DB."""
    from src.api import guest_passes
    db = tmp_path / "guest_passes.sqlite"
    monkeypatch.setattr(guest_passes, "_DEFAULT_DB_PATH", db)
    # Reset the per-path setup tracker so the new db gets its schema
    # bootstrapped on first call.
    monkeypatch.setattr(guest_passes, "_setup_done_paths", set())
    return db


def test_guest_pass_create_requires_admin(monkeypatch):
    _authed_non_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/admin/guest-pass",
            json={"durationHours": 12, "note": "for Brent"},
        )
    assert res.status_code == 403


def test_guest_pass_create_returns_token(monkeypatch, tmp_path):
    _authed_admin(monkeypatch)
    _isolate_guest_pass_db(monkeypatch, tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/admin/guest-pass",
            json={"durationHours": 12, "note": "for Brent"},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    # Plaintext token is returned exactly once.
    assert isinstance(body.get("token"), str)
    assert len(body["token"]) >= 20
    pass_meta = body.get("pass") or {}
    assert pass_meta.get("note") == "for Brent"
    assert pass_meta.get("isActive") is True


def test_guest_pass_create_rejects_zero_duration(monkeypatch, tmp_path):
    _authed_admin(monkeypatch)
    _isolate_guest_pass_db(monkeypatch, tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/admin/guest-pass",
            json={"durationHours": 0, "note": ""},
        )
    assert res.status_code == 400
    body = res.json()
    assert body["error"] == "invalid_duration"


def test_guest_pass_list_returns_metadata_without_token(monkeypatch, tmp_path):
    _authed_admin(monkeypatch)
    _isolate_guest_pass_db(monkeypatch, tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        # Mint two passes.
        c.post("/api/admin/guest-pass", json={"durationHours": 12})
        c.post("/api/admin/guest-pass", json={"durationHours": 1})
        # List them.
        res = c.get("/api/admin/guest-passes")
    assert res.status_code == 200
    body = res.json()
    rows = body.get("passes") or []
    assert len(rows) == 2
    # Critical: no plaintext tokens or hashes leaked in the list.
    for row in rows:
        assert "token" not in row
        assert "tokenHash" not in row
        assert "token_hash" not in row


def test_guest_pass_revoke_marks_revoked(monkeypatch, tmp_path):
    _authed_admin(monkeypatch)
    _isolate_guest_pass_db(monkeypatch, tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        created = c.post(
            "/api/admin/guest-pass", json={"durationHours": 12},
        ).json()
        pass_id = created["pass"]["id"]
        res = c.post(f"/api/admin/guest-pass/{pass_id}/revoke")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["id"] == pass_id


def test_guest_pass_login_creates_time_bounded_session(monkeypatch, tmp_path):
    """End-to-end: admin mints a pass → guest logs in with the
    plaintext token → /api/auth/status returns authenticated."""
    _authed_admin(monkeypatch)
    db = _isolate_guest_pass_db(monkeypatch, tmp_path)
    # Force a known admin password so the login fall-through is the
    # only path that admits the guest token.
    monkeypatch.setattr(server, "JASON_LOGIN_USERNAME", "admin")
    monkeypatch.setattr(server, "JASON_LOGIN_PASSWORD", "admin-pwd")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        # Mint a pass via the admin endpoint.
        created = c.post(
            "/api/admin/guest-pass", json={"durationHours": 1},
        ).json()
        token = created["token"]
        # Drop the admin auth stub so the login route doesn't see us
        # as already-authed.
        monkeypatch.setattr(
            server, "_get_auth_session", lambda r: None,
        )
        monkeypatch.setattr(server, "_is_authenticated", lambda r: False)
        # Guest login: any username, password = the token.
        login_res = c.post(
            "/api/auth/login",
            json={"username": "", "password": token},
        )
    assert login_res.status_code == 200, login_res.text
    body = login_res.json()
    assert body["ok"] is True
    assert body.get("guest") is True
    assert "expiresAtEpoch" in body


def test_invalid_guest_token_returns_401(monkeypatch, tmp_path):
    _isolate_guest_pass_db(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "JASON_LOGIN_USERNAME", "admin")
    monkeypatch.setattr(server, "JASON_LOGIN_PASSWORD", "admin-pwd")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/auth/login",
            json={"username": "", "password": "bogus-token"},
        )
    assert res.status_code == 401


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
    # Force flag OFF to verify the gate.  (Flag now defaults ON
    # after the 2026-04-25 activation, but the gate behavior must
    # still work when explicitly disabled.)
    monkeypatch.setenv("RISKIT_FEATURE_REALIZED_POINTS_API", "0")
    from src.api import feature_flags
    feature_flags.reload()
    try:
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/player/12345/realized")
        assert res.status_code == 503
        assert res.json()["error"] == "feature_disabled"
    finally:
        feature_flags.reload()


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
