"""C2-U1 — ONE lineup owner, enforced structurally.

A canonical owner with live competitors is not canonical.  These tests
are the mechanism that keeps that true: they fail when a second
assignment engine, a second eligibility table or a second slot-demand
derivation appears, rather than leaving it to review.

They are deliberately written against SOURCE TEXT, not behaviour.  A
duplicate implementation that happens to agree today is still a second
owner, and behaviour tests cannot see one.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from src.ros import lineup as owner

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
FRONTEND_LIB = REPO / "frontend" / "lib"

#: The one module allowed to implement assignment.
OWNER_PATH = SRC / "ros" / "lineup.py"

#: Both trees, deliberately.  This scan covered ``src/`` alone until
#: 2026-08-24, which left a real hole in the claim it exists to enforce:
#: a second assignment engine, private eligibility table or duplicate
#: slot-demand derivation living under ``scripts/`` was invisible to it.
#: Scripts are production — ``scripts/`` holds the scrape fetchers, the
#: refit pipeline and the verification instruments, and a lineup solved
#: there would be exactly the second owner ``C2-U1`` retired three of.
#: Adding the tree cost nothing: every existing script already passed.
_SCAN_ROOTS = (SRC, SCRIPTS)


def _python_sources() -> list[Path]:
    return [
        p
        for root in _SCAN_ROOTS
        for p in root.rglob("*.py")
        if p != OWNER_PATH and "__pycache__" not in p.parts
    ]


class TestNoSecondAssignmentEngine:
    """The shape of every retired engine was the same: iterate slots,
    claim the best unused eligible player.  Nothing outside the owner may
    contain that loop again."""

    def test_no_module_outside_the_owner_defines_slot_eligibility(self):
        """A private slot→positions table is how a second engine starts.

        Retired: ``team_impact._DEFAULT_FLEX_ELIGIBLE`` /
        ``_DEFAULT_SFLEX_ELIGIBLE`` / ``_DEFAULT_IDP_FLEX_ELIGIBLE``,
        ``intel/roster_shape._FLEX_ELIGIBLE``, and the inline splits in
        ``scoring/replacement_level.starter_slot_counts``,
        ``bdvm/league_config._FLEX_SLOTS`` and
        ``league_intel/config.FLEX_ELIGIBLE`` — the last two found by
        this very test, having been missed by a by-hand census.

        Scoped to slot-ELIGIBILITY tables, deliberately.  A bare list of
        offensive positions ("which players count as offense") is a
        different concept and legitimately lives all over the tree; the
        fingerprint is a *literal* collection of position strings bound
        to a FLEX-named target, which is what a private eligibility table
        looks like and what every retired one was.
        """

        def _literal_positions(node: ast.AST) -> bool:
            """A collection literal made only of position strings."""
            if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                elts = node.elts
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id not in {"frozenset", "set", "tuple", "list"} or not node.args:
                    return False
                return _literal_positions(node.args[0])
            else:
                return False
            if not elts:
                return False
            known = set(owner.POSITION_ORDER)
            return all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value in known
                for e in elts
            )

        offenders: list[str] = []
        for path in _python_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                if not any("FLEX" in n.upper() for n in names):
                    continue
                value = node.value
                if value is None:
                    continue
                hit = _literal_positions(value) or (
                    isinstance(value, ast.Dict) and any(_literal_positions(v) for v in value.values)
                )
                if hit:
                    offenders.append(f"{path.relative_to(REPO)}:{node.lineno}: {names}")
        assert offenders == [], (
            "a slot-eligibility table outside src/ros/lineup.py:\n  " + "\n  ".join(offenders)
        )

    def test_the_owner_is_the_only_module_that_names_augmenting_paths(self):
        """One exact solver.  Two would have to be proven equivalent."""
        callers = [
            p.relative_to(REPO).as_posix()
            for p in _python_sources()
            if "_augment(" in p.read_text(encoding="utf-8")
        ]
        assert callers == []

    def test_every_consumer_imports_the_owner_rather_than_reimplementing(self):
        """The modules that used to hold their own engine now import it.

        Pinned by name so deleting the import to "simplify" is a visible
        failure rather than a silent regression to a local fill.
        """
        expected = {
            "src/trade/team_impact.py",
            "src/bdvm/roster.py",
            "src/intel/roster_shape.py",
            "src/scoring/replacement_level.py",
            "src/api/data_contract.py",
        }
        for rel in sorted(expected):
            text = (REPO / rel).read_text(encoding="utf-8")
            assert (
                "src.ros.lineup" in text or "src.ros import lineup" in text
            ), f"{rel} no longer imports the canonical lineup owner"

    def test_retired_engines_are_gone_not_renamed(self):
        """Retirement means retirement — not renamed, not wrapped, not
        kept behind a flag "for fallback".

        Checked against each module's NAMESPACE, not its text: the
        docstrings deliberately name what they replaced and why, and a
        text scan would force those explanations out of the code.
        """
        import importlib

        gone = {
            "src.trade.team_impact": (
                "_FILL_ORDER",
                "_flex_share",
                "_eligible",
                "_DEFAULT_FLEX_ELIGIBLE",
                "_DEFAULT_SFLEX_ELIGIBLE",
                "_DEFAULT_IDP_FLEX_ELIGIBLE",
            ),
            "src.bdvm.roster": ("_quick_starter_fpg",),
            "src.intel.roster_shape": ("_FLEX_ELIGIBLE",),
        }
        for mod_name, names in gone.items():
            module = importlib.import_module(mod_name)
            for name in names:
                assert not hasattr(module, name), f"{mod_name} still defines {name}"

    def test_there_is_no_greedy_fallback_inside_the_owner(self):
        """NO ``try: exact except: greedy``.  A fallback is a second
        engine that only runs when nobody is looking."""
        src = OWNER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        # Every function on the assignment path, not just the two
        # top-level entry points — naming only those meant a HELPER could
        # carry the fallback instead, which the C2-U1 review flagged.
        # ``load_league_starter_slots`` is the one deliberate exception:
        # its try/except guards a REGISTRY read and degrades to "no
        # slots", which is a refusal, not a heuristic lineup.
        assignment_path = {
            "solve_optimal_assignment",
            "assign_lineup",
            "_augment",
            "_canonicalize_slots",
            "_eligibility_predicate",
            "_objective",
            "_value_with_health_penalty",
            "_eligible_for_slot",
            "_player_eligible_for_slot",
            "slot_eligible_positions",
            "slot_demand",
            "optimize_lineup",
        }
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in assignment_path:
                seen.add(node.name)
                assert not any(isinstance(n, ast.Try) for n in ast.walk(node)), (
                    f"{node.name} contains exception handling — an exact solver has no "
                    "failure mode that a heuristic answer would be the right response to"
                )
        # A renamed or deleted function must not silently drop out of the
        # guard's coverage — a guard that checks nothing passes forever.
        missing = assignment_path - seen
        assert not missing, f"guard names functions that no longer exist: {sorted(missing)}"


class TestFrontendIsNotAnOptimizer:
    """``frontend/lib/starter-slots.js`` renders; it does not decide."""

    @property
    def _js(self) -> str:
        return (FRONTEND_LIB / "starter-slots.js").read_text(encoding="utf-8")

    def test_the_flex_pool_tables_are_gone(self):
        js = self._js
        for gone in ("FLEX_POOLS", "SUPER_FLEX_POOL", "OFFENSE_FLEX", "slotsFromStarterCounts"):
            assert gone not in js, f"starter-slots.js still exports/defines {gone}"

    def test_it_no_longer_sorts_a_pool_by_value(self):
        """The two-pass fill's first act was ``scored.sort(...)``.  A
        materializer has no reason to rank anything."""
        js = self._js
        assert ".sort(" not in js
        assert "valueFor" not in js

    def test_no_other_frontend_module_fills_a_lineup(self):
        offenders = []
        for path in FRONTEND_LIB.rglob("*.js"):
            if path.name == "starter-slots.js":
                continue
            text = path.read_text(encoding="utf-8")
            if "FLEX_POOLS" in text or "SUPER_FLEX_POOL" in text:
                offenders.append(path.relative_to(REPO).as_posix())
        assert offenders == []

    def test_lineup_position_is_held_in_lockstep_with_python(self):
        """``lineupPosition`` survives as a DISPLAY vocabulary, so it is
        a mirror and must be diffed — the same arrangement
        ``test_source_registry_parity.py`` uses for the source registry.
        """
        js = self._js
        families = {}
        for fam, const in (("DL", "DL_FAMILY"), ("LB", "LB_FAMILY"), ("DB", "DB_FAMILY")):
            match = re.search(rf"const {const} = new Set\(\[([^\]]*)\]\)", js)
            assert match, f"{const} not found in starter-slots.js"
            families[fam] = {m.strip().strip("\"'") for m in match.group(1).split(",") if m.strip()}

        for fam, members in families.items():
            for member in members:
                assert owner.lineup_position(member) == fam, (
                    f"JS maps {member} -> {fam}; Python maps it to "
                    f"{owner.lineup_position(member)}"
                )
        # ...and the other direction, so Python cannot grow a family the
        # display vocabulary does not know about.
        for pos, fam in owner._LINEUP_FAMILY.items():
            if fam in families and pos != "K":
                assert pos in families[fam], f"Python maps {pos} -> {fam}; JS does not"


class TestSlotDemandHasOneOwner:
    def test_no_module_re_derives_the_even_split(self):
        """``1/3`` and ``1/4`` over flex-eligible positions was written
        four times.  It is written once."""
        pattern = re.compile(r"1\.0\s*/\s*(3|4)\b|1\s*/\s*len\(eligible\)")
        offenders = []
        for path in _python_sources():
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and "FLEX" in line.upper():
                    offenders.append(f"{path.relative_to(REPO)}:{line_no}")
        assert offenders == []

    def test_the_three_demand_questions_stay_distinct(self):
        """Collapsing them would reintroduce the error LI-5 measured."""
        demand = owner.slot_demand(["QB", "RB", "FLEX", "SUPER_FLEX"])
        assert demand.dedicated == {"QB": 1.0, "RB": 1.0}
        assert demand.flex_capacity == {"FLEX": 1, "SUPER_FLEX": 1}
        assert demand.even_split != demand.dedicated
        assert demand.even_split_is_approximation is True


class TestTheOwnerIsWhatTheDocsSayItIs:
    def test_the_public_surface_is_present(self):
        for name in (
            "assign_lineup",
            "solve_optimal_assignment",
            "resolve_starter_slots",
            "flatten_starter_slots",
            "slot_demand",
            "slot_eligible_positions",
            "player_eligible_for_slot",
            "lineup_position",
            "normalize_slot",
        ):
            assert callable(getattr(owner, name, None)) or getattr(owner, name, None) is not None

    def test_the_objective_carries_no_missing_to_zero_coercion(self):
        """The retired ``float(player.ros_value or 0.0)``.  Pinned on the
        SOURCE because the defect was invisible in the score."""
        src = inspect.getsource(owner._objective)
        assert "or 0.0" not in src
        assert "player.ros_value is None" in src


@pytest.mark.parametrize(
    "rel",
    ["src/trade/team_impact.py", "src/bdvm/roster.py", "src/api/data_contract.py"],
)
def test_no_consumer_reaches_into_the_owners_privates(rel):
    """Consumers use the declared API.  Reaching for ``_``-prefixed
    helpers is how a private table gets copied out and diverges."""
    text = (REPO / rel).read_text(encoding="utf-8")
    for private in ("_eligible_for_slot", "_slot_demand", "_IDP_FAMILIES", "_FLEX_ELIGIBLE"):
        assert f"lineup.{private}" not in text
        assert f"import {private}" not in text
