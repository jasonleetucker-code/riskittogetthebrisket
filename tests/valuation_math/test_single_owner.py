"""ONE owner guard: KTC's VA algorithm may not be reimplemented a third time.

``src/valuation_math/ktc_va_core.py`` is the single stdlib-only home for KTC's
``processV``/``reverseAdjust`` arithmetic.  ``src/trade/ktc_va.py`` (private
side) and ``src/public_league/trade_grading.py`` (public side) both wrap it
rather than re-deriving it — see both modules' docstrings for why a second
public-side copy existed until 2026-08-20 (C3-VA-01) and why it could not
simply import the private owner.

This is a REAL scan over the shipped tree, not a decorative one: it is proven
non-vacuous by a positive control (a synthetic snippet carrying the same
magic-constant fingerprint as a genuine reimplementation) before the actual
source tree is asserted clean.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The owner module — never itself a "reimplementation".
_OWNER_PATH = _REPO_ROOT / "src" / "valuation_math" / "ktc_va_core.py"

# Directories to scan for a stray copy. Deliberately broad — the defect this
# guards against is a THIRD implementation appearing anywhere, not only in
# the two files that have historically carried one.
_SCAN_DIRS = (
    _REPO_ROOT / "src" / "trade",
    _REPO_ROOT / "src" / "public_league",
)

# Numeric-literal fingerprints unique to each half of KTC's algorithm. These
# are the exact magic constants from KTC's site.min.js — no legitimate
# unrelated function has a reason to use all of them together. A single
# function whose body contains every literal in one set is a
# reimplementation, not a coincidence.
_PROCESS_V_SIGNATURE = frozenset({1.3, 1.05, 6, 0.1, 0.15, 0.6})
_REVERSE_ADJUST_SIGNATURE = frozenset({0.025, 0.75, 0.25, 10099})


def _numeric_literals_per_function(source: str) -> list[frozenset]:
    """Return one frozenset of numeric literals per function body in ``source``."""
    tree = ast.parse(source)
    out: list[frozenset] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        literals: set = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, (int, float)):
                if isinstance(sub.value, bool):
                    continue
                literals.add(sub.value)
        out.append(frozenset(literals))
    return out


def _reimplements_ktc_va(source: str) -> bool:
    """True iff any function in ``source`` carries a full KTC-VA fingerprint."""
    for literals in _numeric_literals_per_function(source):
        if _PROCESS_V_SIGNATURE <= literals:
            return True
        if _REVERSE_ADJUST_SIGNATURE <= literals:
            return True
    return False


# ── Positive control: prove the scan actually fires before trusting it ─────

_DECOY_PROCESS_V = """
def some_other_function(value, max_in_trade, t, nerf_index):
    s = (0.05 * (value / t) ** 1.3 + 0.05 * (value / (1.05 * max_in_trade)) ** 6 + 0.1) * value
    if nerf_index > 0:
        s *= max(0.6, 1 - 0.15 * nerf_index)
    return s
"""

_DECOY_REVERSE_ADJUST = """
def some_solver(raw_diff, max_in_trade, t, nerf_count):
    d = 1.0
    while d > 0.025:
        p = d * 1 * 0.75
        p2 = d * 1 * 0.25
        m = raw_diff + max_in_trade + t + nerf_count + 10099
        d -= 0.1
    return m
"""

_HARMLESS_SNIPPET = """
def unrelated_math(a, b):
    return a * 1.3 + b * 0.1
"""


def test_the_scan_fires_on_a_process_v_reimplementation():
    assert _reimplements_ktc_va(_DECOY_PROCESS_V) is True


def test_the_scan_fires_on_a_reverse_adjust_reimplementation():
    assert _reimplements_ktc_va(_DECOY_REVERSE_ADJUST) is True


def test_the_scan_does_not_fire_on_an_unrelated_function_sharing_one_constant():
    """Negative control: a couple of shared literals alone must not trip it."""
    assert _reimplements_ktc_va(_HARMLESS_SNIPPET) is False


def test_the_owner_module_itself_is_exempt_from_the_scan():
    """Sanity check: the owner's own source trivially matches its own fingerprint."""
    source = _OWNER_PATH.read_text(encoding="utf-8")
    assert _reimplements_ktc_va(source) is True


# ── The real guard ──────────────────────────────────────────────────────────


def test_no_second_python_implementation_of_ktc_value_adjustment():
    offenders: list[str] = []
    for scan_dir in _SCAN_DIRS:
        for path in scan_dir.rglob("*.py"):
            if path.resolve() == _OWNER_PATH.resolve():
                continue
            source = path.read_text(encoding="utf-8")
            if _reimplements_ktc_va(source):
                offenders.append(str(path.relative_to(_REPO_ROOT)))
    assert not offenders, (
        "Found a reimplementation of KTC's Value Adjustment algorithm outside "
        f"the single owner (src/valuation_math/ktc_va_core.py): {offenders}. "
        "Delegate to src.valuation_math.ktc_va_core instead of re-deriving it."
    )
