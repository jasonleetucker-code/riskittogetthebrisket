"""Master-site-audit W20-F001 regression (CW-40 P1 re-adjudication, 2026-11-06) -- CLOSED by
owner decision 2026-11-07: ``/rosters`` is the primary frontend consumer of the Team Gameplan
(``frontend/components/TeamGameplanSection.jsx`` via the ``frontend/app/api/gameplan`` bridge).

Claim: ``GET /api/gameplan`` (and the ``src/roster_intel`` engine behind it) has zero
frontend consumers -- no page, component, lib or Next bridge route calls it.

Reproduction (offline source scan; the same check as the audit's ``grep``, with
comments excluded): any quoted ``/api/gameplan`` string or a ``frontend/app/api/gameplan``
bridge directory in the shipped frontend source.  Note the SERVER-side consumers are real
(``gameplan.league_competitive_postures`` feeds trade posture, the league-adjusted
overlay reuses the cached league bundle) -- the claim that is still true is only that
the per-team gameplan payload itself reaches no UI.

This test was a strict xfail until the /rosters consumer landed; it now asserts the consumer.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
_CALL = re.compile(r"""["'`]/api/gameplan\b""")


def _frontend_sources():
    for sub in ("app", "components", "lib", "hooks"):
        base = FRONTEND / sub
        if not base.is_dir():
            continue
        for ext in ("*.js", "*.jsx", "*.mjs", "*.ts", "*.tsx"):
            yield from base.rglob(ext)


def _consumers() -> list[str]:
    hits = []
    for path in _frontend_sources():
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if _CALL.search(line):
                hits.append(str(path.relative_to(REPO)))
                break
    return hits


def test_backend_endpoint_is_registered():
    assert '@app.get("/api/gameplan")' in (REPO / "server.py").read_text(encoding="utf-8")


def test_a_frontend_surface_consumes_the_gameplan_endpoint():
    assert _consumers() or (FRONTEND / "app" / "api" / "gameplan").is_dir()


def test_rosters_is_the_consumer_and_the_bridge_exists():
    # Owner decision 2026-11-07: /rosters, not some other page, consumes it.
    assert (FRONTEND / "app" / "api" / "gameplan" / "route.js").is_file()
    rosters = (FRONTEND / "app" / "rosters" / "page.jsx").read_text(encoding="utf-8")
    assert "TeamGameplanSection" in rosters
    section = (FRONTEND / "components" / "TeamGameplanSection.jsx").read_text(encoding="utf-8")
    assert '"/api/gameplan"' in section
