"""ADR-DFS-012: the only HiGHS call site in the codebase is the pinned solver thread.

Calling ``scipy.optimize.milp`` (HiGHS) from request threads crashed the whole
process with a native access violation.  This test fails when any module under
``src/`` gains a second call site, so a new feature cannot reintroduce the
crash by solving directly from its own thread.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
SOLVER_NAMES = {"milp", "linprog", "Highs", "highspy"}


def _call_sites():
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in SOLVER_NAMES:
                yield path.relative_to(SRC).as_posix(), node.lineno, node.id
            if isinstance(node, ast.Attribute) and node.attr in SOLVER_NAMES:
                yield path.relative_to(SRC).as_posix(), node.lineno, node.attr
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name.split(".")[-1] in SOLVER_NAMES or alias.name == "highspy":
                        yield path.relative_to(SRC).as_posix(), node.lineno, f"import {alias.name}"


def test_highs_is_only_reached_through_the_pinned_solver_pool():
    sites = sorted(_call_sites())
    files = {f for f, _, _ in sites}
    assert files == {"dfs/optimizer.py"}, f"HiGHS referenced outside the solver pool: {sites}"
    tree = ast.parse((SRC / "dfs" / "optimizer.py").read_text(encoding="utf-8"))
    submits = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "submit"
        and isinstance(n.func.value, ast.Call)
        and getattr(n.func.value.func, "id", None) == "_solver_pool"
    ]
    assert [getattr(c.args[0], "id", None) for c in submits] == ["milp"]
    # Every other mention of milp is the lazy import itself — never a direct call.
    direct = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) in SOLVER_NAMES
    ]
    assert direct == [], "milp is called directly instead of through _solver_pool().submit"
