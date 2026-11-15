"""Pin: the scraper's Playwright driver start and Chromium launch are bounded
by Python-side deadlines.

THE INCIDENT (2026-11-11 23:27 UTC onward, website audit WA-05)
---------------------------------------------------------------
Every production scrape sat at step ``browser`` / ``launch`` with no heartbeat
until the 2 h run timeout; 6 of 8 runs in 24 h failed and the served board went
21 h stale.  Playwright's own 180 s launch timeout is enforced by its Node
driver, so a driver that is itself stalled (the service cgroup was above its
``MemoryHigh``, where the kernel throttles every process in it) never fires
it.  Measured with a stalled driver through the real ``run()``: the old code
hung until the outer cap; the bounded code raised ``TimeoutError`` at the
configured deadline.

``Dynasty Scraper.py`` cannot be imported in a unit test (minutes of module
scope), so this pins the structure with ``ast``, the same way
``tests/identity/test_capture_evidence_scraper_adapter.py`` does.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCRAPER = Path(__file__).resolve().parents[2] / "Dynasty Scraper.py"


def _tree() -> ast.Module:
    return ast.parse(SCRAPER.read_text(encoding="utf-8"))


def _is_wait_for(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "wait_for"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
    )


def _calls_named(tree: ast.AST, dotted_tail: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            try:
                text = ast.unparse(node.func)
            except Exception:  # noqa: BLE001
                continue
            if text.endswith(dotted_tail):
                out.append(node)
    return out


def _enclosing_wait_for(tree: ast.AST, target: ast.Call) -> ast.Call | None:
    for node in ast.walk(tree):
        if _is_wait_for(node):
            for inner in ast.walk(node.args[0]) if node.args else ():
                if inner is target:
                    return node
    return None


def _deadline_default(tree: ast.AST, env_name: str) -> int | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_env_int"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == env_name
        ):
            return node.args[1].value
    return None


def test_every_playwright_driver_start_is_bounded():
    tree = _tree()
    starts = _calls_named(tree, "async_playwright")
    assert starts, "the scraper no longer starts Playwright here — re-point this pin"
    for call in starts:
        assert (
            _enclosing_wait_for(tree, call) is not None
        ), f"async_playwright() at line {call.lineno} has no asyncio.wait_for deadline"
    # And never as a bare ``async with async_playwright()``: that form cannot
    # carry a deadline on the driver start.
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncWith):
            for item in node.items:
                assert "async_playwright" not in ast.unparse(item.context_expr), node.lineno


def test_every_chromium_launch_is_bounded_past_playwrights_own_timeout():
    tree = _tree()
    launches = _calls_named(tree, "chromium.launch")
    assert launches
    for call in launches:
        assert (
            _enclosing_wait_for(tree, call) is not None
        ), f"chromium.launch at line {call.lineno} has no asyncio.wait_for deadline"
    launch_default = _deadline_default(tree, "SCRAPER_BROWSER_LAUNCH_DEADLINE")
    start_default = _deadline_default(tree, "SCRAPER_PLAYWRIGHT_START_DEADLINE")
    assert isinstance(launch_default, int) and isinstance(start_default, int)
    # Past Playwright's own 180 s launch timeout, so its more specific error
    # still wins whenever its driver can raise one; far below the 2 h run cap.
    assert 180 < launch_default <= 600
    assert 0 < start_default <= 600
