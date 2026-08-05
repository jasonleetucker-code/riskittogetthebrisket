"""``/api/gameplan``'s status is machine-checked, not asserted in prose.

Audit W20-F001: the endpoint answers 200 with a 92 KB, heavily
self-documenting payload — positional profiles with measured deficits,
a five-state competitive window, two target engines, an 11-partner
model, a Pareto package frontier — and NOTHING in ``frontend/`` calls
it.  4,385 lines of ``src/roster_intel/`` plus 1,344 of
``src/api/gameplan.py``, unreachable by any user.

The repair the roadmap allows today is to mark the module set
explicitly internal-only so it is not mistaken for live product (it is
deliberately NOT deleted — its 22 dedicated tests execute in neither CI
tier, W24-F002, so nobody knows whether it works, and deleting an
unmeasured subsystem destroys the evidence needed to decide).

A comment saying "no frontend consumer" is exactly the kind of claim
this codebase has been burned by — ``CLAUDE.md``'s adapter table, the
``_ = snapshot`` comment in ``ros/trade_deadline``, five percentile
docstrings.  So this test makes the marker and reality inseparable, in
BOTH directions:

  * frontend callers == 0  =>  the banner MUST be present
  * frontend callers  > 0  =>  the banner MUST be gone

Whichever way the subsystem's fate is decided, the losing state fails.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
BANNER = "INTERNAL-ONLY. NO FRONTEND CONSUMER. NOT LIVE PRODUCT."

_MARKED_FILES = (
    REPO_ROOT / "src" / "api" / "gameplan.py",
    REPO_ROOT / "src" / "roster_intel" / "__init__.py",
)

# A real call site: a quoted string literal containing the path — a
# fetch, an axios call, or a Next bridge route's forward target. Prose
# mentions in comments do not count and must not: the audit's grep over
# frontend/ returned exactly one hit and it was a comment.
#
# Same-line only. Without excluding the newline, the character class
# spans lines and matches an opening quote three functions earlier
# against a path that appears in a comment — which turns every prose
# mention into a false consumer.
_CALL_RE = re.compile(r"""["'`][^"'`\n]*/api/gameplan""")

_SEARCH_DIRS = ("app", "components", "lib", "hooks")
_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs"}


def _frontend_call_sites() -> list[str]:
    hits: list[str] = []
    for sub in _SEARCH_DIRS:
        base = FRONTEND / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix not in _SUFFIXES or not path.is_file():
                continue
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):  # pragma: no cover
                continue
            if _CALL_RE.search(text):
                hits.append(str(path.relative_to(REPO_ROOT)))
    return sorted(hits)


class GameplanStatusMarkerTests(unittest.TestCase):
    def test_marker_and_reality_agree(self) -> None:
        callers = _frontend_call_sites()
        marked = [p for p in _MARKED_FILES if BANNER in p.read_text(encoding="utf-8")]
        unmarked = [
            str(p.relative_to(REPO_ROOT)) for p in _MARKED_FILES if p not in marked
        ]

        if callers:
            self.assertEqual(
                [str(p.relative_to(REPO_ROOT)) for p in marked],
                [],
                "/api/gameplan now has a frontend consumer "
                f"({callers}) — remove the internal-only banner, it is stale.",
            )
        else:
            self.assertEqual(
                unmarked,
                [],
                "/api/gameplan still has no frontend consumer, so every module "
                "in the set must carry the internal-only banner. Missing from: "
                f"{unmarked}",
            )

    def test_the_route_handler_says_it_too(self) -> None:
        """The docstring a reader hits first, in server.py."""
        server = (REPO_ROOT / "server.py").read_text(encoding="utf-8")
        idx = server.index('@app.get("/api/gameplan")')
        handler = server[idx : idx + 2000]
        has_marker = "INTERNAL-ONLY" in handler
        if _frontend_call_sites():
            self.assertFalse(has_marker, "stale internal-only marker on the route")
        else:
            self.assertTrue(
                has_marker,
                "get_gameplan's docstring must state that nothing consumes it",
            )

    def test_the_marker_names_the_finding_and_the_reason(self) -> None:
        """Marked-as-internal is a decision; it has to carry its evidence."""
        if _frontend_call_sites():
            self.skipTest("a consumer exists; the banner is expected to be gone")
        text = (REPO_ROOT / "src" / "api" / "gameplan.py").read_text(encoding="utf-8")
        self.assertIn("W20-F001", text)
        # Why it is marked and not deleted.
        self.assertIn("W24-F002", text)
        # And that the dangling override hook is the same defect, not a
        # second one to chase.
        self.assertIn("W20-F013", text)


class WindowIsTheExceptionTests(unittest.TestCase):
    """``roster_intel/window.py`` IS live product; the package note says so.

    It is THE team-direction definition for the app (W20-F006):
    ``frontend/lib/team-phase.js`` is a port of it and /phases + /rosters
    render it.  A blanket "this package is internal" that did not carve
    it out would invite someone to change an anchor on the assumption
    nothing user-facing depends on it.
    """

    def test_package_note_carves_out_window(self) -> None:
        text = (REPO_ROOT / "src" / "roster_intel" / "__init__.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("window.py", text)
        self.assertIn("team-phase.js", text)
        self.assertIn("IS live product", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
