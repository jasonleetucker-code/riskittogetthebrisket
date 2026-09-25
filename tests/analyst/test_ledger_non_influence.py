"""Structural guard: the analyst ledger may inform intelligence surfaces,
but no canonical-valuation module may import it (C6-ANA-01).

Analyst takes are opinion evidence.  Letting one reach
``rankDerivedValue`` would need its own evidence-gated, owner-approved
methodology (signal independence, freshness, dynasty gating) — this guard
makes that a deliberate change rather than an accidental import.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_CANONICAL_VALUATION = [
    REPO / "src" / "api" / "data_contract.py",
    REPO / "src" / "trade" / "ktc_va.py",
    *sorted((REPO / "src" / "canonical").glob("*.py")),
]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
    return out


def test_canonical_valuation_does_not_import_the_analyst_ledger():
    offenders = {
        str(p.relative_to(REPO)): sorted(m for m in _imports(p) if m.startswith("src.analyst"))
        for p in _CANONICAL_VALUATION
        if p.exists()
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}


def test_guard_actually_scans_files():
    assert any(p.exists() for p in _CANONICAL_VALUATION)
    assert (REPO / "src" / "api" / "data_contract.py").exists()
