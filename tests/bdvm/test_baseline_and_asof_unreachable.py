"""The BDVM request path must never gain a path to an un-gated nflverse fetch.

THE TWO REAL, UN-GATED CALL SITES.

Two functions in this codebase call ``src.nfl_data.ingest`` without
``cache_only=True``, and both are legitimate — they are offline/batch code, not
request-serving code:

* ``src/bdvm/baseline.py::fetch_and_build_baseline`` — the reconstructed-baseline
  projection builder. Its only caller repo-wide is
  ``scripts/bdvm_build_baseline.py``, an offline batch script.
* ``src/playerctx/asof.py`` — its own docstring names this: ``_default_fetch_rows``
  calls ``src.bdvm.schedule.fetch_schedule_rows(season)`` with no ``cache_only``
  argument at all, defaulting to ``False``. Its only callers repo-wide are a test
  and ``scripts/backtest_consensus_edge_composite.py``, also offline.

Neither is imported by ``server.py``, ``src/api/bdvm_api.py``, or
``src/bdvm/service.py`` today — confirmed by grep before writing this file. That
is what makes both safe RIGHT NOW. Neither is *structurally prevented* from
becoming reachable — a future change wiring either into the request path (e.g.
"just call the baseline builder as a fallback when the snapshot is stale") would
silently reopen the exact P1 #946 closed, and nothing before this file would
notice.

Same posture as ``test_h_schedule_module_has_no_remote_downloader`` in
``test_request_path_is_local.py``, which pins the ABSENCE of a downloader inside
one module's own source. This pins the absence of an IMPORT of two known-unsafe
modules from the three files that make up the request path — a reachability
guard, not a source-content guard, because the risk here is a future caller
wiring one of these in, not either module regaining a raw downloader of its own.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_REQUEST_PATH_MODULES = {
    "server.py": _REPO_ROOT / "server.py",
    "src/api/bdvm_api.py": _REPO_ROOT / "src" / "api" / "bdvm_api.py",
    "src/bdvm/service.py": _REPO_ROOT / "src" / "bdvm" / "service.py",
}

#: Dotted module paths that must never be imported by a request-path file.
#: Deliberately the MODULE, not one function inside it — importing either
#: module at all is the risk signal, since nothing else in ``baseline.py``
#: or ``asof.py`` needs guarding beyond "don't reach this module from a
#: request handler."
_FORBIDDEN_MODULES = ("src.bdvm.baseline", "src.playerctx.asof")


def _imported_modules(source: str) -> set[str]:
    """Every dotted module path a source file imports, at any nesting depth.

    Local imports (``from src.bdvm.context_store import load_snapshot``
    inside a function body, the idiom this codebase uses throughout
    ``bdvm_api.py``) are only visible via ``ast.walk`` over the WHOLE tree,
    not just top-level statements — a guard scoped to ``tree.body`` would
    miss every import this codebase actually writes.
    """
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            # ``from src.bdvm import baseline`` imports the SUBMODULE by
            # name rather than naming it in ``node.module`` — the module
            # path only appears once the imported name is appended.
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return found


def _forbidden_offenders(source: str) -> list[str]:
    imported = _imported_modules(source)
    offenders = []
    for forbidden in _FORBIDDEN_MODULES:
        for module in imported:
            if module == forbidden or module.startswith(forbidden + "."):
                offenders.append(f"imports {module!r} (forbidden: {forbidden!r})")
    return offenders


@pytest.mark.parametrize("rel_path", sorted(_REQUEST_PATH_MODULES))
def test_request_path_file_does_not_import_the_unsafe_modules(rel_path):
    path = _REQUEST_PATH_MODULES[rel_path]
    offenders = _forbidden_offenders(path.read_text(encoding="utf-8"))
    assert not offenders, (
        f"{rel_path} has gained a path to an un-gated nflverse fetch:\n  "
        + "\n  ".join(offenders)
        + "\nsrc/bdvm/baseline.py and src/playerctx/asof.py call ingest.* "
        "without cache_only=True and must stay offline-only."
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "import src.bdvm.baseline",
        "import src.bdvm.baseline as _b",
        "from src.bdvm import baseline",
        "from src.bdvm.baseline import fetch_and_build_baseline",
        "import src.playerctx.asof",
        "from src.playerctx import asof",
        "from src.playerctx.asof import build_asof_view",
    ],
)
def test_the_guard_is_not_vacuous(mutation):
    """Mutation proof. Each line is a real way either module could become reachable."""
    # A bare statement string is valid top-level source; nesting doesn't matter
    # here since the guard walks the whole tree regardless of depth (proven
    # separately by the request-path files' own local-import style above).
    assert _forbidden_offenders(mutation), (
        f"the guard did not notice {mutation!r} — it would not catch a real " "future import either"
    )


def test_the_guard_does_not_false_positive_on_an_unrelated_import():
    """Control for the mutation test above — the guard must not fire on noise."""
    benign = "\n".join(
        [
            "import src.bdvm.context_store",
            "from src.bdvm import schedule",
            "from src.playerctx import store",
            "import src.bdvm.baselineish",  # a name that only SHARES a prefix
        ]
    )
    assert _forbidden_offenders(benign) == []


def test_prose_naming_the_forbidden_modules_stays_legal():
    """Control for the mutation test above, same idiom as
    ``test_h_prose_about_the_retired_defect_stays_legal`` in
    ``test_request_path_is_local.py``. This file's OWN docstring names both
    forbidden modules by their dotted path — if the guard fired on prose it
    would fail on itself, and every request-path file's comments explaining
    why it does NOT import these would become a trap.
    """
    assert _forbidden_offenders(Path(__file__).read_text(encoding="utf-8")) == []


def test_the_two_call_sites_are_still_where_this_guard_says_they_are():
    """Named-defect check: if either function moves, this file's docstring
    (and the reason the guard names these two modules specifically) goes
    stale silently unless something re-reads them."""
    baseline_src = (_REPO_ROOT / "src" / "bdvm" / "baseline.py").read_text(encoding="utf-8")
    assert "def fetch_and_build_baseline(" in baseline_src

    asof_src = (_REPO_ROOT / "src" / "playerctx" / "asof.py").read_text(encoding="utf-8")
    assert "fetch_schedule_rows(season)" in asof_src
