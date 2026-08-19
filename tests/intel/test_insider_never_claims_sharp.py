"""Insider Trading must never call an ordinary league-mate a "sharp".

The two products sit on the same substrate (``src/intel/ledger.py``) and
share one metrics primitive (``src/intel/signals.py``), which is what makes
the consolidation safe — and also what makes the vocabulary boundary easy to
blur later.

They answer different questions from different evidence bars:

* **Sharp Tracker** — a claim about SKILL, drawn from the global qualified
  cohort. Dynasty only, and only leagues at least two seasons old.
* **Insider Trading** — "what do the managers in MY league do", drawn from
  one league's members. Keeper leagues count, because a keeper league is real
  evidence about a real person you can trade with.

So a manager can be perfectly legitimate Insider Trading evidence and carry
no sharp qualification whatsoever. Presenting ownership from that population
under a "sharp" label would assert a skill claim the source never made — the
exact thing the lane brief forbids ("do not call normal public ownership
'sharp' unless source qualification says it is").

Today that holds by ABSENCE: the insider modules emit no sharp vocabulary at
all. Absence is not a guarantee, so this pins it. The gate asymmetry itself is
pinned separately by ``tests/sharp/test_sharp_gates.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.utils.config_loader import repo_root

#: The modules that build what the Insider Trading surface returns.
INSIDER_MODULES = (
    "src/intel/service.py",
    "src/intel/leads.py",
    "src/intel/lead_service.py",
)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Every string Constant that is a docstring, by object id.

    Docstrings are the one place "sharp" legitimately appears in these
    modules — they explain the boundary this test enforces.
    """
    found: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _emitted_strings(path: Path) -> list[tuple[str, int]]:
    """``(value, lineno)`` for every non-docstring string literal."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_nodes(tree)
    return [
        (node.value, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
    ]


@pytest.mark.parametrize("module", INSIDER_MODULES)
def test_the_insider_surface_emits_no_sharp_vocabulary(module):
    """No field name, label, status or message may say "sharp".

    A comment or docstring may — and does — because explaining the boundary
    is not the same as asserting the claim.
    """
    offenders = [
        (value, lineno)
        for value, lineno in _emitted_strings(repo_root() / module)
        if "sharp" in value.casefold()
    ]
    assert not offenders, (
        f"{module} emits sharp vocabulary at {offenders}. Insider Trading draws on a "
        "population that is NOT qualification-gated for skill (keeper leagues count, "
        "and there is no league-age floor), so labelling it 'sharp' asserts a claim "
        "the evidence does not support."
    )


def test_the_scanner_would_actually_catch_one():
    """Guard against the test passing because the AST walk stopped matching.

    A parametrised scan that silently finds nothing is indistinguishable from
    a clean codebase, which is the failure mode this repo has hit before.
    """
    source = 'x = {"badge": "sharp manager"}\n'
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    values = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip
    ]
    assert any("sharp" in v.casefold() for v in values)


def test_a_docstring_mentioning_sharp_is_not_an_offence():
    """The exclusion has to be real, or the modules could not document why
    the boundary exists."""
    source = '"""Explains Sharp Tracker."""\nx = 1\n'
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    emitted = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip
    ]
    assert not [v for v in emitted if "sharp" in v.casefold()]
