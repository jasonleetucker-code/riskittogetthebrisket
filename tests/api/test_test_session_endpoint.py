"""Tests for the E2E-only /api/test/create-session endpoint.

Key invariant: the endpoint 404's (NOT 401) when E2E_TEST_MODE is
off — 401 would leak the endpoint's existence.
"""
from __future__ import annotations

import pytest
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


def test_mode_accepts_common_env_values(monkeypatch):
    """E2E_TEST_MODE accepts 1/true/yes/on (case insensitive)."""
    monkeypatch.setenv("E2E_TEST_SECRET", "s")
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
    for val in ("0", "false", "no", "off", "probably", ""):
        monkeypatch.setenv("E2E_TEST_MODE", val)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post(
                "/api/test/create-session",
                headers={"Authorization": "Bearer s"},
            )
        assert res.status_code == 404, f"E2E_TEST_MODE={val} should remain disabled"
