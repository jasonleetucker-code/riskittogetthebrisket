"""Tests for the E2E-only /api/test/create-session endpoint.

Key invariants:
  * the endpoint 404's (NOT 401) when E2E_TEST_MODE is off — 401
    would leak the endpoint's existence;
  * it fails CLOSED when E2E_TEST_USERNAME is unset, instead of
    minting a session for a real, admin-allowlisted account.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import server


def test_endpoint_404s_when_mode_not_set(monkeypatch):
    monkeypatch.delenv("E2E_TEST_MODE", raising=False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/test/create-session",
            headers={"Authorization": "Bearer anything"},
        )
    assert res.status_code == 404


def test_endpoint_404s_when_secret_mismatch(monkeypatch):
    monkeypatch.setenv("E2E_TEST_MODE", "1")
    monkeypatch.setenv("E2E_TEST_SECRET", "correct-secret")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/test/create-session",
            headers={"Authorization": "Bearer wrong-secret"},
        )
    assert res.status_code == 404


def test_endpoint_404s_when_no_auth_header(monkeypatch):
    monkeypatch.setenv("E2E_TEST_MODE", "1")
    monkeypatch.setenv("E2E_TEST_SECRET", "x")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/test/create-session")
    assert res.status_code == 404


def test_endpoint_succeeds_with_valid_mode_and_secret(monkeypatch):
    monkeypatch.setenv("E2E_TEST_MODE", "1")
    monkeypatch.setenv("E2E_TEST_SECRET", "my-secret")
    monkeypatch.setenv("E2E_TEST_USERNAME", "testuser")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/test/create-session",
            headers={"Authorization": "Bearer my-secret"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["username"] == "testuser"
    # Cookie set.
    set_cookies = res.headers.get_list("set-cookie")
    assert any(server.JASON_AUTH_COOKIE_NAME in ck for ck in set_cookies)


def test_endpoint_refuses_when_username_unset(monkeypatch):
    """Fail closed: E2E mode + a correct secret is NOT enough.

    The username used to fall back to the operator's real (admin-
    allowlisted) account, so turning E2E mode on without naming a
    test user minted a real admin session.  There is no default now.
    """
    monkeypatch.setenv("E2E_TEST_MODE", "1")
    monkeypatch.setenv("E2E_TEST_SECRET", "my-secret")
    monkeypatch.delenv("E2E_TEST_USERNAME", raising=False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        # Snapshot INSIDE the context: startup hydrates persisted
        # sessions from disk, so a pre-boot snapshot isn't comparable.
        before = set(server.auth_sessions)
        res = c.post(
            "/api/test/create-session",
            headers={"Authorization": "Bearer my-secret"},
        )
        after = set(server.auth_sessions)
    assert res.status_code == 500
    assert res.json()["error"] == "e2e_username_not_configured"
    # No cookie, and no session minted anywhere.
    assert not res.headers.get_list("set-cookie")
    assert after == before


def test_endpoint_refuses_when_username_blank(monkeypatch):
    """Whitespace-only is the same as unset — no real-account default."""
    monkeypatch.setenv("E2E_TEST_MODE", "1")
    monkeypatch.setenv("E2E_TEST_SECRET", "my-secret")
    monkeypatch.setenv("E2E_TEST_USERNAME", "   ")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/test/create-session",
            headers={"Authorization": "Bearer my-secret"},
        )
    assert res.status_code == 500
    assert res.json()["error"] == "e2e_username_not_configured"


def test_refusal_never_names_a_real_account(monkeypatch):
    """The refusal must not leak (or use) the operator's username."""
    monkeypatch.setenv("E2E_TEST_MODE", "1")
    monkeypatch.setenv("E2E_TEST_SECRET", "my-secret")
    monkeypatch.delenv("E2E_TEST_USERNAME", raising=False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/test/create-session",
            headers={"Authorization": "Bearer my-secret"},
        )
    body = res.text.lower()
    for allowed in server.PRIVATE_APP_ALLOWED_USERNAMES:
        assert allowed not in body
    assert server.JASON_LOGIN_USERNAME.lower() not in body


def test_missing_username_still_404s_before_the_secret_gate(monkeypatch):
    """The misconfiguration report must sit BEHIND the secret check —
    an unauthenticated caller still gets a bare 404, never a 500 that
    confirms the endpoint exists."""
    monkeypatch.setenv("E2E_TEST_MODE", "1")
    monkeypatch.setenv("E2E_TEST_SECRET", "correct-secret")
    monkeypatch.delenv("E2E_TEST_USERNAME", raising=False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/test/create-session",
            headers={"Authorization": "Bearer wrong-secret"},
        )
    assert res.status_code == 404
    assert res.json() == {"error": "not_found"}


def test_mode_accepts_common_env_values(monkeypatch):
    """E2E_TEST_MODE accepts 1/true/yes/on (case insensitive)."""
    monkeypatch.setenv("E2E_TEST_SECRET", "s")
    monkeypatch.setenv("E2E_TEST_USERNAME", "testuser")
    for val in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("E2E_TEST_MODE", val)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post(
                "/api/test/create-session",
                headers={"Authorization": "Bearer s"},
            )
        assert res.status_code == 200, f"E2E_TEST_MODE={val} should enable"


def test_bad_mode_values_still_404(monkeypatch):
    """E2E_TEST_MODE=0/false/no/off/anything_else must NOT enable."""
    monkeypatch.setenv("E2E_TEST_SECRET", "s")
    monkeypatch.setenv("E2E_TEST_USERNAME", "testuser")
    for val in ("0", "false", "no", "off", "probably", ""):
        monkeypatch.setenv("E2E_TEST_MODE", val)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post(
                "/api/test/create-session",
                headers={"Authorization": "Bearer s"},
            )
        assert res.status_code == 404, f"E2E_TEST_MODE={val} should remain disabled"
