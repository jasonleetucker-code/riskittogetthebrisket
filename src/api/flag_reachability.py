"""Structural reachability: which route a feature flag's gate actually reaches.

Audit **F-26** found a feature-flag comment naming the wrong endpoint
(``/api/gameplan`` instead of the route the gate genuinely reaches,
``/api/valuation/league-adjusted``).  The repair was correct, but nothing
in the test suite could have caught the *original* defect: the existing
guards compare a docstring's ON/OFF claim against ``_DEFAULTS``
(:mod:`tests.league_intel.test_flag_docs_match_reality`) or check that a
named route is registered somewhere in the app
(:func:`scripts.verify_lane4_production._registered_routes_static`).
Neither links the flag to a SPECIFIC route through the code that actually
reads it.  Reintroducing F-26's exact defect — renaming the endpoint back
to ``/api/gameplan`` in the comment — leaves every existing guard green.

This module closes that gap by tracing, structurally, in one direction:

    flag name
      -> every ``is_enabled("<flag>")`` call site (the gate)
      -> that call's enclosing function
      -> every function that calls it, transitively, up to a bounded depth
      -> any FastAPI route handler reached along the way, and its path(s)

and, independently, extracting what the flag's own comment block in
``_DEFAULTS`` claims via any ``/api/...`` token — so the test that uses
both can assert the claim is actually reachable rather than merely
present somewhere in the source tree.

Name-based, not import-resolved.  Two functions sharing a bare name would
over-approximate reachability (a caller of "the wrong" same-named
function looks like a caller of the right one) but never under-approximate
it, so a real reachable route is never missed — the failure mode this
guard exists to catch is a route named that is NOT reachable, and
over-approximation cannot hide that.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_HTTP_VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH"}

_ENDPOINT_TOKEN = re.compile(r"/api/[A-Za-z0-9/_-]+")
# The convention this file already uses for "this is the answer, not
# just a mention": ``**`/api/...`**``. A comment explaining a past
# defect (F-26's own block does exactly this) legitimately mentions the
# WRONG endpoint in plain prose while stating the real one in bold --
# so when any bold-marked mention exists, it is authoritative and
# unmarked mentions are historical color, not a second claim.
_BOLD_ENDPOINT_TOKEN = re.compile(r"\*\*`(/api/[A-Za-z0-9/_-]+)`\*\*")

# Bounded so a runaway or accidental cycle in the name-based caller graph
# cannot hang the test; every real chain in this codebase (gate ->
# private resolver -> module-level assembler -> route handler) is 2-3
# hops deep.
_MAX_HOPS = 6


def _iter_source_files() -> list[Path]:
    return [REPO_ROOT / "server.py", *sorted((REPO_ROOT / "src").rglob("*.py"))]


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _called_names(node: ast.AST) -> set[str]:
    """Every function-shaped name this subtree touches -- called OR referenced.

    Deliberately broader than "names directly invoked as ``Call.func``":
    this codebase routes several sync functions to a thread pool with
    ``await run_in_threadpool(_gameplan.get_league_adjusted_values, ...)``,
    where the target is passed as a plain argument, never itself the
    ``func`` of a ``Call`` node. Restricting this to call sites produced a
    real false negative -- the route handler that reaches
    ``get_league_adjusted_values`` this way was invisible to the BFS.
    Capturing every ``Name``/``Attribute`` load is a safe over-approximation
    for reachability (see the module docstring): it can only ADD edges,
    never hide the one this guard exists to find.
    """
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
    return names


def _route_paths(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    paths: set[str] = set()
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
            continue
        if dec.func.attr.upper() not in _HTTP_VERBS:
            continue
        if (
            dec.args
            and isinstance(dec.args[0], ast.Constant)
            and isinstance(dec.args[0].value, str)
        ):
            paths.add(dec.args[0].value)
    return paths


class _FunctionIndex:
    """Every top-level-reachable function/method in the tree, with its calls and route paths."""

    def __init__(self) -> None:
        # (module_path, qualname) -> set of names it calls
        self.calls: dict[tuple[str, str], set[str]] = {}
        # name -> set of (module_path, qualname) defining a function with that name
        self.by_name: dict[str, set[tuple[str, str]]] = {}
        # (module_path, qualname) -> set of route paths, if it's a route handler
        self.routes: dict[tuple[str, str], set[str]] = {}
        # (module_path, qualname) -> True if a gate for some flag lives directly in its body
        self.gate_flags: dict[tuple[str, str], set[str]] = {}

    def index(self, path: Path, tree: ast.Module) -> None:
        module = str(path.relative_to(REPO_ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = (module, node.name)
            self.calls.setdefault(key, set()).update(_called_names(node))
            self.by_name.setdefault(node.name, set()).add(key)
            route_paths = _route_paths(node)
            if route_paths:
                self.routes.setdefault(key, set()).update(route_paths)
            for gate_node in ast.walk(node):
                if not isinstance(gate_node, ast.Call):
                    continue
                func = gate_node.func
                func_name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else (func.attr if isinstance(func, ast.Attribute) else None)
                )
                if func_name != "is_enabled":
                    continue
                if (
                    gate_node.args
                    and isinstance(gate_node.args[0], ast.Constant)
                    and isinstance(gate_node.args[0].value, str)
                ):
                    self.gate_flags.setdefault(key, set()).add(gate_node.args[0].value)


def _build_index() -> _FunctionIndex:
    index = _FunctionIndex()
    for path in _iter_source_files():
        tree = _parse(path)
        if tree is not None:
            index.index(path, tree)
    return index


def reachable_routes_for_flag(flag: str, index: _FunctionIndex | None = None) -> set[str]:
    """Every route path reachable from ``is_enabled(flag)`` via the caller graph.

    BFS over "who calls this function name", starting at every function
    whose body contains the gate for ``flag`` directly, up to
    :data:`_MAX_HOPS`. Any visited function that is a registered route
    handler contributes its path(s) to the result.
    """
    idx = index or _build_index()

    start_nodes = {key for key, flags in idx.gate_flags.items() if flag in flags}
    visited: set[tuple[str, str]] = set()
    frontier: set[tuple[str, str]] = set(start_nodes)
    found_routes: set[str] = set()

    for _ in range(_MAX_HOPS):
        if not frontier:
            break
        next_frontier: set[tuple[str, str]] = set()
        for node_key in frontier:
            if node_key in visited:
                continue
            visited.add(node_key)
            found_routes.update(idx.routes.get(node_key, set()))
            _module, funcname = node_key
            # Who calls a function named `funcname`? Name-based, so this
            # over-approximates rather than under-approximates -- see the
            # module docstring for why that direction is safe here.
            for caller_key, called_names in idx.calls.items():
                if caller_key in visited:
                    continue
                if funcname in called_names:
                    next_frontier.add(caller_key)
        frontier = next_frontier

    return found_routes


def documented_endpoints(flag: str, feature_flags_source: str | None = None) -> set[str]:
    """``/api/...`` tokens in the comment block immediately above ``"<flag>":`` in ``_DEFAULTS``.

    Walks upward from the flag's dict-entry line collecting contiguous
    ``#``-comment lines (this codebase writes long prose blocks directly
    above each entry, with no blank-line separator from the previous
    entry), stopping at the first non-comment line -- the previous flag's
    entry, or the dict's opening line for the first flag.
    """
    if feature_flags_source is None:
        feature_flags_source = (REPO_ROOT / "src" / "api" / "feature_flags.py").read_text(
            encoding="utf-8"
        )
    lines = feature_flags_source.splitlines()
    entry_pattern = re.compile(r'^\s*"' + re.escape(flag) + r'"\s*:')
    entry_idx = next((i for i, line in enumerate(lines) if entry_pattern.match(line)), None)
    if entry_idx is None:
        return set()

    block: list[str] = []
    i = entry_idx - 1
    while i >= 0 and lines[i].strip().startswith("#"):
        block.append(lines[i])
        i -= 1
    block.reverse()
    text = "\n".join(block)
    bold = set(_BOLD_ENDPOINT_TOKEN.findall(text))
    if bold:
        return bold
    return set(_ENDPOINT_TOKEN.findall(text))
