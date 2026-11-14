"""The market board (``/api/data``) never scores realized points.

PR #1938 changes the nflverse realized-points scorer
(``src.nfl_data.realized_points``) and, through it, BDVM's in-season
posterior. Its promotion package claims that the canonical market board is
untouched by that change. These tests are the permanent form of that claim.

What can honestly be asserted:

1. **Static, module level.** The import closure of ``src.api.data_contract``
   does not contain ``src.nfl_data.realized_points`` or ``src.bdvm.actuals``.
   That closure is every top-level ``import`` / ``from ... import`` of a
   ``src`` module, including those inside top-level ``try`` / ``if`` blocks,
   plus the ``__init__`` of every package on the way.
2. **Lazy imports DO reach the scorer module, so "never imported" would be
   false.** Walking the full graph, function-level imports included, finds
   exactly one entry: ``league_registry`` imports the season helper
   ``nfl_projection_season`` from ``src.bdvm.actuals`` inside a function, and
   that module imports ``realized_points`` at top level. That entry is pinned,
   so a new way in is a visible change rather than a silent one.
3. **Behavioural, the real guarantee.** Building the contract from the newest
   complete archived scrape succeeds with every realized-points scoring entry
   point replaced by one that raises:

   * ``_score_stat_line`` (both sources go through it);
   * ``sleeper_stat_line_from_row`` (the nflverse normaliser PR #1938 changes);
   * ``host_stat_line``;
   * ``bdvm.actuals.weekly_points_from_rows``.

   So no part of the build calls them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.archive_fixtures import newest_complete_raw_payload

REPO = Path(__file__).resolve().parents[2]
SCORER_MODULES = ("src.nfl_data.realized_points", "src.bdvm.actuals")


def _module_path(module: str) -> Path | None:
    p = REPO / (module.replace(".", "/") + ".py")
    if p.exists():
        return p
    p = REPO / module.replace(".", "/") / "__init__.py"
    return p if p.exists() else None


def _top_level_src_imports(module: str) -> list[str]:
    path = _module_path(module)
    if path is None:
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for stmt in tree.body:
        # top-level conditional imports run at import time too
        nodes = list(ast.walk(stmt)) if isinstance(stmt, (ast.If, ast.Try)) else [stmt]
        for node in nodes:
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module.startswith("src"):
                    found.append(node.module)
                    found += [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                found += [a.name for a in node.names if a.name.startswith("src")]
    expanded: list[str] = []
    for name in found:
        parts = name.split(".")
        expanded += [".".join(parts[:i]) for i in range(2, len(parts) + 1)]
    return expanded


def _module_level_closure(root: str) -> set[str]:
    seen: set[str] = set()
    stack = [root, root.rsplit(".", 1)[0]]
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        stack.extend(_top_level_src_imports(mod))
    return {m for m in seen if _module_path(m) is not None}


def test_module_level_import_closure_excludes_the_scorer():
    closure = _module_level_closure("src.api.data_contract")
    # Non-vacuous: the walk does find the board's real dependencies.
    assert "src.canonical.player_valuation" in closure
    assert len(closure) > 20
    assert not closure & set(SCORER_MODULES), sorted(closure & set(SCORER_MODULES))


def _all_src_imports(module: str) -> list[tuple[str, list[str]]]:
    """Every ``src`` import in ``module``, function-level (lazy) ones included."""
    tree = ast.parse(_module_path(module).read_text(encoding="utf-8"))
    out: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.startswith("src"):
                out.append((node.module, [a.name for a in node.names]))
        elif isinstance(node, ast.Import):
            out += [(a.name, []) for a in node.names if a.name.startswith("src")]
    return out


def test_every_lazy_entry_into_the_scorer_modules_is_pinned():
    """Walk the board's FULL import graph, lazy imports included, stopping at the
    scorer modules, and pin every import statement that enters one of them.

    Today there is exactly one: ``league_registry`` lazily imports the season
    helper ``nfl_projection_season`` from ``src.bdvm.actuals`` (which imports
    ``realized_points`` at module level).  Importing a module is not calling its
    scorer -- the behavioural test below covers calls -- but a new entry edge
    means a new way in, and it must be looked at rather than slip through.
    """
    seen: set[str] = set()
    stack = ["src.api.data_contract"]
    entries: set[tuple[str, str, tuple[str, ...]]] = set()
    while stack:
        mod = stack.pop()
        if mod in seen or _module_path(mod) is None:
            continue
        seen.add(mod)
        for target_mod, names in _all_src_imports(mod):
            parts = target_mod.split(".")
            targets = [target_mod, *(f"{target_mod}.{n}" for n in names)]
            targets += [".".join(parts[:i]) for i in range(2, len(parts))]
            for target in targets:
                if target in SCORER_MODULES:
                    entries.add((mod, target, tuple(sorted(names))))
                elif target not in seen and _module_path(target) is not None:
                    stack.append(target)
    assert len(seen) > 30  # the walk is not vacuous
    assert entries == {
        ("src.api.league_registry", "src.bdvm.actuals", ("nfl_projection_season",))
    }, sorted(entries)


def test_contract_build_never_calls_realized_points(monkeypatch):
    payload, archive = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape in exports/archive")

    import src.bdvm.actuals as actuals
    import src.nfl_data.realized_points as rp
    from src.api.data_contract import build_api_data_contract

    calls: list[str] = []

    def _forbidden(name: str):
        def _raise(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"the market board called {name}")

        return _raise

    for name in ("_score_stat_line", "sleeper_stat_line_from_row", "host_stat_line"):
        monkeypatch.setattr(rp, name, _forbidden(f"realized_points.{name}"))
    monkeypatch.setattr(
        actuals, "weekly_points_from_rows", _forbidden("actuals.weekly_points_from_rows")
    )

    contract = build_api_data_contract(payload)

    assert calls == [], f"{archive}: {calls}"
    rows = contract.get("playersArray") or []
    assert len(rows) > 500
    assert sum(1 for r in rows if r.get("rankDerivedValue")) > 500
