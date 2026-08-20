"""Structural guard: FAAB Market Heat's trending-velocity metrics are a
measurement tool, not a decision-path input.

Mirrors ``tests/acquisition/test_board_inertness.py``'s pattern (AST-scan
imports rather than trust a docstring). ``src/trade/faab_heat_metrics.py``
and ``scripts/faab_heat_backtest.py`` compute descriptive statistics only —
no coefficient chosen here may ever reach a live recommendation until a
separate, deliberately-scoped, backtest-validated unit promotes it (per
``docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md`` §11 and this
module's own docstring).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: The modules that decide a live FAAB recommendation. If any of them can
#: reach the heat-metrics module, an unvalidated descriptive statistic
#: could silently become a decision input.
_FAAB_DECISION_PATH = (
    "src/trade/faab_engine.py",
    "src/trade/faab_recommender.py",
    "src/trade/faab_contention.py",
    "server.py",
)


def _imported_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_faab_decision_module_imports_the_heat_metrics():
    offenders = []
    for rel in _FAAB_DECISION_PATH:
        path = REPO / rel
        if not path.exists():
            continue
        imported = _imported_modules(path)
        if any(n.startswith("src.trade.faab_heat_metrics") for n in imported):
            offenders.append(rel)
    assert not offenders, (
        f"a FAAB decision module imports the unvalidated heat-metrics module: {offenders}. "
        "Descriptive trending-velocity statistics may not reach a live recommendation "
        "without a separate, backtest-validated promotion."
    )


def test_the_heat_metrics_module_does_not_import_the_faab_engine():
    """The reverse direction should also never happen — a measurement
    tool has no reason to read the thing it might one day inform."""
    path = REPO / "src" / "trade" / "faab_heat_metrics.py"
    imported = _imported_modules(path)
    assert not any(n.startswith("src.trade.faab_engine") for n in imported)
    assert not any(n.startswith("src.trade.faab_recommender") for n in imported)


def test_the_backtest_script_is_not_imported_by_any_decision_module():
    offenders = []
    for rel in _FAAB_DECISION_PATH:
        path = REPO / rel
        if not path.exists():
            continue
        imported = _imported_modules(path)
        if any(n.startswith("scripts.faab_heat_backtest") for n in imported):
            offenders.append(rel)
    assert not offenders, f"a FAAB decision module imports the backtest script: {offenders}"
