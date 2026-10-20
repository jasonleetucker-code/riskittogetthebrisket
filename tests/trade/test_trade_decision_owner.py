"""TC-C / owner decision 5 -- exactly ONE module emits the top-line trade decision.

* The four headline texts exist in the backend only in
  ``src/trade/trade_decision.py``; no other backend module builds them.
* The frontend never constructs them either: it renders
  ``analysis.decision.headlineText`` verbatim (the ``buildRows`` rule).
* The retired ``teamImpact.verdict`` is gone from the producer, the War Room
  evidence and every frontend reader.
* The decision owner is pure: it imports no I/O, engine or mutation module.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from src.trade import trade_decision

ROOT = Path(__file__).resolve().parents[2]
HEADLINES = list(trade_decision.HEADLINE_TEXT.values())
OWNER = ROOT / "src" / "trade" / "trade_decision.py"


def _py_files():
    yield ROOT / "server.py"
    yield from (ROOT / "src").rglob("*.py")


def _frontend_files():
    for sub in ("app", "components", "lib"):
        for p in (ROOT / "frontend" / sub).rglob("*"):
            if p.suffix in (".js", ".jsx", ".ts", ".tsx") and "node_modules" not in p.parts:
                yield p


def test_only_the_owner_holds_the_headline_texts_in_the_backend():
    holders = sorted(
        str(p.relative_to(ROOT))
        for p in _py_files()
        if p != OWNER and any(h in p.read_text(encoding="utf-8") for h in HEADLINES)
    )
    assert holders == []
    owner = OWNER.read_text(encoding="utf-8")
    assert all(h in owner for h in HEADLINES)


def test_the_frontend_renders_the_headline_and_never_builds_it():
    builders = sorted(
        str(p.relative_to(ROOT))
        for p in _frontend_files()
        if any(h in p.read_text(encoding="utf-8") for h in HEADLINES)
    )
    assert builders == []
    room = (ROOT / "frontend/components/trade/TradeWarRoom.jsx").read_text(encoding="utf-8")
    assert "decision.headlineText" in room


def test_analyze_trade_takes_its_headline_from_the_owner():
    tree = ast.parse((ROOT / "src/trade/analyze_trade.py").read_text(encoding="utf-8"))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "decide"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "trade_decision"
    ]
    assert len(calls) == 1


def test_team_impact_verdict_stays_retired():
    team_impact = (ROOT / "src/trade/team_impact.py").read_text(encoding="utf-8")
    assert '"verdict":' not in team_impact and '"compositeScore":' not in team_impact
    owner = OWNER.read_text(encoding="utf-8")
    assert "teamImpact" not in owner.split('"""', 2)[2]  # not read below the docstring
    readers = sorted(
        str(p.relative_to(ROOT))
        for p in _frontend_files()
        if re.search(r"\bti\.verdict\b|teamImpact\??\.verdict\b", p.read_text(encoding="utf-8"))
    )
    assert readers == []


def test_the_owner_is_pure():
    tree = ast.parse(OWNER.read_text(encoding="utf-8"))
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imported.add(n.module or "")
    # Pure stdlib (hashing / serialising its own receipt) + the valuation-math
    # owners.  No I/O, engine, store or network module.
    # ``src.trade.team_verdicts`` (the per-team projections) stays allowed
    # but is no longer imported here: the public alias that reached it was
    # deleted with the PUBLIC section (fairness-only amendment, Lane C).  It
    # is itself pure — pinned below.
    assert imported <= {
        "__future__",
        "typing",
        "hashlib",
        "json",
        "src.valuation_math",
        "src.trade.team_verdicts",
    }
    verdicts = ast.parse((OWNER.parent / "team_verdicts.py").read_text(encoding="utf-8"))
    v_imported = set()
    for n in ast.walk(verdicts):
        if isinstance(n, ast.Import):
            v_imported |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            v_imported.add(n.module or "")
    assert v_imported <= {"__future__", "types", "typing", "src.trade", "src.valuation_math"}
