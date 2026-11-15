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
* the prod-auth specs stay READ-ONLY against production: every non-GET the
  spec CODE itself sends — through ANY request context, a template-built URL,
  or a ``fetch`` with a ``method`` option — must be allowlisted, and the single
  PUT (the guest trade-protections refusal) is preceded, in the same test, by
  the guest-pass precondition and carries a body the server would reject;
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

#: ``<receiver>.post|put|patch|delete|fetch(<first arg>`` on ANY receiver —
#: ``page.request``, the ``request`` fixture, ``context.request``, an
#: ``APIRequestContext`` variable, ``route.fetch`` ...
_WRITE_CALL = re.compile(
    r"(?P<recv>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\.(?P<method>post|put|patch|delete|fetch)"
    r"\(\s*(?P<arg>[^\n]*)"
)
#: A receiver that is (or wraps) an HTTP client: always analysed, whatever
#: its argument looks like.
_HTTP_RECEIVER = re.compile(r"request|context|api|route|client|http", re.I)
#: An explicit write method passed as an option — ``fetch(url, {method: "PUT"})``
#: inside ``page.evaluate``, or ``request.fetch(url, {method: ...})``.
_METHOD_OPTION = re.compile(r"\bmethod\s*:\s*[`\"'](POST|PUT|PATCH|DELETE)[`\"']", re.I)
#: The start of a Playwright test body.
_TEST_START = re.compile(r"\btest\(\s*[`\"']")


def _literal_target(arg: str) -> str | None:
    """The static path a call targets, or ``None`` when it cannot be read.

    ``prodUrl(`/a/b${qs}`)`` → ``/a/b`` (a template may only APPEND to a
    literal path); a template that STARTS with ``${`` or a bare variable is
    unresolvable."""
    m = re.match(r"prodUrl\(\s*([`\"'])(.*?)\1", arg) or re.match(r"([`\"'])(.*?)\1", arg)
    if not m:
        return None
    literal = m.group(2)
    if "${" in literal:
        literal = literal[: literal.index("${")]
    literal = literal.split("?")[0]
    return literal or None


def _line(code: str, offset: int) -> int:
    return code.count("\n", 0, offset) + 1


def non_get_offenders(name: str, code: str) -> list[str]:
    """Every non-GET request a spec's CODE makes that is not allowlisted."""
    offenders: list[str] = []
    for m in _WRITE_CALL.finditer(code):
        recv, method, arg = m.group("recv"), m.group("method"), m.group("arg")
        urlish = arg.lstrip().startswith(("prodUrl(", "`", '"', "'")) and (
            "/api" in arg or "http" in arg or "prodUrl(" in arg or "${" in arg
        )
        if not (_HTTP_RECEIVER.search(recv) or urlish):
            continue  # e.g. ``someMap.delete(key)``
        where = f"{name}:{_line(code, m.start())}"
        target = _literal_target(arg)
        if method == "fetch":
            offenders.append(f"{where}: {recv}.fetch(...) — use an explicit get/post/put")
        elif target is None:
            offenders.append(f"{where}: {method.upper()} to an unresolvable target")
        elif (method, target) not in ALLOWED_NON_GET:
            offenders.append(f"{where}: {method.upper()} {target}")
    for m in _METHOD_OPTION.finditer(code):
        where = f"{name}:{_line(code, m.start())}"
        offenders.append(f"{where}: explicit method {m.group(1).upper()} in request options")
    return offenders


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
            offenders += non_get_offenders(name, code)
        self.assertEqual(
            offenders,
            [],
            "A prod-auth spec makes a non-GET request that is not on the "
            "read-only allowlist. These specs run against PRODUCTION with a "
            "real session; a new write needs an explicit, reviewed reason.\n"
            + "\n".join(offenders),
        )

    def test_the_write_detector_is_not_vacuous(self) -> None:
        """Each evasion the detector must catch, caught."""
        cases = {
            "template target": "await page.request.put(prodUrl(`${base}/api/user/state`), {});",
            "other path, template": "await page.request.post(prodUrl(`/api/user/state${q}`));",
            "fixture context": 'await request.delete(prodUrl("/api/user/trade-protections"));',
            "context.request": 'await context.request.patch(prodUrl("/api/user/state"), {});',
            "api var": "const r = await api.put(url);",
            "evaluate fetch": (
                'await page.evaluate(() => fetch("/api/user/state", { method: "PUT" }));'
            ),
            "request.fetch": 'await page.request.fetch(prodUrl("/api/x"), { method: "GET" });',
        }
        for label, snippet in cases.items():
            with self.subTest(label):
                self.assertTrue(non_get_offenders("x.spec.js", snippet), f"missed: {label}")
        # ...and the allowlisted forms, plus an unrelated Map.delete, pass.
        clean = "\n".join(
            [
                "await page.request.put(prodUrl(`/api/user/trade-protections${qs}`), {});",
                'await page.request.post(prodUrl("/api/trade/finder"), {});',
                "seen.delete(key);",
            ]
        )
        self.assertEqual(non_get_offenders("x.spec.js", clean), [])

    def test_the_trade_protections_put_is_guarded_and_cannot_write(self) -> None:
        """The one PUT is sent only from a proven guest-pass session — checked
        INSIDE THE SAME TEST, before the request — and its body carries an
        unknown field, so even a regressed guest gate answers 400
        invalid_body instead of writing user_kv."""
        code = _spec_sources()["train2-private-surfaces.spec.js"]
        self.assertEqual(code.count("page.request.put("), 1, "exactly one PUT is allowed")
        put_at = code.index("page.request.put(")
        tests_before = list(_TEST_START.finditer(code, 0, put_at))
        self.assertTrue(tests_before, "the PUT is not inside a test")
        same_test = code[tests_before[-1].start() : put_at]
        self.assertIn(
            'toBe("guest_pass")',
            same_test,
            "the guest-pass precondition must run in the same test, before the PUT",
        )
        self.assertIn("prodVerificationNeverWrites", code[put_at : put_at + 600])

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
