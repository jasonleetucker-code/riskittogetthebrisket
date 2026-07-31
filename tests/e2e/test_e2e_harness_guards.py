"""Guards on the Playwright harness itself, run by the FAST pytest gate.

Why these live in pytest rather than in the Playwright suite: the two
failure modes below are exactly the ones the browser suite cannot report
usefully, because both make it fail *everywhere at once* and therefore
look like a broken product rather than a broken harness.

Measured on nightly run 30529404019 (2026-07-30, 19 failed / 118
passed):

* **11 of 19 failures were one missing ``pageUrl()`` wrapper.**
  Navigation in the E2E suite must go through ``pageUrl()``;
  a bare ``page.goto("/rankings")`` resolves against ``baseURL``, which
  is the FastAPI page proxy.  ``_proxy_next`` forwards no cookies
  (``server.py:2891-2896``; ``server.py:12539-12545`` states it
  outright), so once ``frontend/middleware.js`` landed on 2026-07-29
  every such navigation 307'd to ``/login``.  Six rankings journeys, the
  settings-override round-trip, two mobile smokes and two chart smokes
  all reported "rankings board should render rows / element(s) not
  found" — which reads like a dead value pipeline and was a dead cookie.
  In the SAME run a spec that navigated correctly dumped a board with
  968 players and 200 rendered rows.

* **4 more were one rename.**  PR #625's naming canon renamed
  "Trade Builder" → "Trade Calculator" and "Roster Dashboard" →
  "Team Strength".  The frontend half of the canon was pinned by a
  vitest test; the E2E half hardcoded the old strings in three
  different files.  ``tests/e2e/specs/`` had not been touched since
  2026-07-27 — two days before the rename.

Both guards run in ``pr-validation.yml``'s blocking pytest step, so the
next occurrence fails in seconds on the PR instead of overnight in a
suite that is already red and therefore ignored.

The deeper reason this file exists at all: a guard is worthless if its
stated purpose and its actual predicate differ
(``docs/ORCHESTRATION.md`` §6.15).  Both guards below are written so
that reintroducing the exact defect they describe makes them fail —
verified by doing it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = REPO_ROOT / "tests" / "e2e"
JOURNEY_HELPER = E2E_DIR / "helpers" / "journey.js"
FRONTEND_CANON = REPO_ROOT / "frontend" / "__tests__" / "helpers" / "naming-canon.js"

# ``page.goto("/…")`` without pageUrl().  Matches the LITERAL-path form
# only.
#
# The original comment here justified that as "template literals and
# variables are all fine because they cannot be the bare-baseURL
# mistake". That was wrong, and wrong in the specific way this whole file
# exists to catch — a guard whose stated purpose and actual predicate
# differ (docs/ORCHESTRATION.md §6.15).
#
# ``critical-smoke.spec.js`` iterates PUBLIC_ROUTES / AUTH_GATED_ROUTES
# and calls ``page.goto(path)`` with a variable holding "/rankings",
# "/trade"… which lands on baseURL exactly like the literal form. It is
# CORRECT there — those tests assert the backend's own anonymous-access
# behaviour and must not be rerouted to :3000 — but it is correct by
# intent, not because the variable form is inherently safe.
#
# So the honest statement of the rule is narrower than "navigations must
# go through pageUrl()": this guard catches the literal form, which is
# the shape the 11-of-19 nightly regression actually took
# (``gotoRankingsBoard`` had a hardcoded ``page.goto("/rankings")``).
# The variable form is deliberately out of scope because distinguishing
# "iterating routes to test the proxy" from "forgot the wrapper" needs
# intent a regex does not have.
_BARE_GOTO = re.compile(r"""\.goto\(\s*["'](/[^"']*)["']""")

# The one deliberate exemption.  auth-fixture reloads "/" purely to let
# the browser context pick up the cookies ``page.request`` just set;
# "/" is public (``frontend/lib/public-routes.js``) so it does not
# redirect, and the reload's whole point is to exercise the same origin
# the session was minted against.  Documented rather than silently
# skipped — an undocumented entry here is how this guard would rot.
_GOTO_EXEMPT = {
    ("helpers/auth-fixture.js", "/"): (
        "cookie-priming reload immediately after POST "
        "/api/test/create-session; '/' is public so it cannot 307, and "
        "the reload must stay on the origin the session was minted on"
    ),
}

# Names PR #625 retired.  An assertion still matching one of these is a
# rename that only half landed.
_RETIRED_NAMES = (
    "Trade Builder",
    "Roster Dashboard",
    "Signal Blotter",
    "Counter-Pitch",
    "Arbitrage Finder",
    "Dynasty Trade Calculator",
)


def _code_only(line: str) -> str:
    """The executable part of a JS line, comments removed.

    Needed because the helper and the specs both DESCRIBE the defects
    below in prose, quoting the offending call verbatim — so a scanner
    that reads comments flags its own documentation. (It did, first
    run.) Trailing comments are cut at " // " rather than "//" so a URL
    scheme like ``https://`` is never mistaken for a comment.
    """
    stripped = line.lstrip()
    if stripped.startswith("//") or stripped.startswith("*"):
        return ""
    return line.split(" // ", 1)[0]


def _parse_js_string_map(text: str, var_name: str) -> dict[str, str]:
    """Extract a ``const NAME = { "k": "v", … }`` map from JS source.

    Narrow on purpose, matching the idiom in
    ``tests/api/test_source_registry_parity.py``: read the source as
    text, find the object literal, and pull only the string→string
    entries.  Comments and non-string values are skipped, so an unusual
    edit to the map's shape surfaces as a missing key in the diff rather
    than being silently tolerated.
    """
    start = re.search(
        r"(?:const|export\s+const)\s+" + re.escape(var_name) + r"\s*=\s*\{",
        text,
    )
    if start is None:
        raise AssertionError(f"{var_name} not found — did the map get renamed?")

    # Walk to the matching brace so a nested object can never truncate
    # the parse early.
    i = start.end() - 1
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                body = text[i + 1 : j]
                break
    else:  # pragma: no cover - unbalanced source would fail earlier
        raise AssertionError(f"unbalanced braces while reading {var_name}")

    # Strip line comments so a commented-out entry is not parsed.
    body = re.sub(r"//[^\n]*", "", body)
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r"""["']([^"']+)["']\s*:\s*["']([^"']*)["']""", body)
    }


class TestEveryNavigationGoesThroughPageUrl(unittest.TestCase):
    """A bare ``page.goto("/private")`` silently tests the login page."""

    def test_no_bare_literal_goto_in_the_e2e_suite(self) -> None:
        offenders: list[str] = []
        for path in sorted(E2E_DIR.rglob("*.js")):
            if "node_modules" in path.parts:
                continue
            rel = path.relative_to(E2E_DIR).as_posix()
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                for match in _BARE_GOTO.finditer(_code_only(line)):
                    route = match.group(1)
                    if (rel, route) in _GOTO_EXEMPT:
                        continue
                    offenders.append(f"{rel}:{lineno} -> page.goto({route!r})")

        self.assertEqual(
            offenders,
            [],
            "Navigations must go through pageUrl() — a bare literal path "
            "resolves against baseURL (the cookie-less FastAPI page "
            "proxy), so the spec asserts against /login instead of the "
            "page it names. This exact defect was 11 of the 19 nightly "
            "failures on 2026-07-30. Wrap the path: "
            "page.goto(pageUrl('/rankings')). If a bare goto is genuinely "
            "correct, add it to _GOTO_EXEMPT with a reason.\n" + "\n".join(offenders),
        )

    def test_every_exemption_is_still_real(self) -> None:
        """An exemption for a call site that no longer exists is rot."""
        for (rel, route), reason in _GOTO_EXEMPT.items():
            path = E2E_DIR / rel
            self.assertTrue(path.exists(), f"exempted file is gone: {rel}")
            found = {
                m.group(1)
                for line in path.read_text(encoding="utf-8").splitlines()
                for m in _BARE_GOTO.finditer(_code_only(line))
            }
            self.assertIn(
                route,
                found,
                f"{rel} no longer contains a bare goto({route!r}) — drop the "
                "exemption rather than leaving a guard hole open.",
            )
            self.assertGreater(len(reason), 40, f"{rel} needs a real reason")


class TestNamingCanonParity(unittest.TestCase):
    """The E2E page-title canon and the frontend canon must agree.

    The frontend half is checked against the REAL nav module by
    ``frontend/__tests__/nav-model.test.js`` (nav label ≡ CANON ≡
    ``pageTitleFor``) and against the page ``<h1>``s by
    ``frontend/__tests__/components/page-title-canon.test.jsx``.  This
    test closes the loop by pinning the E2E copy to that same canon, so
    the chain is complete:

        nav label ≡ pageTitleFor ≡ page <h1> ≡ E2E assertion

    A rename now has to update one map and is told about every other
    place the name is spelled.
    """

    def setUp(self) -> None:
        self.e2e = _parse_js_string_map(JOURNEY_HELPER.read_text(encoding="utf-8"), "TITLE")
        self.frontend = _parse_js_string_map(FRONTEND_CANON.read_text(encoding="utf-8"), "CANON")

    def test_both_canons_are_non_trivial(self) -> None:
        # Guards the guard: an empty parse would make every comparison
        # below vacuously pass.
        self.assertGreaterEqual(len(self.frontend), 15)
        self.assertGreaterEqual(len(self.e2e), 15)

    def test_the_two_canons_cover_the_same_routes(self) -> None:
        only_e2e = sorted(set(self.e2e) - set(self.frontend))
        only_frontend = sorted(set(self.frontend) - set(self.e2e))
        self.assertEqual(
            (only_e2e, only_frontend),
            ([], []),
            "Page-title canon route drift.\n"
            f"  only in tests/e2e/helpers/journey.js TITLE: {only_e2e}\n"
            f"  only in frontend/__tests__/helpers/naming-canon.js CANON: "
            f"{only_frontend}",
        )

    def test_the_two_canons_agree_on_every_title(self) -> None:
        disagreements = {
            route: {"e2e": self.e2e[route], "frontend": self.frontend[route]}
            for route in sorted(set(self.e2e) & set(self.frontend))
            if self.e2e[route] != self.frontend[route]
        }
        self.assertEqual(
            disagreements,
            {},
            "The E2E suite and the frontend disagree about a page's name. "
            "Whichever is wrong, the user-visible symptom is a nav entry "
            "that opens a page called something else.",
        )

    def test_no_retired_name_survives_in_the_canon(self) -> None:
        offenders = [
            f"{route} -> {title}"
            for canon in (self.e2e, self.frontend)
            for route, title in canon.items()
            if title in _RETIRED_NAMES
        ]
        self.assertEqual(offenders, [], "retired page name back in the canon")


class TestNoRetiredNameInE2EAssertions(unittest.TestCase):
    """Catches the rename drift at its actual scene of the crime."""

    def test_specs_do_not_assert_on_retired_page_names(self) -> None:
        offenders: list[str] = []
        for path in sorted((E2E_DIR / "specs").rglob("*.js")):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                # Comments may name retired titles — the helper and the
                # specs both explain the rename in prose.
                code = _code_only(line)
                for retired in _RETIRED_NAMES:
                    if retired in code:
                        offenders.append(
                            f"{path.relative_to(E2E_DIR).as_posix()}:{lineno} "
                            f"asserts on retired name {retired!r}"
                        )
        self.assertEqual(
            offenders,
            [],
            "An E2E assertion still names a page that was renamed. Use "
            "titleFor(route) from tests/e2e/helpers/journey.js so the "
            "canon is the single source of the string.\n" + "\n".join(offenders),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
