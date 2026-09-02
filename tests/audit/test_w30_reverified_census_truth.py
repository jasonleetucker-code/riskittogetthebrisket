"""Regression guard for W30 rows corrected by the later C10 reachability audit.

The W30 generator predates the re-verification that proved D-112 and D-120 are
intentional retained surfaces.  V1-125 must never regenerate those rows back to
``deprecate`` and then use the result as deletion authority.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "docs/master-site-audit/evidence/W30/build_deadcode_map.py"


def _rows() -> dict[str, tuple[str, ...]]:
    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"))
    rows: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Name) or call.func.id != "add":
            continue
        values = tuple(ast.literal_eval(arg) for arg in call.args)
        rows[values[0]] = values
    return rows


def test_reverified_w30_rows_cannot_regress_to_deprecate() -> None:
    rows = _rows()

    d112 = rows["D-112"]
    assert d112[6] == "retain"
    assert "308 redirect" in d112[4]
    assert "routing-layer" in d112[5]

    d120 = rows["D-120"]
    assert d120[6].startswith("retain")
    assert "test_chat_layers_are_consistently_wired.py" in d120[4]
    assert "guard-tested" in d120[6]
