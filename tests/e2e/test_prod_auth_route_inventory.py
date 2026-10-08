"""Every private route release train 2 shipped is exercised by a prod-auth spec.

Release train 2 (merge ``bc51e7e2d``) shipped private API surfaces that the
post-deploy "V1 Authenticated Production Verification" workflow did not touch,
so the completion ledger could only record them DEPLOYED_NOT_PRODUCTION_VERIFIED.
``tests/e2e/specs/prod-auth/train2-private-surfaces.spec.js`` closes that gap.

This guard keeps it closed, statically, in the fast pytest gate:

* the inventory below is NON-VACUOUS — each route is still declared by the
  backend (a renamed route fails here instead of silently leaving a spec that
  probes a 404 path forever);
* each route is REFERENCED IN CODE (not merely in a comment) by at least one
  prod-auth spec;
* the prod-auth specs stay READ-ONLY against production: the only non-GET
  ``page.request`` calls are the allowlisted ones, and the single PUT (the
  guest trade-protections refusal) is preceded by the guest-pass precondition
  and carries a body the server would reject anyway;
* ``@desktop-only`` titles are filtered from the mobile project at
  collection (``grepInvert``), not collected and skipped.

There is no other prod-auth route inventory in the repo; this module IS it for
the train-2 surfaces. Add a row when a release ships a private route the
production workflow should prove.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = REPO_ROOT / "tests" / "e2e"
PROD_AUTH_DIR = E2E_DIR / "specs" / "prod-auth"
SERVER = REPO_ROOT / "server.py"
PROD_AUTH_CONFIG = E2E_DIR / "prod-auth.config.js"

#: route path (as the spec requests it, path params elided to their static
#: prefix) -> (file that declares it, regex proving the declaration, ledger ids)
TRAIN2_PRIVATE_ROUTES: dict[str, tuple[Path, str, tuple[str, ...]]] = {
    "/api/model-lab": (
        REPO_ROOT / "src" / "model_registry" / "model_lab_api.py",
        r'APIRouter\(prefix="/api/model-lab"',
        ("AL-0b",),
    ),
    "/api/user/trade-protections": (
        SERVER,
        r'@app\.(get|put)\("/api/user/trade-protections"\)',
        ("C3-CON-02",),
    ),
    "/api/players/": (
        SERVER,
        r'@app\.get\("/api/players/\{player\}/value-movement"\)',
        ("UI-contract§10/value-movement",),
    ),
    "/value-movement": (
        SERVER,
        r'@app\.get\("/api/players/\{player\}/value-movement"\)',
        ("UI-contract§10/value-movement",),
    ),
    "/api/roster/intelligence": (
        SERVER,
        r'@app\.get\("/api/roster/intelligence"\)',
        ("C2-CORE-01", "C2-DROP-01", "C2-WEAK-01"),
    ),
    "/api/ros/pick-projections": (
        REPO_ROOT / "src" / "ros" / "api.py",
        r'@router\.get\("/pick-projections"\)',
        ("PICK-PROJECTOR-1652", "#1652", "C1-PICK-03"),
    ),
    "/api/signals/reconciled": (
        SERVER,
        r'@app\.get\("/api/signals/reconciled"\)',
        ("C6-SIG-01",),
    ),
    "/api/league/player-impact": (
        SERVER,
        r'@app\.get\("/api/league/player-impact"\)',
        ("C5-WAR-01",),
    ),
}

#: Pages whose train-2 render the specs drive (route → the page file).
TRAIN2_PAGES: dict[str, Path] = {
    "/players/": REPO_ROOT / "frontend" / "app" / "players" / "[playerId]" / "page.jsx",
    "/waivers": REPO_ROOT / "frontend" / "app" / "waivers" / "page.jsx",
    "/rosters": REPO_ROOT / "frontend" / "app" / "rosters" / "page.jsx",
}

#: The only non-GET calls a prod-auth spec may make itself, and why.
ALLOWED_NON_GET = {
    ("post", "/api/trade/finder"),  # pure computation, mutates nothing
    ("post", "/api/trade/simulate"),  # pure computation, mutates nothing
    ("put", "/api/user/trade-protections"),  # guest-refusal probe, see below
}

_NON_GET_CALL = re.compile(
    r"page\.request\.(post|put|patch|delete|fetch)\(\s*prodUrl\(\s*[`\"']([^`\"'$?]+)"
)


def _code_only(src: str) -> str:
    """Strip comments so a route named in prose is not a probe.

    Block comments are stripped only where they START a line — a glob string
    such as ``"**/api/user/**"`` contains ``/*`` and must not open one."""
    src = re.sub(r"^[ \t]*/\*.*?\*/", "", src, flags=re.S | re.M)
    return "\n".join(re.sub(r"(^|\s)//[^\n]*", "", line) for line in src.splitlines())


def _spec_sources() -> dict[str, str]:
    return {
        p.name: _code_only(p.read_text(encoding="utf-8"))
        for p in sorted(PROD_AUTH_DIR.glob("*.spec.js"))
    }


class TestTrain2RoutesAreProductionVerified(unittest.TestCase):
    def test_inventory_routes_are_still_declared(self) -> None:
        for route, (path, pattern, _rows) in TRAIN2_PRIVATE_ROUTES.items():
            with self.subTest(route=route):
                self.assertTrue(path.exists(), f"{path} is gone")
                self.assertRegex(
                    path.read_text(encoding="utf-8"),
                    pattern,
                    f"{route} is no longer declared where the inventory says — "
                    "update the inventory AND the prod-auth spec that probes it",
                )
        for page, path in TRAIN2_PAGES.items():
            with self.subTest(page=page):
                self.assertTrue(path.exists(), f"{page} page file {path} is gone")

    def test_every_inventory_route_is_probed_by_a_prod_auth_spec(self) -> None:
        sources = _spec_sources()
        self.assertGreater(len(sources), 5, "the prod-auth spec glob stopped matching")
        missing = [
            f"{route} (ledger: {', '.join(rows)})"
            for route, (_p, _pat, rows) in TRAIN2_PRIVATE_ROUTES.items()
            if not any(route in code for code in sources.values())
        ]
        missing += [
            f"page {page}"
            for page in TRAIN2_PAGES
            if not any(
                f'prodUrl("{page}' in code or f"prodUrl(`{page}" in code
                for code in sources.values()
            )
        ]
        self.assertEqual(
            missing,
            [],
            "These train-2 private surfaces are not exercised by any prod-auth "
            "spec, so the post-deploy workflow cannot move their ledger rows past "
            "DEPLOYED_NOT_PRODUCTION_VERIFIED:\n" + "\n".join(missing),
        )

    def test_prod_auth_specs_make_only_allowlisted_writes(self) -> None:
        offenders: list[str] = []
        for name, code in _spec_sources().items():
            for m in _NON_GET_CALL.finditer(code):
                method, path = m.group(1), m.group(2).split("?")[0]
                if (method, path) not in ALLOWED_NON_GET:
                    offenders.append(f"{name}: {method.upper()} {path}")
        self.assertEqual(
            offenders,
            [],
            "A prod-auth spec makes a non-GET request that is not on the "
            "read-only allowlist. These specs run against PRODUCTION with a "
            "real session; a new write needs an explicit, reviewed reason.\n"
            + "\n".join(offenders),
        )

    def test_the_trade_protections_put_is_guarded_and_cannot_write(self) -> None:
        """The one PUT is sent only from a proven guest-pass session, and its
        body carries an unknown field, so even a regressed guest gate answers
        400 invalid_body instead of writing user_kv."""
        code = _spec_sources()["train2-private-surfaces.spec.js"]
        put_at = code.index("page.request.put(")
        before = code[:put_at]
        self.assertIn('toBe("guest_pass")', before, "the PUT lost its guest-pass precondition")
        self.assertIn("prodVerificationNeverWrites", code[put_at : put_at + 600])
        self.assertEqual(code.count("page.request.put("), 1, "exactly one PUT is allowed")

    def test_desktop_only_titles_are_filtered_from_mobile_at_collection(self) -> None:
        cfg = PROD_AUTH_CONFIG.read_text(encoding="utf-8")
        mobile = cfg[cfg.index('name: "prod-mobile"') :]
        self.assertIn("grepInvert: /@desktop-only/", mobile[: mobile.index("use:")])
        code = _spec_sources()["train2-private-surfaces.spec.js"]
        self.assertIn("@desktop-only", code)
        self.assertNotIn(
            "desktopOnly(",
            code,
            "use the @desktop-only tag (filtered at collection), not a runtime skip",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
