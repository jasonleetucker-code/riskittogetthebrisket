"""V1-36 / C3-PKG-01 — single-owner discovery guard for package-generation MECHANICS.

Scope, and why it is drawn this way: the market-value trade-recommendation
surfaces (``src/trade/``, ``src/roster_intel/``) are ONE domain sharing ONE
canonical asset-value scale (``rankDerivedValue``), and it is that domain
this guard protects — a second combinatorial two-sided-package enumerator
appearing anywhere in it, other than the one documented exception below,
is the exact defect class C3-PKG-01 exists to prevent.

Current census (2026-08-22), performed fresh rather than trusted from the
manifest:

* ``src/trade/finder.py`` and ``src/trade/angle.py`` call the owner's own
  ``enumerate_packages`` / ``enumerate_sides`` directly — consolidated.
* ``src/roster_intel/packages.py::generate_packages`` is a DIFFERENT,
  documented, deliberately-separate staged Pareto-frontier search (its own
  ``max_candidates_per_stage`` budget, no ``itertools.combinations``, no
  topology-bound check) — it imports only the owner's identity primitives
  (``PackageAsset``, ``package_key``) plus the shared ``src.trade.constraints``
  outgoing-constraint owner. Allowlisted by name below, not exempted from
  scanning silently.
* ``src/trade/suggestions.py``'s four ``_generate_*`` functions are
  needs-driven heuristic searches (weakest-starter, sweetener-widening,
  tightest-gap dedup) with hardcoded 1-for-1 / 2-for-1 shapes — no
  ``itertools.combinations``, no explicit topology-bound comparison.
* ``src/bdvm/roster.py`` also builds ``itertools.combinations``-based 2-sided
  trade shapes (``find_double_positive_trades``), but it is BDVM's
  fundamental-value double-positive scan — a second, INDEPENDENT value
  concept by explicit design (see ``CLAUDE.md``'s BDVM section). Out of this
  guard's scope by directory (``src/bdvm/``), not by a silently broadened
  allowlist.

──────────────────────────────────────────────────────────────────────
Why this is AST-based and not a regex (PR #1088 follow-up, 2026-08-24)
──────────────────────────────────────────────────────────────────────
The original detector was ``re.compile(r"abs\\([^)]*\\)\\s*<=\\s*\\d")``
co-occurring with the literal text ``combinations(``. That is a
false-negative guard, and the measured escape set is larger than the
audit that prompted this reported. Probed directly:

===========================================  ===========
form                                          old regex
===========================================  ===========
``abs(send_n - recv_n) <= 1``                 MATCH
``d = len(a) - len(b)`` … ``abs(d) <= 1``     MATCH
``abs(len(send) - len(receive)) <= 1``        **MISS**
``abs(send_n - recv_n) <= MAX_DIFF``          **MISS**
``d = len(a) - len(b)`` … ``abs(d) <= MAX``   **MISS**
``abs(player_count(s) - player_count(r))<=1`` **MISS**
===========================================  ===========

Two corrections this table forces, both recorded rather than smoothed
over, because acting on the wrong mechanism would have produced a guard
that still missed the real cases:

1. **Local-variable aliasing alone does NOT evade the old regex** — row
   2 matches. What evades is a ``)`` inside the ``abs(...)`` argument
   (``[^)]*`` stops at the first one) or a non-digit bound. The
   canonical spelling ``abs(len(send) - len(receive)) <= 1`` fails on
   BOTH counts, and ``player_count`` is *the owner's own API name*, so
   the tidiest reimplementation was the least detectable.
2. **``suggestions.py`` was not escaping through this hole.** It
   contains no ``combinations(`` at all, so the co-occurrence AND can
   never fire there, and every one of its ``abs()`` sites compares
   VALUES (``abs(p.display_value - gap_needed) < FAIRNESS_TOLERANCE``,
   where ``gap_needed = target.display_value - ws_ev``) rather than
   player counts. A value-proximity band is not a topology bound.

That second point is what makes the discriminator below the load-bearing
part of this design. **Topology compares COUNTS; value proximity
compares VALUES.** Keying on the syntax ``abs(x - y) <= k`` alone would
flag roughly a dozen legitimate sweetener/fairness bands in
``suggestions.py`` and turn a false-negative guard into a false-positive
one. So an ``abs`` difference is only topology when both operands are
COUNT-LIKE — ``len(...)``, ``player_count(...)``, ``.count(...)``, or a
counting ``sum(1 for ...)`` — resolved through simple local assignment
aliases. Everything else is left alone.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MECHANICS_OWNER = "src/packages/construction.py"
_SCAN_ROOTS = ("src/trade", "src/roster_intel")
#: Documented, deliberately-separate generators — not exemptions from being
#: scanned, exemptions from being COUNTED as a mechanics duplicate.
_KNOWN_SEPARATE_GENERATORS = frozenset({"src/roster_intel/packages.py"})

#: Enumeration primitives. Broader than the retired literal ``combinations(``
#: so that swapping in a sibling itertools helper is not a way out.
_ENUMERATION_NAMES = frozenset({"combinations", "permutations", "product"})

#: Calls whose RESULT is a count. This is the whole false-positive defence:
#: a difference of two of these is a topology bound, a difference of two
#: values is not.
_COUNTING_CALLS = frozenset({"len", "player_count", "count"})

#: Fallback for a name the alias map cannot resolve — a function PARAMETER
#: (``def topo(send_n, recv_n)``) or a value assigned in another module.
#: Without it, ``abs(send_n - recv_n) <= 1`` escapes, which is the plainest
#: spelling of all and one the retired regex DID catch; a replacement that
#: regressed on it would be no upgrade.
#:
#: Deliberately narrow, and checked against the real value vocabulary rather
#: than assumed safe: none of ``gap_needed``, ``sp_ev``, ``surplus_tol``,
#: ``combined``, ``display_value`` or ``gap`` is count-shaped, so the live
#: value bands in ``suggestions.py`` stay unflagged. Resolution ALWAYS wins
#: over this heuristic — it only applies to names nothing else can explain.
_COUNT_SHAPED_NAME_PARTS = ("count", "_num", "num_", "_len", "len_", "size")


def _is_count_shaped_name(name: str) -> bool:
    low = name.lower()
    if low == "n" or low.startswith("n_") or low.endswith("_n"):
        return True
    return any(part in low for part in _COUNT_SHAPED_NAME_PARTS)


#: Comparison operators that express a bound.
_BOUND_OPS = (ast.LtE, ast.Lt)


def _call_name(node: ast.AST) -> str | None:
    """``f(...)`` -> ``"f"``; ``mod.f(...)`` -> ``"f"``; else ``None``."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _uses_enumeration(tree: ast.AST) -> bool:
    return any(_call_name(n) in _ENUMERATION_NAMES for n in ast.walk(tree))


def _alias_map(tree: ast.AST) -> dict[str, ast.AST]:
    """``name -> assigned expression`` for simple single-target assignments.

    Deliberately flat and module-wide rather than scope-exact: this guard
    only needs to see through ``d = len(a) - len(b)`` before a later
    ``abs(d) <= 1``. A name assigned more than once maps to the LAST
    assignment seen, which is enough to follow the alias without pretending
    to do real dataflow. Being approximate here is safe in one direction
    only, and it is the right one: a missed alias makes the guard no worse
    than the regex it replaces, while the count-likeness requirement keeps
    an over-eager resolution from inventing a topology bound.
    """
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                out[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                out[node.target.id] = node.value
    return out


def _is_count_like(node: ast.AST, aliases: dict[str, ast.AST], depth: int = 0) -> bool:
    """Does this expression evaluate to a COUNT of assets?

    Recognised: ``len(...)`` / ``player_count(...)`` / ``x.count(...)``, a
    counting ``sum(1 for ...)``, and any local name that resolves (through
    ``aliases``) to one of those. ``depth`` bounds alias chasing so a
    self-referential assignment cannot loop.
    """
    if depth > 4:
        return False
    if isinstance(node, ast.Call):
        name = _call_name(node)
        if name in _COUNTING_CALLS:
            return True
        # ``sum(1 for a in side if ...)`` — the counting idiom the owner's
        # own ``player_count`` uses internally.
        if name == "sum" and node.args:
            arg = node.args[0]
            if isinstance(arg, (ast.GeneratorExp, ast.ListComp)):
                elt = arg.elt
                if isinstance(elt, ast.Constant) and elt.value == 1:
                    return True
        return False
    if isinstance(node, ast.Name):
        resolved = aliases.get(node.id)
        if resolved is not None:
            return _is_count_like(resolved, aliases, depth + 1)
        return _is_count_shaped_name(node.id)
    return False


def _is_count_difference(node: ast.AST, aliases: dict[str, ast.AST], depth: int = 0) -> bool:
    """``<count> - <count>``, possibly reached through an alias."""
    if depth > 4:
        return False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
        return _is_count_like(node.left, aliases) and _is_count_like(node.right, aliases)
    if isinstance(node, ast.Name):
        resolved = aliases.get(node.id)
        if resolved is not None:
            return _is_count_difference(resolved, aliases, depth + 1)
    return False


def _has_topology_bound(tree: ast.AST) -> bool:
    """``abs(<count> - <count>) <op> <bound>`` anywhere in the module.

    The BOUND is deliberately unconstrained — a digit, a named constant, an
    attribute, anything. Requiring a literal digit is what let
    ``<= MAX_PLAYER_COUNT_DIFFERENCE`` walk straight past the old regex.
    """
    aliases = _alias_map(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not node.ops:
            continue
        if not isinstance(node.ops[0], _BOUND_OPS):
            continue
        left = node.left
        if _call_name(left) != "abs" or not getattr(left, "args", None):
            continue
        if _is_count_difference(left.args[0], aliases):
            return True
    return False


def _find_mechanics_offenders() -> list[str]:
    """Modules that both ENUMERATE combinations and enforce a player-count
    TOPOLOGY bound — the owner's own signature
    (``enumerate_packages``/``enumerate_sides`` + ``topology_is_allowed`` /
    ``MAX_PLAYER_COUNT_DIFFERENCE``).

    Module-level co-occurrence, not per-function: the owner itself splits
    enumeration and the bound across two functions in one file, so a
    per-function AND would miss the owner's own pattern, and a
    reimplementation is no less a duplicate for structuring itself the same
    tidy way.
    """
    offenders: list[str] = []
    for root in _SCAN_ROOTS:
        for path in sorted((_REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel == _MECHANICS_OWNER or rel in _KNOWN_SEPARATE_GENERATORS:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - a broken file is another gate's problem
                continue
            if _uses_enumeration(tree) and _has_topology_bound(tree):
                offenders.append(rel)
    return offenders


def test_there_is_exactly_one_package_mechanics_owner():
    offenders = _find_mechanics_offenders()
    assert not offenders, (
        f"second package-generation mechanics implementation found outside "
        f"{_MECHANICS_OWNER}: {offenders} — route through "
        f"src.packages.enumerate_packages / enumerate_sides instead, or add "
        f"a documented exception to _KNOWN_SEPARATE_GENERATORS with a reason"
    )


def test_the_guard_is_not_vacuous_against_the_owner_itself():
    """The owner file DOES carry the scanned-for signature — proving the
    detector can find a positive rather than passing because it matches
    nothing anywhere."""
    tree = ast.parse((_REPO_ROOT / _MECHANICS_OWNER).read_text(encoding="utf-8"))
    assert _uses_enumeration(tree), "detector no longer sees the owner's enumeration"
    assert _has_topology_bound(tree), "detector no longer sees the owner's topology bound"


# ── The escape set the retired regex missed (PR #1088 follow-up) ──────
#
# Each case is the SAME semantic rule — "the two sides may differ by at
# most N players" — spelled a different legal way. All must be caught.

_TOPOLOGY_FORMS = {
    "direct_digit_bound": "if abs(send_n - recv_n) <= 1: pass",
    "canonical_len_form": "if abs(len(send) - len(receive)) <= 1: pass",
    "named_constant_bound": "if abs(len(a) - len(b)) <= MAX_PLAYER_COUNT_DIFFERENCE: pass",
    "aliased_digit_bound": "d = len(a) - len(b)\nif abs(d) <= 1: pass",
    "aliased_named_bound": "d = len(a) - len(b)\nif abs(d) <= MAX_DIFF: pass",
    "player_count_helper": "if abs(player_count(s) - player_count(r)) <= 1: pass",
    "counting_sum_form": (
        "if abs(sum(1 for x in s if not x.is_pick) - sum(1 for y in r if not y.is_pick)) <= 1:\n"
        "    pass"
    ),
    "alias_of_whole_difference": "gap = len(a) - len(b)\nspread = gap\nif abs(spread) <= 1: pass",
}

#: Real value-proximity code from ``suggestions.py`` and friends. Same
#: ``abs(x - y) < k`` SHAPE, entirely different meaning — none may be
#: flagged, or this guard becomes unusable in the file it is meant to
#: protect.
_VALUE_PROXIMITY_FORMS = {
    "sweetener_band": "if abs(p.display_value - gap_needed) < FAIRNESS_TOLERANCE: pass",
    "precomputed_value_gap": (
        "gap_needed = target.display_value - ws_ev\n"
        "if abs(sp_ev - gap_needed) < surplus_tol: pass"
    ),
    "same_tier_swap": "if abs(g.display_value - r.display_value) < 500: pass",
    "fairness_band": "if abs(gap) < FAIRNESS_TOLERANCE: pass",
    "closest_target_sort": "targets.sort(key=lambda t: abs(combined - t.display_value))",
    "overpay_ratio": "if abs(s.gap) / s.give_total <= CONSOLIDATION_MAX_OVERPAY_RATIO: pass",
}


def test_every_topology_spelling_is_detected():
    """The escape set, closed. ``canonical_len_form``, ``named_constant_bound``,
    ``aliased_named_bound``, ``player_count_helper`` and ``counting_sum_form``
    all walked past the retired regex."""
    missed = [
        name for name, src in _TOPOLOGY_FORMS.items() if not _has_topology_bound(ast.parse(src))
    ]
    assert not missed, f"topology spellings not detected: {missed}"


def test_value_proximity_is_never_mistaken_for_topology():
    """The false-positive census. These are legitimate product bands, not
    package mechanics, and a guard that flags them would be worse than the
    one it replaces."""
    flagged = [
        name for name, src in _VALUE_PROXIMITY_FORMS.items() if _has_topology_bound(ast.parse(src))
    ]
    assert not flagged, f"value-proximity logic wrongly flagged as topology: {flagged}"


def test_enumeration_alone_is_not_an_offence():
    """Both halves are required. A module that enumerates without bounding
    topology is not a second mechanics owner (that is
    ``roster_intel/packages.py``'s shape), and a topology bound with no
    enumeration is not either."""
    enumerate_only = ast.parse("import itertools\nfor c in itertools.combinations(xs, 2): pass")
    assert _uses_enumeration(enumerate_only)
    assert not _has_topology_bound(enumerate_only)

    bound_only = ast.parse("if abs(len(a) - len(b)) <= 1: pass")
    assert not _uses_enumeration(bound_only)
    assert _has_topology_bound(bound_only)


def test_the_live_suggestions_module_is_clean_for_the_stated_reason():
    """Pins WHY ``suggestions.py`` passes, so a future reader does not
    conclude the guard is simply blind to it. It passes because it has no
    enumeration primitive at all AND no count-difference bound — not
    because its value bands slipped through."""
    tree = ast.parse((_REPO_ROOT / "src/trade/suggestions.py").read_text(encoding="utf-8"))
    assert not _uses_enumeration(tree), "suggestions.py gained an enumeration primitive"
    assert not _has_topology_bound(tree), "suggestions.py gained a player-count topology bound"
