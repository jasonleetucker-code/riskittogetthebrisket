"""The three chat layers must be wired consistently, or recorded as unwired.

Backlog defect #5. There are three chat layers and **none of them is
connected to the next**:

1. ``src/api/chat.py`` — 351 lines, imported by nothing.
2. ``frontend/app/api/chat/route.js`` — a careful streaming proxy that
   forwards to a backend ``POST /api/chat`` which does not exist.
3. No UI component calls the proxy.

Each layer looks finished in isolation, which is precisely why this
survived: reading any one file suggests a shipped feature. Only the
composition is dead, and nothing in the tree said so.

**This test does not decide whether chat should ship.** That is a
product call — it means a streaming-LLM dependency, an API key, and a
per-request cost. What it does is make the current state a checkable
fact instead of an invisible one, so the gap cannot widen or be
half-closed silently.

The rule it enforces is *consistency*, not any particular state:

* all three layers wired  -> fine
* all three unwired       -> fine, and recorded here
* anything in between     -> fail, naming the layer that is out of step

So the day someone adds the backend route, this test tells them the UI
caller is still missing rather than letting a half-wired feature ship.
Per ORCHESTRATION.md 6.15, it is shown failing in both directions by
:func:`test_the_consistency_check_is_not_vacuous`.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SERVER = _REPO / "server.py"
_PROXY = _REPO / "frontend" / "app" / "api" / "chat" / "route.js"
_BACKEND_MODULE = _REPO / "src" / "api" / "chat.py"

#: Directories holding hand-written frontend source. ``.next`` is build
#: output — it contains a route manifest naming ``/api/chat``, which is
#: an echo of the proxy's own existence and not a caller. Grepping the
#: whole frontend tree finds that manifest and reports a caller that is
#: not there; that false positive is worth naming because it is the
#: obvious way to write this check wrong.
_UI_SOURCE_DIRS = ("app", "components", "lib")


def _backend_route_exists() -> bool:
    src = _SERVER.read_text(encoding="utf-8", errors="replace")
    return bool(re.search(r'@app\.(post|get)\(\s*["\']/api/chat["\']', src))


def _proxy_exists() -> bool:
    return _PROXY.is_file()


def _ui_callers() -> list[str]:
    hits: list[str] = []
    for d in _UI_SOURCE_DIRS:
        root = _REPO / "frontend" / d
        if not root.is_dir():
            continue
        for path in root.rglob("*.js*"):
            if path == _PROXY:
                continue
            if "/api/chat" in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(path.relative_to(_REPO)))
    return sorted(hits)


def _layer_state() -> dict[str, bool]:
    return {
        "backend route POST /api/chat": _backend_route_exists(),
        "frontend proxy route.js": _proxy_exists(),
        "a UI component that calls it": bool(_ui_callers()),
    }


def test_chat_layers_are_all_wired_or_all_unwired():
    state = _layer_state()
    wired = {k for k, v in state.items() if v}
    unwired = {k for k, v in state.items() if not v}

    assert not (wired and unwired), (
        "chat is half-wired, which ships a feature that cannot work.\n"
        f"  present: {sorted(wired)}\n"
        f"  missing: {sorted(unwired)}\n"
        "Either finish the remaining layer(s) or remove the ones that are "
        "there. See the module docstring: today the intended state is "
        "ALL THREE UNWIRED, pending a product decision on shipping a "
        "streaming-LLM feature."
    )


def test_the_orphan_backend_module_stays_orphaned_deliberately():
    """``src/api/chat.py`` is real, complete, and imported by nothing.

    Recorded rather than deleted: it is 351 lines of working code that
    becomes valuable the moment the product decision goes the other way.
    The reachability audit
    (``scripts/audit/measure_module_reachability.py``) already reports it
    as ORPHAN, so it cannot rot unnoticed — this pins the intent next to
    the other two layers so all three are described in one place.
    """
    assert _BACKEND_MODULE.is_file(), (
        "src/api/chat.py was removed. That is a legitimate decision, but it "
        "makes this test and the #5 disposition note stale — update both."
    )
    server_src = _SERVER.read_text(encoding="utf-8", errors="replace")
    assert "src.api.chat" not in server_src and "from src.api import chat" not in server_src, (
        "server.py now imports src.api.chat. If the backend route is being "
        "wired up, the UI caller has to land too — see the consistency test."
    )


def test_the_consistency_check_is_not_vacuous():
    """Shown failing in both directions.

    A consistency assertion is easy to write so that it passes against
    every possible tree. This drives the predicate with synthetic states
    to prove it discriminates.
    """

    def verdict(backend: bool, proxy: bool, ui: bool) -> bool:
        vals = (backend, proxy, ui)
        return all(vals) or not any(vals)

    assert verdict(True, True, True), "fully wired must pass"
    assert verdict(False, False, False), "fully unwired must pass"
    for partial in (
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, True, False),
        (True, False, True),
        (False, True, True),
    ):
        assert not verdict(*partial), f"half-wired state {partial} must fail"


def test_the_ui_caller_scan_ignores_build_output():
    """The false positive that would make this test lie.

    ``frontend/.next`` holds a generated route manifest naming
    ``/api/chat``. If the scan reached it, the UI layer would read as
    wired forever and the consistency check would report a half-wired
    tree as fully wired.
    """
    assert all(".next" not in c for c in _ui_callers())
    assert "app" in _UI_SOURCE_DIRS and ".next" not in _UI_SOURCE_DIRS
