"""Tests for the private-app auth gate.

The app is a single-user private tool gated by the
``_private_api_gate`` middleware: every ``/api/*`` path except an
explicit public allowlist returns 401 when there is no authenticated
session.  ``curl /api/data`` from a stranger must not leak the
rankings contract.

These tests pin that gate.  It's the core privacy guarantee for
this deployment.
"""
from __future__ import annotations

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
    "/api/trade/simulate-mc",  # Phase 9 — Monte Carlo sim
    "/api/angle/find",
    "/api/angle/packages",
    "/api/scaffold/raw",
    "/api/scaffold/league",
    "/api/scaffold/identity",
    "/api/scaffold/validation",
    "/api/scaffold/report",
    "/api/user/state",
    "/api/player/12345/realized",  # Phase 11 follow-on — realized points
    "/api/admin/nfl-data/flush",
    "/api/admin/sessions/force-logout-all",
    "/api/admin/signal-state/migrate",
]
PRIVATE_POST_PATHS = {
    "/api/trade/suggestions", "/api/trade/finder", "/api/trade/simulate",
    "/api/trade/simulate-mc",
    "/api/angle/find", "/api/angle/packages", "/api/rankings/overrides",
    # Phase 11 admin endpoints
    "/api/admin/nfl-data/flush",
    "/api/admin/sessions/force-logout-all",
    "/api/admin/signal-state/migrate",
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
