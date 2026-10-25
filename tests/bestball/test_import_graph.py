"""Structural guards: offline-only package, no implicit league, no MC probability."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "src" / "bestball"
REPORT = ROOT / "scripts" / "bestball_marginal_report.py"


def _imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def test_no_production_module_imports_bestball():
    candidates = [
        ROOT / "server.py",
        *(ROOT / "src").rglob("*.py"),
        *(ROOT / "scripts").rglob("*.py"),
    ]
    offenders = []
    for path in candidates:
        if PKG in path.parents or path == REPORT:
            continue
        if any(m == "src.bestball" or m.startswith("src.bestball.") for m in _imports(path)):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], offenders


def test_bestball_never_names_a_league_key():
    for path in PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "dynasty_new" not in text, path
        assert "dynasty_main" not in text, path
        assert "load_league_starter_slots" not in text, path
        assert "resolve_starter_slots" not in text, path


def test_no_probability_or_distinguishable_flag_from_mc_error():
    banned_names = re.compile(r"distinguish|significan|p_value|pvalue|z_score|zscore", re.I)
    banned_math = {"NormalDist", "erf", "erfc", "cdf", "norm"}
    for path in PKG.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert not banned_names.search(node.id), (path.name, node.id)
                assert node.id not in banned_math, (path.name, node.id)
            elif isinstance(node, ast.Attribute):
                assert not banned_names.search(node.attr), (path.name, node.attr)
                assert node.attr not in banned_math, (path.name, node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Dict keys / published strings — docstrings may explain the
                # rule, so only short identifier-like strings are checked.
                if re.fullmatch(r"[A-Za-z_]+", node.value):
                    assert not banned_names.search(node.value), (path.name, node.value)


def test_only_competitive_outcome_carries_a_probability_and_it_is_never_from_mc():
    # title_prob_* exists on CompetitiveOutcome for a later simulator path;
    # today championship_delta can only emit None (tests/bestball/test_competitive.py).
    marginal = (PKG / "marginal.py").read_text(encoding="utf-8")
    replacement = (PKG / "replacement.py").read_text(encoding="utf-8")
    assert "prob" not in re.sub(r'""".*?"""', "", marginal, flags=re.S).lower()
    assert "prob" not in re.sub(r'""".*?"""', "", replacement, flags=re.S).lower()
