"""Every Next.js page must be reachable through this backend.

Page routes used to be registered one-by-one in ``server.py``, i.e. a
hand-maintained mirror of another router's route table.  It drifted
three separate times: ``/waivers``, ``/news`` and ``/draft`` were all
404 here while serving fine from Next, along with ``/angle``,
``/trending``, ``/players/compare``, ``/league-comparison``,
``/idptc-rookies``, ``/tools/ros-data-health``, ``/rankings/[position]``
and every ``/league/*`` subroute.

``server.py`` now ends with a catch-all that forwards anything
unclaimed to Next.  These tests pin the properties that made the
drift possible in the first place, so it cannot come back:

  * no Next page 404s at the backend,
  * the catch-all never swallows API or asset traffic,
  * auth gating still applies to pages that need it.

They fail loudly against the pre-catch-all server.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "frontend" / "app"


def _next_page_routes() -> list[str]:
    """Derive the Next.js route table from the App Router file tree.

    Deriving it here rather than hardcoding is the point: a new page
    joins this test automatically, which is exactly the property the
    hand-maintained list lacked.

    Dynamic segments (``[position]``) and route groups are skipped —
    they need a real parameter value to fetch, and the static routes
    already prove the catch-all is wired.
    """
    routes: list[str] = []
    for page in APP_DIR.rglob("page.jsx"):
        rel = page.relative_to(APP_DIR).parent.as_posix()
        route = "/" if rel == "." else "/" + rel
        if "[" in route or "(" in route or route.startswith("/api"):
            continue
        routes.append(route)
    return sorted(set(routes))


def test_next_page_tree_is_discoverable():
    """Guard the guard: if this returns nothing, the coverage test
    below would vacuously pass and the drift could return unseen."""
    routes = _next_page_routes()
    assert len(routes) > 20, f"expected a populated Next route tree, got {routes}"
    # Spot-check the three that actually drifted.
    for drifted in ("/waivers", "/news", "/draft"):
        assert drifted in routes, f"{drifted} missing from the derived route tree"


@pytest.mark.parametrize("route", _next_page_routes())
def test_every_next_page_is_routable(route):
    """No Next page may 404 at the backend.

    The backend is expected to be up while Next is not, so a 503
    ("frontend unavailable") is a pass — that is the proxy correctly
    reporting a missing upstream.  A 3xx to /login is a pass too: the
    route resolved and the auth gate fired.  Only a 404 means the
    route does not exist here, which is the drift this pins.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get(route, follow_redirects=False)
    assert res.status_code != 404, (
        f"{route} is a Next page but 404s at the backend — "
        "the page-route catch-all is missing or shadowed"
    )
    assert res.status_code != 405, f"{route} rejected GET"


def test_catch_all_does_not_swallow_unknown_api_paths():
    """An unknown ``/api/*`` path must stay a JSON error, never get
    proxied to Next as if it were a page.

    401 rather than 404 is the correct answer here: ``_private_api_gate``
    runs as middleware, ahead of routing, and rejects any ``/api/*`` path
    outside the public allowlist without disclosing whether it exists.
    Either status proves the point — what must NOT happen is an HTML
    page body coming back from the frontend proxy.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/definitely-not-a-real-endpoint", follow_redirects=False)
    assert res.status_code in (401, 404), (
        f"unknown /api path returned {res.status_code} — if this is a 2xx the "
        "catch-all is proxying API traffic to Next"
    )
    assert "application/json" in res.headers.get("content-type", "")


def test_catch_all_still_gates_private_pages():
    """Pages behind the auth gate must still redirect when signed out —
    the catch-all must not become an accidental way around it."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/waivers", follow_redirects=False)
    assert res.status_code in (
        302,
        303,
        307,
    ), f"/waivers should redirect an anonymous visitor, got {res.status_code}"
    assert "/login" in res.headers.get("location", "")


def test_catch_all_keeps_public_league_subroutes_public():
    """``/league`` and its subroutes hydrate from the public pipeline
    and must not demand a session."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/league/activity", follow_redirects=False)
    assert res.status_code not in (
        302,
        303,
        307,
    ), "/league/activity is public and must not redirect to login"
    assert res.status_code != 404
