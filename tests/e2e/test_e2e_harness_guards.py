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
  was the FastAPI page proxy.  ``_proxy_next`` forwarded no cookies —
  it took a ``path`` string rather than a ``Request``, so it
  structurally could not — and so once ``frontend/middleware.js``
  landed on 2026-07-29 every such navigation 307'd to
  ``/login``.  Six rankings journeys, the
  settings-override round-trip, two mobile smokes and two chart smokes
  all reported "rankings board should render rows / element(s) not
  found" — which reads like a dead value pipeline and was a dead cookie.
  In the SAME run a spec that navigated correctly dumped a board with
  968 players and 200 rendered rows.

  (Those ``server.py`` line citations were removed rather than
  refreshed: the proxy was deleted in #555, so there is no current line
  to point at.  They had already gone stale once — the second span had
  drifted onto an unrelated ``/api/`` docstring — which is the argument
  against citing line numbers in prose at all.  The failure mode this
  guard catches is unchanged; only its blast radius shrank, because a
  bare goto now 404s loudly instead of quietly rendering /login.)

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
# The original comment justified that as "variables are all fine because
# they cannot be the bare-baseURL mistake" — wrong, in the exact way this
# file exists to catch (docs/ORCHESTRATION.md §6.15). It was corrected to
# say the variable form was out of scope because ``critical-smoke.spec.js``
# iterated route arrays through ``page.goto(path)`` and was CORRECT to:
# those tests asserted the backend page proxy's own anonymous-access
# behaviour and must not be rerouted to :3000.
#
# **That exception is now gone.** #555 deleted the page proxy. The backend
# has no anonymous-access page behaviour to assert, because it serves no
# pages — every page path 404s there. critical-smoke now navigates through
# pageUrl() like everything else, and there is no longer ANY navigation in
# this suite that should resolve against baseURL.
#
# So the rule is finally as broad as it always sounded: every page
# navigation goes through pageUrl(). What has not changed is this regex,
# which still only catches the LITERAL form — the shape the 11-of-19
# nightly regression took (``gotoRankingsBoard`` had a hardcoded
# ``page.goto("/rankings")``).
#
# Be clear about the residual hole rather than implying it closed: a
# reintroduced ``page.goto(path)`` over a route array would still slip
# past. It is left out because a regex cannot tell that from a legitimate
# variable navigation, and a guard that fires on both would be turned off.
# The live consequence is smaller than it was — such a call now 404s
# loudly on every route instead of quietly asserting against /login.
_BARE_GOTO = re.compile(r"""\.goto\(\s*["'](/[^"']*)["']""")

# Deliberate exemptions, keyed (file, route).  EMPTY, and that is the
# desired state — every entry here is a hole in the guard.
#
# There used to be one: auth-fixture's cookie-priming ``page.goto("/")``,
# justified on the grounds that "/" is public so it cannot 307. True,
# and beside the point. Through the backend page proxy "/" hydrates the
# ANONYMOUS shell against an already-authenticated client, and React
# reports that mismatch as an async #418 page error that lands after
# goto() resolves — i.e. after the next test attached its console
# guards. Intermittent failures on whichever authed spec lost the race,
# with :8000 chunk URLs in a stack trace from a test that navigated to
# :3000.
#
# The exemption's reasoning was sound about redirects and silent about
# hydration, which is the same §6.15 shape this file exists to catch.
# The fixture now primes through pageUrl() like everything else.
#
# An entry here needs a reason that survives someone reading it
# adversarially — "it cannot redirect" is not the same claim as "it is
# safe to navigate there".
_GOTO_EXEMPT: dict[tuple[str, str], str] = {}

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


WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PLAYWRIGHT_CONFIG = E2E_DIR / "playwright.config.js"


def _yaml_code_only(text: str) -> str:
    """Strip ``#`` comment lines from YAML before pattern-matching.

    MANDATORY for every check below, not a nicety.  The workflows now
    carry long comments explaining why ``--reporter`` must not be passed
    and why ``E2E_ALLOW_FLAKY`` must not be set — so a naive substring
    scan matches the warning against the defect and fails on a correct
    file.  This file already recorded that trap hitting it once; it hit
    again while these guards were written.

    Deliberately line-oriented and conservative: a ``#`` inside a quoted
    scalar would be over-stripped, which can only cause a guard to look
    at less text, never to invent an offender.
    """
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line.split(" #", 1)[0])
    return "\n".join(out)


def _playwright_run_blocks() -> list[tuple[Path, str]]:
    """(workflow, run-block text) for every step that invokes playwright."""
    blocks = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        code = _yaml_code_only(path.read_text(encoding="utf-8"))
        for chunk in re.split(r"\n\s*-\s+name:", code):
            if "playwright test" in chunk:
                blocks.append((path, chunk))
    return blocks


class TestNoWorkflowUnloadsThePlaywrightReporters(unittest.TestCase):
    """``--reporter`` on the CLI unloads every guard in the reporter array.

    Playwright's ``--reporter`` REPLACES ``playwright.config.js``'s
    ``reporter`` list rather than adding to it, so one flag silently
    unloads ``stack-death-reporter.js`` — the stack-death abort, the
    coverage floor and the flaky banner, all three at once, with nothing
    printed to say so.

    This is not hypothetical twice over.  The reporter's own header
    records that the stack-death guard was first "verified" under
    ``--reporter=line`` and had therefore never executed.  And
    ``prod-e2e-smoke.yml`` passed the same flag for its entire history:
    every production smoke run this repo ever made ran with no guards.
    Fixed 2026-08-05; this test is what stops it coming back.
    """

    # Keyed (workflow filename, flag).  EMPTY, and that is the desired
    # state — every entry here is a hole in the guard, same convention as
    # _GOTO_EXEMPT above.  An entry needs a reason that survives being
    # read adversarially; "we only wanted prettier output" is not one,
    # because that is exactly the trade that produced the incident.
    _REPORTER_EXEMPT: dict[tuple[str, str], str] = {}

    def test_no_workflow_passes_a_reporter_flag(self):
        offenders = []
        for path, chunk in _playwright_run_blocks():
            if not re.search(r"--reporter\b", chunk):
                continue
            if (path.name, "--reporter") in self._REPORTER_EXEMPT:
                continue
            offenders.append(path.name)
        self.assertEqual(
            offenders,
            [],
            "A workflow passes --reporter to playwright, which replaces the "
            "config's reporter array and unloads stack-death-reporter.js "
            "(stack-death abort + coverage floor + flaky banner). Remove the "
            "flag; the config already provides list + html.\n" + "\n".join(offenders),
        )

    def test_every_exemption_is_still_real(self):
        for name, _flag in self._REPORTER_EXEMPT:
            self.assertTrue(
                (WORKFLOWS_DIR / name).exists(),
                f"_REPORTER_EXEMPT names {name}, which no longer exists. "
                "Drop the entry rather than leaving a hole propped open.",
            )


class TestFlakyRunsCannotReportGreen(unittest.TestCase):
    """A retried pass must not read as a clean pass.

    ``retries: 1`` in CI means a test can fail, be retried, pass, and
    leave the run's status at ``passed`` with exit 0.  Nothing read that
    flaky count until 2026-08-05, so ``e2e.yml``'s close step would
    retire the ``e2e-failures`` tracker on a run that contained failures
    — draining every open one, since it iterates ``.[]``.

    The predicate lives in ``playwright.config.js`` as
    ``failOnFlakyTests``, NOT in the reporter, precisely because a
    ``--reporter`` flag can unload the reporter and cannot touch a config
    key.
    """

    def test_config_fails_the_run_on_flaky(self):
        src = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
        self.assertIn(
            "failOnFlakyTests",
            src,
            "playwright.config.js no longer sets failOnFlakyTests. Without it "
            "a retried failure reports as a green run and e2e.yml's close "
            "step retires the tracking issue on it.",
        )

    def test_retries_and_fail_on_flaky_stay_paired(self):
        """The invariant that actually matters.

        ``retries: 0`` plus the key is merely stricter and is fine.  What
        must never happen is a non-zero CI retry count with the key gone:
        that silently restores the old false green, and the diff that
        does it does not look wrong on its own.
        """
        src = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
        retries = re.search(r"^\s*retries:\s*(.+?),\s*$", src, re.MULTILINE)
        self.assertIsNotNone(retries, "could not find a retries: line to check")
        expr = retries.group(1)
        has_nonzero_ci_branch = "CI" in expr and not re.fullmatch(r"0", expr.strip())
        if has_nonzero_ci_branch:
            self.assertIn(
                "failOnFlakyTests",
                src,
                f"retries is {expr!r} (non-zero under CI) but failOnFlakyTests "
                "is gone. Those two are a pair: retries without it means a "
                "flaky test reports green.",
            )

    def test_no_workflow_disables_the_guards(self):
        offenders = []
        for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
            code = _yaml_code_only(path.read_text(encoding="utf-8"))
            for var in ("E2E_ALLOW_FLAKY", "E2E_NO_STACK_GUARD"):
                if re.search(rf"^\s*{var}\s*:", code, re.MULTILINE):
                    offenders.append(f"{path.name} sets {var}")
        self.assertEqual(
            offenders,
            [],
            "A workflow disables an E2E guard. Both switches exist for a "
            "human debugging locally, not for CI — setting either in a "
            "workflow restores the green this repo just stopped "
            "manufacturing.\n" + "\n".join(offenders),
        )


class TestSubsetRunsCarryTheirOwnCoverageFloor(unittest.TestCase):
    """A workflow running ONE spec needs its own floor, or none at all.

    ``stack-death-reporter.js`` defaults to ``E2E_MIN_PASSED=100``, sized
    for the nightly's full suite (139 passed on run 30945387957).  A
    workflow that names a single spec path runs ~32 and would fail every
    time — so a subset run MUST declare its own bounds.

    The converse matters just as much: a workflow running the FULL suite
    must NOT set them, or the nightly's floor becomes editable from YAML,
    which is how a floor quietly becomes unenforceable.

    Values must be numeric literals.  ``Number("3O")`` is NaN and both
    ``passed < NaN`` and ``skipped > NaN`` are false, so one typo would
    disable the coverage floor while its banner claims the opposite.
    ``coverageBound()`` in the reporter now throws on that, and this
    keeps the typo out of the tree in the first place.
    """

    _BOUNDS = ("E2E_MIN_PASSED", "E2E_MAX_SKIPPED")

    def test_subset_runs_declare_numeric_bounds(self):
        offenders = []
        for path, chunk in _playwright_run_blocks():
            names_a_spec = bool(re.search(r"tests/e2e/specs/\S+\.spec\.js", chunk))
            found = {}
            for var in self._BOUNDS:
                m = re.search(rf"^\s*{var}\s*:\s*(.+?)\s*$", chunk, re.MULTILINE)
                if m:
                    found[var] = m.group(1).strip().strip("\"'")

            if names_a_spec:
                for var in self._BOUNDS:
                    if var not in found:
                        offenders.append(f"{path.name} runs a single spec but does not set {var}")
                    elif not re.fullmatch(r"\d+", found[var]):
                        offenders.append(
                            f"{path.name} sets {var}={found[var]!r}, which is not a "
                            "plain integer — an unparseable bound disables the floor"
                        )
            elif found:
                offenders.append(
                    f"{path.name} runs the full suite but sets "
                    f"{sorted(found)} — that makes the nightly's floor "
                    "editable from YAML"
                )
        self.assertEqual(offenders, [], "\n".join(offenders))


class TestNoWaitCanOutliveItsTest(unittest.TestCase):
    """A single wait must never be able to outlive the test that runs it.

    When one ``timeout:`` equals or exceeds the per-test cap, that wait
    can never reach its own deadline: the test is killed first, and the
    run reports "Test timeout of Nms exceeded" at whatever line happened
    to be executing.  The wait's own message — the one written to explain
    what was being waited for — never prints.  So the defect surfaces as
    a different "flaky" test each run and reads as a product regression.

    This is not hypothetical.  It was hit twice on 2026-08-05, from the
    two opposite directions, which is why the guard checks the pair
    rather than either number alone:

    * ``journey-trade.spec.js`` polled ``/arbitrage`` with a 90s budget
      inside a 90s cap.  Run 31026906945 died as a TEST timeout.
    * ``gotoRankingsBoard`` waited 60s inside that same 90s cap, after
      the page load had already spent part of it.  Run 31027451127 died
      as the INNER wait — its own message, "Timeout: 60000ms" — so
      raising the cap alone would not have covered it.

    Both were repaired by giving the waits room under a larger cap, never
    by weakening an assertion.

    The per-file bound is a deliberate over-approximation: a test may
    raise its own ceiling with ``test.setTimeout(N)``, and resolving
    which wait sits inside which test would mean parsing the file's
    scopes.  Taking the largest override in the file cannot produce a
    false positive — it only makes the guard slightly permissive for a
    file that mixes raised and unraised tests.
    """

    # Two spaces of indentation: the per-test key inside defineConfig({}).
    # `expect: { timeout: … }` and the webServer entries are nested deeper
    # and are different budgets entirely.
    _CONFIG_TIMEOUT = re.compile(r"^  timeout:\s*([\d_]+)\s*,", re.MULTILINE)
    _WAIT = re.compile(r"\btimeout:\s*([\d_]+)\b")
    _SET_TIMEOUT = re.compile(r"\btest\.setTimeout\(\s*([\d_]+)\s*\)")

    def _config_timeout(self) -> int:
        src = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
        found = self._CONFIG_TIMEOUT.findall(src)
        self.assertEqual(
            len(found),
            1,
            "could not read exactly one per-test `timeout:` from "
            "playwright.config.js — this guard reads it by indentation, so "
            "reformatting that block silently disarms it. Fix the pattern "
            "rather than deleting the test.",
        )
        return int(found[0].replace("_", ""))

    def test_no_declared_wait_reaches_the_per_test_cap(self) -> None:
        cap = self._config_timeout()
        files = sorted((E2E_DIR / "specs").glob("*.js")) + sorted(
            (E2E_DIR / "helpers").glob("*.js")
        )
        # Without this the whole guard passes vacuously if either directory
        # is renamed — the failure mode every guard in this file exists to
        # avoid.
        self.assertGreater(len(files), 10, f"found only {len(files)} E2E JS files to scan")

        offenders = []
        scanned = 0
        for path in files:
            src = path.read_text(encoding="utf-8")
            overrides = [int(v.replace("_", "")) for v in self._SET_TIMEOUT.findall(src)]
            ceiling = max([cap, *overrides])
            for line_no, line in enumerate(src.splitlines(), start=1):
                for raw in self._WAIT.findall(line):
                    scanned += 1
                    value = int(raw.replace("_", ""))
                    if value >= ceiling:
                        offenders.append(
                            f"{path.relative_to(E2E_DIR)}:{line_no} waits {value}ms "
                            f"against a {ceiling}ms ceiling"
                        )

        self.assertGreater(
            scanned, 20, f"only found {scanned} waits — the pattern stopped matching"
        )
        self.assertEqual(
            offenders,
            [],
            "A wait is budgeted at or above the test that contains it, so it "
            "can never reach its own deadline and its message can never "
            "print. Raise the cap in playwright.config.js (and keep its "
            "arithmetic comment in step), or lower the wait — do not relax "
            "the assertion underneath it.\n" + "\n".join(offenders),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
