"""Tests for the private-app auth gate.

The app is a single-user private tool.  Two gates enforce that:

  1. ``PRIVATE_APP_ALLOWED_USERNAMES`` — only whitelisted Sleeper
     usernames can create a Sleeper-auth session.  Anyone else
     with a valid Sleeper handle gets 403.
  2. ``_private_api_gate`` middleware — every ``/api/*`` path
     except an explicit public allowlist returns 401 when there
     is no authenticated session.  ``curl /api/data`` from a
     stranger must not leak the rankings contract.

These tests pin both gates.  They're the core privacy guarantee
for this deployment.
"""
from __future__ import annotations

import io
import json as _json
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

import server


# ── Middleware gate: unauthenticated /api/* is 401 ─────────────────


PRIVATE_API_PATHS = [
    "/api/data",
    "/api/data/rank-history",
    "/api/data/player-source-history",
    "/api/terminal",
    "/api/trade/suggestions",
    "/api/trade/finder",
    "/api/trade/simulate",
    "/api/angle/find",
    "/api/angle/packages",
    "/api/scaffold/raw",
    "/api/scaffold/league",
    "/api/scaffold/identity",
    "/api/scaffold/validation",
    "/api/scaffold/report",
    "/api/user/state",
]
PRIVATE_POST_PATHS = {
    "/api/trade/suggestions", "/api/trade/finder", "/api/trade/simulate",
    "/api/angle/find", "/api/angle/packages", "/api/rankings/overrides",
}


@pytest.mark.parametrize("path", PRIVATE_API_PATHS)
def test_private_api_paths_require_auth(path):
    """Every private endpoint must 401 without a session cookie.
    Single biggest anti-scrape guarantee."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        if path in PRIVATE_POST_PATHS:
            res = c.post(path, json={})
        else:
            res = c.get(path)
    assert res.status_code == 401, (
        f"{path} leaked without auth: {res.status_code} {res.text[:200]}"
    )
    body = res.json()
    assert body.get("error") == "auth_required"


def test_api_rankings_overrides_requires_auth():
    """POST endpoint covered separately because it's on the list
    but needs a non-empty body to reach the actual handler logic.
    Middleware 401 fires before body validation."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/rankings/overrides", json={})
    assert res.status_code == 401
    assert res.json().get("error") == "auth_required"


PUBLIC_API_PATHS = [
    "/api/health",
    "/api/leagues",
    "/api/rankings/sources",
    "/api/auth/status",
    # The public /league page's draft-capital tab reads this.
    # Payload is public Sleeper data (team names + pick values +
    # owners) — keep reachable without auth.
    "/api/draft-capital",
]


@pytest.mark.parametrize("path", PUBLIC_API_PATHS)
def test_public_api_paths_pass_without_auth(path):
    """The public allowlist must stay reachable for monitoring +
    the login flow + the public-league pipeline."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get(path)
    assert res.status_code != 401, (
        f"{path} requires auth unexpectedly: {res.status_code} {res.text[:200]}"
    )


def test_public_league_prefix_passes_without_auth():
    """The /api/public/league/* prefix serves the isolated public
    pipeline and must never 401."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/public/league/metrics")
    # 200 or 503 are both fine — we just don't want the gate's 401.
    assert res.status_code != 401


def test_signal_alerts_run_bypasses_middleware(monkeypatch):
    """The cron endpoint handles its own auth via a bearer token.
    Middleware must let it through so the endpoint's own check
    runs.  Without a valid token the endpoint returns its own
    401 with error ``admin_auth_required`` (distinct from the
    middleware's ``auth_required``)."""
    monkeypatch.setattr(server, "latest_contract_data", None)
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/signal-alerts/run")
    assert res.status_code == 401
    # Error code proves the ENDPOINT's check fired, not middleware.
    assert res.json().get("error") == "admin_auth_required"


# ── Sleeper-login allowlist ────────────────────────────────────────


def _stub_urlopen_for_sleeper(monkeypatch, username: str, user_id: str):
    """Patch urllib to return the stub Sleeper user for one handle.
    Other handles → 404.  League-members lookups → empty list."""
    real = urllib.request.urlopen

    def fake_urlopen(req, timeout=5.0):
        url = getattr(req, "full_url", "") or str(req)
        if f"/v1/user/{username}" in url:
            body = _json.dumps({
                "user_id": user_id,
                "username": username,
                "display_name": username,
            }).encode()
            return io.BytesIO(body)
        if "/v1/user/" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if "/v1/league/" in url and "/users" in url:
            return io.BytesIO(b"[]")
        return real(req, timeout=timeout)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_sleeper_login_rejects_non_allowlisted_user(monkeypatch):
    """Non-allowlisted Sleeper handle → 403 even though the user
    exists on Sleeper.  The core gate against rando sign-ups."""
    monkeypatch.setattr(
        server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"jasonleetucker"}),
    )
    _stub_urlopen_for_sleeper(monkeypatch, "randomuser99", "99999999")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/auth/sleeper-login", json={"username": "randomuser99"})
    assert res.status_code == 403, res.text
    body = res.json()
    assert body.get("ok") is False
    assert "private" in body.get("error", "").lower()


def test_sleeper_login_accepts_allowlisted_user(monkeypatch):
    """Allowlisted username → 200 + session cookie."""
    monkeypatch.setattr(
        server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"allowed_user"}),
    )
    _stub_urlopen_for_sleeper(monkeypatch, "allowed_user", "12345678")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/auth/sleeper-login", json={"username": "allowed_user"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is True
    assert body.get("sleeperUserId") == "12345678"
    # Cookie set.
    set_cookies = res.headers.get_list("set-cookie")
    assert any(server.JASON_AUTH_COOKIE_NAME in ck for ck in set_cookies)


def test_allowlist_reads_env_var_lowercased():
    """Module-level parse must lowercase + split comma-separated
    entries in the env var."""
    import os
    expected = frozenset(
        u.strip().lower()
        for u in "JasonLeeTucker, AnotherUser".split(",")
        if u.strip()
    )
    assert expected == {"jasonleetucker", "anotheruser"}
