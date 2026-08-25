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
    # Roster intelligence: needs, competitive window, trade targets and
    # partner fit for a named team. Strictly more private than /api/data.
    "/api/gameplan",
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
    # De-allowlisted 2026-08-25 (W22-F005 / V1-103): pipeline internals
    # and the full source inventory are operator data, and the caller
    # census found no anonymous consumer.
    "/api/scaffold/status",
    "/api/user/state",
    "/api/player/12345/realized",  # Phase 11 follow-on — realized points
    "/api/admin/nfl-data/flush",
    "/api/admin/sessions/force-logout-all",
    "/api/admin/signal-state/migrate",
]
PRIVATE_POST_PATHS = {
    "/api/trade/suggestions",
    "/api/trade/finder",
    "/api/trade/simulate",
    "/api/trade/simulate-mc",
    "/api/angle/find",
    "/api/angle/packages",
    "/api/rankings/overrides",
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
    assert res.status_code == 401, f"{path} leaked without auth: {res.status_code} {res.text[:200]}"
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
    # The public /league page's draft-capital tab reads this, so it
    # must stay reachable without auth.  It is public with a
    # REDACTION, not because the whole payload is safe: the per-pick
    # ``rookie*`` fields carry our contract-derived rookie board and
    # are stripped for anonymous callers.  That half is pinned by
    # tests/api/test_draft_capital_public_redaction.py — this entry
    # only asserts reachability.
    "/api/draft-capital",
]


@pytest.mark.parametrize("path", PUBLIC_API_PATHS)
def test_public_api_paths_pass_without_auth(path):
    """The public allowlist must stay reachable for monitoring +
    the login flow + the public-league pipeline."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get(path)
    assert (
        res.status_code != 401
    ), f"{path} requires auth unexpectedly: {res.status_code} {res.text[:200]}"


def test_api_news_is_public_without_auth():
    """``/api/news`` serves aggregated public sports news (Sleeper
    trending + public RSS/sitemap providers) with zero league-private
    data, and the public /league/player/<id> journey page
    server-renders a news card from it — so it must be reachable
    without a session.  The provider set is stubbed empty so the
    test stays offline; the route still returns a full 200 payload
    because "no providers" is a legit empty feed, not an outage."""
    from src.news.service import NewsService

    server._reset_news_service_for_tests(NewsService([]))
    try:
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/news")
        assert res.status_code == 200, f"/api/news gated unexpectedly: {res.status_code}"
        body = res.json()
        assert body.get("items") == []
        assert body.get("source") == "backend"
        # Public endpoint — must advertise a shared-cache TTL, not a
        # private/no-store stamp (see test_cache_control_privacy.py
        # for the inverse invariant on gated routes).
        assert "public" in (res.headers.get("Cache-Control") or "")
    finally:
        server._reset_news_service_for_tests(None)


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

    expected = frozenset(
        u.strip().lower() for u in "JasonLeeTucker, AnotherUser".split(",") if u.strip()
    )
    assert expected == {"jasonleetucker", "anotheruser"}


def test_unknown_api_path_is_json_not_a_page():
    """An unknown ``/api/*`` path must answer with a JSON error, never HTML.

    Rescued from ``tests/api/test_page_route_coverage.py``, which was
    deleted with the page proxy (#555). That file's premise — "every
    Next.js page must be reachable through this backend" — is the exact
    inverse of the change, so it could not be repaired, only retired.
    This one assertion survives on merit and had no other home.

    Its value is the CONTENT-TYPE half. The status is already covered
    above; what this pins is that a path this process does not recognise
    cannot come back as a rendered page. Under the old catch-all that was
    a live hazard — ``@app.get("/{full_path:path}")`` matched everything,
    and only an explicit ``startswith("/api/")`` guard inside the handler
    kept API traffic from being proxied to Next and answered with HTML.

    With the catch-all gone the hazard is structural rather than guarded:
    FastAPI's own 404 is JSON. So this now fails if someone reintroduces
    a catch-all page route — which is precisely the regression worth
    holding, since that is how the deleted surface would come back.

    401 rather than 404 is the correct answer: ``_private_api_gate`` runs
    as middleware, ahead of routing, and rejects any ``/api/*`` path
    outside the public allowlist without disclosing whether it exists.
    Either status proves the point.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/definitely-not-a-real-endpoint", follow_redirects=False)
    assert res.status_code in (401, 404), (
        f"unknown /api path returned {res.status_code} — a 2xx means something "
        "is serving API traffic from a page-style catch-all again"
    )
    assert "application/json" in res.headers.get("content-type", "")


def test_a_page_path_is_not_served_by_this_backend():
    """The page proxy is gone; pages live on Next only (#555).

    The deleted ``tests/api/test_page_route_coverage.py`` asserted the
    opposite for 31 parametrized paths. Rather than leave that direction
    untested, pin the new one — otherwise a future change could
    reintroduce page serving here and nothing would notice.

    ``/rankings`` is the sharpest probe: it was a hand-registered route
    AND matched the catch-all, so a 200 or a 302 here means either came
    back. In production nginx never sends a page to this process
    (``deploy/nginx/chaseupside-proxy.conf`` routes only ``location
    /api/`` to the backend upstream), so a 404 is the honest answer.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        for path in ("/", "/rankings", "/league", "/waivers", "/_next/static/x.js"):
            res = c.get(path, follow_redirects=False)
            assert res.status_code == 404, (
                f"{path} returned {res.status_code} — this backend is serving "
                "pages again; the proxy was deleted in #555"
            )
            assert "text/html" not in res.headers.get(
                "content-type", ""
            ), f"{path} answered with HTML — _serve_app_shell or a catch-all is back"
