"""A ``position: fixed`` rule must anchor itself vertically.

Backlog defect #14, "sticky trade header". It was carried as *could not
reproduce — no defect was visible by inspection*, and the reason that
inspection came up empty is the interesting part.

``.trade-sticky-tray`` declared ``position: fixed; left: 0; right: 0``
and **no vertical offset**. The only rule supplying ``bottom`` lived in
an ``@media (max-width: 768px)`` block several hundred lines further
down. So:

* on a phone the tray was anchored correctly, and
* on every viewport wider than 768px it had ``bottom: auto`` and
  ``top: auto``, which CSS paints at the box's *static* position and then
  pins there — mid-page, overlapping content, not following the scroll.

Grepping the class name shows a ``bottom`` declaration, so the rule reads
as complete. You only see the gap if you notice which block that
declaration is inside. That is the same shape as the guards
ORCHESTRATION.md 6.15 collects: the stated intent ("sticky tray") and the
actual predicate (no anchor at this breakpoint) differ, and nothing
forced them to agree.

This test generalises the defect rather than pinning the one rule.

**Scope: ``position: fixed`` only.** ``position: sticky`` is deliberately
excluded — a sticky box sticks only on the axes that have an offset, so
``.sticky-name`` (``position: sticky; left: 0``, a frozen first table
column that must scroll vertically with its row) is correct with no
vertical anchor. Flagging it would be a false positive, and a check that
cries wolf gets suppressed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

#: Directories holding CSS this repo did not author.
#:
#: ``.next`` is compiled output and ``node_modules`` is third-party, and
#: scanning either is worse than useless here. A ``position: fixed`` rule in a
#: build chunk came from a source file this suite already scans, so the extra
#: cases assert nothing new — while a rule from a dependency is one the repo
#: cannot fix, so flagging it would be the cry-wolf failure the docstring above
#: says the scope exists to avoid.
#:
#: They also made the suite RACE. The file list is captured at import time and
#: frozen into the parametrisation, so a ``next build`` running concurrently
#: replaces a hashed chunk and the test dies on ``FileNotFoundError`` — three
#: false failures in one session, none of them reproducible on a re-run. CI
#: never saw it because pytest and the frontend build are separate jobs there.
_GENERATED_DIRS = frozenset({".next", "node_modules"})

_CSS_FILES = sorted(
    path
    for path in (Path(__file__).resolve().parents[2] / "frontend").rglob("*.css")
    if _GENERATED_DIRS.isdisjoint(path.parts)
)

#: Offsets that anchor a box on the vertical axis. ``inset`` (and its
#: block/shorthand forms) set all four sides at once.
_VERTICAL_ANCHORS = {"top", "bottom", "inset", "inset-block", "inset-block-start", "inset-block-end"}


def _iter_top_level_rules(src: str):
    """Yield ``(line_no, selector, body)`` for top-level rules only.

    Rules nested in ``@media`` / ``@supports`` are skipped on purpose:
    an override inside a breakpoint is exactly what masked this defect,
    so the base rule has to stand on its own.
    """
    lines = src.split("\n")
    i, depth = 0, 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r"\s*([.#][^{@]*?)\s*\{\s*$", line)
        if match and depth == 0:
            body, d, j = [], 0, i
            while j < len(lines):
                body.append(lines[j])
                d += lines[j].count("{") - lines[j].count("}")
                j += 1
                if d == 0:
                    break
            yield i + 1, match.group(1).strip(), "\n".join(body)
            i = j
            continue
        depth += line.count("{") - line.count("}")
        i += 1


def _declared_properties(body: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"(?m)^\s*([a-z-]+)\s*:", body)}


def _unanchored_fixed_rules(path: Path) -> list[tuple[int, str]]:
    src = path.read_text(encoding="utf-8", errors="replace")
    out: list[tuple[int, str]] = []
    for line_no, selector, body in _iter_top_level_rules(src):
        if not re.search(r"(?m)^\s*position:\s*fixed\b", body):
            continue
        if _declared_properties(body) & _VERTICAL_ANCHORS:
            continue
        out.append((line_no, selector))
    return out


@pytest.mark.parametrize("css_path", _CSS_FILES, ids=lambda p: p.name)
def test_no_fixed_rule_relies_on_a_breakpoint_for_its_vertical_anchor(css_path):
    offenders = _unanchored_fixed_rules(css_path)
    assert not offenders, (
        "position:fixed with no top/bottom in the BASE rule renders at the "
        "box's static position and pins there.\n"
        + "\n".join(
            f"  {css_path.name}:{line}  {sel}" for line, sel in offenders
        )
        + "\nIf a breakpoint sets the offset, the base rule still needs one — "
        "otherwise the element is unanchored at every other viewport size."
    )


def test_the_scan_actually_finds_the_original_defect():
    """Non-vacuity, against the real pre-fix text.

    Without this the check would pass just as happily against a parser
    that never matched anything.
    """
    pre_fix = """
.trade-sticky-tray {
  position: fixed;
  left: 0;
  right: 0;
  z-index: 35;
  border-top: 1px solid var(--border);
}

@media (max-width: 768px) {
  .trade-sticky-tray {
    bottom: calc(var(--mobile-nav-h) + env(safe-area-inset-bottom, 0px));
  }
}
"""
    found = [
        sel
        for line, sel, body in _iter_top_level_rules(pre_fix)
        if re.search(r"(?m)^\s*position:\s*fixed\b", body)
        and not (_declared_properties(body) & _VERTICAL_ANCHORS)
    ]
    assert found == [".trade-sticky-tray"], (
        "the scan no longer detects the defect it was written for; the "
        "media-query override must NOT count as anchoring the base rule"
    )


def test_border_top_is_not_mistaken_for_a_top_offset():
    """The parse bug that would silence this check.

    A substring test for ``top`` matches ``border-top``, which nearly
    every bar-shaped element declares — so a naive implementation reports
    the whole file clean.
    """
    body = ".x {\n  position: fixed;\n  border-top: 1px solid red;\n}"
    assert not (_declared_properties(body) & _VERTICAL_ANCHORS)
    assert "border-top" in _declared_properties(body)


def test_sticky_columns_are_not_flagged():
    """``position: sticky`` with only a horizontal offset is correct.

    A frozen table column must scroll vertically with its row. Flagging
    it would make this check noisy enough to be ignored.
    """
    body = ".sticky-name {\n  position: sticky;\n  left: 0;\n  z-index: 2;\n}"
    assert not re.search(r"(?m)^\s*position:\s*fixed\b", body)


def test_there_is_css_to_scan():
    """Guards against the parametrisation silently collapsing to zero
    cases if the frontend tree ever moves."""
    assert _CSS_FILES, "no CSS files found — this suite would pass vacuously"
    # And that the exclusion above narrowed the scan without emptying it: a
    # typo in _GENERATED_DIRS that matched everything would otherwise leave
    # this suite passing vacuously in exactly the way the assert above exists
    # to prevent.
    assert not any(
        not _GENERATED_DIRS.isdisjoint(p.parts) for p in _CSS_FILES
    ), "generated CSS is still being scanned"
