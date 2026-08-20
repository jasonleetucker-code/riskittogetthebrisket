"""V1-31 / V1-32 — single-owner discovery guard for Team Strength and
Team Weakness.

The V1-35 audit (`docs/roster-intelligence/V1_35_METRIC_SEPARATION_AUDIT.md`)
measured the census of every production "how good/bad is this roster"
implementation and found the live duplicates were all on the FRONTEND
(F-1 `scoreTeamTiers`, F-3 `/phases`' classifier — both retired). It did
not leave a guard against a NEW duplicate appearing on the BACKEND: a
second module defining its own `TeamStrength` or `TeamWeakness`-shaped
class would be invisible to every existing check, exactly the residual
V1-29's own census guard was found to have (`scripts/replacement_census.py`
before it grew `undeclared_owner_definitions()` — see docs/
VERSION_1_COMPLETION_CONTRACT.md's V1-29 row and PR #987/faa50ba9a).

This mirrors that exact mechanism rather than inventing a new one: an
AST scan over every declared OWNER symbol's name, asserting each is
DEFINED at exactly the one path its owner module declares — regardless
of whether anything calls it, because an undeclared owner is a defect
the moment it is defined, not only once it acquires a caller.

Pure discovery. No CENSUS row, unit or population claim is asserted
here — src/roster_intel/strength.py and weakness.py's own module
docstrings already state what they own and what they deliberately do
NOT merge (portfolio total, ROS production, marginal contribution).
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Every public symbol name the two owners declare, mapped to the ONE
#: path each may be DEFINED at. Read straight off `__all__` in both
#: modules at HEAD, not hand-maintained separately from the code.
OWNER_SYMBOL_PATHS: dict[str, str] = {
    "PositionStrength": "src/roster_intel/strength.py",
    "TeamStrength": "src/roster_intel/strength.py",
    "build_team_strength": "src/roster_intel/strength.py",
    "rank_team_strengths": "src/roster_intel/strength.py",
    "PositionRanks": "src/roster_intel/weakness.py",
    "SlotRung": "src/roster_intel/weakness.py",
    "PositionNeed": "src/roster_intel/weakness.py",
    "TeamWeakness": "src/roster_intel/weakness.py",
    "build_position_ranks": "src/roster_intel/weakness.py",
    "build_team_weakness": "src/roster_intel/weakness.py",
}

#: Same scan roots as scripts/replacement_census.py — src/ + scripts/ +
#: server.py. Tests are excluded deliberately: a symbol only ever
#: defined in its own unit test is not a production duplicate.
SCAN_ROOTS = ("src", "scripts")
SCAN_FILES = ("server.py",)


def _python_files() -> list[pathlib.Path]:
    files = [p for root in SCAN_ROOTS for p in (REPO / root).rglob("*.py")]
    files += [REPO / f for f in SCAN_FILES]
    return [p for p in files if p.exists()]


def definition_sites(names: set[str]) -> dict[str, list[str]]:
    """Every function/method/class DEFINITION named one of ``names``.

    A call-site scan cannot make this check: it has no notion of which
    DEFINITION a call resolves to, so a second module defining its own
    ``TeamStrength`` would satisfy "is this name used somewhere" for
    free (V1-29's exact MR1/MR2 defeat). Checking DEFINITIONS instead
    closes that gap independent of whether anything calls the
    duplicate.
    """
    hits: dict[str, list[str]] = {}
    for path in _python_files():
        rel = str(path.relative_to(REPO))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.name in names:
                hits.setdefault(node.name, []).append(rel)
    return hits


def undeclared_owner_definitions() -> dict[str, list[str]]:
    """OWNER symbol names DEFINED somewhere other than their declared path."""
    sites = definition_sites(set(OWNER_SYMBOL_PATHS))
    violations: dict[str, list[str]] = {}
    for name, paths in sites.items():
        declared_path = OWNER_SYMBOL_PATHS[name]
        stray = sorted(p for p in set(paths) if p != declared_path)
        if stray:
            violations[name] = stray
    return violations


def test_no_owner_symbol_is_defined_outside_its_declared_path():
    """The discovery guard, checked clean at HEAD."""
    assert undeclared_owner_definitions() == {}


def test_the_guard_catches_an_undeclared_second_strength_owner():
    """Positive control, Team Strength side (V1-31).

    A new module defining its own ``TeamStrength`` — the exact class
    name `src/roster_intel/strength.py` declares — must be caught,
    whether or not it is ever imported or called.
    """
    probe = REPO / "src" / "roster_intel" / "_v131_dup_probe.py"
    probe.write_text(
        "class TeamStrength:\n"
        "    def __init__(self, total=0.0):\n"
        "        self.total = total\n",
        encoding="utf-8",
    )
    try:
        dups = undeclared_owner_definitions()
        assert "TeamStrength" in dups, "the guard did NOT detect an undeclared TeamStrength owner"
        assert "src/roster_intel/_v131_dup_probe.py" in dups["TeamStrength"]
    finally:
        probe.unlink(missing_ok=True)


def test_the_guard_catches_an_undeclared_second_weakness_owner():
    """Positive control, Team Weakness side (V1-32)."""
    probe = REPO / "src" / "roster_intel" / "_v132_dup_probe.py"
    probe.write_text(
        "def build_team_weakness(core, ranks, *, team_count):\n"
        "    return None\n",
        encoding="utf-8",
    )
    try:
        dups = undeclared_owner_definitions()
        assert (
            "build_team_weakness" in dups
        ), "the guard did NOT detect an undeclared build_team_weakness owner"
        assert "src/roster_intel/_v132_dup_probe.py" in dups["build_team_weakness"]
    finally:
        probe.unlink(missing_ok=True)


def test_a_docstring_mention_does_not_trip_the_guard():
    """The complementary half: history notes are not definitions.

    ``engine.py``'s own docstring names ``weakness.PositionNeed`` while
    explaining why its own, different quantity was renamed to
    ``PositionDeficit`` — that mention must stay legal, since it is
    prose about the owner, not a second definition of it.
    """
    src = (REPO / "src" / "roster_intel" / "engine.py").read_text(encoding="utf-8")
    assert "PositionNeed" in src, "the fixture is stale — engine.py no longer names it"
    assert undeclared_owner_definitions() == {}


def test_engine_py_renamed_rather_than_redefined_position_need():
    """The specific collision this guard would have caught, had it existed
    when engine.py's own PositionDeficit was still named PositionNeed
    (see engine.py's docstring: "Renamed from PositionNeed (2026-08-19)").
    Pinned so the rename does not silently revert.
    """
    src = (REPO / "src" / "roster_intel" / "engine.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert "PositionNeed" not in defined, "engine.py redefines PositionNeed — collides with weakness.PositionNeed"
    assert "PositionDeficit" in defined
