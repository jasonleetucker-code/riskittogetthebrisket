"""Records the true state of the two things called "finder".

Backlog defect #6 says: *"/finder computes arbitrage client-side off
useDynastyData, so there are two implementations and the shipped one is
not the audited one ... resolving it means choosing which implementation
is canonical — a product decision."*

**That description is wrong, and the error matters** because it invented
a blocker. Measured 2026-07-28:

* ``frontend/app/finder/page.jsx`` contains no market-versus-board
  comparison of any kind. Its five workflow presets filter and sort the
  board on ``sourceRankSpread``, ``confidenceBucket``, ``isSingleSource``
  and ``rookie``. ``rankDerivedValue`` appears twice, both times inside a
  column accessor rendering a number.
* The only occurrence of the word "arbitrage" on that page is a comment
  calling it "the arbitrage blotter" — a naming leftover, since nothing
  below it computes one.

So there is no competing implementation and nothing to choose between.
The page is a board filter; ``src/trade/finder.py`` is an arbitrage
engine. They do different jobs and merely share a word.

What #6 got right, and what remains true, is the smaller claim:
**``src/trade/finder.py`` has no UI caller.** ``POST /api/trade/finder``
is registered and audited — per-market top-150 gating, ``marketCoverage``,
``assetsUnpricedByBoard``, ``metadata.valueSource`` — and no frontend file
calls it. The T4-2 mixed-market disclosure did land on an engine nobody
invokes.

Wiring it means designing a new UI surface, which is a feature and not a
defect fix, so this test does not demand one. It pins the facts so the
next reader inherits the measured state instead of the mistaken one, and
so that "the engine acquired a caller" is a visible event.

This is the second row of §9 whose *mechanism* did not survive checking
— see the standing caveat there: §9 is reliable in KIND, not in NUMBER.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_PAGE = _REPO / "frontend" / "app" / "finder" / "page.jsx"
_ENGINE = _REPO / "src" / "trade" / "finder.py"
_SERVER = _REPO / "server.py"
_UI_DIRS = ("app", "components", "lib")


def _ui_files():
    for d in _UI_DIRS:
        root = _REPO / "frontend" / d
        if root.is_dir():
            yield from root.rglob("*.js*")


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _strip_comments(src: str) -> str:
    """Drop JS comments before scanning for callers.

    Necessary, and found the hard way: the corrected header comment on
    ``finder/page.jsx`` names ``POST /api/trade/finder`` while explaining
    that the page does *not* call it. A naive substring scan read that
    prose as a caller and failed. Documentation mentioning an endpoint is
    not an invocation of it.
    """
    src = _BLOCK_COMMENT.sub("", src)
    return "\n".join(line for line in src.split("\n") if not line.lstrip().startswith("//"))


def test_the_backend_arbitrage_engine_is_still_exposed():
    """The engine and its endpoint both exist.

    Without this the "no caller" assertion below could go green because
    the whole feature was deleted.
    """
    assert _ENGINE.is_file(), "src/trade/finder.py is gone — update #6"
    server_src = _SERVER.read_text(encoding="utf-8", errors="replace")
    assert re.search(
        r'@app\.post\(\s*["\']/api/trade/finder["\']', server_src
    ), "POST /api/trade/finder is no longer registered"


def test_no_frontend_file_calls_the_finder_endpoint():
    """The live half of #6.

    If this starts failing, the engine has been wired up — good. Update
    the #6 disposition rather than deleting the test.
    """
    callers = sorted(
        str(p.relative_to(_REPO))
        for p in _ui_files()
        if "trade/finder" in _strip_comments(p.read_text(encoding="utf-8", errors="replace"))
    )
    assert not callers, (
        "POST /api/trade/finder now has UI callers:\n"
        + "\n".join(f"  {c}" for c in callers)
        + "\nThat closes backlog #6 — record it there and retire this test."
    )


def test_the_finder_page_does_not_reimplement_arbitrage():
    """The claim #6 got wrong, pinned so it cannot quietly become true.

    A client-side arbitrage calculation would be a second valuation
    implementation, which the "no frontend ranking engine, period" rule
    in CLAUDE.md forbids outright. It does not exist today; this makes
    its appearance a test failure rather than a discovery three audits
    later.
    """
    code = _strip_comments(_PAGE.read_text(encoding="utf-8", errors="replace"))
    forbidden = [
        tok
        for tok in ("ktcValue", "ktc_value", "marketValue", "arbitrage", "valueGap")
        if tok in code
    ]
    assert not forbidden, (
        f"{_PAGE.name} now references {forbidden} outside comments. If the page "
        "is computing board-versus-market deltas in the browser, that is a "
        "second valuation implementation — call POST /api/trade/finder instead."
    )


def test_the_page_is_a_board_filter_not_a_valuation_engine():
    """Positive characterisation, so the test above is not the only
    description of what this page is."""
    src = _PAGE.read_text(encoding="utf-8", errors="replace")
    for marker in ("sourceRankSpread", "confidenceBucket", "isSingleSource"):
        assert marker in src, (
            f"{marker} vanished from the finder page; its workflow presets are "
            "what make it a board filter rather than an engine"
        )
