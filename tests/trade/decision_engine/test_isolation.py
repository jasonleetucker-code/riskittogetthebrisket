"""Batch-1 production safety and package hygiene for the decision engine."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from src.trade import trade_decision

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "src" / "trade" / "decision_engine"
LINEAGE = ROOT / "src" / "evidence_lineage"
NEW_PACKAGES = ("src.trade.decision_engine", "src.evidence_lineage")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


def test_no_production_module_imports_the_new_packages():
    """Library only: /api/trade/analyze and the served decision receipts are
    byte-identical because nothing outside the two packages imports them."""
    offenders = []
    for path in [ROOT / "server.py", *(ROOT / "src").rglob("*.py")]:
        if PKG in path.parents or LINEAGE in path.parents:
            continue
        if any(m.startswith(NEW_PACKAGES) for m in _imports(path)):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_engine_imports_no_sibling_li_package_io_or_league_resolution():
    allowed_src = {
        "src.trade.decision_engine",
        "src.evidence_lineage",
        "src.valuation_math",
    }
    for path in PKG.glob("*.py"):
        for mod in _imports(path):
            if mod.startswith("src"):
                assert any(mod == a or mod.startswith(a + ".") for a in allowed_src), (
                    path.name,
                    mod,
                )
            assert not mod.startswith(("requests", "httpx", "sqlite3", "urllib", "socket"))


def test_no_headline_string_under_the_engine():
    headlines = list(trade_decision.HEADLINE_TEXT.values())
    for path in [*PKG.glob("*.py"), *LINEAGE.glob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert not any(h in text for h in headlines), path.name


def test_no_probability_or_aggregate_utility_in_the_package():
    banned = re.compile(
        r"P\(advantage|probability_of_advantage|aggregate_utility|expected_utility|norm\.cdf|erf\("
    )
    for path in PKG.glob("*.py"):
        assert not banned.search(path.read_text(encoding="utf-8")), path.name


def test_no_league_identity_is_referenced():
    # A pure library: no leagueKey resolution, so dynasty_new (or any league)
    # can never be selected implicitly.
    for path in [*PKG.glob("*.py"), *LINEAGE.glob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert "dynasty_new" not in text and "dynasty_main" not in text
        assert "league_registry" not in text and "leagueKey" not in text
