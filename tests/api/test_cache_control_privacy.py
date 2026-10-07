"""Parity invariant: auth-gated endpoints must never advertise
``Cache-Control: public``.

``_private_api_gate`` 401s any ``/api/*`` path outside the public
allowlists, but the gated handlers historically stamped
``Cache-Control: public, ...`` on their responses.  A shared cache
(CDN, corporate proxy) honoring that header could serve one user's
authenticated payload to another — today's nginx config adds no shared
cache, so this is defense-in-depth, but the header is simply wrong on
a private response.  Browser (private) caching + If-None-Match
revalidation work identically under ``private``.

The test scans ``server.py`` for literal ``"Cache-Control": "public``
stamps, attributes each to the nearest preceding route decorator, and
asserts that route is public per the gate's own allowlist — so a new
endpoint that copies a public header onto a gated route fails here at
PR time.

Routes extracted from ``server.py`` into an ``APIRouter`` module keep this
coverage: the module is listed in ``SCANNED_SOURCES`` and its
``@router.<verb>(...)`` decorators are attributed the same way
(CLEANUP-4 moved the league narrative-article routes, whose public
stamps the scanner sanity check below depends on).
"""

from __future__ import annotations

import re
from pathlib import Path

import server

SERVER_PY = Path(server.__file__)
ARTICLES_API_PY = SERVER_PY.parent / "src" / "public_league" / "articles_api.py"

#: Files whose route handlers are scanned: ``server.py`` plus each router
#: module extracted from it whose decorators spell the full served path
#: (no ``APIRouter(prefix=...)``).
SCANNED_SOURCES = (SERVER_PY, ARTICLES_API_PY)

_ROUTE_RE = re.compile(r"@(?:app|router)\.(?:get|post|put|delete)\(\s*[\"']([^\"']+)[\"']")
_PUBLIC_STAMP_RE = re.compile(r"\"Cache-Control\":\s*\"public")


def _routes_with_public_stamps() -> list[tuple[int, str]]:
    """(line_number, route_path) for every literal public Cache-Control
    stamp in the scanned sources, attributed to the nearest preceding
    route in the same file."""
    hits: list[tuple[int, str]] = []
    for source in SCANNED_SOURCES:
        current_route = "<module level>"
        for lineno, line in enumerate(source.read_text().split("\n"), start=1):
            m = _ROUTE_RE.search(line)
            if m:
                current_route = m.group(1)
            if _PUBLIC_STAMP_RE.search(line):
                hits.append((lineno, current_route))
    return hits


def _is_public_route(route: str) -> bool:
    # Route templates ({season}, {matchup_id}, ...) — substitute a
    # dummy segment so the gate's prefix matching applies.
    concrete = re.sub(r"\{[^}]+\}", "x", route)
    return server._is_public_api_path(concrete)


def test_public_cache_control_only_on_public_routes():
    offenders = [
        (lineno, route)
        for lineno, route in _routes_with_public_stamps()
        if not _is_public_route(route)
    ]
    assert not offenders, (
        "Auth-gated endpoints stamping 'Cache-Control: public' (must be " f"'private'): {offenders}"
    )


def test_scanner_still_sees_the_legitimate_public_stamps():
    """Guard against the scanner silently matching nothing (regex or
    format drift): the deliberately-public stamps must still be found."""
    routes = {route for _, route in _routes_with_public_stamps()}
    assert "/api/push/public-key" in routes
    assert any(r.startswith("/api/league/articles") for r in routes)
