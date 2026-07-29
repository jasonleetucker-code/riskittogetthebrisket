"""The arbitrage engine is wired to a UI, and the two "finder" routes
must not drift back into each other.

Backlog #6, now closed. Its original description was wrong in a way
worth keeping recorded, because the error created a blocker that did not
exist:

    "/finder computes arbitrage client-side off useDynastyData, so there
    are two implementations and the shipped one is not the audited one
    ... resolving it means choosing which implementation is canonical —
    a product decision."

Measured 2026-07-28: ``frontend/app/finder/page.jsx`` contains no
market-versus-board comparison of any kind. Its five presets filter and
sort the board on ``sourceRankSpread`` / ``confidenceBucket`` /
``isSingleSource`` / ``rookie``. There was no second implementation and
therefore no decision to make — only a missing caller.

**Where the phantom came from.** Two places called that page arbitrage
without it computing any: a stale header comment ("the arbitrage
blotter") and, more consequentially, the nav model, which labelled
``/finder`` as *"Arbitrage Finder — Find KTC market gaps you can
exploit"*. Both are corrected: the arbitrage vocabulary now belongs to
``/arbitrage`` alone.

So the tests here changed shape. They no longer assert the engine has no
caller — it has one. They assert the two routes stay distinct, which is
the property that actually matters and the one whose violation cost an
audit cycle.

**2026-07-29, the board filter moved.** ``/finder`` was a second copy of
the rankings table wearing five saved filters; it is now the "Screens"
dropdown on ``/rankings``, with each preset carried over verbatim into
``SCREENS`` in ``frontend/lib/edge-helpers.js`` (their thresholds differ
from the board lenses, so mapping them onto existing lenses would have
silently changed the answers). ``/finder`` is a redirect shim. The
invariant is unchanged and still worth pinning — the screener filters
the board and the arbitrage engine compares board to market — so these
tests now watch the screener's new home.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_BOARD_FILTER = _REPO / "frontend" / "lib" / "edge-helpers.js"
_FINDER_SHIM = _REPO / "frontend" / "app" / "finder" / "page.jsx"
_ARBITRAGE_PAGE = _REPO / "frontend" / "app" / "arbitrage" / "page.jsx"
_PROXY = _REPO / "frontend" / "app" / "api" / "trade" / "finder" / "route.js"
_ENGINE = _REPO / "src" / "trade" / "finder.py"
_SERVER = _REPO / "server.py"
_NAV = _REPO / "frontend" / "lib" / "nav-model.js"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _strip_comments(src: str) -> str:
    """Drop JS comments before scanning.

    Found the hard way: the corrected header comment on the board-filter
    page names ``POST /api/trade/finder`` while explaining that the page
    does not call it, and a naive substring scan read that prose as a
    caller. Documentation mentioning an endpoint is not an invocation.
    """
    src = _BLOCK_COMMENT.sub("", src)
    return "\n".join(line for line in src.split("\n") if not line.lstrip().startswith("//"))


def test_the_engine_and_its_endpoint_still_exist():
    assert _ENGINE.is_file(), "src/trade/finder.py is gone"
    server_src = _SERVER.read_text(encoding="utf-8", errors="replace")
    assert re.search(
        r'@app\.post\(\s*["\']/api/trade/finder["\']', server_src
    ), "POST /api/trade/finder is no longer registered"


def test_the_arbitrage_page_calls_the_engine():
    """#6's live half, now satisfied.

    The engine was audited — per-market top-150 gating,
    ``marketCoverage``, ``assetsUnpricedByBoard``, ``valueSource``
    stamping — and invoked by nothing. The T4-2 mixed-market disclosure
    landed on an engine no user could reach.
    """
    assert _ARBITRAGE_PAGE.is_file(), "the arbitrage page is gone — #6 has regressed"
    page = _strip_comments(_ARBITRAGE_PAGE.read_text(encoding="utf-8", errors="replace"))
    assert "/api/trade/finder" in page, "the arbitrage page no longer calls the engine"
    assert _PROXY.is_file(), "the dev bridge route is gone; `npm run dev` will 404"


def test_the_board_filter_page_still_computes_no_arbitrage():
    """The claim #6 got wrong, pinned so it cannot quietly become true.

    A client-side board-versus-market calculation would be a second
    valuation implementation, which CLAUDE.md's "no frontend ranking
    engine, period" rule forbids outright — and it is now genuinely
    tempting, since a working arbitrage view exists one route away.
    """
    code = _strip_comments(_BOARD_FILTER.read_text(encoding="utf-8", errors="replace"))
    forbidden = [tok for tok in ("ktcValue", "ktc_value", "marketValue", "valueGap") if tok in code]
    assert not forbidden, (
        f"the board screens now reference {forbidden}. If they are computing "
        "board-versus-market deltas in the browser, call POST /api/trade/finder "
        "instead — that is what /arbitrage does."
    )
    assert "/api/trade/finder" not in code, (
        "the board screens now call the arbitrage engine. Two surfaces doing "
        "the same job is what backlog #6 was about; put it on /arbitrage."
    )


def test_the_board_screens_are_still_board_filters():
    """Positive characterisation, so the test above is not the only
    description of what the screener is."""
    src = _BOARD_FILTER.read_text(encoding="utf-8", errors="replace")
    assert "export const SCREENS" in src, "the board screens registry is gone"
    for marker in ("sourceRankSpread", "confidenceBucket", "isSingleSource"):
        assert marker in src, f"{marker} vanished from the board screens"


def test_the_retired_finder_route_still_resolves():
    """Old bookmarks and shared links must not 404.

    The page merged into /rankings; the route stays as a shim so a link
    someone saved to a workflow still lands on that workflow.
    """
    assert _FINDER_SHIM.is_file(), "the /finder shim is gone — old links now 404"
    src = _FINDER_SHIM.read_text(encoding="utf-8", errors="replace")
    assert "/rankings" in src, "the /finder shim no longer points at the board"
    for workflow in ("wr-gaps", "stable-idp", "single-risk", "rookie-spread"):
        assert workflow in src, f"the {workflow} preset lost its redirect mapping"


def test_the_nav_does_not_promise_arbitrage_from_the_board_filter():
    """The specific mislabel that manufactured the phantom.

    The nav called ``/finder`` "Arbitrage Finder — Find KTC market gaps
    you can exploit". A reader auditing the route naturally concluded it
    computed arbitrage, and recorded a competing implementation that was
    never there.
    """
    nav = _NAV.read_text(encoding="utf-8", errors="replace")
    entries = re.findall(r'\{\s*href:\s*"([^"]+)"[^}]*?label:\s*"([^"]+)"[^}]*?\}', nav)
    by_href = dict(entries)

    # The invariant is about which ROUTE owns the word, not the exact
    # string: the nav label is now "Arbitrage" so it matches the page's
    # own <h1> (they disagreed before, which was its own small part of
    # the confusion).  What must never drift is the word landing on the
    # route that does not compute it.
    arbitrage_label = by_href.get("/arbitrage", "")
    assert (
        "arbitrage" in arbitrage_label.lower()
    ), f"/arbitrage should carry the arbitrage label, got {arbitrage_label!r}"
    finder_label = by_href.get("/finder", "")
    assert "arbitrage" not in finder_label.lower(), (
        f"/finder is labelled {finder_label!r}, which promises arbitrage it does "
        "not compute — this is exactly what produced the phantom in backlog #6"
    )
